#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Примитивы студии «ОЛЬГА Дайджест», перенесённые один в один из
`~/olga-digest/engine/core.py` (27.11.2026, восемь O-карточек в news-video —
план в `effects-library/OPEN-ITEMS.md`). Те же имена и та же математика,
другой только путь к шрифтам: на облачном раннере `cards_cloud.py` копирует
весь код плоско в одну папку и шрифты в `<эта папка>/fonts/` — поэтому
`FONTS = os.path.join(HERE, "fonts")`, а не соседний `template/fonts`
(тот путь существует только локально и ломался уже на карточках «Верицы»,
см. комментарий в `verica_core.py`).
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080
FPS = 30
SS = 2

# палитра студии — ночной синий, белый, красный акцент (акцент переопределяется
# по каналу на уровне olga_cards._accent, здесь — исходные константы движка)
BG = (8, 13, 24)
BG2 = (14, 22, 38)
PANEL = (18, 28, 48)
PANEL2 = (26, 38, 62)
LINE = (46, 62, 92)
WHITE = (246, 247, 250)
GREY = (164, 172, 186)
GREY2 = (104, 112, 128)
RED = (214, 38, 44)
RED2 = (160, 26, 30)
BLUE = (64, 148, 255)
BLUE2 = (30, 90, 180)
GOLD = (236, 190, 60)

FONTS = os.path.join(HERE, "fonts")

_fc = {}


def font(kind, size):
    size = max(4, int(round(size)))
    k = (kind, size)
    if k in _fc:
        return _fc[k]
    if kind in ("head", "head_r", "head_l", "head_m"):
        f = ImageFont.truetype(os.path.join(FONTS, "Oswald-VF.ttf"), size)
        try:
            f.set_variation_by_name({"head": "Bold", "head_r": "Regular",
                                      "head_l": "Light", "head_m": "Medium"}[kind])
        except Exception:
            pass
    else:
        f = ImageFont.truetype(os.path.join(FONTS, "Oswald-Bold.ttf"), size)
    _fc[k] = f
    return f


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def smoother(x):
    x = clamp(x)
    return x * x * x * (x * (x * 6 - 15) + 10)


def out_expo(t):
    t = clamp(t)
    return 1.0 if t >= 1.0 else 1 - math.pow(2, -10 * t)


def out_back(t, s=1.4):
    t = clamp(t) - 1
    return 1 + t * t * ((s + 1) * t + s)


def out_cubic(t):
    t = clamp(t) - 1
    return 1 + t * t * t


def seg(t, a, b):
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp((t - a) / (b - a))


def mix(c1, c2, t):
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1, c2))


def layer(w=W, h=H):
    return Image.new("RGBA", (int(w * SS), int(h * SS)), (0, 0, 0, 0))


def layer1(w=W, h=H):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def done(im, w=W, h=H):
    if im.size == (w, h):
        return im
    if im.size == (w * SS, h * SS) and im.mode == "RGBA":
        bb = im.getbbox()
        if bb is None:
            return Image.new("RGBA", (w, h), (0, 0, 0, 0))
        x0, y0, x1, y1 = bb
        x0, y0 = (x0 // SS) * SS, (y0 // SS) * SS
        x1, y1 = min(w * SS, ((x1 + SS - 1) // SS) * SS), min(h * SS, ((y1 + SS - 1) // SS) * SS)
        part = im.crop((x0, y0, x1, y1)).reduce(SS)
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(part, (x0 // SS, y0 // SS))
        return out
    return im.resize((w, h), Image.LANCZOS)


def over(base, *layers):
    base = base.convert("RGBA")
    for L in layers:
        if L is None:
            continue
        if L.size != base.size:
            L = L.resize(base.size, Image.LANCZOS)
        bb = L.getbbox()
        if bb is None:
            continue
        if bb[0] > 0 or bb[1] > 0 or bb[2] < L.size[0] or bb[3] < L.size[1]:
            part = L.crop(bb)
            sub = base.crop(bb)
            base.paste(Image.alpha_composite(sub, part), bb[:2])
        else:
            base = Image.alpha_composite(base, L)
    return base


def alpha(im, a):
    if a >= 1.0:
        return im
    if a <= 0.0:
        return None
    im = im.copy()
    ch = im.split()[3].point(lambda v: int(v * a))
    im.putalpha(ch)
    return im


def text_w(d, text, fnt, track=0.0):
    if track == 0.0:
        return d.textlength(text, font=fnt)
    return sum(d.textlength(ch, font=fnt) + fnt.size * track for ch in text) - fnt.size * track


def tracked(d, x, y, text, fnt, fill, track=0.0, anchor="ls"):
    w = text_w(d, text, fnt, track)
    if anchor[0] == "m":
        x -= w / 2
    elif anchor[0] == "r":
        x -= w
    if track == 0.0:
        d.text((x, y), text, font=fnt, fill=fill, anchor="ls")
        return w
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill, anchor="ls")
        x += d.textlength(ch, font=fnt) + fnt.size * track
    return w


def wrap(text, kind, px, maxw):
    f = font(kind, px * SS)
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    lines, cur = [], ""
    for wd in text.split():
        probe = (cur + " " + wd).strip()
        if d.textlength(probe, font=f) / SS <= maxw or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def fit_px(text, kind, px, maxw, track=0.0):
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    while px > 10:
        if text_w(d, text, font(kind, px * SS), track) / SS <= maxw:
            return px
        px -= 2
    return px


def shadow(size, blur=28, a=150, r=0):
    w, h = size
    pad = blur * 2
    im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([pad, pad, pad + w, pad + h], radius=r, fill=(0, 0, 0, a))
    return im.filter(ImageFilter.GaussianBlur(blur)), pad


def fade(img, k):
    if k >= 1.0:
        return img
    return Image.eval(img.convert("RGB"), lambda v: int(v * max(0.0, k)))


_bg_cache = {}


def studio_bg(t=0.0, tone=0.0):
    """ночной фон студии: градиент + дышащее световое пятно + тонкая сетка —
    тот же фон, на котором само движко Ольги строит одиночные HUD-сцены без
    реального видео (сверено в `scenes.py`: `S.big_number(...)` и
    `S.title_card(...)` кладутся прямо на `C.studio_bg(t, tone)`)."""
    key = (int(t * 2) % 40, round(tone, 1))
    if key in _bg_cache:
        return _bg_cache[key].copy()
    ys = np.linspace(0, 1, H)[:, None]
    xs = np.linspace(0, 1, W)[None, :]
    base = np.array(BG, np.float32)[None, None, :]
    top = np.array(BG2, np.float32)[None, None, :]
    g = np.broadcast_to(base + (top - base) * (1 - ys)[:, :, None] * 0.9, (H, 1, 3))
    g = np.repeat(g, W, axis=1).astype(np.float32)
    cx, cy = 0.28 + 0.03 * math.sin(t * 0.25), 0.22
    rr = (xs - cx) ** 2 * 1.4 + (ys - cy) ** 2
    spot = np.exp(-rr * 4.5) * (26 + 6 * tone)
    g = g + spot[:, :, None] * np.array([0.6, 0.8, 1.2], np.float32)[None, None, :]
    vr = ((xs - 0.5) ** 2 * 1.2 + (ys - 0.5) ** 2) * 0.9
    g = g * (1 - vr * 0.55)[:, :, None]
    im = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    grid = layer1()
    d = ImageDraw.Draw(grid)
    for x in range(0, W, 96):
        d.line([x, 0, x, H], fill=(255, 255, 255, 5))
    for y in range(0, H, 96):
        d.line([0, y, W, y], fill=(255, 255, 255, 5))
    im = Image.alpha_composite(im, grid)
    _bg_cache[key] = im
    return im.copy()
