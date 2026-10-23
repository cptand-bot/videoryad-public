#!/usr/bin/env python3
"""ЭКРАНЫ УСТРОЙСТВ — контент внутри телефона, планшета или монитора.

Зачем: пост, статья или карта, показанные «как есть», читаются как
скриншот. В корпусе устройства тот же кадр читается как съёмка предмета —
появляется объём, свет и масштаб. Отсюда и рекламный вид (user, 21.10:
«чтобы вау, по-голливудски»).

Три корпуса:
  phone    — вертикально, вырез камеры, кнопки сбоку. Под телеграм-посты
             и короткие заявления.
  tablet   — горизонтально, тонкие поля. Под карты, графики, документы.
  desktop  — монитор с рамкой браузера (кружки, адресная строка) и
             подставкой. Под статьи сайтов.

КОРПУС НЕПОДВИЖЕН (user, 21.10: «качать его не надо»). Ни доворота из
перспективы, ни приезда снизу, ни общего зума: устройство стоит в кадре
намертво, как предмет на столе. Живёт только ЭКРАН:

  1. экран загорается — не сразу, набирает яркость;
  2. содержимое приходит: фото выплывает, строки появляются по очереди,
     страница прокручивается к нужному месту;
  3. по стеклу один раз проходит блик;
  4. экран отсвечивает на фон своим цветом.

Содержимое экрана задаётся `screen`:
  {"kind": "image", ...}  — картинка проявляется и медленно едет внутри
                            экрана (прокрутка или внутренний зум);
  {"kind": "post",  ...}  — телеграм-пост: шапка, фото, строки по очереди;
  {"kind": "page",  ...}  — страница сайта: рамка браузера, прокрутка и
                            подсветка нужной строки маркером.

  python3 devices.py <phone|tablet|desktop> <контент.jpg> <out.jpg|out.mp4>
"""
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "template"))
import style_cards as sc

W, H, FPS = sc.W, sc.H, 25

SPECS = {                      # размеры корпуса и экрана в пикселях кадра
    # Корпус НЕ во весь кадр: слева остаётся зона подписей, иначе кикер и
    # заголовок ложатся прямо на стекло (поймано на первой пробе 21.10).
    "phone":   dict(body=(470, 952),  bezel=16, radius=54, screen_radius=42, dx=330),
    "tablet":  dict(body=(1080, 770), bezel=22, radius=38, screen_radius=24, dx=330),
    "desktop": dict(body=(1150, 690), bezel=16, radius=16, screen_radius=5, dx=320),
}


def _find_coeffs(pa, pb):
    """Коэффициенты перспективы для Image.transform (8 чисел)."""
    m = []
    for (x, y), (u, v) in zip(pa, pb):
        m.append([u, v, 1, 0, 0, 0, -x * u, -x * v])
        m.append([0, 0, 0, u, v, 1, -y * u, -y * v])
    A = np.array(m, np.float64)
    B = np.array(pa, np.float64).reshape(8)
    return np.linalg.solve(A, B).reshape(8)


def _round_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r, fill=255)
    return m


def _trim(img, tol=14):
    """Срезает ровные поля по краям скриншота: чёрные или белые канты
    внутри экрана читаются как пустой экран, а не как страница."""
    a = np.asarray(img.convert("RGB"), np.float32)
    col = np.abs(a - a[:, :1, :]).max(axis=(1, 2)) < tol
    row = np.abs(a - a[:1, :, :]).max(axis=(0, 2)) < tol
    ys = np.where(~col)[0]
    xs = np.where(~row)[0]
    if len(ys) < 8 or len(xs) < 8:
        return img
    return img.crop((int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1))


def _fit(img, size):
    w, h = size
    k = max(w / img.width, h / img.height)
    im = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)
    x = (im.width - w) // 2
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def _screen_content(content, size, scroll=0.0, lit=1.0):
    """Контент экрана: вписан, прокручен на scroll (доля запаса), притушен."""
    w, h = size
    # ВСЕГДА ПО ШИРИНЕ. Раньше короткий контент уходил в ветку «вписать по
    # покрытию», и у поста срезало левый край вместе с началом строк
    # (поймано 21.10 на телеграм-посте в телефоне). Если контент ниже
    # экрана — не режем, а дорисовываем фон его же цветом.
    k = w / content.width
    im = content.resize((w, max(1, int(content.height * k))), Image.LANCZOS)
    if im.height < h:
        pad = Image.new("RGB", size, tuple(int(c) for c in np.asarray(
            im.convert("RGB"), np.float32)[:4].reshape(-1, 3).mean(0)))
        pad.paste(im, (0, (h - im.height) // 2))
        im = pad
    else:
        off = int((im.height - h) * max(0.0, min(1.0, scroll)))
        im = im.crop((0, off, w, off + h))
    if lit < 1.0:
        a = np.asarray(im.convert("RGB"), np.float32) * (0.12 + 0.88 * lit)
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return im


def _browser_chrome(size, url="", title=""):
    """Шапка браузера для монитора: кружки, вкладка, адресная строка."""
    w, h = size
    bar = Image.new("RGB", (w, 92), (34, 34, 38))
    d = ImageDraw.Draw(bar)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse((30 + i * 34, 24, 48 + i * 34, 42), fill=c)
    d.rounded_rectangle((150, 14, 150 + min(430, w // 3), 52), 10, fill=(52, 52, 58))
    if title:
        d.text((172, 24), title[:34], font=sc._f(sc.F_HEAD, 22), fill=(205, 205, 212))
    d.rounded_rectangle((30, 58, w - 30, 84), 9, fill=(24, 24, 27))
    if url:
        d.text((48, 61), url, font=sc._f(sc.MONO, 20), fill=(150, 196, 150))
    return bar



# ─────────────────── СОДЕРЖИМОЕ ЭКРАНА: ТРИ СЦЕНАРИЯ ─────────────────────
# Корпус стоит, поэтому вся выразительность — здесь. Каждый рисовальщик
# получает время t и размер экрана и возвращает готовый кадр экрана.

def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _slide_in(im, size, p, dy=46):
    """Выплывание снизу с проявлением: p 0..1."""
    w, h = size
    out = Image.new("RGB", size, (0, 0, 0))
    e = _ease(p)
    lay = Image.new("RGB", size, (0, 0, 0))
    lay.paste(im, (0, int(dy * (1 - e))))
    a = np.asarray(lay, np.float32) * e
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _screen_image(t, size, spec):
    """Картинка: проявляется, затем медленно едет ВНУТРИ экрана."""
    w, h = size
    content = _trim(Image.open(spec["path"]).convert("RGB"))
    zoom_to = spec.get("zoom_to", 1.10)
    scroll_to = spec.get("scroll_to", 0.0)
    appear = _ease((t - 0.45) / 0.8)
    move = max(0.0, min(1.0, (t - 1.1) / max(0.1, spec.get("span", 5.0))))
    z = 1.0 + (zoom_to - 1.0) * move
    k = max(w / content.width, h / content.height) * z
    im = content.resize((max(1, int(content.width * k)), max(1, int(content.height * k))), Image.LANCZOS)
    free_x, free_y = im.width - w, im.height - h
    x = free_x // 2
    y = int(free_y * scroll_to * move) if free_y > 0 else 0
    im = im.crop((x, y, x + w, y + h))
    a = np.asarray(im, np.float32) * (0.10 + 0.90 * appear)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _screen_post(t, size, spec):
    """Телеграм-пост: шапка, фото выплывает, строки приходят по очереди."""
    w, h = size
    BG, CARD = (23, 27, 33), (33, 42, 54)
    im = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(im)
    S = w / 1080.0                                   # всё задано для ширины 1080
    # ВЫРЕЗ КАМЕРЫ СЪЕДАЕТ ВЕРХ: без отступа шапка канала уезжает под
    # «пилюлю» и читается как брак (поймано 21.10 на первой же пробе).
    TOP = int(spec.get("top", 92) * S)

    def F(px):
        return sc._f(sc.F_HEAD, max(9, int(px * S)))

    def M(px):
        return sc._f(sc.MONO, max(9, int(px * S)))

    # шапка канала — приходит первой
    a_head = _ease((t - 0.5) / 0.4)
    if a_head > 0:
        d.rectangle((0, TOP, w, TOP + int(150 * S)), fill=(28, 36, 46))
        if spec.get("avatar"):
            av = Image.open(spec["avatar"]).convert("RGB").resize((int(92 * S), int(92 * S)), Image.LANCZOS)
            m = Image.new("L", av.size, 0)
            ImageDraw.Draw(m).ellipse((0, 0, av.width - 1, av.height - 1), fill=255)
            im.paste(av, (int(34 * S), TOP + int(30 * S)), m)
        d.text((int(148 * S), TOP + int(44 * S)), spec.get("channel", ""), font=F(40),
               fill=(236, 238, 242))
        d.text((int(148 * S), TOP + int(96 * S)), spec.get("subs", ""), font=F(26),
               fill=(130, 146, 162))

    # пузырь поста
    y_card = TOP + int(196 * S)
    d.rounded_rectangle((int(28 * S), y_card, w - int(28 * S), h - int(40 * S)),
                        int(26 * S), fill=CARD)

    # фото выплывает
    y = y_card + int(18 * S)
    if spec.get("photo"):
        ph = Image.open(spec["photo"]).convert("RGB")
        pw = w - int(92 * S)
        ph = ph.resize((pw, int(ph.height * pw / ph.width)), Image.LANCZOS)
        p_ph = (t - 0.9) / 0.7
        if p_ph > 0:
            e = _ease(p_ph)
            band = Image.new("RGB", (pw, ph.height), (0, 0, 0))
            band.paste(ph, (0, 0))
            a = np.asarray(band, np.float32) * e
            band = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
            im.paste(band, (int(46 * S), y + int(26 * S * (1 - e))))
        y += ph.height + int(28 * S)

    # строки по очереди
    for i, line in enumerate(spec.get("lines", [])):
        at = 1.6 + i * 0.28
        a_l = _ease((t - at) / 0.35)
        if a_l <= 0:
            break
        col = (236, 238, 242) if i == 0 else (205, 212, 220)
        col = tuple(int(c * a_l) for c in col)
        d.text((int(60 * S), y), line, font=F(36), fill=col)
        y += int(54 * S)

    # подпись времени и просмотров — последней
    a_f = _ease((t - (1.6 + 0.28 * len(spec.get("lines", [])) + 0.2)) / 0.4)
    if a_f > 0:
        c = tuple(int(v * a_f) for v in (126, 142, 158))
        d.text((int(60 * S), y + int(18 * S)), spec.get("time", ""), font=M(26), fill=c)
        if spec.get("views"):
            tx = spec["views"]
            d.text((w - int(60 * S) - d.textlength(tx, font=M(26)), y + int(18 * S)),
                   tx, font=M(26), fill=c)
    return im


def _screen_page(t, size, spec):
    """Страница сайта: шапка браузера, прокрутка и маркер по нужной строке."""
    w, h = size
    content = _trim(Image.open(spec["path"]).convert("RGB"))
    chrome = _browser_chrome((w, h), url=spec.get("url", ""), title=spec.get("tab", ""))
    ph = h - chrome.height
    k = w / content.width
    page = content.resize((w, max(1, int(content.height * k))), Image.LANCZOS)

    move = max(0.0, min(1.0, (t - 1.2) / 2.4))
    free = max(0, page.height - ph)
    off = int(free * spec.get("scroll_to", 0.0) * _ease(move))
    view = page.crop((0, off, w, off + ph)) if page.height > ph else _fit(content, (w, ph))

    # маркер: доли ширины/высоты ВИДИМОЙ области
    mk = spec.get("mark")
    if mk:
        grow = max(0.0, min(1.0, (t - mk.get("at", 3.4)) / 0.6))
        if grow > 0:
            x0, x1 = int(mk["x0"] * w), int(mk["x1"] * w)
            yy = int(mk["y"] * ph)
            th = max(4, int(mk.get("thick", 0.035) * ph))
            band = Image.new("L", (w, ph), 0)
            bd = ImageDraw.Draw(band)
            bd.rectangle((x0, yy, x0 + int((x1 - x0) * grow), yy + th), fill=190)
            band = band.filter(ImageFilter.GaussianBlur(2))
            paint = Image.new("RGB", (w, ph), (255, 206, 26))
            view = Image.composite(paint, view, band)

    scr = Image.new("RGB", size, (20, 20, 22))
    scr.paste(chrome, (0, 0))
    scr.paste(view, (0, chrome.height))
    return scr


SCREENS = {"image": _screen_image, "post": _screen_post, "page": _screen_page}


def _body(kind, screen_img, lit):
    """Корпус с экраном — RGBA-слой по размеру корпуса."""
    s = SPECS[kind]
    bw, bh = s["body"]
    body = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)

    # металл корпуса: вертикальный градиент + светлая кромка
    met = Image.new("RGB", (bw, bh), (26, 26, 30))
    g = np.linspace(1.35, 0.72, bh, dtype=np.float32)[:, None, None]
    met = Image.fromarray(np.clip(np.asarray(met, np.float32) * g, 0, 255).astype(np.uint8))
    body.paste(met, (0, 0), _round_mask((bw, bh), s["radius"]))
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), s["radius"], outline=(118, 120, 130), width=3)
    d.rounded_rectangle((3, 3, bw - 4, bh - 4), s["radius"] - 2, outline=(58, 58, 66), width=2)

    # экран
    bz = s["bezel"]
    sw, sh = bw - 2 * bz, bh - 2 * bz
    scr = screen_img if screen_img.size == (sw, sh) else screen_img.resize((sw, sh), Image.LANCZOS)
    if lit < 1.0:                       # экран загорается не сразу
        a = np.asarray(scr.convert("RGB"), np.float32) * (0.10 + 0.90 * lit)
        scr = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    body.paste(scr, (bz, bz), _round_mask((sw, sh), s["screen_radius"]))

    # вырез камеры и кнопки
    if kind == "phone":
        d.rounded_rectangle((bw // 2 - 56, bz + 14, bw // 2 + 56, bz + 46), 16, fill=(12, 12, 14))
        d.ellipse((bw // 2 + 26, bz + 22, bw // 2 + 42, bz + 38), fill=(22, 26, 34))
        for y0, y1 in ((236, 330), (352, 446)):
            d.rounded_rectangle((bw - 2, y0, bw + 3, y1), 3, fill=(96, 98, 108))
        d.rounded_rectangle((-3, 268, 2, 380), 3, fill=(96, 98, 108))
    elif kind == "tablet":
        d.ellipse((bw // 2 - 7, bz // 2 - 3, bw // 2 + 7, bz // 2 + 11), fill=(16, 16, 20))
    return body


def _stand(kind, bw, bh):
    """Подставка монитора — отдельным слоем под корпусом."""
    if kind != "desktop":
        return None
    st = Image.new("RGBA", (bw, 150), (0, 0, 0, 0))
    d = ImageDraw.Draw(st)
    d.polygon([(bw // 2 - 46, 0), (bw // 2 + 46, 0), (bw // 2 + 70, 104), (bw // 2 - 70, 104)],
              fill=(52, 52, 60, 255))
    d.rounded_rectangle((bw // 2 - 190, 104, bw // 2 + 190, 134), 14, fill=(64, 64, 74, 255))
    return st


def _glare(size, pos, radius):
    """Блик: мягкая светлая полоса поперёк стекла."""
    w, h = size
    g = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(g)
    x = int(-w * 0.6 + pos * w * 2.2)
    d.polygon([(x, h + 60), (x + radius, h + 60), (x + radius + int(h * 0.55), -60),
               (x + int(h * 0.55), -60)], fill=120)
    return g.filter(ImageFilter.GaussianBlur(radius // 3 + 18))


def device_scene(out=None, *, kind="phone", screen=None, content_path="",
                 kick="", title="", sub="", watermark="ДИПЛОМАТИЯ СИЛЫ",
                 t=None, sfx=None, seconds=7.0, **legacy):
    """Кадр: содержимое внутри НЕПОДВИЖНОГО корпуса устройства.

    screen — словарь сценария экрана (см. SCREENS). Для совместимости
    принимается и голый content_path: он разворачивается в {"kind":"image"}.
    """
    if screen is None:
        screen = {"kind": "image", "path": content_path,
                  "scroll_to": legacy.get("scroll_to", 0.0),
                  "zoom_to": legacy.get("zoom_to", 1.10)}
        if legacy.get("url") or legacy.get("tab"):
            screen = {"kind": "page", "path": content_path,
                      "url": legacy.get("url", ""), "tab": legacy.get("tab", ""),
                      "scroll_to": legacy.get("scroll_to", 0.45),
                      "mark": legacy.get("mark")}
    screen = dict(screen)
    screen.setdefault("span", max(1.0, seconds - 1.6))
    tt = seconds if t is None else t

    s = SPECS[kind]
    bw, bh = s["body"]
    bz = s["bezel"]
    sw, sh = bw - 2 * bz, bh - 2 * bz

    draw_screen = SCREENS[screen.get("kind", "image")]
    scr = draw_screen(tt, (sw, sh), screen)

    lit = min(1.0, max(0.0, (tt - 0.25) / 0.5))      # экран загорается
    glare_p = (tt - 1.1) / 1.3                       # блик проходит один раз

    im = sc.canvas()
    body = _body(kind, scr, lit if t is not None else 1.0)
    stand = _stand(kind, bw, bh)
    if stand is not None:
        full = Image.new("RGBA", (bw, bh + stand.height - 10), (0, 0, 0, 0))
        full.paste(stand, (0, bh - 10), stand)
        full.paste(body, (0, 0), body)
        body = full
        bh = body.height

    # КОРПУС СТОИТ НАМЕРТВО: ни перспективы, ни приезда, ни зума (21.10).
    nw, nh = bw, bh
    x0 = int((W - nw) / 2 + s.get("dx", 0))
    y0 = (H - nh) // 2

    # отсвет экрана на фон — цвет берём с живого кадра экрана
    small = scr.convert("RGB").resize((8, 8), Image.LANCZOS)
    col = tuple(int(c) for c in np.asarray(small, np.float32).reshape(-1, 3).mean(0))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((x0 - 260, y0 - 200, x0 + nw + 260, y0 + nh + 200), fill=108)
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    gl = np.asarray(glow, np.float32)[..., None] / 255.0 * lit
    base = np.asarray(im, np.float32) + gl * np.array(col, np.float32) * 0.55
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))

    # тень под корпусом
    alpha = body.split()[-1]
    sh_l = Image.new("L", (W, H), 0)
    sh_l.paste(alpha, (x0 + 10, y0 + 26))
    sh_l = sh_l.filter(ImageFilter.GaussianBlur(34))
    a = np.asarray(im, np.float32) * (1 - 0.72 * (np.asarray(sh_l, np.float32) / 255.0)[..., None])
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    im.paste(body, (x0, y0), body)

    # блик по стеклу
    if 0.0 < glare_p < 1.0 or t is None:
        gp = 0.62 if t is None else glare_p
        g = _glare((nw, nh), gp, max(40, nw // 7))
        gg = Image.new("L", (W, H), 0)
        gg.paste(g, (x0, y0))
        m = Image.new("L", (W, H), 0)
        m.paste(alpha, (x0, y0))
        gg = Image.fromarray((np.asarray(gg, np.float32) *
                              (np.asarray(m, np.float32) / 255.0)).astype(np.uint8))
        a = np.asarray(im, np.float32) + (np.asarray(gg, np.float32)[..., None] * 0.85)
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    # подписи слева
    a0, dx0 = sc._rv(t, 0.08)
    if a0 > 0 and (kick or title):
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(lay, "RGBA")
        if kick:
            sc.kicker(dd, 92, kick, dot=True, t=t)
        if title:
            sc.track(dd, (sc.MARGIN_L - 120, 142), title, sc._f(sc.F_HEAD, 50),
                     sc.WHITE + (int(255 * a0),), spacing=2)
        if sub:
            dd.text((sc.MARGIN_L - 120, 204), sub, font=sc._f(sc.F_HEAD, 32),
                    fill=(214, 214, 218, int(230 * a0)))
        im = Image.alpha_composite(im.convert("RGBA"), lay).convert("RGB")

    d = ImageDraw.Draw(im, "RGBA")
    sc.footer(d, "", watermark=watermark)
    if out:
        im.save(out, quality=94)
    return im


def device_clip(out_mp4, *, seconds=7.0, fps=FPS, **kw):
    kw.pop("out", None); kw.pop("t", None)
    tmp = tempfile.mkdtemp()
    n = int(seconds * fps)
    for i in range(n):
        device_scene(os.path.join(tmp, f"{i:04d}.jpg"), t=i / fps, seconds=seconds, **kw)
    subprocess.run(["nice", "-n", "19", "ffmpeg", "-v", "error", "-framerate", str(fps),
                    "-i", os.path.join(tmp, "%04d.jpg"), "-c:v", "libx264", "-preset",
                    "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "2",
                    "-y", out_mp4], check=True)
    return out_mp4


if __name__ == "__main__":
    kind, content, out = sys.argv[1], sys.argv[2], sys.argv[3]
    if out.endswith(".mp4"):
        device_clip(out, kind=kind, content_path=content, seconds=7.0,
                    kick="демонстрация", title="ЭКРАН УСТРОЙСТВА")
    else:
        device_scene(out, kind=kind, content_path=content,
                     kick="демонстрация", title="ЭКРАН УСТРОЙСТВА")
    print("готово:", out)
