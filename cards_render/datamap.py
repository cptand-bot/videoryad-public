# -*- coding: utf-8 -*-
"""Анимированная ДАТА-КАРТА для второго сборщика (полный цикл).

Снята с чужого ролика, который пользователь дал разобрать 19.10.2026:
вертикальная карта-инфографика «АТАКА НА МОСКОВСКИЙ РЕГИОН» — сходящиеся
к одной точке траектории, тикающие счётчики, нижний график, шкала дат.
Разбор показал, что это не видеомонтаж и не motion-шаблон, а ПОКАДРОВАЯ
ОТРИСОВКА ПО ТАБЛИЦЕ ДАННЫХ. Поэтому воспроизводится кодом целиком.

Семь слоёв оригинала, все здесь:
 1. карта-подложка, неподвижная, с подписями стран и городов;
 2. шапка: эпиграф, заголовок, период справа;
 3. цель — пульсирующая красная точка с подписью;
 4. тонкие траектории — НАКАПЛИВАЮТСЯ и не стираются (главная механика:
    к концу из них набирается плотная «шерсть», это и читается как объём);
 5. широкие коридоры — агрегированные потоки со свечением, растут по ходу;
 6. событийный слой — пульс-кольца, вспышки;
 7. счётчики с ПОРАЗРЯДНЫМ перекатом + нижний график + шкала дат.

Фазы: проявление → накопление → счётчики замирают, тонкие следы гаснут,
остаются коридоры, лёгкий наплыв. Без этой третьей фазы ролик обрывается.

Оформление подчинено системе второго сборщика (style_cards): та же
виньетка с зерном, та же палитра (белый/золотой/красный/серый), те же три
шрифтовые роли, тот же подвал с источником и вотермарка. Бирюзу оригинала
НЕ берём — она ломает правило «цвета не меняются весь ролик».

ВАЖНО ПРО ЧИСЛА. Правило системы: нет настоящих чисел — не рисуем
счётчик. Тогда вместо счётчика идут СОБЫТИЯ (см. `counters=[]` и
`events_list`): карта остаётся, цифровой одометр выключается.
"""
import json, math, os, random, subprocess, sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import style_cards as sc

W, H = sc.W, sc.H
GEO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo")
SS = 2                                  # суперсэмплинг слоя следов
TRACK_COL = (206, 216, 228)             # холодный свет траекторий
_GEO_CACHE = {}

CITY_RU = {
    "Moscow": "Москва", "Kyiv": "Киев", "Kiev": "Киев", "Minsk": "Минск",
    "Warsaw": "Варшава", "Berlin": "Берлин", "Paris": "Париж",
    "London": "Лондон", "Brussels": "Брюссель", "Vienna": "Вена",
    "Prague": "Прага", "Budapest": "Будапешт", "Bucharest": "Бухарест",
    "Sofia": "София", "Belgrade": "Белград", "Ankara": "Анкара",
    "Istanbul": "Стамбул", "Stockholm": "Стокгольм", "Oslo": "Осло",
    "Helsinki": "Хельсинки", "Copenhagen": "Копенгаген", "Riga": "Рига",
    "Vilnius": "Вильнюс", "Tallinn": "Таллин", "Washington, D.C.": "Вашингтон",
    "Washington": "Вашингтон", "New York": "Нью-Йорк", "Rome": "Рим",
    "Madrid": "Мадрид", "Lisbon": "Лиссабон", "Amsterdam": "Амстердам",
    "Hamburg": "Гамбург", "Munich": "Мюнхен", "Milan": "Милан",
    "Odessa": "Одесса", "Kharkiv": "Харьков", "Lviv": "Львов",
    "Donetsk": "Донецк", "Dnipro": "Днепр", "Chisinau": "Кишинёв",
}
SHORT_RU = {
    "Китайская Народная Республика": "Китай",
    "Российская Федерация": "Россия",
    "Соединённые Штаты Америки": "США",
    "Соединенные Штаты Америки": "США",
    "Турецкая Республика Северного Кипра": "",
    "Исламская Республика Иран": "Иран",
    "Республика Корея": "Корея",
    "Босния и Герцеговина": "Босния",
    "Северная Македония": "Македония",
}
SKIP_RU = {"Фарерские острова", "Аландские острова", "Остров Мэн", "Гернси",
           "Джерси", "Лихтенштейн", "Сан-Марино", "Ватикан", "Монако",
           "Андорра", "Мальта", "Республика Косово", "Люксембург"}


# ─────────────────────────── геометрия ──────────────────────────────────────

def _region_for(target, sources, pad=6.0):
    """Окно карты по цели и источникам, с полями и правильной пропорцией."""
    lons = [target["lon"]] + [s["lon"] for s in sources]
    lats = [target["lat"]] + [s["lat"] for s in sources]
    lon0, lon1 = min(lons) - pad, max(lons) + pad
    lat0, lat1 = min(lats) - pad * .7, max(lats) + pad * .7
    klat = math.cos(math.radians((lat0 + lat1) / 2))
    # дотянуть до 16:9 в экранных единицах
    want = (W / H) / klat
    have = (lon1 - lon0) / (lat1 - lat0)
    if have < want:
        add = ((lat1 - lat0) * want - (lon1 - lon0)) / 2
        lon0, lon1 = lon0 - add, lon1 + add
    else:
        add = ((lon1 - lon0) / want - (lat1 - lat0)) / 2
        lat0, lat1 = lat0 - add, lat1 + add
    return lon0, lon1, lat0, lat1


def _projector(region):
    lon0, lon1, lat0, lat1 = region

    def proj(lon, lat):
        return ((lon - lon0) / (lon1 - lon0) * W,
                (lat1 - lat) / (lat1 - lat0) * H)
    return proj


def _bez(p0, p1, p2, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def _relief_crop(region):
    """Кусок затенённого рельефа под окно карты. Растр лежит в geo/relief.jpg
    (Natural Earth shaded relief, equirectangular на весь мир), поэтому
    вырезка — простая пропорция по долготе и широте."""
    path = os.path.join(GEO, "relief.jpg")
    if not os.path.exists(path):
        return None
    lon0, lon1, lat0, lat1 = region
    src = Image.open(path).convert("RGB")
    sw, sh = src.size
    x0 = int((lon0 + 180) / 360 * sw)
    x1 = int((lon1 + 180) / 360 * sw)
    y0 = int((90 - lat1) / 180 * sh)
    y1 = int((90 - lat0) / 180 * sh)
    x0, x1 = max(0, x0), min(sw, max(x0 + 2, x1))
    y0, y1 = max(0, y0), min(sh, max(y0 + 2, y1))
    crop = src.crop((x0, y0, x1, y1)).resize((W, H), Image.LANCZOS)
    a = np.asarray(crop, np.float32)
    # гасим и холодим: исходник светлый и коричневый, нам нужен тёмный фон
    g = a.mean(axis=2, keepdims=True)
    a = g * np.array((0.86, 0.92, 1.06), np.float32)
    return np.clip(a * 0.185 + 7, 0, 255)


# ─────────────────────────── подложка ───────────────────────────────────────

def basemap(region, labels=True, city_labels=(), relief=False, skip=()):
    """Карта-подложка на фоне фирменной виньетки с зерном. Кэшируется.

    skip — страны, которые подложка НЕ подписывает: их подпишет слой
    поверх (так делает картограмма, где у страны своя плашка со
    значением, и подложечное имя оказывалось вторым таким же)."""
    key = (tuple(round(v, 3) for v in region), labels, tuple(city_labels), relief,
           tuple(sorted(skip)))
    if key in _GEO_CACHE:
        return _GEO_CACHE[key].copy()
    proj = _projector(region)
    w, h = W * SS, H * SS
    land = Image.new("L", (w, h), 0)
    edge = Image.new("L", (w, h), 0)
    dl, de = ImageDraw.Draw(land), ImageDraw.Draw(edge)
    names = []
    data = json.load(open(os.path.join(GEO, "countries.geojson"), encoding="utf-8"))
    for f in data["features"]:
        p, geom = f["properties"], f["geometry"]
        if geom is None:
            continue
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        drawn = False
        area = 0.0
        for poly in polys:
            pts = [(x * SS, y * SS) for x, y in (proj(a, b) for a, b in poly[0])]
            if len(pts) < 3:
                continue
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            if max(xs) < -60 or min(xs) > w + 60 or max(ys) < -60 or min(ys) > h + 60:
                continue
            dl.polygon(pts, fill=255)
            de.line(pts + [pts[0]], fill=255, width=SS)
            drawn = True
            # площадь видимой части — по ней решаем, подписывать ли страну
            bx = max(0, min(w, max(xs))) - max(0, min(w, min(xs)))
            by = max(0, min(h, max(ys))) - max(0, min(h, min(ys)))
            area = max(area, bx * by / (SS * SS))
        nm = SHORT_RU.get(p.get("NAME_RU"), p.get("NAME_RU"))
        _skip = {str(x).strip().upper() for x in skip}
        if drawn and labels and nm and nm not in SKIP_RU and \
                str(nm).upper() not in _skip and \
                str(p.get("NAME_RU") or "").upper() not in _skip and \
                p.get("LABEL_X") is not None:
            x, y = proj(float(p["LABEL_X"]), float(p["LABEL_Y"]))
            if 30 < x < W - 30 and 30 < y < H - 30:
                names.append((area, nm, x, y))

    land = land.resize((W, H), Image.LANCZOS)
    edge = edge.resize((W, H), Image.LANCZOS)
    im = sc.canvas()
    a = np.asarray(im, np.float32)
    lm = (np.asarray(land, np.float32) / 255.0)[..., None]
    em = (np.asarray(edge, np.float32) / 255.0)[..., None]
    rel = _relief_crop(region) if relief else None
    if rel is not None:
        # затенённый рельеф вместо плоской заливки: карта перестаёт быть
        # школьным атласом ещё до того, как на неё лёг хоть один элемент
        a = a * (1 - lm * .92) + lm * rel * .92
    else:
        a = a * (1 - lm * .55) + lm * np.array((31, 33, 37), np.float32) * .55
    a = a * (1 - em * .55) + em * np.array((74, 80, 90), np.float32) * .55
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    if labels:
        d = ImageDraw.Draw(im, "RGBA")
        f = sc._f(sc.MONO, 19)
        taken = []          # занятые прямоугольники — против наезда подписей

        def free(bx):
            for q in taken:
                if not (bx[2] < q[0] or bx[0] > q[2] or bx[3] < q[1] or bx[1] > q[3]):
                    return False
            return True

        # сначала крупные страны: мелкие подписи — главный источник каши
        min_area = W * H * 0.012
        for area, nm, x, y in sorted(names, key=lambda a: -a[0]):
            if area < min_area:
                continue
            t = nm.upper()
            wd = sc.track_w(t, f, 2)
            bx = (x - wd / 2 - 10, y - 20, x + wd / 2 + 10, y + 12)
            if not free(bx):
                continue
            taken.append(bx)
            sc.track(d, (x - wd / 2, y - 11), t, f, (124, 130, 140), 2)
        # города — только названные в вызове, прочие на такой карте лишние
        want = {c.lower() for c in city_labels}
        if want:
            fc = sc._f(sc.MONO, 18)
            for ft in json.load(open(os.path.join(GEO, "places.geojson"),
                                     encoding="utf-8"))["features"]:
                pr = ft["properties"]
                ru = CITY_RU.get(pr.get("nameascii")) or CITY_RU.get(pr.get("name"))
                if not ru or ru.lower() not in want:
                    continue
                x, y = proj(float(pr["longitude"]), float(pr["latitude"]))
                if not (20 < x < W - 20 and 20 < y < H - 20):
                    continue
                wd = fc.getlength(ru)
                bx = (x - 4, y - 14, x + wd + 12, y + 10)
                if not free(bx):
                    continue
                taken.append(bx)
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(150, 156, 166, 235))
                d.text((x + 7, y - 9), ru, font=fc, fill=(150, 156, 166, 235))
    _GEO_CACHE[key] = im
    return im.copy()


# ─────────────────────────── служебное ──────────────────────────────────────

def _ease(x):
    return x * x * (3 - 2 * x)


def _cl(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _fmt(v):
    return f"{v:,}".replace(",", " ")


def _tint(mask, color, gain=1.0):
    m = np.clip(np.asarray(mask, np.float32) / 255.0 * gain, 0, 1)[..., None]
    return m * np.array(color, np.float32)


def _glow(mask, radius, k=.3):
    s = mask.resize((int(W * k), int(H * k)), Image.BILINEAR)
    s = s.filter(ImageFilter.GaussianBlur(radius))
    return s.resize((W, H), Image.BILINEAR)


def _rolling(img, x, y, value, prev, p, fnt, color, alpha=255):
    """Поразрядный перекат одометра, обрезанный по высоте строки.

    Разряды, которые НЕ меняются, стоят на месте; меняющиеся уезжают вверх,
    новые приходят снизу. На стоп-кадре это читается как «8 4 12» — тот же
    артефакт, что у оригинала, и он здесь намеренный: именно он выдаёт
    живой счётчик, а не нарисованное число.
    """
    s_new = _fmt(value)
    s_old = _fmt(prev).rjust(len(s_new))
    lh = int(fnt.size * 1.35)
    wsum = int(sum(fnt.getlength(c) for c in s_new)) + 8
    lay = Image.new("RGBA", (wsum, lh), (0, 0, 0, 0))
    dl = ImageDraw.Draw(lay)
    cx = 0
    for i, ch in enumerate(s_new):
        oc = s_old[i]
        if ch != oc and p < 1.0:
            dl.text((cx, lh * (1 - p) * .38), ch, font=fnt, fill=color + (int(alpha * p),))
            if oc.strip():
                dl.text((cx, -lh * p * .38), oc, font=fnt,
                        fill=color + (int(alpha * .8 * (1 - p)),))
        else:
            dl.text((cx, 0), ch, font=fnt, fill=color + (alpha,))
        cx += fnt.getlength(ch)
    img.alpha_composite(lay, (int(x), int(y)))
    return x + cx


# ─────────────────────────── главная функция ────────────────────────────────

def datamap(out_mp4, *, kick="", title="", title2="", period=("", ""),
            target=None, sources=(), series=None, counters=(),
            events_list=(), chronicle=(), anchor_labels=(), region=None,
            network=(), legend=(), relief=False, seconds=14.0, fps=25,
            source="", watermark="ДО ПРИГОВОРА", labels=True, city_labels=(),
            n_tracks=900, seed=11, keep_frames=None):
    """Собирает mp4 с анимированной дата-картой.

    target   — {"lon":.., "lat":.., "label":"КИЕВ"} — куда всё сходится.
    sources  — [{"lon":.., "lat":.., "w":1.0, "label":"ВАШИНГТОН"}, ...].
    series   — список чисел по периодам (дням/неделям). Задаёт И темп
               появления траекторий, И форму нижнего графика. Без него
               берётся ровный профиль.
    counters — до двух: [{"total":int, "unit":"ВИЗИТА", "line1":"...",
               "line2":"...", "color":"red"|"white"}]. ПУСТОЙ СПИСОК —
               счётчиков нет (когда настоящих чисел нет).
    events_list — [{"lon":..,"lat":..,"at":сек,"label":"..."}] — пульс-кольца
               с подписью: ими заменяются счётчики, когда оперируем событиями.
    network — РЕЖИМ РОСТА СЕТИ (взят из эталона про дороги Китая):
               [{"from":[lon,lat], "to":[lon,lat], "period":i, "cls":"a",
                 "w":1.0}] — каждое ребро ПРОРАСТАЕТ в свой период и
               остаётся. Не сходящиеся траектории, а растущий граф:
               расширение блока по годам, стройка, линии снабжения,
               изменение фронта. Работает вместе с `sources`/`target`
               или вместо них.
    legend — [{"cls":"a","label":"до 1996","color":(r,g,b)}] — легенда
               двойного кодирования: ЦВЕТ = класс ребра, ТОЛЩИНА = его
               вес. Рисуется в правом верхнем углу под блоком периода.
    relief — подложить затенённый рельеф вместо плоской заливки суши
               (geo/relief.jpg, если он есть).
    anchor_labels — подписи периодов (по одной на элемент series): крупная
               цифра времени в правом нижнем углу, как год в эталонном ролике
               про сеть дорог. Читается заметно лучше бегунка по шкале.
    chronicle — [{"date":"11.03.2025","text":"Джидда: помощь возобновлена",
               "at":сек}] — лента событий в левой колонке вместо счётчиков.
               Строки проявляются по очереди и притухают, освобождая внимание.
    period   — ("с 24.02.2022", "по 18.10.2026") — блок дат справа вверху.
    """
    rnd = random.Random(seed)
    nprnd = np.random.RandomState(seed)
    sources = list(sources)
    network = list(network)
    if target is None and not network:
        raise ValueError("datamap: нужен target или network")
    if not sources and not network:
        raise ValueError("datamap: нужен хотя бы один source или network")
    if region is None:
        if target and sources:
            region = _region_for(target, sources)
        else:
            # окно по всем точкам сети
            pts = [p for e in network for p in (e["from"], e["to"])]
            if target:
                pts.append([target["lon"], target["lat"]])
            fake_t = {"lon": pts[0][0], "lat": pts[0][1]}
            region = _region_for(fake_t, [{"lon": p[0], "lat": p[1]} for p in pts[1:]])
    proj = _projector(region)
    TP = proj(target["lon"], target["lat"]) if target else (0, 0)

    # фазы
    T_IN, T_ACC0 = .6 * seconds / 14, 1.1 * seconds / 14
    T_ACC1, T_HOLD = seconds * .79, seconds * .845

    ser = np.array(series, np.float32) if series else np.ones(40, np.float32)
    ser = np.maximum(ser, 0)
    if ser.sum() <= 0:
        ser = np.ones_like(ser)
    NPER = len(ser)
    wprof = ser / ser.sum()
    cum = np.cumsum(wprof)

    # ── траектории ──────────────────────────────────────────────────────────
    tracks = []
    wts = None
    if sources:
        wts = np.array([s.get("w", 1.0) for s in sources], np.float64)
        wts /= wts.sum()
    for _ in range(n_tracks if sources else 0):
        si = nprnd.choice(len(sources), p=wts)
        s = sources[si]
        p0 = proj(s["lon"] + nprnd.normal(0, 1.6), s["lat"] + nprnd.normal(0, 1.0))
        p2 = proj(target["lon"] + nprnd.normal(0, .9), target["lat"] + nprnd.normal(0, .55))
        mx, my = (p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2
        dx, dy = p2[0] - p0[0], p2[1] - p0[1]
        L = math.hypot(dx, dy) or 1
        off = nprnd.normal(0, .16) * L
        p1 = (mx - dy / L * off, my + dx / L * off)
        pts = [_bez(p0, p1, p2, k / 34) for k in range(35)]
        per = int(np.searchsorted(cum, rnd.random()))
        t0 = T_ACC0 + (per + rnd.random()) / NPER * (T_ACC1 - T_ACC0)
        tracks.append((pts, t0, rnd.uniform(.8, 1.5)))
    tracks.sort(key=lambda a: a[1])

    corr = []
    for i, s in enumerate(sources[:6] if target else []):
        p0, p2 = proj(s["lon"], s["lat"]), TP
        mx, my = (p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2
        dx, dy = p2[0] - p0[0], p2[1] - p0[1]
        L = math.hypot(dx, dy) or 1
        off = rnd.uniform(-.1, .1) * L
        p1 = (mx - dy / L * off, my + dx / L * off)
        corr.append(([_bez(p0, p1, p2, k / 60) for k in range(61)],
                     14 + 22 * s.get("w", 1.0), i * .07))

    evs = [(proj(e["lon"], e["lat"]), e.get("at", T_ACC0 + 1 + i * 1.3),
            e.get("label", ""), rnd.uniform(1.5, 2.3))
           for i, e in enumerate(events_list)]

    # ── РЕЖИМ РОСТА СЕТИ ───────────────────────────────────────────────────
    # Каждое ребро прорастает в свой период и ОСТАЁТСЯ. В отличие от
    # траекторий сеть не копит плотность: ребро либо построено, либо нет,
    # поэтому слои складываются максимумом, а не суммой.
    LEG = {l["cls"]: l for l in legend} if legend else {}
    DEF_COL = (214, 170, 92)
    edges = []
    for e in network:
        p0 = proj(*e["from"])
        p2 = proj(*e["to"])
        mx, my = (p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2
        dx, dy = p2[0] - p0[0], p2[1] - p0[1]
        L = math.hypot(dx, dy) or 1
        off = e.get("bend", 0.05) * L
        p1 = (mx - dy / L * off, my + dx / L * off)
        pts = [_bez(p0, p1, p2, k / 16) for k in range(17)]
        per = int(e.get("period", 0))
        # ИНТЕРПОЛЯЦИЯ: ребро не выскакивает целиком, а прорастает внутри
        # своего периода — кадры между опорными точками досчитываются
        t0 = T_ACC0 + (per + rnd.random() * .35) / max(1, NPER) * (T_ACC1 - T_ACC0)
        grow = (T_ACC1 - T_ACC0) / max(1, NPER) * e.get("grow", .75)
        edges.append((pts, t0, max(.12, grow), e.get("cls", "_"),
                      float(e.get("w", 1.0))))
    edges.sort(key=lambda a: a[1])
    net_layers = {c: np.zeros((H * SS, W * SS), np.uint8)
                  for c in ({e[3] for e in edges} or set())}
    net_tmp = Image.new("L", (W * SS, H * SS), 0) if edges else None

    BASE = basemap(region, labels, city_labels, relief)
    base_arr = np.asarray(BASE, np.float32)

    F_TIT = sc._f(sc.F_HEAD, 72)
    F_TIT2 = sc._f(sc.F_HEAD, 48)
    F_NUM = sc._f(sc.F_ALT, 86)
    F_UNIT = sc._f(sc.F_HEAD, 34)
    F_L1 = sc._f(sc.F_HEAD, 30)
    F_L2 = sc._f(sc.MONO, 24)
    F_PER = sc._f(sc.MONO, 24)
    F_SC = sc._f(sc.MONO, 20)
    F_EV = sc._f(sc.MONO, 21)

    # левая штора — чтобы текст читался поверх карты
    shade = np.zeros((H, W), np.float32)
    grad = np.clip(1 - np.arange(W) / 980.0, 0, 1) ** 1.35
    shade[:, :] = grad[None, :]

    persist = np.zeros((H * SS, W * SS), np.float32)
    fresh = None                   # слой «только что построенного» — белая вспышка
    tmp = Image.new("L", (W * SS, H * SS), 0)

    n_frames = int(round(seconds * fps))
    pr = subprocess.Popen(
        ["nice", "-n", "19", "ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-pix_fmt", "yuv420p", "-threads", "3", out_mp4],
        stdin=subprocess.PIPE)

    prev_vals = [0] * len(counters)
    rolls = [1.0] * len(counters)

    for fi in range(n_frames):
        t = fi / fps
        tmp.paste(0, (0, 0, W * SS, H * SS))
        dt = ImageDraw.Draw(tmp)
        heads = []
        for pts, t0, dur in tracks:
            if t < t0:
                break
            if (t - t0) / dur > 1.1:
                continue
            a, b = _cl((t - 1 / fps - t0) / dur), _cl((t - t0) / dur)
            if b <= a:
                continue
            i0, i1 = int(a * 34), min(34, int(b * 34) + 1)
            seg = [(p[0] * SS, p[1] * SS) for p in pts[i0:i1 + 1]]
            if len(seg) > 1:
                dt.line(seg, fill=255, width=1)
            if b < 1.0:
                heads.append(pts[min(34, int(b * 34))])
        fresh_np = np.asarray(tmp, np.float32)
        if fresh is None:
            fresh = fresh_np.copy()
        else:
            fresh *= 0.72          # остывание: белое гаснет за ~4 кадра
            np.maximum(fresh, fresh_np, out=fresh)
        # рост сети: дорисовываем проросшую часть каждого ребра
        if edges:
            for cls, layer in net_layers.items():
                net_tmp.paste(0, (0, 0, W * SS, H * SS))
                dn = ImageDraw.Draw(net_tmp)
                drew = False
                for pts, t0, grow, c, wgt in edges:
                    if c != cls or t < t0:
                        continue
                    # ВНИМАНИЕ: имя `pr` занято хэндлом ffmpeg — не трогать
                    gpr = _cl((t - t0) / grow)
                    k = max(2, int(gpr * 16) + 1)
                    seg = [(q[0] * SS, q[1] * SS) for q in pts[:k]]
                    if len(seg) > 1:
                        dn.line(seg, fill=255, width=max(2, int(wgt * 2.6 * SS)))
                        drew = True
                        if gpr < 1.0:         # голова растущего ребра — свежая
                            hx, hy = pts[min(16, k - 1)]
                            heads.append((hx, hy))
                if drew:
                    np.maximum(layer, np.asarray(net_tmp, np.uint8), out=layer)

        persist += fresh_np * .125
        if t > T_HOLD:
            persist *= .95
        np.clip(persist, 0, 185, out=persist)
        trails = Image.fromarray(persist.astype(np.uint8)).resize((W, H), Image.LANCZOS)

        frame = base_arr.copy() * (0.25 + 0.75 * _ease(_cl(t / T_IN)))

        cm = Image.new("L", (W, H), 0)
        dc = ImageDraw.Draw(cm)
        gp = _cl((t - T_ACC0 - .4) / max(.1, T_ACC1 - T_ACC0 - .4))
        for pts, wmax, delay in corr:
            g = _ease(_cl((gp - delay) / max(.05, 1 - delay)))
            if g <= 0:
                continue
            n = max(2, int(len(pts) * min(1.0, g * 1.2)))
            for i in range(n - 1):
                u = i / (len(pts) - 1)
                wd = wmax * g * (.3 + .8 * math.sin(math.pi * min(1, u * 1.08)) ** .7)
                dc.line([pts[i], pts[i + 1]], fill=int(52 + 36 * g), width=max(2, int(wd)))
        cm = cm.filter(ImageFilter.GaussianBlur(6))
        frame += _tint(cm, TRACK_COL, 1.0) * .42
        frame += _tint(_glow(cm, 8, .3), TRACK_COL, 1.0) * .20
        frame += _tint(trails, TRACK_COL, 1.0) * .58
        frame += _tint(_glow(trails, 5, .3), TRACK_COL, 1.1) * .26
        # «white = just built» из эталона: новорождённый сегмент вспыхивает
        # белым и остывает в основной цвет. Самый дешёвый способ показать,
        # что именно сейчас прибавилось.
        fl = Image.fromarray(np.clip(fresh, 0, 255).astype(np.uint8)).resize(
            (W, H), Image.LANCZOS)
        frame += _tint(fl, (255, 255, 255), 1.0) * .85
        frame += _tint(_glow(fl, 4, .3), (255, 248, 236), 1.2) * .40

        # слои сети: ЦВЕТ = класс ребра (двойное кодирование вместе с толщиной)
        for cls, layer in net_layers.items():
            if not layer.any():
                continue
            col = LEG.get(cls, {}).get("color", DEF_COL)
            lim = Image.fromarray(layer).resize((W, H), Image.LANCZOS)
            frame += _tint(lim, col, 1.0) * .85
            frame += _tint(_glow(lim, 5, .3), col, 1.1) * .35

        # штора слева под текст
        frame *= (1 - shade[..., None] * .62)

        img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8)).convert("RGBA")
        d = ImageDraw.Draw(img, "RGBA")

        for hx, hy in heads[:130]:
            d.ellipse((hx - 1.2, hy - 1.2, hx + 1.2, hy + 1.2), fill=(236, 242, 250, 180))

        for (ex, ey), at, lab, life in evs:
            if not (at <= t <= at + life + 1.1):
                continue
            q = (t - at) / life
            if q <= 1:
                r = 9 + 40 * _ease(_cl(q))
                al = int(195 * (1 - q) ** .85)
                d.ellipse((ex - r, ey - r, ex + r, ey + r), outline=sc.RED + (al,), width=2)
                sc.red_dot(d, ex, ey, 6, t)
                if lab:
                    sc.track(d, (ex + 18, ey - 10), lab.upper(), F_EV,
                             (236, 236, 236, max(0, int(235 * (1 - q * .7)))), 2)
            else:
                q2 = _cl((t - at - life) / 1.1)
                rr = 5 + 22 * q2
                d.ellipse((ex - rr, ey - rr, ex + rr, ey + rr),
                          fill=sc.RED + (int(70 * (1 - q2)),))

        if target:
            sc.red_dot(d, TP[0], TP[1], 9, t)
        if target.get("label") and not (TP[0] < 820 and 110 < TP[1] < 900):
            sc.track(d, (TP[0] + 22, TP[1] - 14), target["label"].upper(),
                     sc._f(sc.F_HEAD, 28), sc.WHITE, 4)
        for s in sources:
            if s.get("label"):
                sx, sy = proj(s["lon"], s["lat"])
                if 0 < sx < W and 0 < sy < H:
                    d.ellipse((sx - 4, sy - 4, sx + 4, sy + 4), fill=(214, 220, 230, 230))
                    # в левой колонке живёт текст — подпись туда не ставим,
                    # иначе название города ложится прямо на строку хроники
                    if not (sx < 880 and 110 < sy < 900):
                        sc.track(d, (sx + 14, sy - 9), s["label"].upper(), F_SC,
                                 (190, 196, 206), 2)

        # ── нижний график ───────────────────────────────────────────────────
        gy0 = H - 112
        perf = _cl((t - T_ACC0) / (T_ACC1 - T_ACC0)) * NPER
        npt = max(2, min(NPER, int(perf) + 1))
        mxv = float(wprof.max())
        xs = [i / max(1, NPER - 1) * (W + 60) - 30 for i in range(npt)]
        area = [(xs[i], gy0 - 10 - (wprof[i] / mxv) ** .55 * 64) for i in range(npt)]
        linec = [(xs[i], gy0 - 6 - (cum[i] ** .95) * 66) for i in range(npt)]
        if len(area) > 2:
            d.polygon(area + [(area[-1][0], gy0 + 14), (-30, gy0 + 14)],
                      fill=sc.RED + (150,))
            d.line(area, fill=(224, 76, 72, 230), width=2)
            d.line(linec, fill=(226, 226, 226, 200), width=2)

        # ── шкала периода справа ────────────────────────────────────────────
        sx0, sy0, sy1 = W - 46, 300, H - 190
        d.line((sx0, sy0, sx0, sy1), fill=(150, 156, 166, 95), width=1)
        pp = _cl((t - T_ACC0) / (T_ACC1 - T_ACC0))
        my = sy0 + pp * (sy1 - sy0)
        d.ellipse((sx0 - 9, my - 9, sx0 + 9, my + 9), fill=sc.RED + (60,))
        d.ellipse((sx0 - 3.2, my - 3.2, sx0 + 3.2, my + 3.2), fill=(240, 226, 226, 250))

        # ── хроника слева (когда счётчиков нет: оперируем событиями) ────────
        if chronicle:
            yy = 430
            fd = sc._f(sc.MONO_B, 23)
            ft = sc._f(sc.F_HEAD, 29)
            for ci, c in enumerate(chronicle):
                at = c.get("at", T_ACC0 + .6 + ci * (T_ACC1 - T_ACC0 - .6)
                           / max(1, len(chronicle)))
                ap = _cl((t - at) / .45)
                if ap <= 0:
                    continue
                dim = .45 + .55 * _cl(1 - (t - at - 2.6) / 3.0)
                a1 = int(235 * ap * dim)
                dx = int(26 * (1 - _ease(ap)))
                sc.track(d, (sc.MARGIN_L + dx, yy), c["date"], fd,
                         (sc.GOLD[0], sc.GOLD[1], sc.GOLD[2], a1), 3)
                d.rectangle((sc.MARK_X, yy + 6, sc.MARK_X + 16, yy + 22),
                            fill=sc.RED + (int(a1 * .9),))
                d.text((sc.MARGIN_L + dx, yy + 34), c["text"], font=ft,
                       fill=sc.WHITE + (a1,))
                yy += 96

        # ── крупный якорь времени (год/месяц текущего периода) ──────────────
        if anchor_labels:
            pi = min(len(anchor_labels) - 1, int(_cl((t - T_ACC0) /
                                                     (T_ACC1 - T_ACC0)) * NPER))
            fa = sc._f(sc.F_ALT, 96)
            lab = str(anchor_labels[pi])
            lw = fa.getlength(lab)
            ax, ay = W - 150 - lw, H - 352
            d.text((ax + 3, ay + 3), lab, font=fa, fill=(0, 0, 0, 150))
            d.text((ax, ay), lab, font=fa, fill=sc.GOLD + (245,))

        # ── счётчики ────────────────────────────────────────────────────────
        k = _cl((t - T_ACC0) / (T_HOLD - T_ACC0))
        ca = int(255 * _cl((t - .9 * seconds / 14) / .5))
        y = 560
        for ci, c in enumerate(counters[:2]):
            val = int(c["total"] * _ease(k) ** (.92 + .12 * ci))
            if val != prev_vals[ci]:
                rolls[ci] = 0.0
            rolls[ci] = min(1.0, rolls[ci] + .44)
            col = sc.RED if c.get("color", "red") == "red" else sc.WHITE
            if ca > 0:
                ex = _rolling(img, sc.MARGIN_L, y, val, prev_vals[ci], rolls[ci],
                              F_NUM, col, ca)
                if c.get("unit"):
                    d.text((ex + 14, y + 40), c["unit"], font=F_UNIT, fill=col + (ca,))
                if c.get("line1"):
                    d.text((sc.MARGIN_L + 2, y + 104), c["line1"], font=F_L1,
                           fill=sc.WHITE + (ca,))
                if c.get("line2"):
                    d.text((sc.MARGIN_L + 2, y + 142), c["line2"], font=F_L2,
                           fill=(198, 202, 210, ca))
            prev_vals[ci] = val
            y += 212

        # ── шапка ───────────────────────────────────────────────────────────
        ta = int(255 * _ease(_cl(t / .45)))
        if kick:
            sc.kicker(d, 132, kick, dot=True, t=t)
        if title:
            d.text((sc.MARGIN_L, 180), title, font=F_TIT, fill=sc.WHITE + (ta,))
        if title2:
            d.text((sc.MARGIN_L, 272), title2, font=F_TIT2, fill=sc.RED + (ta,))
        for i, line in enumerate(period):
            if not line:
                continue
            wd = F_PER.getlength(line)
            d.text((W - 150 - wd, 150 + i * 40), line, font=F_PER,
                   fill=(214, 214, 214, ta))
        # ЛЕГЕНДА: цвет = класс, толщина = вес. Без неё двойное кодирование
        # остаётся украшением — зритель не знает, что значит толщина
        if legend:
            fl = sc._f(sc.MONO, 22)
            lx, ly = W - 150, 252
            wmax = max(F_PER.getlength(str(l.get("label", ""))) for l in legend)
            d.text((lx - wmax - 54, ly - 30), "ЦВЕТ — ЭТАП", font=sc._f(sc.MONO, 17),
                   fill=(150, 156, 166, ta))
            for i, l in enumerate(legend):
                yy = ly + i * 30
                col = l.get("color", (214, 170, 92))
                d.line((lx - wmax - 62, yy + 10, lx - wmax - 18, yy + 10),
                       fill=col + (ta,), width=max(3, int(l.get("w", 1) * 3)))
                d.text((lx - wmax - 6, yy), str(l.get("label", "")), font=fl,
                       fill=(214, 214, 214, ta))
            yy = ly + len(legend) * 30 + 10
            d.text((lx - wmax - 54, yy), "ТОЛЩИНА — ЗНАЧИМОСТЬ",
                   font=sc._f(sc.MONO, 17), fill=(150, 156, 166, ta))

        sc.footer(d, source, watermark)

        img = img.convert("RGB")
        if t > T_HOLD:
            z = 1 + .045 * _ease(_cl((t - T_HOLD) / max(.1, seconds - T_HOLD)))
            nw, nh = int(W * z), int(H * z)
            ox, oy = (nw - W) // 2, (nh - H) // 2
            img = img.resize((nw, nh), Image.LANCZOS).crop((ox, oy, ox + W, oy + H))

        if keep_frames and fi % keep_frames == 0:
            img.save(f"{out_mp4.rsplit('.', 1)[0]}_f{fi:04d}.png")
        pr.stdin.write(img.tobytes())

    pr.stdin.close()
    pr.wait()
    return out_mp4
