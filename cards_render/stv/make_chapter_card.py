#!/usr/bin/env python3
"""Полноэкранная карточка-глава: тёмный фон, золотой эпиграф ("ГЛАВА
ПЕРВАЯ"), тонкая линия, крупный курсивный serif-заголовок, золотой
подзаголовок (место/дата). Статичный кадр N секунд — вставляется отдельным
клипом между смысловыми главами ролика.

Usage: make_chapter_card.py <eyebrow> <title> <subtitle> <out.mp4> <seconds>
"""
import sys
import subprocess
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from chart_common import W, H, INK, GOLD, WHITE, FONT_ITALIC, FONT_REGULAR


def make(eyebrow, title, subtitle, out_mp4, seconds):
    seconds = float(seconds)
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)

    f_eyebrow = ImageFont.truetype(FONT_REGULAR, 34)
    f_title = ImageFont.truetype(FONT_ITALIC, 92)
    f_sub = ImageFont.truetype(FONT_REGULAR, 30)

    def centered(text, font, y, fill):
        bbox = d.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        d.text(((W - w) / 2, y), text, font=font, fill=fill)

    centered(eyebrow.upper(), f_eyebrow, H / 2 - 160, GOLD)
    line_w = 220
    d.line([(W / 2 - line_w / 2, H / 2 - 95), (W / 2 + line_w / 2, H / 2 - 95)], fill=GOLD, width=2)
    centered(title, f_title, H / 2 - 70, WHITE)
    centered(subtitle, f_sub, H / 2 + 60, GOLD)

    png_path = out_mp4.rsplit(".", 1)[0] + ".png"
    img.save(png_path)
    subprocess.run([
        "nice", "-n", "19", "ffmpeg", "-y", "-loop", "1", "-i", png_path, "-t", str(seconds),
        "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        out_mp4
    ], check=True, capture_output=True)
    print("ok ->", out_mp4)


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print(__doc__)
        raise SystemExit(1)
    make(*sys.argv[1:6])
