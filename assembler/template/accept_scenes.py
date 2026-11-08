# -*- coding: utf-8 -*-
"""ПРИЁМКА РАСКАДРОВКИ, СДЕЛАННОЙ ДРУГИМ АГЕНТОМ (Codex).

Схема с 2026-10-23: Codex расписывает ролик на сцены и придумывает запросы
(самая думающая и дорогая по токенам часть), а сборку ведёт вкладка здесь.
Он ничего не запускает и о наших проверках не знает — значит его файл надо
принять строго, до того как за него заплачено поиском.

    python3 accept_scenes.py "/mnt/d/СБОРЩИК/ГОТОВО/<имя>.scenes.json" \\
        --srt <путь к .srt> [--out 5min.scenes.json]

Что проверяется:
  * структура: есть scenes, у каждой id/text/start_sec/duration_sec/source;
  * ТАЙМИНГ: сцены идут подряд без разрывов и нахлёстов, конец совпадает с
    озвучкой (это главное — на нём рассыпается весь монтаж);
  * источники из разрешённого списка;
  * нормы: доля стока, плотность карточек, расстояние между ними;
  * язык запроса: press_photo/web_search — по-русски, pexels — латиницей.

Чинит само только то, что чинится однозначно (накопленный дрейф start_sec).
Всё остальное — называет и выходит с кодом 1.
"""
import argparse
import json
import os
import glob
import io
import re
import sys

OK_SOURCES = {"press_photo", "web_search", "pexels_photo", "pexels_video",
              "local_library", "direct_url"}
CARD_PREFIX = "card:"


def srt_end(path):
    """Последний таймкод SRT в секундах."""
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


# ОДИН МОТИВ, РАЗМНОЖЕННЫЙ ФОРМУЛИРОВКАМИ (03.11, улов `usuario-b5`).
# Внешний агент расписал 20 сцен из 78 на мотиве «выборы»: урна, бюллетень,
# кабинка, участок, комиссия, подсчёт — каждый раз другими словами, поэтому
# проверка «одинаковое начало запроса» его не видела, а на экране это один и
# тот же кадр подряд. Заход к агенту стоит ролику 10-15 минут, ловим ДО фетча.
#
# ПОЧЕМУ ЭТО ПРЕДУПРЕЖДЕНИЕ, А НЕ ОТКАЗ, И ПОЧЕМУ ПОРОГ В ДОЛЯХ. Прогон по 104
# файлам сцен за последние дни (включая СДАННЫЕ ролики) показал: жёсткий
# потолок «4 сцены на мотив» валит сданное — у сданного «Против Трампа»
# парламент в 9 сценах из 78, флаги в 7, протест в 5, и всё это законно, тема
# ролика такая. Поэтому: порог 15% сцен (но не меньше 5), семьи только
# ПРЕДМЕТНЫЕ, а институциональные (парламент, суд) и фоновые (флаги) из счёта
# убраны — флаг за спиной министра не мотив, а деталь. На этом пороге
# сработка приходится ровно на сырые файлы агента (выборы 20/78, 10/67), а
# сданные ролики проходят чисто.
MOTIF_FAMILIES = {
    "выборы": ("урн", "бюллетен", "кабин", "избирател", "голосован",
               "избирком", "подсчёт голос", "подсчет голос"),
    "протест": ("протест", "демонстрац", "митинг", "шеств", "баррикад",
                "файер", "водомёт", "водомет"),
    "деньги": ("банкнот", "купюр", "монет", "кошел", "курс валют"),
    "армия": ("танк", "бтр", "солдат", "окоп", "учения войск"),
}
MOTIF_SHARE = 0.15     # доля сцен, после которой мотив размножен
MOTIF_FLOOR = 5        # и не меньше этого числа сцен


def motif_counts(scenes):
    """Семья мотива -> номера сцен, у которых запрос в неё попадает."""
    out = {}
    for sc in scenes:
        src = str(sc.get("source", ""))
        if src.startswith(CARD_PREFIX) or src.strip() == "direct_url":
            continue
        q = str(sc.get("source_query", "")).lower()
        if not q:
            continue
        for fam, stems in MOTIF_FAMILIES.items():
            if any(st in q for st in stems):
                out.setdefault(fam, []).append(sc.get("id"))
    return out


def _lib_alt(lib):
    """Соседняя библиотека: `media-library` ↔ `media-library-2`.

    ОТКАТ ПОВТОРЯЕТ ФЕТЧЕР (`fetch_assets_news.py`, откат от 29.10), и это не
    удобство, а условие правильного приговора: фетч ищет тег в библиотеке
    канала, а не найдя — в соседней, ДЛЯ ЛЮБОГО тега, не только `БАЗА/`.
    Проверка без отката объявляла живые папки выдуманными (03.11, улов
    `usuario-0d`: на 5 МИНУТ отбились разом ПОЛИТИКА/ЕВРОПА, ЕВРОПА-армия,
    ЕС-форумы-Украина, НАТО, ПОЛЬША, УКРАИНА, ФРАНЦИЯ — 14 сцен из 75, в
    которых лежало от 10 до 141 файла). Цена ошибки обратная заявленной:
    сообщение гнало переписать живые библиотечные сцены в ПОИСКОВЫЕ, а доля
    поиска — главный множитель брака.
    """
    b = os.path.basename(os.path.normpath(lib))
    if b.endswith("-2"):
        return os.path.join(os.path.dirname(os.path.normpath(lib)), b[:-2])
    if b == "media-library":
        return os.path.normpath(lib) + "-2"
    return ""


def _lib_has(lib, rel):
    """Есть ли тег в библиотеке канала ИЛИ в соседней — как у фетчера.

    Возвращает путь, по которому нашлось (или пустую строку).
    """
    # ДВА НАПИСАНИЯ ОДНОЙ ПАПКИ — ОБА ЗАКОННЫ (04.11, улов `usuario-31`).
    # Фетчер с сегодняшнего утра пробует и `ТЕМЫ/X`, и `БАЗА/ТЕМЫ/X`, а
    # приёмка знала только то написание, которое дал агент, — и объявляла
    # `БАЗА/ПОЛИТИКА/ГЕРМАНИЯ` выдуманным путём, хотя папка живая и лежит
    # без префикса. Отказ приёмки стоит круга переписывания задания, а
    # расхождение инструментов — самый дорогой вид ошибки: один говорит
    # «нет», другой бы нашёл.
    _r = str(rel).replace("\\", "/").strip("/")
    _cands = [_r]
    if _r.upper().startswith("БАЗА/"):
        _cands.append(_r.split("/", 1)[1])
    else:
        _cands.append("БАЗА/" + _r)
    for base in (lib, _lib_alt(lib)):
        if not base:
            continue
        for _c in _cands:
            p = os.path.join(base, _c)
            if os.path.isdir(p) or os.path.isfile(p):
                return p
    return ""


def _media_lib(near=""):
    """Папка медиатеки ТАК, КАК ЕЁ ВИДИТ ФЕТЧЕР: `.env` ролика, иначе
    `~/projects/media-library`. Правила разрешения повторяют `check_pins.py`
    (относительное имя вида `media-library-2` раскрывается в `~/projects/…`).
    """
    # ПЕРЕМЕННАЯ ОКРУЖЕНИЯ ЧИТАЕТСЯ ТОЖЕ (03.11): `folder_sheet.py` и
    # `base/catalog.py` берут её, а приёмка брала ТОЛЬКО `.env` — вкладка не
    # могла перекрыть библиотеку на один прогон и делала папку-пустышку со
    # своим `.env`. Приоритет: явная переменная, затем `.env` ролика.
    val = (os.environ.get("MEDIA_LIBRARY_DIR") or "").strip()
    seen = []
    if val:
        lib = os.path.expanduser(val)
        if not os.path.isabs(lib):
            lib = os.path.expanduser(os.path.join("~/projects", lib))
        return lib
    for d in (near, os.getcwd()):
        if not d or d in seen:
            continue
        seen.append(d)
        try:
            for ln in open(os.path.join(d, ".env"), encoding="utf-8",
                           errors="ignore"):
                ln = ln.strip()
                if ln.startswith("MEDIA_LIBRARY_DIR="):
                    val = ln.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
        if val:
            break
    lib = os.path.expanduser(val or "~/projects/media-library")
    if not os.path.isabs(lib):
        lib = os.path.expanduser(os.path.join("~/projects", lib))
    return lib


def main():
    ap = argparse.ArgumentParser(description="принять раскадровку от Codex")
    ap.add_argument("src")
    ap.add_argument("--srt", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--fix", action="store_true",
                    help="починить механическое: дрейф start_sec, тайминг по "
                         "SRT и свалку текста, выдуманный файл медиатеки, "
                         "сцены короче трёх секунд, перегруженную папку")
    ap.add_argument("--channel", default="5 МИНУТ",
                    help="канал в шапку готового файла (ПЛАНЕТА / 5 МИНУТ / …)")
    ap.add_argument("--per-scene", type=float, default=0.0,
                    help="секунд на сцену для нормы (по умолчанию 11.5; "
                         "13.2 — замер «ужать на 13%% разбросом», 28.10)")
    a = ap.parse_args()

    try:
        data = json.load(open(a.src, encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"ОШИБКА: не прочитать {a.src}: {e}")
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not scenes:
        sys.exit("ОШИБКА: в файле нет сцен")

    # ИМЕНА ПОЛЕЙ ПРОВЕРЯЕМ ДО ВСЕГО ОСТАЛЬНОГО (06.11, улов `usuario-84`).
    # Агент иногда называет поля `sid` / `start` / `dur`. Проверки читают
    # `id` / `start_sec` / `duration_sec`, получают None и 0.0 — и `--fix`
    # МОЛЧА схлопывал ролик в ноль сцен («сцена None (0.0 с) короче трёх
    # секунд — склеил со следующей» 73 раза, потом «сцен было 73, стало 0»).
    # Наружу это выглядело как успешная починка: код 0, файл на месте, сцен
    # нет. Правильное поведение — отказ с именами полей.
    _ALIASES = {"id": ("sid", "scene", "n", "num", "number"),
                "duration_sec": ("dur", "duration", "sec", "seconds", "len"),
                "start_sec": ("start", "from", "t0", "begin")}
    _s0 = scenes[0] if isinstance(scenes[0], dict) else {}
    _wrong = []
    for _need, _alts in _ALIASES.items():
        if _need in _s0:
            continue
        for _alt in _alts:
            if _alt in _s0:
                _wrong.append((_alt, _need))
                break
    if _wrong:
        sys.exit("ОШИБКА: поля сцен названы не так, как читает сборка — "
                 "переименуй и повтори:\n"
                 + "\n".join("  «%s» → «%s»" % (a_, b_) for a_, b_ in _wrong)
                 + "\n  (это НЕ чинится ключом --fix: с чужими именами "
                   "длительность читается как 0 с, и починка схлопнула бы "
                   "ролик в ноль сцен молча)")

    # АВТОПОЧИНКА МЕХАНИЧЕСКИХ ОТКАЗОВ (04.11). Замер по 28 сырым файлам
    # агента: приёмка не пропускает 8, и каждый отказ стоит ЗАХОДА к нему
    # (13 минут). Четыре причины из пяти чинятся без него — см.
    # `autofix_scenes.py`. Правки идут ДО проверок, чтобы проверки видели уже
    # починенный файл, и каждая печатается строкой «ПОЧИНЕНО».
    fixlog, fixed_n = [], 0
    if a.fix:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from autofix_scenes import autofix, need_query
        except ImportError as e:
            print("  ВНИМАНИЕ: автопочинка недоступна (%s) — чиню только "
                  "дрейф start_sec" % e)
            autofix = need_query = None
        if autofix:
            _lib0 = _media_lib(os.path.dirname(os.path.abspath(a.out or a.src)))
            _before = len(scenes)
            _keep = [dict(x) for x in scenes]
            scenes, fixlog = autofix(scenes, a.srt, _lib0)
            fixed_n = len(fixlog)
            for _ln in fixlog:
                print("  ПОЧИНЕНО:", _ln)
            if _before != len(scenes):
                # СКЛЕЙКА СЦЕН ПОСЛЕ ФЕТЧА — КАТАСТРОФА, А НЕ ПОЧИНКА (05.11,
                # улов `usuario-f4`). Кадры лежат на диске как
                # `images/scene_NNN.*`, всплывашки — ключами по id, задания
                # карточек — `cards/queue/scene_NNN.json`. Убрали одну сцену —
                # и КАЖДЫЙ кадр после неё встал на чужую сцену, молча: файл
                # валидный, линт чист, `selfcheck` зелёный. До фетча склейка
                # полезна, после — запрещена.
                _imgd = os.path.join(
                    os.path.dirname(os.path.abspath(a.src)) or ".", "images")
                _have_frames = bool(glob.glob(os.path.join(
                    _imgd, "scene_*.*"))) if os.path.isdir(_imgd) else False
                if _have_frames:
                    scenes = _keep
                    print("  !! СКЛЕЙКА СЦЕН ОТМЕНЕНА: рядом лежат скачанные "
                          "кадры (images/scene_*.*), а склейка сдвинула бы "
                          "номера — каждый кадр после места склейки встал бы "
                          "на ЧУЖУЮ сцену. Сцен оставлено %d, как было. "
                          "Короткие сцены правь руками или пересобирай "
                          "раскадровку ДО фетча." % len(scenes))
                    fixlog = [x for x in fixlog if "скле" not in x.lower()]
                    fixed_n = len(fixlog)
                else:
                    print("  ПОЧИНЕНО: сцен было %d, стало %d — номера и "
                          "тайминг пересчитаны подряд"
                          % (_before, len(scenes)))

    bad, warn = [], []
    # --- поля ---
    for i, sc in enumerate(scenes, 1):
        for f in ("id", "text", "start_sec", "duration_sec", "source"):
            if f not in sc:
                bad.append(f"сцена #{i}: нет поля {f}")
        src = str(sc.get("source", ""))
        if src and not src.startswith(CARD_PREFIX) and src not in OK_SOURCES:
            bad.append(f"сцена {sc.get('id')}: неизвестный источник «{src}»")
        if not src.startswith(CARD_PREFIX) and not str(sc.get("source_query", "")).strip():
            bad.append(f"сцена {sc.get('id')}: пустой source_query")
        d = float(sc.get("duration_sec") or 0)
        if d < 3:
            bad.append(f"сцена {sc.get('id')}: длительность {d:.1f} с — короче трёх секунд")
        elif d > 15:
            warn.append(f"сцена {sc.get('id')}: длительность {d:.1f} с — длиннее пятнадцати")
        # ТЕКСТ НЕ ПОМЕЩАЕТСЯ В ЗАЯВЛЕННОЕ ВРЕМЯ = СВАЛКА ОСТАТКА СКРИПТА
        # (30.10, улов `usuario-51`). Живой случай: последняя сцена заявлена
        # на 11,9 с, а в её `text` лежало 2035 знаков — весь хвост скрипта,
        # то есть СТО СЕКУНД озвучки, 13% ролика, одним кадром. Сумма
        # длительностей при этом сходилась идеально, потому что длительность
        # была проставлена фиктивной, а текст с ней никто не сверял: файл
        # прошёл приёмку чисто и уехал бы в сборку.
        # Порог 35 знаков в секунду выбран замером по 2267 сценам сданных
        # роликов: медиана 15,5, девяносто процентов ниже 18,3, девяносто
        # девять ниже 25,6. Выше 35 не поднялась НИ ОДНА принятая сцена —
        # ложных срабатываний нет, а свалка дала 171.
        _txt = str(sc.get("text", "")).strip()
        if d > 0 and _txt and len(_txt) / d > 35:
            bad.append(
                f"сцена {sc.get('id')}: в тексте {len(_txt)} знаков на "
                f"{d:.1f} с — это {len(_txt)/d:.0f} знаков в секунду при норме "
                f"15. Столько не произносится: в сцену свалён остаток скрипта "
                f"(примерно {len(_txt)/15:.0f} с озвучки). Режь её на сцены по "
                f"границам предложений СВОЕГО srt")

    # --- тайминг: непрерывность ---
    drift = []
    t = 0.0
    for sc in scenes:
        st = float(sc.get("start_sec") or 0)
        if abs(st - t) > 0.05:
            drift.append((sc.get("id"), st, t))
        t = (st if not a.fix else t) + float(sc.get("duration_sec") or 0)
    if drift and not a.fix:
        bad.append(f"ТАЙМИНГ РАЗЪЕХАЛСЯ у {len(drift)} сцен "
                   f"(первая — сцена {drift[0][0]}: стоит {drift[0][1]:.2f}, "
                   f"должно быть {drift[0][2]:.2f}). Перезапусти с --fix")

    total = sum(float(s.get("duration_sec") or 0) for s in scenes)
    if a.srt:
        end = srt_end(a.srt)
        if end and abs(total - end) > 1.5:
            bad.append(f"ДЛИТЕЛЬНОСТЬ НЕ СХОДИТСЯ: сцены дают {total:.1f} с, "
                       f"озвучка {end:.1f} с (разница {abs(total-end):.1f} с)")

    # --- нормы ---
    n = len(scenes)
    stock = sum(1 for s in scenes if str(s.get("source", "")).startswith("pexels"))
    cards = [i for i, s in enumerate(scenes)
             if str(s.get("source", "")).startswith(CARD_PREFIX)]
    # СТОК ЗАПРЕЩЁН ПОЛНОСТЬЮ (28.10, прямое слово пользователя после просмотра
    # шести роликов смены: «стоковые кадры вообще не попадают в тему, они просто
    # разрывают смысловой сюжет, нахуй не нужны, удаляем их, не берём больше
    # эти пиксели в новостную сборку»). Был коридор 10-20% и требование «не
    # меньше 5%, иначе начало статичное» — теперь ровно наоборот: ни одной
    # стоковой сцены. Движение берём из медиатеки, которая с этого дня открыта
    # на ВСЕХ каналах.
    if stock:
        bad.append("СТОК ЗАПРЕЩЁН: %d сцен на `pexels_video`/`pexels_photo` "
                   "(%s). Стоковые кадры не попадают в тему и разрывают сюжет "
                   "— прямое слово пользователя 28.10. Замени источник: "
                   "медиатека (она открыта на всех каналах), press_photo, "
                   "web_search, direct_url из досье или карточка арсенала"
                   % (stock, ", ".join(str(s.get("id")) for s in scenes
                                       if str(s.get("source", "")).startswith("pexels"))[:120]))
    # ЧИСЛО СЦЕН — ФОРМУЛОЙ (24.10, прямое слово пользователя «это дофига, 101»).
    # сцен = длительность ÷ 11,5 (медиана по сданным роликам), допуск ±10%.
    if total > 60:
        # ШАГ СЦЕНЫ — КЛЮЧОМ, А НЕ КОНСТАНТОЙ (28.10, по прямому слову
        # пользователя: «ужимать надо разбросом»). 11,5 с остаётся значением по
        # умолчанию — это медиана по сданным роликам, и без ключа поведение
        # прежнее, идущие ролики правка не задевает. При `--per-scene 13.2`
        # норма падает на 13%, а длительности внутри ролика расходятся: 8-10 с
        # под клипы (видео-лид от этого выигрывает), 14-16 с под фото со
        # всплывашкой в середине, 11-12 с на именные сцены.
        want = total / (a.per_scene or 11.5)
        # ВЕРХНЯЯ ГРАНИЦА ПРИ ЗАДАННОМ ШАГЕ ШИРЕ (28.10, замер «Круговая
        # оборона»): норма 48 с допуском 43-52, а минимально достижимый
        # результат — 53, потому что сцены длиннее 16 с правило запрещает и их
        # приходится резать. Получалась ложная тревога ровно там, где правка
        # обязательна. При явном `--per-scene` верх считаем +20%.
        _hi = 1.2 if a.per_scene else 1.1
        if n > want * _hi:
            warn.append("сцен %d при норме %d (%.0f-%.0f) — нарезано мелко, "
                        "медиана %.1f с; каждая лишняя сцена это лишний запрос "
                        "и лишняя плитка на проверку"
                        % (n, round(want), want * 0.9, want * _hi, total / n))
        elif n < want * 0.9:
            warn.append("сцен %d при норме %d (%.0f-%.0f) — кадры будут «застывать»"
                        % (n, round(want), want * 0.9, want * _hi))
    # ВИД КАРТОЧКИ СВЕРЯЕМ С РЕЕСТРОМ ДВЕРИ (2026-10-27, улов `usuario-54` на
    # `5min-granica1997`). Приёмка проверяла только ПРЕФИКС `card:` — поэтому
    # выдуманный агентом `card:bullets` прошёл с кодом 0. Дефект был бы поздним
    # и немым: за `card:*` фетч не идёт, такой вид `card_put.py` не примет,
    # карточку никто не нарисует — в сборке просто пустые сцены. Список берём
    # из самого `card_put.py`, чтобы он не разъезжался с дверью: добавят вид
    # туда — приёмка узнает о нём сама.
    _known = set()
    try:
        _cp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "fullcycle", "card_put.py")
        _txt = open(_cp, encoding="utf-8").read()
        _blk = re.search(r"VIEWS = \{(.*?)\n\}", _txt, re.S)
        if _blk:
            _known = set(re.findall(r'"([a-z_]+)":', _blk.group(1)))
    except Exception:
        _known = set()
    # РЕЕСТРА ДВА, А ПРИЁМКА ЗНАЛА ОДИН (02.11, улов `usuario-04`).
    # Рисованные кадры делают ДВА инструмента: `fullcycle/card_put.py`
    # (карты, досье, плёнка, цитаты) и боевой `template/style_card.py`
    # (`bullets`, `forces`, `timeline`). Бриф раскадровки предлагает виды из
    # ОБОИХ, а приёмка сверялась только с первым — агент честно выполнил
    # бриф, поставил `card:timeline` и получил отказ «вида НЕ СУЩЕСТВУЕТ».
    # Это тот же класс «инструментов два, правку получил один», что и с
    # анимацией карточек 30.10. Читаем оба реестра.
    try:
        _sc = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "style_card.py")
        _st = open(_sc, encoding="utf-8").read()
        _lb = re.search(r"LIMITS = \{(.*?)\n\}", _st, re.S)
        if _lb:
            _known |= set(re.findall(r'"([a-z_]+)":\s*\{', _lb.group(1)))
    except Exception:
        pass
    # РЕЕСТРОВ СТАЛО ТРИ (06.11). Общая дверь элементов арсенала
    # `template/element_put.py` держит свою таблицу (`wall`, `dof`, `poster`,
    # `bars`, `slider` и всё, что он назовёт дальше). Не прочитать её здесь —
    # значит отбивать приёмкой сцену, которую мы сами же и поставили: тот же
    # класс «реестров два, приёмка знает один», что поймали 02.11.
    try:
        _ep = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "element_put.py")
        _et = open(_ep, encoding="utf-8").read()
        _eb = re.search(r"ЭЛЕМЕНТЫ = \{(.*?)\n\}", _et, re.S)
        if _eb:
            _known |= set(re.findall(r'"([a-z_]+)":\s*\{', _eb.group(1)))
    except Exception:
        pass
    for i in cards:
        _view = str(scenes[i].get("source", ""))[len(CARD_PREFIX):].strip()
        if not _view:
            bad.append("сцена %s: источник «card:» без вида — карточку нечем "
                       "рисовать" % scenes[i].get("id"))
        elif _known and _view not in _known:
            bad.append("сцена %s: вида карточки «%s» НЕ СУЩЕСТВУЕТ — "
                       "`card_put.py` знает только: %s. За `card:*` фетч не "
                       "идёт, значит сцена осталась бы пустой молча"
                       % (scenes[i].get("id"), _view,
                          ", ".join(sorted(_known))))

    # КАРТОЧКА ОТ АГЕНТА — ЭТО ПОКА ТОЛЬКО НАМЕРЕНИЕ (08.11). Он ставит
    # источник, а задание на отрисовку кладёт инструмент: доступа к WSL у
    # агента нет. Здесь это ещё не отказ (приёмка идёт ДО того, как вкладка
    # расставит карточки), но вкладка обязана увидеть список сразу — иначе
    # узнает о пустых сценах только из `selfcheck`, где уже блокер.
    if cards:
        _нет_задания = []
        for i in cards:
            _sid = int(scenes[i].get("id"))
            if not os.path.exists(os.path.join(
                    os.path.dirname(os.path.abspath(a.out or a.src)),
                    "cards", "queue", "scene_%03d.json" % _sid)):
                _нет_задания.append(str(_sid))
        if _нет_задания:
            warn.append(
                "карточки назначены агентом, но заданий на отрисовку ещё нет: "
                "сцены %s. Поставь их инструментом (`card_put.py` / "
                "`element_put.py`), иначе кадры будут пустыми — `selfcheck` "
                "отдельно это проверит и не отдаст дашборд."
                % ", ".join(_нет_задания))

    # ЭФФЕКТ №3 «ВРЕЗКА + КРУГИ» — ЕГО ТРИ ГРАНИЦЫ ПРОВЕРЯЮТСЯ ЗДЕСЬ (04.11).
    # Ключ сцены `"fx": "inset"` ставит `template/fx_put.py`; он же проверяет
    # границы при постановке. Приёмка повторяет проверку, потому что файл сцен
    # приходит от внешнего агента и правится руками: опечатка в значении или
    # четвёртый эффект иначе доехали бы до облака, где эффект молча не встанет.
    _fx_sids = [sc.get("id") for sc in scenes
                if str(sc.get("fx", "")).strip()]
    if _fx_sids:
        # Четыре вида из его образца: врезка (03.11) и три перехода (04.11).
        # ПОТОЛОК ТРИ СЧИТАЕТСЯ НА ВСЕ ВИДЫ ВМЕСТЕ — «эффекты не больше 3 раз
        # на видеоряд».
        # СПИСОК ВИДОВ ЧИТАЕМ У САМОЙ ДВЕРИ (06.11, БЛОКЕР вкладки
        # `usuario-84`). Пока он был переписан здесь руками, седьмой вид
        # `flash` раскатался НАПОЛОВИНУ: `fx_put.py` его ставил, обязательный
        # список требовал, а приёмка отбивала «эффекта не существует» — то
        # есть поставить нельзя и не поставить нельзя. Тот же класс, что
        # «реестров два, приёмка знает один».
        try:
            import importlib.util as _ilu
            _fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fx_put.py")
            _sp = _ilu.spec_from_file_location("_fx_put", _fp)
            _fx_mod = _ilu.module_from_spec(_sp)
            _sp.loader.exec_module(_fx_mod)
            _ok_fx = set(_fx_mod.KINDS)
            _trans = set(_fx_mod.TRANS)
        except Exception:
            _five = {"player", "curl", "slides", "stamps", "torn", "filmwin"}
            _ok_fx = {"inset", "mosaic", "panels", "wipe", "depth", "tear",
                      "flash", "subscribe", "subscribe2"} | _five
            _trans = {"mosaic", "panels", "wipe", "depth", "tear",
                      "flash"} | _five
        _first = min((int(sc.get("id", 0)) for sc in scenes), default=0)
        for sc in scenes:
            v = str(sc.get("fx", "")).strip().lower()
            if v in _trans:
                if int(sc.get("id", 0)) <= _first:
                    bad.append("сцена %s: «%s» — переход с кадра ПРОШЛОЙ "
                               "сцены, на первой сцене ролика его ставить не "
                               "с чего" % (sc.get("id"), v))
                if float(sc.get("duration_sec") or 0) < 2.5:
                    bad.append("сцена %s: %.1f с — переходу «%s» нужно не "
                               "меньше 2,5 с"
                               % (sc.get("id"),
                                  float(sc.get("duration_sec") or 0), v))
            if v and v not in _ok_fx:
                bad.append("сцена %s: эффекта «%s» не существует — сборка знает "
                           "только %s" % (sc.get("id"), sc.get("fx"),
                                          ", ".join(sorted(_ok_fx))))
            if v and str(sc.get("source", "")).startswith(CARD_PREFIX):
                bad.append("сцена %s: эффект на рисованную карточку (%s) не "
                           "кладём" % (sc.get("id"), sc.get("source")))
        _ch = a.channel.strip().upper().replace("Ё", "Е")
        # ЗАМОК КАНАЛОВ — ТОЖЕ ИЗ `fx_put.py` (06.11, та же мина, что со
        # списком видов): таблица была переписана здесь руками, и `flash`,
        # разрешённый на всех каналах, отбивался на «5 МИНУТ» как чужой.
        _allow = {"subscribe2": ("5 МИНУТ",)}
        try:
            _allow = dict(_fx_mod.CHANNEL_FX)
        except Exception:
            pass
        _wrong = [sc.get("id") for sc in scenes
                  if str(sc.get("fx", "")).strip().lower() in _ok_fx
                  and _ch not in tuple(
                      x.upper().replace("Ё", "Е")
                      for x in _allow.get(
                          str(sc.get("fx", "")).strip().lower(),
                          ("ПЛАНЕТА",)))]
        if _wrong:
            bad.append("на сценах %s стоят эффекты, которых на канале «%s» "
                       "нет: у каждого канала свой набор (кнопка вида 2 — "
                       "«5 МИНУТ», остальное — ПЛАНЕТА)"
                       % (", ".join(str(i) for i in _wrong), a.channel))
        # ПОТОЛОК ТРИ — НА КАЖДЫЙ ВИД (04.11, его уточнение по первому
        # боевому ролику: «не больше 3 раз ОДНОГО эффекта»). Утром считали
        # на все виды вместе, он посмотрел и сказал, что этого мало.
        # КНОПКА, ПОСТАВЛЕННАЯ НА ЗВУЧАЩИЙ ПРИЗЫВ, В ПОТОЛОК НЕ ВХОДИТ
        # (06.11, его слово при раскатке кнопки: «чтобы она появлялась, как
        # сейчас, три раза рандомно, И ПЛЮС когда звучит фраза „подпишись“»).
        # `fx_put.py` ставит такие сцены СВЕРХ трёх, а приёмка про исключение
        # не знала и валила ролик — на боевом файле «5 МИНУТ» вышло 7 кнопок
        # (3 по ролику + 4 на призыв) и отказ в приёмке на ровном месте.
        _said_re = re.compile(r"подпис|подпиш|колокольчик")
        _by_kind = {}
        for sc in scenes:
            v = str(sc.get("fx", "")).strip().lower()
            if v not in _ok_fx:
                continue
            if v.startswith("subscribe") and _said_re.search(
                    str(sc.get("text", "")).lower().replace("ё", "е")):
                continue
            _by_kind.setdefault(v, []).append(sc.get("id"))
        for _k, _ids in sorted(_by_kind.items()):
            if len(_ids) > 3:
                bad.append("эффекта «%s» в ролике %d (сцены %s) — потолок "
                           "ТРИ НА КАЖДЫЙ ВИД его словом"
                           % (_k, len(_ids),
                              ", ".join(str(i) for i in _ids)))
        _ins = os.path.join(os.path.dirname(os.path.abspath(a.src)), "insets")
        _nofile = [sc.get("id") for sc in scenes
                   if str(sc.get("fx", "")).strip().lower() == "inset"
                   and not os.path.isfile(
                       os.path.join(_ins, "scene_%03d.mp4" % int(sc.get("id", 0))))]
        if _nofile:
            warn.append("эффект-врезка без файла врезки (сцены %s): положи её "
                        "`fx_put.py <scenes.json> <sid> <видео>`, иначе сцена "
                        "соберётся обычным кадром"
                        % ", ".join(str(i) for i in _nofile))

    # ДВЕ СЕМЬИ, КАЖДАЯ СО СВОЕЙ НОРМОЙ (2026-10-29, как в `card_put.py`).
    # Единая норма «одна на 15» писалась под ТЕКСТОВЫЕ карточки и под запрет
    # пользователя «не превращать в слайд-шоу»; изобразительные виды под неё
    # попали заодно и ограничивались вкусом, хотя их ограничивает текст
    # сценария. Здесь проверка считала по-старому и печатала ложное «карточек
    # 11 при норме 5» плюс десяток ложных зазоров — вкладка разбирала их
    # глазами на каждом ролике.
    PICT = {"map", "map_regions", "bubbles", "pie", "film", "film_frame",
            "dossier", "split"}
    _view_of = lambda i: str(scenes[i].get("source", ""))[len(CARD_PREFIX):].strip()
    picts = [i for i in cards if _view_of(i) in PICT]
    texts = [i for i in cards if _view_of(i) not in PICT]
    # НОРМА И ЗАЗОР — ИЗ ОБЩЕГО СПИСКА ОБЯЗАТЕЛЬНЫХ (06.11, улов
    # `usuario-84`). Константы 15/8 и 9/4 писались до того, как он сделал
    # двенадцать элементов обязательными: приёмка печатала четыре ложных
    # «ближе 8 сцен» и «карточек 5 при норме 5» на ОБЯЗАТЕЛЬНЫХ кадрах,
    # которые сама же требует. Ложное предупреждение на каждом ролике — это
    # предупреждение, которое перестают читать.
    _gap_all, _norm_all = None, None
    try:
        import importlib.util as _ilu2
        _op = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "obyazatelno.py")
        _sp2 = _ilu2.spec_from_file_location("_obyaz", _op)
        _ob = _ilu2.module_from_spec(_sp2)
        _sp2.loader.exec_module(_ob)
        _gap_all, _norm_all = _ob.зазор(n), _ob.норма(n)
    except Exception:
        pass
    if _norm_all:
        # один счёт на все виды: зритель видит рисованные кадры общим числом
        if len(cards) > _norm_all + 1:
            warn.append("рисованных кадров %d при норме %d (+1 допуск) — "
                        "норма считается от списка обязательных"
                        % (len(cards), _norm_all))
        for x, y in zip(cards, cards[1:]):
            # по семьям: две изобразительные через 4 сцены — норма
            try:
                _g = _ob.зазор_вида(_view_of(x), n, _view_of(y))
            except Exception:
                _g = _gap_all
            if y - x < _g:
                warn.append(f"карточки на сценах {scenes[x]['id']} и "
                            f"{scenes[y]['id']} ближе {_g} сцен друг к другу")
    else:
        for name, group, per, gap in (("текстовых", texts, 15, 8),
                                      ("изобразительных", picts, 9, 4)):
            nrm = max(1, round(n / per))
            if len(group) > nrm + 1:
                warn.append(f"карточек {name} {len(group)} при норме {nrm} (+1 допуск)")
            for x, y in zip(group, group[1:]):
                if y - x < gap:
                    warn.append(f"карточки на сценах {scenes[x]['id']} и "
                                f"{scenes[y]['id']} ближе {gap} сцен друг к другу")

    # --- ШАБЛОННОСТЬ: уникальность по СМЫСЛУ, а не по приписке (23.10) ---
    # Живой случай: агент получил замечание «запросы повторяются» и приписал к
    # одному шаблону номер сцены — «переговоры …, 2025, сцена 41 — общий план»,
    # «…, сцена 42 — …». Формально 96 уникальных, по сути три. Плюс «сцена 41»
    # внутри поискового запроса — мусор, который поиску мешает.
    junk = re.compile(r"\s*,?\s*сцена\s*\d+\s*[—–-]?.*$|\s*[—–-]\s*(документальн|полевой|общий план).*$",
                      re.I)
    cores = {}
    for sc in scenes:
        if str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q = str(sc.get("source_query", ""))
        if re.search(r"сцена\s*\d+", q, re.I):
            bad.append(f"сцена {sc.get('id')}: в запросе служебная пометка «сцена N» — "
                       f"это мусор для поиска, убери")
        core = junk.sub("", q).strip().lower()
        core = " ".join(core.split()[:6])          # смысловое ядро запроса
        cores.setdefault(core, []).append(sc.get("id"))
    many = {k: v for k, v in cores.items() if len(v) > 3 and k}
    if many:
        worst = max(many.items(), key=lambda kv: len(kv[1]))
        bad.append(f"ЗАПРОСЫ ШАБЛОННЫЕ: {len(many)} формулировок повторяются более трёх раз. "
                   f"Худшая — «{worst[0][:50]}…» на {len(worst[1])} сценах "
                   f"({', '.join(map(str, worst[1][:6]))}…). Нужен СВОЙ предмет в каждой сцене")

    # ГОЛОВНАЯ ГРУППА СЛОВ — ВОТ ЧТО РЕШАЕТ (23.10, улов `usuario-dd`).
    # Прежняя проверка считала ядро по шести словам и ругалась лишь при более
    # чем трёх повторах — и пропустила подмену: агент взял пул из ~34 фраз и
    # прокрутил его ДВАЖДЫ, меняя только хвост-обстоятельство («…, утренний
    # свет» / «…, рядом с наблюдательной машиной»). Формально 95 уникальных
    # строк, на деле 25 пар одинаковых запросов. Поисковик ранжирует по первым
    # словам, хвост игнорирует (правило h), так что на фетче это дало бы
    # ~26 дублей по md5 и круг правок на ровном месте.
    # БИБЛИОТЕЧНЫЕ СЦЕНЫ ЭТА МИНА НЕ КАСАЕТСЯ (2026-10-29). У них
    # `source_query` — ПУТЬ ПАПКИ, а не запрос: «БАЗА/ВЕДОМСТВА/НАТО» у двух
    # сцен это не дубль, фетч отдаёт из папки РАЗНЫЕ файлы по кругу, и норма
    # прямо разрешает до двух сцен на папку. Мина валила ровно то поведение,
    # которое предписано правилами: вкладка развела 16 библиотечных сцен по 16
    # папкам, и видео-лид просел с 14 сцен до 10 — видео-папок в базе всего 11.
    # Свой счёт для библиотеки ниже: больше двух сцен из одной папки — брак.
    lib_dirs = {}
    heads = {}
    for sc in scenes:
        src = str(sc.get("source", ""))
        if src.startswith(CARD_PREFIX):
            continue
        if src.strip() == "local_library":
            d = str(sc.get("source_query", "")).strip().strip("/")
            if d:
                lib_dirs.setdefault(d, []).append(sc.get("id"))
            continue
        # ВЛОЖЕНИЯ ОДНОГО ПОСТА — НЕ ПОВТОР ЗАПРОСА (05.11, улов `usuario-8f`).
        # У `direct_url` в `source_query` лежит АДРЕС, и у двух фото одного
        # поста начало адреса совпадает по определению: пост один, файла два.
        # Приёмка видела «одинаковое начало запроса» и отбивала файл, хотя
        # кадры разные. Проверка головной группы слов к адресам неприменима.
        if src.strip() == "direct_url":
            continue
        q = junk.sub("", str(sc.get("source_query", ""))).strip().lower()
        h = " ".join(q.split()[:3])
        if h:
            heads.setdefault(h, []).append(sc.get("id"))
    # ВЫДУМАННЫЙ ПУТЬ МЕДИАТЕКИ — ОТКАЗ ПРИЁМКИ (03.11, улов `usuario-37`).
    # Внешний агент выдумал ВОСЕМЬ папок, которых нет в каталоге брифа
    # (`ПОЛИТИКА/УКРАИНА`, `ПОЛИТИКА/ЕВРОПА`, `ПОЛИТИКА/США`…), и приёмка
    # пропустила все восемь: проверка путей жила ТОЛЬКО в `check_pins.py`,
    # который гоняют «если есть пины». Дальше фетч по несуществующей папке
    # молча уходит в веб-водопад, а в манифесте остаётся `local_library /
    # cached` — то есть манифест врёт, будто кадр взят из медиатеки.
    # Проверяем ровно то же, что `check_pins`: папка или файл существует.
    _lib = _media_lib(os.path.dirname(os.path.abspath(a.out or a.src)))
    if lib_dirs and not os.path.isdir(_lib):
        warn.append("медиатека «%s» не найдена — пути библиотечных сцен НЕ "
                    "проверены, прогони check_pins.py из папки ролика" % _lib)
    elif lib_dirs:
        for d, ids in sorted(lib_dirs.items()):
            head = d.split(":", 1)[0].strip("/")
            _hit = _lib_has(_lib, head)
            # ПУСТАЯ ПАПКА — ЭТО «ПАПКИ НЕТ» (03.11, улов `usuario-15`).
            # Проверка на выдуманный путь спрашивала только `isdir`, а в базе
            # лежат десятки ЗАГОТОВОК под ночной сбор — пустых каталогов,
            # созданных заранее (сегодня их 12 только на первых двух уровнях).
            # Агент выдумывал путь, он случайно совпадал с заготовкой, приёмка
            # пропускала, а фетч отвечал «папка медиатеки недоступна (в облаке
            # медиатеки нет)» — формулировка уводит в сторону: папка локальная
            # и просто пустая. Сцена при этом приезжала FAILED.
            if _hit and os.path.isdir(_hit):
                try:
                    _n = len([f for f in os.listdir(_hit)
                              if f.lower().endswith(
                                  (".jpg", ".jpeg", ".png", ".webp",
                                   ".mp4", ".mov", ".webm", ".mkv"))])
                except OSError:
                    _n = 0
                if not _n:
                    bad.append("сцены %s: папка медиатеки «%s» СУЩЕСТВУЕТ, но "
                               "ПУСТАЯ (ноль кадров) — это заготовка под "
                               "ночной сбор. Фетч отдаст сцену FAILED. Возьми "
                               "другую папку из каталога или поисковый запрос"
                               % (", ".join(map(str, ids)), d))
                    continue
            if not _hit:
                bad.append("сцены %s: папки медиатеки «%s» НЕТ ни в %s, ни в "
                           "соседней библиотеке — путь выдуман, фетч молча "
                           "уйдёт в поиск, а манифест запишет local_library"
                           % (", ".join(map(str, ids)), d,
                              os.path.basename(_lib)))
    # СОСЕДНИЕ СЦЕНЫ ИЗ ОДНОЙ ПАПКИ — ПОВТОР МОТИВА, ВИДНЫЙ АРИФМЕТИКОЙ
    # (03.11, улов `usuario-79`: 6 пар соседних повторов на одном ролике, из
    # них две — именно этот случай: 14/15 два кадра солдат США из одной папки
    # и 6/9 два Белых дома в пределах четырёх сцен). Ни эта приёмка (запросы
    # РАЗНЫЕ по словам), ни `query_lint` (сверка запросов между собой), ни
    # дедуп по md5 такого не видят по устройству — ловит только глаз на листе.
    # А здесь это чистый счёт по `source_query`, без картинок и до фетча.
    # ИМЕНА ПЕРЕМЕННЫХ ЦИКЛА ЗДЕСЬ — ТОЛЬКО С ПОДЧЁРКИВАНИЕМ (03.11, мой же
    # баг, поймала `usuario-1f`): `for a, b in ...` затирал `a` — namespace
    # argparse, — и приёмка падала `AttributeError: 'int' object has no
    # attribute 'fix'` РОВНО ТОГДА, когда ей было что сказать про соседние
    # папки. Файл `--out` при этом не писался, и это читалось как «раскадровка
    # не принята». Класс: проверка, которая валит инструмент своим
    # срабатыванием, опаснее отсутствующей проверки.
    for d, ids in sorted(lib_dirs.items()):
        _seq = sorted(ids)
        _near = [(_x, _y) for _x, _y in zip(_seq, _seq[1:]) if _y - _x <= 4]
        for _x, _y in _near:
            warn.append("сцены %d и %d идут из ОДНОЙ папки «%s» в пределах "
                        "четырёх сцен — на экране это повтор мотива, даже если "
                        "запросы разными словами. Разведи их по ролику или "
                        "возьми другую папку" % (_x, _y, d))
    for d, ids in sorted(lib_dirs.items()):
        if len(ids) > 2:
            bad.append("папка медиатеки «%s» стоит на %d сценах (%s) — больше "
                       "двух на ролик нельзя, зритель увидит один двор трижды"
                       % (d, len(ids), ", ".join(map(str, ids))))
    _m_lim = max(MOTIF_FLOOR, int(len(scenes) * MOTIF_SHARE))
    for _fam, _ids in sorted(motif_counts(scenes).items()):
        if len(_ids) >= _m_lim:
            warn.append("мотив «%s» размножен на %d сцен из %d (%s) — разными "
                        "словами про одно и то же, на экране это один кадр "
                        "подряд. Порог %d: перепиши лишние на ДРУГИЕ предметы "
                        "или закрой их медиатекой"
                        % (_fam, len(_ids), len(scenes),
                           ", ".join(map(str, _ids)), _m_lim))
    pairs = {k: v for k, v in heads.items() if len(v) > 1}
    if pairs:
        # ИМЯ ЗДЕСЬ НЕ `total` (27.10, улов `usuario-31`): этим именем выше, на
        # строке ~96, посчитана ОБЩАЯ ДЛИТЕЛЬНОСТЬ ролика, и печать итога берёт
        # его же — переиспользование превращало «812,2 с» в «2.0 с», то есть
        # принятый файл выглядел пустым. Сама проверка длительности была живой,
        # врала только печать: ровно класс «успех ≠ сделанная работа».
        n_heads = sum(len(v) for v in pairs.values())
        worst = max(pairs.items(), key=lambda kv: len(kv[1]))
        msg = (f"ОДИНАКОВОЕ НАЧАЛО ЗАПРОСА у {n_heads} сцен в {len(pairs)} группах "
               f"(худшая — «{worst[0]}…» на сценах {', '.join(map(str, worst[1][:8]))}). "
               f"Поиск ранжирует по ПЕРВЫМ словам, хвост-обстоятельство он игнорирует — "
               f"эти сцены получат один и тот же кадр")
        (bad if total > len(scenes) * 0.15 else warn).append(msg)

    # --- ОДИН ОБЪЕКТ, РАЗМНОЖЕННЫЙ ФОРМУЛИРОВКАМИ (25.10, улов `usuario-6f`) ---
    # Новый класс брака раскадровки внешнего агента: уникальность ТЕКСТА запросов
    # соблюдена идеально (64 из 64 уникальны, проверка выше молчит), а по существу
    # один и тот же объект заказан восемь раз разными определениями — «трибуна»,
    # «полукруг», «депутатские ряды», «пленарные места», «вид из зала», «фасад».
    # На живом ролике так вышло 35 сцен из 69 на ПЯТИ объектах. Дефект приезжает
    # дважды: зритель видит один зал восемь раз (правило f), и половина запросов
    # возвращает один файл по md5 (правило h) — то есть ещё и круг правок.
    # Считаем по КОРНЮ существительного, а не по формулировке.
    # служебные слова наших же правил (год/месяц по правилу i, «реальное фото»
    # по шаблону запроса) объектом не являются
    _STOP = {"реальн", "фотогр", "крупны", "общий", "кадр", "съёмка", "съемка",
             "украин", "россий", "москва", "видео", "плане", "вид",
             "январ", "феврал", "марта", "апрел", "май", "июня", "июля",
             "август", "сентяб", "октябр", "ноябр", "декабр",
             # РОДОВЫЕ СЛОВА КОМПОНОВКИ — НЕ ОБЪЕКТ (28.10, улов вкладки
             # «Стубб»): у неё валились `перед…`, `фасад…`, `здани…`,
             # `площад…`, `общий…`, `минист…`. «Фасад министерства обороны
             # Польши» и «фасад министерства финансов Германии» — РАЗНЫЕ
             # объекты, а проверка видела один: она группирует по
             # шестисимвольным основам ВСЕХ значимых слов. Из-за этого приёмка
             # валила круг за кругом на законной раскадровке.
             "фасад", "здани", "площад", "перед", "интерь", "помещ",
             "улица", "улице", "входа", "входе", "минист", "ведомс",
             "комнат", "корпус", "террит", "снаруж", "внутри",
             # АНГЛИЙСКИЕ СЛУЖЕБНЫЕ СЛОВА СТОКА (28.10, замер «Круговая
             # оборона»): основа `closeu…` склеила ПЯТЬ разных предметов —
             # шины фуры, разметку, ковш экскаватора, бетон, колесо вагона.
             # Причём `closeup` предписывает добавлять САМ `query_lint` как
             # лечение мины «дорожная сцена без страны»: один инструмент
             # советовал то, что другой считал повтором объекта.
             "closeu", "close-", "macro", "detail", "shot", "footag",
             "angle", "aerial", "slow m", "timela", "handhe", "tracki"}
    # ИМЯ СОБСТВЕННОЕ РАЗЛИЧАЕТ ОБЪЕКТЫ (28.10, тот же улов). Если у сцен с
    # одной основой РАЗНЫЕ имена собственные (страна, город, ведомство,
    # фамилия), это разные объекты, а не повтор одного. Поэтому внутри группы
    # считаем сцены по НАБОРУ имён: ругаемся только если один и тот же набор
    # встречается больше трёх раз.
    roots = {}
    for sc in scenes:
        if str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q_raw = str(sc.get("source_query", ""))
        # У БИБЛИОТЕЧНОЙ СЦЕНЫ СМЫСЛ НЕСЁТ ПОСЛЕДНИЙ СЕГМЕНТ ПУТИ, А НЕ ПЕРВЫЙ
        # (2026-10-29). Группировка по корням всего пути считала шесть РАЗНЫХ
        # зданий в четырёх странах одним объектом, потому что все они лежат в
        # `ВЛАСТЬ-...`: брифинг-зал Белого дома, МИД России, Кремль, Офис
        # президента Украины, зал НАТО, Берлаймон. Берём только имя папки.
        if str(sc.get("source", "")).strip() == "local_library" and "/" in q_raw:
            _seg = q_raw.rstrip("/").rsplit("/", 1)[-1]
            # ПИН НА ФАЙЛ ИЗ ГРУППИРОВКИ ВЫХОДИТ ВОВСЕ (30.10, улов
            # `usuario-e2`). Когда сцена указывает на КОНКРЕТНЫЙ файл, а не на
            # папку, последний сегмент — это имя файла, и корни берутся из
            # него: `17_StateDept_q9XP76.mp4` дал корень «stated», и четыре
            # РАЗНЫХ клипа объявлялись одним объектом. Предупреждение не
            # валило прогон, но вкладка шла разводить повтор, которого нет.
            # Смысла проверять тут нечего: файлы разные по определению, а
            # довод «часть запросов вернёт один файл по md5» к пинам не
            # относится — md5 у них заведомо разные.
            if re.search(r"\.[A-Za-z0-9]{2,4}$", _seg):
                continue
            # В ПАПКАХ `ТЕМЫ/` ИМЯ СОСТАВНОЕ: `<ТЕМА-ДАТА>_<ОБЪЕКТ>` (04.11,
            # улов `usuario-31`). Счётчик брал весь сегмент — и четыре РАЗНЫХ
            # объекта (тёмные окна, подстанция, ремонтная бригада) из папок
            # `КИЕВ-БЕЗ-СВЕТА-3110_*` объявлялись одним объектом по корню
            # «света», потому что слово стоит в названии ТЕМЫ, а не объекта.
            # Вкладка подчинилась ложному приговору и увела подстанцию в
            # другую папку, где кадр хуже. Берём часть ПОСЛЕ последнего `_`.
            if "_" in _seg:
                _seg = _seg.rsplit("_", 1)[-1]
            q_raw = _seg.replace("-", " ")
        names = frozenset(w.lower()[:6] for w in re.findall(r"\b[А-ЯЁA-Z][а-яёa-z]{3,}", q_raw))
        seen = set()
        for w in re.findall(r"[а-яёa-z]{5,}", q_raw.lower()):
            r = w[:6]
            if r in _STOP or r in seen:
                continue
            seen.add(r)
            roots.setdefault(r, []).append((sc.get("id"), names))
    _by_root = {}
    for r, items in roots.items():
        from collections import Counter
        cnt = Counter(n for _, n in items)
        worst_names, worst_n = cnt.most_common(1)[0]
        if worst_n > 3:
            _by_root[r] = [sid for sid, n in items if n == worst_names]
    roots = _by_root
    heavy = sorted((v for v in roots.values() if len(v) > 3), key=len, reverse=True)
    if heavy:
        named = sorted(((r, v) for r, v in roots.items() if len(v) > 3),
                       key=lambda kv: len(kv[1]), reverse=True)
        head = "; ".join("«%s…» — %d сцен (%s)" % (r, len(v), ", ".join(map(str, v[:8])))
                         for r, v in named[:5])
        warn.append("ОДИН ОБЪЕКТ НА МНОГИХ СЦЕНАХ, разными словами: " + head +
                    " — норма не больше трёх сцен на объект. Уникальность текста "
                    "запросов тут не спасает: зритель увидит один и тот же кадр, "
                    "а часть запросов вернёт один файл по md5")

    # --- ОДИН ЭПИЗОД, РАЗМНОЖЕННЫЙ СИНОНИМАМИ (31.10, три улова за день) ---
    # Проверка выше группирует по КОРНЮ СУЩЕСТВИТЕЛЬНОГО и этот класс не
    # видит: «делегации = участники = представители = руководители =
    # министры» для неё разные слова. Живой счёт одного ролика: 66 сцен в
    # коридоре, с точной суммой длительностей, и ДВАДЦАТЬ из них —
    # «делегации/министры/участники на международной встрече» разными
    # словами (28, 29, 31, 34, 38, 40, 41, 47, 48, 50, 53, 55, 56, 57, 60,
    # 61, 63, 64, 65, 66). Приёмка увидела только «здание» 5, «встреч» 4.
    # В тот же день: 7 сцен «делегации в Абу-Даби» у второй вкладки, 6 сцен
    # дронов и 3 Капитолия подряд у третьей.
    # Это ЗАМЕЧАНИЕ, а не отказ: ролик про саммит законно называет участников
    # много раз. Задача — показать список сцен, чтобы их просмотрели глазами.
    _SYN = {
        "люди власти без имени": ("делегац", "участник", "представител",
                                  "руководител", "министр", "лидер", "чиновник",
                                  "политик", "посол", "дипломат", "глава делегац"),
        "встреча как событие": ("встреч", "саммит", "заседани", "консультац",
                                "переговор", "форум", "сесси", "брифинг",
                                "конференц", "круглый стол"),
        "трибуна и зал": ("трибун", "подиум", "зал заседан", "президиум",
                          "пресс-конференц"),
    }
    for _lbl, _ws in _SYN.items():
        _hit = []
        for sc in scenes:
            if str(sc.get("source", "")).startswith(CARD_PREFIX):
                continue
            _q = str(sc.get("source_query", "")).lower()
            if any(w in _q for w in _ws):
                _hit.append(sc.get("id"))
        # ПОРОГ — ДОЛЯ, А НЕ ЧИСЛО (прогон по восьми сданным роликам 31.10).
        # На пороге «5 сцен» замечание срабатывало у СЕМИ роликов из восьми
        # (встреча 6/47, 9/74, 13/74, 14/79; люди власти 5-8 сцен) — то есть
        # стало бы шумом, а шумное предупреждение перестают читать, как и
        # вечно красный гейт. Доли у сданных: 10-18%; у живого брака
        # (20 сцен из 66) — 30%. Порог «не меньше четверти ролика» даёт ноль
        # ложных на сданных и ловит настоящий случай.
        if len(_hit) >= 5 and len(_hit) >= 0.25 * max(1, len(scenes)):
            warn.append(
                "ОДИН ЭПИЗОД РАЗНЫМИ СЛОВАМИ? «%s» — %d сцен из %d: %s. Проверка по "
                "корням этот класс НЕ ловит (делегации = участники = "
                "представители). Посмотри глазами: если это одно и то же "
                "событие, оставь 1-2 сцены, остальным дай свой якорь — "
                "конкретное здание, папку медиатеки по стране или наш "
                "рисованный кадр." % (_lbl, len(_hit), len(scenes),
                                      ", ".join(map(str, _hit[:20]))))

    # --- КАРТОЧКА: цитата, а не обрывок ---
    for sc in scenes:
        if not str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q = str(sc.get("source_query", "")).strip()
        if not q:
            continue
        # СЛУЖЕБНАЯ ПОДПИСЬ КАРТОЧКИ — НЕ ЦИТАТА (2026-10-29). `card_put.py`
        # сам кладёт в `source_query` строку вида «карточка «dossier» — кадр
        # рисуется в облаке», и проверка ругалась на неё на КАЖДОЙ карточке
        # каждого ролика: четыре ложных предупреждения на четыре карточки.
        if q.lower().startswith("карточка "):
            continue
        first = q.split()[0] if q.split() else ""
        if first and first[:1].islower():
            warn.append(f"сцена {sc.get('id')}: текст карточки начинается с середины фразы "
                        f"(«{q[:40]}…») — нужна цитата целиком")

    # --- язык запроса ---
    cyr = re.compile(r"[а-яёА-ЯЁ]")
    for s in scenes:
        src, q = str(s.get("source", "")), str(s.get("source_query", ""))
        if src in ("press_photo", "web_search") and q and not cyr.search(q):
            warn.append(f"сцена {s.get('id')}: запрос не по-русски — «{q[:60]}»")
        if src.startswith("pexels") and cyr.search(q):
            bad.append(f"сцена {s.get('id')}: pexels ищет только латиницей — «{q[:60]}»")

    print(f"сцен: {n}, общая длительность {total:.1f} с")
    print(f"источники: press/web {sum(1 for s in scenes if s.get('source') in ('press_photo','web_search'))}, "
          f"сток {stock}, карточек {len(cards)}")
    # ПАПКА БИБЛИОТЕЧНОЙ СЦЕНЫ ДОЛЖНА БЫТЬ В МЕДИАТЕКЕ ЭТОГО КАНАЛА (05.11,
    # улов `usuario-f4`). Каналы живут на РАЗНЫХ корнях (`media-library` и
    # `media-library-2`), и сцена с папкой из чужого корня проходила приёмку:
    # папка ведь существует. В облаке такая сцена оказывается пустой или
    # молча подменяется поиском — видно только по пропавшему движению.
    _ml = ""
    for _d in (os.getcwd(), os.path.dirname(os.path.abspath(a.src))):
        try:
            for _l in io.open(os.path.join(_d, ".env"), encoding="utf-8"):
                if _l.strip().startswith("MEDIA_LIBRARY_DIR"):
                    _ml = _l.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
        if _ml:
            break
    if _ml:
        if not os.path.isabs(_ml):
            _ml = os.path.expanduser(os.path.join("~/projects", _ml))
        _nodir = []
        for sc in scenes:
            if str(sc.get("source", "")).strip() != "local_library":
                continue
            _q = str(sc.get("source_query", "")).strip().strip("/")
            if not _q or re.search(r"\.[A-Za-z0-9]{2,4}$", _q):
                continue
            if not any(os.path.isdir(os.path.join(_ml, _c))
                       for _c in (_q, "БАЗА/" + _q)):
                _nodir.append((sc.get("id"), _q))
        if _nodir:
            bad.append(
                "ПАПКИ НЕТ В МЕДИАТЕКЕ ЭТОГО КАНАЛА (%s): сцены %s. У каналов "
                "РАЗНЫЕ корни медиатеки, и папка из чужого корня даёт пустую "
                "сцену в облаке или молчаливую подмену поиском. Проверь "
                "`MEDIA_LIBRARY_DIR` в `.env` проекта и переназначь сцены."
                % (_ml, ", ".join("%s → %s" % (i, q) for i, q in _nodir[:8])))

    # ЧИСЛА В ТЕКСТЕ — ЭТО КАРТОЧКА, А НЕ ФОТОГРАФИЯ (05.11, прямое слово
    # пользователя по сданному ролику: «там рассказываются цифры… там же цифр
    # до ебени матери, можно было графики вывести. Для чего я это всё делаю?
    # Мы разворачиваем серьёзный аналитический канал — визуальное
    # представление аналитики должно быть как у профессионалов»).
    # Живой случай: блок SIPRI (114 миллиардов Германии, 4,5 процента Польши,
    # удвоение расходов за десять лет) проиллюстрирован тремя обычными
    # фотографиями. Инструменты для этого есть и давно: `card:bubbles`,
    # `card:pie`, `card:map_regions`, `card:dossier`.
    # Считаем ЧИСЛОВЫЕ ФАКТЫ: число (цифрами или словами — озвучка пишется
    # прописью) рядом с мерой (процент, миллиард, миллион, тысяча, валюта,
    # «вдвое», «в разы»). Два факта и больше в одной сцене — сцена обязана
    # быть карточкой. Даты и «три-пять суток» мерой не считаются.
    # ЧИСЛИТЕЛЬНЫЕ ПЕРЕЧИСЛЕНЫ ФОРМАМИ, А НЕ КОРНЯМИ (БЛОКЕР 07.11,
    # вкладка `usuario-2c`). Корень с хвостом `\w*` ловил обычные слова:
    # «сто» → «сТОлом», «сТОит», «сТАбильность»; «сем» → «СЕМья»,
    # «СЕМинар»; «пят» → «ПЯТно»; «три» → «ТРИбуна». Сцена «Место за
    # столом часть европейских руководителей требует» давала ТРИ числовых
    # факта и жёсткий отказ приёмки на тексте без единой цифры — и било
    # это ровно по темам про переговоры, где «стол», «Европа» и
    # «настаивает» в каждой второй реплике. Граница слова не спасает:
    # «столом» начинается с «сто».
    # ПОРЯДОК ВАЖЕН: длинные формы стоят ПЕРЕД короткими, иначе
    # «четыреста» матчится как «четыре», хвост «ста» рвёт цепочку, и одно
    # число считается за два (это вернуло бы блокер 06.11 про склейку).
    _NUM_PARTS = [
        r"нол(?:ь|я)", r"одиннадцат\w*", r"двенадцат\w*", r"тринадцат\w*",
        r"четырнадцат\w*", r"пятнадцат\w*", r"шестнадцат\w*",
        r"семнадцат\w*", r"восемнадцат\w*", r"девятнадцат\w*",
        r"двадцат\w*", r"тридцат\w*", r"сорок(?:а)?\b", r"пятьдесят",
        r"шестьдесят", r"семьдесят", r"восемьдесят", r"девяност\w*",
        r"двест\w*", r"трист\w*", r"четырест\w*", r"пятьсот", r"шестьсот",
        r"семьсот", r"восемьсот", r"девятьсот", r"ст[оа]\b",
        r"тысяч\w*", r"миллион\w*", r"миллиард\w*",
        r"один", r"одна", r"одного", r"двух", r"две\b", r"два\b", r"двум",
        r"трёх", r"трех", r"три\b",
        r"четыр(?:е\b|ёх|ех)", r"пят(?:ь\b|и\b|ью\b)",
        r"шест(?:ь\b|и\b|ью\b)", r"сем(?:ь\b|и\b|ью\b)",
        r"восем(?:ь\b|и\b|ью\b)", r"девят(?:ь\b|и\b|ью\b)",
        r"десят(?:ь\b|и\b|ью\b|ок\b)",
    ]
    _NUM_W = "|".join(_NUM_PARTS)
    _MEAS = (r"процент|миллиард|млрд|миллион|млн|доллар|евро|"
             r"рубл|гривен|вдво|втро|в разы|кратн|раза|раз в |километр|км |"
             r"тонн|штук|единиц|человек|бойц|военнослужащ|самолёт|самолет|"
             r"ракет|дрон|беспилотн|комплекс")
    _num_bad = []
    for sc in scenes:
        if str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        _t = str(sc.get("text", "")).lower()
        if not _t:
            continue
        # ОДНО ЧИСЛО ПРОПИСЬЮ — ОДИН ФАКТ, А НЕ ЧЕТЫРЕ (06.11, БЛОКЕР
        # вкладки `usuario-a3`). Счёт шёл ПО СЛОВАМ, поэтому «четыреста
        # тридцать семь миллионов евро» давало 4 факта, «четыре миллиарда
        # триста шестьдесят миллионов… двести миллионов» — 7 вместо двух, и
        # приёмка отбивала сцены, где настоящих фактов один-два. Правило
        # писалось про «три и больше числовых ФАКТА», а не про слова.
        # Поэтому соседние числительные склеиваются в ОДНУ цепочку: если
        # следующее совпадение начинается не дальше чем через 3 знака
        # (пробел, дефис, «и»), это то же самое число.
        _spans = [(_m.start(), _m.end())
                  for _m in re.finditer(r"(\d+[.,]?\d*|\b(?:%s))" % _NUM_W, _t)]
        _chains = []
        for _a, _b in _spans:
            if _chains and _a - _chains[-1][1] <= 4:
                _chains[-1] = (_chains[-1][0], _b)
            else:
                _chains.append((_a, _b))
        _facts = 0
        for _a, _b in _chains:
            # ДАТА — НЕ ЧИСЛОВОЙ ФАКТ: «в две тысячи двадцать втором году»,
            # «к сентябрю двадцать пятого года». Смотрим, не стоит ли сразу
            # за цепочкой слово «год» в любой форме.
            if re.match(r"\s*(год|г\.|году|года|годом|годах)", _t[_b:_b + 10]):
                continue
            _w = _t[max(0, _a - 40):_b + 40]
            if re.search(r"%%|\b(?:%s)" % _MEAS, _w):
                _facts += 1
        if _facts >= 2:
            _num_bad.append((sc.get("id"), _facts))
    # ТРИ ФАКТА И БОЛЬШЕ — ОТКАЗ, ДВА — ЗАМЕЧАНИЕ. Сцена с двумя числами
    # бывает проходной («к ноябрю из двух партий»), а три в одной реплике —
    # это всегда блок данных, который зритель на слух не удержит.
    _num_hard = [x for x in _num_bad if x[1] >= 3]
    _num_soft = [x for x in _num_bad if x[1] == 2]
    if _num_soft:
        warn.append("по два числовых факта в сценах %s — просится карточка "
                    "(`card:bubbles` / `card:pie` / `card:map_regions`), "
                    "решай по смыслу"
                    % ", ".join(str(i) for i, _ in _num_soft[:10]))
    if _num_hard:
        _num_bad = _num_hard
        _lst = ", ".join("%s (%d)" % (i, n) for i, n in _num_bad[:8])
        bad.append(
            "ЧИСЛА ПОКАЗЫВАЮТСЯ, А НЕ РАССКАЗЫВАЮТСЯ: в сценах %s текст "
            "несёт по два и больше числовых факта, а источник — обычный "
            "кадр. Такая сцена обязана быть КАРТОЧКОЙ: `card:bubbles` "
            "(сравнение величин), `card:pie` (доли целого), "
            "`card:map_regions` (кто сколько по странам/областям), "
            "`card:dossier` (ряд цифр по одному субъекту). Всего таких "
            "сцен: %d. Это правило канала, а не вкусовщина: мы делаем "
            "аналитический канал, и цифры в нём иллюстрируются как данные."
            % (_lst, len(_num_bad)))

    # СЦЕНЫ ПРОВЕРЯЕМ ПРОТИВ ОЗВУЧКИ, А НЕ ТОЛЬКО ПРОТИВ САМИХ СЕБЯ (05.11,
    # прямая претензия пользователя по сданному ролику: «картинки появляются
    # раньше, чем идёт озвучка… Пашинян выскакивает до того, как он это самое,
    # карта Варшавского договора ещё раньше выскочила»).
    # Как это проходило мимо всех проверок: сумма длительностей сходилась с
    # озвучкой до десятых, `start_sec` шли подряд без дыр — формально файл
    # безупречен. А РАСПРЕДЕЛЕНИЕ внутри уехало: агент резал сцены «на глаз»,
    # и к середине ролика картинка обгоняла голос на 30 секунд (замер по
    # `varshava-0511`: сцена 8 — 67,7 против 75,8; сцена 28 «карта Варшавского
    # договора» — 296,6 против 326,6; сцена 46 — 510,0 против 518,5).
    # Лечение одно: привязать каждую сцену к МЕСТУ ЕЁ ТЕКСТА в SRT.
    _ENDS = []

    def _cues(path):
        out = []
        try:
            raw = io.open(path, encoding="utf-8-sig", errors="ignore").read()
        except OSError:
            return out
        for blk in re.split(r"\n\s*\n", raw):
            m = re.search(r"(\d\d):(\d\d):(\d\d),(\d+)\s*-->"
                          r"\s*(\d\d):(\d\d):(\d\d),(\d+)", blk)
            if not m:
                continue
            t = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                 + int(m.group(3)) + int(m.group(4)) / 1000.0)
            _e = (int(m.group(5)) * 3600 + int(m.group(6)) * 60
                  + int(m.group(7)) + int(m.group(8)) / 1000.0)
            _ENDS.append(_e)
            txt = " ".join(l for l in blk.split("\n")
                           if "-->" not in l and not l.strip().isdigit()).strip()
            if txt:
                out.append((t, txt))
        return out

    _cu = _cues(a.srt) if getattr(a, "srt", "") else []
    _drift = []
    if _cu:
        import difflib as _dl

        # ЯКОРЬ ИЩЕМ ПОДСТРОКОЙ, А ИЗ НЕСКОЛЬКИХ БЕРЁМ БЛИЖАЙШИЙ К
        # ЗАЯВЛЕННОМУ НАЧАЛУ (06.11, БЛОКЕР вкладки `usuario-80`).
        # Было: похожесть `difflib` по первым 60 знакам. На живом ролике
        # сцена 6 («Кушнер… новая архитектура безопасности… раунд в Абу
        # Даби», ровно одно вхождение на 51,4 с) села на ПОЗДНЕЕ место
        # 549,7 с, где звучит «И здесь Кушнер со своей новой архитектурой
        # безопасности…»: набор слов перевесил. Один неверный якорь утащил
        # блок сцен 6-17 на +409…+495 с, а `--fix` напечатал «принято» и
        # отдал файл, где картинка обгоняет голос на восемь минут — то есть
        # чинилка ломала ИСПРАВНЫЙ файл.
        # Теперь: нормализованный поток реплик, точное вхождение первых
        # 60 знаков сцены, выбор ближайшего кандидата к `start_sec`.
        def _norm(x):
            return re.sub(r"[^0-9a-zа-яё ]+", " ",
                          re.sub(r"\s+", " ", str(x)).lower()).strip()

        _stream, _pos = "", []          # поток и (смещение, время) по репликам
        for _t, _c in _cu:
            _n = _norm(_c)
            if not _n:
                continue
            _pos.append((len(_stream), _t))
            _stream += _n + " "

        def _time_at(off):
            _last = _pos[0][1] if _pos else 0.0
            for _o, _t in _pos:
                if _o > off:
                    break
                _last = _t
            return _last

        # ПОИСК ИДЁТ ВПЕРЁД ПО КУРСОРУ, А НЕ «БЛИЖЕ К ЗАЯВЛЕННОМУ» (08.11,
        # замер вкладки `usuario-47`). Прежняя логика выбирала вхождение,
        # ближайшее к `start_sec` из файла, — и это верно, пока тайминг в
        # файле хотя бы примерно правильный. Но при ПОЗДНЕЙ озвучке (черновой
        # srt, потом настоящий) заявленное время смещено целиком: у неё
        # черновик был 698 с против настоящих 814, и привязка дала 57 сцен из
        # 61 при среднем сдвиге 1,54 с, худший случай 4,39 с.
        # Текст сцен идёт в том же порядке, что речь, поэтому правильнее
        # брать ПЕРВОЕ вхождение после предыдущей сцены и вести курсор.
        # Ключ ищем сначала длинный (60 знаков), потом короткий (первые
        # четыре слова) — агент иногда перефразирует хвост фразы.
        _prev = 0.0
        _cursor = 0
        for sc in scenes:
            _full = _norm(sc.get("text", ""))
            _tx = _full[:60]
            if len(_tx) < 15:
                continue
            _want = float(sc.get("start_sec") or 0)
            _cands = []
            for _key in (_tx, " ".join(_full.split()[:4])):
                if len(_key) < 12:
                    continue
                _i = _stream.find(_key, _cursor)
                if _i < 0:
                    _i = _stream.find(_key)          # хвост мог уйти назад
                while _i >= 0:
                    _cands.append((_i, _time_at(_i)))
                    _i = _stream.find(_key, _i + 1)
                if _cands:
                    break
            if _cands:
                # первое вхождение ПОСЛЕ курсора; нет такого — ближайшее к
                # заявленному времени, как раньше
                _after = [c for c in _cands if c[0] >= _cursor]
                _off, _best_t = (_after[0] if _after
                                 else min(_cands, key=lambda c: abs(c[1] - _want)))
                _cursor = _off + 1
            if not _cands:
                # точного вхождения нет (агент перефразировал) — старый путь
                # похожести, но тоже с выбором ближайшего к заявленному
                _near = [(abs(_t - _want), _t) for _t, _c in _cu
                         if _t >= _prev - 0.5
                         and _dl.SequenceMatcher(None, _tx,
                                                 _norm(_c)[:60]).ratio() >= 0.62]
                if not _near:
                    continue
                _best_t = min(_near)[1]
            _prev = max(_prev, _best_t)
            _d = _best_t - _want
            _drift.append((sc.get("id"), round(_best_t, 1), _d))
        _big = [x for x in _drift if abs(x[2]) > 4.0]
        if _big:
            _w = max(_big, key=lambda x: abs(x[2]))
            msg = ("КАРТИНКА РАСХОДИТСЯ С ОЗВУЧКОЙ: у %d сцен из %d начало не "
                   "совпадает с местом их текста в SRT больше чем на 4 с "
                   "(худшая — сцена %s: в файле %.1f с, в озвучке %.1f с, "
                   "разница %+.1f с). Сумма при этом сходится — проверять "
                   "надо РАСПРЕДЕЛЕНИЕ. Чинится `--fix`: тайминг снимается с "
                   "SRT по тексту каждой сцены."
                   % (len(_big), len(_drift), _w[0],
                      _w[1] - _w[2], _w[1], _w[2]))
            (bad if not a.fix else warn).append(msg)

    for w in warn:
        print("  ВНИМАНИЕ:", w)
    for b in bad:
        print("  ОШИБКА:", b, file=sys.stderr)

    if a.fix:
        if _drift and len([x for x in _drift if abs(x[2]) > 4.0]):
            # ТАЙМИНГ СНИМАЕМ С ОЗВУЧКИ ЦЕЛИКОМ, А НЕ ТОЧЕЧНО. Старт сцены —
            # место её текста в SRT; у сцен без надёжного совпадения (карточки,
            # короткие подписи) старт берётся ЛИНЕЙНОЙ ВСТАВКОЙ между
            # соседями, иначе цепочка рвётся и сумма уезжает. Длительность —
            # строго до старта следующей, у последней — до конца озвучки.
            _pts = {i: t for i, t, _d in _drift}
            _tot = (max(_ENDS) if _ENDS else (_cu[-1][0] + 4.0)) if _cu else None
            _ids = [sc.get("id") for sc in scenes]
            _st = []
            for _n, _sid in enumerate(_ids):
                _st.append(_pts.get(_sid))
            # вставка пропусков
            for _n in range(len(_st)):
                if _st[_n] is not None:
                    continue
                _l = next((m for m in range(_n - 1, -1, -1) if _st[m] is not None), None)
                _r = next((m for m in range(_n + 1, len(_st)) if _st[m] is not None), None)
                if _l is None and _r is None:
                    _st[_n] = 0.0
                elif _l is None:
                    _st[_n] = max(0.0, _st[_r] - 6.0 * (_r - _n))
                elif _r is None:
                    _st[_n] = _st[_l] + 6.0 * (_n - _l)
                else:
                    _st[_n] = _st[_l] + (_st[_r] - _st[_l]) * (_n - _l) / float(_r - _l)
            # монотонность и минимальная длина сцены
            for _n in range(1, len(_st)):
                if _st[_n] < _st[_n - 1] + 2.0:
                    _st[_n] = _st[_n - 1] + 2.0
            _end = _tot if _tot else (_st[-1] + 6.0)
            if _end < _st[-1] + 2.0:
                _end = _st[-1] + 2.0
            # НИ ОДНОЙ СЦЕНЫ КОРОЧЕ 3,5 с (05.11, улов `usuario-f4`: после
            # привязки появились сцены по 2,0 с — кадр не успевает прочитаться,
            # а отрезок медиатеки в такую сцену не лезет вовсе). Недостающее
            # ЗАНИМАЕМ У СОСЕДА: сначала двигаем начало сцены назад, если
            # предыдущая длинная, иначе отодвигаем начало следующей.
            _MINS = 3.5
            for _n in range(len(_st)):
                _nx = _st[_n + 1] if _n + 1 < len(_st) else _end
                _need = _MINS - (_nx - _st[_n])
                if _need <= 0:
                    continue
                _room_back = (_st[_n] - _st[_n - 1] - _MINS) if _n > 0 else _st[_n]
                _take = min(_need, max(0.0, _room_back))
                _st[_n] = round(_st[_n] - _take, 2)
                _need -= _take
                if _need > 0 and _n + 1 < len(_st):
                    _st[_n + 1] = round(_st[_n + 1] + _need, 2)
            _moved = []
            for _n, sc in enumerate(scenes):
                _was = float(sc.get("start_sec") or 0)
                sc["start_sec"] = round(_st[_n], 2)
                _nx = _st[_n + 1] if _n + 1 < len(_st) else _end
                sc["duration_sec"] = round(_nx - _st[_n], 2)
                if abs(_st[_n] - _was) > 8.0:
                    _moved.append((sc.get("id"), round(_st[_n] - _was, 1)))
            if _moved:
                print("  СЦЕНЫ СДВИНУЛИСЬ БОЛЬШЕ ЧЕМ НА 8 с — ПРОВЕРЬ ГЛАЗАМИ,")
                print("  на своих ли словах стоят их кадры (правило «кадр")
                print("  против слова»): "
                      + ", ".join("%s (%+.1f с)" % (i, d) for i, d in _moved[:12]))
            _short = [sc.get("id") for sc in scenes
                      if float(sc.get("duration_sec") or 0) < 3.0]
            if _short:
                print("  ВНИМАНИЕ: после привязки остались короткие сцены: "
                      + ", ".join(map(str, _short)))
            print("  тайминг снят с ОЗВУЧКИ по тексту сцен: привязано %d из %d, "
                  "остальные вставкой между соседями"
                  % (len(_pts), len(scenes)))
            # ЗАДАНИЯ КАРТОЧЕК ПРОТУХАЮТ ВМЕСТЕ С ТАЙМИНГОМ (08.11, улов
            # вкладки `usuario-47`). Карточка рисуется НА ТОЧНУЮ длительность
            # сцены, и эта длительность вшита в задание (`dur`, `anim`).
            # Пересобрали тайминг по настоящей озвучке — все задания стали
            # короче своих сцен: у неё озвучка пришла на 814 с против
            # черновых 698, и все восемнадцать карточек оказались короче на
            # 17% (сцена 29: было 7,6 с, стало 17,5). Инструменты об этом
            # молчали: `card_put` проверяет длительность в момент постановки,
            # `selfcheck` сверяет готовые клипы, которых ещё нет.
            # Раз новая длительность уже посчитана — чиним сами.
            _qdir = os.path.join(os.path.dirname(os.path.abspath(a.out or a.src)),
                                 "cards", "queue")
            _правлено = []
            if os.path.isdir(_qdir):
                _длит = {int(sc.get("id")): float(sc.get("duration_sec") or 0)
                         for sc in scenes}
                for _qf in sorted(glob.glob(os.path.join(_qdir, "scene_*.json"))):
                    try:
                        _q = json.load(open(_qf, encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    _sid = int(_q.get("scene") or 0)
                    _new = _длит.get(_sid)
                    if not _new or abs(float(_q.get("dur") or 0) - _new) < 0.05:
                        continue
                    _was = float(_q.get("dur") or 0)
                    _anim_was = float(_q.get("anim") or 0)
                    _q["dur"] = round(_new, 2)
                    # анимация: если рисовалась ВСЯ сцена — тянем за ней,
                    # если была короче (цитаты, мазки) — оставляем как есть,
                    # только не даём ей превысить новую длительность
                    _q["anim"] = (round(_new, 2) if _anim_was >= _was - 0.05
                                  else round(min(_anim_was, _new), 2))
                    # У cli-видов длительность лежит ЕЩЁ И ВНУТРИ cfg —
                    # рисовалка слушает именно её (08.11, улов `usuario-47`:
                    # поправили dur, а клип вышел на старые 9,2 с при сцене
                    # 14,0 и раскладка его отбила).
                    if isinstance(_q.get("cfg"), dict) and _q["cfg"].get("seconds"):
                        _q["cfg"]["seconds"] = round(_new, 2)
                    json.dump(_q, open(_qf, "w", encoding="utf-8"),
                              ensure_ascii=False)
                    _правлено.append("%d: %.1f→%.1f с" % (_sid, _was, _new))
            if _правлено:
                print("  задания карточек обновлены под новый тайминг (%d): %s"
                      % (len(_правлено), ", ".join(_правлено[:6])
                         + (" …" if len(_правлено) > 6 else "")))
                print("  карточки надо ПЕРЕВЫПУСТИТЬ: cards_cloud.py — иначе "
                      "клип короче сцены и в конце будет чёрный хвост")
            print("  сумма после привязки: %.1f с (озвучка %.1f с)"
                  % (sum(float(x.get("duration_sec") or 0) for x in scenes),
                     _end))
        t = 0.0
        for sc in scenes:
            sc["start_sec"] = round(t, 2)
            t += float(sc.get("duration_sec") or 0)
        print("  тайминг пересчитан подряд от нуля")
        neg = [s.get("id") for s in scenes if float(s.get("duration_sec") or 0) <= 0]
        if neg:
            bad.append("после пересчёта остались неположительные длительности у сцен "
                       + ", ".join(map(str, neg))
                       + " — это не дрейф, а выдуманные числа: переделка")

    # `--fix` ЧИНИТ ТОЛЬКО ТАЙМИНГ И НЕ СНИМАЕТ ОСТАЛЬНЫЕ ОШИБКИ (24.10).
    # Живой случай на `planeta-evak-2510`: без `--fix` приёмка честно отказывала
    # («ПРИНИМАТЬ НЕЛЬЗЯ», код 1), а с `--fix` печатала «принято → …» и код 0,
    # хотя в файле оставались отрицательная длительность −86,6 с у последней
    # сцены и два шаблона запросов. Вкладка, доверившая `--fix`, уехала бы в
    # фетч с мусором и ничего не заметила. Дыра была ровно в том месте, которое
    # приёмка и должна закрывать.
    # ПОЧИНЕННЫЙ ФАЙЛ СОХРАНЯЕТСЯ ВСЕГДА, ДАЖЕ ПРИ ОТКАЗЕ. Иначе выигрыш
    # мнимый: автопочинка разрезала свалку и пересобрала тайминг, файл не
    # принят из-за пустых запросов — и вся механика потеряна, вкладка идёт на
    # заход к агенту, ровно то, от чего уходили.
    _draft = ""
    if fixed_n and a.out:
        _draft = a.out + ".autofix.json"
        _d2 = dict(data) if isinstance(data, dict) else {}
        _d2["channel"] = a.channel
        _d2["scenes"] = scenes
        json.dump(_d2, open(_draft, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    if bad:
        _nq = need_query(scenes) if (a.fix and fixed_n and need_query) else []
        if _nq:
            print("\nВПИШИ ЗАПРОСЫ САМА — ЭТО МИНУТА, ЗАХОД К АГЕНТУ НЕ НУЖЕН "
                  "(%d сцен):" % len(_nq))
            for _sc in _nq:
                print("  сцена %s (%.1f с): %s"
                      % (_sc.get("id"), float(_sc.get("duration_sec") or 0),
                         str(_sc.get("text", ""))[:160]))
            if _draft:
                print("  правь в %s и прогони приёмку по нему" % _draft)
        print("\nПРИНИМАТЬ НЕЛЬЗЯ — исправь перечисленное или попроси переделать."
              + ("\n(механическое `--fix` уже починил, см. строки ПОЧИНЕНО; "
                 "перечисленное выше — смысловое, его пишет вкладка или "
                 "переделывает агент.)" if a.fix else ""),
              file=sys.stderr)
        return 1
    if a.out:
        if isinstance(data, dict):
            data["channel"] = a.channel
            data["scenes"] = scenes
        else:
            data = {"channel": a.channel, "scenes": scenes}
        json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\nпринято → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
