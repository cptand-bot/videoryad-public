# -*- coding: utf-8 -*-
"""ЦИТАТА НА ЛОСКУТЕ БУМАГИ — вырванный клочок с текстом и маркером.

Устройство кадра (как просил пользователь 21.10):
  сверху  — кикер и короткий заголовок;
  ниже    — лоскут бумаги примерно на 75% ширины, вырванный по всем
            четырём краям, с тенью и лёгким наклоном;
  на нём  — текст цитаты тёмным по бумаге;
  маркер  — ПОДЧЁРКИВАНИЕ жёлтым под ключевой фразой, прочерчивается
            слева направо (в `quote_marker` фраза заливается, здесь —
            именно подчёркивается, как ручкой-маркером по бумаге).
"""
import os, sys, math, random
sys.path.insert(0, os.path.expanduser("~/.claude/skills/news-video/fullcycle"))
sys.path.insert(0, os.path.expanduser("~/.claude/skills/news-video/template"))
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import style_cards as sc

PAPER = (247, 244, 236)          # бумага
INK = (28, 26, 24)               # текст на бумаге
INK_SOFT = (96, 92, 86)          # автор на бумаге
MARKER = (255, 206, 26)          # маркер


def _torn_rect(size, box, seed, amp=13, teeth=5):
    """Маска лоскута: прямоугольник с вырванными краями по всем сторонам."""
    w, h = size
    x0, y0, x1, y1 = box
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, math.tau) for _ in range(8)]

    def wobble(u, a, b, k1, k2, k3):
        return (amp * math.sin(u * math.tau * 0.9 + ph[a])
                + amp * 0.5 * math.sin(u * math.tau * 2.7 + ph[b])
                + teeth * 0.8 * math.sin(u * math.tau * k1 + ph[a])
                + teeth * 0.5 * math.sin(u * math.tau * k2 + ph[b])
                + teeth * 0.3 * math.sin(u * math.tau * k3 + ph[(a + 1) % 8]))

    for y in range(int(y0), int(y1)):
        u = (y - y0) / max(1, y1 - y0)
        lx = x0 + wobble(u, 0, 1, 17, 29, 47)
        rx = x1 + wobble(u, 2, 3, 19, 31, 53)
        d.line([(lx, y), (rx, y)], fill=255)
    # верх и низ дорываем отдельно: стираем полосу над/под кривой
    for x in range(int(x0) - 40, int(x1) + 40):
        u = (x - x0) / max(1, x1 - x0)
        ty = y0 + wobble(u, 4, 5, 13, 23, 41)
        by = y1 + wobble(u, 6, 7, 11, 27, 43)
        d.line([(x, y0 - 60), (x, ty)], fill=0)
        d.line([(x, by), (x, y1 + 60)], fill=0)
    return m


def _paper_fill(size, seed):
    """Бумага: тёплый тон, волокна, мягкий градиент к краю."""
    w, h = size
    rng = np.random.default_rng(seed)
    a = np.zeros((h, w, 3), np.float32)
    a[:] = np.array(PAPER, np.float32)
    a += rng.normal(0, 3.4, (h, w, 1))                     # зерно
    a += rng.normal(0, 1.2, (1, w, 3)) * 2                 # вертикальные волокна
    yy = np.linspace(-1, 1, h)[:, None, None]
    a -= 9.0 * np.abs(yy) ** 2                             # лёгкое затемнение к верху/низу
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _marker_underline(size, x0, x1, y, seed, grow=1.0, thick=17):
    """Полоса маркера ПОД строкой: неровная, с ослабевающим нажимом."""
    w, h = size
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, math.tau) for _ in range(3)]
    xe = x0 + (x1 - x0) * max(0.0, min(1.0, grow))
    for x in range(int(x0), int(xe)):
        u = (x - x0) / max(1.0, x1 - x0)
        dy = 2.4 * math.sin(u * math.tau * 1.6 + ph[0]) + 1.3 * math.sin(u * math.tau * 5.3 + ph[1])
        tk = thick * (0.80 + 0.28 * (0.5 + 0.5 * math.sin(u * math.tau * 2.2 + ph[2])))
        fade = 255 if u < 0.9 else int(255 * (1 - (u - 0.9) / 0.1) ** 0.5)
        d.line([(x, y + dy - tk / 2), (x, y + dy + tk / 2)], fill=max(0, fade))
    return m.filter(ImageFilter.GaussianBlur(1.3))


def quote_paper(out=None, kick="", title="", text="", author="", source="",
                accent=None, watermark="ДИПЛОМАТИЯ СИЛЫ", t=None, sfx=None,
                seed=17, tilt=-1.1):
    im = sc.canvas()
    W, H = sc.W, sc.H

    # --- шапка: кикер и короткий заголовок -------------------------------
    a0, dx0 = sc._rv(t, 0.05)
    if a0 > 0:
        sc._ev(sfx, 0.05, "label")
        im = sc._put(im, lambda d: sc.kicker(d, 92, kick, dot=True, t=t), a0, dx0)
    if title:
        a1, dx1 = sc._rv(t, 0.14)
        if a1 > 0:
            im = sc._put(im, lambda d: sc.track(d, (sc.MARGIN_L - 120, 140), title,
                                                sc._f(sc.F_HEAD, 46),
                                                sc.WHITE + (int(255 * a1),), spacing=2),
                         a1, dx1)

    # --- лоскут бумаги ----------------------------------------------------
    pw, ph_ = int(W * 0.76), 560
    x0, y0 = (W - pw) // 2, 330
    box = (x0, y0, x0 + pw, y0 + ph_)
    ap, dxp = sc._rv(t, 0.22)
    if ap <= 0:
        if out:
            im.save(out, quality=94); return out
        return im
    sc._ev(sfx, 0.22, "accent")

    mask = _torn_rect((W, H), box, seed)
    paper = _paper_fill((W, H), seed)

    # текст пишем прямо на бумажном слое, чтобы он жил вместе с лоскутом
    pd = ImageDraw.Draw(paper)
    f = sc._f(sc.F_HEAD, 58)
    pad = 86
    maxw = pw - 2 * pad
    words, lines, cur = text.split(" "), [], ""
    for w_ in words:
        probe = (cur + " " + w_).strip()
        if f.getlength(probe) > maxw and cur:
            lines.append(cur); cur = w_
        else:
            cur = probe
    lines.append(cur)

    ty = y0 + 92
    marks = []                                   # где чертить маркер
    for i, ln in enumerate(lines):
        at = 0.34 + i * 0.16
        av, _ = sc._rv(t, at)
        if av <= 0:
            ty += 76
            continue
        sc._ev(sfx, at, "label")
        pd.text((x0 + pad, ty), ln, font=f, fill=INK)
        if accent and accent in ln:
            k = ln.index(accent)
            ax0 = x0 + pad + f.getlength(ln[:k])
            ax1 = ax0 + f.getlength(accent)
            grow = 1.0 if t is None else max(0.0, min(1.0, (t - at - 0.12) / 0.5))
            if grow > 0:
                marks.append((ax0 - 8, ax1 + 10, ty + 66, grow))
        ty += 76

    if author:
        aa, _ = sc._rv(t, 0.34 + len(lines) * 0.16 + 0.1)
        if aa > 0:
            pd.text((x0 + pad, ty + 26), "— " + author,
                    font=sc._f(sc.MONO, 26), fill=INK_SOFT)

    # маркер поверх текста, но под краями лоскута
    for (mx0, mx1, my, grow) in marks:
        mm = _marker_underline((W, H), mx0, mx1, my, seed + 5, grow)
        paint = Image.new("RGB", (W, H), MARKER)
        paper = Image.composite(paint, paper, mm.point(lambda v: int(v * 0.88)))

    # наклон лоскута вместе с содержимым
    if tilt:
        paper = paper.rotate(tilt, resample=Image.BICUBIC, center=(W // 2, y0 + ph_ // 2))
        mask = mask.rotate(tilt, resample=Image.BICUBIC, center=(W // 2, y0 + ph_ // 2))

    # тень под лоскутом
    sh = mask.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.72))
    sh = sh.transform((W, H), Image.AFFINE, (1, 0, -14, 0, 1, -16))
    base = np.asarray(im, np.float32)
    base *= (1 - 0.62 * (np.asarray(sh, np.float32) / 255.0)[..., None])
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    im = Image.composite(paper, im, mask)

    d = ImageDraw.Draw(im)
    sc.footer(d, source, watermark)
    if out:
        im.save(out, quality=94); return out
    return im


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "quote_paper.jpg"
    quote_paper(out, kick="Минск, 16 октября 2026", title="ЧТО СКАЗАЛ ЛУКАШЕНКО",
                text="Садитесь и договаривайтесь сейчас. Потом будет сложнее. "
                     "Потом ещё сложнее. А потом может стать вообще невозможно",
                author="Александр Лукашенко, президент Белоруссии",
                source="публичное заявление, октябрь 2026",
                accent="вообще невозможно", watermark="АРСЕНАЛ")
    print("готово:", out)
