# -*- coding: utf-8 -*-
"""ПЕРЕДАЧА РОЛИКА ВНЕШНЕМУ АГЕНТУ (Codex) — ОДНОЙ КОМАНДОЙ.

Режим с 2026-10-23: раскадровку и аудит по листам делает Codex, механику ведёт
вкладка. Своего канала между нами нет — текст носит пользователь, поэтому текст
для него готовим МЫ, готовым к вставке: его надиктованные брифы приходят с
обрывками, и агент гадает.

    # после фетча и сборки листов (contact_sheet.py / pair_sheet.py):
    python3 codex_brief.py <scenes.json> --dest "/mnt/d/YouTube/.../1-Тема"
    # после круга правок, когда собран лист замен:
    python3 codex_brief.py <scenes.json> --dest "..." --stage zamena

Что делает:
  * кладёт `thumbs/` в папку ролика на D: (листы, пары, лист замен);
  * пишет туда `СПИСОК-СЦЕН.txt` — сцена, запрос, текст озвучки;
  * печатает БРИФ, готовый к вставке в чат Codex, со списком исключений
    (карточки и пины медиатеки) — без них он честно несёт их как брак.

Картинки при этом НЕ открываются на нашей стороне: в этом режиме на кадры
смотрит только он.
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys

CARD = "card:"


def win(path):
    """/mnt/d/YouTube/... -> D:\\YouTube\\..."""
    m = re.match(r"^/mnt/([a-z])/(.*)$", path)
    if not m:
        return path
    return m.group(1).upper() + ":\\" + m.group(2).replace("/", "\\")


def load(path):
    data = json.load(open(path, encoding="utf-8"))
    return data["scenes"] if isinstance(data, dict) else data


def pins_from_overlays(project):
    """Всплывашки из медиатеки — пины пользователя, их не аудируют.

    В `overlays.json` источника НЕТ (там только photo/sound/at/style), поэтому
    смотрим файлы, по которым всплывашки фетчились: `overlays_fetch.scenes.json`
    и `maps_fetch.scenes.json`. Проверено на `5min-tramp-donbass-2510`: карты
    4 и 96 лежат именно там, со `source: local_library`.
    """
    out = []
    for name in ("overlays_fetch.scenes.json", "maps_fetch.scenes.json"):
        try:
            data = json.load(open(os.path.join(project, name), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for s in (data.get("scenes") if isinstance(data, dict) else data) or []:
            if str(s.get("source", "")) == "local_library" and s.get("id"):
                out.append(int(s["id"]))
    return sorted(set(out))


def plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def main():
    ap = argparse.ArgumentParser(description="бриф и материалы для Codex")
    ap.add_argument("scenes")
    ap.add_argument("--dest", required=True, help="папка ролика на D:")
    ap.add_argument("--thumbs", default="thumbs")
    ap.add_argument("--stage", default="audit", choices=("audit", "zamena"))
    ap.add_argument("--no-copy", action="store_true", help="не копировать листы")
    a = ap.parse_args()

    project = os.path.dirname(os.path.abspath(a.scenes)) or "."
    scenes = load(a.scenes)
    cards = [s["id"] for s in scenes if str(s.get("source", "")).startswith(CARD)]
    pins = pins_from_overlays(project)

    # ЛИСТЫ ЛЕЖАТ В ТРЁХ РАЗНЫХ ПАПКАХ (24.10, улов `usuario-dd`):
    # `contact_sheet.py` кладёт в `sheet.html/`, `pair_sheet.py` — в
    # `pair_sheet/`, а сюда их до сих пор копировали руками. Ищем во всех.
    def _find(pat):
        out = []
        for d in (a.thumbs, "sheet.html", "pair_sheet", "thumbs"):
            out += glob.glob(os.path.join(d, pat))
        seen, uniq = set(), []
        for f in sorted(out):
            b = os.path.basename(f)
            if b not in seen:
                seen.add(b); uniq.append(f)
        return uniq

    sheets = _find("sheet_*.jpg")
    pairs = _find("pair_*.jpg")
    _z = _find("sheet-zameny.jpg")
    zam = _z[0] if _z else os.path.join(a.thumbs, "sheet-zameny.jpg")
    if a.stage == "audit" and not sheets:
        sys.exit("листов нет — сначала contact_sheet.py (и pair_sheet.py)")
    if a.stage == "zamena" and not os.path.exists(zam):
        sys.exit("нет thumbs/sheet-zameny.jpg — сначала собери лист замен")

    dest_thumbs = os.path.join(a.dest, "thumbs")
    if not a.no_copy:
        os.makedirs(dest_thumbs, exist_ok=True)
        n = 0
        for f in sheets + pairs + ([zam] if os.path.exists(zam) else []):
            shutil.copy2(f, dest_thumbs)
            n += 1
        # список сцен — он читает его вместо того, чтобы спрашивать запрос
        lst = [
            "СЦЕНЫ: sheet_1..sheet_%d.jpg — %d плиток, номер сцены выжжен в плитку."
            % (len(sheets), len(scenes)),
            "ПАРЫ: pair_1..pair_%d.jpg — «слева базовый кадр, справа всплывашка той же сцены»."
            % len(pairs) if pairs else "ПАР НЕТ.",
            "",
            "КАРТОЧКИ (рисуем сами, аудировать нечего): %s."
            % (", ".join(map(str, cards)) or "нет"),
            "ПИНЫ ПОЛЬЗОВАТЕЛЯ (всплывашки из медиатеки, неприкасаемы): %s."
            % (", ".join(map(str, pins)) or "нет"),
            "",
            "СЦЕНА | ЗАПРОС | ТЕКСТ СЦЕНЫ",
            "",
        ]
        for s in scenes:
            q = str(s.get("source_query", "")).strip()
            if str(s.get("source", "")).startswith(CARD):
                q = "карточка «%s» — кадр рисуем сами, фетча нет" % s["source"][len(CARD):]
            txt = " ".join(str(s.get("text", "")).split())[:140]
            lst.append("%4d | %s | %s" % (s["id"], q, txt))
        open(os.path.join(dest_thumbs, "СПИСОК-СЦЕН.txt"), "w",
             encoding="utf-8").write("\n".join(lst) + "\n")
        print("скопировано в %s: %d листов + СПИСОК-СЦЕН.txt" % (win(dest_thumbs), n))

    skip = []
    if cards:
        skip.append("сцены %s — наши карточки с цитатами, там всё своё"
                    % ", ".join(map(str, cards)))
    if pins:
        skip.append("всплывашки %s — пины пользователя из медиатеки, неприкасаемы"
                    % ", ".join(map(str, pins)))

    brief = ""
    if a.stage == "audit":
        brief = ("""В папке ролика лежит thumbs — контактные листы. Посмотри их и назови брак.

%s\\thumbs

Что смотреть: sheet_1.jpg … sheet_%d.jpg — все %d %s, номер сцены выжжен в
плитку. %sРядом СПИСОК-СЦЕН.txt — сцена, её поисковый запрос и текст озвучки.

Не аудируй: %s.

Что искать: чужой знак (логотип агентства или телеканала, подпись фотографа,
адрес сайта, t.me — бывает НЕ в углу, а во всю нижнюю треть крупным шрифтом);
текст, нанесённый ПОВЕРХ кадра (титр, плашка телеэфира, скриншот публикации,
водяной знак); не тот сюжет (инспекция вместо обстрела, учения вместо боя,
музей вместо действующего ведомства, манекен вместо солдата); не то место
(читаемый указатель или вывеска не из той области); рисованное (слишком ровное
пламя, симметричная техника, нарисованный флаг); повтор одного кадра на
соседних сценах.

Надпись НА САМОМ ОБЪЕКТЕ — указатель на здании, табличка на укрытии, вывеска,
маркировка на технике — это документальность, НЕ брак, и язык её значения не
имеет: украинский указатель в сюжете про Украину так же нормален, как русская
вывеска в сюжете про Россию.

Как отвечать: номер сцены и одна строка причины. Плитка мелкая и не разобрать
— так и пиши «не разобрать», не гадай, пришлю крупный план.

Отдельные кадры не открывай — только листы.""" % (
            win(a.dest), len(sheets), len(scenes),
            plural(len(scenes), "сцена", "сцены", "сцен"),
            ("Плюс pair_1.jpg … pair_%d.jpg — пары «кадр сцены + его всплывашка», "
             "там ищи повтор одного и того же субъекта. " % len(pairs)) if pairs else "",
            "; ".join(skip) or "ничего"))
    else:
        brief = ("""Посмотри %s\\thumbs\\sheet-zameny.jpg — это кадры из круга правок, их ещё
никто не проверял. Номер сцены и запрос подписаны под каждой плиткой.

Назови номера с браком и одной строкой причину. Не разобрать — так и пиши.

Правила те же, что в основном аудите. Напоминание: надпись на самом объекте
(указатель, табличка, маркировка) — не брак, язык её значения не имеет;
браковать надо то, что нанесено ПОВЕРХ кадра.""" % win(a.dest))

    # ФАЙЛОМ, А НЕ ТОЛЬКО В КОНСОЛЬ (24.10, прямое слово пользователя: «я чокнусь,
    # это всё копировать»). Он прикладывает файл в чат Codex одним движением.
    name = "БРИФ-ДЛЯ-CODEX.txt" if a.stage == "audit" else "БРИФ-ЗАМЕНЫ.txt"
    out = os.path.join(a.dest, name)
    try:
        open(out, "w", encoding="utf-8").write(brief.strip() + "\n")
        print("\nбриф положен файлом: %s" % win(out))
        print("пользователю: приложить этот файл в чат Codex, копировать ничего не надо")
    except OSError as e:
        print("\nне записать бриф в папку ролика (%s) — текст ниже, копировать руками" % e)
        print("\n" + "=" * 70)
        print(brief)
        print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
