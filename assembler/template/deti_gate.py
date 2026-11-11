# -*- coding: utf-8 -*-
"""ГЕЙТ «ДЕТИ И ДЕТСКИЕ ПЛОЩАДКИ» — НИ ОДИН ТАКОЙ КАДР НЕ ДОХОДИТ ДО ДАШБОРДА.

Повод (10.11, его слово по сданному ролику «ЗЕ готов в Антарктиде»):
«У нас есть строжайший запрет: ни дети, ни детские площадки в кадр не
попадают» и следом, когда вкладка стала объяснять, откуда взялся кадр:
«Да мне пофиг, где она была, в базе или не в базе, скачана, не скачана —
НЕ ДОЛЖНО БЫТЬ НА ДАШБОРДЕ. Она не должна туда попадать».

Почему мин в запросах не хватило. `query_lint` чистит ЗАПРОС («школ», «дет»,
«семь»), но кадр приходит не только из запроса: его даёт база кадров
(`local_library`), вложение телеграма, ручная подмена, карточка арсенала.
В тот раз папка базы называлась ДВОР-МНОГОЭТАЖЕК-КИЕВА, запрос был чистый,
а все одиннадцать файлов в папке оказались детскими площадками.
Поэтому гейт смотрит НЕ запрос, а САМ КАДР, и стоит перед дашбордом.

Четыре команды:

    python3 deti_gate.py listy  <проект>            # собрать листы на просмотр
    python3 deti_gate.py verdikt <проект> --bad 5,12 [--vse-chisto]
    python3 deti_gate.py check  <проект>            # гейт: 0 — чисто, 1 — нет
    python3 deti_gate.py centr  <проект>            # кому нужен второй проход

ЛИСТОВ ДВА ВИДА (с 11.11): общие `deti/lists/list_*.jpg` и ОТДЕЛЬНЫЕ листы
центра `deti/centr/centr_*.jpg` — вертикали и узкие кадры, которые в ролике
стоят по центру с размытыми полями. На общем листе такая сцена ужимается в
полоску 98 px, и фигура в ней пропадает; на листе центра она крупнее в 4,2
раза. Смотрящему показывать ОБА вида, иначе `check` вердикт не примет.

Кто смотрит листы: СУБАГЕНТ вкладки (дёшево, свой контекст, картинки в
основной поток не копятся) или внешний агент. На машине пользователя не
считается ничего, кроме склейки готовых миниатюр и промера кадров на
заливку полей (~5 с на ролик из 70 сцен, замер 11.11).

Гейт зовут `selfcheck.py` (не отдаёт дашборд) и `cloud/ship.sh` (не собирает
ролик). Обход — только `VIDEORYAD_NO_DETI=1` и только по его прямому слову
про этот ролик.
"""
import argparse
import glob
import json
import os
import sys
import time

MARKER = "deti"
VERDICT = os.path.join(MARKER, "verdict.json")
LISTS = os.path.join(MARKER, "lists")
# Сколько миниатюр кладём на один лист: 24 хватает, чтобы площадка была видна
# глазом, и держит число картинок у смотрящего в рамках правила 23.10
# (потолок 25 изображений на субагента).
PER_SHEET = 24
COLS = 6
CELL_W, CELL_H = 320, 200

# ── ВЕРТИКАЛЬ С РАЗМЫТЫМИ ПОЛЯМИ — ПЕРВЫЙ ЗАФИКСИРОВАННЫЙ ПРОМАХ ГЕЙТА (11.11)
# Сцена 58 сданного ролика: вертикальный кадр поставлен по центру, поля —
# размытая копия его же. У скамейки стоит девочка: мелко, но различимо.
# `deti_gate` промолчал, и субагент по четырём листам тоже ответил «чисто».
# Причина чисто механическая: ячейка общего листа 320x200, и вертикаль
# 800x1422 ложится в неё полоской 98x174 — фигура ростом в 1/8 кадра
# становится 22 px и съедается миниатюрой.
# КЛАСС ШИРОКИЙ: с 05.11 порог вложений телеграма снижен до 800 px по длинной
# стороне, такие кадры ставятся родным размером по центру с заливкой полей —
# значит их много. Замер 11.11 по 23 сданным роликам: 4-26 таких сцен на
# ролик, медиана 11.
# ЛЕЧЕНИЕ: такие сцены идут ВТОРЫМ, ОТДЕЛЬНЫМ проходом — лист крупных кропов
# ТОЛЬКО настоящей части кадра (ячейка 740 вместо 320: фигура крупнее в 4,2
# раза по стороне), и без этого прохода `check` вердикт не принимает.
CENTR_DIR = os.path.join(MARKER, "centr")
PER_CENTR = 4            # 4 на лист: 2x2 по 740 = 1480 px, смотрящий не ужимает
CENTR_COLS = 2
CENTR_CELL = 740
# Пороги СБОРЩИКА — должны совпадать с `build_clips_1080.py`, иначе гейт
# смотрит не тот класс кадров: рамка 1920x1080, портрет при пропорции < 1,15,
# заливка полей при необходимом апскейле больше 1,35×.
FRAME_W, FRAME_H = 1920, 1080
PORTRAIT_AR = 1.15
MAX_COVER_UP = 1.35
# Распознавание УЖЕ ЗАПЕЧЁННОЙ заливки (файл приехал 16:9, а настоящая часть
# внутри): резкость по колонкам + сверка полей с размытой копией центра.
PROBE_W, PROBE_H = 256, 144
BAND_MAX = 0.90          # полоса резкости шире — обычный кадр
MARGIN_MIN = 0.04        # поле уже — не заливка
SYM_MAX = 0.04           # поля заливки симметричны по устройству
PAD_RATIO = 0.40         # резкость полей к резкости полосы
PAD_CORR = 0.62          # сходство поля с размытой копией центра

# ВТОРОЙ ПРОХОД ТРЕБУЕТСЯ С 11.11, А НЕ ЗАДНИМ ЧИСЛОМ — тем же правилом, что и
# сам гейт (10.11): ролики, уже идущие по трубам, ломать запрещено.
CENTR_SINCE = 1794406000.0   # 2026-11-11 14:06 (момент установки второго прохода)

# Копия вердикта ВНЕ папки забора (11.11). `get.sh` чистит `<проект>-cloud`
# целиком — вместе с каталогом `deti/`, — и `faza.sh sdacha` на СВОЁМ ЖЕ
# готовом ролике печатал «ПРОВЕРКА ДЕТИ НЕ ПРОЙДЕНА — СБОРКУ ДЕРЖУ». Два
# случая за смену 11.11 у разных вкладок: доставка проходила целиком, но в
# логе висел красный ОТКАЗ, и по нему легко решить, что ролик не уехал.
STATE_DIR = os.path.expanduser(
    os.environ.get("VIDEORYAD_DETI_STATE", "~/.cache/videoryad/deti"))


def _project_dir(p):
    return os.path.abspath(os.path.expanduser(p))


def _state_verdict(pdir):
    """Путь к копии вердикта в каталоге состояния. Ключ — имя ролика БЕЗ
    суффикса `-cloud`: забор и рабочая папка — один и тот же ролик."""
    name = os.path.basename(pdir.rstrip("/")) or "bez-imeni"
    if name.endswith("-cloud"):
        name = name[:-len("-cloud")]
    return os.path.join(STATE_DIR, name + ".json")


def _scenes_file(pdir):
    """Рабочий scenes.json проекта (не сырой файл агента `codex*.json`)."""
    cands = [f for f in glob.glob(os.path.join(pdir, "*.scenes.json"))
             if not os.path.basename(f).startswith(("codex", "lib_", "raw"))]
    if not cands:
        cands = glob.glob(os.path.join(pdir, "*.scenes.json"))
    return cands[0] if cands else None


def _scene_ids(pdir):
    sf = _scenes_file(pdir)
    if not sf:
        return []
    try:
        d = json.load(open(sf, encoding="utf-8"))
    except Exception:
        return []
    sc = d.get("scenes", d) if isinstance(d, dict) else d
    return [int(s["id"]) for s in sc if "id" in s]


def _frame_for(pdir, sid):
    """Картинка сцены для листа: сперва готовая миниатюра (её уже посчитали —
    облако или дашборд), потом сам кадр. Видео берём ТОЛЬКО если от него уже
    есть кадр-миниатюра: декодировать mp4 ради листа значит считать на его
    машине, а это запрещено (23.10)."""
    images = os.path.join(pdir, "images")
    for p in (os.path.join(images, ".rev", f"{sid:03d}.jpg"),
              os.path.join(pdir, "thumbs", f"{sid:03d}.jpg")):
        if os.path.exists(p):
            return p
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(images, f"scene_{sid:03d}{ext}")
        if os.path.exists(p):
            return p
    p = os.path.join(images, f"scene_{sid:03d}.mp4.revframe.jpg")
    if os.path.exists(p):
        return p
    # ВИДЕО-СЦЕНА БЕЗ ГОТОВОЙ МИНИАТЮРЫ. Площадка может быть и в клипе, так
    # что пропускать такие сцены нельзя — дыра в гейте. Снимаем ОДИН кадр
    # (0,1-0,3 с на сцену, десяток сцен на ролик) и кладём рядом, чтобы
    # второй раз не считать. Это единственный счёт этого инструмента на
    # машине пользователя; всё остальное берётся готовым.
    src = os.path.join(images, f"scene_{sid:03d}.mp4")
    if os.path.exists(src):
        import subprocess
        ff = os.environ.get("FFMPEG_BIN", "ffmpeg")
        try:
            subprocess.run([ff, "-nostdin", "-v", "error", "-ss", "1", "-i", src,
                            "-frames:v", "1", "-vf", "scale=400:-1", "-threads", "1",
                            "-y", p], capture_output=True, timeout=25)
        except Exception:
            return None
        if os.path.exists(p):
            return p
    return None


def _font(size):
    """Шрифт С КИРИЛЛИЦЕЙ для подписей на листах (11.11). Встроенный шрифт PIL
    рисует русские буквы квадратиками — подпись «сцена 58 · вертикаль» на листе
    читалась как ряд плашек, и смотрящий не мог назвать номер."""
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _centr_src(pdir, sid):
    """Файл для КРУПНОГО кропа: сперва сам кадр в родном размере, и только
    если его нет — миниатюра. На общем листе хватает миниатюры, здесь нет:
    смысл прохода в том, чтобы фигура была видна (11.11)."""
    images = os.path.join(pdir, "images")
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(images, f"scene_{sid:03d}{ext}")
        if os.path.exists(p):
            return p
    return _frame_for(pdir, sid)


def _by_aspect(w, h):
    """Сборщик поставит кадр родным размером с размытыми полями? Условие один
    в один с `build_clips_1080.build_image_clip` (portrait or narrow) — иначе
    гейт смотрел бы не тот класс кадров."""
    if not w or not h:
        return None
    if (w / float(h)) < PORTRAIT_AR:
        return "вертикаль %dx%d" % (w, h)
    if max(FRAME_W / float(w), FRAME_H / float(h)) > MAX_COVER_UP:
        return "узкий кадр %dx%d" % (w, h)
    return None


def _corr(u, v):
    import math
    n = len(u)
    if n < 64:
        return 0.0
    mu = sum(u) / float(n); mv = sum(v) / float(n)
    su = math.sqrt(sum((x - mu) ** 2 for x in u) / n)
    sv = math.sqrt(sum((x - mv) ** 2 for x in v) / n)
    if su < 1e-6 or sv < 1e-6:
        return 0.0
    return sum((u[i] - mu) * (v[i] - mv) for i in range(n)) / (n * su * sv)


def _baked_pads(path):
    """Заливка УЖЕ запечена в файл (кадр приехал 16:9, настоящая часть внутри).

    Вернуть (x0, x1) долями ширины или None. Признака ДВА, и нужны оба:
      1) резкость по колонкам падает ступенькой, полоса симметрична и уже
         кадра — поля размыты;
      2) поле СОВПАДАЕТ с размытой копией центра, растянутой на весь кадр, —
         именно так его и рисует сборщик.
    Замер 11.11 на 978 широких горизонтальных кадрах сданных роликов: по
    одному первому признаку ложных 406 (42%), с обоими — 8 (0,8%). Цена
    ложного — лишняя плитка на листе, а не отказ, поэтому порог такой.
    Счёт на машине: ~50 мс на кадр, ~3 с на ролик (остальное отсеивается
    дешёвыми проверками до сверки)."""
    from PIL import Image, ImageFilter
    try:
        with Image.open(path) as _im:
            orig = _im.convert("L")
            W0, H0 = orig.size
    except Exception:
        return None
    sm = orig.resize((PROBE_W, PROBE_H), Image.BILINEAR)
    a = sm.load()
    b = sm.filter(ImageFilter.GaussianBlur(2.0)).load()
    e = [sum(abs(a[x, y] - b[x, y]) for y in range(PROBE_H)) / float(PROBE_H)
         for x in range(PROBE_W)]
    c0, c1 = int(PROBE_W * 0.42), int(PROBE_W * 0.58)
    mid = sorted(e[c0:c1]); cen = mid[len(mid) // 2]
    if cen <= 1.0:           # кадр ровный целиком — ступеньки нет
        return None
    t = cen * 0.42
    x0 = c0
    while x0 > 0 and e[x0 - 1] >= t:
        x0 -= 1
    x1 = c1
    while x1 < PROBE_W and e[x1] >= t:
        x1 += 1
    band = (x1 - x0) / float(PROBE_W)
    ml, mr = x0 / float(PROBE_W), (PROBE_W - x1) / float(PROBE_W)
    if band > BAND_MAX or min(ml, mr) < MARGIN_MIN or abs(ml - mr) > SYM_MAX:
        return None
    pads = e[:x0] + e[x1:]
    if not pads or (sum(pads) / len(pads) / cen) > PAD_RATIO:
        return None
    bx0 = int(x0 / float(PROBE_W) * W0)
    bx1 = max(int(x1 / float(PROBE_W) * W0), bx0 + 8)
    core = orig.crop((bx0, 0, bx1, H0))
    k = max(PROBE_W / float(core.size[0]), PROBE_H / float(core.size[1]))
    cw, ch = max(PROBE_W, int(core.size[0] * k)), max(PROBE_H, int(core.size[1] * k))
    ox, oy = (cw - PROBE_W) // 2, (ch - PROBE_H) // 2
    exp = core.resize((cw, ch), Image.BILINEAR).crop(
        (ox, oy, ox + PROBE_W, oy + PROBE_H)).filter(ImageFilter.GaussianBlur(3.2))
    act = sm.filter(ImageFilter.GaussianBlur(3.2))
    ea, aa = exp.load(), act.load()
    u, v = [], []
    for x in list(range(0, x0)) + list(range(x1, PROBE_W)):
        for y in range(0, PROBE_H, 2):
            u.append(ea[x, y]); v.append(aa[x, y])
    if _corr(u, v) < PAD_CORR:
        return None
    return (x0 / float(PROBE_W), x1 / float(PROBE_W))


def _video_wh(src):
    """Родной размер клипа. Нужен потому, что миниатюра видеосцены кладётся
    шириной 400 px, и ПО НЕЙ любой клип выглядит «узким»: на первом же прогоне
    11.11 это дало 12 ложных сцен из 33. `ffprobe` дешевле снятия кадра,
    который здесь и так делается."""
    import subprocess
    fp = os.environ.get("FFPROBE_BIN", "ffprobe")
    try:
        r = subprocess.run([fp, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height",
                            "-of", "csv=p=0:s=x", src],
                           capture_output=True, timeout=15)
        a, b = r.stdout.decode().strip().split("\n")[0].split("x")[:2]
        return int(a), int(b)
    except Exception:
        return 0, 0


def _centr_task(pdir, sid):
    """(путь, коробка кропа, причина) для сцены, которой нужен ОТДЕЛЬНЫЙ
    крупный кроп, иначе None. Коробка — в координатах файла."""
    path = _centr_src(pdir, sid)
    if not path:
        return None
    from PIL import Image
    try:
        with Image.open(path) as im:
            fw, fh = im.size      # размер ФАЙЛА, в нём же считается коробка
    except Exception:
        return None
    w, h = fw, fh                 # размер, по которому решает СБОРЩИК
    mp4 = os.path.join(pdir, "images", f"scene_{sid:03d}.mp4")
    if os.path.exists(mp4):
        vw, vh = _video_wh(mp4)
        if vw and vh:
            w, h = vw, vh
    why = _by_aspect(w, h)
    if why:
        # сам файл и есть «настоящая часть» — поля дорисует сборщик
        return path, (0, 0, fw, fh), why + ", поля дорисует сборщик"
    pads = _baked_pads(path)
    if pads:
        x0, x1 = int(pads[0] * fw), int(pads[1] * fw)
        return path, (x0, 0, max(x1, x0 + 8), fh), \
            "размытые поля уже в файле, настоящая часть %d%%" % \
            round((pads[1] - pads[0]) * 100)
    return None


def _centr_ids(pdir, ids):
    """Номера сцен, которым нужен второй проход. Считается ЗАНОВО на каждом
    вызове: кадр могли заменить после листов."""
    out = []
    for sid in ids:
        try:
            if _centr_task(pdir, sid):
                out.append(sid)
        except Exception:
            continue
    return out


def cmd_listy(args):
    from PIL import Image, ImageDraw
    pdir = _project_dir(args.project)
    ids = _scene_ids(pdir)
    if not ids:
        print("deti_gate: не нашёл scenes.json — нечего проверять", file=sys.stderr)
        return 2
    out_dir = os.path.join(pdir, LISTS)
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.jpg")):
        os.remove(old)

    pairs = [(sid, _frame_for(pdir, sid)) for sid in ids]
    have = [(s, f) for s, f in pairs if f]
    missing = [s for s, f in pairs if not f]

    sheets = []
    for start in range(0, len(have), PER_SHEET):
        chunk = have[start:start + PER_SHEET]
        rows = (len(chunk) + COLS - 1) // COLS
        sheet = Image.new("RGB", (CELL_W * COLS, CELL_H * rows), (18, 18, 18))
        d = ImageDraw.Draw(sheet)
        for i, (sid, path) in enumerate(chunk):
            try:
                im = Image.open(path)
                im.thumbnail((CELL_W - 8, CELL_H - 26))
            except Exception:
                continue
            x = (i % COLS) * CELL_W + 4
            y = (i // COLS) * CELL_H + 22
            sheet.paste(im, (x, y))
            d.text((x, y - 18), f"сцена {sid}", fill=(255, 225, 70),
                   font=_font(15))
        name = os.path.join(out_dir, f"list_{len(sheets) + 1:02d}.jpg")
        sheet.save(name, quality=80)
        sheets.append(name)

    # ВТОРОЙ ПРОХОД — КРУПНЫЕ КРОПЫ НАСТОЯЩЕЙ ЧАСТИ КАДРА (11.11). На общем
    # листе вертикаль ужимается в полоску 98x174, и фигура у скамейки
    # пропадает — именно так гейт промолчал на сцене 58. Здесь та же сцена
    # занимает ячейку 740: по стороне крупнее в 4,2 раза.
    centr, c_sheets = [], []
    tasks = []
    for sid, _ in have:
        try:
            t = _centr_task(pdir, sid)
        except Exception:
            t = None
        if t:
            tasks.append((sid, t))
            centr.append(sid)
    c_dir = os.path.join(pdir, CENTR_DIR)
    if tasks:
        os.makedirs(c_dir, exist_ok=True)
        for old in glob.glob(os.path.join(c_dir, "*.jpg")):
            os.remove(old)
        for start in range(0, len(tasks), PER_CENTR):
            chunk = tasks[start:start + PER_CENTR]
            rows = (len(chunk) + CENTR_COLS - 1) // CENTR_COLS
            sheet = Image.new("RGB", (CENTR_CELL * CENTR_COLS,
                                      (CENTR_CELL + 26) * rows), (18, 18, 18))
            d = ImageDraw.Draw(sheet)
            for i, (sid, (path, box, why)) in enumerate(chunk):
                try:
                    im = Image.open(path).crop(box)
                    # 1:1 и ни пикселя вверх: апскейл информации не добавляет,
                    # а мылом прячет мелкую фигуру
                    im.thumbnail((CENTR_CELL - 8, CENTR_CELL - 8))
                except Exception:
                    continue
                x = (i % CENTR_COLS) * CENTR_CELL + 4
                y = (i // CENTR_COLS) * (CENTR_CELL + 26) + 22
                sheet.paste(im, (x, y))
                d.text((x, y - 19), f"сцена {sid} · {why}", fill=(255, 225, 70),
                       font=_font(17))
            name = os.path.join(c_dir, f"centr_{len(c_sheets) + 1:02d}.jpg")
            sheet.save(name, quality=85)
            c_sheets.append(name)

    meta = {"ids": ids, "sheets": sheets, "missing": missing, "ts": time.time(),
            "centr": centr, "centr_sheets": c_sheets}
    json.dump(meta, open(os.path.join(pdir, MARKER, "lists.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"листов: {len(sheets)} (сцен {len(have)} из {len(ids)})")
    for s in sheets:
        print("  " + s)
    if missing:
        print(f"без картинки пока: {len(missing)} сцен — {missing[:12]}")
    print("\nЧТО СПРОСИТЬ У СМОТРЯЩЕГО (субагент, не основной поток):")
    print("  «Назови номера сцен, где есть ребёнок, подросток, школьник ИЛИ")
    print("   детская площадка — в том числе ПУСТАЯ: горка, качели, песочница,")
    print("   школьный двор, детский сад. Даже мелко на заднем плане.»")
    if c_sheets:
        print(f"\nЛИСТЫ ЦЕНТРА — ОТДЕЛЬНЫЙ ПРОХОД, ПОКАЗАТЬ ОБЯЗАТЕЛЬНО "
              f"({len(centr)} сцен):")
        for s in c_sheets:
            print("  " + s)
        print("  Это вертикали и узкие кадры: в ролике они стоят по центру, "
              "поля — размытая\n  копия. На общем листе такая сцена — полоска "
              "в 98 px, фигуру там не видно.")
        print(f"  Сцены второго прохода: {centr}")
    else:
        print("\nвертикалей и кадров с размытыми полями нет — второй проход не нужен")
    print("Потом: python3 deti_gate.py verdikt <проект> --bad 5,12  (или --vse-chisto)")
    return 0


def cmd_centr(args):
    """Диагностика: какие сцены требуют второго прохода и почему."""
    pdir = _project_dir(args.project)
    ids = _scene_ids(pdir)
    n = 0
    for sid in ids:
        try:
            t = _centr_task(pdir, sid)
        except Exception as e:
            print("  сцена %d: не смог посмотреть (%s)" % (sid, e))
            continue
        if t:
            n += 1
            print("  сцена %-3d %s  [%s]" % (sid, t[2], os.path.basename(t[0])))
    print("второй проход нужен %d сценам из %d" % (n, len(ids)))
    return 0


def cmd_verdikt(args):
    pdir = _project_dir(args.project)
    ids = _scene_ids(pdir)
    bad = []
    if args.bad:
        for part in str(args.bad).replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                bad.append(int(part))
    if not args.vse_chisto and not bad:
        print("deti_gate: назови --bad <номера> или подтверди --vse-chisto",
              file=sys.stderr)
        return 2
    os.makedirs(os.path.join(pdir, MARKER), exist_ok=True)
    # Какие сцены ушли во ВТОРОЙ проход — берём из листов, а не со слов
    # смотрящего: вердикт обязан доказывать, что крупные кропы ему показали.
    centr = []
    try:
        _lm = json.load(open(os.path.join(pdir, MARKER, "lists.json"),
                             encoding="utf-8"))
        centr = [int(x) for x in _lm.get("centr", [])]
    except Exception:
        pass
    v = {"checked": ids, "bad": sorted(set(bad)), "ts": time.time(),
         "kto": args.kto or "субагент вкладки", "centr": sorted(set(centr))}
    json.dump(v, open(os.path.join(pdir, VERDICT), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # КОПИЯ ВНЕ ПАПКИ ЗАБОРА (11.11): `get.sh` чистит `<проект>-cloud`
    # целиком, и вердикт пропадал ровно перед сдачей.
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        json.dump(dict(v, pdir=pdir), open(_state_verdict(pdir), "w",
                                           encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception as e:
        print("  (копия вердикта в каталог состояния не легла: %s)" % e)
    if bad:
        print(f"записано: брак в сценах {v['bad']} — замени кадры и прогони листы заново")
    else:
        print(f"записано: чисто, просмотрено сцен {len(ids)}"
              + (f", из них вторым проходом {len(centr)}" if centr else ""))
    return 0


# ГЕЙТ ДЕЙСТВУЕТ СО СЛЕДУЮЩЕГО РОЛИКА, А НЕ ЗАДНИМ ЧИСЛОМ (10.11, его прямое
# слово через полчаса после установки: «они ничего не должны переделывать,
# это просто на следующий ролик… вот сборка идёт — какая будет, такая пускай
# приезжает»). Проект, начатый ДО этой отметки, гейт пропускает с одной
# строкой предупреждения: ломать идущие сборки запрещено.
GATE_SINCE = 1794320000.0   # 2026-11-10 14:13 (момент установки)


def _started_before_gate(pdir, since=None):
    """Когда ролик НАЧАТ. По `scenes.json` судить нельзя: его переписывает
    каждый круг правок, и идущий со вчера ролик выглядел бы новым. Берём то,
    что кладётся один раз и не меняется, — озвучку и `.srt`; если их нет,
    саму папку."""
    stamps = []
    for pat in ("narration.*", "*.srt", "*.mp3"):
        for f in glob.glob(os.path.join(pdir, pat)):
            try:
                stamps.append(os.path.getmtime(f))
            except OSError:
                pass
    if not stamps:
        try:
            stamps.append(os.path.getmtime(pdir))
        except OSError:
            return False
    return min(stamps) < (GATE_SINCE if since is None else since)


def cmd_check(args):
    """ГЕЙТ. Код 0 — можно отдавать дашборд и собирать; 1 — нельзя."""
    pdir = _project_dir(args.project)
    if os.environ.get("VIDEORYAD_NO_DETI") == "1":
        print("deti_gate: ОБХОД VIDEORYAD_NO_DETI=1 — только по его прямому слову")
        return 0
    if _started_before_gate(pdir) and not os.path.exists(os.path.join(pdir, VERDICT)):
        print("ДЕТИ: ролик начат до установки гейта (10.11 14:20) — пропускаю, "
              "проверка обязательна начиная со СЛЕДУЮЩЕГО ролика")
        return 0
    ids = _scene_ids(pdir)
    vp = os.path.join(pdir, VERDICT)
    otkuda = ""
    if not os.path.exists(vp):
        # ВЕРДИКТ МОГЛА УНЕСТИ ЧИСТКА ЗАБОРА (11.11): `get.sh` сносит
        # содержимое `<проект>-cloud` целиком, вместе с `deti/`. Два случая
        # за смену: `faza.sh sdacha` на СВОЁМ ЖЕ готовом ролике печатал
        # «ПРОВЕРКА ДЕТИ НЕ ПРОЙДЕНА — СБОРКУ ДЕРЖУ», хотя проверка была
        # сделана час назад. Поэтому ищем копию в каталоге состояния.
        sp = _state_verdict(pdir)
        if os.path.exists(sp):
            vp, otkuda = sp, " (вердикт из каталога состояния: папку забора чистил get.sh)"
        else:
            print("ДЕТИ: проверка не делалась вовсе.", file=sys.stderr)
            print("  python3 ~/.claude/skills/news-video/template/deti_gate.py listy "
                  + pdir, file=sys.stderr)
            return 1
    try:
        v = json.load(open(vp, encoding="utf-8"))
    except Exception:
        print("ДЕТИ: вердикт нечитаем — прогони проверку заново", file=sys.stderr)
        return 1
    bad = [int(x) for x in v.get("bad", [])]
    if bad:
        print(f"ДЕТИ: в сценах {bad} ребёнок или детская площадка — заменить кадры",
              file=sys.stderr)
        return 1
    checked = set(int(x) for x in v.get("checked", []))
    new = [i for i in ids if i not in checked]
    if new:
        print(f"ДЕТИ: сцены {new[:12]} появились после проверки — прогони листы заново",
              file=sys.stderr)
        return 1
    # ВТОРОЙ ПРОХОД ПО ЦЕНТРАЛЬНОМУ КРОПУ (11.11). Считаем ЗАНОВО по тому,
    # что лежит в `images` сейчас: кадр могли заменить после листов.
    try:
        centr_now = _centr_ids(pdir, ids)
    except Exception as e:      # нет PIL — не держим ролик, но говорим вслух
        print("ДЕТИ: второй проход не посчитан (%s) — проверь вертикали глазами"
              % e, file=sys.stderr)
        centr_now = []
    seen = set(int(x) for x in v.get("centr", []))
    miss = [i for i in centr_now if i not in seen]
    if miss and not _started_before_gate(pdir, CENTR_SINCE):
        print(f"ДЕТИ: сцены {miss[:12]} — вертикаль или узкий кадр с размытыми "
              "полями.", file=sys.stderr)
        print("  В ролике они стоят по центру, на общем листе ужимаются в "
              "полоску и фигуру\n  там не видно (промах 11.11, сцена 58: "
              "девочка у скамейки).", file=sys.stderr)
        print("  Нужен ОТДЕЛЬНЫЙ проход по крупным кропам:", file=sys.stderr)
        print("  python3 ~/.claude/skills/news-video/template/deti_gate.py listy "
              + pdir, file=sys.stderr)
        print("  → показать смотрящему листы `deti/centr/centr_*.jpg` и записать "
              "вердикт заново", file=sys.stderr)
        return 1
    tail = f", вторым проходом {len(centr_now)}" if centr_now else ""
    print(f"ДЕТИ: чисто ({len(checked)} сцен просмотрено{tail}){otkuda}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("listy", help="собрать контактные листы на просмотр")
    a.add_argument("project")
    a.set_defaults(func=cmd_listy)
    b = sub.add_parser("verdikt", help="записать вердикт смотрящего")
    b.add_argument("project")
    b.add_argument("--bad", help="номера сцен с детьми/площадками через запятую")
    b.add_argument("--vse-chisto", action="store_true", dest="vse_chisto")
    b.add_argument("--kto", help="кто смотрел")
    b.set_defaults(func=cmd_verdikt)
    e = sub.add_parser("centr", help="какие сцены требуют второго прохода (11.11)")
    e.add_argument("project")
    e.set_defaults(func=cmd_centr)
    c = sub.add_parser("check", help="гейт: 0 — чисто, 1 — нельзя отдавать")
    c.add_argument("project")
    c.set_defaults(func=cmd_check)
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
