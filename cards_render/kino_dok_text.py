# -*- coding: utf-8 -*-
"""ДВА ПРИЁМА ИЗ KINO-DOK, ПЕРЕНЕСЕНЫ ОДИН В ОДИН (24.11.2026, его прямое
слово: «оно же уже разработано, нам не надо ничего разрабатывать, нам надо
это всё перетащить к себе»).

Источник — фильм «Последний прогноз Киссинджера» (скилл `kino-dok`),
`~/kino-kissinger/engine/hook.py` (`word`/`fit_px`) и `hook3.py`
(`title_b20`). Перенесена ТОЛЬКО чистая отрисовка (математика хода,
шрифт, текст) — без привязки к фильму (`core.py`/`cuts.py`/видеоархив
фильма не нужны). Правка видов — в ОБОИХ местах: тут и в исходнике
фильма, если меняете приём содержательно.

    card:dok_word   D9   крупное слово всплывает снизу, кегль сам
                         ужимается под ширину поля
    card:dok_title  D13  заголовок брифинга: белое слово + красный акцент,
                         снизу растёт красная черта

Фон — графит (палитра фильма: графит/бумага/белый, красный только на
акценте и линии), с лёгким зерном, не плоская заливка.

Возвращает RGB-кадр 1920×1080 (этого ждёт `style_cards.render_anim`).
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080
SS = 2                      # суперсэмплинг текстовых слоёв — как в оригинале
SAFE_X, SAFE_Y = 96, 54

BG = (18, 18, 21)           # графит — палитра фильма
WHITE = (240, 238, 234)
RED = (204, 34, 30)         # красный только для акцента/линии/числа

FONTS = os.path.join(HERE, "fonts")
# В ОРИГИНАЛЕ — переменный Oswald-VF.ttf (Bold/Regular/Light/Medium).
# Обоим приёмам нужна ТОЛЬКО жирная насечка ("head"), а она у нас уже лежит
# статическим файлом в общей папке шрифтов — второй шрифт не тащим.
F_HEAD = os.path.join(FONTS, "Oswald-Bold.ttf")

_fc = {}


def font(size):
    size = max(4, int(round(size)))
    if size not in _fc:
        _fc[size] = ImageFont.truetype(F_HEAD, size)
    return _fc[size]


def clamp(x, a=0.0, b=1.0):
    return a if x < a else (b if x > b else x)


def out_cubic(t):
    t = clamp(t)
    return 1 - pow(1 - t, 3)


def layer():
    return Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))


def done(im):
    return im.resize((W, H), Image.LANCZOS)


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


def text_layer(text, px, color, x, y, anchor="ms", track=0.06, a=1.0):
    im = layer()
    d = ImageDraw.Draw(im)
    f = font(px * SS)
    col = tuple(color) + (int(255 * clamp(a)),)
    tracked(d, x * SS, y * SS, text, f, col, track, anchor)
    return done(im)


def fit_px(text, px, maxw, track=0.0):
    """D9: кегль сам ужимается, пока строка не влезет в поле — тот же
    приём, что в оригинале, те же шаги по 4 px."""
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    while px > 20 and text_w(d, text, font(px * SS), track) / SS > maxw:
        px -= 4
    return px


def _grain(seed=2):
    rng = np.random.default_rng(seed)
    n = (rng.random((H // 3, W // 3)).astype(np.float32) * 255).astype(np.uint8)
    im = Image.fromarray(n, "L").resize((W, H), Image.BILINEAR)
    return im


def _fon():
    """Графитовый фон с лёгким зерном и виньеткой — не плоская заливка."""
    base = Image.new("RGB", (W, H), BG)
    g = _grain().point(lambda v: 10 + v // 14)
    arr = np.asarray(base, np.int16) + (np.asarray(g, np.int16)[..., None] - 18)
    im = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB")
    v = Image.new("L", (W, H), 40)
    dv = ImageDraw.Draw(v)
    dv.ellipse([-W * 0.6, -H * 0.7, W * 1.6, H * 1.7], fill=90)
    v = v.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(260))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(im, dark, v)


def dok_word(out=None, t=None, text="", channel="", watermark="",
            dur=0.0, sfx=None, **_):
    """D9. `--text` — слово/короткая фраза, всплывает снизу за ~1 с, кегль
    подбирается под поля SAFE_X."""
    full = dur if dur > 0 else 4.0
    # ПОСТЕР (t=None) ПОКАЗЫВАЕТ УСТОЯВШЕЕСЯ СОСТОЯНИЕ, НЕ СТАРТ (24.11,
    # поймано живым тестом — t=0 рисовал слово ещё невидимым, постер выходил
    # пустым чёрным кадром). Та же развязка, что у zal_g01 (t=None → HERO).
    tt = 1.0 if t is None else max(0.0, min(1.0, t / 1.0))   # окно хода — 1 с, как в оригинале
    txt = (text or "СЛОВО").strip().upper()

    img = _fon()
    px = fit_px(txt, 160, W - 2 * SAFE_X)
    kk = out_cubic(tt)
    rise = 40 * (1 - kk)
    a = clamp(tt * 2)
    lay = text_layer(txt, px, WHITE, W / 2, H / 2 + rise, anchor="ms", a=a)
    img = Image.alpha_composite(img.convert("RGBA"), lay)

    rgb = img.convert("RGB")
    if out:
        rgb.save(out, quality=92)
        return out
    return rgb


def dok_title(out=None, t=None, text="", accent="", channel="", watermark="",
             dur=0.0, sfx=None, **_):
    """D13. `--text` — белая часть заголовка, `--accent` — красное слово
    следом; под строкой растёт красная черта."""
    full = dur if dur > 0 else 4.0
    # ПОСТЕР (t=None) — устоявшееся состояние, не старт (та же правка, что в dok_word).
    tt = 1.0 if t is None else max(0.0, min(1.0, t / 0.8))   # ~0,8 с, как в оригинале
    white = (text or "ЗАГОЛОВОК").strip().upper()
    acc = (accent or "").strip().upper()

    img = _fon()
    kk = out_cubic(tt)
    a = int(255 * clamp(tt * 2))
    x, y, px = SAFE_X + 20, 150, 56
    d_probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    f = font(px * SS)
    w1 = text_w(d_probe, white, f, 0.06)
    lay = layer()
    d = ImageDraw.Draw(lay)
    yy = (y + (1 - kk) * 16) * SS
    tracked(d, x * SS, yy, white, f, WHITE + (a,), 0.06)
    if acc:
        tracked(d, x * SS + w1 + px * 0.35 * SS, yy, acc, f, RED + (a,), 0.06)
    d.rectangle([x * SS, (y + 16) * SS, (x + 260 * kk) * SS, (y + 19) * SS], fill=RED + (a,))
    img = Image.alpha_composite(img.convert("RGBA"), done(lay))

    rgb = img.convert("RGB")
    if out:
        rgb.save(out, quality=92)
        return out
    return rgb


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "word"
    if cmd == "word":
        im = dok_word(t=0.6, text=" ".join(sys.argv[2:]) or "ТРИ ГОДА", dur=4.0)
        im.save("/tmp/dok_word_test.jpg", quality=92)
        print("готово: /tmp/dok_word_test.jpg")
    else:
        im = dok_title(t=0.5, text="ЗАГОЛОВОК", accent="БРИФИНГА", dur=4.0)
        im.save("/tmp/dok_title_test.jpg", quality=92)
        print("готово: /tmp/dok_title_test.jpg")
