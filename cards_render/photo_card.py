#!/usr/bin/env python3
"""СЛАБОЕ ФОТО — МАЛЕНЬКИМ, А НЕ НА ВЕСЬ ЭКРАН.

Повод (user, 2026-10-21, зло): «мы делаем это голливудское качество, и в
конечном итоге такая срань вылазит посередине, вообще размытая, хрен
разберёшь, что там нарисовано… Если есть только в этом качестве — значит
надо ставить маленьким, картинка слева, а справа надписи какие-то».

Поэтому:
  photo_quality() — честная оценка снимка: разрешение и резкость;
  photo_card()    — композиция для слабого снимка: окно с фото слева,
                    заголовок и строки фактов справа. Фото не растягивается
                    на 1920 и потому не разваливается в кашу.

Порог ставится по тому, во сколько раз снимок придётся увеличить. Кадр
1920x1080: снимок шириной 1600 тянется в 1,2 раза — это ещё терпимо,
640 — в три раза, и получается именно то, на что ругается пользователь.
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "template"))
import style_cards as sc
import torn_split as ts

W, H = sc.W, sc.H

MIN_W = 1500          # ниже — на весь экран не ставим
MIN_SHARP = 90.0      # дисперсия Лапласа на приведённом кадре


def photo_quality(path):
    """Сколько в снимке пикселей и насколько он резкий."""
    im = Image.open(path).convert("L")
    w, h = im.size
    k = 900 / max(1, w)
    sm = im.resize((900, max(1, int(h * k))), Image.BILINEAR) if k < 1 else im
    a = np.asarray(sm, np.float32)
    lap = (a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] - 4 * a[1:-1, 1:-1])
    sharp = float(lap.var())
    upscale = W / max(1, w)
    ok = (w >= MIN_W) and (sharp >= MIN_SHARP)
    return {"w": w, "h": h, "sharp": round(sharp, 1), "upscale": round(upscale, 2),
            "full_screen_ok": ok,
            "why": "" if ok else
                   (f"ширина {w} px (нужно от {MIN_W})" if w < MIN_W else
                    f"резкость {sharp:.0f} (нужно от {MIN_SHARP:.0f})")}


def photo_card(out=None, *, photo="", kick="", title="", lines=(), source="",
               watermark="ДИПЛОМАТИЯ СИЛЫ", t=None, sfx=None, seconds=7.0,
               frame_w=0.40, photo_zoom=0.07, zoom_steps=3):
    """Фото слева в окне, надписи справа.

    Окно занимает frame_w ширины кадра, снимок вписывается в него БЕЗ
    увеличения выше его собственного разрешения — поэтому слабый кадр
    выглядит нормально: он просто маленький.

    ЗУМ ИДЁТ ТОЛЬКО ПО ФОТОГРАФИИ, внутри окна (user, 21.10: «зум для
    общей сцены не нужен, зачем его применять к тексту — зум можно
    применить к фотографии внутри»). Поэтому рендерить эту карточку надо
    с tail_zoom=0: движение здесь своё, а наезд на весь кадр вместе с
    подписями только мешает. Профиль плавный ступенчатый, общий с
    остальным арсеналом.
    """
    im = sc.canvas()
    tt = seconds if t is None else t

    fw = int(W * frame_w)
    fh = int(fw * 0.72)
    fx, fy = 150, (H - fh) // 2 + 20

    src = Image.open(photo).convert("RGB")
    # ВПИСЫВАЕМ, НЕ РАСТЯГИВАЯ: если снимок меньше окна, окно ужимается
    # под него, а не снимок раздувается под окно.
    # наезд внутри окна: кадрируем ИСХОДНИК плотнее, окно не меняется
    if photo_zoom and t is not None:
        z = ts._step_zoom(min(1.0, t / max(0.1, seconds)), photo_zoom, zoom_steps)
        cw, ch = int(src.width / z), int(src.height / z)
        ox, oy = (src.width - cw) // 2, (src.height - ch) // 2
        src = src.crop((ox, oy, ox + cw, oy + ch))

    k = min(fw / src.width, fh / src.height)
    if k > 1.0:
        fw, fh = int(src.width), int(src.height)
        fx, fy = 150, (H - fh) // 2 + 20
        k = 1.0
    pic = src.resize((max(1, int(src.width * k)), max(1, int(src.height * k))), Image.LANCZOS)
    pic = pic.crop(((pic.width - fw) // 2, (pic.height - fh) // 2,
                    (pic.width - fw) // 2 + fw, (pic.height - fh) // 2 + fh)) \
        if pic.width >= fw and pic.height >= fh else pic

    a_pic = 1.0 if t is None else max(0.0, min(1.0, (tt - 0.25) / 0.55))
    if a_pic > 0:
        # лёгкая тень окна
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).rectangle((fx + 8, fy + 12, fx + pic.width + 8, fy + pic.height + 12), fill=190)
        sh = sh.filter(ImageFilter.GaussianBlur(26))
        base = np.asarray(im, np.float32) * (1 - 0.55 * (np.asarray(sh, np.float32) / 255.0)[..., None])
        im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
        lay = Image.new("RGB", (W, H), (0, 0, 0))
        lay.paste(pic, (fx, fy))
        a = np.asarray(im, np.float32) * (1 - a_pic) + np.asarray(
            Image.composite(lay, im, Image.new("L", (W, H), 0).point(lambda v: v)), np.float32) * 0
        im.paste(Image.fromarray(np.clip(np.asarray(pic, np.float32) * a_pic, 0, 255).astype(np.uint8)),
                 (fx, fy))
        d = ImageDraw.Draw(im, "RGBA")
        d.rectangle((fx - 2, fy - 2, fx + pic.width + 1, fy + pic.height + 1),
                    outline=(120, 122, 132, int(230 * a_pic)), width=2)

    # ---- правая колонка: заголовок и строки ------------------------------
    tx = fx + pic.width + 92
    d = ImageDraw.Draw(im, "RGBA")
    # КИКЕР РИСУЕМ САМИ, В ПРАВОЙ КОЛОНКЕ. sc.kicker ставит строку от левого
    # поля кадра — а слева тут стоит фото, и подпись легла прямо на снимок
    # (поймано 21.10 на первой пробе).
    a_k, _ = sc._rv(t, 0.12)
    if a_k > 0 and kick:
        fk = sc._f(sc.F_HEAD, 26)
        d.ellipse((tx, fy + 14, tx + 14, fy + 28), fill=sc.RED + (int(255 * a_k),))
        d.text((tx + 28, fy + 8), " ".join(kick.upper()), font=fk,
               fill=sc.GOLD + (int(240 * a_k),))

    y = fy + 64
    a_t, _ = sc._rv(t, 0.22)
    if a_t > 0 and title:
        f = sc._f(sc.F_HEAD, 54)
        for ln in _wrap(title, f, W - tx - 120):
            d.text((tx, y), ln, font=f, fill=sc.WHITE + (int(255 * a_t),))
            y += 64
        y += 14

    for i, ln in enumerate(lines):
        a_l, _ = sc._rv(t, 0.42 + i * 0.22)
        if a_l <= 0:
            break
        f = sc._f(sc.F_HEAD, 34)
        d.rectangle((tx, y + 12, tx + 6, y + 36), fill=sc.RED + (int(255 * a_l),))
        for j, part in enumerate(_wrap(ln, f, W - tx - 140)):
            d.text((tx + 24, y), part, font=f, fill=(214, 214, 218, int(235 * a_l)))
            y += 44
        y += 12

    sc.footer(ImageDraw.Draw(im, "RGBA"), source, watermark=watermark)
    if out:
        im.save(out, quality=94)
    return im


def _wrap(text, font, maxw):
    words, out, cur = text.split(" "), [], ""
    for w_ in words:
        probe = (cur + " " + w_).strip()
        if font.getlength(probe) > maxw and cur:
            out.append(cur); cur = w_
        else:
            cur = probe
    out.append(cur)
    return out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        q = photo_quality(p)
        mark = "на весь экран МОЖНО" if q["full_screen_ok"] else "ТОЛЬКО маленьким: " + q["why"]
        print(f'{os.path.basename(p):40s} {q["w"]}x{q["h"]}  резкость {q["sharp"]:7.1f}  '
              f'увеличение x{q["upscale"]}  → {mark}')
