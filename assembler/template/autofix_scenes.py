# -*- coding: utf-8 -*-
"""АВТОПОЧИНКА ФАЙЛА РАСКАДРОВКИ ВНЕШНЕГО АГЕНТА (04.11).

ЗАЧЕМ. Замер 04.11 по 28 сырым файлам агента за 30.10-05.11: приёмка не
пропускает 8 (29%), и каждый отказ стоит ЗАХОДА к нему — 13 минут на ролик.
Причины отказов по числу файлов: свалка остатка скрипта в одну сцену 4 ·
одинаковое начало запроса 3 · одна папка медиатеки на 10 сценах 2 ·
выдуманный путь к файлу медиатеки 2 · сцены короче трёх секунд 1.

Четыре из пяти причин чинятся МЕХАНИЧЕСКИ, без него, — этим и занят файл.
Пятая («одинаковое начало запроса») требует смысла и остаётся вкладке.

ЧТО ЧИНИТСЯ САМО И ПОЛНОСТЬЮ:
  1. выдуманный ФАЙЛ в живой папке медиатеки — подставляется существующий
     файл той же папки (только `БАЗА`, только шире 1600 px, не в бан-листе,
     не занятый другой сценой этого же ролика);
  2. сцена короче трёх секунд — склеивается с соседней, сумма сохраняется.

ЧТО ЧИНИТСЯ МЕХАНИКОЙ, А ТЕКСТ ЗАПРОСА ДОПИСЫВАЕТ ВКЛАДКА (не агент):
  3. свалка остатка скрипта: тайминг сцен пересобирается ПО SRT (текст каждой
     сцены ищется в субтитрах, оттуда берётся настоящее начало), непокрытый
     отрезок режется на сцены по 11,5 с по границам предложений;
  4. папка медиатеки больше чем на двух сценах — лишние сцены снимаются с
     папки.
Новым и снятым сценам ставится пустой `source_query`: приёмка их честно
назовёт и файл не примет, пока вкладка не впишет запросы. Это одна минута
её работы вместо тринадцати минут захода.

ГЛАВНОЕ ОГРАНИЧЕНИЕ (его правило 04.11: «после каждого улучшения начинается
ухудшение; можно не трогать старое, которое работает?»). Пересборка тайминга
включается ТОЛЬКО когда файл и так не принимается по свалке текста или когда
заявленное начало сцены расходится с SRT больше чем на 5 секунд. У нормального
файла агента ни одна цифра не меняется — проверено прогоном по 28 файлам.
"""
import datetime
import hashlib
import json
import os
import re
import sys

PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")

MIN_SCENE = 3.0        # короче — склеиваем с соседней (норма приёмки)
CUT_MAX = 16.0         # длиннее — режем (норма приёмки: сцена 3…15 с)
CUT_TARGET = 11.5      # целевая длина куска (норма сцен = длительность/11,5)
MIN_CHUNK = 5.0        # короче куска не делаем
PHOTO_MIN_W = 1600     # порог качества фото (его слово 31.10)
DRIFT_TRIGGER = 5.0    # расхождение с SRT, после которого пересобираем тайминг
DENSITY_MAX = 35.0     # знаков в секунду, выше — свалка остатка скрипта
BAN_FILE = "~/projects/media-library/.banned_md5.json"


# ---------------------------------------------------------------- SRT

def cues(path):
    """[(начало, конец, текст)] из SRT."""
    try:
        txt = open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return []
    out = []
    pat = (r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*"
           r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})\s*\n(.*?)(?=\n\s*\n|\Z)")
    for m in re.finditer(pat, txt, re.S):
        a = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
             + int(m.group(3)) + int(m.group(4)) / 1000.0)
        b = (int(m.group(5)) * 3600 + int(m.group(6)) * 60
             + int(m.group(7)) + int(m.group(8)) / 1000.0)
        t = " ".join(m.group(9).split())
        if t and b > a:
            out.append((a, b, t))
    return out


def _norm(s):
    """Текст для сверки: буквы, цифры и одиночные пробелы, «ё» = «е»."""
    s = str(s or "").lower().replace("ё", "е")
    s = re.sub(r"[^0-9a-zа-я]+", " ", s)
    return " ".join(s.split())


def _flat(cs):
    """Весь текст субтитров строкой + время начала КАЖДОГО символа."""
    buf, tms = [], []
    for a, b, t in cs:
        n = _norm(t)
        if not n:
            continue
        step = (b - a) / len(n)
        for i, ch in enumerate(n):
            buf.append(ch)
            tms.append(a + step * i)
        buf.append(" ")
        tms.append(b)
    return "".join(buf), tms


def _sentence_ends(cs):
    """Времена концов реплик, которыми кончается предложение."""
    return [b for _a, b, t in cs if t.rstrip()[-1:] in ".!?…"]


# ---------------------------------------------------------------- бан-лист

def banned_md5():
    """md5 → запись, только действующие баны (просроченные `--days` не в счёт)."""
    try:
        d = json.load(open(os.path.expanduser(BAN_FILE), encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    today = datetime.date.today().isoformat()
    out = {}
    for k, v in (d.items() if isinstance(d, dict) else []):
        if isinstance(v, dict) and v.get("until") and str(v["until"]) < today:
            continue
        out[k] = v
    return out


def _md5(path):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for part in iter(lambda: f.read(1 << 20), b""):
                h.update(part)
    except OSError:
        return ""
    return h.hexdigest()


def _width(path):
    """Ширина кадра: из имени файла (`07_1600x900.jpg`), иначе измерением."""
    m = re.search(r"(\d{3,5})x(\d{3,5})", os.path.basename(path))
    if m:
        return int(m.group(1))
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size[0]
    except Exception:
        return 0


# ------------------------------------------------- 1. выдуманный файл

def _resolve(lib, rel):
    """Путь к тегу медиатеки так, как его видит фетчер (через приёмку)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from accept_scenes import _lib_has
    except Exception:
        return ""
    try:
        return _lib_has(lib, rel)
    except Exception:
        return ""


def fix_missing_file(scenes, lib, log):
    """Выдуманный ФАЙЛ в живой папке `БАЗА` → существующий файл той же папки."""
    if not lib or not os.path.isdir(lib):
        return
    taken = set()
    for sc in scenes:
        q = str(sc.get("source_query", "")).replace("\\", "/").strip("/")
        if str(sc.get("source", "")).strip() == "local_library" and q:
            taken.add(os.path.basename(q).lower())
    ban = banned_md5()
    for sc in scenes:
        if str(sc.get("source", "")).strip() != "local_library":
            continue
        tag = str(sc.get("source_query", "")).replace("\\", "/").strip("/")
        ext = os.path.splitext(tag)[1].lower()
        if ext not in PHOTO_EXT + VIDEO_EXT:
            continue                      # это папка, а не файл — не наш случай
        if _resolve(lib, tag):
            continue                      # файл на месте
        head = os.path.dirname(tag)
        if "БАЗА" not in head.upper():
            # В старой библиотеке `ПОЛИТИКА/*` ниже порога 1600 px лежит 81%
            # из 1409 фото (замер 04.11) — автоподстановка оттуда вернула бы
            # ровно те мутные кадры, на которые он жаловался. Не трогаем.
            continue
        hit = _resolve(lib, head)
        if not hit or not os.path.isdir(hit):
            continue                      # папки нет — выдумать её нечем
        want = VIDEO_EXT if ext in VIDEO_EXT else PHOTO_EXT
        cands = []
        try:
            names = sorted(os.listdir(hit))
        except OSError:
            continue
        for nm in names:
            if not nm.lower().endswith(want):
                continue
            if nm.lower() in taken:
                continue
            p = os.path.join(hit, nm)
            if not os.path.isfile(p):
                continue
            if _md5(p) in ban:
                continue
            if want is PHOTO_EXT:
                w = _width(p)
                if w and w < PHOTO_MIN_W:
                    continue
                cands.append((w, nm))
            else:
                yr = re.search(r"_(20\d\d)_", nm)
                cands.append((int(yr.group(1)) if yr else 0, nm))
        if not cands:
            continue                      # нечего подставить — пусть отказ
        cands.sort(reverse=True)
        pick = cands[0][1]
        sc["source_query"] = head + "/" + pick
        taken.add(pick.lower())
        log.append("сцена %s: файла «%s» в папке нет — поставил «%s» из той же "
                   "папки (%s px, не в бане, не занят другой сценой)"
                   % (sc.get("id"), os.path.basename(tag), pick,
                      cands[0][0] if want is PHOTO_EXT else "видео"))


# ------------------------------------------------- 2. короткие сцены

def fix_short(scenes, log):
    """Сцена короче трёх секунд склеивается с соседней, сумма сохраняется.

    КЛЕИМ К КОРОТКОЙ ИЗ СОСЕДЕЙ (04.11): на `planeta-pomosch` склейка «всегда
    в предыдущую» выгнала пять сцен за 15 с — застывший кадр на 18 секунд
    вместо двух нормальных. Выбор более короткого соседа держит сцены в норме
    3…15 с без всякой дополнительной правки.
    """
    out = []
    for i, sc in enumerate(scenes):
        d = float(sc.get("duration_sec") or 0)
        if d >= MIN_SCENE or len(scenes) < 2:
            out.append(sc)
            continue
        _nd = float(scenes[i + 1].get("duration_sec") or 0) if i + 1 < len(scenes) else 1e9
        _pd = float(out[-1].get("duration_sec") or 0) if out else 1e9
        if out and _nd < _pd and i + 1 < len(scenes):
            nxt = scenes[i + 1]
            nxt["duration_sec"] = round(float(nxt.get("duration_sec") or 0) + d, 2)
            nxt["start_sec"] = float(sc.get("start_sec") or 0)
            nxt["text"] = (str(sc.get("text", "")).rstrip() + " "
                           + str(nxt.get("text", "")).lstrip()).strip()
            log.append("сцена %s (%.1f с) короче трёх секунд — склеил со "
                       "следующей (она короче предыдущей)" % (sc.get("id"), d))
            continue
        if out:                                   # в предыдущую
            prev = out[-1]
            prev["duration_sec"] = round(float(prev.get("duration_sec") or 0) + d, 2)
            prev["text"] = (str(prev.get("text", "")).rstrip() + " "
                            + str(sc.get("text", "")).lstrip()).strip()
            log.append("сцена %s (%.1f с) короче трёх секунд — склеил со сценой "
                       "%s" % (sc.get("id"), d, prev.get("id")))
        else:                                     # первая — в следующую
            nxt = scenes[1] if len(scenes) > 1 else None
            if nxt is None:
                out.append(sc)
                continue
            nxt["duration_sec"] = round(float(nxt.get("duration_sec") or 0) + d, 2)
            nxt["start_sec"] = float(sc.get("start_sec") or 0)
            nxt["text"] = (str(sc.get("text", "")).rstrip() + " "
                           + str(nxt.get("text", "")).lstrip()).strip()
            log.append("сцена %s (%.1f с) короче трёх секунд — склеил со "
                       "следующей" % (sc.get("id"), d))
    return out


# ------------------------------------------------- 3. тайминг по SRT

def _match_starts(scenes, flat, tms):
    """Настоящее начало каждой сцены по её тексту в субтитрах."""
    starts, cur = [], 0
    for sc in scenes:
        n = _norm(sc.get("text", ""))
        if not n:
            return None
        # КОРОТКИЙ ТЕКСТ СЦЕНЫ ТОЖЕ ОБЯЗАН СВЕРЯТЬСЯ (04.11, регрессия на
        # `5min-poroh-sikorsky`): сцена 16 это «Спасибо, записали» — 16 знаков,
        # а нижняя граница ключа стояла 20, цикл обрывался сразу и вся
        # пересборка объявлялась невозможной из-за ОДНОЙ короткой реплики.
        # Поэтому ключ укорачивается до 8 знаков, но поиск по всему файлу
        # (а не вперёд от курсора) разрешён только длинным ключам: короткий
        # легко совпадёт не там.
        pos = -1
        _tried = set()
        for ln in (len(n), 120, 80, 40, 25, 12, 8):
            ln = min(ln, len(n))
            if ln < 6 or ln in _tried:
                continue
            _tried.add(ln)
            key = n[:ln]
            pos = flat.find(key, cur)
            if pos < 0 and ln >= 25:
                pos = flat.find(key)
            if pos >= 0:
                break
        if pos < 0:
            return None
        starts.append(tms[pos])
        cur = pos + 1
    for i in range(1, len(starts)):
        if starts[i] < starts[i - 1]:
            return None               # порядок сцен не совпал с SRT — не лезем
    return starts


def _cut(a, b, cs, ends):
    """Отрезок (a, b) → куски по CUT_TARGET с границами по предложениям."""
    bounds = [t for t in ends if a + MIN_CHUNK <= t <= b - MIN_CHUNK]
    pts, t = [a], a
    while b - t > CUT_MAX:
        want = t + CUT_TARGET
        # ХВОСТ БЕЗ ТОЧКИ ВСЁ РАВНО РЕЖЕМ (04.11, замер на `5min-pribaltika`):
        # когда до конца отрезка не осталось ни одной границы предложения,
        # прежний код выходил из цикла и оставлял последнюю сцену на 25 с —
        # вдвое выше нормы 15. Теперь режем ровно по времени.
        near = [x for x in bounds if x > t + MIN_CHUNK]
        pick = min(near, key=lambda x: abs(x - want)) if near else want
        if pick - t > CUT_MAX:        # длинная реплика без точки — режем ровно
            pick = want
        pts.append(pick)
        t = pick
    pts.append(b)
    out = []
    for i in range(len(pts) - 1):
        s, e = pts[i], pts[i + 1]
        txt = " ".join(t for _a, _b, t in cs if s - 0.05 <= _a < e - 0.05)
        out.append((s, e, txt))
    return out


def realign(scenes, srt, log):
    """Пересобрать тайминг по SRT и разрезать непокрытые отрезки.

    Возвращает новый список сцен либо None, если сверка не удалась (тогда
    ничего не меняем — отказ приёмки честнее выдуманных цифр).
    """
    cs = cues(srt)
    if not cs:
        return None
    flat, tms = _flat(cs)
    if not flat:
        return None
    starts = _match_starts(scenes, flat, tms)
    if starts is None:
        log.append("тайминг по SRT пересобрать не удалось: текст сцен не "
                   "сверяется с субтитрами — чинить руками")
        return None
    end = cs[-1][1]
    ends = _sentence_ends(cs)
    out = []
    for i, sc in enumerate(scenes):
        a = starts[i]
        b = starts[i + 1] if i + 1 < len(starts) else end
        if b - a <= 0.2:
            # ДВЕ СЦЕНЫ НА ОДНОМ ТЕКСТЕ: по SRT у второй нет своего времени.
            # Молча выбрасывать нельзя — номера сцен поедут, а вкладка не
            # поймёт, почему их стало меньше.
            log.append("сцена %s по SRT не имеет своего времени (её текст "
                       "совпал с предыдущей) — убрал" % sc.get("id"))
            continue
        chunks = _cut(a, b, cs, ends) if b - a > CUT_MAX else [(a, b, None)]
        for j, (s, e, txt) in enumerate(chunks):
            new = dict(sc)
            new["start_sec"] = round(s, 2)
            new["duration_sec"] = round(e - s, 2)
            if txt is not None:
                new["text"] = txt
            if j:
                new["source"] = "press_photo"
                new["source_query"] = ""
                new["visual_prompt"] = ""
                new["overlays"] = []
            out.append(new)
        if len(chunks) > 1:
            log.append("сцена %s заявлена на %.1f с, а её текст по SRT занимает "
                       "%.1f с — разрезал на %d сцен по границам предложений "
                       "(первая оставила свой запрос, остальным нужен запрос)"
                       % (sc.get("id"), float(sc.get("duration_sec") or 0),
                          b - a, len(chunks)))
    return out


# ------------------------------------------------- 4. перегруженная папка

def fix_folder_overload(scenes, log, limit=2):
    """Папка медиатеки больше чем на `limit` сценах — лишние снимаем с папки."""
    seen = {}
    for sc in scenes:
        if str(sc.get("source", "")).strip() != "local_library":
            continue
        tag = str(sc.get("source_query", "")).replace("\\", "/").strip("/")
        if not tag:
            continue
        head = tag
        if os.path.splitext(tag)[1].lower() in PHOTO_EXT + VIDEO_EXT:
            head = os.path.dirname(tag)
        seen.setdefault(head, []).append(sc)
    for head, group in sorted(seen.items()):
        if len(group) <= limit:
            continue
        for sc in group[limit:]:
            sc["source"] = "press_photo"
            sc["source_query"] = ""
            sc["visual_prompt"] = ""
        log.append("папка «%s» стояла на %d сценах (норма %d) — снял с неё "
                   "сцены %s, им нужен запрос"
                   % (head, len(group), limit,
                      ", ".join(str(s.get("id")) for s in group[limit:])))


# ---------------------------------------------------------------- вход

def need_realign(scenes, srt):
    """Пересобирать тайминг или файл агента и так в порядке.

    ПОВОД РОВНО ОДИН: плотность текста выше 35 знаков в секунду, то есть в
    сцену свален остаток скрипта. Такую сцену нельзя оставить — её текст
    занимает в озвучке в разы больше заявленного, и дальше разъезжается весь
    монтаж.

    ПОЧЕМУ НЕТ ВТОРОГО ПОВОДА — ЗАМЕР 04.11, ПЕРВАЯ ЖЕ РЕГРЕССИЯ. Сначала
    пересборка включалась ещё и по расхождению заявленного начала сцены с её
    местом в SRT больше 5 секунд. Прогон по 28 файлам агента: СЕМЬ файлов,
    которые приёмка пропускала чисто, после такой пересборки отказывались
    (`5min-garantii`, `5min-sibiga`, `planeta-gaz`, `planeta-kuleba`,
    `planeta-lavrov`, `planeta-npz-udary`, `planeta-sibiga`) — сцены резались
    и теряли запросы на ровном месте. Ровно то, о чём его правило: «после
    каждого улучшения начинается ухудшение». Порог убран, остался один повод,
    на котором файл и так не принимается.
    """
    for sc in scenes:
        d = float(sc.get("duration_sec") or 0)
        t = str(sc.get("text", "")).strip()
        if d > 0 and t and len(t) / d > DENSITY_MAX:
            return True
    return False


def autofix(scenes, srt, lib):
    """Починить всё механическое. Возвращает (сцены, журнал правок)."""
    log = []
    scenes = [dict(s) for s in scenes]
    # ПОРЯДОК ВАЖЕН И ВЫБРАН ЗАМЕРОМ (04.11). Склейка коротких сцен идёт
    # ПЕРВОЙ, и только если после неё плотность текста всё ещё выше нормы —
    # пересобирается тайминг по SRT. На `planeta-pomosch` склейка одна закрыла
    # и короткие сцены, и плотность: файл принимался полностью, без единого
    # пустого запроса. При обратном порядке пересборка резала его на сцены и
    # оставляла вкладке десять запросов — работающее портилось сильной правкой
    # там, где хватало слабой.
    scenes = fix_short(scenes, log)
    if srt and need_realign(scenes, srt):
        new = realign(scenes, srt, log)
        if new:
            scenes = new
            scenes = fix_short(scenes, log)
    fix_folder_overload(scenes, log)
    fix_missing_file(scenes, lib, log)
    # НОМЕРА И ТАЙМИНГ ПОДРЯД: номер сцены — это имя файла кадра
    # (`images/scene_NNN`), поэтому после склейки и нарезки он обязан идти
    # без дыр, иначе манифест и дашборд разъедутся.
    t = 0.0
    for i, sc in enumerate(scenes, 1):
        sc["id"] = i
        sc["start_sec"] = round(t, 2)
        t += float(sc.get("duration_sec") or 0)
    return scenes, log


def need_query(scenes):
    """Сцены, которым автопочинка оставила пустой запрос."""
    return [sc for sc in scenes
            if not str(sc.get("source_query", "")).strip()
            and not str(sc.get("source", "")).startswith("card:")]
