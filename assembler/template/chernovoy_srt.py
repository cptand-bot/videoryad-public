#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЧЕРНОВОЙ SRT ПО ТЕКСТУ — ЧТОБЫ НЕ СТОЯТЬ В ОЧЕРЕДИ ЗА ГОЛОСОМ (08.11.2026).

Повод: вечером 08.11 сервис озвучки перестал принимать соединения, и все темы
дня встали «готовыми к озвучке». Вкладка `usuario-47` заметила главное: SRT
нужен раскадровке ТОЛЬКО ради тайминга, а тайминг своего текста считается без
всякого сервиса — по скорости чтения.

ПОЧЕМУ ЭТО НЕ ГАДАНИЕ. Скорость диктора постоянна и МЕРЯЕТСЯ ПО НАШИМ ЖЕ
СДАННЫМ РОЛИКАМ: берём пары «текст + srt» по дереву НОВОСТИ и считаем знаки в
секунду. Замер 08.11 по 34 парам: медиана 15,90 зн/с, разброс 14,98…16,70.
И он РАЗНЫЙ ПО КАНАЛАМ — ПЛАНЕТА ~15,2, «5 МИНУТ» ~16,0, ПЕРЕВОД ~16,6, —
поэтому скорость берётся по каналу, а общая медиана только запасной вариант.
Оценка самой `ozvuchka.py` («12:55» на 10 858 знаках = 14,0 зн/с) завышает
длительность примерно на минуту — на неё не опираемся.

    python3 chernovoy_srt.py <текст.txt> [--out <файл.srt>] [--скорость 15.9]
    python3 chernovoy_srt.py --замер          # показать замер по всем роликам

ЧТО ПОТОМ. Когда придёт НАСТОЯЩАЯ озвучка, тайминг пересобирается по ней:
    accept_scenes.py <сцены.json> --srt <настоящий.srt> --fix --out <...>
Содержание сцен при этом не теряется: текст тот же, меняются только секунды.
Черновой файл кладём рядом с пометкой `.chernovoy.srt`, чтобы его нельзя было
спутать с настоящим и случайно отправить в сборку.
"""

import argparse
import glob
import os
import re
import sys

ДЕРЕВО = os.environ.get("NEWS_ROOT", "/mnt/d/YouTube/НОВОСТИ")
ОБЩАЯ = 15.9                      # медиана по 34 парам, замер 08.11
СЛУЖЕБНЫЕ = ("ЗАДАНИЕ", "БРИФ", "ОТВЕТ", "ПРОМПТ", "УПАКОВКА", "РЕРАЙТ",
             "ГЕОРАДАР", "АУДИТ", "ДОСЬЕ", "ЧИСТО", "ПОДРЕЗАН")


def читать(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", "replace")


def длина_srt(path):
    """Последняя метка времени — это и есть длительность озвучки."""
    t = читать(path)
    м = re.findall(r"-->\s*(\d\d):(\d\d):(\d\d)[,.](\d\d\d)", t)
    if not м:
        return 0.0
    h, mi, s, ms = м[-1]
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000.0


def пары(root=ДЕРЕВО):
    """Готовые пары «текст + srt» из сданных роликов — на них и меряем."""
    out = []
    for srt in glob.glob(os.path.join(root, "*/НОЯБРЬ/*/*/*.srt")) + \
            glob.glob(os.path.join(root, "*/*/*/*.srt")):
        d = os.path.dirname(srt)
        тексты = [f for f in glob.glob(os.path.join(d, "*.txt"))
                  if not any(s in os.path.basename(f).upper() for s in СЛУЖЕБНЫЕ)]
        if not тексты:
            continue
        txt = max(тексты, key=os.path.getsize)
        n = len(читать(txt).strip())
        dur = длина_srt(srt)
        if dur > 60 and n > 2000:
            канал = ""
            for часть in os.path.abspath(d).split(os.sep):
                if часть.upper() in ("ПЛАНЕТА", "5 МИНУТ", "ОЛЬГА ДАЙДЖЕСТ",
                                     "ДИПЛОМАТИЯ СИЛЫ") or часть.upper().startswith("ПЕРЕВОД"):
                    канал = часть.upper()
            try:
                когда = os.path.getmtime(srt)
            except OSError:
                когда = 0
            out.append((n / dur, канал, d, когда))
    return out


def канал_из_пути(путь):
    """Канал — сегмент дерева НОВОСТИ. Пусто, если такого сегмента нет."""
    найден = ""
    for часть in os.path.abspath(путь or ".").split(os.sep):
        if часть.upper() in ("ПЛАНЕТА", "5 МИНУТ", "ОЛЬГА ДАЙДЖЕСТ",
                             "ДИПЛОМАТИЯ СИЛЫ") or часть.upper().startswith("ПЕРЕВОД"):
            найден = часть.upper()
    return найден


def скорость(канал="", root=ДЕРЕВО, свежих=5):
    """Знаков в секунду: медиана ПОСЛЕДНИХ роликов канала.

    СЧИТАЕМ ТОЛЬКО СВЕЖЕЕ (08.11). Голос канала меняется: на ПЕРЕВОДЕ он
    завёл новый шаблон, и тот читает 13,3 зн/с против 16,6 у прежнего —
    разница почти четверть, то есть две минуты на ролике. Старые замеры
    того же канала сделаны ДРУГИМ голосом и тянут оценку в прошлое,
    поэтому берём последние по времени и медиану уже среди них.
    """
    зам = пары(root)
    свои = sorted([(t, v) for v, ch, _d, t in зам
                   if канал and ch == канал.upper()], reverse=True)
    если = [v for _t, v in свои[:свежих]]
    if not если:
        если = sorted([v for v, _ch, _d, _t in зам])
    if not если:
        return ОБЩАЯ, 0
    # ПРИ ОДНОМ-ДВУХ ЗАМЕРАХ БЕРЁМ САМЫЙ СВЕЖИЙ, А НЕ МЕДИАНУ: медиана из
    # двух — это больший, то есть ровно старый голос, от которого мы и
    # уходим. Медиана осмысленна, когда роликов канала хотя бы три.
    if свои and len(если) <= 2:
        return свои[0][1], len(свои[:свежих])
    если = sorted(если)
    return если[len(если) // 2], len(свои[:свежих]) if свои else 0


def фразы(текст):
    """Режем на фразы так же, как слышит ухо: по точкам и длинным паузам."""
    чистый = re.sub(r"\s+", " ", текст.replace("\r", " ")).strip()
    куски = re.split(r"(?<=[.!?…])\s+", чистый)
    out = []
    for к in куски:
        к = к.strip()
        if not к:
            continue
        # длинную фразу делим по запятой, чтобы строка не висела 12 секунд
        while len(к) > 220:
            р = к.rfind(",", 80, 200)
            р = р if р > 0 else 200
            out.append(к[:р + 1].strip())
            к = к[р + 1:].strip()
        if к:
            out.append(к)
    return out


def время(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def собрать(текст, зн_в_сек):
    ф = фразы(текст)
    блоки, t = [], 0.0
    for i, x in enumerate(ф, 1):
        d = max(1.2, len(x) / зн_в_сек)
        блоки.append("%d\n%s --> %s\n%s\n" % (i, время(t), время(t + d), x))
        t += d
    return "\n".join(блоки), t, len(ф)


def main():
    ap = argparse.ArgumentParser(description="черновой srt по тексту, без сервиса озвучки")
    ap.add_argument("text", nargs="?", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--скорость", type=float, default=0, dest="speed")
    ap.add_argument("--замер", action="store_true", dest="measure")
    ap.add_argument("--канал", default="", dest="kanal",
                    help="канал явно — когда текст лежит в папке проекта, "
                         "а не в дереве НОВОСТИ")
    a = ap.parse_args()

    if a.measure:
        зам = пары()
        по_каналам = {}
        for v, ch, _d, _t in зам:
            по_каналам.setdefault(ch or "(канал не определён)", []).append(v)
        print("пар «текст+srt» найдено: %d" % len(зам))
        for ch, vs in sorted(по_каналам.items()):
            vs.sort()
            print("  %-26s замеров %2d · медиана %.2f зн/с · %.2f…%.2f"
                  % (ch, len(vs), vs[len(vs) // 2], vs[0], vs[-1]))
        return 0

    if not a.text or not os.path.isfile(a.text):
        sys.exit("нужен файл текста (или --замер)")

    канал = (a.kanal or "").strip().upper()
    if not канал:
        канал = канал_из_пути(os.path.abspath(a.text))
    if not канал:
        # ТЕКСТ ЛЕЖИТ В ПАПКЕ ПРОЕКТА, А НЕ В ДЕРЕВЕ «НОВОСТИ» (11.11, улов
        # вкладки `usuario-45`). Канал определялся ТОЛЬКО по пути файла, а
        # вкладка зовёт инструмент на копии в `~/projects/<проект>` — канал
        # «не определён», скорость берётся общей медианой (15,96 зн/с) вместо
        # канальной (у ПЕРЕВОДА ~16,6), и черновой тайминг уезжает на ~20 с
        # за 13 минут. Смотрим метку проекта и исходную папку темы.
        pdir = os.path.dirname(os.path.abspath(a.text)) or "."
        for имя in (".kanal", ".channel"):
            try:
                with open(os.path.join(pdir, имя), encoding="utf-8") as f:
                    канал = f.read().strip().upper()
                if канал:
                    break
            except OSError:
                continue
        if not канал:
            try:
                with open(os.path.join(pdir, ".source_dir"), encoding="utf-8") as f:
                    канал = канал_из_пути(f.read().strip())
            except OSError:
                pass
    v, n = (a.speed, 0) if a.speed else скорость(канал)
    текст = читать(a.text).strip()
    srt, длит, кол = собрать(текст, v)

    out = a.out or os.path.splitext(a.text)[0] + ".chernovoy.srt"
    open(out, "w", encoding="utf-8").write(srt)
    print("канал: %s" % (канал or "не определён"))
    print("скорость: %.2f зн/с%s" % (v, (" (медиана по %d роликам канала)" % n) if n else ""))
    print("текст %d знаков → %d фраз, %d:%02d звучания"
          % (len(текст), кол, int(длит // 60), int(длит % 60)))
    print("сцен при норме 11,5 с: ~%d" % round(длит / 11.5))
    print("готово: %s" % out)
    print("")
    print("ЭТО ЧЕРНОВИК. Он годится ТОЛЬКО для раскадровки, пока нет голоса.")
    print("Придёт настоящая озвучка — пересобрать тайминг по ней:")
    print("  accept_scenes.py <сцены.json> --srt <настоящий.srt> --fix --out <...>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
