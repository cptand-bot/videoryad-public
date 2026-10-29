#!/usr/bin/env python3
"""КИНОШНЫЕ ПРИЁМЫ — пять рабочих элементов (приняты 2026-10-21).

Из шести эскизов пользователь отклонил двойную экспозицию («корявенько»),
остальные пять утвердил целиком. Здесь они доведены до элементов с
движением: каждая функция принимает t и рисуется через
style_cards.render_anim, то есть получает и ступенчатый зум в хвосте.

  depth_of_field  — фон в боке, резкость на лице; фокус переводится в кадре
  cinema_look     — формат 2.39, киношный цвет, анаморфный блик
  dossier         — папка: строки печатаются, штамп впечатывается
  evidence_wall   — снимки на булавках, нити протягиваются по очереди
  trailer_title   — удар текстом, красная черта, вспышка
"""
import functools
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "template"))
import style_cards as sc
import random as _random

W, H = sc.W, sc.H


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _fit(path, size=(W, H), zoom=1.0, shift=0.0):
    im = Image.open(path).convert("RGB")
    w, h = size
    k = max(w / im.width, h / im.height) * zoom
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    free = max(0, im.width - w)
    x = int(free * (0.5 + shift / 2))
    y = max(0, (im.height - h) // 2)
    return im.crop((x, y, x + w, y + h))


def focus_point(path, part=0.40):
    """Точка интереса с поправкой на композицию.

    Голая детальность уводила фокус на яркий флаг у края кадра (поймано
    21.10), поэтому карта перепадов взвешивается гауссом к центру по
    горизонтали и к верхней трети по вертикали — там, где в портрете
    голова.
    """
    im = Image.open(path).convert("L")
    sm = im.resize((160, max(1, int(160 * im.height / im.width))), Image.BILINEAR)
    a = np.asarray(sm, np.float32)
    g = (np.abs(np.diff(a, axis=1, prepend=a[:, :1])) +
         np.abs(np.diff(a, axis=0, prepend=a[:1, :])))
    yy, xx = np.mgrid[0:sm.height, 0:sm.width]
    g = g * np.exp(-((xx / sm.width - 0.5) ** 2) / 0.10) \
          * np.exp(-((yy / sm.height - 0.38) ** 2) / 0.08)
    ww, hh = max(2, int(sm.width * part)), max(2, int(sm.height * part))
    ii = np.pad(np.cumsum(np.cumsum(g, 0), 1), ((1, 0), (1, 0)))
    best, bxy = -1.0, (0.5, 0.42)
    for y in range(0, sm.height - hh + 1, 3):
        for x in range(0, sm.width - ww + 1, 3):
            v = ii[y + hh, x + ww] - ii[y, x + ww] - ii[y + hh, x] + ii[y, x]
            if v > best:
                best, bxy = v, ((x + ww / 2) / sm.width, (y + hh / 2) / sm.height)
    return bxy


def _head(im, kick="", title="", sub="", watermark="ДИПЛОМАТИЯ СИЛЫ", t=None, dark=True):
    a, _ = sc._rv(t, 0.12)
    if a > 0 and (kick or title):
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay, "RGBA")
        if dark:
            d.rectangle((0, 0, 1020, 258), fill=(8, 8, 9, 130))
        if kick:
            d.ellipse((150, 92, 164, 106), fill=sc.RED + (int(255 * a),))
            d.text((178, 86), " ".join(kick.upper()), font=sc._f(sc.F_HEAD, 24),
                   fill=sc.GOLD + (int(240 * a),))
        if title:
            d.text((150, 126), title, font=sc._f(sc.F_HEAD, 52), fill=(255, 255, 255, int(255 * a)))
        if sub:
            d.text((150, 192), sub, font=sc._f(sc.F_HEAD, 30), fill=(214, 214, 218, int(230 * a)))
        im = Image.alpha_composite(im.convert("RGBA"), lay).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    sc.footer(d, "", watermark=watermark)
    return im


# ─────────────────────────── 1. ГЛУБИНА РЕЗКОСТИ ─────────────────────────
def depth_of_field(out=None, *, photo="", kick="", title="", sub="",
                   watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=7.0, t=None, sfx=None,
                   blur=18, bokeh=22, pull=True):
    """Фон уходит в боке, резким остаётся герой.

    pull=True — фокус ПЕРЕВОДИТСЯ: первые полторы секунды резок весь кадр,
    потом фон мягко уходит. Это тот самый приём с переводом фокуса, а не
    просто размытая подложка.
    """
    tt = seconds if t is None else t
    base = _fit(photo)
    fx, fy = focus_point(photo)

    k = 1.0 if not pull else _ease((tt - 0.5) / 1.3)
    if k <= 0.01:
        im = base
    else:
        bk = base.filter(ImageFilter.GaussianBlur(blur * k))
        if bokeh:
            d = ImageDraw.Draw(bk, "RGBA")
            rnd = random.Random(7)
            for _ in range(bokeh):
                r = rnd.randint(26, 74)
                x, y = rnd.randint(0, W), rnd.randint(0, int(H * 0.85))
                d.ellipse((x, y, x + r, y + r), fill=(255, 238, 200, int(rnd.randint(10, 26) * k)))
            bk = bk.filter(ImageFilter.GaussianBlur(6))
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).ellipse((int(W * fx) - 470, int(H * fy) - 410,
                                      int(W * fx) + 470, int(H * fy) + 470), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(150))
        im = Image.composite(base, bk, mask)
    sc._ev(sfx, 0.5, "accent")
    im = _head(im, kick, title, sub, watermark, t)
    if out:
        im.save(out, quality=94)
    return im


# ──────────────────────────── 2. КИНОЛУК 2.39 ────────────────────────────
def cinema_look(out=None, *, photo="", kick="", title="", sub="",
                watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=7.0, t=None, sfx=None,
                flare=True, grain=3.4):
    """Широкий формат, киношная вилка цвета и анаморфный блик."""
    tt = seconds if t is None else t
    base = _fit(photo)
    a = np.asarray(base, np.float32)
    sh = np.clip(1 - a.mean(2, keepdims=True) / 255.0, 0, 1)[..., 0]
    a[..., 2] += 26 * sh
    a[..., 0] += 20 * (1 - sh)
    a[..., 1] += 6 * (1 - sh)
    a = (a - 128) * 1.12 + 120
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    if flare:
        # блик проходит один раз слева направо, а не висит на месте
        p = 0.5 if t is None else max(0.0, min(1.0, (tt - 0.9) / 2.2))
        if 0 < p < 1 or t is None:
            cx = W * (0.18 + 0.72 * p)
            fl = Image.new("L", (W, H), 0)
            ImageDraw.Draw(fl).ellipse((cx - W * 0.26, H * 0.30, cx + W * 0.26, H * 0.345), fill=150)
            fl = fl.filter(ImageFilter.GaussianBlur(30))
            g = np.asarray(fl, np.float32)[..., None] / 255.0
            arr = np.asarray(im, np.float32) + g * np.array([70, 140, 255], np.float32)
            im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if grain:
        n = np.random.default_rng(3).normal(0, grain, (H, W, 1))
        im = Image.fromarray(np.clip(np.asarray(im, np.float32) + n, 0, 255).astype(np.uint8))

    im = _head(im, kick, title, sub, watermark, t, dark=False)
    # поля формата 2.39 кладём ПОВЕРХ подписей, чтобы те не торчали в поле
    bar = int((H - W / 2.39) / 2)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, bar), fill=(0, 0, 0))
    d.rectangle((0, H - bar, W, H), fill=(0, 0, 0))
    if out:
        im.save(out, quality=94)
    return im


# ──────────────────────────────── 3. ДОСЬЕ ───────────────────────────────
def dossier(out=None, *, case="", rows=(), photo="", stamp="ПЕРВОИСТОЧНИК",
            kick="", title="", sub="", watermark="ДИПЛОМАТИЯ СИЛЫ",
            seconds=9.0, t=None, sfx=None):
    """Папка с документом: строки печатаются, штамп впечатывается с ударом."""
    tt = seconds if t is None else t
    im = sc.canvas()
    pw, ph = 1180, 820
    px, py = 370, 236

    paper = Image.new("RGB", (pw, ph), (238, 234, 224))
    rng = np.random.default_rng(5)
    paper = Image.fromarray(np.clip(np.asarray(paper, np.float32) +
                                    rng.normal(0, 4.0, (ph, pw, 1)), 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(paper)
    a_case = _ease((tt - 0.35) / 0.4)
    if a_case > 0:
        d.text((70, 70), case, font=sc._f(sc.MONO, 34), fill=(42, 40, 36))
        d.line((70, 126, pw - 70, 126), fill=(120, 116, 108), width=2)

    # строки печатаются по буквам, как на машинке
    for i, ln in enumerate(rows):
        at = 0.9 + i * 0.55
        p = (tt - at) / 0.45
        if p <= 0:
            break
        sc._ev(sfx, at, "label")
        n = len(ln) if p >= 1 else max(1, int(len(ln) * p))
        d.text((70, 170 + i * 56), ln[:n], font=sc._f(sc.MONO, 28), fill=(54, 50, 46))

    if photo:
        a_ph = _ease((tt - (0.9 + len(rows) * 0.55)) / 0.5)
        if a_ph > 0:
            pic = _fit(photo, (330, 230))
            pic = Image.fromarray(np.clip(np.asarray(pic, np.float32) * a_ph, 0, 255).astype(np.uint8))
            paper.paste(pic, (750, 470))
            d.rectangle((748, 468, 1082, 702), outline=(90, 86, 80), width=3)

    # штамп: приходит крупнее и «вдавливается»
    at_st = 0.9 + len(rows) * 0.55 + 0.75
    p_st = (tt - at_st) / 0.35
    if p_st > 0 and stamp:
        sc._ev(sfx, at_st, "accent")
        scale = 1.0 + 0.5 * max(0.0, 1 - min(1.0, p_st)) ** 2
        st = Image.new("RGBA", (560, 150), (0, 0, 0, 0))
        sd = ImageDraw.Draw(st)
        sd.rectangle((4, 4, 556, 146), outline=(176, 36, 32, 225), width=7)
        sd.text((40, 38), stamp, font=sc._f(sc.F_HEAD, 58), fill=(176, 36, 32, 230))
        st = st.rotate(-9, resample=Image.BICUBIC, expand=True)
        if scale != 1.0:
            st = st.resize((int(st.width * scale), int(st.height * scale)), Image.LANCZOS)
        paper.paste(st, (int(90 - (st.width - 560) / 2), int(560 - (st.height - 150) / 2)), st)

    # тень папки
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).rectangle((px + 10, py + 16, px + pw + 10, py + ph + 16), fill=190)
    sh = sh.filter(ImageFilter.GaussianBlur(30))
    arr = np.asarray(im, np.float32) * (1 - 0.55 * (np.asarray(sh, np.float32) / 255.0)[..., None])
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    im.paste(paper, (px, py))
    d2 = ImageDraw.Draw(im, "RGBA")
    d2.rectangle((px - 2, py - 2, px + pw + 1, py + ph + 1), outline=(120, 118, 112, 140), width=2)
    # скрепка
    d2.arc((1230, 196, 1330, 300), 180, 360, fill=(198, 200, 206, 255), width=9)
    d2.line((1230, 248, 1230, 392), fill=(198, 200, 206, 255), width=9)
    d2.line((1330, 248, 1330, 350), fill=(198, 200, 206, 255), width=9)
    d2.arc((1230, 330, 1330, 420), 0, 180, fill=(198, 200, 206, 255), width=9)

    im = _head(im, kick, title, sub, watermark, t)
    if out:
        im.save(out, quality=94)
    return im


# ───────────────────────────── 4. СТЕНА УЛИК ─────────────────────────────
def evidence_wall(out=None, *, shots=(), back="", kick="", title="", sub="",
                  watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=10.0, t=None, sfx=None):
    """Снимки на булавках: карточки приходят по очереди, затем между ними
    протягиваются красные нити — связь видна буквально.

    shots — ((путь, x, y, наклон, подпись), ...)
    """
    tt = seconds if t is None else t
    im = sc.canvas()
    if back:
        im = Image.blend(im, _fit(back).filter(ImageFilter.GaussianBlur(10)), 0.22)

    pts = []
    for i, (path, x, y, ang, cap) in enumerate(shots):
        at = 0.4 + i * 0.5
        a_c = _ease((tt - at) / 0.4)
        card = _fit(path, (300, 210))
        fr = Image.new("RGB", (324, 258), (242, 240, 234))
        fr.paste(card, (12, 12))
        fd = ImageDraw.Draw(fr)
        fd.text((16, 228), cap, font=sc._f(sc.MONO, 19), fill=(54, 52, 48))
        fr = fr.rotate(ang, resample=Image.BICUBIC, expand=True)
        cx, cy = x + fr.width // 2, y + 10
        pts.append((cx, cy, at))
        if a_c <= 0:
            continue
        sc._ev(sfx, at, "label")
        sh = Image.new("L", (W, H), 0)
        sh.paste(Image.new("L", fr.size, 190), (x + 8, y + 12))
        sh = sh.filter(ImageFilter.GaussianBlur(18))
        arr = np.asarray(im, np.float32) * (1 - 0.5 * a_c * (np.asarray(sh, np.float32) / 255.0)[..., None])
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        if a_c < 1.0:
            fr = Image.fromarray(np.clip(np.asarray(fr.convert("RGB"), np.float32) * a_c,
                                         0, 255).astype(np.uint8))
        im.paste(fr, (x, int(y + 26 * (1 - a_c))))

    d = ImageDraw.Draw(im, "RGBA")
    for i in range(len(pts) - 1):
        (x1, y1, a1), (x2, y2, a2) = pts[i], pts[i + 1]
        at = max(a1, a2) + 0.45
        p = _ease((tt - at) / 0.4)
        if p <= 0:
            continue
        sc._ev(sfx, at, "accent")
        d.line([(x1, y1), (int(x1 + (x2 - x1) * p), int(y1 + (y2 - y1) * p))],
               fill=(180, 40, 38, 225), width=3)
    for (x, y, at) in pts:
        if tt >= at:
            d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(214, 60, 56, 255))

    im = _head(im, kick, title, sub, watermark, t)
    if out:
        im.save(out, quality=94)
    return im


# ─────────────────────────── 5. ТРЕЙЛЕРНАЯ ТИТРА ─────────────────────────
def trailer_title(out=None, *, title="", sub="", watermark="ДИПЛОМАТИЯ СИЛЫ",
                  seconds=6.0, t=None, sfx=None, size=112, spacing=16):
    """Удар текстом на чёрном: разрядка, красная черта, вспышка-засвет."""
    tt = seconds if t is None else t
    im = Image.new("RGB", (W, H), sc.bg(0.82))
    a = np.asarray(im, np.float32)
    yy = np.linspace(-1, 1, H)[:, None, None]
    im = Image.fromarray(np.clip(a + np.clip(34 * (1 - np.abs(yy)), 0, 255), 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")

    a_t = _ease((tt - 0.35) / 0.3)
    if a_t > 0:
        sc._ev(sfx, 0.35, "accent")
        f = sc._f(sc.F_HEAD, size)
        sc.track(d, (260, 420), title, f, (255, 255, 255, int(255 * a_t)), spacing=spacing)
    a_l = _ease((tt - 0.72) / 0.45)
    if a_l > 0:
        d.line((264, 580, 264 + int(1396 * a_l), 580), fill=(176, 36, 32, 255), width=4)
    a_s = _ease((tt - 1.1) / 0.4)
    if a_s > 0 and sub:
        sc.track(d, (266, 614), sub, sc._f(sc.MONO, 34), (214, 214, 218, int(230 * a_s)), spacing=10)

    # вспышка идёт один раз вместе с приходом текста
    p = (tt - 0.35) / 0.9
    if 0 < p < 1 or t is None:
        pp = 0.5 if t is None else p
        fl = Image.new("L", (W, H), 0)
        x = int(W * (0.1 + 0.9 * pp))
        ImageDraw.Draw(fl).polygon([(x, H), (x + 200, H), (x + 600, 0), (x + 400, 0)], fill=90)
        fl = fl.filter(ImageFilter.GaussianBlur(70))
        arr = np.asarray(im, np.float32) + np.asarray(fl, np.float32)[..., None] * 0.9
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    d = ImageDraw.Draw(im, "RGBA")
    sc.footer(d, "", watermark=watermark)
    if out:
        im.save(out, quality=94)
    return im


# ──────────────── 6. FLASHBACK С ПОЛЯ БОЯ (21.10) ───────────────────────
def _blob(size, cx, cy, r, seed, lobes=7):
    """Клякса копоти: несколько слипшихся пятен с рваным краем."""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    rnd = random.Random(seed)
    for i in range(lobes):
        a = rnd.uniform(0, math.tau)
        dist = rnd.uniform(0, r * 0.55)
        rr = r * rnd.uniform(0.35, 0.95)
        x = cx + math.cos(a) * dist
        y = cy + math.sin(a) * dist
        d.ellipse((x - rr, y - rr * rnd.uniform(0.7, 1.2),
                   x + rr, y + rr * rnd.uniform(0.7, 1.2)), fill=255)
    # брызги вокруг
    for _ in range(rnd.randint(6, 16)):
        a = rnd.uniform(0, math.tau)
        dist = r * rnd.uniform(0.9, 2.2)
        rr = r * rnd.uniform(0.05, 0.18)
        x, y = cx + math.cos(a) * dist, cy + math.sin(a) * dist
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(r * 0.08))
    a = np.asarray(m, np.float32)
    a = np.clip((a - 90) * 3.2, 0, 255)          # порог — край становится рваным
    return Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))


def battle_flashback(out=None, *, photo="", seed=7, soot=14, burn=1.0,
                     vignette=0.8, density=0.62, kick="", title="", subtitle="",
                     watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=7.0, t=None, sfx=None,
                     waves=3):
    """FLASHBACK С ПОЛЯ БОЯ — копоть, осколки, выжженный свет.

    Сделано по образцу, который прислал пользователь (21.10). Правила,
    выведенные из образца и первой пробы:
      · копоть НЕ ЗАКРЫВАЕТ ГЕРОЯ — вокруг точки интереса держится чистая
        зона, иначе лицо заливает чёрным и кадр умирает;
      · пятна полупрозрачные, с рваным краем и брызгами, плюс вертикальные
        потёртости, как на стекле и плёнке;
      · свет выжжен: контраст вверх, тени в холод, света в тепло;
      · в движении пятна приходят ВОЛНАМИ, и на каждой волне кадр коротко
        темнеет — это и есть «мелькание» флешбэка.
    """
    base = _fit(photo)
    # ЛИЦО НЕ ЗАКРЫВАЕМ (правка 21.10): на образце копоть идёт по краям и
    # по фону, а герой остаётся читаемым. Берём ту же точку интереса, что
    # и остальной арсенал, и держим вокруг неё чистую зону.
    fx, fy = focus_point(photo, 0.34)
    safe = (fx * W, fy * H, min(W, H) * 0.30)
    a = np.asarray(base, np.float32)

    # выжженный свет: контраст вверх, тени в холод, света в тепло
    sh = np.clip(1 - a.mean(2, keepdims=True) / 255.0, 0, 1)[..., 0]
    a[..., 2] += 22 * sh * burn
    a[..., 0] += 26 * (1 - sh) * burn
    a[..., 1] += 10 * (1 - sh) * burn
    a = (a - 128) * (1.0 + 0.34 * burn) + 118
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    # копоть: тёмные кляксы по краям и частично на кадре
    # сколько копоти уже «прилетело» к этому моменту
    if t is None:
        shown, flick = 1.0, 1.0
    else:
        p = max(0.0, min(1.0, t / max(0.1, seconds * 0.62)))
        step = 1.0 / waves
        k = min(waves, int(p / step) + 1)
        shown = k / waves
        # короткое затемнение в момент каждой волны
        edge = (p % step) / step
        flick = 1.0 - 0.45 * math.exp(-((edge) ** 2) / 0.0024) if p > 0.02 else 1.0
        if edge < 0.03:
            sc._ev(sfx, t, "accent")
    soot = max(1, int(soot * shown))
    rnd = random.Random(seed)
    soot_mask = Image.new("L", (W, H), 0)
    placed = 0
    tries = 0
    while placed < soot and tries < soot * 12:
        tries += 1
        edge = placed < soot * 0.75
        cx = rnd.choice([rnd.uniform(-60, W * 0.26), rnd.uniform(W * 0.74, W + 60)]) if edge else rnd.uniform(W * 0.15, W * 0.85)
        cy = rnd.choice([rnd.uniform(-40, H * 0.26), rnd.uniform(H * 0.74, H + 40)]) if edge else rnd.uniform(H * 0.1, H * 0.9)
        r = rnd.uniform(45, 150) * (1.3 if edge else 0.55)
        if math.hypot(cx - safe[0], cy - safe[1]) < safe[2] + r * 0.7:
            continue                      # в чистую зону не лезем
        b = _blob((W, H), cx, cy, r, seed * 31 + placed)
        soot_mask = Image.fromarray(np.maximum(np.asarray(soot_mask), np.asarray(b)))
        placed += 1

    # вертикальные потёртости, как на плёнке и на стекле
    sd = ImageDraw.Draw(soot_mask)
    for _ in range(rnd.randint(3, 6)):
        x = rnd.uniform(0, W)
        if abs(x - safe[0]) < safe[2]:
            continue
        sd.line((x, 0, x + rnd.uniform(-40, 40), H), fill=rnd.randint(70, 150),
                width=rnd.randint(2, 7))
    soot_mask = soot_mask.filter(ImageFilter.GaussianBlur(3))
    sm = (np.asarray(soot_mask, np.float32) / 255.0)[..., None]
    arr = np.asarray(im, np.float32) * (1 - density * sm)   # копоть полупрозрачна
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # виньетка — глухая, как на образце
    v = Image.new("L", (W, H), 0)
    ImageDraw.Draw(v).ellipse((-W * 0.22, -H * 0.3, W * 1.22, H * 1.3), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(210))
    vv = (np.asarray(v, np.float32) / 255.0)[..., None]
    arr = np.asarray(im, np.float32) * (1 - vignette * 0.75 * (1 - vv))
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # пыль и мелкие осколки в воздухе
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(rnd.randint(40, 70)):
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        r = rnd.uniform(1, 3.4)
        d.ellipse((x, y, x + r, y + r), fill=(228, 220, 206, rnd.randint(18, 70)))
    gseed = seed if t is None else seed + int(t * 25) // 2
    n = np.random.default_rng(gseed).normal(0, 4.5, (H, W, 1))
    im = Image.fromarray(np.clip(np.asarray(im, np.float32) * flick + n, 0, 255).astype(np.uint8))
    im = _head(im, kick, title, subtitle, watermark, t)
    if out:
        im.save(out, quality=94)
    return im


# ───────── РАЗЛЁТ КУСКОВ: центр стоит, периферия улетает (21.10) ────────
def _angle_noise(seed, harmonics=18):
    """Случайная периодическая функция угла — рваность границ.

    Гармоник много и спад пологий: без высоких составляющих край выходит
    гладким, и куски выглядят вырезанными ножницами, а не оторванными
    (поймано 21.10 на первой пробе).
    """
    rnd = np.random.default_rng(seed)
    amps = rnd.uniform(0.3, 1.0, harmonics) / (np.arange(1, harmonics + 1) ** 0.55)
    phs = rnd.uniform(0, math.tau, harmonics)
    def f(th):
        out = np.zeros_like(th)
        for k, (a, p) in enumerate(zip(amps, phs), start=1):
            out += a * np.sin(k * th + p)
        return out / np.sum(amps)
    return f


@functools.lru_cache(maxsize=4)
def burst_masks(pieces=6, seed=23, core=0.30, jag=0.22, cx=0.5, cy=0.46):
    """Маски: центральный кусок и `pieces` секторов вокруг, все с рваными краями.

    КЭШИРУЕТСЯ: форма разрыва за клип не меняется, а пересчёт на каждом
    кадре съедал память — рендер молча убивало нехваткой ОЗУ (21.10).
    Координатные сетки держим во float32: во float64 они весили вдвое.
    """
    yy, xx = np.mgrid[0:H, 0:W]
    yy = yy.astype(np.float32); xx = xx.astype(np.float32)
    px, py = cx * W, cy * H
    dx, dy = xx - px, yy - py
    r = np.hypot(dx, dy)
    th = np.arctan2(dy, dx)

    nz_r = _angle_noise(seed)          # рваность границы центра
    nz_a = _angle_noise(seed + 101)    # рваность радиальных разрывов

    base_r = min(W, H) * core
    r_core = base_r * (1 + jag * nz_r(th * 3.0) + 0.05 * nz_r(th * 23.0))
    core_m = (r < r_core)

    # границы секторов гуляют по углу
    th_mod = th + 0.22 * nz_a(th * 2.0 + r / 260.0) + 0.035 * nz_a(th * 17.0 + r / 70.0)
    sector = np.floor(((th_mod + math.pi) / math.tau) * pieces).astype(int) % pieces

    masks = [Image.fromarray((core_m * 255).astype(np.uint8))]
    for i in range(pieces):
        m = (~core_m) & (sector == i)
        masks.append(Image.fromarray((m * 255).astype(np.uint8)))
    centers = []
    for i in range(pieces):
        a = (i + 0.5) / pieces * math.tau - math.pi
        centers.append((math.cos(a), math.sin(a)))
    return masks, centers, (px, py)


def torn_burst(out=None, *, photo="", pieces=7, seed=23, under=1.0,
               kick="", title="", subtitle="", watermark="ДИПЛОМАТИЯ СИЛЫ",
               seconds=7.0, t=None, sfx=None, spread=None, hold=1.2, fly=1.1,
               edge_px=17):
    """РАЗЛЁТ КУСКОВ: верхний слой разрывает и уносит, снизу — чистый кадр.

    Механика уточнена пользователем (21.10, вторая правка): «все куски
    уезжают, а остаётся просто чистое изображение, исходник. И швы,
    рубленые, чуть толще — как у фотографии, которая разъезжается».
    Поэтому:
      · улетают ВСЕ куски, центр тоже — на месте ничего не держится;
      · нижний слой НЕ ТРОГАЕМ: под разрывом лежит оригинал как есть,
        без затемнения и размытия;
      · кромка разрыва толстая, бумажная, с неровной плотностью — как у
        наших швов, а не тонкая обводка.

    pieces — на сколько кусков рвёт (все улетают)
    spread — ход разлёта; None = считается от t
    """
    if spread is None:
        if t is None:
            spread = 1.0
        else:
            x = max(0.0, min(1.0, (t - hold) / max(0.1, fly)))
            spread = x * x * (3 - 2 * x)
            if 0 < x < 0.1:
                sc._ev(sfx, t, "accent")

    base = _fit(photo)
    # ПОД РАЗРЫВОМ — ЧИСТЫЙ ИСХОДНИК (21.10)
    im = base.copy() if under >= 1.0 else Image.fromarray(
        np.clip(np.asarray(base, np.float32) * under, 0, 255).astype(np.uint8))

    masks, dirs, (px, py) = burst_masks(pieces, seed, cx=0.5, cy=0.46)
    rnd = _random.Random(seed)
    paper = Image.new("RGB", (W, H), (242, 240, 234))

    # каждый кусок уходит наружу; порядок — дальние первыми, чтобы
    # перекрытия выглядели естественно
    order = list(range(len(masks)))
    for i in order:
        m = masks[i]
        # КУСКИ УХОДЯТ ЗА КРАЙ ПОЛНОСТЬЮ (21.10, третья правка: «они улетают
        # с видимой части экрана, не остаются застрявшими где-то на краях»).
        # Прежние 520-600 px хватало только на то, чтобы сдвинуть кусок
        # размером в пол-экрана: он так и висел у рамки. Нужен ход больше
        # диагонали кадра, с разгоном к концу.
        far = math.hypot(W, H) * 1.35                        # ~2680 px
        if i == 0:
            ux = math.cos(-0.5); uy = math.sin(-0.5)          # центр тоже улетает
            d = far * spread ** 1.8
        else:
            ux, uy = dirs[i - 1]
            d = far * spread ** 1.7
        ox, oy = ux * d, uy * d - 90 * spread
        ang = (13 if i % 2 else -10) * spread

        piece = Image.new("RGB", (W, H), (0, 0, 0))
        piece.paste(base, (0, 0), m)
        mm = m
        if ang:
            piece = piece.rotate(ang, resample=Image.BICUBIC, center=(px, py))
            mm = mm.rotate(ang, resample=Image.BICUBIC, center=(px, py))
        piece = piece.transform((W, H), Image.AFFINE, (1, 0, -ox, 0, 1, -oy),
                                resample=Image.BILINEAR)
        mm = mm.transform((W, H), Image.AFFINE, (1, 0, -ox, 0, 1, -oy),
                          resample=Image.BILINEAR)

        # тень: считаем на уменьшенной маске и растягиваем обратно
        small = mm.resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(5))
        sh = small.resize((W, H), Image.BILINEAR)
        a = np.asarray(im, np.float32)
        a *= (1 - 0.62 * spread * (np.asarray(sh, np.float32) / 255.0)[..., None])
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        del a, sh, small
        im.paste(piece, (0, 0), mm)

        # ТОЛСТАЯ БУМАЖНАЯ КРОМКА по контуру куска, с неровной плотностью
        grown = mm.filter(ImageFilter.MaxFilter(edge_px if edge_px % 2 else edge_px + 1))
        band = np.clip(np.asarray(grown, np.float32) - np.asarray(mm, np.float32), 0, 255)
        wob = np.random.default_rng(seed * 7 + i).normal(1.0, 0.35, (H // 8, W // 8))
        wob_im = Image.fromarray(np.clip(wob * 128, 0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)
        band = np.clip(band * (np.asarray(wob_im, np.float32) / 128.0) * spread, 0, 255).astype(np.uint8)
        im.paste(paper, (0, 0), Image.fromarray(band))
        del band, wob, wob_im, piece, mm, grown

    im = _head(im, kick, title, subtitle, watermark, t)
    if out:
        im.save(out, quality=94)
    return im
