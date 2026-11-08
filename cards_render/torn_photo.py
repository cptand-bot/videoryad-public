# -*- coding: utf-8 -*-
"""Композит «тогда / сейчас» через разрыв бумаги.

Снято с образца, который пользователь дал 19.10.2026 (гостиница «Бристоль»,
Одесса, 1899 / 2024): архивный кадр живёт вертикальной полосой в центре,
современный — по краям, между ними рваный край бумаги с белой кромкой и
тенью. Годы подписаны по углам, адрес — в шапке.

Разрыв НЕ берётся готовой текстурой: он строится процедурно, поэтому у
каждого композита свой уникальный край, а край подгоняется под кадр
(амплитуда, частота зазубрин, толщина кромки).

Как устроен край (три слагаемых, иначе получается «пила» из фотошопа):
 1. крупная волна — куда вообще гуляет линия разрыва;
 2. средние зазубрины — характерный рваный ритм бумаги;
 3. мелкие волокна — редкие острые выступы на 1-2 пикселя, именно они
    дают ощущение бумаги, а не ножниц.

Кромка рисуется как полоса белого вдоль линии разрыва с переменной
шириной (бумага рвётся неровно) и мягкой тенью на нижний слой.
"""
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

NV = os.path.expanduser("~/.claude/skills/news-video/template/fonts")
F_HEAD = os.path.join(NV, "RobotoCondensed-Bold.ttf")
F_ALT = os.path.join(NV, "Oswald-Bold.ttf")


def _f(path, size):
    from PIL import ImageFont
    return ImageFont.truetype(path, size)


def _edge(h, x0, seed, amp=34, teeth=13, fibers=True):
    """Вертикальная линия разрыва: x для каждой строки изображения."""
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, math.tau) for _ in range(6)]
    xs = np.zeros(h, np.float32)
    for y in range(h):
        u = y / max(1, h - 1)
        v = (amp * 1.00 * math.sin(u * math.tau * 0.7 + ph[0])
             + amp * 0.55 * math.sin(u * math.tau * 1.9 + ph[1])
             + amp * 0.30 * math.sin(u * math.tau * 4.3 + ph[2])
             + teeth * 0.70 * math.sin(u * math.tau * 23.0 + ph[3])
             + teeth * 0.45 * math.sin(u * math.tau * 41.0 + ph[4])
             + teeth * 0.30 * math.sin(u * math.tau * 67.0 + ph[5]))
        xs[y] = x0 + v
    if fibers:                      # редкие острые волокна
        for _ in range(h // 18):
            y = rnd.randrange(h)
            ln = rnd.randint(2, 7)
            d = rnd.uniform(-1, 1) * teeth * 1.6
            for k in range(ln):
                if 0 <= y + k < h:
                    xs[y + k] += d * (1 - k / ln)
    return xs


def _mask_from_edges(size, left_xs, right_xs):
    """Маска центральной полосы: 255 внутри разрыва, 0 снаружи."""
    w, h = size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    for y in range(h):
        a, b = int(left_xs[y]), int(right_xs[y])
        if b > a:
            d.line([(a, y), (b, y)], fill=255)
    return m


def _edge_band(size, xs, width_px, seed):
    """Белая кромка вдоль линии: полоса переменной ширины."""
    w, h = size
    band = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(band)
    rnd = random.Random(seed + 7)
    ph = rnd.uniform(0, math.tau)
    for y in range(h):
        u = y / max(1, h - 1)
        wd = width_px * (0.65 + 0.5 * (0.5 + 0.5 * math.sin(u * math.tau * 3.1 + ph)))
        x = xs[y]
        d.line([(x - wd / 2, y), (x + wd / 2, y)], fill=255)
    return band


def _fit(img, size, zoom=1.0, dx=0.0, dy=0.0):
    """Кадрирует фото под холст с масштабом и сдвигом (доля ширины/высоты)."""
    w, h = size
    im = img.convert("RGB")
    k = max(w / im.width, h / im.height) * zoom
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    ox = (im.width - w) / 2 + dx * w
    oy = (im.height - h) / 2 + dy * h
    ox = max(0, min(im.width - w, ox))
    oy = max(0, min(im.height - h, oy))
    return im.crop((int(ox), int(oy), int(ox) + w, int(oy) + h))


def archival(img, strength=1.0):
    """Архивный вид: обесцвечивание, тёплый тон, зерно, падение контраста
    по краям. Применяется ТОЛЬКО если исходник цветной и новодельный —
    настоящее архивное фото трогать не нужно."""
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g, cutoff=1)
    a = np.asarray(g, np.float32) / 255.0
    a = np.clip(a * 1.04 - 0.02, 0, 1)
    warm = np.stack([a * 253, a * 246, a * 231], -1)
    out = warm * strength + np.asarray(img.convert("RGB"), np.float32) * (1 - strength)
    im = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    n = np.random.default_rng(5).normal(0, 5.0, (im.height, im.width, 1))
    im = Image.fromarray(np.clip(np.asarray(im, np.float32) + n, 0, 255).astype(np.uint8))
    return im


def _labels(im, size, *, title="", subtitle="", year_old="", year_new="",
            watermark="", ink="light", alpha=1.0):
    """Подписи кладутся ОТДЕЛЬНЫМ слоем: в клипе створки разъезжаются, и
    текст, нарисованный на них, уезжал вместе с картинкой (20.10)."""
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    A = int(255 * max(0.0, min(1.0, alpha)))
    col = (240, 240, 242, A) if ink == "light" else (26, 26, 28, A)
    sha = (0, 0, 0, int(150 * alpha)) if ink == "light" else (255, 255, 255, int(140 * alpha))

    def _t(xy, text, font, fill=col):
        d.text((xy[0] + 2, xy[1] + 2), text, font=font, fill=sha)
        d.text(xy, text, font=font, fill=fill)

    if year_old:
        _t((int(w * 0.040), int(h * 0.040)), year_old, _f(F_ALT, int(h * 0.060)))
    if title:
        _t((int(w * 0.040), int(h * 0.120)), title.upper(), _f(F_HEAD, int(h * 0.042)))
    if subtitle:
        _t((int(w * 0.040), int(h * 0.175)), subtitle.upper(), _f(F_HEAD, int(h * 0.030)),
           (214, 214, 216, A) if ink == "light" else (60, 60, 62, A))
    if year_new:
        f = _f(F_ALT, int(h * 0.060))
        tw = d.textlength(year_new, font=f)
        _t((w - int(w * 0.040) - tw, int(h * 0.880)), year_new, f)
    if watermark:
        f = _f(F_HEAD, int(h * 0.024))
        tw = d.textlength(watermark.upper(), font=f)
        d.text(((w - tw) / 2, int(h * 0.944)), watermark.upper(), font=f,
               fill=(226, 226, 228, int(190 * alpha)))
    im.paste(Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB"), (0, 0))
    return im


def torn_photo(out, *, old_path, new_path, size=(1920, 1080),
               title="", subtitle="", year_old="", year_new="",
               old_fit=None, new_fit=None, band_x=(0.30, 0.66),
               amp=46, teeth=7, edge_px=16, seed=11,
               make_old_archival=False, watermark="", ink="light",
               labels=True):
    """Собирает постер «тогда/сейчас».

    old_fit / new_fit — {"zoom":1.0,"dx":0.0,"dy":0.0}: как кадрировать
    каждый снимок, чтобы здание совпало по месту и масштабу. Это и есть
    вся ручная работа — остальное процедурно.
    band_x — доли ширины, между которыми идёт полоса архивного кадра.
    """
    w, h = size
    if h > w:
        print("тогда/сейчас: вертикальный формат отключён 20.10 — "
              "работаем только прямоугольным кадром 16:9", file=__import__("sys").stderr)
        size = (1920, 1080)
        w, h = size
    old = Image.open(old_path)
    new = Image.open(new_path)
    if make_old_archival:
        old = archival(old)
    base = _fit(new, size, **(new_fit or {}))
    top = _fit(old, size, **(old_fit or {}))

    lx = _edge(h, w * band_x[0], seed, amp, teeth)
    rx = _edge(h, w * band_x[1], seed + 101, amp * 0.9, teeth)
    mask = _mask_from_edges(size, lx, rx)

    # тень от оторванного края на нижний слой
    sh = mask.filter(ImageFilter.GaussianBlur(14))
    a = np.asarray(base, np.float32)
    sm = (np.asarray(sh, np.float32) / 255.0)[..., None]
    mm = (np.asarray(mask, np.float32) / 255.0)[..., None]
    a = a * (1 - 0.55 * np.clip(sm - mm, 0, 1))
    base = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    im = Image.composite(top, base, mask)

    # белая кромка по обоим разрывам
    band = Image.new("L", size, 0)
    for xs, sd in ((lx, seed), (rx, seed + 101)):
        band = ImageChops_lighter(band, _edge_band(size, xs, edge_px, sd))
    paper = Image.new("RGB", size, (250, 249, 246))
    # лёгкая фактура бумаги на кромке
    nz = np.random.default_rng(seed).normal(0, 7.0, (h, w, 1))
    paper = Image.fromarray(np.clip(np.asarray(paper, np.float32) + nz, 0, 255).astype(np.uint8))
    shadow = band.filter(ImageFilter.GaussianBlur(9))
    a = np.asarray(im, np.float32)
    a *= (1 - 0.35 * (np.asarray(shadow, np.float32) / 255.0)[..., None])
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    im = Image.composite(paper, im, band)

    if labels:
        _labels(im, size, title=title, subtitle=subtitle, year_old=year_old,
                year_new=year_new, watermark=watermark, ink=ink)

    if out:
        im.save(out, quality=94)
    return {"im": im, "mask": mask, "band": band, "size": size,
            "lx": lx, "rx": rx, "out": out}


def torn_clip(out_mp4, *, seconds=6.0, fps=25, shift=430, hit_at=1.25,
              zoom_to=1.035, sfx_out=False, **kw):
    """«Тогда/сейчас» В ДВИЖЕНИИ: половины съезжаются к центру и
    пристукиваются (user, 20.10.2026: «правая сторона прикрепляется к
    серединке, левая — тык-тык»).

    Механика: композит собирается один раз, затем режется по линиям
    разрыва на три слоя — левый современный, центральная архивная
    полоса, правый современный. Боковые слои стартуют разведёнными и
    приезжают к центру; в момент стыка идёт короткий перелёт с двумя
    затухающими колебаниями (это и есть «тык-тык»), а весь кадр на один
    кадр вздрагивает. Дальше — медленный наезд, чтобы картинка не
    висела мёртвой.

    Все параметры `torn_photo` принимаются как есть; `out` не нужен.
    """
    import subprocess
    kw.pop("out", None)
    lab = {k: kw.pop(k, "") for k in ("title", "subtitle", "year_old",
                                      "year_new", "watermark")}
    ink = kw.get("ink", "light")
    built = torn_photo(None, labels=False, **kw)
    im, size = built["im"], built["size"]
    w, h = size
    lx, rx = built["lx"], built["rx"]

    # три слоя по линиям разрыва
    left_m = Image.new("L", size, 0)
    right_m = Image.new("L", size, 0)
    dl, dr = ImageDraw.Draw(left_m), ImageDraw.Draw(right_m)
    for y in range(h):
        dl.line([(0, y), (max(0, lx[y]), y)], fill=255)
        dr.line([(min(w, rx[y]), y), (w, y)], fill=255)
    center_m = Image.new("L", size, 255)
    ImageDraw.Draw(center_m).rectangle((0, 0, w, h), fill=255)
    center_m = ImageChops_subtract(center_m, ImageChops_lighter(left_m, right_m))

    layer_l = Image.new("RGB", size, (0, 0, 0))
    layer_l.paste(im, (0, 0), left_m)
    layer_r = Image.new("RGB", size, (0, 0, 0))
    layer_r.paste(im, (0, 0), right_m)
    layer_c = Image.new("RGB", size, (0, 0, 0))
    layer_c.paste(im, (0, 0), center_m)

    # фон под разъехавшимися створками — фирменная виньетка, не чёрный провал
    bg = Image.new("RGB", size, (12, 12, 14))
    g = Image.new("L", (w // 8, h // 8), 0)
    ImageDraw.Draw(g).ellipse((-w // 16, -h // 16, w // 8 + w // 16, h // 8 + h // 16),
                              fill=120)
    g = g.filter(ImageFilter.GaussianBlur(20)).resize(size, Image.BILINEAR)
    bg = Image.composite(Image.new("RGB", size, (26, 26, 28)), bg, g)

    def frame(t):
        p = min(1.0, max(0.0, t / hit_at))
        e = 1 - (1 - p) ** 3                      # приезд
        off = shift * (1 - e)
        # ДЁРГАНЬЯ НЕТ ВООБЩЕ (user, 2026-10-21: «когда применяешь зум, не
        # надо применять ещё и дёргание это, оно меня бесит»). Раньше здесь
        # жил затухающий «тык» створок при стыковке — снято. Створки просто
        # доезжают и встают, дальше работает только зум.
        dxl = -off
        dxr = off
        # ВЕСЬ КАДР НЕ ТРЯСЁТСЯ (user, 20.10: «трясучка бесит, глаз от неё
        # устаёт»). Отдача живёт только в самих створках, картинка стоит.
        dy = 0
        f = bg.copy()
        f.paste(layer_c, (0, dy), center_m)
        ml = left_m.transform(size, Image.AFFINE, (1, 0, -dxl, 0, 1, -dy))
        mr = right_m.transform(size, Image.AFFINE, (1, 0, -dxr, 0, 1, -dy))
        f.paste(layer_l.transform(size, Image.AFFINE, (1, 0, -dxl, 0, 1, -dy)),
                (0, 0), ml)
        f.paste(layer_r.transform(size, Image.AFFINE, (1, 0, -dxr, 0, 1, -dy)),
                (0, 0), mr)
        # Наезд ТОЛЬКО В ОДНУ СТОРОНУ и очень медленно: зум туда-сюда
        # утомляет (user, 20.10). Никакого возврата и покачивания.
        if t > hit_at:
            z = 1 + (zoom_to - 1) * min(1.0, (t - hit_at) / max(0.1, seconds - hit_at))
            nw, nh = int(w * z), int(h * z)
            f = f.resize((nw, nh), Image.LANCZOS).crop(
                ((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h))
        # подписи появляются, когда створки сошлись
        la = 0.0 if t < hit_at - 0.1 else min(1.0, (t - hit_at + 0.1) / 0.45)
        if la > 0:
            _labels(f, size, ink=ink, alpha=la, **lab)
        return f

    n = int(round(seconds * fps))
    pr = subprocess.Popen(
        ["nice", "-n", "19", "ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-pix_fmt", "yuv420p", "-threads", "4", out_mp4],
        stdin=subprocess.PIPE)
    for i in range(n):
        pr.stdin.write(frame(i / fps).tobytes())
    pr.stdin.close()
    pr.wait()
    if sfx_out:
        import json
        json.dump([{"at": round(hit_at, 2), "role": "card"}],
                  open(out_mp4.rsplit(".", 1)[0] + ".sfx.json", "w",
                       encoding="utf-8"), ensure_ascii=False, indent=1)
    return out_mp4


def ImageChops_subtract(a, b):
    from PIL import ImageChops
    return ImageChops.subtract(a, b)


def ImageChops_lighter(a, b):
    from PIL import ImageChops
    return ImageChops.lighter(a, b)
