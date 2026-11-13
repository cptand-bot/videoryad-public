# -*- coding: utf-8 -*-
"""ПЕРЕСЧЁТ ОТПЕЧАТКОВ ПО УЖЕ ЗАБАНЕННЫМ КАДРАМ — разово (2026-11-13).

Бан-лист `.banned_md5.json` знает 3302 файла, но только по md5. Чтобы
забаненный КАДР не возвращался пережатой копией (его претензия 13.11),
каждому забаненному файлу, который ещё лежит на диске, нужно посчитать
перцептивный отпечаток и положить в `.banned_phash.json`. Остальные
добавятся сами при следующем бане.

Ищет забаненные файлы двумя путями: по `path` из самой записи (у клипов
медиатеки там абсолютный путь) и обходом папок кадров проектов
(у кадров с дашборда там только `images/scene_NNN.jpg` — без имени проекта,
поэтому опознаём по md5).

  python3 phash_backfill.py                 # сухой прогон: сколько найдётся
  python3 phash_backfill.py --pisat         # записать отпечатки в лист
  python3 phash_backfill.py --pisat --tolko-puti   # только по path из записей
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phash_ban as P                                            # noqa: E402

MD5_LOG = os.path.expanduser("~/projects/media-library/.banned_md5.json")
EXT = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".mkv", ".webm")
PROJ = os.path.expanduser("~/projects")


def file_md5(path):
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    pisat = "--pisat" in sys.argv
    tolko = "--tolko-puti" in sys.argv
    with open(MD5_LOG, encoding="utf-8") as f:
        ban = json.load(f)
    print("забанено по md5: %d" % len(ban), flush=True)

    found = {}          # md5 -> путь к живому файлу
    for md5, e in ban.items():
        p = e.get("path") or ""
        if p and not p.startswith("http") and os.path.isfile(p):
            found[md5] = p
    print("нашлось по path из записи: %d" % len(found), flush=True)

    if not tolko:
        t0 = time.time()
        seen = 0
        for d in sorted(os.listdir(PROJ)):
            img = os.path.join(PROJ, d, "images")
            if not os.path.isdir(img):
                continue
            for name in os.listdir(img):
                if not name.lower().endswith(EXT):
                    continue
                path = os.path.join(img, name)
                if not os.path.isfile(path):
                    continue
                seen += 1
                try:
                    h = file_md5(path)
                except OSError:
                    continue
                if h in ban and h not in found:
                    found[h] = path
        print("обошёл кадров проектов: %d за %.0f с; всего живых забаненных: %d"
              % (seen, time.time() - t0, len(found)), flush=True)

    ok = flat = bad = 0
    for md5, path in sorted(found.items(), key=lambda kv: kv[1]):
        e = ban.get(md5) or {}
        if pisat:
            ph = P.ban_phash(path, md5=md5, reason=e.get("reason", ""),
                             until=e.get("until", ""), project=e.get("project", ""))
        else:
            ph = P.dhash_hex(path)
        if ph:
            ok += 1
        else:
            flat += 1
    print("отпечаток посчитан: %d · ровный кадр (только md5): %d · нечитаем: %d"
          % (ok, flat, bad), flush=True)
    if pisat:
        print("лист: %s — записей %d"
              % (P.log_path(), len(P.load_banned_phash())), flush=True)
    else:
        print("СУХОЙ ПРОГОН. Записать: --pisat", flush=True)


if __name__ == "__main__":
    main()
