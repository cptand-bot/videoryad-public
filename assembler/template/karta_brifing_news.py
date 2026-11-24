# -*- coding: utf-8 -*-
"""КАРТА-БРИФИНГ В НОВОСТНОМ КОНВЕЙЕРЕ — один вид, `card:karta_brifing`
(24.11.2026, его прямое слово «раскатай на все трубы, завтра применим»).

ЧТО ЭТО. Карта региона Украина/Чёрное море (рельеф, подсветка Украина/
Россия, подписи Чёрное/Азовское море/Крым) + радар и зона на точке события,
взятой ИЗ ТЕКСТА СЦЕНЫ словарём `place_lookup.py` (есть название из
`data/places_ua_theater.json` — радар едет туда, нет — остаётся на Киеве).

ТОЛЬКО ЭТОТ РЕГИОН. Вид годится СТРОГО для тем Украина/Россия/Крым/
Чёрное море — другой географии подложка не знает (это не общий геокодер,
словарь ручной, 30 точек). Вкладка ставит вид только там, где это действительно
войне/региону подходит, не на любую военную тему мира.

ОТКУДА ВЗЯТО. Движок — скилл `karta-brifing` (прототип P4, полка `B1-B20`
общей библиотеки). Тяжёлая часть (рельеф Natural Earth II, 89 МБ, 3D-макеты
кораблей) в облако НЕ едет — подложка запечена ОДИН РАЗ заранее
(`karta_brifing_data/base_map.jpg` + `meta.json`, 160 КБ) тем же
`karta-brifing/engine/prep_ukraine.py`, что лежит в скилле. Здесь — только
дешёвая композиция поверх готовой картинки: `karta_brifing_atoms.py` —
копия `karta-brifing/engine/atoms.py` (чистый PIL+numpy, без тяжёлых
зависимостей), один в один, если меняете — меняйте в обоих местах.

НЕ ОБЯЗАТЕЛЬНЫЙ ЭЛЕМЕНТ. В `obyazatelno.py` не вписан — ставится вручную,
когда сцена по смыслу подходит, не на каждый ролик.

Возвращает RGB-кадр 1920×1080 (этого ждёт `style_cards.render_anim`).
"""
import json
import math
import os

from PIL import Image, ImageDraw

import karta_brifing_atoms as A
import place_lookup as PL

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "karta_brifing_data")

W, H = 1920, 1080
_NATIVE = (1600, 900)   # разрешение запечённой подложки — ровно 16:9, тот же кадр без обрезки

_base = None
_meta = None


def _load():
    global _base, _meta
    if _base is None:
        _base = Image.open(os.path.join(DATA, "base_map.jpg")).convert("RGB")
        with open(os.path.join(DATA, "meta.json"), encoding="utf-8") as f:
            _meta = json.load(f)
    return _base, _meta


def _ease(t):
    return t * t * (3 - 2 * t)


def _kb(base, t, zoom=0.05, cx=0.5, cy=0.5):
    z = 1.0 + zoom * _ease(t)
    w, h = base.size
    nw, nh = w / z, h / z
    x0 = (w - nw) * cx
    y0 = (h - nh) * cy
    return base.crop((x0, y0, x0 + nw, y0 + nh)).resize(_NATIVE, Image.LANCZOS)


def _знак(img, watermark):
    """Подпись канала в правом верхнем углу — вне полосы субтитров (та же
    зона, что держат приёмы белого зала)."""
    if not watermark:
        return
    ImageDraw.Draw(img, "RGBA").text(
        (W - 96 - 150, 54 + 6), str(watermark),
        font=A.font(A.F_REG, 19), fill=(236, 240, 248, 220))


def ua_theater(out=None, t=None, text="", channel="", watermark="",
              dur=0.0, sfx=None, **_):
    base, meta = _load()
    full = dur if dur > 0 else 4.0
    # ПОСТЕР (t=None) ПОКАЗЫВАЕТ УСТОЯВШЕЕСЯ СОСТОЯНИЕ, НЕ СТАРТ (24.11,
    # тот же баг и та же правка, что у kino_dok_text.dok_word/dok_title):
    # t=0 рисовал только кольцо радара без подписей/зоны/флага — поймано
    # живым тестом постера, не глазами на видео.
    tt = 1.0 if t is None else max(0.0, min(1.0, t / full))

    im = _kb(base, tt, 0.05).convert("RGBA")

    # подписи региона — всегда те же (Чёрное/Азовское море, Крым), не из текста
    for i, (x, y, s) in enumerate(meta["labels"]):
        k = max(0.0, min(1.0, (tt - i * .08) / .3))
        if k > 0:
            im = Image.alpha_composite(im, A.sea_label(
                _NATIVE, x, y, s, px=22, color=(236, 244, 255, int(220 * _ease(k)))))

    # точка эффекта — из текста сцены словарём мест; нет совпадения — Киев (tw из meta)
    found = PL.point(text) if text else None
    if found:
        fr_lon0, fr_lon1 = 26.0, 42.0   # та же рамка, что в prep_ukraine.py
        fr_lat0, fr_lat1 = 42.0, 52.0
        px = (found[0] - fr_lon0) / (fr_lon1 - fr_lon0) * _NATIVE[0]
        py = (1.0 - (found[1] - fr_lat0) / (fr_lat1 - fr_lat0)) * _NATIVE[1]
        point = (px, py)
    else:
        point = tuple(meta["tw"])

    im = Image.alpha_composite(im, A.radar(_NATIVE, point[0], point[1], 190,
                                           ang=-tt * math.tau))
    k = max(0.0, min(1.0, (tt - .15) / .4))
    if k > 0:
        im = Image.alpha_composite(im, A.threat_zone(
            _NATIVE, point[0], point[1], 70 + 120 * _ease(k)))

    # флаг на точке агрессора — нейтральный (без звёзд, П-прав. 24.11)
    cn = meta["cn"]
    k = max(0.0, min(1.0, (tt - .2) / .3))
    if k > 0:
        fc = tuple(tuple(c) if c else None for c in meta.get("flag_colors", ((222, 41, 41), None)))
        fs = meta.get("flag_stars", True)
        im = Image.alpha_composite(im, A.pin_flag(
            _NATIVE, cn[0], cn[1] + (1 - _ease(k)) * 22, colors=fc, stars=fs))

    im = im.resize((W, H), Image.LANCZOS)   # 1600×900 → 1920×1080, тот же кадр 16:9
    _знак(im, watermark)
    rgb = im.convert("RGB")
    if out:
        rgb.save(out, quality=92)
        return out
    return rgb


if __name__ == "__main__":
    import sys
    txt = " ".join(sys.argv[1:]) or "Удар по Одессе"
    im = ua_theater(t=1.8, text=txt, channel="ПЛАНЕТА", watermark="ПЛАНЕТА", dur=4.0)
    im.save("/tmp/kb_news_test.jpg", quality=92)
    print("готово: /tmp/kb_news_test.jpg, текст:", txt)
