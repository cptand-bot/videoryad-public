#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""КАРТОЧКИ РАЗБОРА В БОЕВОМ СБОРЩИКЕ — обёртка над fullcycle/style_cards.py.

Второй элемент арсенала после цитаты-лоскута, и входит он в ту же дверь
`card:<вид>`: фетч за такой сценой не идёт, линтер не считает её текст
запросом, видео-лид не засчитывает, эффекты не ложатся.

ЗАЧЕМ (слово пользователя 2026-10-22): «давай пробуем этому пикселю сраному
сделать замену — наши комментарии, то, что мы выводим. Там всё-таки какая-то
динамика будет, какой-то видеопотенциал есть». Повод — сток мёртв третий
ролик подряд: на `ze-soglasen-2310` девять из четырнадцати стоковых сцен
вернулись заглушками (яркость 28 из 255), сток в ролике 0% при коридоре
10-20%. Эти сцены абстрактные по смыслу — рассуждение, вывод, расстановка
сил, — и фотографии им не положено по правилу f0. Поэтому вместо чужого
стока рисуем СВОЙ кадр с нашим текстом.

Три вида (у каждого своя динамика, чтобы ролик не стал презентацией):

    bullets  — тезисы разбора, до 5 пунктов, строки проявляются по очереди
    forces   — расстановка сил: кто и чего хочет, РОВНО 3 строки
    timeline — хронология: линия прочерчивается, засечки зажигаются

Пользоваться так (из папки проекта, ПЕРЕД ship.sh):

    python3 ~/.claude/skills/news-video/template/style_card.py \\
        planeta.scenes.json 34 bullets \\
        --kick "ЧТО ЭТО ЗНАЧИТ" \\
        --item "Киев соглашается обсуждать территории" \\
        --item "Условие одно — гарантии Вашингтона" \\
        --item "Европа об этом узнаёт из прессы" \\
        --note "а значит, решение уже принято без неё"

    python3 … 51 forces --kick "РАССТАНОВКА СИЛ" \\
        --row "ВАШИНГТОН=нужна сделка до выборов" \\
        --row "КИЕВ=нужны деньги и гарантии" \\
        --row "БРЮССЕЛЬ=нужно остаться за столом"

    python3 … 67 timeline --kick "КАК ЭТО ШЛО" --title "Три недели" \\
        --event "28 сентября=первый звонок" \\
        --event "12 октября=встреча в Белом доме|hot" \\
        --event "21 октября=заявление о согласии"

Делает ровно то же, что quote_card.py: берёт длительность и канал из сцены,
гонит проверки ДО рендера, рисует images/scene_NNN.mp4 РОВНО на duration_sec,
кладёт постер в cards/, прежний кадр убирает в cards/replaced/, ставит сцене
источник `card:<вид>` и ведёт общий журнал cards/cards.json.
"""
import argparse, fcntl, json, os, shutil, subprocess, sys, time

# Непустой source_query — см. разбор в quote_card.py: гарды облака считают
# сцену с пустым запросом неклассифицированной и роняют прогон на setup.
_CARD_QUERY = "карточка разбора — кадр рисуется локально, фетч не нужен"

SKILL = os.path.dirname(os.path.abspath(__file__))
FULLCYCLE = os.path.join(os.path.dirname(SKILL), "fullcycle")

WM = {
    "ПЛАНЕТА": "ПЛАНЕТА",
    "ОЛЬКА": "ОЛЬКА",
    "ДИПЛОМАТИЯ СИЛЫ": "ДИПЛОМАТИЯ СИЛЫ",
    "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО": "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО",
    "5 МИНУТ": "5 МИНУТ",
}

# Ёмкости рисовалок — ПОВТОРЯЮТ fullcycle/style_cards.py. Рисовалка лишнее
# молча обрезает (forces: «ТОЛЬКО 3 строки, четвёртая уезжает за край»),
# поэтому считаем здесь и падаем ДО рендера.
LIMITS = {
    "bullets":  {"items": (2, 5), "item_chars": 62, "kick_chars": 34},
    "forces":   {"items": (3, 3), "item_chars": 46, "kick_chars": 34},
    "timeline": {"items": (3, 6), "item_chars": 40, "kick_chars": 34},
}

# Расстановка по ролику. Норма карточек общая на ВСЕ виды (одна на 15 сцен,
# 22.10), но у видов разная динамика, поэтому подряд одинаковые не ставим.
PER_SCENES, MIN_GAP, MIN_GAP_SAME_KIND = 15, 8, 16


def _fail(code, *lines):
    print("\n".join(lines), file=sys.stderr)
    sys.exit(code)


def _channel(scenes_path, data):
    ch = (data.get("channel") or "").strip()
    if ch:
        return ch
    up = os.path.abspath(scenes_path).upper()
    for name in WM:
        if name.upper().replace(" ", "") in up.replace(" ", "").replace("-", ""):
            return name
    return ""


def _split_pair(raw, what):
    """«ЛЕВОЕ=правое» → (левое, правое). Разделитель только первый знак =."""
    if "=" not in raw:
        _fail(2, f"{what} пишется как «левое=правое», а пришло: {raw}")
    left, right = raw.split("=", 1)
    return left.strip(), right.strip()


def main():
    ap = argparse.ArgumentParser(description="карточка разбора на сцену ролика")
    ap.add_argument("scenes")
    ap.add_argument("sid", type=int)
    ap.add_argument("kind", choices=sorted(LIMITS))
    ap.add_argument("--kick", default="", help="эпиграф над карточкой")
    ap.add_argument("--title", default="", help="заголовок (timeline/forces)")
    ap.add_argument("--item", action="append", default=[],
                    help="пункт для bullets (повторяй для каждого)")
    ap.add_argument("--row", action="append", default=[],
                    help="строка forces: «КТО=чего хочет»")
    ap.add_argument("--event", action="append", default=[],
                    help="событие timeline: «дата=что было» или «дата=что было|hot»")
    ap.add_argument("--note", default="", help="сноска внизу (золотая)")
    ap.add_argument("--source", default="", help="первоисточник, можно пустым")
    ap.add_argument("--images", default="images")
    ap.add_argument("--anim", type=float, default=2.5,
                    help="секунд рисовать покадрово, дальше медленный наезд")
    ap.add_argument("--tail-zoom", type=float, default=0.06)
    ap.add_argument("--watermark", default="", help="перебить канал вручную")
    ap.add_argument("--dry-run", action="store_true", help="только проверки")
    ap.add_argument("--force", action="store_true",
                    help="не падать на расстановке (норма, интервал)")
    a = ap.parse_args()

    if not os.path.isfile(a.scenes):
        _fail(2, f"нет файла сцен: {a.scenes}")
    data = json.load(open(a.scenes, encoding="utf-8"))
    scenes = data["scenes"] if isinstance(data, dict) else data
    scene = next((s for s in scenes if int(s.get("id", -1)) == a.sid), None)
    if scene is None:
        _fail(2, f"в {a.scenes} нет сцены {a.sid}")

    dur = float(scene.get("duration_sec") or 0)
    if dur <= 0:
        _fail(2, f"у сцены {a.sid} нет duration_sec")

    channel = a.watermark or _channel(a.scenes, data if isinstance(data, dict) else {})
    watermark = WM.get(channel, channel or "").upper()
    if not watermark:
        _fail(2, "не определить канал: в шапке scenes.json нет «channel», в пути "
                 "его тоже не видно. Передай --watermark, иначе в углу встанет "
                 "ЧУЖОЕ имя канала (у рисовалки по умолчанию «ДИПЛОМАТИЯ СИЛЫ»)")

    lim = LIMITS[a.kind]

    # --- ПРОВЕРКА 1: содержимое под вид -----------------------------------
    raw = {"bullets": a.item, "forces": a.row, "timeline": a.event}[a.kind]
    flag = {"bullets": "--item", "forces": "--row", "timeline": "--event"}[a.kind]
    lo, hi = lim["items"]
    if not lo <= len(raw) <= hi:
        _fail(2, f"виду «{a.kind}» нужно от {lo} до {hi} строк ({flag}), "
                 f"а пришло {len(raw)}.",
              "  forces рисует РОВНО три дорожки — четвёртая уезжает за край "
              "кадра и рисовалка об этом не скажет." if a.kind == "forces" else "")

    # --- ПРОВЕРКА 2: длина строк ------------------------------------------
    # Рисовалка обрезает молча, поэтому меряем здесь.
    long_lines = []
    items, rows, events = [], [], []
    for r in raw:
        if a.kind == "bullets":
            items.append(r)
            if len(r) > lim["item_chars"]:
                long_lines.append((r, len(r)))
        elif a.kind == "forces":
            who, want = _split_pair(r, "строка forces")
            rows.append({"who": who, "want": want})
            if len(want) > lim["item_chars"]:
                long_lines.append((want, len(want)))
        else:
            when, what = _split_pair(r, "событие timeline")
            hot = what.endswith("|hot")
            what = what[:-4].strip() if hot else what
            # ключи рисовалки: "date"/"mark" — засечка, "text" — подпись
            # (проверено по style_cards.timeline, 22.10: на "when"/"what"
            # она падает KeyError уже в рендере, то есть после всех проверок)
            ev = {"date": when, "text": what}
            if hot:
                ev["hot"] = True
            events.append(ev)
            if len(what) > lim["item_chars"]:
                long_lines.append((what, len(what)))
    if long_lines:
        _fail(3, f"не влезает в карточку «{a.kind}» (потолок {lim['item_chars']} знаков):",
              *[f"  {n} знаков: {t}" for t, n in long_lines],
              "  рисовалка обрежет это МОЛЧА — сократи строку")
    if len(a.kick) > lim["kick_chars"]:
        _fail(3, f"эпиграф длиннее {lim['kick_chars']} знаков ({len(a.kick)}): {a.kick}")

    # --- ПРОВЕРКА 3: текст не повторяет уже стоящую карточку --------------
    jpath = os.path.join("cards", "cards.json")
    journal = json.load(open(jpath, encoding="utf-8")) if os.path.isfile(jpath) else {}
    mine = " ".join(items) + " ".join(r["want"] for r in rows) \
        + " ".join(e["text"] for e in events)
    for sid_s, rec in journal.items():
        if int(sid_s) == a.sid:
            continue
        theirs = " ".join(rec.get("lines", [])) or rec.get("text", "")
        if theirs and theirs.strip() == mine.strip():
            msg = f"тот же текст уже стоит на сцене {sid_s}"
            if not a.force:
                _fail(2, msg, "  снимается ключом --force")
            print("ВНИМАНИЕ:", msg)

    # --- ПРОВЕРКА 4: расстановка ------------------------------------------
    others = {}
    for x in scenes:
        src = str(x.get("source", ""))
        if src.startswith("card") and int(x.get("id", -1)) != a.sid:
            others[int(x.get("id", 0))] = src.split(":", 1)[-1]
    norm = max(1, round(len(scenes) / PER_SCENES))
    near = [i for i in others if abs(i - a.sid) < MIN_GAP]
    if near:
        msg = (f"карточка слишком близко к соседней (сцены {', '.join(map(str, sorted(near)))}): "
               f"держим не меньше {MIN_GAP} сцен между любыми карточками.")
        if not a.force:
            _fail(2, msg, "  выбери сцену подальше или сними ключом --force")
        print("ВНИМАНИЕ:", msg)
    # ОДИН ВИД ПОДРЯД — ЭТО ПРЕЗЕНТАЦИЯ, А НЕ РОЛИК. Своя, более широкая
    # дистанция: два списка тезисов через восемь сцен читаются как слайды.
    same = [i for i, k in others.items()
            if k == a.kind and abs(i - a.sid) < MIN_GAP_SAME_KIND]
    if same:
        msg = (f"такой же вид «{a.kind}» уже стоит рядом (сцены "
               f"{', '.join(map(str, sorted(same)))}): одинаковые карточки ближе "
               f"{MIN_GAP_SAME_KIND} сцен читаются как слайды презентации.")
        if not a.force:
            _fail(2, msg, "  возьми другой вид (bullets/forces/timeline) "
                          "или сцену подальше, либо сними ключом --force")
        print("ВНИМАНИЕ:", msg)
    over = len(others) + 1 - (norm + 1)
    if over > 0:
        print(f"ВНИМАНИЕ: карточек станет {len(others) + 1} при норме {norm} (+1 допуск) "
              f"на {len(scenes)} сцен — это на {over} больше коридора")

    print(f"сцена {a.sid}: {dur:.2f} с, канал {channel}, вид {a.kind}, "
          f"строк {len(raw)}; карточек в ролике станет {len(others) + 1} "
          f"из нормы {norm} ({len(scenes)} сцен)")
    if a.dry_run:
        print("--dry-run: проверки пройдены, ничего не нарисовано")
        return

    # --- рендер ------------------------------------------------------------
    sys.path.insert(0, FULLCYCLE)
    import style_cards as sc

    os.makedirs(a.images, exist_ok=True)
    os.makedirs(os.path.join("cards", "replaced"), exist_ok=True)
    out_mp4 = os.path.join(a.images, f"scene_{a.sid:03d}.mp4")
    poster = os.path.join("cards", f"scene_{a.sid:03d}.jpg")

    common = dict(kick=a.kick, source=a.source, watermark=watermark)
    if a.kind == "bullets":
        fn = sc.bullets
        kwargs = dict(common, items=tuple(items), note=a.note or None)
    elif a.kind == "forces":
        fn = sc.forces
        kwargs = dict(common, title=a.title, rows=tuple(rows), note=a.note or None)
    else:
        fn = sc.timeline
        kwargs = dict(common, title=a.title, events=tuple(events),
                      note=a.note or None)

    t0 = time.time()
    fn(out=poster, **kwargs)                 # постер — он же проверка глазами
    # fps БОЕВОЙ (30): сборщик клипов работает на 30, смешение частот в concat
    # уже однажды растянуло готовый ролик на 20%.
    sc.render_anim(fn, kwargs, dur, out_mp4, fps=30, anim_seconds=a.anim,
                   tail_zoom=a.tail_zoom, sfx_out=False)
    took = time.time() - t0

    # --- ПРОВЕРКА 5: длительность совпала со сценой ------------------------
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", out_mp4], capture_output=True, text=True)
    got = float((r.stdout or "0").strip() or 0)
    if abs(got - dur) > 0.2:
        _fail(4, f"длительность разошлась: клип {got:.2f} с, сцена {dur:.2f} с. "
                 "Разница больше 0,2 с — сборщик начнёт клип не с начала. Файл "
                 f"оставлен, пересними: {out_mp4}")

    # --- прежний кадр сцены в сторону --------------------------------------
    moved = []
    for ext in ("jpg", "jpeg", "png", "webp", "mov"):
        p = os.path.join(a.images, f"scene_{a.sid:03d}.{ext}")
        if os.path.exists(p):
            shutil.move(p, os.path.join("cards", "replaced", os.path.basename(p)))
            moved.append(os.path.basename(p))

    # --- сцена и журнал ----------------------------------------------------
    # Перечитываем файл перед записью и правим ТОЛЬКО свою сцену, под замком:
    # рендер держит объект десятки секунд, и правки соседних сцен, сделанные
    # вкладкой в это время, иначе молча откатываются (разбор — quote_card.py).
    lines = items or [r["want"] for r in rows] or [e["text"] for e in events]
    card = {k: v for k, v in dict(
        kind=a.kind, kick=a.kick, title=a.title, lines=lines, note=a.note,
        src=a.source, watermark=watermark, anim=a.anim).items()
        if v not in ("", None, [])}

    lockp = os.path.join("cards", ".scenes.lock")
    with open(lockp, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        fresh = json.load(open(a.scenes, encoding="utf-8"))
        fscenes = fresh["scenes"] if isinstance(fresh, dict) else fresh
        tgt = next((x for x in fscenes if int(x.get("id", -1)) == a.sid), None)
        if tgt is None:
            _fail(2, f"сцена {a.sid} исчезла из {a.scenes}, пока шёл рендер")
        tgt["source"] = f"card:{a.kind}"
        tgt["source_query"] = _CARD_QUERY
        tgt["card"] = card
        tmp = a.scenes + ".tmp"
        json.dump(fresh, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, a.scenes)

        journal = json.load(open(jpath, encoding="utf-8")) if os.path.isfile(jpath) else {}
        journal[str(a.sid)] = dict(card, duration=dur, file=out_mp4,
                                   rendered=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(journal, open(jpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"готово за {took:.1f} с: {out_mp4} ({got:.2f} с), постер {poster}")
    if moved:
        print("прежний кадр сцены убран в cards/replaced/: " + ", ".join(moved))
    print(f"источник сцены: card:{a.kind} — фетч за ней не пойдёт, в видео-лид "
          f"не считается, эффекты на карточку не лягут")


if __name__ == "__main__":
    main()
