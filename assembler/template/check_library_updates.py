#!/usr/bin/env python3
"""
check_library_updates.py — MUST be run before starting any new montage.

Snapshots ~/projects/media-library and diffs against the previous snapshot so
we always know what the user added since the last video. The library lives on
a DrvFs mount (/mnt/d) where find -mtime / -cmin are unreliable, so we compare
an explicit manifest (relative path -> size, mtime) instead.

Usage:
    python3 check_library_updates.py             # show diff vs last snapshot
    python3 check_library_updates.py --commit    # show diff AND save new snapshot

Workflow: run without --commit at the start of a build, show the user what is
new, decide with them which folders need index_library.py (long multi-shot
sourcevideos only), then run again with --commit once the new material is
accounted for.

Exit codes: 0 = no changes, 10 = changes found, 1 = library missing.
"""
import json
import os
import sys
import time

LIB = os.path.expanduser("~/projects/media-library")
SNAP = os.path.join(LIB, ".library_snapshot.json")
CATEGORIES = ("ПОЛИТИКА", "АСТРОЛОГИЯ", "МИСТИКА", "ЦЕРКОВЬ")
MEDIA_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi",
             ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
LONG_VIDEO_BYTES = 15 * 1024 * 1024  # >15 MB mp4 ≈ a long multi-shot compilation


def scan():
    manifest = {}
    for cat in CATEGORIES:
        root = os.path.join(LIB, cat)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in MEDIA_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                rel = os.path.relpath(full, LIB)
                manifest[rel] = [st.st_size, int(st.st_mtime)]
    return manifest


def folder_of(rel):
    parts = rel.split(os.sep)
    # ПОЛИТИКА/НАТО/x.mp4 -> ПОЛИТИКА/НАТО ; ПОЛИТИКА/ПОЛЬША/ТУСК/x -> ПОЛИТИКА/ПОЛЬША/ТУСК
    return os.sep.join(parts[:-1]) if len(parts) > 2 else os.sep.join(parts[:1])


def main():
    commit = "--commit" in sys.argv
    if not os.path.isdir(LIB):
        print(f"НЕТ медиатеки: {LIB}", file=sys.stderr)
        return 1

    now = scan()
    old = {}
    old_when = None
    if os.path.exists(SNAP):
        try:
            blob = json.load(open(SNAP, encoding="utf-8"))
            old = blob.get("files", {})
            old_when = blob.get("saved_at")
        except (OSError, ValueError):
            pass

    added = sorted(k for k in now if k not in old)
    removed = sorted(k for k in old if k not in now)
    changed = sorted(k for k in now if k in old and now[k] != old[k])

    if old_when:
        print(f"Прошлый снимок медиатеки: {old_when}")
    else:
        print("Прошлого снимка медиатеки нет — это первый прогон, всё считается новым.")
    print(f"Сейчас файлов в медиатеке: {len(now)}\n")

    if not (added or removed or changed):
        print("✅ Медиатека не менялась с прошлого раза. Можно собирать.")
        return 0

    by_folder = {}
    for k in added:
        by_folder.setdefault(folder_of(k), {"add": [], "chg": [], "del": []})["add"].append(k)
    for k in changed:
        by_folder.setdefault(folder_of(k), {"add": [], "chg": [], "del": []})["chg"].append(k)
    for k in removed:
        by_folder.setdefault(folder_of(k), {"add": [], "chg": [], "del": []})["del"].append(k)

    needs_index = []
    print(f"⚠️  ИЗМЕНЕНИЯ: +{len(added)} новых, ~{len(changed)} изменённых, -{len(removed)} удалённых\n")
    for folder in sorted(by_folder):
        d = by_folder[folder]
        print(f"📁 {folder}")
        long_new = 0
        for k in d["add"]:
            size = now[k][0]
            tag = ""
            if k.lower().endswith((".mp4", ".mov", ".webm", ".mkv")) and size > LONG_VIDEO_BYTES:
                tag = "  ← длинное видео, вероятно нужна разметка"
                long_new += 1
            print(f"    + {os.path.basename(k)}  ({size // 1024} КБ){tag}")
        for k in d["chg"]:
            print(f"    ~ {os.path.basename(k)}")
        for k in d["del"]:
            print(f"    - {os.path.basename(k)}")
        has_index = os.path.exists(os.path.join(LIB, folder, "index.json"))
        if long_new and not has_index:
            needs_index.append(folder)
        elif long_new and has_index:
            needs_index.append(folder + "  (index.json уже есть — до-разметить новые куски)")
        print()

    if needs_index:
        print("🔧 Кандидаты на index_library.py (длинные многосюжетные видео):")
        for f in needs_index:
            print(f"    - {f}")
        print()

    if commit:
        json.dump(
            {"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": now},
            open(SNAP, "w", encoding="utf-8"),
            ensure_ascii=False,
        )
        print(f"💾 Новый снимок сохранён: {SNAP}")
    else:
        print("Снимок НЕ сохранён. После разбора новых файлов запусти с --commit.")
    return 10


if __name__ == "__main__":
    sys.exit(main())
