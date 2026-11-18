#!/usr/bin/env python3
"""Карточка-факт (concept card): размытое затемнённое НАСТОЯЩЕЕ фото фоном
(не выдуманная картинка), золотой эпиграф сверху, посимвольно "печатающийся"
текст по центру, курсивная подпись-источник снизу.

Для моментов, где у темы физически нет подходящего стокового кадра (редкий
научный эксперимент, историческая деталь) — и ТАКЖЕ как сознательный приём
для усиления авторитетности научпоп-ролика (user, 2026-10-06: "это даже
лучше работает, чем стоковое фото... придаёт видео элемент большего
авторитета"), не только как заглушка на крайний случай.

Usage:
  python3 make_concept_card.py <config.json> <out.mp4>

config.json:
{
  "background_photo": "images/scene_006.jpg",
  "eyebrow": "Полевой эксперимент",
  "text": "ЧУЧЕЛА В ПОЛНЫЙ РОСТ. РАЗНЫЙ ЦВЕТ ГРИВЫ.",
  "source": "Peyton West, Serengeti Lion Project · 2006",
  "seconds": 5.5
}
"""
import json
import os
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart_common import W, H, GOLD, WHITE, FONT_ITALIC


def ass_time(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    cs = round(s * 100)
    if cs >= 6000:
        cs -= 6000; m += 1
    return f"{h:01d}:{m:02d}:{cs//100:02d}.{cs%100:02d}"


def make(cfg, out_mp4):
    from chart_common import photo_canvas, eyebrow as draw_eyebrow
    seconds = float(cfg.get("seconds", 5.5))
    bg = photo_canvas(cfg["background_photo"])
    draw_eyebrow(bg, cfg["eyebrow"], y=300)
    bg_png = out_mp4.rsplit(".", 1)[0] + "_bg.png"
    bg.save(bg_png)

    text = cfg["text"]
    source = cfg.get("source", "")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 46)
    total_w = font.getlength(text)
    x = 960 - total_w / 2
    y = 520
    t0 = 0.5
    cps = 0.045
    hold_until = seconds - 0.3

    HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Char,Arial,46,&H00EDE8DE,&H000000FF,&H00141210,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Sub,Playfair Display,28,&H00C4A261,&H000000FF,&H00141210,&H00000000,0,-1,0,0,100,100,0,0,1,0,0,5,220,220,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [HEADER]
    blips = []  # побуквенный "бип" (2026-10-07) — сводится build_sfx_track.py
    t = t0
    for ch in text:
        w = font.getlength(ch)
        if ch != " ":
            lines.append(f"Dialogue: 0,{ass_time(t)},{ass_time(hold_until)},Char,,0,0,0,,"
                          f"{{\\an7\\pos({x:.0f},{y})\\fad(60,0)}}{ch}")
            blips.append(t)
        x += w
        t += cps

    if source:
        lines.append(f"Dialogue: 0,{ass_time(t+0.3)},{ass_time(hold_until)},Sub,,0,0,0,,"
                      f"{{\\an5\\pos(960,600)\\fad(300,200)}}{source}")

    ass_path = out_mp4.rsplit(".", 1)[0] + ".ass"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    subprocess.run([
        "nice", "-n", "19", "ffmpeg", "-y", "-loop", "1", "-i", bg_png, "-t", str(seconds),
        "-vf", f"fps=30,format=yuv420p,subtitles={ass_path}:fontsdir={fonts_dir}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        out_mp4
    ], check=True, capture_output=True)
    sfx_path = out_mp4.rsplit(".", 1)[0] + ".sfx.json"
    json.dump([{"at": bt, "role": "typewriter"} for bt in blips],
              open(sfx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("ok ->", out_mp4, f"({len(blips)} блипов -> {sfx_path})")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    make(cfg, sys.argv[2])
