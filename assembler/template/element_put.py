#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОБЩАЯ ДВЕРЬ ДЛЯ ЭЛЕМЕНТОВ АРСЕНАЛА — ОДИН ИНСТРУМЕНТ НА ВСЕ ВИДЫ.

Повод (06.11). Он называет элементы по номерам полки библиотеки эффектов
один за другим — A34, A35, A68, A69, A56, A73, A64, A40, A41, A4, A5, A6 —
и требует: «сделать эти элементы обязательными при сборке». Под каждый
заводить свой ключ в `card_put.py` и свою ветку кода — это день работы и
двенадцать мест, где правка может не доехать. Поэтому дверь ОДНА, а элемент
— строка в таблице `ЭЛЕМЕНТЫ` ниже.

Что делает: кладёт задание в `cards/queue/` (считает ОБЛАКО, на машине
пользователя не рисуется ничего — его слово 23.10), ставит сцене источник
`card:<вид>`, ведёт тот же журнал `cards/cards.json`, что `quote_card.py` и
`style_card.py`. Рисует задание `fullcycle/render_cards.py` в прогоне
`cards-render` — тем же кодом, что витрина арсенала.

    python3 element_put.py <scenes.json> <сцена> <код или вид> [ключи]

Примеры:
    # A56 — стена улик: от двух до шести снимков с подписями
    python3 element_put.py planeta.scenes.json 23 A56 \\
        --shot "images/scene_004.jpg=Встреча 12 октября" \\
        --shot "images/scene_017.jpg=Подпись соглашения" \\
        --shot "images/scene_031.jpg=Заявление о срыве"

    # A64 — глубина резкости: фон в боке, герой резкий
    python3 element_put.py planeta.scenes.json 12 A64 \\
        --photo images/scene_012.jpg --title "Кто принимает решение"

    # A4 — столбчатая диаграмма (2-5 величин, цифры НЕ обязательны)
    python3 element_put.py planeta.scenes.json 44 A4 \\
        --title "Кто сколько даёт" --bar "ФРГ=0.9" --bar "ФРАНЦИЯ=0.55" \\
        --bar "ИТАЛИЯ=0.3"

    # A5 — слайдер-диапазон
    python3 element_put.py planeta.scenes.json 51 A5 \\
        --title "Оценки расходятся" --min 0 --max 140 --low 28 --high 135 \\
        --value 60

    # A6 — плакат-инфографика: весь сюжет одним кадром
    python3 element_put.py planeta.scenes.json 8 A6 \\
        --title "Что произошло" --photo images/scene_008.jpg \\
        --fact "три страны=остановили поставки" --bottom "решение отложено"

`--list` печатает таблицу элементов, `--dry-run` только проверяет.
"""
import argparse
import json
import os
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
FULLCYCLE = os.path.join(os.path.dirname(SKILL), "fullcycle")

WM = {
    "ПЛАНЕТА": "ПЛАНЕТА",
    "ОЛЬКА": "ОЛЬКА",
    "ДИПЛОМАТИЯ СИЛЫ": "ДИПЛОМАТИЯ СИЛЫ",
    "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО": "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО",
    "5 МИНУТ": "5 МИНУТ",
}

# ---------------------------------------------------------------------------
# ТАБЛИЦА ЭЛЕМЕНТОВ. Ключ — вид, который встанет сцене как `card:<вид>`.
#   код    — номер на полке библиотеки эффектов (его язык: «внедри A56»)
#   fn     — «модуль.функция» арсенала (режимы frame и clip)
#   script — скрипт второго скилла (режим cli), едет папкой `stv`
#   mode   — frame (кадр оживляем сами) · clip (функция пишет mp4) · cli
#   нужно  — какие ключи обязательны
#   tail   — наезд в хвосте: 0, если у элемента своё движение
# ---------------------------------------------------------------------------
ЭЛЕМЕНТЫ = {
    "wall": {
        "код": "A56", "fn": "cinematic.evidence_wall", "mode": "frame",
        "имя": "стена улик: снимки на булавках, между ними красная нить",
        "нужно": ["shots"], "tail": 0.0,
        "когда": "показать СВЯЗЬ событий: кто с кем, что за чем",
    },
    "dof": {
        "код": "A64", "fn": "cinematic.depth_of_field", "mode": "frame",
        "имя": "глубина резкости: фон в боке, герой резкий, фокус переводится",
        "нужно": ["photo"], "tail": 0.0,
        "когда": "один человек или предмет в кадре, вокруг мешающий фон",
    },
    "poster": {
        "код": "A6", "fn": "poster.poster", "mode": "frame",
        "имя": "плакат-инфографика: весь сюжет одним кадром",
        "нужно": ["title"], "tail": 0.0,
        "когда": "узловая сцена: статус, цифры, место и вывод вместе",
    },
    "bars": {
        "код": "A4", "script": "build_chart_bars.py", "mode": "cli",
        "имя": "столбчатая диаграмма: столбцы растут по очереди",
        "нужно": ["bars"], "tail": 0.0,
        "когда": "сравнение 2-5 величин; доля важнее точного числа",
    },
    "slider": {
        "код": "A5", "script": "build_chart_slider.py", "mode": "cli",
        "имя": "слайдер-диапазон: маркер едет по шкале и встаёт на итоге",
        "нужно": ["slider"], "tail": 0.0,
        "когда": "оценка с разбросом: «от столько-то до столько-то»",
    },
}
КОД_В_ВИД = {v["код"]: k for k, v in ЭЛЕМЕНТЫ.items()}


def _fail(code, *lines):
    for ln in lines:
        if ln:
            print(ln, file=sys.stderr)
    sys.exit(code)


def _pair(raw, what):
    if "=" not in raw:
        _fail(2, f"{what}: нужно «левое=правое», а пришло «{raw}»")
    a, b = raw.split("=", 1)
    return a.strip(), b.strip()


def _channel(scenes_path, data):
    ch = str((data or {}).get("channel") or "").strip()
    if ch:
        return ch
    low = scenes_path.replace("\\", "/").lower()
    for name in ("планета", "олька", "5 минут", "дипломатия силы",
                 "перевод с дипломатического"):
        if name in low:
            return name.upper()
    return ""


def _layout(n):
    """Места для снимков стены улик. Рисовалка ждёт (путь, x, y, наклон,
    подпись) и САМА ничего не раскладывает — поэтому раскладка здесь.
    Сетка держит поля 150 px и не залезает на подвал (FOOT_Y 1006):
    карточка 324x258, два ряда по три."""
    cols = 3 if n > 2 else n
    rows = 1 if n <= 3 else 2
    x0, y0 = 240, 250 if rows == 2 else 380
    dx, dy = 560, 330
    tilt = (-4, 3, -2, 4, -3, 2)
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        out.append((x0 + c * dx - (0 if rows == 2 else 0),
                    y0 + r * dy, tilt[i % len(tilt)]))
    return out



def _chislo(v):
    """Число из ключа командной строки: запятая и пробелы прощаются."""
    t = str(v).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "«%s» — не число. Шкала слайдера задаётся ТОЛЬКО числами: "
            "--min 0 --max 100 --value 38.4 (запятая тоже годится). "
            "Словесный диапазон сюда не кладётся — слова идут в --sub и "
            "--caption." % v)


def main():
    ap = argparse.ArgumentParser(description="элемент арсенала на сцену ролика")
    ap.add_argument("scenes", nargs="?", default="")
    ap.add_argument("sid", nargs="?", type=int)
    ap.add_argument("what", nargs="?", default="", help="код полки (A56) или вид (wall)")
    ap.add_argument("--photo", default="")
    ap.add_argument("--shot", action="append", default=[],
                    help="стена улик: «путь.jpg=подпись», от 2 до 6 раз")
    ap.add_argument("--bar", action="append", default=[],
                    help="диаграмма: «подпись=доля 0..1», от 2 до 5 раз")
    ap.add_argument("--fact", action="append", default=[],
                    help="плакат: «что=значение», до 4 раз")
    ap.add_argument("--kick", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--sub", default="")
    ap.add_argument("--bottom", default="", help="плакат: лента-вывод внизу")
    ap.add_argument("--source", default="")
    ap.add_argument("--caption", default="",
                    help="диаграмма: подпись-ВЫВОД под числом (у слайдера это "
                         "`caption`, а подпись диапазона над шкалой — --sub)")
    # ШКАЛА ПРИНИМАЕТ ТОЛЬКО ЧИСЛА, И ТЕПЕРЬ ОНА ОБ ЭТОМ ГОВОРИТ (08.11,
    # улов `usuario-45`): словесный диапазон падал голым «invalid float
    # value» от argparse, и было непонятно, чего от тебя хотят. Заодно
    # принимаем запятую как десятичный разделитель — его тексты пишутся
    # с запятой («4,36»), и спотыкаться на этом незачем.
    ap.add_argument("--min", type=_chislo, default=0.0,
                    help="слайдер: НАЧАЛО шкалы, только число (0, 12.5, 4,36)")
    ap.add_argument("--max", type=_chislo, default=100.0,
                    help="слайдер: КОНЕЦ шкалы, только число")
    ap.add_argument("--low", type=_chislo, default=None,
                    help="слайдер: нижняя граница подсвеченного диапазона, число")
    ap.add_argument("--high", type=_chislo, default=None,
                    help="слайдер: верхняя граница диапазона, число")
    ap.add_argument("--value", type=_chislo, default=None,
                    help="слайдер: где стоит маркер, число")
    ap.add_argument("--watermark", default="")
    ap.add_argument("--anim", type=float, default=0.0,
                    help="секунд рисовать покадрово; 0 — вся сцена")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list or not a.scenes:
        print("ЭЛЕМЕНТЫ АРСЕНАЛА В БОЕВОЙ ДВЕРИ (код · вид · режим · чем рисуется):")
        for вид, el in ЭЛЕМЕНТЫ.items():
            print("  %-4s card:%-8s %-5s %s"
                  % (el["код"], вид, el["mode"], el["имя"]))
            print("        когда: %s" % el["когда"])
        return 0

    if a.sid is None or not a.what:
        _fail(2, "нужно: element_put.py <scenes.json> <сцена> <код или вид>")

    вид = КОД_В_ВИД.get(a.what.upper(), a.what.lower())
    el = ЭЛЕМЕНТЫ.get(вид)
    if el is None:
        _fail(2, f"элемента «{a.what}» в этой двери нет.",
              "  есть: " + ", ".join("%s (%s)" % (v["код"], k)
                                     for k, v in ЭЛЕМЕНТЫ.items()),
              "  цитаты ставит quote_card.py, разборы — style_card.py, "
              "карты и плёнку — fullcycle/card_put.py")

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
                 "тоже не видно. Передай --watermark, иначе в углу встанет "
                 "ЧУЖОЕ имя канала.")

    # --- собираем задание под конкретный элемент --------------------------
    kwargs, cfg, script = {}, None, el.get("script", "")
    if вид == "wall":
        shots = [_pair(x, "снимок стены улик") for x in a.shot]
        if not 2 <= len(shots) <= 6:
            _fail(2, "стене улик нужно от 2 до 6 снимков: "
                     "--shot «путь.jpg=подпись»",
                  f"  пришло {len(shots)}")
        for p, _c in shots:
            if not os.path.isfile(p):
                _fail(2, f"нет файла снимка: {p}")
        места = _layout(len(shots))
        kwargs = {
            "shots": [[p, x, y, ang, cap]
                      for (p, cap), (x, y, ang) in zip(shots, места)],
            "kick": a.kick, "title": a.title, "sub": a.sub,
        }
    elif вид == "dof":
        if not a.photo or not os.path.isfile(a.photo):
            _fail(2, "глубине резкости нужен кадр: --photo путь.jpg",
                  f"  {'файла нет: ' + a.photo if a.photo else 'ключ не передан'}")
        kwargs = {"photo": a.photo, "kick": a.kick, "title": a.title,
                  "sub": a.sub}
    elif вид == "poster":
        if not a.title:
            _fail(2, "плакату нужен заголовок: --title «…»")
        facts = [_pair(x, "факт плаката") for x in a.fact]
        kwargs = {"kick": a.kick, "title": a.title, "subtitle": a.sub,
                  "hero_photo": a.photo, "bottom": a.bottom,
                  "source": a.source,
                  "facts": [{"label": k, "value": v} for k, v in facts]}
        if a.photo and not os.path.isfile(a.photo):
            _fail(2, f"нет файла кадра: {a.photo}")
    elif вид == "bars":
        bars = [_pair(x, "столбец диаграммы") for x in a.bar]
        if not 2 <= len(bars) <= 5:
            _fail(2, "диаграмме нужно от 2 до 5 столбцов: --bar «подпись=0.6»",
                  f"  пришло {len(bars)}")
        rows = []
        for label, val in bars:
            try:
                v = float(str(val).replace(",", "."))
            except ValueError:
                _fail(2, f"доля столбца «{label}» не число: {val}",
                      "  это ОТНОСИТЕЛЬНАЯ высота 0..1, точность не нужна")
            if not 0 < v <= 1.0:
                _fail(2, f"доля столбца «{label}» должна быть в 0..1, а не {v}")
            rows.append({"label": label.upper(), "value": v})
        # ЦВЕТ СТОЛБЦА ОБЯЗАТЕЛЕН: `build_chart_bars.py` читает `b["color"]`
        # прямым ключом и без него падает KeyError — то есть сцена пришла бы
        # пустой, а прогон «успешным». Цвета свои задавать не просим (его
        # слово про графику: «не надо какие-то точности, нам наглядно надо»),
        # берём ряд от красного к серому — он читается на любом фоне канала.
        ЦВЕТА = ("B92526", "EABD23", "8C8C92", "3E6FB0", "6E6E74")
        for i, r in enumerate(rows):
            r.setdefault("color", ЦВЕТА[i % len(ЦВЕТА)])
        cfg = {"title": a.title, "caption": a.caption,
               "seconds": round(dur, 2), "bars": rows}
    elif вид == "slider":
        # ИМЕНА ПОЛЕЙ — РОВНО КАК У РИСОВАЛКИ (06.11, улов `usuario-84`):
        # `build_chart_slider.py` читает `marker_value` прямым ключом и падает
        # KeyError, а `range_label` (подпись диапазона над шкалой) и `caption`
        # (вывод под числом) у неё РАЗНЫЕ поля — я свалил их в одно.
        # `marker_display` без нас выводил бы голое число.
        val = a.value if a.value is not None else a.max / 2.0
        if not a.max > a.min:
            _fail(2, f"у слайдера --max ({a.max}) должен быть больше --min ({a.min})")
        _disp = ("%d" % val) if float(val).is_integer() else ("%.1f" % val)
        cfg = {"title": a.title, "min": a.min, "max": a.max,
               "low": a.low if a.low is not None else a.min,
               "high": a.high if a.high is not None else a.max,
               "marker_value": val, "marker_display": _disp,
               "seconds": round(dur, 2),
               "range_label": a.sub or "РАЗБРОС ОЦЕНОК",
               "caption": a.caption, "source": a.source}

    anim = round(dur, 2) if a.anim <= 0 else round(min(a.anim, dur), 2)

    # --- расстановка: та же норма и зазор, что у остальных карточек -------
    # Считаем ОДНИМ списком со цитатами и разборами: зритель видит не «цитаты
    # и элементы», а рисованные кадры (решение 22.10). Числа берём из
    # `style_card.py`, чтобы не разъехались.
    sys.path.insert(0, SKILL)
    _ob = None
    try:
        import obyazatelno as _ob
        MIN_GAP, НОРМА = _ob.зазор(len(scenes)), _ob.норма(len(scenes))
    except Exception:
        MIN_GAP, НОРМА = 8, max(1, round(len(scenes) / 15))
    others = {int(x.get("id", 0)): str(x.get("source", ""))[5:]
              for x in scenes
              if str(x.get("source", "")).startswith("card:")
              and int(x.get("id", -1)) != a.sid}
    def _gap_to(_other_sid):
        try:
            return _ob.зазор_вида(вид, len(scenes), others.get(_other_sid))
        except Exception:
            return MIN_GAP
    near = [i for i in others if abs(i - a.sid) < _gap_to(i)]
    if near:
        print("ВНИМАНИЕ: рядом уже стоят карточки (сцены %s) — держим %d сцен "
              "между любыми рисованными кадрами"
              % (", ".join(map(str, sorted(near))), MIN_GAP))

    print("сцена %d: %.2f с, канал %s, элемент %s (card:%s), режим %s; "
          "рисованных кадров в ролике станет %d при норме %d (%d сцен, "
          "зазор %d)"
          % (a.sid, dur, channel, el["код"], вид, el["mode"],
             len(others) + 1, НОРМА, len(scenes), MIN_GAP))
    if a.dry_run:
        print("--dry-run: проверки пройдены, задание не записано")
        return 0

    # --- в очередь (на машине не рисуется ничего) -------------------------
    import cards_queue as cq
    _card = {k: v for k, v in dict(
        kind=вид, код=el["код"], kick=a.kick, title=a.title,
        src=a.source, watermark=watermark, anim=anim).items()
        if v not in ("", None, [])}
    jpath = cq.queue(a.scenes, a.sid, вид, dur, watermark, channel,
                     dict(kwargs), anim=anim, tail_zoom=el.get("tail", 0.0),
                     card=_card)
    # режим и скрипт/функция дописываем в задание: `cards_queue` их не знает,
    # а `render_cards` без них не поймёт, чем рисовать.
    job = json.load(open(jpath, encoding="utf-8"))
    job["mode"] = el["mode"]
    if el["mode"] == "cli":
        job["script"] = script
        job["cfg"] = cfg
        job["kwargs"] = {}
    else:
        job["view"] = el["fn"]          # полное «модуль.функция» для реестра
    json.dump(job, open(jpath, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    cq.report(jpath, a.sid, вид, a.scenes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
