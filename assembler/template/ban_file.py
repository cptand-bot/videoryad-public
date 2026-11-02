#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Blacklist a file so future news-video builds don't use it again — for a
library shot (or a re-hosted web photo) that keeps recurring and just looks
stale/overused, independent of the normal 3-video cooldown.

Default is permanent. Pass --days N to make it time-limited instead — the
file becomes usable again once N days have passed (2026-09-23: "не совсем
убивать... через 10 дней только его использовать").

Usage:
    python3 ban_file.py <path-to-file> ["причина"] [--days N]
    python3 ban_file.py --md5 <hash> ["причина"] [--days N]   # file already gone

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


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        raise SystemExit(1)
    argv, days = _take_days(argv)
    until_msg = f"на {days} дн." if days else "навсегда"

    if argv[0] == "--md5":
        if len(argv) < 2:
            print(__doc__)
            raise SystemExit(1)
        md5 = argv[1]
        reason = argv[2] if len(argv) > 2 else ""
        ban_md5(md5, path="", reason=reason, days=days)
        print(f"забанено {until_msg} (md5 {md5}): {reason or '(без причины)'}")
        return
    path = argv[0]
    reason = argv[1] if len(argv) > 1 else ""
    md5 = file_md5(path)
    ban_md5(md5, path=path, reason=reason, days=days)
    print(f"забанено {until_msg}: {path}  (md5 {md5})  {reason or '(без причины)'}")
    _siblings_hint(path)


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
