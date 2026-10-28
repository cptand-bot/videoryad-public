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


def srt_end_sec(path):
    """Последний таймкод SRT в секундах."""
    import re
    try:
        txt = open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return 0.0
    last = 0.0
    for m in re.finditer(r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*"
                         r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})", txt):
        h, mi, s, ms = map(int, m.group(5, 6, 7, 8))
        last = max(last, h * 3600 + mi * 60 + s + ms / 1000.0)
    return last


def mines_text():
    """Живой список мин из линтера — не копия, которая отстаёт."""
    import subprocess
    lint = os.path.join(os.path.dirname(os.path.abspath(__file__)), "query_lint.py")
    try:
        r = subprocess.run(["python3", lint, "--mines-brief"],
                           capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def write_scenes_task(dest, srt, channel, out_name="ЗАДАНИЕ-РАСКАДРОВКА.txt"):
    """Задание на раскадровку: числа цифрами + ЖИВОЙ список мин линтера."""
    total = srt_end_sec(srt)
    want = total / 11.5 if total else 0
    body = [
        "Распиши этот ролик на сцены по своей постоянной инструкции.",
        "",
        "Канал: %s. Длительность озвучки: %.1f с." % (channel, total),
        "ЧИСЛО СЦЕН: %d (допустимо %d-%d). Посчитай своё число ДО того, как"
        % (round(want), round(want * 0.9), round(want * 1.1)),
        "начнёшь писать сцены, и уложись в этот диапазон.",
        "Сумма длительностей обязана сойтись с озвучкой: %.1f с ±1,5 с." % total,
        "Карточек: %d (одна на 15 сцен), между соседними не меньше 8 сцен."
        % max(1, round(want / 15)),
        "Сток (pexels_video) 10-20% сцен, pexels_photo НЕ использовать.",
        # ОБА СЛУЧАЯ ЖИВЫЕ, 28.10: вкладка 2 вернула первый заход, где десять
        # стоковых запросов были написаны по-русски и с топонимами (сток
        # городов не знает и на топониме отдаёт случайную страну), а вкладка 1
        # получила 72 сцены БЕЗ закадровых реплик, потому что в своём брифе
        # написала «поле text не заполняй» в смысле экранных надписей — он
        # понял буквально, и приёмка легла.
        "ЗАПРОСЫ К СТОКУ (`pexels_video`) — ТОЛЬКО ПО-АНГЛИЙСКИ, предметные,",
        "БЕЗ топонимов, имён и названий: сток городов не знает, а на топониме",
        "отдаёт случайную страну. Все остальные запросы — только по-русски.",
        "ПОЛЕ `text` — ЭТО ЗАКАДРОВАЯ РЕПЛИКА СЦЕНЫ ИЗ СУБТИТРОВ, оно",
        "заполняется ВСЕГДА. Экранные надписи — это `overlays`, и только они;",
        "если надписи не нужны, пустым оставляй `overlays`, а не `text`.",
        "",
        # ОДИН ОБЪЕКТ, РАЗМНОЖЕННЫЙ ФОРМУЛИРОВКАМИ (25.10, улов `usuario-6f`):
        # уникальность текста запросов он соблюдает идеально, а по существу
        # заказывает один зал восемь раз разными определениями. Считает теперь
        # и приёмка (группировка по корню), но дешевле сказать ему заранее.
        "НА ОДИН ОБЪЕКТ — НЕ БОЛЬШЕ ТРЁХ СЦЕН ЗА РОЛИК. Считай по",
        "СУЩЕСТВИТЕЛЬНОМУ, а не по формулировке: «трибуна зала», «полукруг",
        "зала», «депутатские ряды», «вид из зала», «фасад здания» — это ОДИН",
        "объект, заказанный пять раз, и зритель увидит один и тот же кадр.",
        "Разные определения при одном существительном уникальностью не",
        "считаются. Не хватает объектов — бери другой субъект той же линии",
        "(другое ведомство, другой город, другую сторону события), а не",
        "новое определение к прежнему.",
        "",
        "Субтитры приложены файлом в этой же папке, путей вида D:\\ здесь нет.",
        "Результат верни ОДНИМ блоком ```json, на диск ничего не записывай.",
        "Числами в ответе не отчитывайся — их проверит приёмка.",
        "",
    ]
    mines = mines_text()
    if mines:
        body += [mines, ""]
    path = os.path.join(dest, out_name)
    open(path, "w", encoding="utf-8").write("\n".join(body))
    return path, round(want), total

def main():
    ap = argparse.ArgumentParser(description="бриф и материалы для Codex")
    ap.add_argument("scenes", nargs="?", default="")
    ap.add_argument("--dest", required=True, help="папка ролика на D:")
    ap.add_argument("--thumbs", default="thumbs")
    ap.add_argument("--stage", default="audit",
                    choices=("audit", "zamena", "scenes"))
    ap.add_argument("--srt", default="", help="для --stage scenes")
    ap.add_argument("--channel", default="", help="для --stage scenes")
    ap.add_argument("--no-copy", action="store_true", help="не копировать листы")
    a = ap.parse_args()

    # --stage scenes: задание на раскадровку, ещё ДО того как сцены есть.
    # Первым аргументом в этом режиме передают любой путь-заглушку.
    if a.stage == "scenes":
        if not a.srt or not a.channel:
            sys.exit("для --stage scenes нужны --srt и --channel")
        path, want, total = write_scenes_task(a.dest, a.srt, a.channel)
        print("задание на раскадровку: %s" % win(path))
        print("  канал %s, озвучка %.1f с, просим %d сцен, "
              "список мин линтера вклеен" % (a.channel, total, want))
        return 0

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
    # `--no-copy` НЕ ДОЛЖЕН ОСТАВЛЯТЬ БРИФ БЕЗ СПИСКА СЦЕН (24.10, улов
    # `usuario-91`): бриф ссылается на `СПИСОК-СЦЕН.txt` всегда, а при
    # `--no-copy` файл не создавался — агент получал указание на то, чего нет.
    # Теперь список пишется В ПАПКУ ПРОЕКТА даже когда листы не копируем.
    if a.no_copy:
        os.makedirs(a.thumbs, exist_ok=True)
        dest_thumbs = a.thumbs
    if True:
        os.makedirs(dest_thumbs, exist_ok=True)
        n = 0
        if not a.no_copy:
            for f in sheets + pairs + ([zam] if os.path.exists(zam) else []):
                # КОПИРОВАНИЕ ФАЙЛА В САМОГО СЕБЯ — НЕ ОШИБКА, А ПУСТАЯ РАБОТА
                # (2026-10-27, улов `usuario-b5`): с тех пор как папку ролика на
                # `D:` трогать нельзя, `--dest` указывает на сам проект, и
                # листы копировались из `thumbs/` в тот же `thumbs/` —
                # `shutil.SameFileError`, падение брифа на ровном месте.
                _dst = os.path.join(dest_thumbs, os.path.basename(f))
                if os.path.abspath(f) == os.path.abspath(_dst):
                    n += 1
                    continue
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

    # ДВА ИСКЛЮЧЕНИЯ ВШИТЫ В ШАБЛОН, А НЕ В ПАМЯТЬ ВКЛАДКИ (26.10, улов
    # `usuario-aa`). Вкладка вписала их в первый бриф руками и забыла во
    # второй — агент честно забраковал карту-всплывашку и полосу Financial
    # Times на сцене, которая это издание дословно называет. Две ложные
    # тревоги за ролик, и на позднем заходе их легко принять за правду и
    # снять хороший кадр.
    EXCEPTIONS = """

ДВА ИСКЛЮЧЕНИЯ, КОТОРЫЕ ВЫГЛЯДЯТ КАК БРАК, НО РАЗРЕШЕНЫ ПРЯМО:
1. КАРТА во всплывашке на географической сцене — это не «инфографика вместо
   фотографии», а наш единственный способ показать место. Контурная карта
   региона разрешена; браковать её не надо.
2. СКРИНШОТ ПУБЛИКАЦИИ (газета, агентство) во всплывашке, когда сцена НАЗЫВАЕТ
   это издание — разрешён: там текст и есть предмет сцены. Браком остаётся
   кадр ТВ-ЭФИРА с экранной плашкой и логотипом канала.
Оба исключения касаются только ВСПЛЫВАШЕК; в базовом кадре карта и скриншот
по-прежнему брак."""

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

Отдельные кадры не открывай — только листы.%s""" % (
            win(a.dest), len(sheets), len(scenes),
            plural(len(scenes), "сцена", "сцены", "сцен"),
            ("Плюс pair_1.jpg … pair_%d.jpg — пары «кадр сцены + его всплывашка», "
             "там ищи повтор одного и того же субъекта. " % len(pairs)) if pairs else "",
            "; ".join(skip) or "ничего", EXCEPTIONS))
    else:
        brief = ("""Посмотри %s\\thumbs\\sheet-zameny.jpg — это кадры из круга правок, их ещё
никто не проверял. Номер сцены и запрос подписаны под каждой плиткой.

Назови номера с браком и одной строкой причину. Не разобрать — так и пиши.

Правила те же, что в основном аудите. Напоминание: надпись на самом объекте
(указатель, табличка, маркировка) — не брак, язык её значения не имеет;
браковать надо то, что нанесено ПОВЕРХ кадра.%s""" % (win(a.dest), EXCEPTIONS))

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
