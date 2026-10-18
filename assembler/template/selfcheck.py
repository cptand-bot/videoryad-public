#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Полная самопроверка сборки по SKILL.md ПЕРЕД тем как:
  - отдавать дашборд пользователю,
  - говорить «готово к собирай»,
  - запускать build_clips / assemble_final.

Обязательное правило (user, 2026-09-06, после 07.09-2: «делай самопроверку
каждого своего шага на полный цикл. Не делать ни одного действия лишнего
без самопроверки»). Косяк из задачи в задачу всплывает потому, что шаги
скилла пропускаются молча — этот скрипт их ловит.

Запуск:  python3 selfcheck.py <scenes.json> [images_dir]
Код возврата 0 = всё чисто. !=0 = есть НАРУШЕНИЯ, чинить до отдачи дашборда.
"""
import glob, hashlib, json, os, subprocess, sys

scenes_path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("*.scenes.json"))[0]
images = sys.argv[2] if len(sys.argv) > 2 else "images"
proj = os.path.dirname(os.path.abspath(scenes_path)) or "."
os.chdir(proj)

FAIL, WARN = [], []
d = json.load(open(scenes_path, encoding="utf-8"))
scenes = d["scenes"] if isinstance(d, dict) else d
# Канал в шапке `<niche>.scenes.json` лежит ВЕРХНИМ УРОВНЕМ (`channel`), а не
# в блоке `meta` — проверено на всех живых проектах 2026-10-16. Раньше читался
# только `meta`, которого там нет ни у кого: печаталось «канал ?», и проверка
# `anchor` по каналу МОЛЧА не выполнялась ни разу за всё время. Читаем оба
# места, чтобы работало и со старыми файлами, где `meta` всё-таки есть.
meta = {} if not isinstance(d, dict) else {**d, **(d.get("meta") or {})}
ids = [s["id"] for s in scenes]
total = sum(s["duration_sec"] for s in scenes)

def asset(i):
    return [f for f in glob.glob(f"{images}/scene_{i:03d}.*") if not f.endswith(".json")]

needs = {}
if os.path.exists("needs_upload.json"):
    needs = json.load(open("needs_upload.json", encoding="utf-8"))

# 1. каждая сцена — либо файл, либо needs_upload
for i in ids:
    if not asset(i) and str(i) not in needs:
        FAIL.append(f"сцена {i}: нет ни картинки, ни записи в needs_upload.json")

# 2. format sniff — не-JPEG под .jpg (SKILL.md 2d)
for f in glob.glob(f"{images}/scene_*.jpg"):
    kind = subprocess.run(["file", "-b", f], capture_output=True, text=True).stdout
    if "JPEG" not in kind and "JFIF" not in kind:
        FAIL.append(f"{f}: не JPEG ({kind.strip()[:30]}) — build_clips подавится")

# 2b. oversized video source (user, 2026-09-16, furious — a whole 359s
# compilation reel got hand-pinned as a "single scene" clip and copied
# verbatim into images/, which build_clips_1080.py DOES trim correctly at
# build time (-t duration), but a source this large chokes/slows the live
# dashboard's thumbnail step and is a sign a long multi-shot compilation was
# used raw instead of being indexed (SKILL.md rule 3). Catch it before it
# ever reaches fetch/dashboard, not after.
for i, s in ((s["id"], s) for s in scenes):
    if s.get("source") != "local_library":
        continue  # pexels_video/press stock clips are legitimately longer than the cut; only a library exact-file pin risks being a whole compilation
    for f in asset(i):
        if not f.lower().endswith((".mp4", ".mov", ".webm")):
            continue
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", f], capture_output=True, text=True, timeout=10)
            src_dur = float(r.stdout.strip() or 0)
        except Exception:
            continue
        want = s["duration_sec"]
        if src_dur > max(30, want * 5):
            FAIL.append(f"{f}: источник {src_dur:.0f}с при нужных {want:.1f}с — похоже на "
                        f"целую нарезку/компиляцию, взятую как один клип (SKILL.md rule 3, "
                        f"index_library.py detect до использования, не голым файлом)")

# 3. дубли одного файла (no-repeat, SKILL.md rule 4/5)
h = {}
for f in glob.glob(f"{images}/scene_*.*") + glob.glob("overlays/scene_*.*"):
    if f.endswith((".json", ".text.png")):   # .text.png — рендер слова, дубли норм
        continue
    h.setdefault(hashlib.md5(open(f, "rb").read()).hexdigest(), []).append(os.path.basename(f))
for k, v in h.items():
    if len(v) > 1:
        FAIL.append(f"одинаковый файл в: {sorted(v)}")

# 4. overlays.json — ОБЯЗАН быть до дашборда, ~3/мин, anchor по каналу (SKILL.md 3b)
if not os.path.exists("overlays.json"):
    FAIL.append("overlays.json НЕТ — всплывашки не расставлены (SKILL.md 3b, обязательно ДО дашборда)")
else:
    ov = json.load(open("overlays.json", encoding="utf-8"))
    n_ov = len([k for k in ov if k != "anchor"])
    per_min = n_ov / (total / 60)
    # Плотность всплывашек — всегда ПРЕДУПРЕЖДЕНИЕ, не блокер: пользователь
    # удаляет лишние на дашборде (его правки = финал). ПЛАНЕТА целится в ~3/мин,
    # поиск-только идёт реже (прецедент «Чудовищные потери 2» ~1.3/мин).
    if per_min < 2.5:
        WARN.append(f"всплывашек {n_ov} ({per_min:.1f}/мин) — на ПЛАНЕТЕ ~3/мин; меньше — ок, если это твои правки")
    # у всех всплывашек пустой sound -> видеоряд выйдет без звука всплывашек
    # (feedback_overlays_sound_field_lost, 2026-09-08). Переприсвоить sound
    # (['whoosh','zatvor','pop'][i%3]) и локально прогнать build_overlays.py sfx.
    snd = [v.get("sound") or (v.get("text", {}).get("sound", "") if isinstance(v.get("text"), dict) else "")
           for k, v in ov.items() if k != "anchor"]
    if snd and not any(snd):
        FAIL.append("у ВСЕХ всплывашек sound='' — видеоряд соберётся БЕЗ звука "
                    "всплывашек. Переприсвоить sound в overlays.json.")
    ch = (meta.get("channel") or "").upper()
    want = "bottom" if "ПЛАНЕТА" in ch or "ПЛАНЕТА" == ch else "top"
    if ch and ov.get("anchor", "bottom") != want:
        FAIL.append(f"overlays anchor={ov.get('anchor','bottom')}, для канала {ch} нужен {want} (SKILL.md 3b)")
    for k, v in ov.items():
        if k == "anchor":
            continue
        ph = v.get("photo", "")
        tb = v.get("text") if isinstance(v.get("text"), dict) else None
        has_txt = bool(tb and str(tb.get("words") or tb.get("text") or "").strip())
        if not ph and has_txt:
            continue                       # чисто текст-всплывашка — фото не нужно
        if not os.path.exists(ph):
            FAIL.append(f"всплывашка {k}: файла нет ({ph})")
            continue
        oh = hashlib.md5(open(ph, "rb").read()).hexdigest()
        bf = asset(int(k))
        if bf and hashlib.md5(open(bf[0], "rb").read()).hexdigest() == oh:
            FAIL.append(f"всплывашка {k} = базовый кадр сцены (нельзя, SKILL.md 3b)")

    # 4b. всплывашка называет ТОГО ЖЕ человека/институт, что и базовый кадр —
    # не ловится md5 (два РАЗНЫХ файла одного и того же человека всё ещё
    # нарушение, user 2026-10-05/08: "Трамп всплывашка иллюстрирует Трампа",
    # "Сибига иллюстрирует Сибигу"). Сверяем имена собственные в запросах,
    # а не пиксели — работает даже когда это два разных фото одного лица.
    import re as _re
    def _names(text):
        # includes Ukrainian-only letters (і/ї/є/ґ) — without them a Cyrillic
        # word truncates mid-letter ("Київ"->"Ки", "Чернігівський"->"Черн")
        # and those stubs false-match across unrelated scenes (found live,
        # session 2026-10-08, peer session on an all-Ukrainian "5 МИНУТ" build).
        return set(_re.findall(r"[А-ЯЁІЇЄҐ][а-яёіїєґА-ЯЁІЇЄҐ]+", text or ""))
    _STOP = {"Украины", "Украина", "Украине", "Киев", "Киева", "Москва", "Москвы",
              "России", "Россия", "Верховная", "Рада", "Радой", "Радою", "НАТО",
              "МИД", "МЗС", "Кремль", "США", "ЕС", "Индии", "Индия",
              # Ukrainian/other-language forms of the same stop-words — without
              # these, a scene/overlay pair written in Ukrainian (or naming a
              # country other than RU/UA) false-flagged as a name collision
              # just because both mentioned "Україна"/"Ємен" (user_56 report,
              # cross-session, 2026-10-10). Add more language forms here as
              # they're caught, same spirit as the a3 cheat-sheet below.
              "Україна", "України", "Україні", "Україну", "Україною",
              "Київ", "Києва", "Києві", "Київу", "Москві", "Росія", "Росії",
              "Росію", "Росією", "ЗСУ", "Кремля", "Кремлі", "Ємен", "Ємену",
              "Йемен", "Йемену", "Йемена", "ЄС", "Індія", "Індії"}
    # ГЕОГРАФИЯ — НЕ «ТОТ ЖЕ ЧЕЛОВЕК» (2026-10-17, БЛОКЕР на
    # planeta-tri-bukvy-1810: девять FAIL из девяти были совпадением
    # страноведческого слова — «Германии», «Европейского», «Словакии»,
    # «Эстонии»). База «здание ЕЦБ во Франкфурте» + всплывашка «Кристин
    # Лагард глава Европейского центрального банка» — это ОДОБРЕННЫЙ приём
    # «лицо того, кто в этом здании решает», а проверка его бракует. На
    # ролике, где все 85 сцен про Германию и ЕС, секция была неработоспособна
    # и обходилась косметикой запроса, то есть не работала вовсе.
    # Поэтому из сравнения выбрасываются страны, города и производные от них
    # прилагательные — по КОРНЮ, а не поимённым списком форм.
    # Фамилии НЕ трогаем: «Зеленский», «Навальный» и прочие -ский остаются,
    # иначе проверка потеряет главный свой случай.
    _GEO_STEMS = (
        "герман", "немецк", "европ", "евросоюз", "брюссел", "страсбург",
        "франкфурт", "берлин", "мюнхен", "гамбург", "кёльн", "кельн",
        "дрезден", "штутгарт", "дюссельдорф", "бонн", "рамштайн",
        "словак", "словацк", "словен", "чехи", "чешск", "праг", "венгр",
        "будапешт", "польш", "польск", "варшав", "эстон", "таллин",
        "латви", "рига", "литв", "вильнюс", "франц", "париж", "итали",
        "рим", "испан", "мадрид", "португал", "греци", "афин", "турци",
        "анкар", "стамбул", "румын", "бухарест", "болгар", "софи",
        "серби", "хорват", "австри", "вен", "швейцар", "женев", "швеци",
        "стокгольм", "норвег", "осло", "финлянд", "хельсинки", "дани",
        "копенгаген", "нидерланд", "амстердам", "роттердам", "гааг",
        "бельги", "люксембург", "ирланд", "британ", "англи", "лондон",
        "шотланд", "америк", "вашингтон", "сша", "китай", "кита", "пекин",
        "япони", "токио", "коре", "инди", "иран", "тегеран", "ирак",
        "израил", "иерусалим", "сири", "египт", "африк", "азербайджан",
        "армени", "грузи", "казахстан", "белорус", "беларус", "минск",
        "молдов", "кишинёв", "кишинев", "балти", "крым", "донецк",
        "луганск", "харьков", "одесс", "львов", "днепр", "запорож",
        "херсон", "мариупол", "киев", "київ", "москв", "петербург",
        "украин", "україн", "росси", "росі", "брюссель",
    )

    def _is_geo(w):
        lw = w.lower()
        return any(lw.startswith(st) for st in _GEO_STEMS)

    _by_id = {s["id"]: s for s in scenes}
    _ovq_path = None
    for _cand in glob.glob("*overlays_fetch*.json") + glob.glob("*overlay*fetch*.scenes.json"):
        _ovq_path = _cand
        break
    if _ovq_path and os.path.exists(_ovq_path):
        _ovq = {s["id"]: s.get("source_query", "") for s in json.load(open(_ovq_path, encoding="utf-8"))["scenes"]}
        for k, v in ov.items():
            if k == "anchor":
                continue
            sid = int(k)
            base_q = _by_id.get(sid, {}).get("source_query", "")
            ov_q = _ovq.get(sid, "")
            shared = (_names(base_q) - _STOP) & (_names(ov_q) - _STOP)
            shared = {w for w in shared if not _is_geo(w)}
            if shared:
                FAIL.append(f"всплывашка {k}: тот же человек/объект ({', '.join(sorted(shared))}) "
                            f"что и базовый кадр — база: {base_q!r}, всплывашка: {ov_q!r}")
        # 4c. ИМЯ В ТЕКСТОВОЙ ВСПЛЫВАШКЕ ДОЛЖНО СТОЯТЬ НА КАДРЕ ЭТОГО ЧЕЛОВЕКА
        # (2026-10-18, третий случай за два дня — значит проверять должен код).
        # Дефект рождается не при расстановке, а при ПРАВКЕ: вкладка меняет
        # базовый кадр, а именная надпись остаётся от прежнего. Живьём:
        # «надпись Анна Скороход, а на фотографии Зеленский» (17.10) и
        # «ВАННАЧЧИ: ЕВРОПА — НЕ БАНКОМАТ» на панораме Рима, куда база уехала
        # после замены (18.10). Зритель читает это как «подписали не того».
        #
        # Как отличаем ИМЯ от обычного слова капсом, не заводя стоп-листа:
        # слово из надписи считается именем, только если где-то в ТЕКСТАХ сцен
        # встречается то же слово с ЗАГЛАВНОЙ буквы («Ванначчи», «Скороход»).
        # «ЗАКОННЫЕ», «НОЯБРЬ», «ГРАНИЦА» в текстах идут со строчной и именами
        # не считаются. Эвристику «текст без цифры и имени = абстракция» тут
        # НЕ повторяем — её сняли 17.10 за 26 ложных из 41.
        # Это WARN, а не FAIL: бывает законный случай (надпись про человека,
        # которого кадр подразумевает), и блокировать сдачу из-за него нельзя.
        # ПОЧИНЕНО 2026-10-18 В ТОТ ЖЕ ЧАС: первая версия давала 6 ложных из 6
        # на живом ролике («ПОДПИСИ», «БАНКОМАТ», «ОПЕРАЦИЯ», «БОЛЬШЕ»,
        # «ДОХОДЫ»). Причина системная: в закадровом тексте полно слов В НАЧАЛЕ
        # ПРЕДЛОЖЕНИЯ, и они тоже с заглавной («Банкомат. Подошёл. Вставил
        # карту»), а надписи вкладка строит из ключевых слов фразы — почти
        # каждое где-то открывает предложение. Стенд этого не показал, потому
        # что проверочные надписи в текстах шли со строчной.
        # Теперь имя засчитывается, только если слово встречается с заглавной
        # НЕ в начале предложения (фамилия внутри фразы стоит всегда) И нигде
        # не встречается со строчной (нарицательное хоть раз да будет строчным).
        _all_text = " ".join(sc.get("text", "") or "" for sc in scenes)
        _lower_seen = {w.lower() for w in _re.findall(r"[а-яёіїєґ]{5,}", _all_text)}
        _name_pool = set()
        for _sc in scenes:
            _t = _sc.get("text", "") or ""
            for _m in _re.finditer(r"[А-ЯЁІЇЄҐ][а-яёіїєґА-ЯЁІЇЄҐ]{4,}", _t):
                _w = _m.group(0)
                _before = _t[:_m.start()].rstrip(" «\"'(—-")
                if not _before or _before[-1] in ".!?…:;":
                    continue              # начало предложения — не признак имени
                if _w.lower() in _lower_seen:
                    continue              # где-то идёт со строчной = нарицательное
                if _is_geo(_w):
                    continue
                _name_pool.add(_w.lower()[:5])
        for k, v in ov.items():
            if k == "anchor" or not isinstance(v, dict):
                continue
            _tb = v.get("text") or {}
            _words = str(_tb.get("words") or "")
            if not _words:
                continue
            sid = int(k)
            _base_q = (_by_id.get(sid, {}).get("source_query", "") or "").lower()
            for _tok in _re.findall(r"[А-ЯЁІЇЄҐ]{5,}", _words):
                _stem = _tok.lower()[:5]
                if _stem not in _name_pool or _is_geo(_tok):
                    continue
                if _stem not in _base_q:
                    WARN.append(
                        f"всплывашка {k}: надпись называет «{_tok}», а базовый "
                        f"кадр этой сцены про другое ({_base_q!r}) — именная "
                        f"надпись ставится ТОЛЬКО на кадр этого человека; "
                        f"частая причина: базу меняли, а надпись осталась")

        # ЛИШНИЕ ЗАПИСИ В FETCH-ФАЙЛЕ = ВОСКРЕШЕНИЕ СНЯТОГО (2026-10-16).
        # Пользователь снимает всплывашки на дашборде, overlays.json худеет,
        # а overlays_fetch.scenes.json остаётся прежним — и облако набирает
        # кадры для снятых, после чего они возвращаются в ролик. Правило 13
        # велит подрезать fetch-файл руками, но проверку легко проскочить:
        # раньше selfcheck сверял overlays.json только с файлами на диске и
        # на это не ругался вовсе (поймано живьём на planeta-yalta-1710,
        # 55 записей против 44). Стоит миллисекунду, закрывает весь класс.
        _ov_ids = {int(k) for k in ov if k != "anchor"}
        _extra = sorted(set(_ovq) - _ov_ids)
        if _extra:
            FAIL.append(
                f"{_ovq_path}: лишние {len(_extra)} записей, которых нет в overlays.json "
                f"(id: {', '.join(map(str, _extra[:12]))}{'…' if len(_extra) > 12 else ''}) — "
                f"облако наберёт кадры для СНЯТЫХ всплывашек и они вернутся в ролик. "
                f"Подрезать fetch-файл до состава overlays.json перед ship (SKILL.md п.13)")

# 5. видео-лид (SKILL.md rule 7) — ПРЕДУПРЕЖДЕНИЕ, не блокер: пользователь
# может сознательно наменять фото в первой трети на дашборде (его правки =
# финал). Флагаем, чтобы он знал, но сборку не держим.
# Соседний скрипт — ПО ПОЛНОМУ ПУТИ ОТ СЕБЯ, а не по имени из cwd
# (2026-10-17): selfcheck теперь гоняется из template при cwd = папка
# проекта, и голое имя искалось бы в проекте, где копии может не быть.
_HERE = os.path.dirname(os.path.abspath(__file__))
r = subprocess.run(["python3", os.path.join(_HERE, "check_lead.py"), scenes_path, images],
                   capture_output=True, text=True)
if r.returncode != 0:
    WARN.append("видео-лид не выполнен (см. ниже) — ок, если это твои правки на дашборде:\n     "
                + (r.stdout + r.stderr).strip().replace("\n", "\n     ")[:400])

# 4c. ВИДЕО КОРОЧЕ СВОЕЙ СЦЕНЫ = ВИДИМАЯ ПЕТЛЯ (2026-10-17). build_clips
# добивает короткий источник `-stream_loop -1`, то есть клип 6,0 с на сцене
# 10,0 с проигрывается полтора раза подряд — зритель видит повтор движения.
# В логе фетча при этом честный `ok`: файл скачан, он просто короткий.
# Ловится только сверкой длительности файла с `duration_sec` сцены.
_short = []
for _s in scenes:
    _a = asset(_s["id"])
    if not _a or not _a[0].lower().endswith((".mp4", ".mov")):
        continue
    try:
        _pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", _a[0]],
                             capture_output=True, text=True)
        _d = float((_pr.stdout or "0").strip() or 0)
    except Exception:
        continue
    _need = float(_s.get("duration_sec") or 0)
    if _d and _need and _d < _need - 0.25:
        _short.append(f"сцена {_s['id']}: клип {_d:.1f}с на сцену {_need:.1f}с "
                      f"(петля ×{_need/_d:.1f})")
if _short:
    WARN.append("видео КОРОЧЕ своей сцены — будет видимый повтор движения, "
                "заменить или укоротить сцену:\n     " + "\n     ".join(_short[:10]))

# 5a. ВСПЛЫВАШКА С ТЕМ ЖЕ ЗАПРОСОМ, ЧТО И БАЗОВЫЙ КАДР (2026-10-17).
# Найдено прямо в журнале отказов: на 5min-gerasimov сцена 7 — и база, и
# всплывашка «Московский Кремль Спасская башня флаг России», пользователь
# снял со словами «не понимаю наличие этой всплывашки». Это механическая
# ошибка классификации, глазами её ловить незачем.
try:
    _ovq = {}
    for _cand in glob.glob("*overlays_fetch*.json") + glob.glob("*overlay*fetch*.scenes.json"):
        try:
            for _o in json.load(open(_cand, encoding="utf-8")).get("scenes", []):
                _ovq[int(_o.get("id", -1))] = (_o.get("source_query") or "").strip().lower()
        except (OSError, ValueError, TypeError):
            continue
    for _s in scenes:
        _q = (_s.get("source_query") or "").strip().lower()
        if _q and _ovq.get(_s["id"]) == _q:
            FAIL.append(f"всплывашка {_s['id']}: запрос ТОТ ЖЕ, что у базового кадра "
                        f"(«{_q[:50]}») — она ничего не добавляет, переписать или снять")
except Exception:
    pass

# 5b. СВЕРКА ВСЕЙ СБОРКИ С АКТИВНЫМ БАН-ЛИСТОМ (2026-10-17). Фетчер баны
# чтит на всех путях (скачивание, кэш, библиотека, дашбордная замена), и всё
# же на `planeta-svergnut-1810` забаненный девять дней назад кадр (чужое лицо,
# выдаваемое поиском за Гончаренко) оказался в готовой сборке. Поймала его
# только ручная сверка перед ship — ни фетчер, ни selfcheck, ни четыре
# субагента не увидели: лицо похожее, на плитке не отличить. Путь, которым он
# прошёл, по логам восстановить не удалось — значит нужен ПОСЛЕДНИЙ рубеж,
# который не зависит от того, каким путём файл попал в папку.
_ban_path = os.environ.get("VIDEORYAD_BANNED_FILE") or os.path.expanduser(
    "~/projects/media-library/.banned_md5.json")
try:
    import time as _t
    _ban_raw = json.load(open(_ban_path, encoding="utf-8"))
    _today = _t.strftime("%Y-%m-%d")
    _ban = {m for m, e in _ban_raw.items()
            if not (isinstance(e, dict) and e.get("until")) or e["until"] >= _today}
except (OSError, ValueError):
    _ban_raw, _ban = {}, set()
if _ban:
    _checked = 0
    for _p in sorted(glob.glob(f"{images}/scene_*.*") + glob.glob("overlays/scene_*.*")):
        if _p.endswith((".json", ".revframe.jpg", ".ovthumb.jpg")):
            continue
        try:
            _h = hashlib.md5(open(_p, "rb").read()).hexdigest()
        except OSError:
            continue
        _checked += 1
        if _h in _ban:
            _why = (_ban_raw.get(_h) or {}).get("reason", "")
            FAIL.append(f"ЗАБАНЕННЫЙ КАДР В СБОРКЕ: {_p} (md5 {_h[:10]}) — "
                        f"бан от {(_ban_raw.get(_h) or {}).get('date','?')}: {_why or 'без причины'}. "
                        f"Заменить до сборки.")
    print(f"[selfcheck] сверка с бан-листом: {_checked} файлов против {len(_ban)} активных банов")

# 6. сцена 1 = видео — БЫЛО hard FAIL, РАЗЖАЛОВАНО В WARN (user, 2026-10-08,
# зло: "исключаем из правила первый кадр видео... топчетесь на одном месте и
# какую-то ерунду явную подсовываете" — после того как search-only канал
# (5 МИНУТ) не смог найти реальное видео конкретного события ни с одной
# формулировкой запроса, и единственной альтернативой жёсткому гейту было
# либо нерелевантный сток, либо AI-фабрикация). Правило "видео лучше, если
# есть осмысленное" остаётся советом (см. ниже), но больше не блокер.
any_video = any(a and a[0].endswith((".mp4", ".mov")) for a in (asset(i) for i in ids))
a1 = asset(ids[0])
if a1 and not a1[0].endswith((".mp4", ".mov")):
    if any_video:
        WARN.append(f"сцена {ids[0]} не видео (было бы по старому правилу видео-лида, "
                    "но правило сцена-1=видео отменено 2026-10-08 — это не блокер)")
    else:
        WARN.append("во всём ролике нет ни одного видео — весь видеоряд из фото (Ken Burns). "
                    "Ок для канала на поиске-только; для ПЛАНЕТЫ так быть не должно.")

print("=" * 60)
print(f"САМОПРОВЕРКА: {scenes_path}  ({len(scenes)} сцен, {total:.0f}с, канал {meta.get('channel','?')})")
print("=" * 60)
if WARN:
    print("\n⚠ ПРЕДУПРЕЖДЕНИЯ:")
    for w in WARN:
        print("  -", w)
if FAIL:
    print(f"\n❌ НАРУШЕНИЙ: {len(FAIL)} — чинить ДО отдачи дашборда:")
    for x in FAIL:
        print("  -", x)
    sys.exit(1)
print("\n✅ всё чисто — дашборд можно отдавать")
