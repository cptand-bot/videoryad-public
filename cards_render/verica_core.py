# -*- coding: utf-8 -*-
"""ОБЩАЯ ТЕХНИКА ИЗ ДВИЖКА «ВЕРИЦЫ» (27.11.2026, второй заход).

Первый заход (verica_cards.py v1) перенёс только голую геометрию и
получил справедливое «убожество после фабла» — плоские фигуры без
света, без текстуры, без наплыва. Это тот кусок `~/kino-verica/engine/
core.py` и `fx.py`, которого не хватало: тень от лампы, бумага, зерно
плёнки, виньетка, наплыв по краям. Перенесено один в один (переведены
только имена на латиницу), кроме того, что требует звукового файла или
содержания конкретного фильма.
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
SS = 2
_fc = {}
_grain_cache = {}
_vig = {}


def font(path, size):
    size = max(4, int(round(size)))
    k = (path, size)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(path, size)
    return _fc[k]


def clamp(x, a=0.0, b=1.0):
    return a if x < a else (b if x > b else x)


def lerp(a, b, t):
    return a + (b - a) * t


def smoother(x):
    x = clamp(x)
    return x * x * x * (x * (x * 6 - 15) + 10)


def out_expo(t):
    t = clamp(t)
    return 1.0 if t >= 1 else 1 - pow(2, -10 * t)


def out_back(t, s=1.4):
    t = clamp(t)
    return 1 + (s + 1) * pow(t - 1, 3) + s * pow(t - 1, 2)


def out_cubic(t):
    t = clamp(t)
    return 1 - pow(1 - t, 3)


def seg(t, a, b):
    return clamp((t - a) / max(1e-6, b - a))


def mix(c1, c2, t):
    return tuple(int(round(lerp(c1[i], c2[i], clamp(t)))) for i in range(3))


def layer(w=W, h=H):
    return Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))


def done(im, w=W, h=H):
    return im.resize((w, h), Image.LANCZOS)


def over(base, *layers):
    out = base.convert("RGBA") if base.mode != "RGBA" else base
    for lay in layers:
        if lay is None:
            continue
        if lay.size != out.size:
            lay = lay.resize(out.size, Image.LANCZOS)
        out = Image.alpha_composite(out, lay)
    return out


def alpha(im, a):
    a = clamp(a)
    if a >= 1.0:
        return im
    r, g, b, al = im.split()
    al = al.point(lambda v: int(v * a))
    return Image.merge("RGBA", (r, g, b, al))


def text_w(d, text, fnt, track=0.0):
    return sum(d.textlength(ch, font=fnt) for ch in text) + \
        track * fnt.size * max(0, len(text) - 1)


def tracked(d, x, y, text, fnt, fill, track=0.0, anchor="ls"):
    tw = text_w(d, text, fnt, track)
    if anchor[0] == "m":
        x -= tw / 2
    elif anchor[0] == "r":
        x -= tw
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill, anchor="ls")
        x += d.textlength(ch, font=fnt) + track * fnt.size
    return tw


def wrap(text, fnt_path, px, maxw, track=0.0):
    f = font(fnt_path, px * SS)
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    out, cur = [], ""
    for w_ in (text or "").split():
        probe = (cur + " " + w_).strip()
        if text_w(d, probe, f, track) / SS <= maxw or not cur:
            cur = probe
        else:
            out.append(cur)
            cur = w_
    if cur:
        out.append(cur)
    return out


# ── фактуры (core.py: noise/paper/grain/vignette) ──────────────────────
def noise(w, h, seed=1, scale=1.0):
    rng = np.random.default_rng(seed)
    sw, sh = max(2, int(w / scale)), max(2, int(h / scale))
    n = rng.random((sh, sw)).astype(np.float32)
    im = Image.fromarray((n * 255).astype(np.uint8), "L")
    if scale != 1.0:
        im = im.resize((w, h), Image.BILINEAR)
    return im


def paper(w, h, seed=2, tone=(206, 196, 176), dark=0.0):
    """лист бумаги: зерно волокон, лёгкие пятна, виньетка по краям."""
    base = Image.new("RGB", (w, h), tone)
    g = noise(w, h, seed, 2.2).filter(ImageFilter.GaussianBlur(1.2))
    a = np.asarray(base, np.float32) + (np.asarray(g, np.float32) / 255 - 0.5)[:, :, None] * 26
    if dark:
        a *= (1.0 - dark)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    vig = np.clip(1.0 - 0.12 * np.clip(r - 0.4, 0, 1.4) ** 1.6, 0, 1)
    a2 = np.asarray(im, np.float32) * vig[:, :, None]
    return Image.fromarray(np.clip(a2, 0, 255).astype(np.uint8), "RGB")


def grain(img, t, amount=0.045, seed_mod=97):
    """плёночное зерно: меняется каждый кадр."""
    key = int(t * 30) % seed_mod
    if key not in _grain_cache:
        rng = np.random.default_rng(1000 + key)
        _grain_cache[key] = rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32)
    g = _grain_cache[key]
    gw, gh = img.size
    gg = g
    if (gw, gh) != (W, H):
        gg = np.asarray(Image.fromarray(((g - g.min()) / (g.ptp() + 1e-6) * 255)
                         .astype(np.uint8)).resize((gw, gh)), np.float32) / 255 - 0.5
    else:
        gg = np.kron(g, np.ones((2, 2), np.float32))[:H, :W]
    a = np.asarray(img.convert("RGB"), np.float32)
    a += gg[:, :, None] * amount * 255
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def vignette(img, k=0.55):
    w, h = img.size
    if (w, h) not in _vig:
        yy, xx = np.mgrid[0:h, 0:w]
        r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        _vig[(w, h)] = np.clip(r - 0.45, 0, 1.2) ** 1.6
    a = np.asarray(img.convert("RGB"), np.float32)
    a *= (1.0 - k * _vig[(w, h)])[:, :, None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def fade(img, k):
    k = clamp(k)
    if k >= 1:
        return img
    a = np.asarray(img.convert("RGB"), np.float32) * k
    return Image.fromarray(a.astype(np.uint8), "RGB")


def in_out_fade(img, t, dur, fi=0.35, fo=0.35):
    k = 1.0
    if fi > 0:
        k = min(k, seg(t, 0, fi))
    if fo > 0:
        k = min(k, 1 - seg(t, dur - fo, dur))
    return fade(img, smoother(k))


def finish(img, t, dur, fi=0.3, fo=0.3, grain_k=0.03, vig=0.35):
    """ФИНАЛЬНАЯ ОБРАБОТКА КАДРА — ставится в конце КАЖДОЙ карточки
    (core.finish оригинала). Без неё и был тот самый «плоский рендер»."""
    img = img.convert("RGB")
    if vig > 0:
        img = vignette(img, vig)
    if grain_k > 0:
        img = grain(img, t, grain_k)
    return in_out_fade(img, t, dur, fi, fo)


def shadow_of(size, lx, ly, cx, cy, blur=18, a=170, depth=0.07):
    """тень карточки size с центром (cx, cy): уходит от лампы (lx, ly)."""
    w, h = size
    dx = (cx - lx) * depth
    dy = (cy - ly) * depth * 0.6 + 10
    lay = Image.new("RGBA", (w + 120, h + 120), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rectangle([60, 60, 60 + w, 60 + h], fill=(0, 0, 0, a))
    lay = lay.filter(ImageFilter.GaussianBlur(blur))
    return lay, int(cx - w / 2 - 60 + dx), int(cy - h / 2 - 60 + dy)


def masked_write(text, px, fnt_path, color, k, size, heavy=False, italic=True):
    """РУКОПИСНАЯ ПОМЕТКА (core.rukopis): строка пишется по маске слева
    направо, у кончика пера — точка. `k` 0…1 — доля написанного."""
    pw, ph = size
    lay = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    if k <= 0:
        return lay
    f = font(fnt_path, px)
    d = ImageDraw.Draw(lay)
    tw = d.textlength(text, font=f)
    base = int(px * 1.05)
    d.text((0, base), text, font=f, fill=color + (255,), anchor="ls")
    if heavy:
        d.text((1, base + 1), text, font=f, fill=color + (255,), anchor="ls")
    kk = out_cubic(k)
    m = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(m).rectangle([0, 0, int(tw * kk) + 2, int(px * 1.6)], fill=255)
    al = Image.fromarray(np.minimum(np.asarray(lay.getchannel("A")),
                                     np.asarray(m)).astype(np.uint8), "L")
    lay.putalpha(al)
    if k < 1:
        xe = tw * kk
        ImageDraw.Draw(lay).ellipse([xe - 4, base - px * 0.3 - 4, xe + 4, base - px * 0.3 + 4],
                                     fill=color + (255,))
    return lay
