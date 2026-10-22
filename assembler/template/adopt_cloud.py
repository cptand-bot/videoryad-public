#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adopt_cloud.py — перенести кадры из папки ЗАБОРА в папку ролика.

Зачем отдельный инструмент (2026-10-22, улов `usuario-ad`, стоило разбора на
пустом месте): в `images/manifest.json` поле `file` — ГОЛОЕ ИМЯ файла
(«scene_001.mp4»), без каталога. Естественное
`os.path.join(<корень забора>, m["file"])` даёт несуществующий путь, все кадры
молча считаются отсутствующими и переносится НОЛЬ сцен — при том что в заборе
честные 88 файлов, а `FETCH-report.md` говорит «БЕЗ КАДРА: 0». Выглядит как
пустой забор, хотя забор полон.

Правильный путь — `<забор>/images/<basename>`, и то же самое для всплывашек
(`<забор>/overlays/`). Здесь это зашито, чтобы больше никто не складывал путь
руками.

    python3 adopt_cloud.py <папка забора> <папка ролика> [--dry-run] [--force]

По умолчанию НЕ перезаписывает существующие файлы в папке ролика (там могут
лежать кадры, которые вкладка уже правила руками) — для перезаписи `--force`.
Печатает построчный итог и в конце сверку: сколько сцен в сценарии, сколько
кадров перенесено, по скольким кадра нет вовсе.
"""
import glob
import json
import os
import shutil
import sys

_IMG = (".jpg", ".jpeg", ".png", ".webp")
_VID = (".mp4", ".mov", ".webm")


def _scenes_file(proj):
    cs = [x for x in glob.glob(os.path.join(proj, "*.scenes.json"))
          if "overlays_fetch" not in os.path.basename(x)]
    if not cs:
        return ""
    cs.sort(key=lambda q: (-len(_load(q).get("scenes", [])), len(os.path.basename(q))))
    return cs[0]


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _recs(d):
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    for k in ("items", "scenes", "manifest"):
        v = d.get(k)
        if isinstance(v, list):
            return [r for r in v if isinstance(r, dict)]
    return []


def adopt(src, dst, dry=False, force=False):
    if not os.path.isdir(src):
        print("!! нет папки забора: %s" % src)
        return 2
    os.makedirs(os.path.join(dst, "images"), exist_ok=True)

    total_moved = total_skipped = missing = 0
    for sub in ("images", "overlays"):
        moved = skipped = 0
        s_dir = os.path.join(src, sub)
        if not os.path.isdir(s_dir):
            continue
        d_dir = os.path.join(dst, sub)
        os.makedirs(d_dir, exist_ok=True)
        man = _recs(_load(os.path.join(s_dir, "manifest.json")))
        names = [os.path.basename(str(m.get("file") or "")) for m in man if m.get("file")]
        if not names:
            # манифеста нет или он пуст — берём, что лежит на диске
            names = [os.path.basename(p) for p in glob.glob(os.path.join(s_dir, "scene_*"))
                     if os.path.splitext(p)[1].lower() in _IMG + _VID]
        print("== %s: в манифесте/на диске %d файлов" % (sub, len(names)))
        for n in sorted(set(names)):
            sp = os.path.join(s_dir, n)          # <-- ВОТ ЭТОТ ПУТЬ, а не join(src, n)
            if not os.path.isfile(sp):
                print("   НЕТ в заборе: %s" % n)
                missing += 1
                continue
            dp = os.path.join(d_dir, n)
            if os.path.exists(dp) and not force:
                skipped += 1
                continue
            if not dry:
                shutil.copy2(sp, dp)
            moved += 1
        print("   перенесено %d, пропущено (уже есть) %d" % (moved, skipped))
        total_moved += moved
        total_skipped += skipped

    print("ИТОГО перенесено %d, пропущено %d" % (total_moved, total_skipped))
    sf = _scenes_file(dst) or _scenes_file(src)
    if sf:
        scenes = _load(sf).get("scenes", [])
        have = set()
        for p in glob.glob(os.path.join(dst, "images", "scene_*")):
            if os.path.splitext(p)[1].lower() in _IMG + _VID:
                try:
                    have.add(int(os.path.basename(p).split("_")[1].split(".")[0]))
                except (IndexError, ValueError):
                    pass
        no = [s.get("id") for s in scenes if s.get("id") not in have
              and not str(s.get("source", "")).startswith("card")]
        print("\nсверка со сценарием %s: сцен %d, кадров на месте %d, без кадра %d"
              % (os.path.basename(sf), len(scenes), len(have), len(no)))
        if no:
            print("  без кадра: %s" % ", ".join(str(x) for x in no[:30]))
    if dry:
        print("\n--dry-run: ничего не скопировано")
    if missing:
        print("!! %d файлов из манифеста не нашлось в заборе" % missing)
    return 1 if missing else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(adopt(args[0], args[1],
                   dry="--dry-run" in sys.argv, force="--force" in sys.argv))
