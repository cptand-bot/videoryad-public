#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОБЯЗАТЕЛЬНЫЕ ЭЛЕМЕНТЫ РОЛИКА — ОДИН СПИСОК НА ВСЕ ГЕЙТЫ.

Его прямое слово 06.11, после того как он назвал A34 и A35 на полке
библиотеки эффектов: «Сделать эти элементы обязательными при сборке. И
сейчас дам ещё элементы, которые при сборке дашборда и при сборке видеоряда
должны быть обязательно».

ПОЧЕМУ ОТДЕЛЬНЫМ ФАЙЛОМ, А НЕ СТРОКОЙ В `selfcheck.py`. Элементов будет
больше, называет он их по одному и в разное время, а гейта ДВА: дашборд
(`selfcheck.py`, до того как вкладка даёт адрес) и видеоряд (`ship.sh`, до
необратимой отправки). Пока правило жило бы в двух файлах, оно разъехалось
бы при первой же правке — ровно тот класс «инструментов два, правку получил
один», на котором 02.11 потерялась приёмка `card:timeline`.

ДОБАВИТЬ НОВЫЙ ЭЛЕМЕНТ — ЭТО ОДНА СТРОКА В `ОБЯЗАТЕЛЬНЫЕ` НИЖЕ.

Проверка идёт по `scenes.json`: у рисованного кадра источник `card:<вид>`,
поэтому наличие элемента видно без обращения к файлам и работает одинаково
до фетча, на дашборде и перед сборкой.

    python3 obyazatelno.py <scenes.json> --gate dashboard
    python3 obyazatelno.py <scenes.json> --gate video

Код выхода 1 — обязательного элемента нет; текст отказа говорит, чем его
поставить. `--list` печатает текущий список, `--json` отдаёт машинный ответ.
"""
import argparse
import json
import os
import sys

# Прежние числа расстановки (были константами в `style_card.py` и
# `card_put.py`): норма — одна карточка на 15 сцен, зазор 8 сцен.
PER_SCENES = 15
MIN_GAP_БАЗА = 8

# код — номер на полке библиотеки эффектов (`~/.claude/skills/effects-library`),
# чтобы его «внедри A34» и наш список читались одними и теми же именами.
#
#   view   — что стоит в `source` сцены: `card:<view>`
#   fx     — вместо `view`: вид эффекта в поле `fx` сцены (переходы, кнопки)
#   min    — сколько таких сцен должно быть в ролике
#   gate   — "dashboard" (проверяется и перед дашбордом, и перед сборкой)
#            "video"     (только перед полной сборкой)
#   каналы — None значит ВСЕ каналы; иначе список имён
#   чем    — команда, которой элемент ставится (идёт в текст отказа)
ОБЯЗАТЕЛЬНЫЕ = [
    {
        # ЕДИНСТВЕННЫЙ ПОКА ЭЛЕМЕНТ НЕ-КАРТОЧКА: это ПЕРЕХОД между сценами,
        # он живёт в поле `fx`, а не в `source`. Поэтому у него `fx`, а не
        # `view`, и в норму рисованных кадров он не входит.
        "код": "A73",
        "имя": "засвет: кадр вспыхивает в белое, из вспышки выходит следующий",
        "fx": "flash",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        # sid у `fx_put.py` ПОЗИЦИОННЫЙ, ключа `--sid` он не знает (улов
        # `usuario-a3` 06.11: «unrecognized arguments»).
        "чем": ("python3 ~/.claude/skills/news-video/template/fx_put.py "
                "<scenes.json> <сцена> --kind flash"),
        "когда": ("поворот сюжета: смена темы, после которой идёт вывод. "
                  "Работает на ВСЕХ каналах (06.11), прочие переходы — "
                  "только ПЛАНЕТА"),
    },
    {
        "код": "A35",
        "имя": "цитата-сплит: слева лицо, справа слова",
        "view": "split",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/template/quote_card.py "
                "<scenes.json> <сцена> --photo <лицо.jpg> --text «реплика» "
                "--author «Имя Фамилия» --role «должность на момент заявления»"),
        "когда": ("любое ИМЕННОЕ заявление в тексте: сказано, кто сказал, "
                  "и лицо узнаваемо"),
    },
    {
        "код": "A34",
        "имя": "слабое фото маленьким: снимок в окне, справа факты",
        "view": "photo",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/template/style_card.py "
                "<scenes.json> <сцена> photo --photo <кадр.jpg> "
                "--title «о чём кадр» --item «факт» --item «факт»"),
        "когда": ("кадр заведомо слабый — мелкий, узкий, веб-превью "
                  "телеграма: вместо растяжки на весь экран ставим его "
                  "в окно, а площадь держит текст"),
    },
    # A68/A69 НАЗВАНЫ ИМ СЛЕДОМ, 06.11. Двери у них уже стояли (внедрены
    # 28.10 в составе семи элементов арсенала) — обязательными не были.
    {
        "код": "A68",
        "имя": "лента плёнки вбок: кадры едут и встают на нужном",
        "view": "film",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/fullcycle/card_put.py "
                "<scenes.json> <сцена> film "
                "--images «images/scene_012.jpg,images/scene_031.jpg,images/scene_044.jpg»"),
        "когда": ("перечисление событий или «тогда и сейчас»: от ТРЁХ кадров "
                  "по теме, подписи стоят внутри кадров"),
    },
    {
        "код": "A69",
        "имя": "один кадр в плёнке: академический 1.37, свет проектора",
        "view": "film_frame",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/fullcycle/card_put.py "
                "<scenes.json> <сцена> film_frame --photo <архивный.jpg>"),
        "когда": ("архивный кадр, о котором прямо говорит текст, — подаём "
                  "его как хронику, а не как обычное фото"),
    },
    # ОН НАЗВАЛ ИХ ОДНИМ ПОТОКОМ 06.11: A56, A64, A40, A41, A4, A5, A6.
    # Двери: `pull` и `marker_serif` стояли с 22.10 (`card_put.py`), остальные
    # открыты в тот же день общей дверью `template/element_put.py`.
    {
        "код": "A56",
        "имя": "стена улик: снимки на булавках, красная нить между ними",
        "view": "wall",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/template/element_put.py "
                "<scenes.json> <сцена> A56 --shot «кадр.jpg=подпись» "
                "--shot «кадр.jpg=подпись» (от 2 до 6)"),
        "когда": "показать СВЯЗЬ событий: кто с кем встречался, что за чем шло",
    },
    {
        "код": "A64",
        "имя": "глубина резкости: фон в боке, герой резкий",
        "view": "dof",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/template/element_put.py "
                "<scenes.json> <сцена> A64 --photo <кадр.jpg> --title «о чём»"),
        "когда": ("в кадре один человек или предмет, а вокруг мешающий фон — "
                  "фокус переводится на героя"),
    },
    {
        "код": "A6",
        "имя": "плакат-инфографика: весь сюжет одним кадром",
        "view": "poster",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/template/element_put.py "
                "<scenes.json> <сцена> A6 --title «что произошло» "
                "--photo <кадр.jpg> --fact «что=значение» --bottom «вывод»"),
        "когда": "узловая сцена: статус, цифры, место и вывод вместе",
    },
    {
        "код": "A4",
        "имя": "столбчатая диаграмма: столбцы растут по очереди",
        "view": "bars",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/template/element_put.py "
                "<scenes.json> <сцена> A4 --title «о чём» --bar «ФРГ=0.9» "
                "--bar «ФРАНЦИЯ=0.55»"),
        "когда": ("сравнение 2-5 величин. ТОЧНОСТЬ НЕ НУЖНА (его слово "
                  "28.10): нет цифр — ставим соотношение"),
    },
    {
        "код": "A5",
        "имя": "слайдер-диапазон: маркер едет по шкале и встаёт на итоге",
        "view": "slider",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/template/element_put.py "
                "<scenes.json> <сцена> A5 --title «о чём» --min 0 --max 140 "
                "--low 28 --high 135 --value 60"),
        "когда": "оценка с разбросом: «от столько-то до столько-то»",
    },
    {
        "код": "A40",
        "имя": "ВРЕЗ: спокойная цитата без маркера, кавычка в фоне",
        "view": "pull",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/fullcycle/card_put.py "
                "<scenes.json> <сцена> pull --text «реплика» "
                "--author «Имя» --role «должность»"),
        "когда": ("карточек в ролике много и пестрить нельзя — этот вид не "
                  "спорит с соседними"),
    },
    {
        "код": "A41",
        "имя": "МАЗОК: засечки, гигантская кавычка в фоне, оранжевый мазок",
        "view": "marker_serif",
        "min": 1,
        "gate": "dashboard",
        "каналы": None,
        "чем": ("python3 ~/.claude/skills/news-video/fullcycle/card_put.py "
                "<scenes.json> <сцена> marker_serif --text «реплика» "
                "--accent «фраза под мазком»"),
        "когда": "газетный характер: заявление, которое ведёт сцену",
    },
]


def обязательных_карточек():
    """Сколько РИСОВАННЫХ КАДРОВ ролик обязан содержать (эффекты не считаем:
    они не занимают сцену, а ложатся на её кадр)."""
    return len([e for e in ОБЯЗАТЕЛЬНЫЕ if e.get("view")])


def норма(n_scenes):
    """НОРМА РИСОВАННЫХ КАДРОВ С ПОЛОМ ПО ОБЯЗАТЕЛЬНЫМ (06.11).

    Прежняя норма — одна карточка на 15 сцен (при 70 сценах пять). После
    того как он назвал одиннадцать обязательных элементов, старая норма и
    обязательный список стали противоречить друг другу: инструмент требовал
    поставить одиннадцать и тут же ругался, что их больше нормы. Пол по
    обязательным снимает противоречие и не задирает норму там, где
    обязательных мало.
    """
    return max(1, round(n_scenes / PER_SCENES), обязательных_карточек())


def зазор(n_scenes):
    """ЗАЗОР МЕЖДУ РИСОВАННЫМИ КАДРАМИ — ПО МЕСТУ, А НЕ КОНСТАНТОЙ 8.

    Одиннадцать обязательных кадров при зазоре 8 требуют ролика в 88 сцен —
    а приходят 56-78. Поэтому зазор считается от того, сколько кадров ролик
    ОБЯЗАН вместить: на 70 сценах и 11 обязательных это 5 сцен, на коротком
    ролике ужимается до 3, но не меньше — две карточки через две сцены
    читаются как слайды. Там, где обязательных мало, зазор остаётся прежним.
    """
    need = обязательных_карточек()
    if need <= 1:
        return MIN_GAP_БАЗА
    return max(3, min(MIN_GAP_БАЗА, int(n_scenes / need) - 1))


# СЕМЬИ ВИДОВ (06.11, улов `usuario-a3`). Зазор между карточками зависит от
# того, что видит зритель: две ЦИТАТЫ рядом читаются как слайды, а карта и
# снимок в окне — нет. Это уже было в `fullcycle/card_put.py` и в брифе
# (текст 8, изобразительное 4, между семьями 5), но боевые `style_card.py` и
# `element_put.py` держали ОДИН плоский зазор — и на ролике в 101 сцену
# отбивали законную пару «фото в окне» + «стена улик» через 6 сцен.
ИЗОБРАЗИТЕЛЬНЫЕ = {
    "photo", "wall", "dof", "poster", "bars", "slider", "film", "film_frame",
    "map", "map_regions", "map_dist", "bubbles", "pie", "dossier", "split",
    "slope", "line",
}
ЗАЗОР_ТЕКСТ, ЗАЗОР_ИЗО, ЗАЗОР_МЕЖДУ = 8, 4, 5


def семья(view):
    return "изо" if str(view).strip() in ИЗОБРАЗИТЕЛЬНЫЕ else "текст"


def зазор_вида(view, n_scenes, сосед=None):
    """Сколько сцен держать между этим видом и соседом.

    Общий потолок — `зазор(n_scenes)` (он считается от числа обязательных);
    внутри него работает семейный зазор. Сосед не назван — берём свой
    семейный, он строже всего в своей семье.
    """
    общий = зазор(n_scenes)
    своя = ЗАЗОР_ТЕКСТ if семья(view) == "текст" else ЗАЗОР_ИЗО
    if сосед is not None and семья(сосед) != семья(view):
        своя = ЗАЗОР_МЕЖДУ
    return max(1, min(своя, общий))


def папка_кадра(photo_path):
    """Папка медиатеки, из которой взят снимок, или пустая строка.

    Нужна для проверки «одна папка — одна сцена» (06.11, улов `usuario-c8`):
    на сданном ролике Пентагон стоял на сцене 70 базовым кадром из
    `ВЛАСТЬ-США/ПЕНТАГОН-ВОЗДУХА` и на сцене 74 внутри `card:dof` — фото под
    карточку вкладка взяла из ТОЙ ЖЕ папки. Ни один гейт этого не видел:
    файлы разные по md5, а карточка проверяется как рисованный кадр, не как
    кадр медиатеки.
    """
    p = os.path.realpath(os.path.expanduser(str(photo_path or "")))
    if not p:
        return ""
    low = p.replace("\\", "/")
    for marker in ("/media-library-2/", "/media-library/"):
        if marker in low:
            rest = low.split(marker, 1)[1]
            parts = [x for x in rest.split("/") if x][:-1]   # без имени файла
            if parts and parts[0] == "БАЗА":
                parts = parts[1:]
            return "/".join(parts[:2])
    return ""


def сосед_из_той_же_папки(scenes, sid, photo_path, окно=8):
    """Соседние сцены (±окно), которые берут кадр из ТОЙ ЖЕ папки медиатеки."""
    tag = папка_кадра(photo_path)
    if not tag:
        return []
    out = []
    for s in scenes:
        try:
            i = int(s.get("id", -1))
        except (TypeError, ValueError):
            continue
        if i == int(sid) or abs(i - int(sid)) > окно:
            continue
        q = str(s.get("source_query", "")).replace("\\", "/")
        src = str(s.get("source", ""))
        if src == "local_library" and tag and tag.split("/")[-1].upper() in q.upper():
            out.append(i)
        elif src.startswith("card:"):
            cph = (s.get("card") or {}).get("photo") or ""
            if cph and папка_кадра(cph) == tag:
                out.append(i)
    return sorted(out)


def _scenes(path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("scenes", []), data
    return data, {}


def _channel(meta, path):
    ch = str(meta.get("channel") or "").strip()
    if ch:
        return ch
    low = path.replace("\\", "/").lower()
    for name in ("планета", "олька", "5 минут", "дипломатия силы",
                 "перевод с дипломатического"):
        if name in low:
            return name.upper()
    return ""


def check(scenes, channel="", gate="dashboard"):
    """Чего не хватает. Возвращает список строк отказа (пустой — всё стоит)."""
    have, have_fx = {}, {}
    for s in scenes:
        src = str(s.get("source", ""))
        if src.startswith("card:"):
            have[src[5:].strip()] = have.get(src[5:].strip(), 0) + 1
        f = str(s.get("fx", "")).strip().lower()
        if f:
            have_fx[f] = have_fx.get(f, 0) + 1
    bad = []
    for el in ОБЯЗАТЕЛЬНЫЕ:
        if gate == "dashboard" and el["gate"] == "video":
            continue                      # этот спрашиваем только перед сборкой
        if el["каналы"] and channel and channel.upper() not in [
                c.upper() for c in el["каналы"]]:
            continue
        n = (have_fx.get(el["fx"], 0) if el.get("fx")
             else have.get(el["view"], 0))
        if n >= el["min"]:
            continue
        bad.append(
            "ОБЯЗАТЕЛЬНЫЙ ЭЛЕМЕНТ %s («%s») стоит %d раз при норме %d.\n"
            "    когда уместен: %s\n"
            "    чем ставится: %s"
            % (el["код"], el["имя"], n, el["min"], el["когда"], el["чем"]))
    return bad


def main():
    ap = argparse.ArgumentParser(description="обязательные элементы ролика")
    ap.add_argument("scenes", nargs="?", default="")
    ap.add_argument("--gate", choices=["dashboard", "video"], default="dashboard")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list or not a.scenes:
        print("ОБЯЗАТЕЛЬНЫЕ ЭЛЕМЕНТЫ (гейт → код → вид → сколько):")
        for el in ОБЯЗАТЕЛЬНЫЕ:
            метка = ("fx:" + el["fx"]) if el.get("fx") else ("card:" + el["view"])
            print("  %-9s %-4s %-17s x%d  %s"
                  % (el["gate"], el["код"], метка, el["min"], el["имя"]))
        return 0

    if not os.path.isfile(a.scenes):
        print("нет файла сцен: %s" % a.scenes, file=sys.stderr)
        return 2
    scenes, meta = _scenes(a.scenes)
    bad = check(scenes, _channel(meta, a.scenes), a.gate)
    if a.json:
        print(json.dumps({"gate": a.gate, "ok": not bad, "нет": bad},
                         ensure_ascii=False, indent=1))
        return 1 if bad else 0
    if bad:
        print("❌ ОБЯЗАТЕЛЬНЫХ ЭЛЕМЕНТОВ НЕТ В РОЛИКЕ (%d):" % len(bad))
        for b in bad:
            print("  - " + b)
        return 1
    print("✅ обязательные элементы на месте (%s)" % a.gate)

    # ОБЯЗАТЕЛЬНЫЙ СПИСОК — ЭТО МИНИМУМ, А НЕ ПОТОЛОК (07.11, его слово,
    # зло: «ну как это лежат без дела? Зачем мы их разрабатываем, если
    # используешь только девять? Давай один, почему не один?»).
    # Что произошло: список из двенадцати обязательных стал и потолком —
    # вкладки ставили ровно его и ничего больше, и во всех шести роликах
    # дня были одни и те же девять видов, при том что в `card_put.py` их
    # ДВАДЦАТЬ ДВА. Разработанное и принятое лежало без дела.
    # Поэтому: сверх обязательных в ролике должно стоять не меньше ТРЁХ
    # ДРУГИХ видов. Это предупреждение, а не блокер: он снимает лишнее на
    # дашборде сам, но молчать об этом нельзя.
    _obyaz_views = {el.get("view") for el in ОБЯЗАТЕЛЬНЫЕ if el.get("view")}
    _in_film = set()
    for _s in scenes:
        _src = str(_s.get("source", ""))
        if _src.startswith("card:"):
            _in_film.add(_src.split(":", 1)[1])
    _extra = sorted(_in_film - _obyaz_views)
    _ALL_VIEWS = ["quote", "split", "tape", "doc", "strike", "duel", "pull",
                  "marker_serif", "paper_typed", "paper_hand", "slope", "line",
                  "map", "map_regions", "bubbles", "map_dist", "pie", "dossier",
                  "film", "film_frame", "vyrezka", "vyrezka_kontur"]
    _unused = [v for v in _ALL_VIEWS if v not in _in_film]
    print("видов в ролике: %d (обязательных %d + своих %d)"
          % (len(_in_film), len(_in_film & _obyaz_views), len(_extra)))
    if _extra:
        print("   сверх обязательных: %s" % ", ".join(_extra))
    if len(_extra) < 3:
        print("⚠ СВЕРХ ОБЯЗАТЕЛЬНЫХ ВСЕГО %d ВИДОВ — нужно не меньше трёх."
              % len(_extra))
        print("   Обязательный список это МИНИМУМ, а не потолок: разработано "
              "и принято 22 вида, и они должны идти в дело.")
        print("   Не заняты в этом ролике: %s" % ", ".join(_unused[:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
