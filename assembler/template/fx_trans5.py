#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ШЕСТЬ ПРИЁМОВ КАНАЛА «5 МИНУТ» ПО ЕГО ОБРАЗЦУ 06.11.

Образец — `D:\\ЗАГРУЗКИ\\5 минут-ЭФФЕКТЫ\\5 минут-ЭФФЕКТЫ.mp4` (23,9 с, 4K).
Разобран по кадрам: шесть различимых приёмов, ни один не повторяет то, что
уже принято на ПЛАНЕТЕ (`fx_trans.py`: мозаика-монитор, панели, вайп,
глубина, разрыв, засвет).

  player   (14,4-19,2 с образца) — окна старого медиаплеера: серая панель,
           синяя полоса заголовка, меню, кнопки внизу. Три окна влетают под
           наклоном поверх прошлого кадра, последнее раскрывается в новый.
  curl     (20,8-23,6) — снимок с белой рамкой разворачивается из скрученного
           листа на стене из таких же снимков и растёт на весь экран.
  slides   (8,4-11,2) — лента слайдов: карточки со скруглённой белой рамкой
           идут из глубины одна за другой, последняя раскрывается в кадр.
  stamps   (4,8-7,2) — стена марок: кадр разложен на плитки с зубчатым краем
           на бежевой подложке, марки прошлого кадра сменяются новыми.
  torn     (12,8-15,2) — вырванный клок: новый кадр приходит обрывком бумаги
           с волокнистой кромкой на чёрном и разворачивается во весь экран.
  filmwin  (0,8-1,6) — окошки плёнки: рамки 35 мм с перфорацией и кропами
           нового кадра летят поверх прошлого, по краям розовый засвет.

ЗАМОК КАНАЛА: все шесть — ТОЛЬКО «5 МИНУТ» (его слово 06.11: «это пойдёт на
канал 5 минут, только на канал 5 минут»). Приёмы ПЛАНЕТЫ сюда не лезут и
наоборот — замок стоит и здесь, и в `fx_put.py`.

ПОЧЕМУ ОТДЕЛЬНЫЙ ФАЙЛ, А НЕ ВИДЫ ВНУТРИ `fx_trans.py`: там шесть принятых
приёмов, а принятое приравнено к сданному и регрессий быть не должно. Общие
кирпичи (вписать кадр, покадровый зум, сглаживание, перспектива) берутся
оттуда импортом — дублей кода нет.

    python3 fx_trans5.py <кадр прошлой сцены|-> <кадр своей сцены> <out.mp4> \\
        --kind player|curl|slides|stamps|torn|filmwin --seconds 11.5 \\
        [--trans 1.6] [--channel "5 МИНУТ"]
"""
import argparse
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fx_trans import (W, H, FPS, _cover, _zoom_frame, _smootherstep,  # noqa
                      _persp_coeffs, _workers)

KINDS = ("player", "curl", "slides", "stamps", "torn", "filmwin")
# Длительность самого приёма. Мерено по образцу и округлено так, чтобы на
# превью 480 px движение успевало прочитаться (его правило 05.11).
TRANS_SEC = {"player": 1.8, "curl": 1.6, "slides": 1.5,
             "stamps": 1.6, "torn": 1.4, "filmwin": 1.5}
CHANNEL = "5 МИНУТ"

STAMP_COLS, STAMP_ROWS = 7, 4
PAPER = (223, 216, 201)          # бежевая подложка стены марок
WIN_FACE = (236, 233, 216)       # панель окна плеера
WIN_EDGE = (128, 128, 128)


def _chan_norm(c):
    return (c or "").strip().upper().replace("Ё", "Е")


# ----------------------------------------------------------- общие кирпичи
def _font(size):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _lerp(a, b, t):
    return a + (b - a) * t


def _quad(cx, cy, w, h, tilt=0.0, rot=0.0):
    """Четырёхугольник карточки: центр, размер, наклон в глубину и поворот.

    tilt > 0 — правая кромка выше и короче (уходит от нас), как в образце.
    """
    hw, hh = w / 2.0, h / 2.0
    kl, kr = 1.0 + tilt, 1.0 - tilt
    pts = [(-hw, -hh * kl), (hw, -hh * kr), (hw, hh * kr), (-hw, hh * kl)]
    if abs(rot) > 1e-4:
        ca, sa = math.cos(rot), math.sin(rot)
        pts = [(x * ca - y * sa, x * sa + y * ca) for x, y in pts]
    return [(cx + x, cy + y) for x, y in pts]


def _place(out, card, quad, shadow=0.0):
    """Положить карточку (RGBA) в произвольный четырёхугольник экрана."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    bx0 = max(int(math.floor(min(xs))), -W)
    by0 = max(int(math.floor(min(ys))), -H)
    bx1 = min(int(math.ceil(max(xs))), 2 * W)
    by1 = min(int(math.ceil(max(ys))), 2 * H)
    bw, bh = bx1 - bx0, by1 - by0
    if bw < 6 or bh < 6:
        return
    dst = [(x - bx0, y - by0) for x, y in quad]
    src = [(0, 0), (card.width, 0), (card.width, card.height),
           (0, card.height)]
    co = _persp_coeffs(dst, src)
    if not co:
        return
    card = card.convert("RGBA")
    piece = card.transform((bw, bh), Image.PERSPECTIVE, co, Image.BICUBIC)
    poly = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(poly).polygon([(int(x), int(y)) for x, y in dst], fill=255)
    mask = ImageChops.multiply(piece.split()[3], poly)
    if shadow > 0.01:
        sh = mask.filter(ImageFilter.GaussianBlur(16))
        sh = sh.point(lambda v: int(v * shadow))
        out.paste(Image.new("RGB", (bw, bh), (0, 0, 0)),
                  (bx0 + 12, by0 + 16), sh)
    out.paste(piece.convert("RGB"), (bx0, by0), mask)


def _rounded(img, radius, border, color=(255, 255, 255)):
    """Кадр в скруглённой рамке: возвращает RGBA с прозрачными углами."""
    from PIL import Image, ImageDraw
    w = img.width + border * 2
    h = img.height + border * 2
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius,
                                        fill=255)
    face = Image.new("RGBA", (w, h), color + (255,))
    face.paste(img.convert("RGB"), (border, border))
    card.paste(face, (0, 0), m)
    return card


def _shrink(base, k, bg=(0, 0, 0)):  # noqa: D401
    """Кадр отъезжает в глубину: уменьшённая копия по центру тёмного поля.
    `_zoom_frame` на это не годится — при z < 1 он просит отрицательный box.
    """
    from PIL import Image
    k = max(0.05, min(1.0, k))
    if k > 0.999:
        return base.copy()
    w, h = max(2, int(W * k)), max(2, int(H * k))
    out = Image.new("RGB", (W, H), bg)
    out.paste(base.resize((w, h), Image.BICUBIC), ((W - w) // 2, (H - h) // 2))
    return out


def _out_blend(im, B, p, start):
    """Хвост приёма: чистый выход в новый кадр, без щелчка."""
    from PIL import Image
    if p <= start:
        return im
    q = _smootherstep((p - start) / max(0.02, 1.0 - start))
    return Image.blend(im, B, q)


# ------------------------------------------------------------ окна плеера
def _player_card(img, w=1120, h=700):
    """Окно старого медиаплеера: заголовок, меню, кадр, панель кнопок."""
    from PIL import Image, ImageDraw
    card = Image.new("RGBA", (w, h), WIN_FACE + (255,))
    d = ImageDraw.Draw(card)
    bar = 34
    # синяя полоса заголовка с градиентом, как в образце
    for x in range(w):
        t = x / float(w - 1)
        d.line([(x, 0), (x, bar)],
               fill=(int(_lerp(10, 120, t)), int(_lerp(36, 170, t)),
                     int(_lerp(106, 215, t))))
    f = _font(17)
    d.text((10, 8), "Media Player", font=f, fill=(255, 255, 255))
    for i, cap in enumerate(("File", "View", "Play", "Tools", "Help")):
        d.text((12 + i * 62, bar + 8), cap, font=_font(15), fill=(40, 40, 40))
    # три кнопки окна справа
    for i in range(3):
        x = w - 28 - i * 26
        d.rectangle([x, 6, x + 20, bar - 6], fill=(214, 211, 194),
                    outline=(90, 90, 90))
    top = bar + 32
    pad = 10
    foot = 56
    iw, ih = w - pad * 2, h - top - foot - pad
    d.rectangle([pad - 2, top - 2, pad + iw + 1, top + ih + 1],
                fill=(0, 0, 0))
    card.paste(_cover(img, iw, ih), (pad, top))
    # панель кнопок: play, stop, две «лампочки»
    fy = top + ih + 8
    d.rectangle([pad, fy, w - pad, h - 10], fill=(214, 211, 194),
                outline=WIN_EDGE)
    bx = pad + 26
    d.polygon([(bx, fy + 14), (bx, fy + 32), (bx + 16, fy + 23)],
              fill=(40, 40, 40))
    d.rectangle([bx + 40, fy + 14, bx + 56, fy + 30], fill=(40, 40, 40))
    d.rectangle([bx + 78, fy + 14, bx + 94, fy + 30], fill=(70, 70, 70))
    d.rectangle([0, 0, w - 1, h - 1], outline=WIN_EDGE, width=3)
    return card


def _player_frame(p, st):
    from PIL import Image
    out = st["bgd"].copy()
    t = _smootherstep(p)
    # три окна: своя задержка, свой прилёт из-за края, свой наклон
    # РАНЬШЕ И КРУПНЕЕ (правка по листу превью 06.11): при lag 0,16/0,30 и
    # масштабах 0,52/0,44 первые две трети приёма экран стоял пустым, а окна
    # на превью 480 px читались спичечными коробками. Его правило: движение
    # должно читаться на миниатюре.
    plan = ((0.00, (-0.16, 0.40), (0.27, 0.40), 0.16, -0.10, 0.70),
            (0.08, (1.18, 0.28), (0.74, 0.30), 0.10, 0.12, 0.60),
            (0.18, (0.50, 1.28), (0.52, 0.60), -0.12, 0.06, 1.05))
    for lag, (sx, sy), (ex, ey), tilt, rot, scale in plan:
        q = _smootherstep(max(0.0, (p - lag)) / max(0.05, 1.0 - lag))
        if q <= 0.002:
            continue
        cx = _lerp(sx, ex, q) * W
        cy = _lerp(sy, ey, q) * H
        k = scale * _lerp(0.72, 1.0, q)
        card = st["card"]
        cw, ch = card.width * k, card.height * k
        _place(out, card, _quad(cx, cy, cw, ch, tilt * (1.0 - 0.25 * q),
                                rot * (1.0 - q * 0.5)), shadow=0.45)
    # последнее окно раскрывается в чистый кадр
    return _out_blend(out, st["B"], p, 0.80)


# --------------------------------------------------- снимок с загибом
def _wall(A, seed):
    """Стена из тёмных снимков — фон приёма `curl`, считается один раз."""
    from PIL import Image, ImageDraw, ImageEnhance
    rnd = random.Random(seed)
    wall = Image.new("RGB", (W, H), (10, 10, 12))
    small = ImageEnhance.Color(_cover(A, 300, 180)).enhance(0.10)
    small = ImageEnhance.Brightness(small).enhance(0.38)
    cell = _rounded(small, 4, 10, color=(205, 205, 205))
    cell = ImageEnhance.Brightness(cell.convert("RGB")).enhance(0.55)
    cell = cell.convert("RGBA")
    d = ImageDraw.Draw(wall)
    for r in range(-1, 6):
        for c in range(-1, 7):
            x = c * 340 + (r % 2) * 60 + rnd.randint(-14, 14)
            y = r * 230 + rnd.randint(-12, 12)
            _place(wall, cell, _quad(x, y, cell.width, cell.height,
                                     0.06, -0.06))
    d.rectangle([0, 0, W, H], fill=None)
    return wall


def _curl_frame(p, st):
    from PIL import Image, ImageDraw
    out = st["wall"].copy()
    t = _smootherstep(p)
    photo = st["card"]
    # лист разворачивается: видна доля ширины, справа — светлая дуга загиба
    open_k = _smootherstep(min(1.0, p / 0.55))
    vis = _lerp(0.34, 1.0, open_k)
    scale = _lerp(0.34, 1.12, t)
    rot = math.radians(_lerp(-9.0, 0.0, t))
    cw, ch = photo.width * scale, photo.height * scale
    part = photo.crop((0, 0, max(8, int(photo.width * vis)), photo.height))
    pw = cw * vis
    cx = W / 2.0 - (cw - pw) / 2.0 * 0.35
    cy = H / 2.0
    _place(out, part, _quad(cx, cy, pw, ch, 0.05 * (1.0 - t), rot),
           shadow=0.55)
    if vis < 0.985:
        # сам загиб: светлый серп на правой кромке, ширина падает с раскрытием
        band = Image.new("RGBA", (220, max(8, int(photo.height))),
                         (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        for x in range(band.width):
            q = x / float(band.width - 1)
            v = int(255 - 150 * q * q)
            bd.line([(x, 0), (x, band.height)], fill=(v, v, v, 255))
        bw = max(10.0, 190 * scale * (1.0 - open_k) + 26 * scale)
        bx = cx + pw / 2.0 + bw / 2.0 - 4
        _place(out, band, _quad(bx, cy, bw, ch * 0.96, 0.22, rot), shadow=0.3)
    return _out_blend(out, st["B"], p, 0.82)


# ------------------------------------------------------- лента слайдов
def _slides_frame(p, st):
    """ФОН — НЕ ЧЁРНОЕ ПОЛЕ, А ПРОШЛЫЙ КАДР, УХОДЯЩИЙ В ГЛУБИНУ. Первая
    версия начинала с чистого чёрного: на прогоне в памяти кадры p=0 и
    p=0.17 дали контраст 0 — то есть 0,3 с пустоты между сценами, ровно то
    мигание, за которое уже чинили мозаику 05.11."""
    from PIL import Image
    t = _smootherstep(p)
    if st.get("A") is not None:
        out = _shrink(st["Ad"], 1.0 - 0.45 * t, bg=st.get("Abg", (0, 0, 0)))
    else:
        out = Image.new("RGB", (W, H), (0, 0, 0))
    card = st["card"]
    plan = ((0.00, 0.40, 1.02), (0.10, 0.34, 0.78), (0.20, 0.30, 0.56))
    for lag, s0, s1 in reversed(plan):
        q = _smootherstep(max(0.0, (p - lag)) / max(0.05, 0.80 - lag))
        if q <= 0.002:
            continue
        k = _lerp(s0, s1, q)
        cx = _lerp(1.16, 0.52, q) * W
        cy = _lerp(0.58, 0.50, q) * H
        _place(out, card, _quad(cx, cy, card.width * k, card.height * k,
                                _lerp(0.26, 0.09, q), math.radians(-3 * (1 - q))),
               shadow=0.5)
    return _out_blend(out, st["B"], p, 0.84)


# ---------------------------------------------------------- стена марок
def _stamp_mask(w, h, seed):
    """Маска марки: прямоугольник с полукруглыми вырезами по периметру."""
    from PIL import Image, ImageDraw
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    r = 9
    d.rectangle([r, r, w - r - 1, h - r - 1], fill=255)
    d.rectangle([0, r, w - 1, h - r - 1], fill=255)
    d.rectangle([r, 0, w - r - 1, h - 1], fill=255)
    step = 26
    for x in range(step // 2, w, step):
        d.ellipse([x - r, -r, x + r, r], fill=0)
        d.ellipse([x - r, h - r, x + r, h + r], fill=0)
    for y in range(step // 2, h, step):
        d.ellipse([-r, y - r, r, y + r], fill=0)
        d.ellipse([w - r, y - r, w + r, y + r], fill=0)
    return m


def _stamps_frame(p, st):
    from PIL import Image, ImageDraw
    n = STAMP_COLS * STAMP_ROWS
    cw, ch = W / float(STAMP_COLS), H / float(STAMP_ROWS)
    out = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(out)
    gone = int(_smootherstep(min(1.0, p / 0.40)) * n)
    lit = int(_smootherstep(max(0.0, (p - 0.10) / 0.62)) * n)
    mask = st["smask"]
    gap = 7
    for idx in range(n):
        r, c = divmod(idx, STAMP_COLS)
        x0, y0 = int(c * cw) + gap, int(r * ch) + gap
        box = (int(c * cw), int(r * ch), int((c + 1) * cw), int((r + 1) * ch))
        src = None
        if st["oi"][idx] < lit:
            src = st["B"] if idx not in st["blank"] else None
            if src is None:
                # «пустая» марка: серое поле с полоской, как в образце
                tile = Image.new("RGB", (mask.width, mask.height),
                                 (168, 170, 178))
                td = ImageDraw.Draw(tile)
                td.rectangle([int(mask.width * 0.28), int(mask.height * 0.52),
                              int(mask.width * 0.72), int(mask.height * 0.60)],
                             fill=(206, 208, 214))
                out.paste(tile, (x0, y0), mask)
                continue
        elif st["A"] is not None and st["oo"][idx] >= gone:
            src = st["A"]
        if src is None:
            continue
        tile = src.crop(box).resize((mask.width, mask.height))
        out.paste(tile, (x0, y0), mask)
    return _out_blend(out, st["B"], p, 0.78)


# ------------------------------------------------------- вырванный клок
def _torn_card(img, seed):
    """Кадр обрывком бумаги: рваный контур, белая кромка, царапины."""
    from PIL import Image, ImageDraw, ImageFilter
    rnd = random.Random(seed)
    w, h = 1500, 860
    pad = 34
    pts = []

    def edge(x0, y0, x1, y1, amp):
        n = max(6, int(math.hypot(x1 - x0, y1 - y0) / 38))
        for i in range(n):
            t = i / float(n)
            x = _lerp(x0, x1, t) + rnd.uniform(-amp, amp)
            y = _lerp(y0, y1, t) + rnd.uniform(-amp, amp)
            pts.append((x, y))

    edge(pad, pad, w - pad, pad, 16)
    edge(w - pad, pad, w - pad, h - pad, 20)
    edge(w - pad, h - pad, pad, h - pad, 16)
    edge(pad, h - pad, pad, pad, 20)
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    # белая волокнистая кромка — контур, размытый и подрезанный той же маской
    edge_m = m.filter(ImageFilter.MaxFilter(9))
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    paper = Image.new("RGB", (w, h), (238, 235, 228))
    card.paste(paper, (0, 0), edge_m)
    inner = m.filter(ImageFilter.MinFilter(9))
    card.paste(_cover(img, w, h), (0, 0), inner)
    # царапины и пятна на бумаге
    d = ImageDraw.Draw(card)
    for _ in range(14):
        x = rnd.randint(0, w)
        y = rnd.randint(0, h)
        d.line([(x, y), (x + rnd.randint(-120, 120), y + rnd.randint(-40, 40))],
               fill=(255, 255, 255, rnd.randint(14, 34)),
               width=rnd.choice((1, 1, 2)))
    return card


def _torn_frame(p, st):
    """Клок ложится на ПРИТЕМНЁННЫЙ прошлый кадр, а не на пустоту — чтобы в
    паузе читался обрывок поверх картинки, а не чёрный экран с бумажкой."""
    from PIL import Image
    t = _smootherstep(p)
    if st.get("A") is not None:
        out = _zoom_frame(st["Ad"], W, H, 1.0 + 0.06 * t)
    else:
        out = Image.new("RGB", (W, H), (0, 0, 0))
    k = _lerp(0.52, 1.30, t)
    card = st["card"]
    rot = math.radians(_lerp(-4.5, 0.0, t))
    _place(out, card, _quad(W / 2.0, H / 2.0, card.width * k * 0.86,
                            card.height * k * 0.86, 0.04 * (1 - t), rot),
           shadow=0.6)
    return _out_blend(out, st["B"], p, 0.80)


# -------------------------------------------------------- окошки плёнки
def _film_card(img, w=760, h=470, crop=None):
    """Рамка 35 мм: чёрное поле, перфорация сверху и снизу, кадр внутри."""
    from PIL import Image, ImageDraw
    card = Image.new("RGBA", (w, h), (16, 16, 18, 255))
    d = ImageDraw.Draw(card)
    perf = 30
    src = img if crop is None else img.crop(crop)
    card.paste(_cover(src, w - 24, h - perf * 2 - 16), (12, perf + 8))
    for x in range(12, w - 20, 36):
        d.rounded_rectangle([x, 7, x + 20, perf - 6], radius=3,
                            fill=(238, 238, 238))
        d.rounded_rectangle([x, h - perf + 6, x + 20, h - 8], radius=3,
                            fill=(238, 238, 238))
    d.rectangle([0, 0, w - 1, h - 1], outline=(40, 40, 44), width=2)
    return card


def _filmwin_frame(p, st):
    from PIL import Image
    out = st["bgd"].copy()
    # ЗАСВЕТ ТОЛЬКО ПО КРАЯМ. Первая версия мешала розовый слой со ВСЕМ
    # кадром (`Image.blend`) — на листе превью это читалось не как засвет
    # плёнки, а как сбитый цвет всего кадра, то есть ровно тот «брак
    # картинки на стоп-кадре», который у нас запрещён.
    k = 0.14 + 0.20 * math.sin(math.pi * p)
    out.paste(st["pink"], (0, 0), st["glowmask"].point(lambda v: int(v * k)))
    plan = ((0.00, (-0.08, 0.22), (0.27, 0.26), 0.62, -0.13),
            (0.10, (1.12, 0.74), (0.73, 0.70), 0.54, 0.10),
            (0.20, (0.50, 1.22), (0.52, 0.50), 1.12, 0.04))
    for i, (lag, (sx, sy), (ex, ey), scale, rot) in enumerate(plan):
        q = _smootherstep(max(0.0, (p - lag)) / max(0.05, 1.0 - lag))
        if q <= 0.002:
            continue
        card = st["cards"][i]
        k = scale * _lerp(0.80, 1.0, q)
        _place(out, card, _quad(_lerp(sx, ex, q) * W, _lerp(sy, ey, q) * H,
                                card.width * k, card.height * k,
                                0.12 * (1 - q), rot * (1.0 - 0.4 * q)),
               shadow=0.5)
    return _out_blend(out, st["B"], p, 0.82)


# ------------------------------------------------------------------ сборка
_ST = {}


def _init(state):
    _ST.update(state)


def _frame(kind, p, st):
    if kind == "player":
        return _player_frame(p, st)
    if kind == "curl":
        return _curl_frame(p, st)
    if kind == "slides":
        return _slides_frame(p, st)
    if kind == "stamps":
        return _stamps_frame(p, st)
    if kind == "torn":
        return _torn_frame(p, st)
    return _filmwin_frame(p, st)


def _one(arg):
    i, total, tf, kind, zoom, out_dir = arg
    if i < tf:
        im = _frame(kind, i / float(max(1, tf - 1)), _ST)
    else:
        q = (i - tf) / float(max(1, total - tf - 1))
        im = _zoom_frame(_ST["base"], W, H, 1.0 + zoom * _smootherstep(q))
    im.save(os.path.join(out_dir, "f_%05d.jpg" % i), quality=95)
    return i


def prepare(kind, A, B, seed=20261106):
    """Всё тяжёлое — ОДИН раз на переход, а не на каждый кадр."""
    from PIL import Image, ImageEnhance, ImageFilter
    st = {"A": A, "B": B}
    rnd = random.Random(seed)
    if kind in ("player", "filmwin"):
        src = A if A is not None else B
        bg = _zoom_frame(_cover(src, W, H, headroom=1.18), W, H, 1.06)
        st["bgd"] = ImageEnhance.Brightness(
            bg.filter(ImageFilter.GaussianBlur(5))).enhance(0.62)
    if kind == "player":
        st["card"] = _player_card(B)
    elif kind == "curl":
        st["wall"] = _wall(A if A is not None else B, seed)
        st["card"] = _rounded(_cover(B, 1280, 720), 6, 46)
    elif kind == "slides":
        st["card"] = _rounded(_cover(B, 1280, 720), 56, 26)
    elif kind == "stamps":
        cw = int(W / float(STAMP_COLS)) - 14
        ch = int(H / float(STAMP_ROWS)) - 14
        st["smask"] = _stamp_mask(cw, ch, seed)
        n = STAMP_COLS * STAMP_ROWS
        oo = list(range(n)); rnd.shuffle(oo)
        oi = list(range(n)); rnd.shuffle(oi)
        st["oo"], st["oi"] = oo, oi
        st["blank"] = set(rnd.sample(range(n), max(2, n // 8)))
    elif kind == "torn":
        st["card"] = _torn_card(B, seed)
    if kind in ("slides", "torn") and A is not None:
        st["Ad"] = ImageEnhance.Brightness(
            A.filter(ImageFilter.GaussianBlur(4))).enhance(0.30)
        px = st["Ad"].resize((1, 1)).getpixel((0, 0))
        st["Abg"] = tuple(max(0, int(v * 0.5)) for v in px)
    elif kind == "filmwin":
        bw, bh = B.width, B.height
        crops = (None,
                 (int(bw * 0.18), int(bh * 0.05), int(bw * 0.62), int(bh * 0.55)),
                 (int(bw * 0.30), int(bh * 0.25), int(bw * 0.95), int(bh * 0.95)))
        st["cards"] = [_film_card(B, crop=c) for c in crops]
        from PIL import ImageDraw
        gm = Image.new("L", (W, H), 0)
        gd = ImageDraw.Draw(gm)
        for x in range(0, W, 2):
            t = min(x / (W * 0.16), (W - x) / (W * 0.16), 1.0)
            gd.line([(x, 0), (x, H)], fill=int(235 * max(0.0, 1.0 - t) ** 1.4))
        st["glowmask"] = gm.filter(ImageFilter.GaussianBlur(26))
        st["pink"] = Image.new("RGB", (W, H), (222, 46, 126))
    return st


def render_frames(prev_img, img, out_dir, kind, seconds, trans, zoom=0.10):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    B = _cover(Image.open(img).convert("RGB"), W, H)
    A = _cover(Image.open(prev_img).convert("RGB"), W, H) if prev_img else None
    st = prepare(kind, A, B)
    st["base"] = _cover(Image.open(img).convert("RGB"), W, H, headroom=1.12)
    total = int(round(seconds * FPS))
    tf = min(total - 2, int(round(trans * FPS)))
    args = [(i, total, tf, kind, zoom, out_dir) for i in range(total)]
    nw = min(_workers(), 8)
    if nw > 1 and total > 30:
        import multiprocessing as mp
        try:
            with mp.get_context("fork").Pool(nw, _init, (st,)) as pool:
                for _ in pool.imap_unordered(_one, args, chunksize=6):
                    pass
            return total, tf
        except Exception as e:
            print("  кадры в один поток (%s)" % e, file=sys.stderr)
    _init(st)
    for a in args:
        _one(a)
    return total, tf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prev", help="кадр прошлой сцены (или '-' если его нет)")
    ap.add_argument("img", help="кадр своей сцены")
    ap.add_argument("out")
    ap.add_argument("--kind", default="player", choices=KINDS)
    ap.add_argument("--seconds", type=float, default=11.5)
    ap.add_argument("--trans", type=float, default=0.0)
    ap.add_argument("--zoom", type=float, default=0.10)
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()

    if _chan_norm(a.channel) != _chan_norm(CHANNEL):
        print("!! ЭТИ ШЕСТЬ ПРИЁМОВ — ТОЛЬКО КАНАЛ «5 МИНУТ» (его слово "
              "06.11). Канал «%s» — не ставлю." % a.channel, file=sys.stderr)
        return 2
    prev = "" if a.prev in ("-", "") else a.prev
    if prev and not os.path.isfile(prev):
        prev = ""
    if not os.path.isfile(a.img):
        sys.exit("нет файла: %s" % a.img)
    trans = a.trans or TRANS_SEC[a.kind]
    if a.seconds < trans + 1.0:
        trans = max(0.4, a.seconds - 1.0)

    tmp = tempfile.mkdtemp(prefix="fx5_")
    try:
        total, tf = render_frames(prev, a.img, tmp, a.kind, a.seconds, trans,
                                  a.zoom)
        cmd = [a.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(FPS), "-i", os.path.join(tmp, "f_%05d.jpg"),
               "-an", "-t", "%.3f" % a.seconds,
               "-c:v", "libx264", "-preset", "veryfast",
               "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
               "-pix_fmt", "yuv420p", a.out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.isfile(a.out) \
            and os.path.getsize(a.out) > 0
        print(("готово: %s (приём «%s» %.1f с из %.1f с сцены)"
               % (a.out, a.kind, tf / float(FPS), a.seconds)) if ok
              else ("FAIL\n" + r.stderr[-700:]))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
