#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МАТЕРИАЛ ДОСЬЕ ДОЛЖЕН БЫТЬ В РОЛИКЕ, А НЕ В ФАЙЛЕ `tg.json`.

    dossier_use.py <scenes.json> [overlays.json …] [--tg tg.json] [--strict]

Строжайшее правило пользователя (31.10, сказано трижды за десять минут):
«То, что отдаётся георадаром, по возможности ВСЁ вставлять, что можно. Всё
использовать. Фотографии, видео, которые там вставляются. Для чего они тогда
нужны, если их не вставлять? Искать какую-то срань?»

Поэтому порядок источников в ролике такой, и он не обсуждается:
  1. материал досье (вложения постов георадара) — СНАЧАЛА;
  2. медиатека и база кадров;
  3. поиск — ТОЛЬКО то, что не закрыли первые два.

Скрипт сверяет `tg.json` (выдачу `tg_media.py`) со сценарием и говорит, что из
присланного пользователем осталось лежать без дела. Неиспользованный материал
при живых сценах из ПОИСКА — отказ: значит ролик ищет то, что уже лежит рядом.

Ширина кадра поводом НЕ является: узкий кадр ставится в родном размере по
центру с размытой заливкой полей (правило 30.10). Карты из постов идут в сцены
первым делом — карта источника это информация, а не «кадр 800 px».
"""
import ast
import glob
import json
import os
import sys

SEARCH = ("press_photo", "web_search", "wikimedia",
          "pexels_photo", "pexels_video", "pexels")


def _urls(rec, key):
    v = rec.get(key) or []
    if isinstance(v, str):
        try:
            v = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            v = [v] if v.startswith("http") else []
    return [str(u) for u in v if str(u).startswith("http")]


def _notes(rec):
    v = rec.get("notes") or []
    if isinstance(v, str):
        try:
            v = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            v = [v]
    return [str(x) for x in v]


def load_tg(path):
    d = json.load(open(path, encoding="utf-8"))
    recs = d if isinstance(d, list) else (d.get("items") or d.get("posts") or [])
    out = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        post = str(r.get("url") or "")
        for u in _urls(r, "photos"):
            out.append({"url": u, "post": post, "kind": "фото",
                        "notes": _notes(r)})
        for u in _urls(r, "videos"):
            out.append({"url": u, "post": post, "kind": "видео",
                        "notes": _notes(r)})
    return out


def used_strings(paths):
    """Всё, что сценарий и всплывашки уже упоминают, одной кучей."""
    blob = []
    stats = {"direct_url": 0, "search": 0, "library": 0, "card": 0, "total": 0}
    for p in paths:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("!! не прочитать %s: %s" % (p, e))
            continue
        scenes = d.get("scenes", d) if isinstance(d, dict) else d
        if not isinstance(scenes, list):
            continue
        for s in scenes:
            if not isinstance(s, dict):
                continue
            src = str(s.get("source") or "")
            q = str(s.get("source_query") or "")
            blob.append(q)
            for k in ("file", "url", "asset", "path"):
                if s.get(k):
                    blob.append(str(s[k]))
            stats["total"] += 1
            if src == "direct_url":
                stats["direct_url"] += 1
            elif src.startswith("card"):
                stats["card"] += 1
            elif src == "local_library":
                stats["library"] += 1
            elif src in SEARCH:
                stats["search"] += 1
    return "\n".join(blob), stats


def load_rejected(where):
    """ЖУРНАЛ ОТКЛОНЁННОГО МАТЕРИАЛА ДОСЬЕ (31.10, предложение `usuario-b2`).

    Гейт не отличал «посмотрел и отклонил по дефекту или по теме» от «не
    смотрел». Живой случай: запись `ARM` многотемная, и пять файлов из неё
    про ДРУГИЕ сюжеты той же записи (танкеры в США, гарантии для России) плюс
    кадр с логотипом телеканала — к ролику не относятся вовсе, а гейт висел
    красным. Красный гейт, который «всегда красный», перестают читать — это
    хуже отсутствия гейта. Поэтому отклонённое засчитывается РАЗОБРАННЫМ, но
    только с названной причиной, и причина печатается: молча спрятать файл
    нельзя.

    Файл рядом со сценарием: `tg_rejected.json` (или `tg_отказы.json`).
    Формат любой из двух: {"<url>": "причина"} или
    [{"url": "…", "why": "…"}, …].
    """
    out = {}
    for name in ("tg_rejected.json", "tg_отказы.json"):
        p = os.path.join(where, name)
        if not os.path.isfile(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("!! не прочитать %s: %s" % (name, e))
            continue
        if isinstance(d, dict):
            for k, v in d.items():
                out[str(k)] = str(v)
        elif isinstance(d, list):
            for r in d:
                if isinstance(r, dict) and r.get("url"):
                    out[str(r["url"])] = str(r.get("why") or r.get("reason") or "")
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    tgs = []
    if "--tg" in sys.argv:
        tg1 = sys.argv[sys.argv.index("--tg") + 1]
        args = [a for a in args if a != tg1]
        tgs = [tg1]
    here = os.path.dirname(os.path.abspath(args[0])) or "."
    # ВСЕ ПРОГОНЫ tg_media, А НЕ ПЕРВЫЙ ФАЙЛ ПО АЛФАВИТУ (31.10, улов
    # `usuario-6a`): у вкладки было два прогона, `tg.json` и `tg2.json`, и
    # второй в счёт не шёл — то есть материал «не существовал» для гейта.
    for c in sorted(glob.glob(os.path.join(here, "tg*.json"))):
        b = os.path.basename(c).lower()
        if "reject" in b or "отказ" in b or c in tgs:
            continue
        tgs.append(c)
    # ВСПЛЫВАШКИ СЧИТАЮТСЯ ТОЖЕ (31.10, тот же улов). Гейт сам пишет «что не
    # лезет в сцену — идёт во всплывашку», а смотрел только базовые сцены:
    # вкладка поставила шесть файлов досье всплывашками и получила
    # «поставлено 0». Для ролика, закрывшего материал целиком всплывашками,
    # это валило бы фетч без причины.
    _have = {os.path.abspath(x) for x in args}
    for c in sorted(glob.glob(os.path.join(here, "*overlay*.json"))
                    + glob.glob(os.path.join(here, "overlays*.json"))):
        if os.path.abspath(c) not in _have and "snapshot" not in os.path.basename(c):
            args.append(c)
            _have.add(os.path.abspath(c))
    tg = tgs[0] if tgs else None
    if not tgs:
        print("ОШИБКА: не найден файл выдачи tg_media.py (tg*.json) рядом со "
              "сценарием.", file=sys.stderr)
        print("  Досье ОБЯЗАНО быть прогнано до раскадровки: соберите ВСЕ "
              "ссылки t.me со ВСЕХ листов xlsx (Archive, Debug, AuthorNotes, "
              "NewsInbox, Claims, Sources, Productions) и прогоните "
              "tg_media.py --json tg.json <ссылки…>.", file=sys.stderr)
        return 2

    media = []
    _seen_u = set()
    for t in tgs:
        for m in load_tg(t):
            if m["url"] in _seen_u:
                continue
            _seen_u.add(m["url"])
            media.append(m)
    print("выдачи tg_media: %s" % ", ".join(os.path.basename(t) for t in tgs))
    print("сверяю со: %s" % ", ".join(os.path.basename(x) for x in args))
    blob, st = used_strings(args)
    rej = load_rejected(os.path.dirname(os.path.abspath(args[0])) or ".")
    if not media:
        print("в %s медиа нет вовсе — вложений у постов не было, претензий "
              "нет" % os.path.basename(tg))
        return 0

    unused = [m for m in media if m["url"] not in blob
               and m["url"] not in rej]
    used = len([m for m in media if m["url"] in blob])
    dropped = [m for m in media if m["url"] not in blob and m["url"] in rej]
    print("=== МАТЕРИАЛ ДОСЬЕ ===")
    print("файлов во вложениях постов: %d (фото %d, видео %d)" % (
        len(media), sum(1 for m in media if m["kind"] == "фото"),
        sum(1 for m in media if m["kind"] == "видео")))
    print("поставлено в ролик: %d, разобрано и отклонено: %d, лежит без "
          "дела: %d" % (used, len(dropped), len(unused)))
    for m in dropped[:40]:
        print("  отклонено: %s из %s — %s"
              % (m["kind"], m["post"], rej.get(m["url"]) or "без причины"))
    print("сцен: всего %d — досье %d, медиатека %d, поиск %d, рисованных %d"
          % (st["total"], st["direct_url"], st["library"], st["search"],
             st["card"]))

    if not unused:
        print("\nЧисто: весь материал досье в ролике.")
        return 0

    print("\nНЕ ИСПОЛЬЗОВАНО:")
    for m in unused[:40]:
        note = ("; ".join(m["notes"])[:90]) if m["notes"] else ""
        print("  %s из %s%s" % (m["kind"], m["post"], (" — " + note) if note else ""))
        print("      %s" % m["url"])
    if len(unused) > 40:
        print("  … и ещё %d" % (len(unused) - 40))

    print("\n  Если файл СМОТРЕЛИ и он не подходит (чужая тема той же записи "
          "ARM, клеймо по центру, вшитые субтитры) — впиши его в "
          "tg_rejected.json рядом со сценарием: {\"<url>\": \"причина\"}. "
          "Он зачтётся разобранным, а причина останется видна.")
    if st["search"]:
        print("\nОТКАЗ: %d сцен закрыты ПОИСКОМ, пока %d файлов досье лежат "
              "без дела." % (st["search"], len(unused)))
        print("  Порядок источников: досье → медиатека и база → поиск, и"
              " только им.")
        print("  Ширина НЕ повод оставить кадр в стороне: узкий кадр ставится в"
              " родном размере по центру с размытой заливкой полей.")
        print("  КАРТЫ из постов ставятся в сцены первым делом — карта"
              " источника это информация, а не «кадр 800 px».")
        print("  Что физически не лезет в сцену — идёт во всплывашку (порог"
              " 800).")
        return 1
    print("\nСцен из поиска нет — остаток досье это не брак, но посмотри, не "
          "просится ли он во всплывашки.")
    return 1 if "--strict" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())
