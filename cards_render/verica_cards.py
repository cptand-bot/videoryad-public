# -*- coding: utf-8 -*-
"""ДВЕНАДЦАТЬ КАРТОЧЕК ИЗ «ВЕРИЦЫ» — ВТОРОЙ ЗАХОД (27.11.2026).

ПЕРВЫЙ ЗАХОД (один файл, голая геометрия PIL — круги, прямоугольники,
линии) ПРИЗНАН НЕГОДНЫМ. Его прямое слово: «какое убожество... это как
получилось, чтобы было такое убогое качество после фабла». Причина
найдена предметно: настоящие функции фильма (`~/kino-verica/engine/
scenes3-6.py`) используют совсем другую технику — тень от лампы
(`fx.shadow_of`), текстуру бумаги (`core.paper`), анимированное зерно
плёнки + виньетку + наплыв на каждом кадре (`core.finish`), и везде
физику (поворот вокруг кромки, пружинный вылет, затухающие колебания),
а не линейное появление. Первый заход взял голую геометрию функций и
отбросил именно это.

Перенесено ВТОРОЙ РАЗ — техника один в один из исходника (модуль
`verica_core.py`, портирован из `core.py`/`fx.py`), содержание обобщено
в аргументы там, где в оригинале были намертво зашиты имена, даты и
места фильма (это НЕЛЬЗЯ перенести один в один по определению — не наш
текст). Контрольная сверка техники — у каждой функции в докстроке
названа исходная.

Возвращает RGB-кадр 1920×1080 (этого ждёт `style_cards.render_anim`).
"""
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import verica_core as vc

HERE = os.path.dirname(os.path.abspath(__file__))
# НЕ `../template/fonts` — ЭТО ЛОКАЛЬНЫЙ ПУТЬ, НА РАННЕРЕ ЕГО НЕТ (27.11.2026,
# живой случай: `kalendar` падал `OSError: cannot open resource`). На раннере
# `cards_cloud.py` кладёт весь код фуллсайкла и `template` ПЛОСКО в одну папку,
# а шрифты — в `<та же папка>/fonts/`, без вложенного «template». Тот же
# приём, что уже у `kino_dok_text.py`: шрифты рядом со СКРИПТОМ, не рядом с
# «template». Локально копия всех нужных шрифтов лежит здесь же,
# `fullcycle/fonts/` — не только Caveat (было раньше), но и Oswald/Roboto/Tinos.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
_TEMPLATE = os.path.join(os.path.dirname(HERE), "template")
if _TEMPLATE not in sys.path:
    sys.path.insert(0, _TEMPLATE)          # запасной путь — только локально
try:
    import palitra
except Exception:
    palitra = None

W, H = vc.W, vc.H
SS = vc.SS
SAFE_X, SAFE_Y = 96, 54

FONTS = os.path.join(HERE, "fonts")
F_HEAD = os.path.join(FONTS, "Oswald-Bold.ttf")
F_SANS = os.path.join(FONTS, "RobotoCondensed-Bold.ttf")
F_SERIF = os.path.join(FONTS, "Tinos-Bold.ttf")
F_HAND = os.path.join(FONTS, "Caveat-Bold.ttf")

PAPER = (210, 201, 181)
INK = (32, 30, 27)
GRAPHITE = (18, 18, 22)
WHITE = (240, 238, 234)
GREY = (150, 150, 156)
GREY2 = (90, 90, 96)
LAMP = (W * 0.5, -300)          # условная лампа сверху — тот же угол, что в фильме


def _accent(channel):
    if palitra is not None and channel:
        try:
            return tuple(palitra.accent(channel, tiho=True))
        except Exception:
            pass
    return (204, 34, 30)


# clamp/lerp/easing — тонкие обёртки над verica_core
clamp, lerp, smoother = vc.clamp, vc.lerp, vc.smoother
out_cubic, out_expo, out_back, seg = vc.out_cubic, vc.out_expo, vc.out_back, vc.seg
layer, done, over, alpha = vc.layer, vc.done, vc.over, vc.alpha
tracked, text_w = vc.tracked, vc.text_w


def text_layer(text, px, color, x, y, font_path=F_HEAD, anchor="ms", track=0.02, a=1.0):
    im = layer()
    d = ImageDraw.Draw(im)
    f = vc.font(font_path, px * SS)
    col = tuple(color) + (int(255 * clamp(a)),)
    tracked(d, x * SS, y * SS, text, f, col, track, anchor)
    return done(im)


def fit_px(text, px, maxw, font_path=F_HEAD, track=0.0):
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    while px > 18 and text_w(d, text, vc.font(font_path, px * SS), track) / SS > maxw:
        px -= 4
    return px


def wrap(text, px, maxw, font_path=F_SERIF, track=0.0):
    return vc.wrap(text, font_path, px, maxw, track)


def _graphite_bg(seed=7):
    base = Image.new("RGB", (W, H), GRAPHITE)
    g = vc.noise(W, H, seed, 2.4)
    a = np.asarray(base, np.float32) + (np.asarray(g, np.float32)[..., None] / 255 - 0.5) * 14
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"), "RGB")
    return vc.vignette(im, 0.42)


def _kicker(img, text, channel, color=None, y=SAFE_Y + 26):
    if not text:
        return img
    col = color or _accent(channel)
    lay = text_layer(text.strip().upper(), 34, col, SAFE_X, y,
                      font_path=F_SANS, anchor="ls", track=0.14)
    return Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")


def _settle(t, window, dur):
    """tt (0..1, окно приёма) и real_t (секунды в сцене) из входа render_anim.
    t=None (постер) — приём сыгран (tt=1), а real_t — СЕРЕДИНА ролика, не
    конец: конец сидит в зоне fade-out у `finish()` и кадр уходит в чёрное
    (живой баг первой сборки: постеры всех 12 карточек оказались чёрным
    кадром). Постеру нужна точка ПОСЛЕ приёма и ДО угасания."""
    if t is None:
        settled = window + 0.15
        return 1.0, min(settled, max(0.0, dur - 0.5))
    return clamp(t / window), t


# ===========================================================================
# P1 · kalendar — ОТРЫВНОЙ КАЛЕНДАРЬ
# источник: scenes4.kalendar — лист отрывается, поворот вокруг верхней
# кромки, улёт вверх-вправо с угасанием; тень от лампы, бумага, переплётные
# дырочки. Было: статичная сетка из 31 цифры.
# ===========================================================================
def kalendar(out=None, t=None, accent="", value="", kick="", channel="",
            watermark="", dur=6.0, sfx=None, **_):
    """P1. --accent — текущий лист (остаётся), --value — прошлый лист (если
    задан, срывается и улетает), --kick — подпись под блоком."""
    tt, real_t = _settle(t, 1.5, dur)
    acc = _accent(channel)
    img = _graphite_bg()
    pw, ph = 620, 560
    cx, cy = W / 2, H * 0.52
    x0, y0 = int(cx - pw / 2), int(cy - ph / 2)
    base = Image.new("RGBA", (pw + 40, ph + 60), (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle([0, 0, pw + 39, ph + 59], radius=14,
                                            fill=(40, 36, 34, 255), outline=(70, 66, 62, 255), width=3)
    sh, sx, sy = vc.shadow_of((pw + 40, ph + 60), *LAMP, cx, cy + 10, blur=26, a=180)
    img = img.convert("RGBA")
    img.alpha_composite(sh, (sx, sy))
    img.alpha_composite(base, (x0 - 20, y0 - 20))

    def sheet(label, tone=(222, 214, 196)):
        im = vc.paper(pw, ph, seed=120 + (hash(label) % 50), tone=tone).convert("RGBA")
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, pw - 1, 70], fill=acc)
        d.text((pw / 2, 52), "ДАТА", font=vc.font(F_SANS, 32), fill=(250, 248, 244, 255), anchor="ms")
        px = fit_px(label, 150, pw - 60)
        d.text((pw / 2, ph * 0.64), label, font=vc.font(F_HEAD, px), fill=INK + (255,), anchor="ms")
        for j in range(7):
            d.ellipse([60 + j * 85, 8, 60 + j * 85 + 14, 22], fill=(30, 28, 26, 255))
        return im

    img.alpha_composite(sheet(accent or "ДАТА"), (x0, y0))
    if value:
        e = smoother(tt)
        if e < 1.0:
            old = sheet(str(value), tone=(206, 196, 176))
            ang = -70 * e
            old = old.rotate(ang, Image.BICUBIC, expand=True, center=(0, 0))
            old = vc.alpha(old, 1 - seg(e, 0.6, 1.0))
            img.alpha_composite(old, (int(x0 + 300 * e), int(y0 - 420 * e)))
    img = img.convert("RGB")
    if kick:
        y = y0 + ph + 56
        for ln in wrap(str(kick), 34, pw, font_path=F_SERIF)[:2]:
            lay = text_layer(ln, 34, WHITE, cx, y, font_path=F_SERIF, anchor="ms", track=0.0)
            img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
            y += 46
    img = _kicker(img, "КАЛЕНДАРЬ", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# P2 · kartoteka — КАРТОТЕЧНЫЙ ЯЩИК
# источник: scenes3.kartoteka — ящик выезжает сверху, карточки в глубину
# (масштаб и альфа по depth), одна вылетает вперёд с поворотом; тень,
# текстура дерева/бумаги, ручка. Было: ряд одинаковых серых столбиков.
# ===========================================================================
def kartoteka(out=None, t=None, accent="", kick="", channel="", watermark="",
              dur=6.0, sfx=None, **_):
    """P2. --accent — имя на карточке, которая выезжает вперёд, --kick —
    категория на ярлычке ящика."""
    tt, real_t = _settle(t, 1.2, dur)
    acc = _accent(channel)
    img = _graphite_bg(seed=11)
    kk = out_cubic(tt)
    bw, bh = 1180, 620
    bx = int(W / 2 - bw / 2)
    by = int(H * 0.56 - bh / 2 - (1 - kk) * (H * 0.9))
    box = vc.paper(bw, bh, seed=95, tone=(96, 80, 62)).convert("RGBA")
    d = ImageDraw.Draw(box)
    d.rectangle([0, 0, bw - 1, bh - 1], outline=(40, 32, 24, 255), width=5)
    d.rectangle([14, 14, bw - 15, bh - 15], fill=(28, 23, 18, 255))
    n = 9
    hero = n // 2
    rng = random.Random(3)
    for i in range(n - 1, -1, -1):
        depth = i / (n - 1)
        cw, ch = 460, 300
        scl = 1.0 - 0.18 * depth
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rectangle([0, 0, cw - 1, ch - 1], fill=(214, 206, 186, 255), outline=(130, 120, 100, 255), width=2)
        cd.rectangle([0, 0, cw - 1, 14], fill=acc + (255,) if i == hero else (120, 110, 90, 255))
        label = (accent or "ДЕЛО").strip().upper() if i == hero else "ДЕЛО №%d" % (i + 1)
        cd.text((22, 56), label[:22], font=vc.font(F_SANS, 26), fill=(50, 44, 38, 255), anchor="ls")
        for j in range(3):
            wl = rng.randint(140, 320)
            cd.rectangle([22, 90 + j * 46, 22 + wl, 90 + j * 46 + 22], fill=(190, 182, 164, 255))
        card = card.resize((int(cw * scl), int(ch * scl)), Image.LANCZOS)
        cx_ = bw / 2 + depth * 40
        cy_ = bh * 0.60 - depth * 110
        if i == hero:
            prog = clamp((tt - 0.35) / 0.55)
            cy_ -= out_cubic(prog) * 150
            card = vc.alpha(card, 1.0)
            card = card.rotate(-6 * (1 - out_cubic(prog)), Image.BICUBIC, expand=True)
        else:
            card = vc.alpha(card, 1.0 - 0.45 * depth)
        box.alpha_composite(card, (int(cx_ - card.size[0] / 2), int(cy_ - card.size[1] / 2)))
    d.rectangle([0, bh - 150, bw - 1, bh - 1], fill=(112, 94, 72, 255), outline=(40, 32, 24, 255), width=5)
    d.rounded_rectangle([bw / 2 - 90, bh - 95, bw / 2 + 90, bh - 55], radius=16, fill=(170, 150, 118, 255))
    sh, sx, sy = vc.shadow_of((bw, bh), *LAMP, bx + bw / 2, by + bh / 2, blur=30, a=190)
    img = img.convert("RGBA")
    img.alpha_composite(sh, (sx, sy))
    img.alpha_composite(vc.alpha(box, kk), (bx, by))
    img = img.convert("RGB")
    img = _kicker(img, kick or "КАРТОТЕКА", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# P3 · oscillo — ОСЦИЛЛОГРАФ
# источник: scenes5.oscillo (бегущая огибающая звука). Своего аудио у
# карточки нет — оставлен сгенерированный сигнал, но добавлены реальные
# штрихи оригинала: мягкое свечение под кривой, зеркальные столбики.
# ===========================================================================
def oscillo(out=None, t=None, accent="", value="", channel="", watermark="",
           dur=6.0, sfx=None, **_):
    """P3. --accent — подпись сигнала, --value — число у кривой."""
    tt, real_t = _settle(t, 2.2, dur)
    acc = _accent(channel)
    img = _graphite_bg(seed=13)
    d = ImageDraw.Draw(img)
    gx0, gx1 = SAFE_X + 40, W - SAFE_X - 40
    gy0, gy1 = H * 0.30, H * 0.72
    for i in range(0, 11):
        x = gx0 + (gx1 - gx0) * i / 10
        d.line([(x, gy0), (x, gy1)], fill=(42, 72, 50), width=1)
    n = max(2, int(1200 * clamp(tt)))
    pts = []
    for i in range(n):
        frac = i / 1200
        x = gx0 + (gx1 - gx0) * frac
        env = math.exp(-3.2 * frac)
        yv = env * math.sin(frac * 46)
        y = (gy0 + gy1) / 2 - yv * (gy1 - gy0) * 0.42
        pts.append((x, y))
    if len(pts) >= 2:
        glow = vc.layer()
        gd = ImageDraw.Draw(glow)
        gd.line([(p[0] * SS, p[1] * SS) for p in pts], fill=acc + (120,), width=14 * SS, joint="curve")
        glow = glow.filter(ImageFilter.GaussianBlur(10 * SS))
        img = Image.alpha_composite(img.convert("RGBA"), vc.done(glow)).convert("RGB")
        d = ImageDraw.Draw(img)
        d.line(pts, fill=acc, width=5, joint="curve")
    if accent:
        lay = text_layer(accent.strip().upper(), 42, WHITE, gx0, gy0 - 36,
                         font_path=F_SANS, anchor="ls", track=0.08)
        img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
    if value:
        lay = text_layer(str(value), 30, vc.mix(acc, WHITE, 0.4), gx1, gy1 + 50,
                         font_path=F_SANS, anchor="rs", track=0.02)
        img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
    img = _kicker(img, "СИГНАЛ", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# P8 · pismo — ПИСЬМО
# источник: scenes3.pismo/pismo_frame/rukopis — лист бумаги под лампой,
# машинописный текст проявляется по буквам, поверх — рукописная пометка,
# написанная по маске (а не отдельным шрифтом поверх). Тень, бумага,
# виньетка стола.
# ===========================================================================
def pismo(out=None, t=None, text="", kick="", author="", channel="",
         watermark="", dur=6.0, sfx=None, **_):
    """P8. --text — текст письма (печатается по буквам), --author —
    рукописная пометка-подпись (пишется по маске, не наложенный шрифт)."""
    tt, real_t = _settle(t, 2.4, dur)
    img = Image.new("RGB", (W, H), (14, 13, 12))
    img = vc.vignette(img, 0.6)
    pw, ph = 1180, 980
    x0 = int(W / 2 - pw / 2)
    y0 = int(H * 0.52 - ph / 2)
    sh, sx, sy = vc.shadow_of((pw, ph), *LAMP, W / 2, H * 0.52, blur=28, a=170)
    img = img.convert("RGBA")
    img.alpha_composite(sh, (sx, sy))
    sheet = vc.paper(pw, ph, seed=81, tone=(196, 187, 168)).convert("RGBA")
    d = ImageDraw.Draw(sheet)
    d.line([(90, 120), (pw - 90, 120)], fill=(130, 120, 104, 255), width=2)
    lines = wrap(text or "", 48, pw - 220, font_path=F_SERIF)
    total_chars = sum(len(ln) for ln in lines) or 1
    budget = int(total_chars * clamp(tt * 1.4))
    y = 220
    for ln in lines:
        n = min(len(ln), budget)
        budget -= n
        if n > 0:
            d.text((110, y), ln[:n], font=vc.font(F_SERIF, 46), fill=INK + (255,), anchor="ls")
        y += 64
        if budget <= 0 and n < len(ln):
            break
    if author:
        note = vc.masked_write(("— " + str(author)).strip(), 58, F_HAND,
                               (40, 32, 64), clamp((tt - 0.55) / 0.4), (pw, ph))
        note = note.rotate(-3, Image.BICUBIC, expand=False,
                            center=(pw - 420, ph - 220))
        sheet.alpha_composite(note, (pw - 780, ph - 320))
    img.alpha_composite(sheet, (x0, y0))
    img = img.convert("RGB")
    img = _kicker(img, kick or "ПИСЬМО", channel)
    return _finish(img, out, real_t, dur, grain_k=0.04, vig=0.5)


# ===========================================================================
# P11 · schyot_palochek — СЧЁТ ПАЛОЧКАМИ
# источник: scenes6.schyot_palochek — слово крупно всплывает, под ним
# группами по пять растут насечки (пятая наискось), на бумаге с тенью.
# ===========================================================================
def schyot_palochek(out=None, t=None, accent="", value="", channel="",
                    watermark="", dur=6.0, sfx=None, **_):
    """P11. --accent — что считаем, --value — число (по умолчанию 23)."""
    tt, real_t = _settle(t, 1.8, dur)
    acc = _accent(channel)
    img = vc.paper(W, H, seed=5, tone=PAPER).convert("RGBA")
    try:
        n = max(1, min(60, int(str(value).strip() or 23)))
    except ValueError:
        n = 23
    a = int(255 * smoother(clamp(tt * 2)))
    rise = (1 - out_cubic(clamp(tt * 2))) * 30
    if accent:
        lay = text_layer(("«%s»" % accent.strip().upper()), 96, INK, W / 2, H * 0.34 + rise,
                         font_path=F_HEAD, anchor="ms", track=0.03, a=a / 255)
        img.alpha_composite(lay)
    d = ImageDraw.Draw(img)
    shown = int(round(n * clamp((tt - 0.15) / 0.85)))
    x0 = W / 2 - 150
    y0, y1 = H * 0.46, H * 0.58
    for j in range(shown):
        g, r = j // 5, j % 5
        bx = x0 + g * 110 + r * 18
        if r < 4:
            d.line([(bx, y0), (bx, y1)], fill=(30, 28, 26, 255), width=9)
        else:
            d.line([(bx - 80, y1 - 6), (bx + 8, y0 + 6)], fill=(170, 30, 26, 255), width=9)
    img = img.convert("RGB")
    lay = text_layer(str(n), 150, (170, 30, 26), W - SAFE_X - 220, H - 200,
                     font_path=F_HEAD, anchor="rs", track=0.0)
    img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
    img = _kicker(img, "СЧЁТ", channel, color=INK)
    return _finish(img, out, real_t, dur, vig=0.25)


# ===========================================================================
# P12 · liniya_zhizni — ЛИНИЯ ЖИЗНИ
# источник: scenes3.liniya_zhizni — шкала, красный бегунок со свечением,
# вехи встают с подъёмом текста, пройденный путь красный.
# ===========================================================================
def liniya_zhizni(out=None, t=None, accent="", value="", channel="",
                  watermark="", dur=6.0, sfx=None, **_):
    """P12. --accent — подпись отметки, --value — доля пути 0-100."""
    tt, real_t = _settle(t, 1.8, dur)
    acc = _accent(channel)
    img = _graphite_bg(seed=17)
    d = ImageDraw.Draw(img)
    x0, x1 = SAFE_X + 60, W - SAFE_X - 60
    y = H / 2
    d.line([(x0, y), (x1, y)], fill=GREY2, width=5)
    for frac, lbl in ((0.0, "НАЧАЛО"), (1.0, "СЕГОДНЯ")):
        x = x0 + (x1 - x0) * frac
        a = int(255 * clamp(tt * 3))
        d.line([(x, y - 20), (x, y + 20)], fill=GREY, width=3)
        img2 = img.convert("RGBA")
        lay = text_layer(lbl, 28, GREY, x, y + 56, font_path=F_SANS,
                         anchor="ms" if frac else "ls", track=0.08, a=clamp(tt * 3))
        img = Image.alpha_composite(img2, lay).convert("RGB")
        d = ImageDraw.Draw(img)
    try:
        target = max(0.0, min(100.0, float(str(value).strip() or 70))) / 100.0
    except ValueError:
        target = 0.7
    frac_now = out_cubic(tt) * target
    xp = x0 + (x1 - x0) * frac_now
    d.line([(x0, y), (xp, y)], fill=(204, 34, 30), width=6)
    glow = vc.layer()
    gd = ImageDraw.Draw(glow)
    gd.ellipse([(xp - 30) * SS, (y - 30) * SS, (xp + 30) * SS, (y + 30) * SS], fill=(204, 34, 30, 140))
    glow = glow.filter(ImageFilter.GaussianBlur(10 * SS))
    img = Image.alpha_composite(img.convert("RGBA"), vc.done(glow))
    d = ImageDraw.Draw(img)
    d.ellipse([xp - 12, y - 12, xp + 12, y + 12], fill=(204, 34, 30, 255))
    img = img.convert("RGB")
    if accent:
        rise = (1 - out_cubic(tt)) * 26
        lay = text_layer(accent.strip().upper(), 44, WHITE, xp, y - 64 - rise,
                         font_path=F_SANS, anchor="ms", track=0.04, a=clamp(tt * 2))
        img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
    img = _kicker(img, "ЛИНИЯ ЖИЗНИ", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# P14 · pereskaz — ПЕРЕСКАЗ ПО ИЗДАНИЯМ
# источник: scenes5.pereskaz — ряд карточек-изданий, каждая влетает левее
# предыдущей с задержкой, рамка+шапка, стрелка-переход между панелями.
# ===========================================================================
def pereskaz(out=None, t=None, items=None, channel="", watermark="",
            dur=6.0, sfx=None, **_):
    """P14. --item — один пункт (ключ повторить 2-4 раза); каждый ложится
    в свою панель-карточку слева направо, панели соединены стрелкой."""
    tt, real_t = _settle(t, 1.8, dur)
    acc = _accent(channel)
    img = _graphite_bg(seed=19)
    pts = [str(p).strip() for p in (items or []) if str(p).strip()][:4]
    n = max(1, len(pts))
    pw, ph = 420, 200
    gap = 60
    total_w = n * pw + (n - 1) * gap
    x0 = (W - total_w) / 2
    y0 = H * 0.5 - ph / 2
    img = img.convert("RGBA")
    for i, p in enumerate(pts):
        ki = seg(tt, i / n, (i + 1) / n + 0.15)
        if ki <= 0:
            break
        kk = out_cubic(ki)
        xi = x0 + i * (pw + gap)
        panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)
        pd.rectangle([0, 0, pw - 1, ph - 1], fill=(26, 26, 31, 235), outline=(90, 90, 98, 255), width=2)
        pd.rectangle([0, 0, pw - 1, 46], fill=acc)
        pd.text((18, 33), "ВЕРСИЯ %d" % (i + 1), font=vc.font(F_SANS, 24), fill=(20, 18, 16, 255), anchor="ls")
        yy = 96
        for ln in wrap(p, 32, pw - 40, font_path=F_SERIF)[:4]:
            pd.text((20, yy), ln, font=vc.font(F_SERIF, 32), fill=WHITE + (255,), anchor="ls")
            yy += 42
        panel = vc.alpha(panel, clamp(ki * 2.2))
        img.alpha_composite(panel, (int(xi + (1 - kk) * 70), int(y0)))
        if i > 0 and kk > 0.3:
            ad = ImageDraw.Draw(img)
            xa, xb = xi - gap + 12, xi - 12
            yc = y0 + ph / 2
            a = int(255 * kk)
            ad.line([(xa, yc), (xb, yc)], fill=acc + (a,), width=4)
            ad.polygon([(xb, yc), (xb - 16, yc - 9), (xb - 16, yc + 9)], fill=acc + (a,))
    img = img.convert("RGB")
    img = _kicker(img, "ПЕРЕСКАЗ", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# P16 · otschet_dney — ОТСЧЁТ ДНЕЙ
# источник: scenes5.otschet_dney — шкала делений заполняется слева
# направо (седьмая насечка выше), подписи по краям, счётчик растёт.
# ===========================================================================
def otschet_dney(out=None, t=None, accent="", value="", channel="", watermark="",
                 dur=6.0, sfx=None, **_):
    """P16. --value — итоговое число, --accent — подпись под числом."""
    tt, real_t = _settle(t, 1.8, dur)
    acc = _accent(channel)
    img = _graphite_bg(seed=23)
    d = ImageDraw.Draw(img)
    x0, x1 = SAFE_X + 60, W - SAFE_X - 60
    y = H * 0.66
    try:
        target = max(1, int(str(value).strip() or 100))
    except ValueError:
        target = 100
    n = min(92, max(14, target))
    kk = out_cubic(tt)
    m = int(n * kk)
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        on = i < m
        hh = 32 if i % 7 == 0 else 18
        col = acc if on else (66, 66, 72)
        d.rectangle([x - 2, y - hh, x + 2, y + hh], fill=col)
    img = img.convert("RGB")
    shown = int(round(target * kk))
    lay = text_layer(str(shown), 260, acc, W / 2, y - 120, font_path=F_HEAD, anchor="ms", track=0.0)
    img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
    lay = text_layer((accent or "ДНЕЙ").strip().upper(), 42, WHITE, W / 2, y - 60,
                     font_path=F_SANS, anchor="ms", track=0.12)
    img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
    img = _kicker(img, "ОТСЧЁТ", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# P17 · shtamp_lestnica — ШТАМП + ЛЕСТНИЦА ПРОМАХОВ
# источник: scenes6.shtamp/lestnica_promahov — штамп падает с высоты
# (масштаб 1,8→1), резиновая краска с пропусками (шум по альфе), в
# момент удара — кольцо пыли; строки лестницы с красным индексом слева.
# ===========================================================================
_shtamp_cache = {}


def _stamp_texture(text, color):
    key = (text, color)
    if key not in _shtamp_cache:
        s = 2
        f = vc.font(F_SANS, 78 * s)
        d0 = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        tw = text_w(d0, text, f, 0.12)
        w, h = int(tw + 110 * s), 150 * s
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([4 * s, 4 * s, w - 4 * s, h - 4 * s], radius=14 * s,
                            outline=color + (255,), width=6 * s)
        tracked(d, w / 2, h / 2 + 30 * s, text, f, color + (255,), 0.12, "ms")
        n1 = np.asarray(vc.noise(w, h, 71, 1.3), np.float32) / 255.0
        n2 = np.asarray(vc.noise(w, h, 72, 6.0), np.float32) / 255.0
        al = np.asarray(im.getchannel("A"), np.float32) * np.clip(0.35 + 0.9 * n1 * (0.6 + 0.6 * n2), 0, 1)
        im.putalpha(Image.fromarray(np.clip(al, 0, 255).astype(np.uint8), "L"))
        _shtamp_cache[key] = im.resize((w // s, h // s), Image.LANCZOS)
    return _shtamp_cache[key]


def _stamp_stroke(text, color, k, cx, cy, angle=-8.0):
    if k <= 0:
        return None
    im = _stamp_texture(text, color)
    kk = out_expo(k)
    sc = 1.8 - 0.8 * kk
    rot = im.rotate(angle, Image.BICUBIC, expand=True)
    if sc != 1.0:
        rot = rot.resize((max(2, int(rot.size[0] * sc)), max(2, int(rot.size[1] * sc))), Image.LANCZOS)
    rot = vc.alpha(rot, clamp(k * 3) * (0.55 + 0.45 * kk))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(rot, (int(cx - rot.size[0] / 2), int(cy - rot.size[1] / 2)))
    if 0.85 < k < 1.0:
        dust = vc.layer()
        dd = ImageDraw.Draw(dust)
        ph = (k - 0.85) / 0.15
        r = (40 + 220 * ph) * SS
        dd.ellipse([cx * SS - r, cy * SS - r * 0.45, cx * SS + r, cy * SS + r * 0.45],
                   outline=(230, 225, 215, int(160 * (1 - ph))), width=int(6 * SS * (1 - ph) + 1))
        out = Image.alpha_composite(out, vc.done(dust))
    return out


def shtamp_lestnica(out=None, t=None, kick="", accent="", items=None,
                    channel="", watermark="", dur=6.0, sfx=None, **_):
    """P17. --kick — заголовок листа, --item — строка лестницы (повторить
    2-4 раза), --accent — слово штампа (по умолчанию «ОТКАЗ»)."""
    tt, real_t = _settle(t, 1.8, dur)
    acc = _accent(channel)
    img = vc.paper(W, H, seed=9, tone=PAPER).convert("RGBA")
    if kick:
        lay = text_layer(kick.strip().upper(), 44, INK, SAFE_X + 40, 220,
                         font_path=F_HEAD, anchor="ls", track=0.03)
        img.alpha_composite(lay)
    pts = [str(p).strip() for p in (items or []) if str(p).strip()][:4]
    n = max(1, len(pts))
    y = 300
    for i, p in enumerate(pts):
        ki = seg(tt, i / n, (i + 1) / n + 0.1)
        if ki <= 0:
            break
        a = int(255 * smoother(ki))
        yy = y + i * 110 + (1 - out_cubic(ki)) * 30
        lay = text_layer("%02d" % (i + 1), 54, (170, 30, 26), SAFE_X + 150, yy,
                         font_path=F_HEAD, anchor="rs", track=0.03, a=a / 255)
        img.alpha_composite(lay)
        lay = text_layer(p, 38, INK, SAFE_X + 200, yy - 4, font_path=F_SERIF,
                         anchor="ls", track=0.0, a=a * 0.9 / 255)
        img.alpha_composite(lay)
        d = ImageDraw.Draw(img)
        d.line([(SAFE_X + 40, yy + 24), (SAFE_X + 110, yy + 24)], fill=acc + (a,), width=3)
        d.line([(SAFE_X + 110, yy + 24), (W - SAFE_X - 40, yy + 24)], fill=(60, 56, 50, a))
    img = img.convert("RGB")
    k_stamp = clamp((tt - 0.45) / 0.5)
    st = _stamp_stroke((accent or "ОТКАЗ").strip().upper(), (170, 28, 24), k_stamp,
                       W - SAFE_X - 260, 320, -10.0)
    if st is not None:
        img = Image.alpha_composite(img.convert("RGBA"), st).convert("RGB")
    img = _kicker(img, "ШТАМП", channel, color=INK)
    return _finish(img, out, real_t, dur, vig=0.25)


# ===========================================================================
# P18 · sortirovka — СОРТИРОВКА ПО ДВУМ СТОЛБЦАМ
# источник: scenes6.sortirovka — центральная черта растёт, левый столбец
# влетает с зачёркиванием, правый — с точкой-маркером на пружинном вылете.
# ===========================================================================
def sortirovka(out=None, t=None, left="", right="", items=None, channel="",
              watermark="", dur=6.0, sfx=None, **_):
    """P18. --left/--right — ярлыки столбцов, --item (повторить) —
    распределяются по очереди в левый/правый столбец."""
    tt, real_t = _settle(t, 1.8, dur)
    acc = _accent(channel)
    img = _graphite_bg(seed=29)
    pts = [str(p).strip() for p in (items or []) if str(p).strip()][:8]
    lx, rx = W * 0.27, W * 0.73
    k_div = clamp(tt * 2)
    img = img.convert("RGBA")
    d = ImageDraw.Draw(img)
    d.rectangle([W / 2 - 2, H * 0.5 - H * 0.30 * k_div, W / 2 + 2, H * 0.5 + H * 0.30 * k_div], fill=GREY2)
    a_h = int(255 * k_div)
    for x, lbl in ((lx, left or "ОДНО"), (rx, right or "ДРУГОЕ")):
        lay = text_layer(lbl.strip().upper(), 36, WHITE, x, H * 0.22, font_path=F_SANS,
                         anchor="ms", track=0.2, a=a_h / 255)
        img.alpha_composite(lay)
    left_items = pts[0::2][:4]
    right_items = pts[1::2][:4]
    for i, p in enumerate(left_items):
        ki = seg(tt, i / max(1, len(left_items)), (i + 1) / max(1, len(left_items)) + 0.1)
        if ki <= 0:
            continue
        a = int(255 * smoother(ki))
        x = lx - 240 + (1 - out_cubic(ki)) * 260
        y = H * 0.34 + i * 96
        lay = text_layer(p[:28], 34, WHITE, x, y, font_path=F_SERIF, anchor="ls", track=0.0, a=a / 255)
        img.alpha_composite(lay)
    for i, p in enumerate(right_items):
        ki = seg(tt, i / max(1, len(right_items)), (i + 1) / max(1, len(right_items)) + 0.1)
        if ki <= 0:
            continue
        a = int(255 * smoother(ki))
        x = rx - 20 - (1 - out_cubic(ki)) * 260
        y = H * 0.34 + i * 96
        d = ImageDraw.Draw(img)
        r = 10 * out_back(ki)
        d.ellipse([x - 180 - r, y - 14 - r, x - 180 + r, y - 14 + r], fill=acc + (a,))
        lay = text_layer(p[:28], 34, WHITE, x, y, font_path=F_SERIF, anchor="ls", track=0.0, a=a / 255)
        img.alpha_composite(lay)
    img = img.convert("RGB")
    img = _kicker(img, "СОРТИРОВКА", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# P19 · kompas — КОМПАС
# источник: scenes6.kompas — кольцо с 36 делениями, стрелка мечется
# затухающими колебаниями (exp-decay sine) и останавливается на курсе,
# дву­тоновая стрелка (красный нос / серый хвост).
# ===========================================================================
_СТОРОНЫ = {"С": -90, "В": 0, "Ю": 90, "З": 180}


def kompas(out=None, t=None, accent="", value="", channel="", watermark="",
          dur=6.0, sfx=None, **_):
    """P19. --value — угол 0-360 либо буква С/В/Ю/З, --accent — подпись
    под циферблатом."""
    tt, real_t = _settle(t, 2.0, dur)
    acc = _accent(channel)
    img = _graphite_bg(seed=31)
    d = ImageDraw.Draw(img)
    cx, cy, R = W / 2, H * 0.46, 280
    a = int(255 * clamp(tt * 3))
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=(150, 150, 156, a), width=4)
    for i in range(36):
        ang = math.radians(i * 10)
        L = 22 if i % 9 == 0 else 11
        x0, y0 = cx + (R - 4) * math.cos(ang), cy + (R - 4) * math.sin(ang)
        x1, y1 = cx + (R - 4 - L) * math.cos(ang), cy + (R - 4 - L) * math.sin(ang)
        d.line([(x0, y0), (x1, y1)], fill=(150, 150, 156, a), width=2)
    # СТОРОНЫ СВЕТА НА ЦИФЕРБЛАТЕ (27.11.2026, его слово: «разбавить
    # надписями» — принят условно, был самым голым из 12 на отборе).
    img = img.convert("RGBA")
    for letter, deg in _СТОРОНЫ.items():
        rad = math.radians(deg)
        lx = cx + (R - 54) * math.cos(rad)
        ly = cy + (R - 54) * math.sin(rad)
        lay = text_layer(letter, 38, WHITE, lx, ly + 14, font_path=F_SANS,
                         anchor="mm", track=0.0, a=clamp(tt * 3))
        img.alpha_composite(lay)
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    v = str(value).strip().upper()
    target = _СТОРОНЫ.get(v)
    if target is None:
        try:
            target = float(v or 0)
            if target > 180:
                target -= 360
        except ValueError:
            target = 0.0
    kk = clamp(tt)
    swing = 140 * math.exp(-3.2 * kk) * math.sin(kk * 22.0) + \
        target * smoother(min(1.0, kk * 1.3))
    ang = math.radians(swing)
    tip = (cx + (R - 40) * math.cos(ang), cy + (R - 40) * math.sin(ang))
    tail = (cx - (R - 70) * math.cos(ang), cy - (R - 70) * math.sin(ang))
    px, py = -math.sin(ang) * 16, math.cos(ang) * 16
    d.polygon([tip, (cx + px, cy + py), (cx - px, cy - py)], fill=acc + (a,))
    d.polygon([tail, (cx + px, cy + py), (cx - px, cy - py)], fill=(200, 200, 206, a))
    d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=WHITE + (a,))
    # ОКОШКО ОТСЧЁТА (27.11.2026, та же правка «разбавить надписями»):
    # рамка с градусом/буквой курса, как застеклённый индикатор прибора.
    kw = clamp((tt - 0.6) / 0.35)
    if kw > 0:
        bx, by, bw_, bh_ = cx + R + 50, cy - 36, 150, 72
        d.rectangle([bx, by, bx + bw_, by + bh_], outline=(150, 150, 156, int(255 * kw)), width=2)
        disp = v if v in _СТОРОНЫ else "%03d°" % (int(round(target)) % 360)
        img = img.convert("RGBA")
        lay = text_layer(disp, 40, acc, bx + bw_ / 2, by + bh_ / 2 + 14,
                         font_path=F_HEAD, anchor="mm", track=0.0, a=kw)
        img.alpha_composite(lay)
        img = img.convert("RGB")
        d = ImageDraw.Draw(img)
    img = img.convert("RGB")
    if accent:
        lay = text_layer(accent.strip().upper(), 38, WHITE, cx, cy + R + 64,
                         font_path=F_SANS, anchor="ms", track=0.05)
        img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
    img = _kicker(img, "КОМПАС", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# P20 · chertezh — СИНЬКА ЧЕРТЕЖА
# источник: scenes6.chertezh — тёмно-синяя сетка с виньеткой, пунктирный
# маршрут проявляется по длине пути, точки с подписями «ПУНКТ N», стрелка
# в конце.
# ===========================================================================
def chertezh(out=None, t=None, accent="", items=None, channel="", watermark="",
            dur=6.0, sfx=None, **_):
    """P20. --accent — название объекта, --item (повторить 2-4 раза) —
    подпись у точки маршрута."""
    tt, real_t = _settle(t, 2.0, dur)
    acc = _accent(channel)
    BLUE = (18, 30, 48)
    im = Image.new("RGB", (W, H), BLUE)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 56):
        d.line([(x, 0), (x, H)], fill=(40, 56, 78), width=1)
    for y in range(0, H, 56):
        d.line([(0, y), (W, y)], fill=(40, 56, 78), width=1)
    img = vc.vignette(im, 0.32)
    pts_lbl = [str(p).strip() for p in (items or []) if str(p).strip()][:5] or ["ТОЧКА"]
    m = max(2, len(pts_lbl) + 1)
    path = [(W * (0.14 + 0.72 * i / (m - 1)),
             H * (0.68 if i % 2 == 0 else 0.34)) for i in range(m)]
    d = ImageDraw.Draw(img)
    kk = out_cubic(tt)
    total = sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))
    drawn = total * kk
    acc_len = 0.0
    for i in range(len(path) - 1):
        (xa, ya), (xb, yb) = path[i], path[i + 1]
        seg_len = math.dist(path[i], path[i + 1])
        if acc_len >= drawn:
            break
        frac = min(1.0, (drawn - acc_len) / seg_len)
        n_dash = int(seg_len * frac / 22)
        for j in range(n_dash):
            u0, u1 = j * 22 / seg_len, (j * 22 + 12) / seg_len
            d.line([(xa + (xb - xa) * u0, ya + (yb - ya) * u0),
                    (xa + (xb - xa) * u1, ya + (yb - ya) * u1)], fill=(205, 212, 222), width=3)
        acc_len += seg_len
    img = img.convert("RGBA")
    for i, (x, y) in enumerate(path[:-1]):
        ki = seg(tt, i / m, (i + 0.6) / m)
        if ki <= 0:
            continue
        a = int(255 * smoother(ki))
        d2 = ImageDraw.Draw(img)
        r = 9
        d2.ellipse([x - r, y - r, x + r, y + r], outline=(204, 34, 30, a), width=3)
        label = pts_lbl[i] if i < len(pts_lbl) else "ТОЧКА %d" % (i + 1)
        lay = text_layer(label[:24], 26, (205, 212, 222), x + 26, y - 22,
                         font_path=F_SANS, anchor="ls", track=0.08, a=a / 255)
        img.alpha_composite(lay)
    if kk >= 0.98 and len(path) >= 2:
        x, y = path[-1]
        d2 = ImageDraw.Draw(img)
        d2.polygon([(x + 34, y), (x + 6, y - 14), (x + 6, y + 14)], fill=(204, 34, 30, 255))
    img = img.convert("RGB")
    img = _kicker(img, (accent or "ЧЕРТЁЖ"), channel, color=acc)
    return _finish(img, out, real_t, dur, vig=0.3)


# ===========================================================================
# ФИНАЛЬНАЯ ОБРАБОТКА + СОХРАНЕНИЕ — ЕДИНАЯ ТОЧКА ДЛЯ ВСЕХ 12
# ===========================================================================
def _finish(img, out, real_t, dur, grain_k=0.03, vig=0.35, fi=0.3, fo=0.3):
    img = vc.finish(img, real_t, dur, fi=fi, fo=fo, grain_k=grain_k, vig=vig)
    if out:
        img.save(out, quality=92)
        return out
    return img
