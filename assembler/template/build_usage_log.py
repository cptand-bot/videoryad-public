#!/usr/bin/env python3
"""Backfill / update ~/projects/media-library/.usage_log.json.

Walks every past news-video project's images/ dir, md5s each asset, and for
any that byte-match a file currently in the media-library, records
{project, date} against that md5. This is what lets the fetcher skip a
library shot that was used in the last N videos instead of recycling it
across every video (user, 2026-08-29).

Run once to seed history, then fetch_assets_news.py maintains it per build.
"""
import hashlib, json, os, sys, glob, datetime

HOME = os.path.expanduser("~")
def _media_library_dir():
    """Медиатека канала из .env, а не зашитая библиотека-1 (2026-10-19).
    Та же правка, что сделана в check_lead.py 03.10: на каналах, сидящих на
    media-library-2 (5 МИНУТ / ДИПЛОМАТИЯ СИЛЫ / ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО),
    этот скрипт смотрел в ЧУЖУЮ медиатеку и тихо находил ноль файлов —
    молча, без единой ошибки в выводе. Нормализуем и форму
    `MEDIA_LIBRARY_DIR=media-library-2` (имя папки без пути), она описана в
    рабочих заметках и встречается в живых .env."""
    val = os.environ.get("MEDIA_LIBRARY_DIR")
    if not val:
        # .env ищем не только в текущей папке, но и выше по дереву: скрипт
        # часто зовут из подпапки проекта, и тогда он молча брал библиотеку-1
        d = os.path.abspath(".")
        for _ in range(4):
            cand = os.path.join(d, ".env")
            if os.path.exists(cand):
                with open(cand, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("MEDIA_LIBRARY_DIR="):
                            val = line.split("=", 1)[1].strip()
                            break
                if val:
                    break
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    if not val:
        return os.path.expanduser("~/projects/media-library")
    val = os.path.expanduser(val)
    if not os.path.isabs(val):
        val = os.path.expanduser(os.path.join("~/projects", val))
    return val

LIB = _media_library_dir()
print("медиатека:", LIB, "" if os.path.isdir(LIB) else "— ПАПКИ НЕТ", flush=True)
LOG = os.path.join(LIB, ".usage_log.json")
# both video pipelines share one journal; scan every project dir either builds in
PROJECT_ROOTS = [
    os.path.join(HOME, "projects/news-video"),
    os.path.join(HOME, "projects/script-to-video/output"),
    os.path.join(HOME, "projects/script-to-video/scripts"),
]
if len(sys.argv) > 1:                      # optional extra roots on the CLI
    PROJECT_ROOTS = [os.path.expanduser(a) for a in sys.argv[1:]]


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_library_index(wanted_sizes):
    """md5 -> relative path, only for library files whose byte size matches
    some project asset (a library file copied into a project keeps its size).
    Skips md5-ing the many GB of library video that can't possibly match."""
    idx = {}
    exts = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")
    for root, _, files in os.walk(LIB):
        if os.path.basename(root) in (".thumbs",):
            continue
        for fn in files:
            if not fn.lower().endswith(exts):
                continue
            p = os.path.join(root, fn)
            try:
                if os.path.getsize(p) not in wanted_sizes:
                    continue
                idx.setdefault(md5(p), os.path.relpath(p, LIB))
            except OSError:
                pass
    return idx


def collect_project_assets():
    out = {}
    proj_paths = []
    for root in PROJECT_ROOTS:
        proj_paths += sorted(glob.glob(os.path.join(root, "*")))
    for proj_path in proj_paths:
        if not os.path.isdir(proj_path):
            continue
        proj = os.path.basename(proj_path)
        img_dirs = glob.glob(os.path.join(proj_path, "images")) + \
                   glob.glob(os.path.join(proj_path, "*", "images"))
        assets = []
        for d in img_dirs:
            for p in glob.glob(os.path.join(d, "*")):
                if os.path.isfile(p) and os.path.getsize(p) > 0:
                    assets.append(p)
        if assets:
            out[proj] = (proj_path, assets)
    return out


def main():
    projects = collect_project_assets()
    wanted_sizes = set()
    for _, (_, assets) in projects.items():
        for p in assets:
            try:
                wanted_sizes.add(os.path.getsize(p))
            except OSError:
                pass
    print(f"{len(projects)} projects, {len(wanted_sizes)} distinct asset sizes")
    lib_idx = build_library_index(wanted_sizes)
    print(f"library: {len(lib_idx)} files match a project-asset size")

    log = {}
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            log = json.load(f)

    for proj, (proj_path, assets) in projects.items():
        try:
            date = datetime.date.fromtimestamp(os.path.getmtime(proj_path)).isoformat()
        except OSError:
            date = "unknown"
        hits = 0
        for p in assets:
            try:
                h = md5(p)
            except OSError:
                continue
            if h in lib_idx:
                entries = log.setdefault(h, [])
                if not any(e["project"] == proj for e in entries):
                    entries.append({"project": proj, "date": date, "file": lib_idx[h]})
                hits += 1
        print(f"{proj:28s} {len(assets):4d} assets, {hits:4d} from library")

    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print(f"\nwrote {LOG}: {len(log)} library files have usage history")


if __name__ == "__main__":
    main()
