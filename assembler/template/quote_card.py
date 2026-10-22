# -*- coding: utf-8 -*-
"""ЦИТАТА-ЛОСКУТ В БОЕВОМ СБОРЩИКЕ — обёртка над fullcycle/quote_paper.py.

Зачем отдельный файл, а не вызов рисовалки напрямую: рисовалка ничего не
знает про сцену. Она рисует кадр по тем словам, что ей дали, и молча рисует
его НЕ ТАК, если слова не влезли или если длительность разошлась со сценой.
Обёртка берёт на себя всё, что относится к ролику: длительность сцены, канал,
проверки и запись в scenes.json.

Пользоваться так (из папки проекта):

    python3 ~/.claude/skills/news-video/template/quote_card.py \
        planeta.scenes.json 58 \
        --text "Садиться втроём. А если не получится — значит, не судьба" \
        --accent "не судьба" \
        --kick "Вашингтон · 21.10.2026" --title "ЧТО СКАЗАЛ ТРАМП" \
        --author "Дональд Трамп" --source "Белый дом, журналистам"

Делает ровно это:
  1. читает сцену → длительность и канал;
  2. гонит ПЯТЬ проверок ДО рендера (они ниже, каждая со своим кодом выхода);
  3. рисует images/scene_NNN.mp4 РОВНО на duration_sec сцены + постер
     cards/scene_NNN.jpg для глаз;
  4. убирает прежний кадр сцены в cards/replaced/ (не удаляет — вернуть можно);
  5. ставит сцене source «card:quote» и пишет журнал cards/cards.json.

ПОЧЕМУ source «card:quote», а не «own»: это ШТАТНАЯ ДВЕРЬ для всего арсенала
второго сборщика. Любой source, начинающийся на «card», означает для сит:
кадр рисуется у нас, в веб за ним не ходить, запросом его не считать, в
видео-лид не записывать, эффекты на него не класть. Следующему элементу
(bullets, forces, timeline, карта) хватит своей рисовалки — сита править уже
не придётся.
"""
import argparse, fcntl, json, os, shutil, subprocess, sys, time

# ПОЧЕМУ У КАРТОЧКИ НЕПУСТОЙ `source_query` (2026-10-22, улов `usuario-ec`):
# гард облака «Check classification» считает scenes.json НЕклассифицированным,
# если у сцены пусто в `source_query`, и прогон падал на setup за 5 секунд с
# «scenes.json не классифицирован и секрета CLAUDE_CODE_OAUTH_TOKEN нет» —
# то есть выглядело как проблема с токеном. Гард в .yml тоже научен
# пропускать `card:*`, но данные держим самодостаточными: любое чужое сито,
# проверяющее «пусто ли», на карточке больше не спотыкается. Содержимое не
# читает никто: фетч и линтер смотрят только на `source.startswith("card")`.
_CARD_QUERY = "карточка цитаты — кадр рисуется локально, фетч не нужен"

SKILL = os.path.dirname(os.path.abspath(__file__))
FULLCYCLE = os.path.join(os.path.dirname(SKILL), "fullcycle")

# Канал → вотермарка. Канал берётся из шапки scenes.json («channel»), иначе из
# имени папки проекта. Гоча вкладки-автора, 21.10: в рисовалке вотермарка по
# умолчанию «ДИПЛОМАТИЯ СИЛЫ», и на ПЛАНЕТЕ её надо передавать явно — иначе
# ролик уезжает с чужим именем канала в углу.
WM = {
    "ПЛАНЕТА": "ПЛАНЕТА",
    "ОЛЬКА": "ОЛЬКА",
    "ДИПЛОМАТИЯ СИЛЫ": "ДИПЛОМАТИЯ СИЛЫ",
    "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО": "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО",
    "5 МИНУТ": "5 МИНУТ",
}

# --- зеркало раскладки quote_paper.py --------------------------------------
# Эти числа ПОВТОРЯЮТ рисовалку (fullcycle/quote_paper.py): ширина лоскута,
# поля, кегль, шаг строки. Иначе проверку «влез ли текст» делать не на чем —
# рисовалка просто обрежет лишнее и не скажет ни слова. Разъедутся числа —
# разъедется и проверка, поэтому они собраны здесь одним блоком с именами как
# там. Проверено на версии рисовалки от 21.10.2026.
PAPER_W_FRAC, PAPER_H = 0.76, 560
PAPER_Y0, PAD, FSIZE, LINE_STEP, TEXT_Y_OFF = 330, 86, 58, 76, 92
AUTHOR_GAP, BOTTOM_KEEP = 26, 54

# Расстановка карточек по ролику (норма пользователя 22.10): одна на 15 сцен,
# между соседними не меньше MIN_GAP сцен.
PER_SCENES, MIN_GAP = 15, 8


def _fail(code, *lines):
    print("\n".join(lines), file=sys.stderr)
    sys.exit(code)


def _wrap(text, font, maxw):
    """Тот же перенос, что в рисовалке: по пробелам, по ширине строки."""
    lines, cur = [], ""
    for w in text.split(" "):
        probe = (cur + " " + w).strip()
        if font.getlength(probe) > maxw and cur:
            lines.append(cur)
            cur = w
        else:
            cur = probe
    lines.append(cur)
    return lines


def _channel(scenes_path, data):
    ch = (data.get("channel") or "").strip()
    if ch:
        return ch
    up = os.path.abspath(scenes_path).upper()
    for name in WM:
        if name.upper().replace(" ", "") in up.replace(" ", "").replace("-", ""):
            return name
    return ""


def main():
    ap = argparse.ArgumentParser(description="цитата-лоскут на сцену ролика")
    ap.add_argument("scenes")
    ap.add_argument("sid", type=int)
    ap.add_argument("--text", required=True, help="сама цитата, без кавычек")
    ap.add_argument("--accent", default="", help="фраза под маркером (целиком в одной строке)")
    ap.add_argument("--kick", default="", help="кикер: место · дата")
    ap.add_argument("--title", default="", help="короткий заголовок над лоскутом")
    ap.add_argument("--author", default="", help="кто сказал; закадровый текст автора — без автора")
    ap.add_argument("--source", default="", help="первоисточник (SOURCES.md), можно пустым")
    ap.add_argument("--images", default="images")
    ap.add_argument("--anim", type=float, default=2.0, help="секунд рисовать покадрово")
    ap.add_argument("--tail-zoom", type=float, default=0.06)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--watermark", default="", help="перебить канал вручную")
    ap.add_argument("--dry-run", action="store_true", help="только проверки, без рендера")
    ap.add_argument("--force", action="store_true", help="не падать на повторе фразы")
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
                 "тоже не видно. Передай --watermark ЯВНО, иначе в углу встанет "
                 "«ДИПЛОМАТИЯ СИЛЫ» (значение рисовалки по умолчанию).")

    sys.path.insert(0, FULLCYCLE)
    sys.path.insert(0, SKILL)
    try:
        import style_cards as sc
        import quote_paper as qp
    except Exception as e:                       # в облаке этого файла нет — и не надо
        _fail(3, f"не загрузить рисовалку из {FULLCYCLE}: {e}")

    # --- ПРОВЕРКА 1: текст влезает в лоскут --------------------------------
    font = sc._f(sc.F_HEAD, FSIZE)
    pw = int(sc.W * PAPER_W_FRAC)
    maxw = pw - 2 * PAD
    lines = _wrap(a.text, font, maxw)
    room = PAPER_H - TEXT_Y_OFF - BOTTOM_KEEP - (AUTHOR_GAP + 34 if a.author else 0)
    n_max = max(1, int(room // LINE_STEP) + 1)
    if len(lines) > n_max:
        _fail(2,
              f"цитата не влезает в лоскут: {len(lines)} строк, помещается {n_max}.",
              f"  строки: " + " / ".join(lines),
              "  укороти текст примерно на "
              f"{sum(len(l) for l in lines[n_max:]) + 1} знаков "
              "(лоскут не растягивается — это лист бумаги, а не плашка).")

    # --- ПРОВЕРКА 2: акцент попал в ОДНУ строку ----------------------------
    # Гоча вкладки-автора, поймана живьём 21.10: рисовалка ищет акцент уже в
    # РАЗБИТОЙ строке (`if accent in ln`). Фраза, которую порвал перенос,
    # маркера не получает — и ни ошибки, ни предупреждения не будет.
    if a.accent:
        if a.accent not in a.text:
            _fail(2, f"акцента «{a.accent}» нет в тексте цитаты — маркер будет нечем чертить")
        if not any(a.accent in ln for ln in lines):
            best = ""
            for ln in lines:                     # что из акцента целиком влезло в строку
                cand = [p for p in _pieces(a.accent) if p in ln]
                if cand:
                    longest = max(cand, key=len)
                    if len(longest) > len(best):
                        best = longest
            _fail(2,
                  f"акцент «{a.accent}» разорван переносом строки — маркера не будет, "
                  "и рисовалка об этом не скажет.",
                  "  строки: " + " / ".join(lines),
                  (f"  возьми кусок покороче, например «{best}»" if best else
                   "  возьми кусок покороче — он должен целиком лежать в одной строке"))

    # --- ПРОВЕРКА 3: фраза не повторяется в ролике -------------------------
    jpath = os.path.join("cards", "cards.json")
    journal = json.load(open(jpath, encoding="utf-8")) if os.path.isfile(jpath) else {}
    for sid_s, rec in journal.items():
        if int(sid_s) != a.sid and rec.get("text", "").strip() == a.text.strip():
            msg = (f"эта же фраза уже стоит на сцене {sid_s} — две одинаковые карточки "
                   "в одном ролике читаются как склейка.")
            if not a.force:
                _fail(2, msg, "  снимается ключом --force, если так и задумано")
            print("ВНИМАНИЕ:", msg)

    # --- ПРОВЕРКА 4: плотность и расстановка ------------------------------
    # Норма пользователя (22.10): ОДНА карточка на 15 сцен, допуск ±1; между
    # двумя карточками не меньше 8 сцен, две подряд — никогда. Считается от
    # числа сцен ролика, а не на глаз, поэтому считает инструмент.
    others = sorted(int(x.get("id", 0)) for x in scenes
                    if str(x.get("source", "")).startswith("card")
                    and int(x.get("id", -1)) != a.sid)
    norm = max(1, round(len(scenes) / PER_SCENES))
    near = [i for i in others if abs(i - a.sid) < MIN_GAP]
    if near:
        msg = (f"карточка слишком близко к соседней (сцены {', '.join(map(str, near))}): "
               f"между карточками держим не меньше {MIN_GAP} сцен, две подряд — никогда.")
        if not a.force:
            _fail(2, msg, "  выбери сцену подальше или сними ключом --force")
        print("ВНИМАНИЕ:", msg)
    over = len(others) + 1 - (norm + 1)
    if over > 0:
        print(f"ВНИМАНИЕ: карточек станет {len(others) + 1} при норме {norm} (+1 допуск) "
              f"на {len(scenes)} сцен — это на {over} больше коридора")

    print(f"сцена {a.sid}: {dur:.2f} с, канал {channel}, строк {len(lines)}/{n_max}, "
          f"маркер: {'да' if a.accent else 'нет'}; "
          f"карточек в ролике станет {len(others) + 1} из нормы {norm} "
          f"({len(scenes)} сцен)")
    if a.dry_run:
        print("--dry-run: проверки пройдены, ничего не нарисовано")
        return

    # --- рендер ------------------------------------------------------------
    os.makedirs(a.images, exist_ok=True)
    os.makedirs(os.path.join("cards", "replaced"), exist_ok=True)
    out_mp4 = os.path.join(a.images, f"scene_{a.sid:03d}.mp4")
    poster = os.path.join("cards", f"scene_{a.sid:03d}.jpg")

    kwargs = dict(kick=a.kick, title=a.title, text=a.text, author=a.author,
                  source=a.source, accent=a.accent or None, watermark=watermark,
                  seed=a.seed)
    t0 = time.time()
    qp.quote_paper(out=poster, **kwargs)         # постер — он же проверка глазами
    # ВАЖНО: fps БОЕВОЙ (30), а не 25 как по умолчанию у рисовалки — сборщик
    # клипов работает на 30, и смешение частот в concat уже однажды растянуло
    # готовый ролик на 20%.
    sc.render_anim(qp.quote_paper, kwargs, dur, out_mp4, fps=30,
                   anim_seconds=a.anim, tail_zoom=a.tail_zoom, sfx_out=False)
    took = time.time() - t0

    # --- ПРОВЕРКА 4: длительность совпала со сценой ------------------------
    # Клип длиннее сцены больше чем на секунду — и _pick_start() начнёт его с
    # середины: пропадёт и появление лоскута, и прочерчивание маркера. Молча.
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", out_mp4], capture_output=True, text=True)
    got = float((r.stdout or "0").strip() or 0)
    if abs(got - dur) > 0.2:
        _fail(4, f"длительность разошлась: клип {got:.2f} с, сцена {dur:.2f} с. "
                 "Разница больше 0,2 с — сборщик начнёт клип не с начала. Файл оставлен, "
                 f"пересними: {out_mp4}")

    # --- старый кадр сцены в сторону ---------------------------------------
    # Иначе в images/ лежат и scene_NNN.jpg, и scene_NNN.mp4: сборщик возьмёт
    # mp4 (его расширение первое в списке), а счётчик видео-лида берёт первый
    # файл, какой вернёт glob — то есть как повезёт.
    moved = []
    for ext in ("jpg", "jpeg", "png", "webp", "mov"):
        p = os.path.join(a.images, f"scene_{a.sid:03d}.{ext}")
        if os.path.exists(p):
            shutil.move(p, os.path.join("cards", "replaced", os.path.basename(p)))
            moved.append(os.path.basename(p))

    # --- сцена и журнал ----------------------------------------------------
    # ПЕРЕЧИТЫВАЕМ ФАЙЛ ПЕРЕД ЗАПИСЬЮ И ПРАВИМ ТОЛЬКО СВОЮ СЦЕНУ (2026-10-22,
    # улов `usuario-ec`). Раньше писался объект, прочитанный при СТАРТЕ рендера:
    # карточка держит его 30-60 секунд, и всё, что вкладка исправила в
    # scenes.json за это время (переписанные по линтеру запросы соседних сцен),
    # молча откатывалось. Живой случай: откатились 9 починенных мин, в облако
    # уехали запросы с минами, ошибки не было ни одной — заметили только по
    # тому, что линт вдруг снова дал те же 9 мин. Та же гонка между двумя
    # карточками, запущенными фоном пачкой, поэтому ещё и замок на файл.
    card = {k: v for k, v in dict(
        kind="quote_paper", text=a.text, accent=a.accent, kick=a.kick,
        title=a.title, author=a.author, src=a.source, watermark=watermark,
        anim=a.anim, seed=a.seed).items() if v not in ("", None)}
    scene["source"] = "card:quote"
    scene["source_query"] = _CARD_QUERY
    scene["card"] = card

    lockp = os.path.join("cards", ".scenes.lock")
    with open(lockp, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        fresh = json.load(open(a.scenes, encoding="utf-8"))
        fscenes = fresh["scenes"] if isinstance(fresh, dict) else fresh
        tgt = next((x for x in fscenes if int(x.get("id", -1)) == a.sid), None)
        if tgt is None:
            _fail(2, f"сцена {a.sid} исчезла из {a.scenes}, пока шёл рендер")
        tgt["source"] = "card:quote"
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
    print("источник сцены: card:quote — фетч за ней не пойдёт, в видео-лид не "
          "считается, эффекты на бумагу не лягут")
    done = sorted(int(x.get("id", 0)) for x in scenes
                  if str(x.get("source", "")).startswith("card"))
    print(f"карточки ролика: {', '.join(map(str, done))} — {len(done)} из нормы {norm} "
          f"({len(scenes)} сцен, одна на {PER_SCENES})")


def _pieces(s):
    """Все связные куски фразы по словам — чтобы подсказать влезающий акцент."""
    ws = s.split(" ")
    out = []
    for i in range(len(ws)):
        for j in range(i + 1, len(ws) + 1):
            out.append(" ".join(ws[i:j]))
    return out


if __name__ == "__main__":
    main()
