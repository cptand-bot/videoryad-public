#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Атомы карты-брифинга: свечения, радары, зоны, выноски, HUD, макеты.

Каждый атом рисует СВОЙ прозрачный слой и ничего не знает про соседей —
так же, как сделаны круги-радар в `fx_rings.py`. Слои складываются поверх
подложки в нужном порядке, любой можно выключить.
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WF = "/mnt/c/Windows/Fonts/"
LIB = "/usr/share/fonts/truetype/liberation/"
DJV = "/usr/share/fonts/truetype/dejavu/"


def _pick(*names):
    """Шрифт ищем по цепочке: машина автора → раннер облака.
    На раннере GitHub шрифтов Windows нет, и пять клипов из двадцати
    падали на ровном месте (OSError: cannot open resource)."""
    for n in names:
        if os.path.exists(n):
            return n
    return names[-1]


F_HEAD = _pick(WF + "ariblk.ttf", LIB + "LiberationSans-Bold.ttf", DJV + "DejaVuSans-Bold.ttf")
F_BOLD = _pick(WF + "arialbd.ttf", LIB + "LiberationSans-Bold.ttf", DJV + "DejaVuSans-Bold.ttf")
F_REG = _pick(WF + "arial.ttf", LIB + "LiberationSans-Regular.ttf", DJV + "DejaVuSans.ttf")
F_COND = _pick(WF + "bahnschrift.ttf", LIB + "LiberationSansNarrow-Regular.ttf",
               DJV + "DejaVuSansCondensed.ttf")

SS = 3   # суперсэмплинг: PIL не умеет сглаживание, рисуем крупно и ужимаем


def font(path, size):
    return ImageFont.truetype(path, size)


def _blur(layer, r):
    return layer.filter(ImageFilter.GaussianBlur(r))


def glow(draw_fn, size, color, core=2, spread=14, power=1.0):
    """Общий приём свечения: фигура рисуется в маску, маска размывается
    трижды с разным радиусом и красится цветом. Так сделаны все светящиеся
    атомы — кольца, обводки, купол, трассеры."""
    w, h = size
    m = Image.new("L", (w * 1, h * 1), 0)
    draw_fn(ImageDraw.Draw(m))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for r, a in ((spread * 2.2, 0.22), (spread, 0.38), (spread * 0.35, 0.55)):
        mm = _blur(m, r)
        lay = Image.new("RGBA", (w, h), color + (0,))
        lay.putalpha(mm.point(lambda v: int(v * a * power)))
        out = Image.alpha_composite(out, lay)
    core_lay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    cm = _blur(m, core * 0.4)
    mix = tuple(min(255, int(c * 0.35 + 255 * 0.65)) for c in color)
    core_lay = Image.new("RGBA", (w, h), mix + (0,))
    core_lay.putalpha(cm.point(lambda v: int(v * 0.95 * power)))
    return Image.alpha_composite(out, core_lay)


def ellipse_pts(cx, cy, rx, ry, n=240, a0=0.0, a1=math.tau, squash=1.0, rot=0.0):
    pts = []
    for i in range(n + 1):
        a = a0 + (a1 - a0) * i / n
        x = rx * math.cos(a)
        y = ry * math.sin(a) * squash
        xr = x * math.cos(rot) - y * math.sin(rot)
        yr = x * math.sin(rot) + y * math.cos(rot)
        pts.append((cx + xr, cy + yr))
    return pts


# ─────────────────────────── 1. КОЛЬЦО-ПУЛЬС ───────────────────────────
def ring_pulse(size, cx, cy, r, color=(90, 200, 255), squash=0.35, width=4,
               power=1.0):
    """Кольцо на воде в перспективе — расходится от объекта."""
    def fn(d):
        d.line(ellipse_pts(cx, cy, r, r, squash=squash), fill=255, width=width)
    return glow(fn, size, color, spread=13, power=power)


# ─────────────────────── 2. ЗОНА УГРОЗЫ (заливка) ───────────────────────
def threat_zone(size, cx, cy, r, color=(236, 54, 60), squash=1.0, fill=0.30):
    w, h = size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse([cx - r, cy - r * squash, cx + r, cy + r * squash], fill=255)
    # заливка слабеет к центру — у края плотнее
    arr = np.asarray(_blur(m, r * 0.22), np.float32) / 255.0
    edge = np.clip(arr * (1.35 - arr), 0, 1)
    edge = edge / max(edge.max(), 1e-6)
    lay = Image.new("RGBA", (w, h), color + (0,))
    lay.putalpha(Image.fromarray((np.clip(arr * fill + edge * 0.45, 0, 1) * 255).astype(np.uint8)))
    out = Image.alpha_composite(out, lay)

    def rim(d):
        d.ellipse([cx - r, cy - r * squash, cx + r, cy + r * squash], outline=255, width=5)
    return Image.alpha_composite(out, glow(rim, size, color, spread=16))


# ─────────────────────────── 3. РАДАР ───────────────────────────
def radar(size, cx, cy, r, color=(80, 200, 255), sweep=True, ang=0.0, rings=3):
    w, h = size

    def fn(d):
        for i in range(1, rings + 1):
            rr = r * i / rings
            wdt = 4 if i == rings else 2
            if i == rings - 1:
                for k in range(0, 360, 9):   # пунктирное среднее кольцо
                    a0 = math.radians(k)
                    a1 = math.radians(k + 4.5)
                    d.line(ellipse_pts(cx, cy, rr, rr, n=6, a0=a0, a1=a1), fill=255, width=2)
            else:
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=255, width=wdt)
        d.line([cx - r * 1.12, cy, cx + r * 1.12, cy], fill=255, width=2)
        d.line([cx, cy - r * 1.12, cx, cy + r * 1.12], fill=255, width=2)
        for k in range(0, 360, 30):          # тики по внешнему кругу
            a = math.radians(k)
            d.line([(cx + r * 0.93 * math.cos(a), cy + r * 0.93 * math.sin(a)),
                    (cx + r * 1.06 * math.cos(a), cy + r * 1.06 * math.sin(a))],
                   fill=255, width=3)

    base = glow(fn, size, color, spread=11)
    if sweep:
        sw = Image.new("L", (w, h), 0)
        ds = ImageDraw.Draw(sw)
        for i in range(70):                   # хвост развёртки
            a = ang - math.radians(i * 1.1)
            v = int(200 * (1 - i / 70) ** 1.6)
            ds.polygon([(cx, cy),
                        (cx + r * math.cos(a), cy + r * math.sin(a)),
                        (cx + r * math.cos(a - 0.02), cy + r * math.sin(a - 0.02))],
                       fill=v)
        lay = Image.new("RGBA", (w, h), color + (0,))
        lay.putalpha(_blur(sw, 3))
        base = Image.alpha_composite(base, lay)
    return base


# ─────────────────── 4. ПРИЦЕЛ В ПЕРСПЕКТИВЕ ───────────────────
def crosshair(size, cx, cy, r, color=(70, 210, 255), squash=0.42):
    def fn(d):
        d.line(ellipse_pts(cx, cy, r, r, squash=squash), fill=255, width=4)
        d.line([cx - r * 1.9, cy - r * 0.52, cx + r * 1.9, cy + r * 0.52], fill=255, width=2)
        d.line([cx - r * 1.9, cy + r * 0.52, cx + r * 1.9, cy - r * 0.52], fill=255, width=2)
        for k in range(0, 360, 45):
            a = math.radians(k)
            x = cx + r * math.cos(a)
            y = cy + r * squash * math.sin(a)
            d.line([(x, y - 7), (x, y + 7)], fill=255, width=3)
    return glow(fn, size, color, spread=12)


# ───────────────────── 5. КУПОЛ-ПОЛУСФЕРА ─────────────────────
def dome(size, cx, cy, r, color=(90, 210, 255), dashed=True):
    def fn(d):
        d.line(ellipse_pts(cx, cy, r, r, n=200, a0=math.pi, a1=math.tau), fill=255, width=5)
        d.line(ellipse_pts(cx, cy, r, r * 0.30, n=200), fill=255, width=4)
        if dashed:
            for k, rr in ((0.72, 0.62), (0.46, 0.40)):
                pts = ellipse_pts(cx, cy, r * k, r * k, n=160, a0=math.pi, a1=math.tau)
                for i in range(0, len(pts) - 6, 10):
                    d.line(pts[i:i + 5], fill=210, width=3)
    return glow(fn, size, color, spread=14)


# ────────────── 6. ОБВОДКА ОБЪЕКТА НЕОНОМ (по маске) ──────────────
def outline_glow(mask, color=(90, 255, 140), width=4, spread=18, power=1.0):
    """Контурная подсветка: берём альфу объекта, вычитаем сжатую копию —
    получаем ровно его силуэт толщиной `width`, дальше обычное свечение."""
    m = mask.filter(ImageFilter.MaxFilter(3))
    inner = m.filter(ImageFilter.MinFilter(2 * max(1, width // 2) + 1))
    edge = Image.fromarray(np.clip(np.asarray(m, np.int16) - np.asarray(inner, np.int16), 0, 255).astype(np.uint8))
    size = mask.size
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    for r, a in ((spread * 2.0, 0.26), (spread, 0.42), (spread * 0.3, 0.72)):
        lay = Image.new("RGBA", size, color + (0,))
        lay.putalpha(_blur(edge, r).point(lambda v: int(v * a * power)))
        out = Image.alpha_composite(out, lay)
    mix = tuple(min(255, int(c * 0.45 + 255 * 0.55)) for c in color)
    lay = Image.new("RGBA", size, mix + (0,))
    lay.putalpha(edge.point(lambda v: int(v * 0.80 * power)))
    return Image.alpha_composite(out, lay)


# ─────────── 7. ЗАЛИВКА ОБЪЕКТА СВЕЧЕНИЕМ («объект горит») ───────────
def fill_glow(mask, color=(255, 176, 54), power=1.0, halo=26):
    size = mask.size
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    lay = Image.new("RGBA", size, color + (0,))
    lay.putalpha(_blur(mask, halo).point(lambda v: int(v * 0.5 * power)))
    out = Image.alpha_composite(out, lay)
    lay = Image.new("RGBA", size, color + (0,))
    lay.putalpha(mask.point(lambda v: int(v * 0.62 * power)))
    return Image.alpha_composite(out, lay)


# ─────────────────── 8. ПОДПИСЬ АКВАТОРИИ ───────────────────
def sea_label(size, x, y, text, px=26, track=0.22, color=(236, 244, 255, 225)):
    w, h = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(F_REG, int(px * SS))
    cx = x * SS
    adv = [d.textlength(ch, font=f) for ch in text]
    extra = px * SS * track
    total = sum(adv) + extra * (len(text) - 1)
    cur = cx - total / 2
    for ch, a in zip(text, adv):
        d.text((cur, y * SS), ch, font=f, fill=color, anchor="lm")
        cur += a + extra
    return im.resize((w, h), Image.LANCZOS)


# ─────────────────── 9. ВЫНОСКА-ПОВОДОК ───────────────────
def leader(size, x0, y0, x1, y1, text, px=22, head="arrow", up=True,
           color=(255, 255, 255, 240)):
    """Тонкая линия от подписи к объекту: точка у подписи, стрелка у цели —
    ровно как в образце («AIRCRAFT CARRIER», «255 ←»)."""
    w, h = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    a, b = (x0 * SS, y0 * SS), (x1 * SS, y1 * SS)
    d.line([a, b], fill=color, width=max(2, SS // 2))
    d.ellipse([a[0] - 4 * SS // 2, a[1] - 4 * SS // 2, a[0] + 4 * SS // 2, a[1] + 4 * SS // 2], fill=color)
    if head == "arrow":
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        L = 9 * SS
        d.polygon([b,
                   (b[0] - L * math.cos(ang - 0.42), b[1] - L * math.sin(ang - 0.42)),
                   (b[0] - L * math.cos(ang + 0.42), b[1] - L * math.sin(ang + 0.42))], fill=color)
    f = font(F_REG, int(px * SS))
    ty = y0 * SS - (px * 1.25 * SS if up else -px * 1.25 * SS)
    d.text((x0 * SS, ty), text, font=f, fill=color, anchor="mm")
    return im.resize((w, h), Image.LANCZOS)


# ─────────────────── 10. МАРКЕР-ФЛАЖОК ───────────────────
def pin_flag(size, x, y, colors=((222, 41, 41), None), stars=True, px=34):
    """Прямоугольный флажок на ножке с точкой-основанием."""
    w, h = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    X, Y = x * SS, y * SS
    fw, fh = px * 1.5 * SS, px * SS
    d.line([(X, Y), (X, Y - fh * 1.55)], fill=(242, 246, 255, 235), width=max(2, SS // 2))
    d.ellipse([X - 5 * SS // 2, Y - 5 * SS // 2, X + 5 * SS // 2, Y + 5 * SS // 2],
              outline=(242, 246, 255, 240), width=max(2, SS // 2))
    box = [X + 3 * SS, Y - fh * 1.55, X + 3 * SS + fw, Y - fh * 0.55]
    d.rectangle(box, fill=colors[0] + (242,))
    if stars:
        sx, sy = box[0] + fw * 0.17, box[1] + fh * 0.30
        d.regular_polygon((sx, sy, fh * 0.17), 5, rotation=-18, fill=(255, 222, 60, 255))
        for k, (dx, dy) in enumerate(((.34, -.16), (.46, .02), (.46, .24), (.34, .40))):
            d.regular_polygon((box[0] + fw * (0.17 + dx), box[1] + fh * (0.30 + dy), fh * 0.065),
                              5, rotation=-18, fill=(255, 222, 60, 255))
    return im.resize((w, h), Image.LANCZOS)


def pin_drop(size, x, y, color=(240, 246, 255), px=26):
    w, h = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    X, Y, R = x * SS, y * SS, px * SS * 0.42
    d.ellipse([X - R, Y - R * 2.1, X + R, Y - R * 0.1], outline=color + (240,), width=max(2, SS // 2))
    d.polygon([(X - R * 0.52, Y - R * 0.55), (X + R * 0.52, Y - R * 0.55), (X, Y + R * 0.55)],
              fill=color + (240,))
    d.ellipse([X - R * 0.34, Y - R * 1.45, X + R * 0.34, Y - R * 0.77], fill=color + (240,))
    return im.resize((w, h), Image.LANCZOS)


# ─────────────────── 11. HUD-ПАНЕЛЬ СО СЧЁТОМ ───────────────────
def hud_count(size, x, y, cols, rows, filled, label=None, clock=None,
              icon="jet", px=16, accent=(150, 214, 255)):
    """Плашка-счётчик: сетка иконок заполняется по ходу реплики, справа —
    циферблат. Число в кадре читается БЕЗ цифр — глазом по количеству."""
    w, h = size
    pad = 14
    cw, ch = px * 1.55, px * 1.25
    bw = int(cols * cw + pad * 2 + (px * 3.6 if clock is not None else 0))
    bh = int(rows * ch + pad * 2)
    im = Image.new("RGBA", (bw * SS, bh * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, bw * SS - 1, bh * SS - 1], radius=10 * SS,
                        fill=(16, 34, 62, 168), outline=accent + (210,), width=max(2, SS // 2))
    n = 0
    for r in range(rows):
        for c in range(cols):
            cx = (pad + c * cw + cw / 2) * SS
            cy = (pad + r * ch + ch / 2) * SS
            on = n < filled
            col = (240, 248, 255, 245) if on else (150, 180, 220, 70)
            _jet_icon(d, cx, cy, px * 0.52 * SS, col) if icon == "jet" else \
                d.ellipse([cx - px * .3 * SS, cy - px * .3 * SS, cx + px * .3 * SS, cy + px * .3 * SS], fill=col)
            n += 1
    if clock is not None:
        R = px * 1.35 * SS
        cx = (bw - pad - px * 1.6) * SS
        cy = bh * SS / 2
        d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(248, 250, 255, 240),
                  outline=(30, 48, 80, 255), width=max(2, SS // 2))
        for k in range(12):
            a = math.radians(k * 30)
            d.line([(cx + R * .80 * math.sin(a), cy - R * .80 * math.cos(a)),
                    (cx + R * .92 * math.sin(a), cy - R * .92 * math.cos(a))],
                   fill=(30, 48, 80, 255), width=max(2, SS // 3))
        hh, mm = clock
        ah = math.radians((hh % 12) * 30 + mm * 0.5)
        am = math.radians(mm * 6)
        d.line([(cx, cy), (cx + R * .48 * math.sin(ah), cy - R * .48 * math.cos(ah))],
               fill=(22, 36, 62, 255), width=max(3, SS))
        d.line([(cx, cy), (cx + R * .70 * math.sin(am), cy - R * .70 * math.cos(am))],
               fill=(22, 36, 62, 255), width=max(2, SS // 2 + 1))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(im.resize((bw, bh), Image.LANCZOS), (int(x), int(y)))
    if label:
        out = Image.alpha_composite(out, sea_label((w, h), x + bw / 2, y - 16, label, px=15, track=0.16))
    return out


def _jet_icon(d, cx, cy, r, col):
    """Иконка самолёта сверху — стреловидная, как в счётчике образца."""
    pts = [(cx + r * 1.15, cy), (cx + r * 0.25, cy - r * 0.26), (cx - r * 0.30, cy - r * 0.95),
           (cx - r * 0.62, cy - r * 0.95), (cx - r * 0.34, cy - r * 0.18),
           (cx - r * 0.86, cy - r * 0.18), (cx - r * 1.05, cy - r * 0.52),
           (cx - r * 1.22, cy - r * 0.52), (cx - r * 1.14, cy)]
    full = pts + [(x, 2 * cy - y) for x, y in reversed(pts[:-1])]
    d.polygon(full, fill=col)


# ─────────────────── 12. ИНСПЕКТОР-ВРЕЗКА ───────────────────
def inspector(size, x, y, bw, bh, inner=None, label="", top=(228, 58, 62),
              bot=(60, 170, 255)):
    """Скруглённое окно с «штырьком» сверху: градиент тревога→контроль по
    рамке, внутри — тот же объект крупно, снаружи подпись капсом."""
    w, h = size
    im = Image.new("RGBA", (int(bw) * SS, int(bh) * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    R = 16 * SS
    grad = Image.new("RGBA", (int(bw) * SS, int(bh) * SS))
    ga = np.linspace(0, 1, int(bh) * SS, dtype=np.float32)[:, None, None]
    col = (np.array(top, np.float32)[None, None, :] * (1 - ga) +
           np.array(bot, np.float32)[None, None, :] * ga)
    col = np.repeat(col, int(bw) * SS, axis=1)
    grad = Image.fromarray(np.dstack([col, np.full(col.shape[:2], 235, np.float32)]).astype(np.uint8), "RGBA")
    msk = Image.new("L", (int(bw) * SS, int(bh) * SS), 0)
    ImageDraw.Draw(msk).rounded_rectangle([0, 0, int(bw) * SS - 1, int(bh) * SS - 1], radius=R, fill=255)
    im.paste(grad, (0, 0), msk)
    if inner is not None:
        fit = inner.resize((int(bw * SS * 0.92), int(bh * SS * 0.92)), Image.LANCZOS)
        im.paste(fit, (int(bw * SS * 0.04), int(bh * SS * 0.04)), fit)
    d.rounded_rectangle([0, 0, int(bw) * SS - 1, int(bh) * SS - 1], radius=R,
                        outline=(250, 252, 255, 250), width=3 * SS)
    small = im.resize((int(bw), int(bh)), Image.LANCZOS)

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    halo = Image.new("L", (w, h), 0)
    ImageDraw.Draw(halo).rounded_rectangle([x, y, x + bw, y + bh], radius=16, fill=255)
    out = Image.alpha_composite(out, outline_glow(halo, (150, 212, 255), width=3, spread=16, power=0.8))
    out.alpha_composite(small, (int(x), int(y)))
    # «штырёк»-капсула сверху по центру
    pin = Image.new("RGBA", (30 * SS, 52 * SS), (0, 0, 0, 0))
    dp = ImageDraw.Draw(pin)
    dp.rounded_rectangle([6 * SS, 0, 24 * SS, 46 * SS], radius=9 * SS,
                         fill=(120, 134, 158, 255), outline=(236, 242, 250, 255), width=2 * SS)
    dp.rounded_rectangle([11 * SS, 6 * SS, 16 * SS, 30 * SS], radius=3 * SS, fill=(216, 226, 240, 220))
    out.alpha_composite(pin.resize((30, 52), Image.LANCZOS), (int(x + bw / 2 - 15), int(y - 26)))
    if label:
        out = Image.alpha_composite(out, sea_label((w, h), x - 46, y + 18, label, px=17, track=0.14))
    return out


# ─────────────────── 13. ЗАГОЛОВОК ───────────────────
def title(size, x, y, white, accent, px=64, acc_color=(255, 190, 32)):
    w, h = size
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(F_HEAD, px * SS)
    gap = int(px * 0.30 * SS)
    w1 = d.textlength(white, font=f)
    w2 = d.textlength(accent, font=f)
    X = x * SS
    for dx, dy in ((3, 4), (-3, 4), (0, 6)):
        d.text((X + dx * SS // 2, y * SS + dy * SS // 2), white, font=f, fill=(0, 0, 0, 120), anchor="lm")
        d.text((X + w1 + gap + dx * SS // 2, y * SS + dy * SS // 2), accent, font=f, fill=(0, 0, 0, 120), anchor="lm")
    d.text((X, y * SS), white, font=f, fill=(255, 255, 255, 255), anchor="lm")
    d.text((X + w1 + gap, y * SS), accent, font=f, fill=acc_color + (255,), anchor="lm")
    return im.resize((w, h), Image.LANCZOS)


# ─────────────────── 14. МАКЕТ АВИАНОСЦА ───────────────────
def carrier(size, cx, cy, L, ang=-28, scale_h=0.30):
    """Объёмный макет сверху-сбоку: корпус, борт, палуба с разметкой,
    надстройка. Возвращает (слой, маска) — маска идёт в подсветку."""
    w, h = size
    W = L * 0.34
    im = Image.new("RGBA", (int(L * 1.6) * 2, int(L * 1.0) * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ox, oy = im.size[0] / 2, im.size[1] / 2
    Ls, Ws = L * 2, W * 2
    deck = [(ox - Ls * .50, oy - Ws * .34), (ox + Ls * .34, oy - Ws * .50),
            (ox + Ls * .50, oy - Ws * .10), (ox + Ls * .44, oy + Ws * .30),
            (ox - Ls * .42, oy + Ws * .50), (ox - Ls * .50, oy + Ws * .12)]
    side = [(x, y + Ws * scale_h) for x, y in deck]
    d.polygon([deck[3], deck[4], deck[5], side[5], side[4], side[3]], fill=(96, 104, 116, 255))
    d.polygon(deck, fill=(118, 124, 134, 255))
    d.polygon([(ox - Ls * .46, oy - Ws * .18), (ox + Ls * .40, oy - Ws * .34),
               (ox + Ls * .40, oy + Ws * .16), (ox - Ls * .40, oy + Ws * .32)],
              fill=(74, 78, 86, 255))
    for k in range(14):                       # осевой пунктир палубы
        t0 = k / 14
        x0 = ox - Ls * .42 + Ls * .80 * t0
        y0 = oy - Ws * .08 - Ws * .16 * t0
        d.line([(x0, y0), (x0 + Ls * .034, y0 - Ws * .006)], fill=(242, 246, 252, 235), width=max(2, int(Ws * .035)))
    d.line([(ox - Ls * .40, oy + Ws * .10), (ox + Ls * .34, oy - Ws * .10)],
           fill=(238, 196, 70, 220), width=max(2, int(Ws * .03)))
    isl = [(ox + Ls * .10, oy - Ws * .30), (ox + Ls * .22, oy - Ws * .33),
           (ox + Ls * .22, oy - Ws * .60), (ox + Ls * .10, oy - Ws * .56)]
    d.polygon(isl, fill=(150, 156, 166, 255))
    d.polygon([(ox + Ls * .13, oy - Ws * .60), (ox + Ls * .19, oy - Ws * .62),
               (ox + Ls * .19, oy - Ws * .86), (ox + Ls * .16, oy - Ws * .88),
               (ox + Ls * .13, oy - Ws * .84)], fill=(168, 174, 184, 255))
    d.ellipse([ox + Ls * .14, oy - Ws * .98, ox + Ls * .19, oy - Ws * .88], fill=(214, 220, 230, 255))
    d.polygon([deck[0], deck[5], side[5], side[0]], fill=(132, 60, 56, 255))   # скула

    im = im.rotate(ang, Image.BICUBIC, expand=False, center=(ox, oy))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(im, (int(cx - ox), int(cy - oy)))
    return out, out.getchannel("A")


# ─────────────────── 15. КИЛЬВАТЕР / ТРАССА ───────────────────
def wake(size, x0, y0, x1, y1, width=18, color=(236, 244, 255), power=1.0):
    w, h = size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    n = 60
    for i in range(n):
        t = i / n
        a = int(210 * (1 - t) ** 1.5)
        ww = int(width * (0.35 + 1.5 * t))
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        d.ellipse([x - ww, y - ww * 0.42, x + ww, y + ww * 0.42], fill=a)
    lay = Image.new("RGBA", (w, h), color + (0,))
    lay.putalpha(_blur(m, 7).point(lambda v: int(v * 0.72 * power)))
    return lay


# ─────────────────── 16. САМОЛЁТ С ТРАССЕРОМ ───────────────────
def jet(size, x, y, r=16, ang=0.0, trail=120, trail_color=(255, 64, 58),
        body=(226, 234, 244)):
    w, h = size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    tm = Image.new("L", (w, h), 0)
    dt = ImageDraw.Draw(tm)
    for i in range(48):
        t = i / 48
        a = int(235 * (1 - t) ** 1.25)
        rr = r * (0.42 - 0.30 * t)
        px_ = x - math.cos(ang) * trail * t
        py_ = y - math.sin(ang) * trail * t
        dt.ellipse([px_ - rr, py_ - rr, px_ + rr, py_ + rr], fill=a)
    for rad, al in ((16, 0.30), (7, 0.45), (2, 0.85)):
        lay = Image.new("RGBA", (w, h), trail_color + (0,))
        lay.putalpha(_blur(tm, rad).point(lambda v: int(v * al)))
        out = Image.alpha_composite(out, lay)
    pl = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    _jet_icon(ImageDraw.Draw(pl), x * SS, y * SS, r * SS, body + (248,))
    pl = pl.rotate(-math.degrees(ang), Image.BICUBIC, center=(x * SS, y * SS))
    return Image.alpha_composite(out, pl.resize((w, h), Image.LANCZOS))


# ─────────────────── 17. ВЕЕР СТРЕЛОК К ЦЕЛИ ───────────────────
def fan(size, cx, cy, R, n=11, a0=170, a1=370, r=13, inward=True,
        color=(255, 64, 58)):
    """Веер машин к цели. ВСЕ трассеры рисуются в ОДНУ маску и размываются
    один раз: раньше каждый самолёт тянул свои три размытия на полный кадр,
    и кадр с тринадцатью машинами считался пятнадцать секунд вместо одной."""
    w, h = size
    tm = Image.new("L", (w, h), 0)
    dt = ImageDraw.Draw(tm)
    bodies = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # спрайт машины рисуется ОДИН раз в маленьком буфере и дальше только
    # поворачивается: поворот полного кадра на каждую машину стоил 20 секунд
    sp = int(r * 3.2) * SS
    sprite = Image.new("RGBA", (sp * 2, sp * 2), (0, 0, 0, 0))
    _jet_icon(ImageDraw.Draw(sprite), sp, sp, r * SS, (226, 234, 244, 248))
    sprite = sprite.resize((sp * 2 // SS, sp * 2 // SS), Image.LANCZOS)
    trail = R * 0.42
    for i in range(n):
        a = math.radians(a0 + (a1 - a0) * i / max(1, n - 1))
        d = R * (0.82 + 0.3 * ((i * 37) % 10) / 10)
        x, y = cx + d * math.cos(a), cy + d * math.sin(a) * 0.62
        # курс считаем ПО ЭКРАНУ, а не по углу разброса: кольцо сжато по
        # высоте, и шлейф от «геометрического» угла уезжал поперёк движения
        ang = math.atan2(cy - y, cx - x) if inward else math.atan2(y - cy, x - cx)
        for k in range(40):
            t = k / 40
            al = int(235 * (1 - t) ** 1.25)
            rr = r * (0.42 - 0.30 * t)
            px_ = x - math.cos(ang) * trail * t
            py_ = y - math.sin(ang) * trail * t
            dt.ellipse([px_ - rr, py_ - rr, px_ + rr, py_ + rr], fill=al)
        rot = sprite.rotate(-math.degrees(ang), Image.BICUBIC)
        bodies.alpha_composite(rot, (int(x - rot.width / 2), int(y - rot.height / 2)))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for rad, al in ((16, .30), (7, .45), (2, .85)):
        lay = Image.new("RGBA", (w, h), color + (0,))
        lay.putalpha(_blur(tm, rad).point(lambda v: int(v * al)))
        out = Image.alpha_composite(out, lay)
    return Image.alpha_composite(out, bodies.resize((w, h), Image.LANCZOS))


# ─────────────────── 18. БЕГУЩИЙ ОГОНЬ ПО ПОЛОСЕ ───────────────────
def runway_fire(size, x0, y0, x1, y1, t=0.6, color=(255, 70, 52), width=7):
    def fn(d):
        xa, ya = x0 + (x1 - x0) * max(0, t - .34), y0 + (y1 - y0) * max(0, t - .34)
        xb, yb = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        d.line([(xa, ya), (xb, yb)], fill=255, width=width)
    return glow(fn, size, color, spread=15, power=1.2)


# ───────── 19. ОБЪЕКТ С ПОДСВЕТКОЙ: ореол ПОД ним, контур поверх ─────────
def lit_object(base, obj, x, y, color=(90, 255, 140), width=5, spread=24,
               power=1.0):
    """Правильный порядок слоёв: сначала мягкий ореол на фоне, затем сам
    объект, затем тонкий яркий контур по его краю."""
    size = base.size
    m = Image.new("L", size, 0)
    m.paste(obj.getchannel("A"), (int(x), int(y)))
    halo = Image.new("RGBA", size, (0, 0, 0, 0))
    for r, a in ((spread * 2.4, 0.34), (spread, 0.46)):
        lay = Image.new("RGBA", size, color + (0,))
        lay.putalpha(_blur(m, r).point(lambda v: int(v * a * power)))
        halo = Image.alpha_composite(halo, lay)
    out = Image.alpha_composite(base.convert("RGBA"), halo)
    out.alpha_composite(obj, (int(x), int(y)))
    return Image.alpha_composite(out, outline_glow(m, color, width=width,
                                                   spread=spread * 0.5, power=power))


# ───────────── 20. BLOOM: свет проливается по кадру ─────────────
def bloom(im, thr=186, power=0.55, radius=22):
    """Последний проход по готовому кадру: яркие места разливаются мягким
    свечением — тем самым «киношным» слоем, который в образце есть, а в
    чистой отрисовке его нет."""
    arr = np.asarray(im.convert("RGB"), np.float32)
    lum = arr.max(axis=2)
    k = np.clip((lum - thr) / max(1.0, 255 - thr), 0, 1)[..., None]
    bright = Image.fromarray((arr * k).astype(np.uint8))
    b1 = bright.filter(ImageFilter.GaussianBlur(radius))
    b2 = bright.filter(ImageFilter.GaussianBlur(radius * 2.6))
    out = arr + np.asarray(b1, np.float32) * power + np.asarray(b2, np.float32) * power * 0.6
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


# ───────────── 21. ТОЛЬКО ШЛЕЙФ (под объёмный самолёт) ─────────────
def trail(size, x, y, ang, length=150, color=(255, 64, 58), r=14, power=1.0):
    w, h = size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    for i in range(52):
        t = i / 52
        a = int(240 * (1 - t) ** 1.3)
        rr = r * (0.42 - 0.32 * t)
        d.ellipse([x - math.cos(ang) * length * t - rr, y - math.sin(ang) * length * t - rr,
                   x - math.cos(ang) * length * t + rr, y - math.sin(ang) * length * t + rr],
                  fill=a)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for rad, al in ((17, .30), (7, .46), (2, .88)):
        lay = Image.new("RGBA", (w, h), color + (0,))
        lay.putalpha(_blur(m, rad).point(lambda v: int(v * al * power)))
        out = Image.alpha_composite(out, lay)
    return out
