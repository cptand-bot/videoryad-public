#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""narration_in.py — забрать озвучку из ПРИВАТНОГО хранилища на раннер.

Зачем (09.11, закрытие утечки; путь ВЫКЛЮЧЕН по умолчанию, см. ship.sh).
Озвучка ехала в облако файлом в `queue/<ролик>` и оставалась в истории
ПУБЛИЧНОГО репозитория навсегда. Замерено живьём: после уборки очереди
`narration.mp3` на 12,1 МБ скачивался АНОНИМНО по SHA старого коммита, а
`git push --force` этого не лечит — оторванный блоб так же отдаётся и
по API, и через `raw.githubusercontent.com`, и обычным `git fetch <sha>`.

Входом запуска озвучка поехать не может: предел входов `workflow_dispatch`
65 535 символов, а 12 МБ mp3 в base64 это ~16,5 МБ, то есть в 250 раз
больше (gzip не помогает, mp3 уже сжат).

Поэтому: в очередь едет только УКАЗАТЕЛЬ `narration.ptr` (тег релиза и имя
ассета), а сам файл лежит ассетом релиза в ПРИВАТНОМ репозитории-хранилище.
Раннер забирает его по токену из секрета `NARRATION_STORE_TOKEN`. В публичной
истории не остаётся ни байта звука.

ТОКЕНУ НУЖЕН ТОЛЬКО ДОСТУП НА ЧТЕНИЕ. Этот скрипт делает ровно два запроса
GET (найти релиз по тегу, скачать ассет) и не пишет в хранилище ничего.
Заливает звук `ship.sh` — но он работает под ЖИВЫМ входом вкладки в `gh`, а
не под этим токеном, и удаляет релиз после забора тоже `get.sh` под тем же
входом. Поэтому в секреты публичной цели кладётся мелкозернистый токен на
ОДИН репозиторий с правом Contents: Read — больше ему не нужно ничего.

АДРЕС ХРАНИЛИЩА В УКАЗАТЕЛЬ НЕ ПИШЕТСЯ: указатель уезжает в публичный
репозиторий и в ассет релиза `*-project.tgz`, то есть имя приватного репо
стало бы известно наружу. Адрес приходит с ЦЕЛИ — переменной окружения
`NARRATION_STORE_REPO` (секрет или variable репозитория). В указателе он
допускается только как осознанное переопределение.

Токен берётся ТОЛЬКО из переменной окружения и никуда не печатается:
Actions печатает текст шага в лог, а логи публичного репозитория открыты
всем. По той же причине адрес скачивания не логируется целиком.

Использование (на раннере):
    NARRATION_STORE_TOKEN=<токен> python3 narration_in.py <папка задания>

Коды возврата:
    0 — озвучка на месте, или указателя нет вовсе (старый путь, не наше
        дело), или путь осознанно выключен;
    1 — указатель ЕСТЬ, но забрать не удалось. Это именно ошибка: молча
        продолжать нельзя, иначе готовый файл на полтысячи мегабайт
        приедет НЕМЫМ, а правок после сборки не бывает.
"""
import json
import os
import sys
import urllib.error
import urllib.request

PTR = "narration.ptr"
API = "https://api.github.com"
EXTS = (".mp3", ".wav", ".m4a")


def _req(url, token, accept):
    r = urllib.request.Request(url)
    r.add_header("Authorization", "Bearer %s" % token)
    r.add_header("Accept", accept)
    r.add_header("X-GitHub-Api-Version", "2022-11-28")
    return r


def have_voice(proj):
    """Озвучка уже в папке — так работает вкладка со СТАРЫМ ship.sh. Этот
    путь намеренно оставлен рабочим: раскатка кода и обновление вкладок не
    одномоментны, ломать идущие ролики нельзя."""
    for ext in EXTS:
        p = os.path.join(proj, "narration" + ext)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
    return ""


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    proj = argv[0]

    already = have_voice(proj)
    if already:
        print("озвучка: файл уже в задании (старый путь), %d байт"
              % os.path.getsize(already))
        return 0

    ptr_path = os.path.join(proj, PTR)
    if not os.path.isfile(ptr_path):
        print("озвучка: указателя нет — путь приватного хранилища не задействован")
        return 0

    try:
        with open(ptr_path, encoding="utf-8") as f:
            ptr = json.load(f)
        tag = str(ptr["tag"])            # тег релиза = имя ролика
        asset = str(ptr["asset"])        # narration.mp3 / .wav / .m4a
    except (OSError, ValueError, KeyError) as e:
        print("озвучка: указатель %s не читается (%s)" % (PTR, type(e).__name__))
        return 1

    # адрес хранилища — с ЦЕЛИ, не из указателя (см. шапку)
    repo = os.environ.get("NARRATION_STORE_REPO", "") or str(ptr.get("repo", ""))
    if "/" not in repo:
        print("озвучка: указатель есть, а адрес хранилища на цели не задан")
        print("         (нет NARRATION_STORE_REPO) — забрать неоткуда.")
        return 1

    if os.path.splitext(asset)[1].lower() not in EXTS:
        print("озвучка: в указателе чужое расширение (%s) — не беру" % asset)
        return 1

    token = os.environ.get("NARRATION_STORE_TOKEN", "")
    if not token:
        print("озвучка: указатель есть, а секрета NARRATION_STORE_TOKEN на цели")
        print("         НЕТ — забрать нечем. Положи секрет или собирай старым путём.")
        return 1

    # 1. найти релиз по тегу и в нём нужный ассет
    try:
        with urllib.request.urlopen(
                _req("%s/repos/%s/releases/tags/%s" % (API, repo, tag),
                     token, "application/vnd.github+json"), timeout=60) as r:
            rel = json.load(r)
    except (urllib.error.URLError, ValueError) as e:
        code = getattr(e, "code", "?")
        print("озвучка: релиз %s в хранилище не открылся (HTTP %s). Проверь, что"
              % (tag, code))
        print("         токен даёт Contents:Read на этот приватный репозиторий.")
        return 1

    aid = size = None
    for a in rel.get("assets", []):
        if a.get("name") == asset:
            aid, size = a.get("id"), a.get("size")
            break
    if aid is None:
        print("озвучка: в релизе %s нет ассета %s (есть: %s)"
              % (tag, asset, ", ".join(a.get("name", "?")
                                       for a in rel.get("assets", [])) or "ничего"))
        return 1

    # 2. скачать. Поток, а не в память: файл 12-18 МБ, и держать его целиком
    #    незачем.
    dest = os.path.join(proj, asset)
    try:
        with urllib.request.urlopen(
                _req("%s/repos/%s/releases/assets/%s" % (API, repo, aid),
                     token, "application/octet-stream"), timeout=600) as r, \
                open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        print("озвучка: скачивание не удалось (%s)" % type(e).__name__)
        return 1

    # 3. ПРОВЕРЯЕМ РЕЗУЛЬТАТОМ, А НЕ НАЛИЧИЕМ ФАЙЛА: обрыв на середине даёт
    #    файл-огрызок, с которым ролик приедет с обрезанным голосом, и видно
    #    это станет только в готовом видео.
    got = os.path.getsize(dest)
    if size and got != size:
        os.remove(dest)
        print("озвучка: скачалось %d байт из %d — огрызок, файл не оставляю"
              % (got, size))
        return 1
    print("озвучка: взята из приватного хранилища, %d байт" % got)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
