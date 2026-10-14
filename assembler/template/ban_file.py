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
import sys

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


if __name__ == "__main__":
    main()
