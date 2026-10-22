#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_report.py — честный отчёт о том, ЧТО НЕ ДОЕХАЛО после фетча.

Повод (2026-10-22, улов `usuario-5a` на `5min-polsha-2310`): отчёт
`_cloud/QA-report.md` писал «картинок сцен: 58» при ДЕВЯТИ пустых сценах —
он считал файлы в `images/`, не сверяя их со сценарием и не глядя в
манифесты. Отчёт был зелёный, и девять сцен уехали бы в сборку заглушками,
если бы вкладка не пошла сверять манифесты руками.

Хуже того, пустота оказалась ДВУХ РАЗНЫХ ПРИРОД, и лечатся они по-разному:
  - сцены 32, 33, 41, 56, 58 — `status: FAILED` в манифесте: фетч ходил и
    не добыл. Лечение — переписать запрос;
  - сцены 6, 23, 40, 57 — ЗАПИСИ НЕТ НИ В ОДНОМ манифесте: их никто не
    фетчил, потому что отменился один шард из двадцати (`fetch (7)`).
    Запросы тут ни при чём, лечение — добор этих сцен.
Половина «нулевого круга» была не виной формулировок — а выглядела так же.

Запуск: python3 fetch_report.py <папка проекта> [--md <файл>]
Код возврата 1, если есть потери (для вызова из шага CI), иначе 0.
"""
import glob
import json
import os
import sys

_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
_VID_EXT = (".mp4", ".mov", ".webm")
_DARK = 45          # средняя яркость ниже — почти наверняка заглушка облака
_PLACEHOLDER_MAX = 60 * 1024


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
    if isinstance(d, dict) and all(isinstance(v, dict) for v in d.values()):
        return list(d.values())
    return []


def _brightness(path):
    """Средняя яркость кадра или None. Заглушку облака по РАЗМЕРУ не поймать
    (бывает и 34 КБ, и 36864 — проверено 2026-10-13), по яркости — всегда."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("L").resize((32, 32))
            px = im.tobytes()
        return sum(px) / float(len(px))
    except Exception:
        return None


def report(proj, md_path=""):
    sf = _scenes_file(proj)
    if not sf:
        print("!! в %s нет *.scenes.json — отчёт не построить" % proj)
        return 1
    scenes = _load(sf).get("scenes", [])
    ids = [s.get("id") for s in scenes]
    by_id = {s.get("id"): s for s in scenes}
    images_dir = os.path.join(proj, "images")

    # что лежит на диске
    have, dark = {}, []
    for p in glob.glob(os.path.join(images_dir, "scene_*")):
        ext = os.path.splitext(p)[1].lower()
        if ext not in _IMG_EXT + _VID_EXT:
            continue
        try:
            sid = int(os.path.basename(p).split("_")[1].split(".")[0])
        except (IndexError, ValueError):
            continue
        have[sid] = p
        if ext in _IMG_EXT and os.path.getsize(p) <= _PLACEHOLDER_MAX:
            b = _brightness(p)
            if b is not None and b < _DARK:
                dark.append((sid, int(b), os.path.getsize(p) // 1024))

    # что говорят манифесты шардов
    failed, seen, where = {}, set(), {}
    for m in sorted(glob.glob(os.path.join(images_dir, "manifest*.json"))):
        tag = os.path.basename(m).replace("manifest.", "").replace(".json", "") or "merged"
        for r in _recs(_load(m)):
            sid = r.get("id")
            if sid is None:
                continue
            seen.add(sid)
            where.setdefault(sid, tag)
            if str(r.get("status", "")).upper() == "FAILED":
                failed[sid] = (tag, r.get("reason") or "причина не записана")

    cards = [i for i in ids if str(by_id[i].get("source", "")).startswith("card")]
    no_file = [i for i in ids if i not in have and i not in cards]
    never_fetched = [i for i in no_file if i not in seen]
    tried_failed = [i for i in no_file if i in seen]

    lines = []
    a = lines.append
    a("# ЧТО НЕ ДОЕХАЛО ПОСЛЕ ФЕТЧА")
    a("")
    a("- сцен в сценарии:      %d  (%s)" % (len(ids), os.path.basename(sf)))
    a("- кадров на диске:      %d" % len(have))
    a("- карточек (рисуем сами): %d%s" % (len(cards),
      (" — " + ", ".join(map(str, cards))) if cards else ""))
    a("- БЕЗ КАДРА:            %d%s" % (len(no_file), "" if no_file else "  (чисто)"))
    a("")
    if never_fetched:
        a("## ИХ НИКТО НЕ ФЕТЧИЛ — записи нет ни в одном манифесте (%d)" % len(never_fetched))
        a("")
        a("Это упавший или отменённый ШАРД, а не плохие запросы: формулировки")
        a("трогать НЕ НАДО, нужен добор именно этих сцен.")
        a("")
        for i in never_fetched:
            a("- сцена %s — %s" % (i, (by_id[i].get("source_query") or "")[:70]))
        a("")
    if tried_failed:
        a("## ФЕТЧ ХОДИЛ И НЕ ДОБЫЛ — status FAILED (%d)" % len(tried_failed))
        a("")
        a("Вот это и есть кандидаты на переписывание запроса.")
        a("")
        for i in tried_failed:
            tag, why = failed.get(i, (where.get(i, "?"), "в манифесте нет FAILED, но файла нет"))
            a("- сцена %s [%s] %s" % (i, tag, why))
            a("    запрос: %s" % (by_id[i].get("source_query") or "")[:70])
        a("")
    if dark:
        a("## ПОХОЖИ НА ЗАГЛУШКУ ОБЛАКА — почти чёрный кадр (%d)" % len(dark))
        a("")
        a("Файл есть, поэтому в прежнем отчёте такая сцена считалась готовой.")
        a("")
        for sid, b, kb in sorted(dark):
            a("- сцена %s: яркость %d из 255, %d КБ" % (sid, b, kb))
        a("")
    if not (never_fetched or tried_failed or dark):
        a("Потерь нет: у каждой сцены есть свой кадр, заглушек не видно.")
        a("")

    text = "\n".join(lines)
    print(text)
    if md_path:
        try:
            os.makedirs(os.path.dirname(md_path) or ".", exist_ok=True)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError as e:
            print("!! не записать %s: %s" % (md_path, e))
    return 1 if (never_fetched or tried_failed or dark) else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    md = ""
    if "--md" in sys.argv:
        i = sys.argv.index("--md")
        md = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
    sys.exit(report(args[0], md))
