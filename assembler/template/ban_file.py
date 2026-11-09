#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Blacklist a file so future news-video builds don't use it again — for a
library shot (or a re-hosted web photo) that keeps recurring and just looks
stale/overused, independent of the normal 3-video cooldown.

Default is permanent. Pass --days N to make it time-limited instead — the
file becomes usable again once N days have passed (2026-09-23: "не совсем
убивать... через 10 дней только его использовать").

Usage:
    python3 ban_file.py <path-to-file> "причина" [--days N]
    python3 ban_file.py --md5 <hash> "причина" [--days N]      # file already gone
    python3 ban_file.py <файл> [<файл> ...] --why "причина"     # пачкой
    python3 ban_file.py --md5 <hash> [<hash> ...] --why "причина"

ПРИЧИНА ОБЯЗАТЕЛЬНА. Её можно передать позиционно (вторым аргументом) или
ключом --why / --причина / --prichina / --reason. Без причины скрипт НЕ
банит и объясняет, каким ключом её передать.

<path-to-file> can be anything: a file under ~/projects/media-library/,
a project's images/scene_NNN.* or overlays/scene_NNN.*, or any other local
copy — matching is always by md5 content hash, never by path, so this also
catches a re-downloaded or renamed copy of the same photo.

Writes to ~/projects/media-library/.banned_md5.json, read by
fetch_assets_news.py's load_blocked_md5() (blocks a local_library pick)
and _accept() (blocks a press_photo/pexels/wikimedia download that happens
to match). Takes effect on the next fetch — does not touch anything
already placed in an open project's images/ or overlays/. A --days entry
stops being enforced automatically once it expires (checked by date, no
cleanup step needed).
"""
import os
import sys

# ИМПОРТ НЕ ДОЛЖЕН ЗАВИСЕТЬ ОТ ТОГО, ОТКУДА ЗАПУСТИЛИ (2026-10-18, улов usuario-42).
# С 17.10 `fetch_assets_news.py` в папку ролика НЕ копируется (запускается из
# template), а `ban_file.py` в списке копируемых остался — и копия в папке
# проекта падала с ModuleNotFoundError. Коварно тем, что цикл по девяти файлам
# отработал «успешно» и напечатал девять трейсбеков подряд: на бегу читается
# как «забанено», а не забанено ничего.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from fetch_assets_news import ban_md5, file_md5
except ImportError:                      # устаревшая копия рядом с проектом
    _tpl = os.path.expanduser("~/.claude/skills/news-video/template")
    if _tpl not in sys.path:
        sys.path.insert(0, _tpl)
    from fetch_assets_news import ban_md5, file_md5


# ПРИЧИНУ ПРИНИМАЕМ ЛЮБЫМ ИЗ ЭТИХ ИМЁН (09.11, улов на осмотре медиатеки).
# Живой случай: агент банил 21 файл базы и честно передавал причину ключом
# `--why` — которого у скрипта не было. Разбор позиционный, поэтому слово
# «--why» уехало в поле `reason` как ТЕКСТ ПРИЧИНЫ (15 записей с причиной
# «--why»), а у остальных причина осталась пустой. Ни одна строка не упала,
# бан прошёл, вкладка увидела «забанено» — и 21 кадр лёг в журнал
# безымянным. Дорого это тем, что причина бана — единственное, что потом
# отличает «вшитое клеймо стокового сайта» (навсегда) от «коллизия, рефетч»
# (на два дня): без неё запись нельзя ни проверить, ни снять.
# Поэтому: имена-синонимы ниже + отказ без причины (см. `_need_reason`).
REASON_KEYS = ("--why", "--причина", "--prichina", "--reason", "--why-ru")


def _take_days(argv):
    """Pull --days N out of argv in place, return (argv, days|None)."""
    if "--days" in argv:
        i = argv.index("--days")
        if i + 1 >= len(argv):
            print(__doc__)
            raise SystemExit(1)
        try:
            days = int(argv[i + 1])
        except ValueError:
            print(__doc__)
            raise SystemExit(1)
        del argv[i:i + 2]
        return argv, days
    return argv, None


def _take_reason(argv):
    """Вынуть причину, переданную КЛЮЧОМ, вернуть (argv, причина|None).

    None значит «ключа не было» — это не то же самое, что пустая строка
    (её штатно передаёт кнопка 🚫 дашборда: там причина пишется в журнал
    отказов отдельно, и ломать кнопку отказом нельзя).
    """
    for key in REASON_KEYS:
        if key in argv:
            i = argv.index(key)
            if i + 1 >= len(argv):
                print("ключ %s без текста причины — напиши её в кавычках: "
                      "%s \"вшитое клеймо в углу\"" % (key, key),
                      file=sys.stderr)
                raise SystemExit(2)
            reason = argv[i + 1]
            del argv[i:i + 2]
            return argv, reason
    return argv, None


def _need_reason(what):
    """Причины нет вовсе — не банить молча, а объяснить, каким ключом её дать."""
    print("ПРИЧИНА НЕ ПЕРЕДАНА — ничего не забанено (%s).\n"
          "Причина бана это единственное, что потом отличает «вшитое клеймо "
          "стокового сайта» (навсегда) от «коллизия, рефетч» (на два дня), "
          "поэтому безымянные баны больше не принимаются.\n"
          "Передай её вторым аргументом или ключом --why:\n"
          "    python3 ban_file.py <файл> \"титры во весь кадр\"\n"
          "    python3 ban_file.py <файл> [<файл> ...] --why \"титры во весь кадр\"\n"
          "    python3 ban_file.py --md5 <hash> --why \"клеймо телеканала\"\n"
          "Синонимы ключа: %s" % (what, ", ".join(REASON_KEYS)),
          file=sys.stderr)
    raise SystemExit(2)


# ПУСТАЯ ПРИЧИНА ОТ КНОПКИ ДАШБОРДА — НЕ ОТКАЗ, НО И НЕ ПУСТОЕ ПОЛЕ (09.11).
# `review.py` зовёт нас как `ban_file.py <файл> <причина>`, где причина бывает
# пустой строкой (пользователь снял кадр, не комментируя — это разрешено,
# дашборд пишет снятие с запросом в журнал отказов сам). Отказ там означал бы
# 500 на кнопку 🚫, то есть сломанный дашборд. Поэтому слот есть — работаем,
# но в журнал кладём опознаваемый текст, а не пустоту.
BLANK_REASON = "причина не названа (снято без текста)"


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        raise SystemExit(1)
    argv, days = _take_days(argv)
    argv, reason_kw = _take_reason(argv)
    until_msg = f"на {days} дн." if days else "навсегда"

    if argv and argv[0] == "--md5":
        hashes = [h for h in argv[1:] if h]
        if not hashes:
            print(__doc__)
            raise SystemExit(1)
        if reason_kw is None:
            # Старый разбор: <hash> ["причина"]. Хэшей больше одного здесь
            # быть не может — иначе второй уехал бы в причину, как 09.11.
            if len(hashes) > 2:
                print("лишние аргументы: %s. Нескольким хэшам причину "
                      "передавай ключом --why \"причина\"."
                      % ", ".join(hashes[2:]), file=sys.stderr)
                raise SystemExit(2)
            if len(hashes) < 2:
                _need_reason("md5 %s" % hashes[0])
            hashes, reason = hashes[:1], hashes[1]
        else:
            reason = reason_kw
        reason = reason if reason.strip() else BLANK_REASON
        for md5 in hashes:
            # ОТЧЁТ ПО ФАКТУ, А НЕ ПО НАМЕРЕНИЮ (09.11): `ban_md5` отказывает
            # понизить вечный бан до срочного, и печатать «забанено на 2 дн.»
            # после отказа значило бы врать вызывающему рефетчу.
            if ban_md5(md5, path="", reason=reason, days=days):
                print(f"забанено {until_msg} (md5 {md5}): {reason}")
            else:
                print(f"НЕ записано (md5 {md5}): остался прежний бан")
        return

    if reason_kw is None:
        # Старый разбор: <файл> ["причина"].
        if len(argv) > 2:
            print("лишние аргументы: %s. Пачку файлов бань так:\n"
                  "    python3 ban_file.py <файл> [<файл> ...] --why \"причина\""
                  % ", ".join(argv[2:]), file=sys.stderr)
            raise SystemExit(2)
        if len(argv) < 2:
            _need_reason(argv[0])
        paths, reason = argv[:1], argv[1]
    else:
        paths, reason = argv, reason_kw
    if not paths:
        print(__doc__)
        raise SystemExit(1)
    reason = reason if reason.strip() else BLANK_REASON

    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        # ФАЙЛА НЕТ — ЭТО ОТКАЗ, А НЕ ТРЕЙСБЕК В СЕРЕДИНЕ ПАЧКИ: иначе
        # половина списка забанена, половина нет, и вкладка этого не видит.
        print("нет файла(ов): %s\nЕсли файл уже удалён, бань по хэшу: "
              "ban_file.py --md5 <hash> --why \"причина\""
              % ", ".join(missing), file=sys.stderr)
        raise SystemExit(2)

    for path in paths:
        md5 = file_md5(path)
        if ban_md5(md5, path=path, reason=reason, days=days):
            print(f"забанено {until_msg}: {path}  (md5 {md5})  {reason}")
        else:
            print(f"НЕ записано: {path}  (md5 {md5}) — остался прежний бан")
    _siblings_hint(paths[-1])


def _siblings_hint(path):
    """Забанен файл ИЗ МЕДИАТЕКИ — назови соседей по папке (02.11).

    Почему: кадры в папку базы приезжают ПАЧКОЙ из одного источника, и порок
    у них общий. Живой счёт на ролике НПЗ: в папке
    `БАЗА/ВЛАСТЬ-РОССИЯ/ГАЗОВАЯ-КОМПРЕССОРНАЯ-СТАНЦИЯ` замощённое клеймо
    «Magnific» оказалось на файлах 07, 08 и 09 из девяти — треть папки, — и
    раздача по кругу, наткнувшись на забаненный 08, честно выдала СОСЕДНИЙ
    09, то есть следующий кадр той же пачки с тем же клеймом.
    Автоматом этот знак не ловится: проверено на живых файлах, его не берёт
    ни OCR (ни по кадру, ни по усиленному высокочастотному остатку), ни
    поиск периодичности по спектру — у забракованных кадров те же числа, что
    у годных. Значит остаётся глаз, и дешевле посмотреть пачку ОДИН раз, чем
    натыкаться на неё по одному кадру в каждом следующем ролике.
    """
    try:
        d = os.path.dirname(os.path.abspath(path))
        if "media-library" not in d.replace("\\", "/"):
            return
        sib = sorted(f for f in os.listdir(d)
                     if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                     and f != os.path.basename(path))
        if not sib:
            return
        print("  ЭТО ФАЙЛ МЕДИАТЕКИ. Кадры приезжают в папку ПАЧКОЙ из одного "
              "источника, и порок у них общий — посмотри соседей сразу, "
              "целиком, а не по одному в каждом следующем ролике:")
        print("    %s" % d)
        print("    %s" % ", ".join(sib[:20]))
        print("  Лист папки одной командой: python3 %s \"%s\"" % (
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "folder_sheet.py"),
            os.sep.join(d.replace("\\", "/").split("/")[-2:])))
    except OSError:
        pass


if __name__ == "__main__":
    main()
