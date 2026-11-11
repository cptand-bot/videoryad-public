#!/usr/bin/env python3
"""СНЕСТИ ЗАБАНЕННЫЙ КАДР ИЗ МЕДИАТЕКИ — ПО ХЭШУ, А НЕ ПО ПУТИ.

Его слово 11.11.2026, дважды: «все забаненные ролики и картинки со вчера и со
сегодняшнего забанить навсегда и записать это себе на лбу, чтобы они больше
никогда не появлялись» и «если я говорю в бан всплывашку или картинку, то
значит её в бан. Её надо сносить нафиг. И записывать куда-то, чтобы она больше
не появлялась».

ЗАЧЕМ ОТДЕЛЬНЫЙ ШАГ. Бан писался только в лист `.banned_md5.json`, и он
держал ФЕТЧ: поиск такой кадр больше не приносил. Но сам файл оставался в
`БАЗА/`, а оттуда кадр приходит как `local_library` — мимо фетча и мимо листа.
Промер 11.11: СЕМЬ кадров, забаненных им словами «навсегда / для всех
сборок» 04-07.11, всё ещё лежали в медиатеке и могли встать в любой
следующий ролик. Плюс 20 кадров из банов 10-11.11.

ПОЧЕМУ ПО ХЭШУ. Дашборд банит КОПИЮ в папке проекта (`images/scene_066.jpg`),
а в медиатеке тот же кадр лежит под своим именем. Совпадение путей бесполезно,
совпадает только md5.

ИНДЕКС. Полный обход 1450 файлов стоит минуты, поэтому хэши кэшируются в
`БАЗА/.md5-index.json` по (путь, размер, mtime) и обновляются только для
изменившихся файлов. Первый вызов платит обход, дальше — мгновенно.

    python3 baza_snos.py --md5 <hash> [<hash> ...]   # снести по хэшам
    python3 baza_snos.py --file <путь>               # снести двойник файла
    python3 baza_snos.py --index                     # только обновить индекс
"""
import hashlib
import json
import os
import shutil
import sys
import time

BAZA = os.environ.get("VIDEORYAD_BAZA") or "/mnt/d/media-library/БАЗА"
INDEX = os.path.join(BAZA, ".md5-index.json")
EXT = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm")


def _md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _skip(root):
    parts = root.split(os.sep)
    return ".korzina" in parts or "thumbs" in parts


def индекс(обновить=True):
    """{md5: [путь, ...]} по всей базе, кэш по (размер, mtime)."""
    old = {}
    if os.path.exists(INDEX):
        try:
            old = json.load(open(INDEX, encoding="utf-8"))
        except Exception:
            old = {}
    new, by_md5, пересчитано = {}, {}, 0
    for root, dirs, files in os.walk(BAZA):
        if _skip(root):
            continue
        for f in files:
            if not f.lower().endswith(EXT):
                continue
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            ключ = "%d:%d" % (st.st_size, int(st.st_mtime))
            prev = old.get(p)
            if prev and prev.get("k") == ключ:
                h = prev["h"]
            elif обновить:
                try:
                    h = _md5(p)
                except Exception:
                    continue
                пересчитано += 1
            else:
                continue
            new[p] = {"k": ключ, "h": h}
            by_md5.setdefault(h, []).append(p)
    if обновить:
        try:
            json.dump(new, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e:
            print("индекс не сохранён: %r" % (e,), file=sys.stderr)
    return by_md5, пересчитано


def снести(md5s, причина=""):
    """Вынести из базы все файлы с такими хэшами. Отдаёт список путей."""
    md5s = {m.strip().lower() for m in md5s if m and m.strip()}
    if not md5s:
        return []
    by_md5, пересчитано = индекс()
    кор = os.path.join(BAZA, ".korzina", time.strftime("%Y-%m-%d") + "-ban")
    вынесено = []
    for m in md5s:
        for p in by_md5.get(m, []):
            if not os.path.exists(p):
                continue
            rel = os.path.relpath(p, BAZA)
            dst = os.path.join(кор, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.move(p, dst)
                вынесено.append(rel)
            except Exception as e:
                print("  НЕ вынесен из базы: %s (%r)" % (rel, e), file=sys.stderr)
    if вынесено:
        print("  СНЕСЕНО ИЗ МЕДИАТЕКИ: %d — больше этот кадр не придёт как "
              "local_library" % len(вынесено))
        for rel in вынесено:
            print("    %s" % rel)
        print("    (вынесено в %s, не удалено)" % кор)
        журнал(вынесено, причина)
    return вынесено


def журнал(пути, причина):
    try:
        f = os.path.join(BAZA, ".korzina", "ЧТО-И-ПОЧЕМУ-СНЕСЕНО.md")
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            for rel in пути:
                fh.write("- %s · %s · %s\n"
                         % (time.strftime("%Y-%m-%d %H:%M"), rel, причина or "без причины"))
    except Exception:
        pass


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        raise SystemExit(1)
    if a[0] == "--index":
        by, n = индекс()
        print("в индексе хэшей: %d · пересчитано: %d" % (len(by), n))
        raise SystemExit(0)
    if a[0] == "--file":
        if len(a) < 2 or not os.path.exists(a[1]):
            print("нет файла", file=sys.stderr)
            raise SystemExit(2)
        снести([_md5(a[1])], "снос двойника %s" % os.path.basename(a[1]))
        raise SystemExit(0)
    if a[0] == "--md5":
        снести(a[1:], "ban_file")
        raise SystemExit(0)
    print(__doc__)
    raise SystemExit(1)
