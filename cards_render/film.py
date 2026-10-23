#!/usr/bin/env python3
"""КИНОПЛЁНКА — четыре элемента (приняты 2026-10-21, «берём все»).

  film_strip   — лента с перфорацией едет вбок и останавливается на кадре
  film_single  — один кадр в плёнке: свет проектора, мерцание, царапины
  film_contact — полоски контактного листа приходят по очереди
  film_newsreel— кинохроника: лидер с обратным отсчётом 3-2-1

ЗЕРНО ЖИВОЕ. У каждого кадра свой seed, поэтому зерно и царапины
шевелятся, как на настоящей плёнке; статичное зерно сразу читается как
картинка с фильтром, а не как плёнка.

ДЁРГАНЬЯ ПЛЁНКИ (gate weave) ЗДЕСЬ НЕТ. Настоящая плёнка в проекторе
гуляет по вертикали, но пользователь дрожание кадра снял прямым словом
(21.10: «дёргание меня бесит»). Параметр weave оставлен, по умолчанию 0 —
включать только по прямой просьбе.
"""
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "template"))
import style_cards as sc
import cinematic as cn

W, H = sc.W, sc.H


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _grain(im, strength=6.0, scratches=True, seed=3, dust=True):
    """Зерно, царапины и пыль. seed меняется от кадра к кадру — плёнка живёт."""
    a = np.asarray(im.convert("RGB"), np.float32)
    rng = np.random.default_rng(seed)
    a += rng.normal(0, strength, (im.height, im.width, 1))
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    r = random.Random(seed)
    d = ImageDraw.Draw(im, "RGBA")
    if scratches:
        for _ in range(r.randint(1, 3)):
            x = r.randint(0, im.width)
            d.line((x, 0, x + r.randint(-14, 14), im.height),
                   fill=(236, 232, 224, r.randint(22, 48)), width=r.choice([1, 1, 2]))
    if dust:
        for _ in range(r.randint(8, 20)):
            x, y = r.randint(0, im.width), r.randint(0, im.height)
            rr = r.randint(1, 3)
            d.ellipse((x, y, x + rr, y + rr), fill=(230, 226, 218, r.randint(28, 66)))
    return im


def _flicker(im, t, amp=0.05, seed=0, fps=25, step=3):
    """Мерцание яркости лампы проектора.

    КВАНТУЕТСЯ ПО ТЕМ ЖЕ ТРЁМ КАДРАМ, ЧТО И ЗЕРНО (21.10). Непрерывное
    мерцание меняет яркость КАЖДОГО кадра, и межкадровое сжатие перестаёт
    работать: девятисекундная кинохроника весила 57 МБ даже после правки
    зерна. На глаз разницы нет — лампа и так «моргает» ступенями.
    """
    tq = (int(t * fps) // step) * step / fps
    k = 1.0 + amp * math.sin(tq * 17.3 + seed) * 0.5 + amp * math.sin(tq * 43.1 + seed) * 0.5
    a = np.asarray(im, np.float32) * k
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _perf_strip(w, h, frame_h, pitch=58, hole=(30, 22), margin=26, col=(18, 18, 20)):
    strip = Image.new("RGB", (w, h), col)
    d = ImageDraw.Draw(strip)
    hw, hh = hole
    y_top = (h - frame_h) // 2
    for x in range(margin, w - margin, pitch):
        d.rounded_rectangle((x, (y_top - hh) // 2 + 4, x + hw, (y_top - hh) // 2 + 4 + hh), 5,
                            fill=(234, 232, 226))
        yb = h - (y_top - hh) // 2 - hh - 4
        d.rounded_rectangle((x, yb, x + hw, yb + hh), 5, fill=(234, 232, 226))
    return strip


def _frame_seed(t, fps=25, step=3):
    """Номер рисунка зерна.

    ЗЕРНО МЕНЯЕТСЯ НЕ КАЖДЫЙ КАДР (21.10). Уникальный шум в каждом кадре
    убивает сжатие: девятисекундная кинохроника весила 60 МБ, и браузер
    её просто не проигрывал. Настоящая плёнка всё равно «живёт» реже
    частоты кадров, поэтому меняем рисунок раз в три кадра — на глаз то
    же самое, вес меньше на порядок.
    """
    return int(t * fps) // step * 7 + 3


# ───────────────────────── 1. ЛЕНТА ЕДЕТ ВБОК ────────────────────────────
def film_strip(out=None, *, shots=(), captions=(), kick="", title="", sub="",
               watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=10.0, t=None, sfx=None,
               stop_on=None, frame_w=640, frame_h=430):
    """Лента с кадрами едет вбок и мягко останавливается.

    stop_on — номер кадра (с нуля), на котором лента встаёт по центру.
    По умолчанию встаёт на середине ленты.
    """
    tt = seconds if t is None else t
    im = sc.canvas()
    n = max(1, len(shots))
    if stop_on is None:
        stop_on = n // 2

    sh_h = frame_h + 150
    strip = _perf_strip(frame_w * n + 320, sh_h, frame_h)
    y0 = (sh_h - frame_h) // 2
    d = ImageDraw.Draw(strip)
    for i, path in enumerate(shots):
        pic = cn._fit(path, (frame_w - 22, frame_h - 16))
        x = 60 + i * frame_w
        strip.paste(pic, (x + 11, y0 + 8))
        d.rectangle((x, y0, x + frame_w - 22, y0 + frame_h), outline=(44, 44, 48), width=3)
        if i < len(captions) and captions[i]:
            # ПОДПИСЬ ВНУТРИ КАДРА, а не под ним: под кадром идёт
            # перфорация, и текст ложился прямо на дырки (21.10).
            cap = captions[i]
            fnt = sc._f(sc.MONO, 20)
            tw = d.textlength(cap, font=fnt)
            d.rectangle((x + 11, y0 + frame_h - 46, x + 11 + tw + 28, y0 + frame_h - 8),
                        fill=(10, 10, 12))
            d.text((x + 25, y0 + frame_h - 40), cap, font=fnt, fill=(214, 178, 64))
    strip = _grain(strip, 5.0, True, _frame_seed(tt), dust=True)

    # ход ленты: приезжает и мягко встаёт на нужном кадре
    p = _ease(min(1.0, tt / 2.6))
    target = -(60 + stop_on * frame_w + (frame_w - 22) / 2 - W / 2)
    start = target + frame_w * 2.4
    x_off = int(start + (target - start) * p)
    im.paste(strip, (x_off, (H - sh_h) // 2 + 40))
    sc._ev(sfx, 0.1, "accent")

    # края уходят в темноту — лента продолжается за кадром
    v = Image.new("L", (W, H), 0)
    ImageDraw.Draw(v).rectangle((260, 0, W - 260, H), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(170))
    a = np.asarray(im, np.float32) * (0.35 + 0.65 * (np.asarray(v, np.float32) / 255.0)[..., None])
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    im = cn._head(im, kick, title, sub, watermark, t)
    if out:
        im.save(out, quality=94)
    return im


# ──────────────────────── 2. ОДИН КАДР В ПЛЁНКЕ ──────────────────────────
def film_single(out=None, *, photo="", kick="", title="", sub="",
                watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=8.0, t=None, sfx=None,
                wear=7.5, weave=0.0):
    """Академический кадр в плёнке: свет проектора, мерцание, царапины."""
    tt = seconds if t is None else t
    im = Image.new("RGB", (W, H), (10, 10, 12))
    fh = int(H * 0.66)
    fw = int(fh * 1.37)
    pic = cn._fit(photo, (fw, fh))
    pic = _grain(pic, wear, True, _frame_seed(tt) + 11)
    if t is not None:
        pic = _flicker(pic, tt, 0.06, 2)

    x0, y0 = (W - fw) // 2, (H - fh) // 2 + 74
    if weave:
        y0 += int(weave * math.sin(tt * 9.1))

    d = ImageDraw.Draw(im)
    # перфорация бежит вместе с ходом плёнки
    shift = int((tt * 62) % 62) if t is not None else 0
    for y in range(y0 - 72 + shift, y0 + fh + 10, 62):
        d.rounded_rectangle((x0 - 76, y, x0 - 40, y + 30), 6, fill=(226, 224, 218))
        d.rounded_rectangle((x0 + fw + 40, y, x0 + fw + 76, y + 30), 6, fill=(226, 224, 218))
    d.rectangle((x0 - 120, 0, x0 - 14, H), outline=(34, 34, 38), width=2)
    d.rectangle((x0 + fw + 14, 0, x0 + fw + 120, H), outline=(34, 34, 38), width=2)

    a_pic = 1.0 if t is None else _ease((tt - 0.3) / 0.5)
    if a_pic < 1.0:
        pic = Image.fromarray(np.clip(np.asarray(pic, np.float32) * a_pic, 0, 255).astype(np.uint8))
    im.paste(pic, (x0, y0))
    d.rectangle((x0 - 3, y0 - 3, x0 + fw + 2, y0 + fh + 2), outline=(44, 44, 48), width=4)
    sc._ev(sfx, 0.3, "quote")

    g = Image.new("L", (W, H), 0)
    ImageDraw.Draw(g).ellipse((x0 - 200, y0 - 160, x0 + fw + 200, y0 + fh + 160), fill=70)
    g = g.filter(ImageFilter.GaussianBlur(160))
    arr = np.asarray(im, np.float32) + np.asarray(g, np.float32)[..., None] * 0.5 * a_pic
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    im = cn._head(im, kick, title, sub, watermark, t)
    if out:
        im.save(out, quality=94)
    return im


# ──────────────────────── 3. КОНТАКТНЫЙ ЛИСТ ─────────────────────────────
def film_contact(out=None, *, shots=(), kick="", title="", sub="",
                 watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=10.0, t=None, sfx=None,
                 highlight=None, rows=3, per_row=3):
    """Полоски плёнки приходят по очереди; нужный кадр можно подсветить.

    highlight — (номер полоски, номер кадра в ней) или None.
    """
    tt = seconds if t is None else t
    im = sc.canvas()
    # Сетка поджата (21.10): при прежних размерах нижняя полоска уходила
    # за нижний край кадра и обрезалась.
    fh, fw = 195, 295
    layout = ((-7, (170, 236)), (-7, (120, 496)), (-7, (220, 756)))
    k = 0
    for row in range(min(rows, len(layout))):
        ang, (sx, sy) = layout[row]
        at = 0.35 + row * 0.55
        a_row = 1.0 if t is None else _ease((tt - at) / 0.45)
        if a_row <= 0:
            continue
        sc._ev(sfx, at, "label")
        sh_h = fh + 72
        strip = _perf_strip(fw * per_row + 80, sh_h, fh, pitch=46, hole=(24, 16), margin=18)
        y0 = (sh_h - fh) // 2
        sd = ImageDraw.Draw(strip)
        for i in range(per_row):
            idx = row * per_row + i
            if idx >= len(shots):
                break
            pic = cn._fit(shots[idx], (fw - 18, fh - 12))
            hot = highlight == (row, i)
            if hot and t is not None:
                hp = _ease((tt - (at + 1.1)) / 0.5)
                if hp > 0:
                    pic = Image.fromarray(np.clip(np.asarray(pic, np.float32) * (1 + 0.35 * hp),
                                                  0, 255).astype(np.uint8))
            strip.paste(pic, (30 + i * fw + 9, y0 + 6))
            sd.rectangle((30 + i * fw, y0, 30 + i * fw + fw - 18, y0 + fh),
                         outline=(206, 60, 56) if hot else (44, 44, 48),
                         width=5 if hot else 2)
            sd.text((30 + i * fw + 8, y0 + fh + 10), f"{idx+1:02d}A",
                    font=sc._f(sc.MONO, 16), fill=(206, 170, 60))
        strip = _grain(strip, 4.0, False, _frame_seed(tt) + row * 5)
        strip = strip.rotate(ang, resample=Image.BICUBIC, expand=True)
        if a_row < 1.0:
            strip = Image.fromarray(np.clip(np.asarray(strip.convert("RGB"), np.float32) * a_row,
                                            0, 255).astype(np.uint8))
        dx = int(-180 * (1 - a_row)) if row % 2 == 0 else int(180 * (1 - a_row))
        sh = Image.new("L", (W, H), 0)
        sh.paste(Image.new("L", strip.size, 200), (sx + dx + 10, sy + 14))
        sh = sh.filter(ImageFilter.GaussianBlur(22))
        a = np.asarray(im, np.float32) * (1 - 0.5 * a_row * (np.asarray(sh, np.float32) / 255.0)[..., None])
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        im.paste(strip, (sx + dx, sy))
    im = cn._head(im, kick, title, sub, watermark, t)
    if out:
        im.save(out, quality=94)
    return im


# ────────────────────────── 4. КИНОХРОНИКА ───────────────────────────────
def film_newsreel(out=None, *, photo="", kick="", title="", sub="",
                  watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=9.0, t=None, sfx=None,
                  countdown=3.0, sepia=False):
    """Лидер с обратным отсчётом, затем сам кадр хроники.

    countdown — сколько секунд крутится отсчёт (3-2-1), дальше идёт кадр.
    """
    tt = seconds if t is None else t
    base = cn._fit(photo)
    g = ImageOps.grayscale(base)
    a = np.clip(np.asarray(g, np.float32) * 1.06 - 6, 0, 255)
    tone = (1.02, 0.99, 0.92) if not sepia else (1.08, 0.97, 0.80)
    im = Image.fromarray(np.clip(np.stack([a * tone[0], a * tone[1], a * tone[2]], -1),
                                 0, 255).astype(np.uint8))
    im = _grain(im, 7.0, True, _frame_seed(tt) + 21)
    if t is not None:
        im = _flicker(im, tt, 0.07, 5)

    v = Image.new("L", (W, H), 0)
    ImageDraw.Draw(v).ellipse((-W * 0.15, -H * 0.2, W * 1.15, H * 1.2), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(190))
    arr = np.asarray(im, np.float32) * (0.45 + 0.55 * (np.asarray(v, np.float32) / 255.0)[..., None])
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    d = ImageDraw.Draw(im, "RGBA")
    bw = int((W - H * 4 / 3) / 2)
    d.rectangle((0, 0, bw, H), fill=(0, 0, 0))
    d.rectangle((W - bw, 0, W, H), fill=(0, 0, 0))

    # отсчёт: сектор обегает круг за секунду, цифра меняется
    if t is None or tt < countdown:
        left = countdown - (0 if t is None else tt)
        num = max(1, min(3, int(math.ceil(left))))
        frac = 1.0 - (left - math.floor(left)) if t is not None else 0.58
        cx, cy, r = W // 2, H // 2, 210
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(236, 232, 224, 210), width=4)
        d.line((cx - r, cy, cx + r, cy), fill=(236, 232, 224, 150), width=3)
        d.line((cx, cy - r, cx, cy + r), fill=(236, 232, 224, 150), width=3)
        d.pieslice((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * frac,
                   fill=(236, 232, 224, 34))
        f = sc._f(sc.F_HEAD, 300)
        tw = d.textlength(str(num), font=f)
        d.text((cx - tw / 2, cy - 190), str(num), font=f, fill=(240, 236, 228, 235))
        if t is not None and frac < 0.08:
            sc._ev(sfx, tt, "label")
    im = cn._head(im, kick, title, sub, watermark, t)
    if out:
        im.save(out, quality=94)
    return im
