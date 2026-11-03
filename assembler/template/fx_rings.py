#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кадры эффекта «круги на воде + луч радара» — прозрачные PNG для наложения.

    python3 fx_rings.py <папка> [--size 900] [--frames 180] [--seconds 6]

Эффект НЕЗАВИСИМ от кадра (прямое слово пользователя 03.11): «круги должны
быть независимым эффектом, они не должны цеплять и дёргать что-то ещё, они
сами должны работать — как круги на воде, как радар, крутится». Поэтому
рисуются отдельным слоем и накладываются поверх, а сам кадр не трогается
ничем: ни глитчем, ни сдвигом каналов (глитч он отверг: «эффект глича — это
не то, не к картинке должны применяться»).

Петля бесшовная: за N кадров круги проходят ровно один цикл, луч — полный
оборот, поэтому слой можно зациклить на любую длину сцены.
"""
import argparse
import math
import os

from PIL import Image, ImageDraw


def render(out_dir, size=900, frames=180):
    os.makedirs(out_dir, exist_ok=True)
    c = size // 2
    for i in range(frames):
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        t = i / frames
        # расходящиеся круги: четыре волны со сдвигом фазы, ровное затухание
        for k in range(4):
            p = (t + k / 4.0) % 1.0
            r = 0.078 * size + p * 0.40 * size
            a = int(230 * (1 - p) ** 1.5)
            if a <= 3:
                continue
            d.ellipse([c - r, c - r, c + r, c + r],
                      outline=(255, 255, 255, a),
                      width=max(2, int(5 * (1 - p)) + 1))
        # луч радара со шлейфом — один оборот за петлю
        ang = t * 360.0
        for j in range(26):
            a = int(120 * (1 - j / 26.0) ** 2)
            if a <= 2:
                continue
            th = math.radians(ang - j * 2.2)
            d.line([c, c, c + 0.478 * size * math.cos(th),
                    c + 0.478 * size * math.sin(th)],
                   fill=(255, 255, 255, a), width=2)
        im.save(os.path.join(out_dir, "r_%03d.png" % i))
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--frames", type=int, default=180)
    a = ap.parse_args()
    n = render(a.out_dir, a.size, a.frames)
    print("кадров эффекта: %d → %s (петля %.1f с при 30 к/с)"
          % (n, a.out_dir, n / 30.0))


if __name__ == "__main__":
    main()
