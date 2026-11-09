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

    # A5 — слайдер-диапазон (--unit приписывает единицу к числу под маркером)
    python3 element_put.py planeta.scenes.json 51 A5 \\
        --title "Оценки расходятся" --min 0 --max 140 --low 28 --high 135 \\
        --value 60 --unit "млрд евро"

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

# ПОРОГ ЯРКОСТИ ПЛАКАТА — ЧИСЛОМ И НА ВИДУ (08.11 замер, 09.11 вынесен в
# константу). Годные кандидаты шли от 100 из 255; ниже плакат притемняет окно
# под фотографией и кадр в нём неотличим от пустого чёрного поля.
ЯРКОСТЬ_ПЛАКАТА = 100
# Наш предел осветления — ×1,6: так поднимает фото карточка-досье
# (`fullcycle/cinematic.py`, замер 29.10 по его слову «надо немножечко более
# светло»), выше уже выбеливает лица. По нему и считаем, спасёт ли осветление.
ПРЕДЕЛ_ОСВЕТЛЕНИЯ = 1.6

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
    ap.add_argument("--feature", action="append", default=[],
                    help="плакат: строка правой колонки «особенности», до 4 раз; "
                         "без неё фото занимает и правую треть")
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
    # ЕДИНИЦА ИЗМЕРЕНИЯ БЫЛА ТОЛЬКО У ДВОЙНИКА (09.11, улов `usuario-e6`).
    # `card_put.py` знает `--unit` с самого начала, а эта дверь — нет, и
    # слайдер A5 (обязательный элемент) уезжал с голым числом: «60» вместо
    # «60 млрд евро». Ключ назван и подсказан ОДИН В ОДИН с двойником, иначе
    # вкладка будет помнить два разных имени для одного и того же.
    ap.add_argument("--unit", default="", help="график: единица измерения, например « млн т»")
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
        # ЗАГОЛОВОК СТЕНЕ УЛИК ОБЯЗАТЕЛЕН (08.11, его слово по сцене 52:
        # «52 это что? Где какая-то хоть надпись там? Про что эта картинка?»).
        # Без `--title`/`--kick` верхние две трети кадра остаются ПУСТЫМИ, а
        # три снимка внизу без общей мысли читаются как случайный набор.
        if not (a.title or a.kick):
            _fail(2, "стене улик нужен ЗАГОЛОВОК: --title «…» (и по желанию "
                     "--kick «…»)",
                  "  без него верх кадра пустой, а снимки внизу выглядят",
                  "  случайным набором — именно за это и прилетело 08.11.")
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
        # КАДР ПЛАКАТУ ОБЯЗАТЕЛЕН (08.11, увидел пользователь на дашборде
        # 8791, сцена 68): без `hero_photo` рисовалка оставляет на месте
        # фотографии ПУСТОЙ СЕРЫЙ ПРЯМОУГОЛЬНИК во всю правую половину, а
        # прогон отчитывается успехом. Его слова: «там тоже наш эффект, в
        # середине должна быть какая-то картинка. Картинки нет. Серое пятно».
        # Плакат без кадра не бывает: это «весь сюжет одним кадром».
        # И КАДР ДОЛЖЕН БЫТЬ СВЕТЛЫМ (08.11, улов `usuario-45` через полчаса
        # после первой правки). Плакат притемняет окно под фотографию, и
        # ночной снимок (средняя яркость 54 из 255) выглядит в нём ровно как
        # «фото не подставилось» — тот же чёрный прямоугольник, из-за
        # которого пользователь и написал замечание. Годные кандидаты шли от
        # 100. Поэтому проверка «файл есть» без проверки яркости бесполезна.
        if a.photo and os.path.isfile(a.photo):
            try:
                from PIL import Image, ImageStat
                _im = Image.open(a.photo).convert("L")
                _br = ImageStat.Stat(_im).mean[0]
                if _br < ЯРКОСТЬ_ПЛАКАТА:
                    # ЧИСЛА В САМ ОТКАЗ (09.11, просьба вкладки): без них
                    # вкладка мерила яркость `ImageStat` руками, чтобы
                    # понять, спасёт ли осветление или нужен другой кадр.
                    # Теперь видно сразу: яркость, порог, нехватка и во
                    # сколько раз надо поднять против нашего предела ×1,6.
                    _раз = ЯРКОСТЬ_ПЛАКАТА / max(_br, 1.0)
                    _вердикт = (
                        "Осветление СПАСЁТ: нужно усиление ×%.2f, наш предел "
                        "×%.1f." % (_раз, ПРЕДЕЛ_ОСВЕТЛЕНИЯ)
                        if _раз <= ПРЕДЕЛ_ОСВЕТЛЕНИЯ else
                        "Осветление НЕ СПАСЁТ: нужно ×%.2f при пределе ×%.1f "
                        "(выше — выбеливает лица). Бери другой кадр: день, "
                        "освещённое помещение, огни в кадре."
                        % (_раз, ПРЕДЕЛ_ОСВЕТЛЕНИЯ))
                    _fail(2, "кадр СЛИШКОМ ТЁМНЫЙ для плаката: яркость %.0f "
                             "при пороге %d из 255 (не хватает %.0f)"
                             % (_br, ЯРКОСТЬ_ПЛАКАТА, ЯРКОСТЬ_ПЛАКАТА - _br),
                          "  Плакат притемняет окно под фотографией, и тёмный",
                          "  снимок в нём неотличим от пустого чёрного поля.",
                          "  " + _вердикт,
                          "  Кадр: %s" % a.photo)
            except ImportError:
                pass
            except Exception:
                pass
        if not a.photo:
            _fail(2, "плакату-инфографике нужен КАДР: --photo images/scene_NNN.jpg",
                  "  без него на месте фотографии останется пустое серое поле,",
                  "  а прогон отчитается успехом. Возьми кадр этой же сцены",
                  "  (или вынь его из клипа: ffmpeg -ss 80% длительности).")
        facts = [_pair(x, "факт плаката") for x in a.fact]
        # ПРАВАЯ КОЛОНКА ПЛАКАТА (08.11): `--feature «текст»` до четырёх раз.
        # Без неё фотография сама занимает правую треть — пустого места в
        # кадре не остаётся ни при каком раскладе.
        kwargs = {"kick": a.kick, "title": a.title, "subtitle": a.sub,
                  "hero_photo": a.photo, "bottom": a.bottom,
                  "source": a.source,
                  "features": [{"text": x} for x in (a.feature or [])[:4]],
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
        # ЦВЕТА СТОЛБЦОВ — ПО КАНАЛУ, А НЕ ОДИН НАБОР НА ВСЕХ (08.11, его
        # слово, повторено второй день: «на четвёртой сцене графики, столбики
        # — одинаковые цвета и на „5 минут“, и на „Планете“. Это узнаваемо.
        # Надо, чтобы хотя бы немножко визуально отличались»). Набор серий у
        # каналов уже есть (`style_cards.CHANNEL_SERIES`), но эта дверь его не
        # спрашивала и подставляла жёсткую пятёрку красный-золото-серый —
        # поэтому ролики-близнецы и выглядели одинаково в данных.
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.join(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))), "fullcycle"))
            import style_cards as _sc
            ЦВЕТА = tuple("%02X%02X%02X" % c for c in _sc.series_colors(channel))
            # первый цвет набора — белый (роль «суть»), для столбцов он
            # слишком нейтрален: ставим его последним, чтобы первым шёл
            # фирменный цвет канала
            ЦВЕТА = ЦВЕТА[1:] + ЦВЕТА[:1]
        except Exception:
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
        # ПРАВИЛО ПРОБЕЛА — ТО ЖЕ, ЧТО В `fullcycle/charts.py::_unit` (09.11):
        # у «%», «°», «₽», «$» единица прилипает к числу, у словесной —
        # отделяется пробелом. Своего формата здесь не изобретаем: у двойника
        # `card_put.py` единица уходит в `charts.py` и печатается именно так,
        # а рисовалка слайдера своего поля `unit` не знает вовсе — число под
        # маркером она берёт из `marker_display` готовой строкой.
        if a.unit:
            _disp += (a.unit if a.unit in ("%", "°", "₽", "$") else " " + a.unit)
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
        _кл = _ob.клонов_в(data)
        MIN_GAP, НОРМА = _ob.зазор(len(scenes), _кл), _ob.норма(len(scenes), _кл)
    except Exception:
        MIN_GAP, НОРМА = 8, max(1, round(len(scenes) / 15))
    others = {int(x.get("id", 0)): str(x.get("source", ""))[5:]
              for x in scenes
              if str(x.get("source", "")).startswith("card:")
              and int(x.get("id", -1)) != a.sid}
    def _gap_to(_other_sid):
        try:
            return _ob.зазор_вида(вид, len(scenes), others.get(_other_sid), _кл)
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
