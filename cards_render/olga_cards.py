# -*- coding: utf-8 -*-
"""ВОСЕМЬ КАРТОЧЕК ИЗ «ОЛЬГИ ДАЙДЖЕСТ» (27.11.2026) — план в
`effects-library/OPEN-ITEMS.md`, раздел «O-список». Перенесены по тому же
правилу, что и «Верица» (его прямое слово про Верицу: один в один с
исходником, не голая геометрия заново): техника взята из
`~/olga-digest/engine/studio.py` + `core.py` функция за функцией
(`story_open`, `title_card`, `fact_rows`, `big_number`, `checklist`,
`map_panel`, `bars`) — тот же набор примитивов (layer/done/over/alpha/
smoother/seg/out_expo/out_back), та же математика появления (пружина,
растущая линия, затухающий пульс), только фон другой: в оригинале эти
функции кладутся ПОВЕРХ реального видео Ольги, а у самостоятельной
карточки новостного сборщика видео нет — поэтому фон тот же
`core.studio_bg()`, на который само студийное ядро сажает HUD-сцены без
видео (сверено в `scenes.py`: `S.big_number(...)` и `S.title_card(...)`
лежат прямо на `C.studio_bg(t, tone)`, без кадра Ольги под ними).

Акцент карточек «ОЛЬГИ» в фильме — фирменный красный студии (`core.RED`).
Здесь он ЗАМЕНЁН на акцент канала (`_accent(channel)`, как и у «Верицы» —
его правило 27.11: «нужно каждому каналу своя цветовая гамма») везде, где
цвет несёт опознавание бренда (плашки, крупное число, точка на карте,
растущие полосы). Семантический цвет «да/нет» в чек-листе (галочка/крест)
оставлен исходным — это не бренд, а значение, роль та же, что у семафора.

Возвращает RGB-кадр 1920×1080 (ждёт `render_cards`/`style_cards.render_anim`).
"""
import math
import os
import re
import sys

from PIL import Image, ImageDraw

import olga_core as oc

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
_TEMPLATE = os.path.join(os.path.dirname(HERE), "template")
if _TEMPLATE not in sys.path:
    sys.path.insert(0, _TEMPLATE)
try:
    import palitra
except Exception:
    palitra = None

W, H = oc.W, oc.H
SS = oc.SS
SAFE_X, SAFE_Y = 96, 54

clamp, lerp, smoother = oc.clamp, oc.lerp, oc.smoother
out_cubic, out_expo, out_back, seg = oc.out_cubic, oc.out_expo, oc.out_back, oc.seg
layer, done, over, alpha = oc.layer, oc.done, oc.over, oc.alpha
tracked, text_w, wrap, fit_px = oc.tracked, oc.text_w, oc.wrap, oc.fit_px
RED, BLUE, WHITE, GREY, GREY2, LINE = oc.RED, oc.BLUE, oc.WHITE, oc.GREY, oc.GREY2, oc.LINE


def _accent(channel):
    if palitra is not None and channel:
        try:
            return tuple(palitra.accent(channel, tiho=True))
        except Exception:
            pass
    return RED


def text_layer(text, kind, px, color, x, y, anchor="ls", track=0.0, a=1.0):
    im = layer()
    d = ImageDraw.Draw(im)
    f = oc.font(kind, px * SS)
    col = tuple(color) + (int(255 * clamp(a)),)
    tracked(d, x * SS, y * SS, text, f, col, track, anchor)
    return done(im)


def _settle(t, window, dur):
    """см. verica_cards._settle — тот же живой баг (постер в зоне fade-out
    у финишной функции давал чёрный кадр), то же лечение: постеру давать
    точку ПОСЛЕ появления и ДО угасания, не конец ролика."""
    if t is None:
        settled = window + 0.15
        return 1.0, min(settled, max(0.0, dur - 0.4))
    return clamp(t / max(0.01, window)), t


def _finish(img, out, real_t, dur, fi=0.25, fo=0.3):
    """fade в чёрное по краям клипа — у реального движка переходов между
    сценами нет (монтаж режет жёстко по мастер-таймкоду голоса, см.
    `sborka.py`), но самостоятельная карточка в новостном сборщике — это
    изолированный клип без соседей по той же шкале, и без краевого fade
    первый/последний кадр обрывается щелчком."""
    k = min(smoother(seg(real_t, 0, fi)), 1 - smoother(seg(real_t, dur - fo, dur)))
    img = oc.fade(img, max(0.0, k)) if k < 0.999 else img
    if out:
        img.save(out, quality=92)
        return out
    return img


def _kicker(img, text, channel, color=None, y=SAFE_Y + 26):
    if not text:
        return img
    col = color or _accent(channel)
    lay = text_layer(text.strip().upper(), "head", 30, col, SAFE_X, y, anchor="ls", track=0.16)
    return Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")


def _panel_title(img, title, x, y, color, r=8):
    """плашка-заголовок окна/панели — `studio.panel()`/`map_panel()`'s
    framed(label=...), перенесено как отдельная функция, чтобы ставить и
    на фон без окна."""
    if not title:
        return img
    im = layer()
    d = ImageDraw.Draw(im)
    f = oc.font("head", 24 * SS)
    tw = text_w(d, title.upper(), f, 0.14) + 32 * SS
    d.rounded_rectangle([x * SS, y * SS, x * SS + tw, (y + 44) * SS], radius=r * SS, fill=color + (255,))
    d.rectangle([x * SS, (y + 20) * SS, x * SS + tw, (y + 44) * SS], fill=color + (255,))
    tracked(d, (x + 16) * SS, (y + 31) * SS, title.upper(), f, WHITE + (255,), 0.14)
    im = done(im)
    return Image.alpha_composite(img.convert("RGBA"), im).convert("RGB")


# ===========================================================================
# O7 · otbivka — ОТБИВКА СЮЖЕТА
# источник: studio.story_open — диагональная шторка проходит через кадр,
# номер сюжета крупно, заголовок и место; тёмная подложка держит текст.
# ===========================================================================
def otbivka(out=None, t=None, value="", accent="", kick="", channel="",
            watermark="", dur=4.5, sfx=None, **_):
    """O7. --value — номер сюжета (по умолчанию 1), --accent — заголовок,
    --kick — место/источник."""
    window = 1.5
    tt, real_t = _settle(t, window, dur)
    acc = _accent(channel)
    try:
        num = int(float(value)) if value else 1
    except (TypeError, ValueError):
        num = 1
    title = (accent or "НОВОСТЬ").strip()
    place = (kick or "").strip()

    img = oc.studio_bg(real_t, 0.3).convert("RGBA")
    ov = layer()
    d = ImageDraw.Draw(ov)
    k1 = seg(tt, 0.0, 0.5)
    x_in = lerp(-W * 0.6, W * 1.3, out_cubic(k1)) * SS
    poly = [(x_in - 380 * SS, 0), (x_in, 0), (x_in - 380 * SS, H * SS), (x_in - 760 * SS, H * SS)]
    d.polygon(poly, fill=acc + (255,))
    poly2 = [(x_in - 440 * SS, 0), (x_in - 380 * SS, 0), (x_in - 760 * SS, H * SS), (x_in - 820 * SS, H * SS)]
    d.polygon(poly2, fill=(255, 255, 255, 190))

    k3 = seg(tt, 0.4, 0.75)
    a = int(255 * smoother(k3))
    if a > 0:
        d.rectangle([0, 0, W * SS, H * SS], fill=(6, 10, 20, int(a * 0.86)))
        fn = oc.font("head", 260 * SS)
        kn = out_back(seg(tt, 0.5, 1.0))
        tracked(d, (SAFE_X) * SS + (1 - kn) * -200 * SS, (H * 0.55 + 80) * SS,
                "%02d" % num, fn, acc + (int(a * kn),), 0.0)
        ft = oc.font("head", 72 * SS)
        lines = wrap(title.upper(), "head", 72, W - SAFE_X - 500)[:2]
        kt = seg(tt, 0.65, 1.1)
        for i, ln in enumerate(lines):
            ka = smoother(seg(kt, i * 0.2, i * 0.2 + 0.6))
            tracked(d, (SAFE_X + 410) * SS, (H * 0.5 - 10 + i * 82) * SS + (1 - ka) * 30 * SS,
                    ln, ft, WHITE + (int(a * ka),), 0.02)
        if place:
            fp = oc.font("head_r", 30 * SS)
            kp = smoother(seg(tt, 1.0, 1.4))
            yy = (H * 0.5 - 10 + len(lines) * 82 + 6) * SS
            d.rectangle([(SAFE_X + 410) * SS, yy - 2 * SS, (SAFE_X + 410) * SS + 220 * SS * kp, yy + 2 * SS],
                        fill=acc + (int(a * kp),))
            tracked(d, (SAFE_X + 410) * SS, yy + 44 * SS, place.upper(), fp, GREY + (int(a * kp),), 0.2)
    img = Image.alpha_composite(img, done(ov)).convert("RGB")
    return _finish(img, out, real_t, dur)


# ===========================================================================
# O8 · zastavka — ЗАСТАВКА ВЫПУСКА
# источник: studio.title_card — красная плита выезжает из центра, имя
# крупно внутри, подзаголовок снизу с растущей чертой.
# ===========================================================================
def zastavka(out=None, t=None, accent="", kick="", channel="",
             watermark="", dur=3.5, sfx=None, **_):
    """O8. --accent — имя выпуска крупно (по умолчанию «ОЛЬГА ДАЙДЖЕСТ»),
    --kick — подзаголовок (по умолчанию «ВЫПУСК НОВОСТЕЙ»)."""
    window = 1.1
    tt, real_t = _settle(t, window, dur)
    acc = _accent(channel)
    big = (accent or "ОЛЬГА ДАЙДЖЕСТ").strip().upper()
    small = (kick or "ВЫПУСК НОВОСТЕЙ").strip().upper()

    img = oc.studio_bg(real_t, 0.5).convert("RGBA")
    ov = layer()
    d = ImageDraw.Draw(ov)
    big_px = fit_px(big, "head", 150, W - 240)
    f = oc.font("head", big_px * SS)
    kk = out_expo(seg(tt, 0, 0.6))
    a = int(255 * seg(tt, 0, 0.3))
    tw = text_w(d, big, f, 0.04)
    cx, cy = W * SS / 2, H * SS * 0.5
    pw = (tw + 120 * SS) * kk
    d.rectangle([cx - pw / 2, cy - (big_px * 0.73) * SS, cx + pw / 2, cy + (big_px * 0.47) * SS], fill=acc + (a,))
    kt = seg(tt, 0.3, 0.8)
    if kt > 0:
        tracked(d, cx, cy + big_px * 0.33 * SS, big, f, WHITE + (int(255 * kt),), 0.04, "ms")
    ks = seg(tt, 0.7, 1.1)
    if ks > 0:
        f2 = oc.font("head_l", 36 * SS)
        tracked(d, cx, cy + big_px * 0.87 * SS, small, f2, GREY + (int(255 * ks),), 0.4, "ms")
        d.rectangle([cx - 120 * SS * ks, cy + (big_px * 0.87 + 20) * SS,
                     cx + 120 * SS * ks, cy + (big_px * 0.87 + 23) * SS], fill=WHITE + (int(255 * ks),))
    img = Image.alpha_composite(img, done(ov)).convert("RGB")
    return _finish(img, out, real_t, dur)


# ===========================================================================
# O14 · stroki_faktov — СТРОКИ ФАКТОВ
# источник: studio.fact_rows — серая подпись сверху, белое значение
# снизу, появляются по одной слева с лёгким сдвигом; левая кромка цвета
# акцента.
# ===========================================================================
def stroki_faktov(out=None, t=None, items=None, kick="", channel="",
                   watermark="", dur=5.0, sfx=None, **_):
    """O14. --item (повторить 2-5 раз) в формате «Подпись=Значение»,
    --kick — общий заголовок панели."""
    items = items or []
    rows = []
    for it in items[:5]:
        if "=" in it:
            lab, val = it.split("=", 1)
        else:
            lab, val = "", it
        rows.append((lab.strip() or "ФАКТ", val.strip()))
    if not rows:
        rows = [("ФАКТ", "—")]
    step = 0.32
    window = max(1.2, len(rows) * step + 0.5)
    tt, real_t = _settle(t, window, dur)
    acc = _accent(channel)
    k = real_t

    img = oc.studio_bg(real_t, 0.2).convert("RGBA")
    x, y = SAFE_X + 10, int(H * 0.5 - (len(rows) * 150) / 2)
    ov = layer()
    d = ImageDraw.Draw(ov)
    fl = oc.font("head_r", 22 * SS)
    fv = oc.font("head", 44 * SS)
    yy = y * SS
    for i, (lab, val) in enumerate(rows):
        kk = smoother(seg(k, i * step, i * step + 0.4))
        if kk <= 0:
            break
        a = int(255 * kk)
        dx = (1 - kk) * 34 * SS
        d.rectangle([x * SS + dx, yy, x * SS + dx + 5 * SS, yy + 96 * SS], fill=acc + (a,))
        tracked(d, x * SS + 24 * SS + dx, yy + 26 * SS, lab.upper(), fl, GREY + (a,), 0.2)
        vpx = fit_px(val, "head", 44, 1000)
        tracked(d, x * SS + 24 * SS + dx, yy + 86 * SS, val, oc.font("head", vpx * SS), WHITE + (a,), 0.01)
        yy += 150 * SS
    img = Image.alpha_composite(img, done(ov)).convert("RGB")
    img = _kicker(img, kick or "СТРОКИ ФАКТОВ", channel, color=acc)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# O16 · krupnoe_chislo — КРУПНОЕ ЧИСЛО
# источник: studio.big_number(rings=True) — число со счётчиком-разгоном и
# затухающими кольцами, подпись снизу, label сверху.
# ===========================================================================
def krupnoe_chislo(out=None, t=None, value="", accent="", kick="", channel="",
                    watermark="", dur=4.0, sfx=None, **_):
    """O16. --value — итоговое число, --accent — слово рядом (единица),
    --kick — подпись над числом."""
    window = 1.3
    tt, real_t = _settle(t, window, dur)
    acc = _accent(channel)
    k = real_t
    try:
        val = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        val = 0.0

    img = oc.studio_bg(real_t, 0.4).convert("RGBA")
    ov = layer()
    d = ImageDraw.Draw(ov)
    kk = out_expo(k)
    a = int(255 * clamp(k * 3))
    cur = lerp(0.0, val, kk)
    shown = "{:,.0f}".format(cur).replace(",", " ") if abs(val - round(val)) < 1e-6 else "{:,.1f}".format(cur)
    px = 190
    fn = oc.font("head", px * SS)
    fu = oc.font("head_l", int(px * 0.42) * SS)
    nw = text_w(d, shown, fn, 0.0)
    unit = (accent or "").strip()
    uw = text_w(d, unit, fu, 0.1) if unit else 0
    gap = px * 0.16 * SS if unit else 0
    cx, cy = W / 2, H * 0.54
    x = cx * SS - (nw + gap + uw) / 2
    y = cy * SS + px * 0.36 * SS
    tracked(d, x, y, shown, fn, acc + (a,), 0.0)
    if unit:
        tracked(d, x + nw + gap, y, unit, fu, WHITE + (a,), 0.1)
    if kick:
        fl = oc.font("head_r", int(px * 0.17) * SS)
        tracked(d, cx * SS, (cy - px * 0.58) * SS, kick.upper(), fl, GREY + (a,), 0.3, "ms")
    if 0 < k < 1.3:
        for j in range(3):
            r = (px * 0.8 + j * px * 0.3) * SS * (0.5 + 0.9 * kk)
            ra = int(110 * (1 - kk) * (1 - j * 0.3))
            if ra > 0:
                d.ellipse([cx * SS - r, cy * SS - r, cx * SS + r, cy * SS + r], outline=acc + (ra,), width=2 * SS)
    img = Image.alpha_composite(img, done(ov)).convert("RGB")
    return _finish(img, out, real_t, dur)


# ===========================================================================
# O30 · schetchik_let — СЧЁТЧИК ЛЕТ
# источник: studio.big_number(rings=False) — тот же счётчик, без колец,
# для лет/годовщин (его хватает без пульсации кольцами фильма).
# ===========================================================================
def schetchik_let(out=None, t=None, value="", accent="", kick="", channel="",
                   watermark="", dur=4.0, sfx=None, **_):
    """O30. --value — число лет, --accent — слово рядом (по умолчанию
    «ЛЕТ»), --kick — подпись над числом."""
    return krupnoe_chislo(out=out, t=t, value=value, accent=accent or "ЛЕТ",
                          kick=kick, channel=channel, watermark=watermark,
                          dur=dur, sfx=sfx, rings=False)


# ===========================================================================
# O19 · cheklist — ЧЕК-ЛИСТ
# источник: studio.checklist — рамка, галочка/крест рисуются штрихами
# (не шрифтом), зачёркивание у отрицательных пунктов.
# ===========================================================================
def cheklist(out=None, t=None, items=None, kick="", channel="",
             watermark="", dur=5.0, sfx=None, **_):
    """O19. --item (повторить 2-5 раз): префикс «+» — сделано (галочка),
    «-» — нет (крест, зачёркнуто), «?» — неизвестно; без префикса — «+»."""
    items = items or []
    rows = []
    for it in items[:5]:
        txt = it.strip()
        ok = True
        if txt[:1] in ("+", "-", "?"):
            ok = {"+": True, "-": False, "?": None}[txt[0]]
            txt = txt[1:].strip()
        rows.append((txt or "ПУНКТ", ok))
    if not rows:
        rows = [("ПУНКТ", True)]
    step = 0.5
    window = max(1.2, len(rows) * step + 0.5)
    tt, real_t = _settle(t, window, dur)
    k = real_t

    img = oc.studio_bg(real_t, 0.2).convert("RGBA")
    ov = layer()
    d = ImageDraw.Draw(ov)
    x, y = SAFE_X + 10, int(H * 0.5 - (len(rows) * 78) / 2)
    f = oc.font("head_m", 40 * SS)
    for i, (txt, ok) in enumerate(rows):
        ki = seg(k, i * step, i * step + 0.5)
        if ki <= 0:
            break
        a = int(255 * smoother(ki))
        yy = (y + i * 78) * SS
        bx = x * SS
        d.rounded_rectangle([bx, yy - 24 * SS, bx + 48 * SS, yy + 24 * SS], radius=8 * SS, outline=LINE + (a,), width=2 * SS)
        km = smoother(seg(ki, 0.5, 1.0))
        if ok is None:
            d.text((bx + 24 * SS, yy), "?", font=oc.font("head", 44 * SS), fill=RED + (int(a * km),), anchor="mm")
        elif ok:
            d.line([bx + 12 * SS, yy, bx + 12 * SS + 10 * SS * km, yy + 10 * SS * km], fill=BLUE + (a,), width=5 * SS)
            d.line([bx + 22 * SS, yy + 10 * SS, bx + 22 * SS + 16 * SS * km, yy + 10 * SS - 22 * SS * km], fill=BLUE + (a,), width=5 * SS)
        else:
            d.line([bx + 12 * SS, yy - 12 * SS, bx + 12 * SS + 24 * SS * km, yy - 12 * SS + 24 * SS * km], fill=RED + (a,), width=5 * SS)
            d.line([bx + 36 * SS, yy - 12 * SS, bx + 36 * SS - 24 * SS * km, yy - 12 * SS + 24 * SS * km], fill=RED + (a,), width=5 * SS)
        tw = tracked(d, bx + 70 * SS, yy + 14 * SS, txt, f, (RED if ok is None else WHITE) + (a,), 0.02)
        if ok is False and km > 0:
            d.line([bx + 70 * SS, yy, bx + 70 * SS + tw * km, yy], fill=RED + (a,), width=4 * SS)
    img = Image.alpha_composite(img, done(ov)).convert("RGB")
    img = _kicker(img, kick or "ЧЕК-ЛИСТ", channel)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# O23 · polosy — ПОЛОСЫ СРАВНЕНИЯ
# источник: studio.bars — горизонтальные полосы растут по очереди,
# подпись слева, значение справа; полоса цвета акцента канала.
# ===========================================================================
def polosy(out=None, t=None, items=None, kick="", channel="",
           watermark="", dur=5.0, sfx=None, **_):
    """O23. --item (повторить 2-5 раз) в формате «Подпись=Число[=Текст]»;
    текст значения — по умолчанию само число."""
    items = items or []
    rows = []
    for it in items[:5]:
        parts = it.split("=")
        lab = parts[0].strip() if parts else it.strip()
        try:
            val = float(parts[1]) if len(parts) > 1 else 1.0
        except (TypeError, ValueError):
            val = 1.0
        vtxt = parts[2].strip() if len(parts) > 2 else ("%.0f" % val if val == int(val) else str(val))
        rows.append((lab or "СТРОКА", val, vtxt))
    if not rows:
        rows = [("СТРОКА", 1.0, "1")]
    step = 0.5
    window = max(1.2, len(rows) * step + 0.7)
    tt, real_t = _settle(t, window, dur)
    acc = _accent(channel)
    k = real_t

    img = oc.studio_bg(real_t, 0.2).convert("RGBA")
    ov = layer()
    d = ImageDraw.Draw(ov)
    w = W - SAFE_X * 2
    x, y = SAFE_X, int(H * 0.5 - (len(rows) * 96) / 2)
    mv = max(v for _, v, _ in rows) or 1
    fl = oc.font("head_r", 22 * SS)
    fv = oc.font("head", 30 * SS)
    for i, (lab, val, vtxt) in enumerate(rows):
        ki = seg(k, i * step, i * step + 0.7)
        if ki <= 0:
            break
        a = int(255 * smoother(seg(ki, 0, 0.4)))
        yy = (y + i * 96) * SS
        tracked(d, x * SS, yy + 20 * SS, lab.upper(), fl, GREY + (a,), 0.18)
        bw = (w - 170) * SS * (val / mv) * out_expo(ki)
        d.rounded_rectangle([x * SS, yy + 34 * SS, x * SS + (w - 170) * SS, yy + 62 * SS], radius=6 * SS, fill=(255, 255, 255, 18))
        if bw > 2:
            d.rounded_rectangle([x * SS, yy + 34 * SS, x * SS + max(bw, 12 * SS), yy + 62 * SS], radius=6 * SS, fill=acc + (a,))
        tracked(d, (x + w) * SS, yy + 62 * SS, vtxt, fv, WHITE + (a,), 0.0, "rs")
    img = Image.alpha_composite(img, done(ov)).convert("RGB")
    img = _kicker(img, kick or "ПОЛОСЫ СРАВНЕНИЯ", channel, color=acc)
    return _finish(img, out, real_t, dur)


# ===========================================================================
# O21 · karta_koltso — КАРТА С КОЛЬЦОМ
# источник: studio.map_panel — контурная карта окна, страна подсвечена,
# лёгкий наезд-зум, точка с тройным затухающим кольцом-пульсом и подписью.
# Координаты страны/города берёт `card_put.py` из своих справочников
# (ГОРОДА/СТРАНЫ/СТОЛИЦЫ) — числа сюда приходят уже проверенные, не с
# потолка (его правило 16.11 про Эстонию-Россию-4800км).
# ===========================================================================
def karta_koltso(out=None, t=None, lon_c=0.0, lat_c=0.0, span=14.0,
                  point_lon=None, point_lat=None, country="", accent="",
                  kick="", title="", channel="", watermark="", dur=5.0,
                  sfx=None, **_):
    """O21. Координаты и русское имя страны (`country`, для подсветки
    полигона) резолвит дверь по --accent (страна/город) через свои
    справочники ГОРОДА/СТРАНЫ/СТОЛИЦЫ — не халлюцинация числами (его
    правило 16.11 про Эстонию-Россию-4800км). --kick — подпись у точки,
    --title — заголовок окна карты."""
    window = 1.6
    tt, real_t = _settle(t, window, dur)
    acc = _accent(channel)
    k = real_t
    w, h = 1400, 820
    bx, by = int(W / 2 - w / 2), int(H / 2 - h / 2)

    cosl = max(0.2, math.cos(math.radians(lat_c)))
    dlon = span / 2
    dlat = span * (h / w) * cosl / 2
    lon = (lon_c - dlon, lon_c + dlon)
    lat = (lat_c - dlat, lat_c + dlat)

    base = _map_base((w, h), lon, lat, focus=country or None, accent=acc)
    kk = out_expo(seg(k, 0, 1.2))
    z = 1.06 - 0.06 * kk
    bw, bh = int(w * z), int(h * z)
    base = base.resize((bw, bh), Image.LANCZOS).crop(((bw - w) // 2, (bh - h) // 2, (bw - w) // 2 + w, (bh - h) // 2 + h))

    ov = layer(w, h)
    d = ImageDraw.Draw(ov)

    def xy(lo, la):
        u = (lo - lon[0]) / (lon[1] - lon[0])
        v = 1 - (la - lat[0]) / (lat[1] - lat[0])
        return (u * w * SS, v * h * SS)

    plon = point_lon if point_lon is not None else lon_c
    plat = point_lat if point_lat is not None else lat_c
    px, py = xy(plon, plat)
    kp = seg(k, 0.5, 1.0)
    if kp > 0:
        for j in range(3):
            ph = (k * 0.7 + j * 0.33) % 1.0
            r = (10 + 60 * ph) * SS
            a = int(200 * (1 - ph) * kp)
            d.ellipse([px - r, py - r, px + r, py + r], outline=acc + (a,), width=2 * SS)
        r0 = 8 * SS
        d.ellipse([px - r0, py - r0, px + r0, py + r0], fill=acc + (int(255 * kp),))
        d.ellipse([px - 3 * SS, py - 3 * SS, px + 3 * SS, py + 3 * SS], fill=WHITE + (int(255 * kp),))
    if kick and kp > 0.3:
        kl = seg(kp, 0.3, 1.0)
        f = oc.font("head", 26 * SS)
        tw = text_w(d, kick.upper(), f, 0.1)
        lx, ly = px + 20 * SS, py - 24 * SS
        if lx + tw + 28 * SS > w * SS:
            lx = max(8 * SS, px - 20 * SS - tw - 22 * SS)
        ly = max(30 * SS, ly)
        d.rectangle([lx, ly - 20 * SS, lx + tw + 22 * SS, ly + 14 * SS], fill=(6, 10, 18, int(220 * kl)))
        d.rectangle([lx, ly - 20 * SS, lx + 4 * SS, ly + 14 * SS], fill=acc + (int(255 * kl),))
        tracked(d, lx + 12 * SS, ly + 4 * SS, kick.upper(), f, WHITE + (int(255 * kl),), 0.1)
    ov = done(ov, w, h)
    pic = Image.alpha_composite(base.convert("RGBA"), ov)

    img = oc.studio_bg(real_t, 0.2).convert("RGBA")
    kf = seg(k, 0, 0.5)
    sc = 0.92 + 0.08 * out_expo(kf)
    ww, hh = int(w * sc), int(h * sc)
    xx, yy = int(bx + (w - ww) / 2), int(by + (h - hh) / 2)
    pic2 = pic.resize((ww, hh), Image.LANCZOS)
    sh, pad = oc.shadow((ww, hh), 26, int(150 * out_expo(kf)), 10)
    img.paste(sh, (xx - pad, yy - pad), sh)
    pic_a = alpha(pic2, out_expo(kf))
    if pic_a is not None:
        img.alpha_composite(pic_a, (xx, yy))
    dd = ImageDraw.Draw(img)
    dd.rounded_rectangle([xx, yy, xx + ww - 1, yy + hh - 1], radius=10, outline=LINE + (255,), width=2)
    img = img.convert("RGB")
    img = _panel_title(img, title or "КАРТА", bx, by, acc)
    img = _kicker(img, "КАРТА С КОЛЬЦОМ", channel, color=acc, y=H - 50)
    return _finish(img, out, real_t, dur)


_MAP_CACHE = {}
_GEO = None


def _geo():
    """Контуры стран — та же папка `fullcycle/geo/countries.geojson`, что
    уже возит на раннер `charts.cartogram`/`charts.map_dist` (и так же
    едет туда: `cards_cloud.py` шлёт `geo/` при любом виде со словом «map»
    в имени — `_needs_geo` там дополнена именем `olga_cards.karta_koltso`
    явно, в самом слове «koltso» подстроки «map» нет)."""
    global _GEO
    if _GEO is not None:
        return _GEO
    import json
    p = os.path.join(HERE, "geo", "countries.geojson")
    _GEO = json.load(open(p, encoding="utf-8"))["features"] if os.path.exists(p) else []
    return _GEO


def _rings(ft):
    g = ft["geometry"]
    if g["type"] == "Polygon":
        return [g["coordinates"][0]]
    if g["type"] == "MultiPolygon":
        return [p[0] for p in g["coordinates"]]
    return []


def _name_ru(ft):
    p = ft["properties"]
    return p.get("NAME_RU") or p.get("ADMIN") or p.get("NAME") or ""


def _norm_place(s):
    return re.sub(r"[^А-ЯA-Z]", "", str(s or "").upper().replace("Ё", "Е"))


def _focus_hit(name_ru, focus):
    """сверка нестрогая (регистр/пробелы/«Китай» внутри «Китайская Народная
    Республика») — подсветка полигона необязательный штрих, не гейт: не
    нашли точно — карта всё равно работает, просто без закраски страны."""
    if not focus:
        return False
    a, b = _norm_place(name_ru), _norm_place(focus)
    if not a or not b:
        return False
    if a == b:
        return True
    n = min(len(a), len(b))
    return n >= 4 and a[:min(5, n)] == b[:min(5, n)]


def _mix3(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _map_base(size, lon, lat, focus=None, accent=None):
    """Палитра карты ПЕРЕДЕЛАНА 27.11.2026 (его прямое слово «я не вижу
    никакой карты»): прежние тона суши/океана (10,16,30 / 26,36,56 / 44,58,
    86) были практически неотличимы друг от друга И от фона студии
    (`core.studio_bg`, 8,13,24 — тот же класс темноты), поэтому карта
    сливалась в сплошное тёмное пятно. Суша теперь заметно светлее океана,
    страна-фокус — не чуть светлее соседей, а в цвете АКЦЕНТА КАНАЛА (его
    же правило 27.11 «каждому каналу своя цветовая гамма», применено и
    здесь, а не только к надписям)."""
    key = (size, lon, lat, focus, accent)
    if key in _MAP_CACHE:
        return _MAP_CACHE[key].copy()
    w, h = size
    OCEAN = (16, 22, 34, 255)
    LAND = (64, 86, 118, 255)
    acc3 = accent if accent else RED
    FOCUS = _mix3(LAND[:3], acc3, 0.6) + (255,)
    im = Image.new("RGBA", (w * SS, h * SS), OCEAN)
    d = ImageDraw.Draw(im)

    def xy(p):
        u = (p[0] - lon[0]) / (lon[1] - lon[0])
        v = 1 - (p[1] - lat[0]) / (lat[1] - lat[0])
        return (u * w * SS, v * h * SS)

    for ft in _geo():
        rs = _rings(ft)
        hit = _focus_hit(_name_ru(ft), focus)
        for ring in rs:
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            if max(xs) < lon[0] - 5 or min(xs) > lon[1] + 5 or max(ys) < lat[0] - 5 or min(ys) > lat[1] + 5:
                continue
            pts = [xy(p) for p in ring]
            if len(pts) < 3:
                continue
            fill = FOCUS if hit else LAND
            outline = tuple(min(255, c + 40) for c in fill[:3]) + (255,)
            d.polygon(pts, fill=fill, outline=outline)
    step = 1.0 if (lon[1] - lon[0]) < 8 else 5.0
    g0 = math.floor(lon[0] / step) * step
    while g0 <= lon[1]:
        x0, _ = xy((g0, lat[0]))
        d.line([x0, 0, x0, h * SS], fill=(255, 255, 255, 14), width=1)
        g0 += step
    g0 = math.floor(lat[0] / step) * step
    while g0 <= lat[1]:
        _, y0 = xy((lon[0], g0))
        d.line([0, y0, w * SS, y0], fill=(255, 255, 255, 14), width=1)
        g0 += step
    im = im.resize((w, h), Image.LANCZOS)
    _MAP_CACHE[key] = im
    return im.copy()
