# -*- coding: utf-8 -*-
"""КАРТА ОБСТАНОВКИ: линия соприкосновения, продвижение, полуокружение.

Делается по ТЕКСТУ сообщения, а не копированием чужой карты: населённые
пункты берутся по координатам (они открытые), линия обстановки строится
по описанию — «восточнее такого-то», «в треугольнике таких-то». Поэтому
в подвале стоит обязательная оговорка: это СХЕМА ПО ОПИСАНИЮ, а не
оперативная карта. Без неё картинка выдаёт за факт то, чего в источнике
нет.

Что умеет:
  • подложка с затенённым рельефом (тот же `datamap.basemap`);
  • линия обстановки ДВУХ дат: «было» тонким пунктиром, «стало»
    сплошной, между ними заливается полоса изменения — именно она и
    есть новость;
  • стрелки продвижения: прорастают по очереди, с подписью и
    наконечником, толщина по значимости;
  • «карман» (полуокружение) — замкнутый контур с пульсацией и
    подписью, плюс отдельная пунктирная нитка «путь отхода»;
  • населённые пункты: точка, подпись без наезда на соседние, ключевой
    пункт пульсирует;
  • якорь времени (дата) и легенда, подвал с источником.

Палитра — системная: наступление красным (роль акцента), оборона
холодным серо-синим, служебное золотым. Зелёного и жёлтого «как на
военных картах» здесь нет: ролик должен оставаться в своей системе.

  python3 frontline.py <config.json> <out.mp4|out.png>
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import style_cards as sc
import datamap as dm

W, H = sc.W, sc.H

ATK = (198, 54, 48)          # наступление
ATK_SOFT = (150, 46, 42)
DEF = (92, 112, 138)         # оборона
POCKET = (236, 196, 60)      # полуокружение
INK = (232, 232, 232)


def _terrain(region, tiles_dir):
    """Рельеф по открытым terrarium-тайлам: мозаика, вырезка окна,
    отмывка (hillshade) плюс мягкая гипсометрия. Именно по ней видно,
    что восточнее начинается ровная степь, а не просто пустое поле."""
    import glob
    import re as _re
    lon0, lon1, lat0, lat1 = region
    files = glob.glob(os.path.join(tiles_dir, "t_*_*.png"))
    if not files:
        return None
    xs, ys = set(), set()
    pat = _re.compile(r"t_(\d+)_(\d+)\.png$")
    for f in files:
        m = pat.search(f)
        if m:
            xs.add(int(m.group(1)))
            ys.add(int(m.group(2)))
    if not xs:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    z = 12
    n = 2 ** z
    big = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
    for f in files:
        m = pat.search(f)
        x, y = int(m.group(1)), int(m.group(2))
        try:
            big.paste(Image.open(f).convert("RGB"), ((x - x0) * 256, (y - y0) * 256))
        except Exception:
            pass
    # высоты из terrarium: (R*256 + G + B/256) - 32768
    a = np.asarray(big, np.float32)
    elev = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768

    def lon2px(lon):
        return ((lon + 180.0) / 360.0 * n - x0) * 256

    def lat2px(lat):
        la = math.radians(lat)
        yy = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
        return (yy - y0) * 256

    px0, px1 = lon2px(lon0), lon2px(lon1)
    py0, py1 = lat2px(lat1), lat2px(lat0)
    px0, px1 = max(0, int(px0)), min(elev.shape[1], int(px1))
    py0, py1 = max(0, int(py0)), min(elev.shape[0], int(py1))
    if px1 - px0 < 8 or py1 - py0 < 8:
        return None
    cut = elev[py0:py1, px0:px1]
    cut = np.asarray(Image.fromarray(cut).resize((W, H), Image.BICUBIC), np.float32)

    # отмывка: свет с северо-запада
    gy, gx = np.gradient(cut)
    slope = np.arctan(np.hypot(gx, gy) * 0.9)
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(42)
    shade = (math.sin(alt) * np.cos(slope) +
             math.cos(alt) * np.sin(slope) * np.cos(az - aspect))
    shade = np.clip(shade, 0, 1)
    # гипсометрия: низины темнее и холоднее, возвышенности теплее
    lo, hi = np.percentile(cut, 3), np.percentile(cut, 97)
    hyp = np.clip((cut - lo) / max(hi - lo, 1e-6), 0, 1)
    base = np.stack([24 + hyp * 26, 24 + hyp * 23, 26 + hyp * 17], axis=-1)
    out = base * (0.55 + 0.85 * shade[..., None])
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def _osm_layer(im, region, osm_path):
    """Дороги, реки, леса и застройка — своей графикой по данным OSM.
    Без них карта не узнаётся: именно трасса и речка дают зрителю
    понять, что он смотрит на конкретное место."""
    if not osm_path or not os.path.exists(osm_path):
        return im
    data = json.load(open(osm_path, encoding="utf-8"))
    lon0, lon1, lat0, lat1 = region

    def P(lon, lat):
        return ((lon - lon0) / (lon1 - lon0) * W,
                (lat1 - lat) / (lat1 - lat0) * H)

    def mask(items, draw_fn, ss=2):
        def fn(d, s):
            for it in items:
                pts = [(P(x, y)[0] * s, P(x, y)[1] * s) for x, y in it["pts"]]
                if len(pts) < 2:
                    continue
                draw_fn(d, pts, s, it)
        return _aa((W, H), fn, ss=ss)

    # леса
    if data.get("forest"):
        m = mask(data["forest"], lambda d, p, s, it: d.polygon(p, fill=255))
        _tint(im, m, (34, 46, 36), 0.55)
    # застройка
    if data.get("town"):
        m = mask(data["town"], lambda d, p, s, it: d.polygon(p, fill=255))
        _tint(im, m, (74, 72, 70), 0.45)
    # вода
    if data.get("water"):
        def wfn(d, p, s, it):
            if it.get("tag") in ("river", "stream"):
                d.line(p, fill=255, width=int((3 if it["tag"] == "river" else 2) * s))
            else:
                d.polygon(p, fill=255)
        m = mask(data["water"], wfn)
        _tint(im, m, (46, 70, 96), 0.75)
    # дороги: трассы заметнее просёлков
    if data.get("road"):
        wide = [r for r in data["road"] if r["tag"] in ("motorway", "trunk", "primary")]
        thin = [r for r in data["road"] if r not in wide]
        if thin:
            m = mask(thin, lambda d, p, s, it: d.line(p, fill=255, width=int(1.6 * s)))
            _tint(im, m, (120, 116, 108), 0.6)
        if wide:
            m = mask(wide, lambda d, p, s, it: d.line(p, fill=255, width=int(3.2 * s)))
            _tint(im, m, (176, 170, 156), 0.85)
    return im


_BIG_CACHE = {}


def _ground_camera(base_reg, reg, tiles_dir, osm_path, scale=3):
    """Подложка под движущуюся камеру.

    Рельеф и вектор считаются ОДИН раз для широкого окна в утроенном
    разрешении, а кадр просто вырезается из этого буфера. Иначе каждое
    новое положение камеры пересобирало мозаику тайлов и 2600 объектов
    OSM — полторы секунды на кадр (замер 20.10).
    """
    key = (tuple(round(v, 4) for v in base_reg), tiles_dir, osm_path, scale)
    if key not in _BIG_CACHE:
        global W, H
        w0, h0 = W, H
        W, H = w0 * scale, h0 * scale
        try:
            big = _ground(base_reg, tiles_dir, osm_path)
        finally:
            W, H = w0, h0
        _BIG_CACHE[key] = big
    big = _BIG_CACHE[key]
    blon0, blon1, blat0, blat1 = base_reg
    lon0, lon1, lat0, lat1 = reg
    bw, bh = big.size
    x0 = (lon0 - blon0) / (blon1 - blon0) * bw
    x1 = (lon1 - blon0) / (blon1 - blon0) * bw
    y0 = (blat1 - lat1) / (blat1 - blat0) * bh
    y1 = (blat1 - lat0) / (blat1 - blat0) * bh
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(bw, int(x1)), min(bh, int(y1))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return _ground(reg, tiles_dir, osm_path)
    # BILINEAR вместо LANCZOS: рельеф и так мягкий, а на каждом кадре
    # разница в качестве незаметна — зато вдвое быстрее
    return big.crop((x0, y0, x1, y1)).resize((W, H), Image.BILINEAR)


def _ground(region, tiles_dir=None, osm_path=None):
    """Подложка для КРУПНОГО масштаба (десятки километров).

    `datamap.basemap` здесь не годится: контуры стран на таком окне не
    дают ничего, а мировой рельеф растягивается в пятно. Поэтому своя
    земля: фирменная виньетка, мягкие пятна рельефа, координатная сетка
    с подписями и масштабная линейка — по ней зритель понимает, что три
    километра до посёлка это действительно рядом.
    """
    lon0, lon1, lat0, lat1 = region
    key = (tuple(round(v, 4) for v in region), tiles_dir, osm_path)
    if key in _GROUND_CACHE:
        return _GROUND_CACHE[key].copy()
    im = None
    if tiles_dir:
        im = _terrain(region, tiles_dir)
    if im is None:                      # нет тайлов — прежняя условная земля
        im = sc.canvas()
        rng = np.random.default_rng(7)
        small = Image.fromarray((rng.random((28, 48)) * 255).astype(np.uint8), "L")
        relief = small.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(26))
        a = np.asarray(im, np.float32)
        r = (np.asarray(relief, np.float32) / 255.0)[..., None]
        a = a + (r - 0.5) * 16.0
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    im = _osm_layer(im, region, osm_path)

    d = ImageDraw.Draw(im, "RGBA")
    f = sc._f(sc.MONO, 18)
    # сетка: шаг растёт вместе с охватом карты — на обзорной карте в
    # несколько градусов шаг 0.1° давал полсотни линий и подписи забивали
    # кадр (поймано 20.10 на карте направлений)
    w_deg = lon1 - lon0
    step = (0.05 if w_deg < 0.6 else 0.1 if w_deg < 1.5 else
            0.25 if w_deg < 3.0 else 0.5 if w_deg < 6.0 else 1.0)
    x = math.ceil(lon0 / step) * step
    while x < lon1:
        px = (x - lon0) / (lon1 - lon0) * W
        d.line([(px, 0), (px, H)], fill=(255, 255, 255, 16), width=1)
        d.text((px + 6, 206), f"{x:.2f}°", font=f, fill=(255, 255, 255, 38))
        x += step
    y = math.ceil(lat0 / step) * step
    while y < lat1:
        py = (lat1 - y) / (lat1 - lat0) * H
        d.line([(0, py), (W, py)], fill=(255, 255, 255, 16), width=1)
        d.text((10, py + 4), f"{y:.2f}°", font=f, fill=(255, 255, 255, 40))
        y += step
    # масштабная линейка
    km_per_deg = 111.32 * math.cos(math.radians((lat0 + lat1) / 2))
    px_per_km = W / ((lon1 - lon0) * km_per_deg)
    for km in (20, 10, 5, 2):
        if px_per_km * km < W * 0.3:
            break
    bx, by = sc.MARGIN_L, H - 232
    d.rectangle((bx, by, bx + px_per_km * km, by + 7), fill=(226, 226, 230, 210))
    for i in range(3):
        xx = bx + px_per_km * km * i / 2
        d.rectangle((xx, by - 5, xx + 2, by + 12), fill=(226, 226, 230, 210))
    lab = f"{km} км"
    d.text((bx + px_per_km * km / 2 - f.getlength(lab) / 2, by + 14), lab,
           font=f, fill=(206, 206, 210, 230))
    _GROUND_CACHE[key] = im
    return im.copy()


_GROUND_CACHE = {}
_STATIC_CACHE = {}


def _proj_region(points, pad=0.10):
    """Окно карты по всем точкам сюжета, с полями в долях размаха."""
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)
    dx = max(lon1 - lon0, 0.02)
    dy = max(lat1 - lat0, 0.02)
    lon0 -= dx * pad * 2.2
    lon1 += dx * pad * 2.2
    lat0 -= dy * pad
    lat1 += dy * pad
    klat = math.cos(math.radians((lat0 + lat1) / 2)) or 1.0
    want = (W / H) / klat
    have = (lon1 - lon0) / max(lat1 - lat0, 1e-9)
    if have < want:
        add = ((lat1 - lat0) * want - (lon1 - lon0)) / 2
        lon0, lon1 = lon0 - add, lon1 + add
    else:
        add = ((lon1 - lon0) / want - (lat1 - lat0)) / 2
        lat0, lat1 = lat0 - add, lat1 + add
    return lon0, lon1, lat0, lat1


def _smooth(pts, k=18):
    """Catmull-Rom: линия обстановки не должна быть ломаной из отрезков."""
    if len(pts) < 3:
        return list(pts)
    out, n = [], len(pts)
    for i in range(n - 1):
        p0 = pts[max(i - 1, 0)]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[min(i + 2, n - 1)]
        for j in range(k):
            t = j / k
            t2, t3 = t * t, t * t * t
            out.append((
                0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
                       (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
                0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
                       (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)))
    out.append(tuple(pts[-1]))
    return out


def _aa(size, fn, ss=2):
    w, h = int(size[0]), int(size[1])
    m = Image.new("L", (w * ss, h * ss), 0)
    fn(ImageDraw.Draw(m), ss)
    return m.resize((w, h), Image.LANCZOS)


class _Shift:
    """Обёртка над ImageDraw: сдвигает координаты в систему бокса."""

    def __init__(self, d, ox, oy):
        self._d, self._ox, self._oy = d, ox, oy

    def _p(self, xy):
        return [(x - self._ox, y - self._oy) for x, y in xy]

    def polygon(self, xy, **kw):
        self._d.polygon(self._p(xy), **kw)

    def line(self, xy, **kw):
        self._d.line(self._p(xy), **kw)

    def ellipse(self, box, **kw):
        self._d.ellipse((box[0] - self._ox, box[1] - self._oy,
                         box[2] - self._ox, box[3] - self._oy), **kw)


def _vis(x, y, pad=30):
    """Точка внутри кадра? Подпись объекта, уехавшего за край камеры,
    висит в пустоте и читается как мусор (поймано 20.10 на бете)."""
    return -pad <= x <= W + pad and -pad <= y <= H + pad


def _box_of(points, pad=60):
    """Прямоугольник вокруг объекта с полем — в нём и рисуем маску.
    Маска на полный кадр с суперсэмплингом стоила 1,7 с на кадр; в боксе
    она стоит десятки миллисекунд (замер 20.10)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0 = max(0, int(min(xs) - pad))
    y0 = max(0, int(min(ys) - pad))
    x1 = min(W, int(max(xs) + pad))
    y1 = min(H, int(max(ys) + pad))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return (x0, y0, x1, y1)


def _mask_box(box, fn, ss=2):
    x0, y0, x1, y1 = box
    return _aa((x1 - x0, y1 - y0),
               lambda d, s: fn(d, s, x0, y0), ss=ss), (x0, y0)


def _tint(im, mask, color, alpha=1.0, box=(0, 0)):
    if alpha < 1.0:
        mask = mask.point(lambda v: int(v * alpha))
    im.paste(Image.new("RGB", mask.size, tuple(int(c) for c in color)), box, mask)


def _glow(im, mask, color, k=0.5, blur=16, box=(0, 0)):
    _tint(im, mask.filter(ImageFilter.GaussianBlur(blur)), color, k, box)


def _dash(d, pts, ss, color_mask=255, on=9, off=7, width=3):
    """Пунктир по полилинии — длина штриха считается по пути, иначе на
    изгибах пунктир рвётся неровно."""
    acc, draw_on, seg = 0.0, True, []
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        seg_len = math.hypot(x2 - x1, y2 - y1)
        t = 0.0
        while t < seg_len:
            step = min((on if draw_on else off) - acc, seg_len - t)
            a = (x1 + (x2 - x1) * (t / seg_len), y1 + (y2 - y1) * (t / seg_len))
            t2 = t + step
            b = (x1 + (x2 - x1) * (t2 / seg_len), y1 + (y2 - y1) * (t2 / seg_len))
            if draw_on:
                d.line([ (a[0] * ss, a[1] * ss), (b[0] * ss, b[1] * ss) ],
                       fill=color_mask, width=int(width * ss))
            acc += step
            t = t2
            if acc >= (on if draw_on else off) - 1e-9:
                draw_on = not draw_on
                acc = 0.0


def _arrow_path(a, b, bend=0.22):
    """Дуга от точки к точке: прямая стрелка на карте выглядит чертежом,
    дуга читается как движение."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    cx, cy = mx - dy * bend, my + dx * bend
    pts = []
    for i in range(41):
        t = i / 40
        u = 1 - t
        pts.append((u * u * a[0] + 2 * u * t * cx + t * t * b[0],
                    u * u * a[1] + 2 * u * t * cy + t * t * b[1]))
    return pts


def _camera_region(camera, base_reg, t):
    """Окно кадра на момент t. Камера ТОЛЬКО приближается и ведёт вбок:
    зум-аут и дрожь запрещены (user, 20.10), поэтому между ключевыми
    окнами идёт плавная интерполяция со смягчением, без возврата."""
    if not camera or t is None:
        return base_reg
    keys = sorted(camera, key=lambda k: float(k.get("at", 0)))
    if t <= float(keys[0].get("at", 0)):
        return tuple(keys[0].get("region") or base_reg)
    for a, b in zip(keys, keys[1:]):
        ta, tb = float(a.get("at", 0)), float(b.get("at", 0))
        if ta <= t <= tb:
            ra = a.get("region") or base_reg
            rb = b.get("region") or base_reg
            k = sc._ease((t - ta) / max(tb - ta, 1e-6))
            return tuple(ra[i] + (rb[i] - ra[i]) * k for i in range(4))
    return tuple(keys[-1].get("region") or base_reg)


def _episode(episodes, t):
    """Подпись эпизода («что сейчас показываем») — крупной плашкой."""
    if not episodes or t is None:
        return None
    cur = None
    for e in sorted(episodes, key=lambda x: float(x.get("at", 0))):
        if t >= float(e.get("at", 0)):
            cur = e
    if cur is None:
        return None
    age = t - float(cur.get("at", 0))
    if age > float(cur.get("hold", 5.0)):
        return None
    return cur, age


def frontline(out=None, *, kick="", title="", date="", places=(), front_now=(),
              front_before=(), arrows=(), pockets=(), routes=(), legend=(),
              note="", source="", disclaimer="схема по описанию сообщения, "
              "не оперативная карта", watermark="ДО ПРИГОВОРА",
              region=None, terrain_dir=None, osm=None, camera=(), episodes=(),
              units=(), t=None, sfx=None):
    """Кадр карты обстановки. `t` — секунды (None = полный статичный кадр).

    places     — [{"name", "lon", "lat", "key": True, "side": "atk"/"def"}]
    front_now  — [[lon, lat], ...] линия на сегодня
    front_before — она же на прошлую дату (пунктиром)
    arrows     — [{"from": [lon,lat] | "имя", "to": ..., "label", "weight"}]
    pockets    — [{"points": [[lon,lat]...], "label"}]
    routes     — [{"points": [...], "label"}] — пунктирные нитки (отход)
    """
    pts_all = [(p["lon"], p["lat"]) for p in places]
    pts_all += [tuple(p) for p in front_now] + [tuple(p) for p in front_before]
    for pk in pockets:
        pts_all += [tuple(p) for p in pk.get("points", [])]
    if not pts_all:
        return sc.canvas()
    base_reg = tuple(region) if region else _proj_region(pts_all)
    reg = _camera_region(camera, base_reg, t)
    proj = dm._projector(reg)
    if camera and t is not None:
        im = _ground_camera(base_reg, reg, terrain_dir, osm)
    else:
        im = _ground(reg, terrain_dir, osm)

    def P(v):
        """Точка сюжета: координаты или имя населённого пункта."""
        if isinstance(v, str):
            for p in places:
                if p["name"].lower() == v.lower():
                    return proj(p["lon"], p["lat"])
            return (W / 2, H / 2)
        return proj(v[0], v[1])

    _label_boxes = []
    _STATIC_KEY = (tuple(round(v, 4) for v in reg),
                   json.dumps(front_before, sort_keys=True),
                   json.dumps(front_now, sort_keys=True))
    A = (lambda at, dur=0.5: 1.0 if t is None
         else max(0.0, min(1.0, (t - at) / dur)))
    E = (lambda at, dur=0.5: sc._ease(A(at, dur)))

    # Готовый «фон обстановки» (земля + зона + обе линии) кэшируется:
    # перерисовывать его на каждом кадре стоило по 2-3 секунды, и клип на
    # полминуты считался бы четверть часа (поймано 20.10).
    moving = bool(camera) and t is not None
    full_lines = (t is None) or t >= 3.7
    if full_lines and not moving and _STATIC_KEY in _STATIC_CACHE:
        im = _STATIC_CACHE[_STATIC_KEY].copy()
        front_before_draw, front_now_draw = (), ()
    else:
        front_before_draw, front_now_draw = front_before, front_now

    # ── полоса изменения между «было» и «стало»
    if front_before_draw and front_now_draw:
        k = E(1.5, 0.8)
        if k > 0:
            a = [P(p) for p in front_before]
            b = [P(p) for p in front_now]
            poly = _smooth(a) + _smooth(b)[::-1]

            bx = _box_of(poly, 10)
            if bx:
                m, off = _mask_box(bx, lambda d, ss, ox, oy: d.polygon(
                    [((x - ox) * ss, (y - oy) * ss) for x, y in poly], fill=255))
                _tint(im, m, ATK_SOFT, 0.13 * k, off)
            # штриховка поверх заливки — чтобы полоса читалась как зона,
            # а не как ещё одна плоская заливка
                hw, hh = bx[2] - bx[0], bx[3] - bx[1]

                def hatch(d, ss):
                    for x in range(-hh, hw + hh, 26):
                        d.line([(x * ss, 0), ((x + hh) * ss, hh * ss)],
                               fill=255, width=int(1.6 * ss))
                hm = _aa((hw, hh), hatch, ss=2)
                hm = Image.composite(hm, Image.new("L", (hw, hh), 0), m)
                _tint(im, hm, ATK, 0.11 * k, off)

    # ── линия «было»
    if front_before_draw:
        k = E(1.1, 0.6)
        if k > 0:
            p = _smooth([P(x) for x in front_before])
            bx = _box_of(p, 14)
            if bx:
                m, off = _mask_box(bx, lambda d, ss, ox, oy: _dash(
                    d, [(x - ox, y - oy) for x, y in p], ss, 255, 11, 9, 2.4))
                _tint(im, m, (150, 158, 170), 0.85 * k, off)

    # ── линия «стало» прочерчивается
    if front_now_draw:
        prog = 1.0 if t is None else sc._ease(max(0.0, min(1.0, (t - 1.9) / 1.8)))
        if prog > 0:
            p = _smooth([P(x) for x in front_now])
            n = max(2, int(len(p) * prog))
            seen = p[:n]

            bx = _box_of(seen, 20)
            if bx:
                m, off = _mask_box(bx, lambda d, ss, ox, oy: d.line(
                    [((x - ox) * ss, (y - oy) * ss) for x, y in seen], fill=255,
                    width=int(4.6 * ss), joint="curve"))
                _glow(im, m, ATK, 0.45, 14, off)
                _tint(im, m, ATK, 1.0, off)
            sc._ev(sfx, 1.9, "accent")

    if full_lines and not moving and _STATIC_KEY not in _STATIC_CACHE:
        _STATIC_CACHE[_STATIC_KEY] = im.copy()

    # ── стрелки продвижения
    f_lab = sc._f(sc.F_HEAD, 27)
    for i, ar in enumerate(arrows):
        at = 3.9 + i * 0.75
        k = 1.0 if t is None else sc._ease(max(0.0, min(1.0, (t - at) / 0.9)))
        if k <= 0:
            continue
        sc._ev(sfx, at, "label")
        a, b = P(ar["from"]), P(ar["to"])
        path = _arrow_path(a, b, ar.get("bend", 0.2))
        cut = max(2, int(len(path) * k))
        seen = path[:cut]
        wgt = float(ar.get("weight", 1.0))

        # ЖИРНАЯ СТРЕЛА (20.10): тонкая дуга читалась как «нарисовали
        # карандашом». Тело строится полигоном с сужением к хвосту, у
        # головы — крупный наконечник, по телу идёт светлая кромка.
        wd_head = 26 + 16 * wgt
        wd_body = 13 + 9 * wgt

        def _body_poly(seen, wd_body, wd_head):
            left, right = [], []
            n = len(seen)
            for i, (x, y) in enumerate(seen):
                if i == 0:
                    ax, ay = seen[1][0] - x, seen[1][1] - y
                elif i == n - 1:
                    ax, ay = x - seen[-2][0], y - seen[-2][1]
                else:
                    ax, ay = seen[i + 1][0] - seen[i - 1][0], seen[i + 1][1] - seen[i - 1][1]
                L = math.hypot(ax, ay) or 1.0
                nx, ny = -ay / L, ax / L
                u = i / max(n - 1, 1)
                w = wd_body * (0.42 + 0.58 * u)          # сужение к хвосту
                left.append((x + nx * w, y + ny * w))
                right.append((x - nx * w, y - ny * w))
            return left + right[::-1]

        poly = _body_poly(seen, wd_body, wd_head)

        abx = _box_of(poly, 26)
        if abx is None:
            continue
        mx, my = seen[len(seen) // 2]
        if ar.get("label") and k > 0.6 and _vis(mx, my, -40):
            d = ImageDraw.Draw(im, "RGBA")
            txt = str(ar["label"]).upper()
            wd = sc.track_w(txt, f_lab, 2)
            bx = (mx - wd / 2 - 12, my - 48, mx + wd / 2 + 12, my - 10)
            d.rectangle(bx, fill=(14, 12, 12, 212))
            d.rectangle((bx[0], bx[1], bx[0] + 4, bx[3]), fill=ATK + (255,))
            sc.track(d, (mx - wd / 2, my - 44), txt, f_lab, INK + (255,), 2)
            _label_boxes.append(bx)

    # ── «карман» и путь отхода
    f_pk = sc._f(sc.F_HEAD, 29)
    for i, pk in enumerate(pockets):
        at = 6.4 + i * 0.6
        k = 1.0 if t is None else sc._ease(max(0.0, min(1.0, (t - at) / 0.8)))
        if k <= 0:
            continue
        sc._ev(sfx, at, "quote")
        pts = [P(x) for x in pk.get("points", [])]
        if len(pts) < 3:
            continue
        ring = _smooth(pts + [pts[0]])
        puls = 1.0 if t is None else 0.72 + 0.28 * (
            0.5 + 0.5 * math.cos((t - at) * 3.4))

        pbx = _box_of(ring, 26)
        if pbx:
            m, off = _mask_box(pbx, lambda d, ss, ox, oy: d.line(
                [((x - ox) * ss, (y - oy) * ss) for x, y in ring], fill=255,
                width=int(4.2 * ss), joint="curve"))
            _glow(im, m, POCKET, 0.5 * puls * k, 20, off)
            _tint(im, m, POCKET, k, off)
            fm, off2 = _mask_box(pbx, lambda d, ss, ox, oy: d.polygon(
                [((x - ox) * ss, (y - oy) * ss) for x, y in ring], fill=255))
            _tint(im, fm, POCKET, 0.10 * k, off2)
        cx = sum(x for x, _ in pts) / len(pts)
        cy = min(y for _, y in pts) - 54
        if pk.get("label") and _vis(cx, cy, -40):
            d = ImageDraw.Draw(im, "RGBA")
            txt = str(pk["label"]).upper()
            wd = sc.track_w(txt, f_pk, 3)
            d.rectangle((cx - wd / 2 - 16, cy - 10, cx + wd / 2 + 16, cy + 34),
                        fill=(26, 20, 6, 226))
            sc.track(d, (cx - wd / 2, cy - 4), txt, f_pk, POCKET + (255,), 3)
            _label_boxes.append((cx - wd / 2 - 16, cy - 10, cx + wd / 2 + 16, cy + 34))

    for i, rt in enumerate(routes):
        at = 7.6 + i * 0.5
        k = 1.0 if t is None else sc._ease(max(0.0, min(1.0, (t - at) / 0.9)))
        if k <= 0:
            continue
        pts = _smooth([P(x) for x in rt.get("points", [])])
        n = max(2, int(len(pts) * k))
        rbx = _box_of(pts[:n], 16)
        if rbx:
            m, off = _mask_box(rbx, lambda d, ss, ox, oy: _dash(
                d, [(x - ox, y - oy) for x, y in pts[:n]], ss, 255, 14, 10, 3.0))
            _tint(im, m, (226, 226, 230), 0.9 * k, off)
        ex, ey = pts[n - 1]
        if rt.get("label") and k > 0.7 and _vis(ex, ey, -60):
            d = ImageDraw.Draw(im, "RGBA")
            txt = str(rt["label"]).upper()
            f = sc._f(sc.MONO, 23)
            wd = f.getlength(txt)
            d.rectangle((ex + 12, ey - 20, ex + 28 + wd, ey + 18),
                        fill=(14, 14, 16, 206))
            d.text((ex + 20, ey - 14), txt, font=f, fill=(226, 226, 230, 255))

    # ── штабные знаки подразделений
    f_un = sc._f(sc.MONO_B, 22)
    f_un2 = sc._f(sc.MONO, 19)
    for i, u in enumerate(units):
        at = float(u.get("at", 5.0))
        k = 1.0 if t is None else sc._ease(max(0.0, min(1.0, (t - at) / 0.6)))
        if k <= 0:
            continue
        x, y = P(u.get("pos") or [0, 0])
        if not _vis(x, y, -80):
            continue
        col = ATK if u.get("side", "atk") == "atk" else DEF
        bw2, bh2 = 62 * k, 40 * k
        d = ImageDraw.Draw(im, "RGBA")
        d.rectangle((x - bw2, y - bh2, x + bw2, y + bh2), fill=(16, 16, 18, 226),
                    outline=col + (255,), width=3)
        if u.get("kind", "inf") == "inf":        # пехота: косые
            d.line([(x - bw2, y - bh2), (x + bw2, y + bh2)], fill=col + (235,), width=3)
            d.line([(x - bw2, y + bh2), (x + bw2, y - bh2)], fill=col + (235,), width=3)
        elif u.get("kind") == "mech":            # мотопехота: овал
            d.ellipse((x - bw2 * 0.6, y - bh2 * 0.5, x + bw2 * 0.6, y + bh2 * 0.5),
                      outline=col + (235,), width=3)
        if k > 0.8 and u.get("label"):
            txt = str(u["label"]).upper()
            wd = f_un.getlength(txt)
            d.rectangle((x - wd / 2 - 10, y + bh2 + 6, x + wd / 2 + 10, y + bh2 + 40),
                        fill=(16, 16, 18, 216))
            d.text((x - wd / 2, y + bh2 + 10), txt, font=f_un, fill=INK + (255,))
            if u.get("note"):
                n2 = str(u["note"])
                wd2 = f_un2.getlength(n2)
                d.text((x - wd2 / 2, y + bh2 + 44), n2, font=f_un2,
                       fill=(168, 168, 174, 255))
        sc._ev(sfx, at, "label")

    # ── населённые пункты
    d = ImageDraw.Draw(im, "RGBA")
    f_pl = sc._f(sc.F_HEAD, 26)
    # шапка, подвал, легенда и плашки стрелок заняты заранее
    taken = [(0, 0, W, 190), (0, H - 210, W, H)]
    taken += _label_boxes
    for i, p in enumerate(sorted(places, key=lambda q: not q.get("key"))):
        at = 0.5 + i * 0.12
        k = 1.0 if t is None else sc._ease(max(0.0, min(1.0, (t - at) / 0.4)))
        if k <= 0:
            continue
        x, y = proj(p["lon"], p["lat"])
        key = bool(p.get("key"))
        col = ATK if p.get("side") == "atk" else (
            POCKET if p.get("side") == "pocket" else (214, 216, 220))
        r = (9 if key else 6) * k
        if key:
            puls = 1.0 if t is None else 0.55 + 0.45 * (
                0.5 + 0.5 * math.cos(t * 3.0))
            d.ellipse((x - r * 3.4 * puls, y - r * 3.4 * puls,
                       x + r * 3.4 * puls, y + r * 3.4 * puls),
                      fill=col + (int(46 * puls),))
        d.ellipse((x - r, y - r, x + r, y + r), fill=col + (255,))
        d.ellipse((x - r, y - r, x + r, y + r), outline=(14, 14, 16, 220), width=2)

        txt = str(p["name"]).upper()
        wd = sc.track_w(txt, f_pl, 2)
        spot = None
        for dx, dy in ((16, -14), (-wd - 18, -14), (-wd / 2, 18), (-wd / 2, -48),
                       (16, 16), (-wd - 18, 16), (16, -44), (-wd - 18, -44),
                       (30, -70), (-wd - 32, -70), (30, 44), (-wd - 32, 44),
                       (-wd / 2, 54), (-wd / 2, -78)):
            bx = (x + dx - 8, y + dy - 6, x + dx + wd + 8, y + dy + 30)
            if bx[0] < 8 or bx[2] > W - 8 or bx[1] < 120 or bx[3] > H - 120:
                continue
            if any(not (bx[2] < q[0] or bx[0] > q[2] or bx[3] < q[1] or bx[1] > q[3])
                   for q in taken):
                continue
            spot = (x + dx, y + dy, bx)
            break
        if spot is None:
            continue
        taken.append(spot[2])
        d.rectangle((spot[2][0], spot[2][1], spot[2][2], spot[2][3]),
                    fill=(12, 12, 14, 170))
        sc.track(d, (spot[0], spot[1]), txt, f_pl,
                 (INK if key else (198, 200, 206)) + (int(255 * k),), 2)

    # ── шапка, дата, легенда, подвал
    a, dx = sc._rv(t, 0.15)
    if kick:
        im = sc._put(im, lambda dd: sc.kicker(dd, 64, kick), a, dx)
    a, dx = sc._rv(t, 0.3)
    # заголовок живёт только в первом эпизоде: дальше его место занимает
    # подпись происходящего, иначе две крупные надписи дерутся
    head_k = 1.0 if t is None else max(0.0, min(1.0, (6.4 - t) / 0.6))
    if title and head_k > 0:
        im = sc._put(im, lambda dd: dd.text((sc.MARGIN_L, 110), title,
                                            font=sc._f(sc.F_HEAD, 58),
                                            fill=sc.WHITE + (int(255 * head_k),)),
                     a * head_k, dx)
    d = ImageDraw.Draw(im, "RGBA")
    if date:
        f = sc._f(sc.MONO_B, 30)
        wd = f.getlength(date)
        d.rectangle((W - 150 - wd - 26, 70, W - 124, 122), fill=(14, 14, 16, 214))
        d.rectangle((W - 150 - wd - 26, 70, W - 150 - wd - 22, 122), fill=ATK + (255,))
        d.text((W - 150 - wd - 10, 80), date, font=f, fill=INK + (255,))

    if legend:
        lx = W - 470
        ly = H - 56 - 28 * len(legend)
        f = sc._f(sc.MONO, 22)
        d.rectangle((lx - 22, ly - 18, lx + 420, ly + 28 * len(legend) + 10),
                    fill=(12, 12, 14, 214))
        for name, kind in legend:
            col = {"atk": ATK, "def": DEF, "pocket": POCKET,
                   "route": (226, 226, 230), "was": (150, 158, 170)}.get(kind, INK)
            if kind in ("was", "route"):
                for k2 in range(3):
                    d.rectangle((lx + k2 * 14, ly + 10, lx + k2 * 14 + 8, ly + 13),
                                fill=col + (255,))
            else:
                d.rectangle((lx, ly + 8, lx + 34, ly + 15), fill=col + (255,))
            d.text((lx + 50, ly), name, font=f, fill=(206, 206, 210, 255))
            ly += 28

    ep = _episode(episodes, t)
    if ep:
        e, age = ep
        a_ep = min(1.0, age / 0.4) * min(1.0, max(0.0, (float(e.get("hold", 5.0)) - age) / 0.5))
        f1 = sc._f(sc.F_HEAD, 46)
        txt = str(e.get("text", "")).upper()
        wd = sc.track_w(txt, f1, 3)
        y_ep = 110 if (t is not None and t > 6.6) else 192
        bx = (sc.MARGIN_L - 20, y_ep - 10, sc.MARGIN_L + wd + 24, y_ep + 56)
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.rectangle(bx, fill=(16, 14, 14, int(220 * a_ep)))
        ld.rectangle((bx[0], bx[1], bx[0] + 6, bx[3]), fill=ATK + (int(255 * a_ep),))
        sc.track(ld, (sc.MARGIN_L, y_ep), txt, f1, INK + (int(255 * a_ep),), 3)
        im = Image.alpha_composite(im.convert("RGBA"), lay).convert("RGB")
        d = ImageDraw.Draw(im, "RGBA")

    if note:
        f = sc._f(sc.MONO, 26)
        d.rectangle((sc.MARGIN_L - 18, H - 158, sc.MARGIN_L + f.getlength(note) + 18,
                     H - 116), fill=(12, 12, 14, 200))
        d.text((sc.MARGIN_L, H - 152), note, font=f, fill=sc.GOLD + (255,))
    if disclaimer:
        f = sc._f(sc.MONO, 20)
        d.text((sc.MARGIN_L, H - 108), disclaimer, font=f, fill=(142, 142, 148, 255))
    sc.footer(d, source, watermark)

    if out:
        im.save(out, quality=94)
    return im


def _cli():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2]
    dur = float(cfg.pop("dur", 12.0))
    anim = cfg.pop("anim", None)
    if out.lower().endswith((".png", ".jpg", ".jpeg")):
        frontline(out, **cfg)
        print("ok ->", out)
        return
    frontline(out.rsplit(".", 1)[0] + ".jpg", **cfg)
    sc.render_anim(frontline, cfg, dur, out,
                   anim_seconds=float(anim) if anim else None, sfx_out=True)
    print("ok ->", out)


if __name__ == "__main__":
    _cli()
