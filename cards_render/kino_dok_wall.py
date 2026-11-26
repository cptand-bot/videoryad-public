# -*- coding: utf-8 -*-
"""D6 ИЗ KINO-DOK, ПЕРЕНЕСЕНО ОДИН В ОДИН С ПАРАМЕТРИЗАЦИЕЙ (24.11.2026,
его слово: «D6 и D3, но не обязательными — желательными. Если не набирается
достаточно информации, их не выводим»).

Источник — фильм «Последний прогноз Киссинджера» (скилл `kino-dok`),
`~/kino-kissinger/engine/hook3.py` (`wall`/`_card_base`). Геометрия
(тёмная стена, портрет центром, пять карточек в полях, нити к
портрету, отъезд камеры в конце) — КАК В ОРИГИНАЛЕ. Правка по смыслу:
в фильме у карточек были вшиты фамилия Киссинджера, конкретный архив и
живое видео в одной из пяти (`pic`). Здесь карточка — ТОЛЬКО заголовок
+ подпись (без вложенного фото/видео), а портрет и пять карточек
приходят СНАРУЖИ.

    card:dok_wall   D6   тёмная стена, портрет в центре, пять карточек
                          в полях связаны нитями к портрету, камера
                          отъезжает в конце

НЕ ОБЯЗАТЕЛЬНЫЙ вид (его слово 24.11): ставить ТОЛЬКО когда для сцены
реально нашлись ПЯТЬ РАЗНЫХ фактов про одного человека — иначе этот
вид не подходит. `card_put.py` требует ровно 5 карточек и падает
`_fail`, если дано меньше — решение «не набралось» видно на этапе
раскладки, не в рендере.

Возвращает RGB-кадр 1920×1080 (этого ждёт `style_cards.render_anim`).
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080
SS = 2
FPS = 25

WALL_BG = (24, 23, 25)
PAPER = (228, 222, 208)
INK = (40, 38, 34)
RED = (204, 34, 30)

FONTS = os.path.join(HERE, "fonts")
F_HEAD = os.path.join(FONTS, "Oswald-Bold.ttf")
F_HEAD_R = os.path.join(FONTS, "Oswald-Regular.ttf") if os.path.exists(
    os.path.join(FONTS, "Oswald-Regular.ttf")) else F_HEAD

# ПЯТЬ ПОЗИЦИЙ — ТЕ ЖЕ, ЧТО В ОРИГИНАЛЕ (hook3.py:POS), геометрия нитей
# считается от них же, поэтому их не раздвигать без пересчёта.
POS = [(W * 0.185, H * 0.28), (W * 0.185, H * 0.72), (W * 0.50, H * 0.78),
       (W * 0.815, H * 0.28), (W * 0.815, H * 0.72)]
ROT = (-4, 3, -2, 4, -3)
CW, CH = 480, 330

STEP = 0.4        # интервал появления карточек
POP = 0.6
PULL_DUR = 1.4    # сколько секунд длится отъезд камеры в конце

_fc = {}


def font(path, size):
    size = max(4, int(round(size)))
    key = (path, size)
    if key not in _fc:
        _fc[key] = ImageFont.truetype(path, size)
    return _fc[key]


def clamp(x, a=0.0, b=1.0):
    return a if x < a else (b if x > b else x)


def lerp(a, b, t):
    return a + (b - a) * t


def seg(t, a, b):
    return clamp((t - a) / max(1e-6, b - a))


def smoother(x):
    x = clamp(x)
    return x * x * x * (x * (x * 6 - 15) + 10)


def out_cubic(t):
    t = clamp(t)
    return 1 - pow(1 - t, 3)


def out_back(t, s=1.4):
    t = clamp(t)
    return 1 + (s + 1) * pow(t - 1, 3) + s * pow(t - 1, 2)


def noise(w, h, seed=1, scale=1.0):
    rng = np.random.default_rng(seed)
    sw, sh = max(2, int(w / scale)), max(2, int(h / scale))
    n = rng.random((sh, sw)).astype(np.float32)
    im = Image.fromarray((n * 255).astype(np.uint8), "L")
    if scale != 1.0:
        im = im.resize((w, h), Image.BILINEAR)
    return im


def paper_tex(w, h, seed=2):
    base = Image.new("RGB", (w, h), PAPER)
    fib = noise(w, h, seed, 1.0).filter(ImageFilter.GaussianBlur(0.6))
    a = np.asarray(base, np.float32)
    f = (np.asarray(fib, np.float32) / 255.0 - 0.5) * 14
    a += f[:, :, None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def cover(im, size):
    w, h = size
    iw, ih = im.size
    s = max(w / iw, h / ih)
    nw, nh = int(iw * s) + 1, int(ih * s) + 1
    big = im.resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - w) // 2, (nh - h) // 2
    return big.crop((x0, y0, x0 + w, y0 + h))


def shadow_box(size, blur=30, a=160):
    w, h = size
    pad = blur * 3
    im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([pad, pad, pad + w, pad + h], fill=(0, 0, 0, a))
    return im.filter(ImageFilter.GaussianBlur(blur)), pad


def vignette(img, k=0.6):
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    v = np.clip(r - 0.45, 0, 1.2) ** 1.6
    a = np.asarray(img.convert("RGB"), np.float32)
    a *= (1.0 - k * v)[:, :, None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def wrap(text, fnt, maxw):
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    out, cur = [], ""
    for w in text.split():
        probe = (cur + " " + w).strip()
        if d.textlength(probe, font=fnt) <= maxw or not cur:
            cur = probe
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


_wall_bg = None
_card_cache = {}


def _background():
    global _wall_bg
    if _wall_bg is None:
        base = Image.new("RGB", (W, H), WALL_BG)
        n = noise(W, H, 77, 3.0).filter(ImageFilter.GaussianBlur(1.2))
        a = np.asarray(base, np.float32) + (np.asarray(n, np.float32) - 128)[:, :, None] * 0.12
        _wall_bg = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    return _wall_bg


def _portrait(photo):
    port = None
    if photo and os.path.exists(photo):
        try:
            port = cover(Image.open(photo).convert("RGB"), (380, 470))
            port = port.convert("L").convert("RGB")
        except Exception:
            port = None
    if port is None:
        port = Image.new("RGB", (380, 470), (60, 58, 56))
    return port


def _card(i, num, title, sub):
    key = (num, title, sub)
    if key in _card_cache:
        return _card_cache[key]
    w, h = CW, CH
    im = paper_tex(w, h, seed=60 + i).convert("RGBA")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], outline=(120, 112, 100, 255), width=2)
    d.ellipse([w / 2 - 11, 12, w / 2 + 11, 34], fill=RED + (255,))
    d.ellipse([w / 2 - 5, 18, w / 2 + 5, 28], fill=(255, 120, 110, 255))
    y = 60
    d.text((30, y), num, font=font(F_HEAD_R, 28), fill=RED + (255,))
    for j, ln in enumerate(wrap(title.upper(), font(F_HEAD, 38), w - 60)[:2]):
        d.text((30, y + 40 + j * 44), ln, font=font(F_HEAD, 38), fill=INK + (255,))
    fs = font(F_HEAD_R, 24)
    y2 = y + 40 + 44 * min(2, len(wrap(title.upper(), font(F_HEAD, 38), w - 60))) + 24
    for j, ln in enumerate(wrap(sub, fs, w - 60)[:3]):
        d.text((30, y2 + j * 30), ln, font=fs, fill=(70, 66, 60, 255))
    _card_cache[key] = im
    return im


def dok_wall(out=None, t=None, photo="", karty=None, channel="", watermark="",
            dur=0.0, sfx=None, **_):
    """D6. `karty` — РОВНО 5 строк «ЗАГОЛОВОК|подпись». Появляются по
    очереди слева, затем камера отъезжает (сцена читает как единое
    фото-досье на тёмной стене)."""
    karty = list(karty or [])[:5]
    full = dur if dur > 0 else 7.0
    last_open = (len(karty) - 1) * STEP if karty else 0.0
    cards_done = last_open + POP
    pull_start = max(cards_done, full - PULL_DUR)
    # ПОСТЕР (t=None) — все карточки появились, ДО отъезда (гоча 24.11:
    # t=0/пустой кадр не годится постером).
    tt = cards_done if t is None else max(0.0, t)

    ks = []
    lives = {}
    for i in range(5):
        if i < len(karty):
            open_at = i * STEP
            ks.append(seg(tt, open_at, open_at + POP))
        else:
            ks.append(0.0)
    pull = seg(tt, pull_start, pull_start + PULL_DUR) if PULL_DUR > 0 else 0.0

    port = _portrait(photo).convert("RGBA")
    sc = lerp(1.0, 0.80, smoother(pull))
    big = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    cx, cy = W / 2, H * 0.44
    for i, k in enumerate(ks):
        if k <= 0:
            continue
        kk = out_cubic(k)
        px, py = POS[i]
        ex, ey = cx + (px - cx) * (1 - kk), cy + (py - cy) * (1 - kk)
        d.line([(px, py), (ex, ey)], fill=RED + (int(220 * min(1, k * 2)),), width=3)

    fr = Image.new("RGBA", (port.size[0] + 24, port.size[1] + 24), (236, 230, 218, 255))
    fr.paste(port, (12, 12))
    sh, pad = shadow_box(fr.size, 34, 170)
    big.alpha_composite(sh, (int(cx - fr.size[0] / 2 - pad + 10), int(cy - fr.size[1] / 2 - pad + 16)))
    big.alpha_composite(fr, (int(cx - fr.size[0] / 2), int(cy - fr.size[1] / 2)))

    for i, k in enumerate(ks):
        if k <= 0:
            continue
        kk = out_back(k)
        parts = karty[i].split("|", 1)
        title, sub = parts[0], (parts[1] if len(parts) > 1 else "")
        tex = _card(i, str(i + 1).zfill(2), title, sub)
        s = 0.86 + 0.14 * kk
        tx = tex.resize((int(tex.size[0] * s), int(tex.size[1] * s)), Image.LANCZOS)
        tx.putalpha(tx.split()[3].point(lambda v: int(v * clamp(k * 3))))
        px, py = POS[i]
        tx = tx.rotate(ROT[i], Image.BICUBIC, expand=True)
        sh, pad = shadow_box(tx.size, 26, 150)
        big.alpha_composite(sh, (int(px - tx.size[0] / 2 - pad + 8), int(py - tx.size[1] / 2 - pad + 14)))
        big.alpha_composite(tx, (int(px - tx.size[0] / 2), int(py - tx.size[1] / 2)))

    img = _background().copy().convert("RGBA")
    if sc != 1.0:
        nw, nh = int(W * sc), int(H * sc)
        img.alpha_composite(big.resize((nw, nh), Image.LANCZOS),
                            ((W - nw) // 2, (H - nh) // 2 + int(10 * (1 - sc))))
    else:
        img.alpha_composite(big)
    rgb = vignette(img.convert("RGB"), 0.6)
    if out:
        rgb.save(out, quality=92)
        return out
    return rgb


if __name__ == "__main__":
    demo = ["ОДИН|первый факт про человека", "ДВА|второй факт",
            "ТРИ|третий факт", "ЧЕТЫРЕ|четвёртый факт", "ПЯТЬ|пятый факт"]
    im = dok_wall(t=2.0, photo="", karty=demo, dur=7.0)
    im.save("/tmp/dok_wall_test.jpg", quality=92)
    print("готово: /tmp/dok_wall_test.jpg")
