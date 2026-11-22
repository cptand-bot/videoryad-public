#!/usr/bin/env python3
"""Анимированный слайдер-диапазон: маркер едет вдоль шкалы (ease-out) и
останавливается на итоговом значении, число при остановке пульсирует
(больше->меньше, 2026-10-06 user: "цифра тридцать пять становится больше
потом опять меньше"). Опциональная круглая фото-врезка в углу (тема графика).

Для пересмотренных/уточнённых оценок, диапазонов с большой неопределённостью
("от X до Y, по уточнённым данным ~Z") — визуализирует именно то, что текст
говорит словами, не выдумывая точность, которой нет в источнике.

Usage: python3 build_chart_slider.py <config.json> <out.mp4>

config.json:
{
  "title": "Пересмотренная оценка · 2009",
  "min": 0, "max": 140,
  "low": 28, "high": 135,
  "range_label": "ПЕРВОНАЧАЛЬНАЯ ОЦЕНКА (ДИАПАЗОН)",
  "marker_value": 35,
  "marker_display": "≈35",
  "caption": "по изотопному анализу шерсти и костного коллагена",
  "photo": {"path": "images/scene_024.jpg", "label": "львы Цаво"},
  "seconds": 5.0
}
"""
import json
import math
import os
import sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart_common import (W, H, GOLD, TEAL, GREY, data_canvas, eyebrow, circle_photo,
                           glow_rect, glow_point, ease_out_cubic, render_video, FONT_ITALIC)

F_SMALL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
F_CAP = ImageFont.truetype(FONT_ITALIC, 28)
_BIG_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

BAR_Y = 560
X0, X1 = 460, 1460
SLIDE_START, SLIDE_DUR = 0.5, 1.1
PULSE_START, PULSE_DUR = 1.7, 1.3


def make(cfg, out_mp4):
    vmin, vmax = cfg.get("min", 0), cfg.get("max", 100)
    low, high = cfg["low"], cfg["high"]
    marker_value = cfg["marker_value"]
    marker_display = cfg.get("marker_display", str(marker_value))
    caption_at = PULSE_START + PULSE_DUR + 0.3
    seconds = float(cfg.get("seconds", caption_at + 1.9))

    def xpos(v):
        return X0 + (X1 - X0) * (v - vmin) / (vmax - vmin)

    def draw(t):
        im = data_canvas()
        eyebrow(im, cfg["title"])

        photo_cfg = cfg.get("photo")
        if photo_cfg:
            circ = circle_photo(photo_cfg["path"], 190, GOLD, border_w=8)
            im.paste(circ, (W - circ.width - 90, 150), circ)
            d = ImageDraw.Draw(im)
            if photo_cfg.get("label"):
                bbox = d.textbbox((0, 0), photo_cfg["label"], font=F_SMALL)
                cw2 = bbox[2] - bbox[0]
                d.text((W - 90 - circ.width/2 - cw2/2, 150 + circ.height + 10),
                       photo_cfg["label"], font=F_SMALL, fill=GREY)

        d = ImageDraw.Draw(im)
        d.line([(X0, BAR_Y), (X1, BAR_Y)], fill=(70, 78, 90), width=10)
        xa, xb = xpos(low), xpos(high)
        glow_rect(im, (xa, BAR_Y - 5, xb, BAR_Y + 5), GREY, alpha=140, blur=0, pad=0)
        d = ImageDraw.Draw(im)
        for v, label in [(low, str(low)), (high, str(high))]:
            x = xpos(v)
            d.line([(x, BAR_Y - 22), (x, BAR_Y + 22)], fill=GREY, width=3)
            bbox = d.textbbox((0, 0), label, font=F_SMALL)
            lw = bbox[2] - bbox[0]
            d.text((x - lw/2, BAR_Y + 34), label, font=F_SMALL, fill=GREY)
        if cfg.get("range_label"):
            d.text((X0, BAR_Y - 70), cfg["range_label"], font=F_SMALL, fill=GREY)

        slide_t = ease_out_cubic((t - SLIDE_START) / SLIDE_DUR)
        if slide_t > 0:
            xr = xa + (xpos(marker_value) - xa) * slide_t
            glow_point(im, (xr, BAR_Y), TEAL, r=12, glow=40)
            d = ImageDraw.Draw(im)
            d.line([(xr, BAR_Y), (xr, BAR_Y - 140)], fill=TEAL, width=2)

            pulse_t = (t - PULSE_START) / PULSE_DUR
            if pulse_t < 0:
                scale = 1.0 if slide_t >= 1 else 0.0
            else:
                env = max(0.0, 1 - pulse_t) if pulse_t <= 1 else 0.0
                scale = 1.0 + 0.22 * math.sin(pulse_t * 3.0 * math.pi) * env
            if slide_t >= 0.98 or pulse_t >= 0:
                fsize = max(10, int(86 * max(scale, 0.05)))
                f_big_dyn = ImageFont.truetype(_BIG_PATH, fsize)
                bbox = d.textbbox((0, 0), marker_display, font=f_big_dyn)
                bw, bh_ = bbox[2]-bbox[0], bbox[3]-bbox[1]
                d.text((xr - bw/2, BAR_Y - 180 - bh_), marker_display, font=f_big_dyn, fill=TEAL)

        if cfg.get("caption"):
            cap_t = ease_out_cubic((t - caption_at) / 0.6)
            if cap_t > 0:
                layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
                ld = ImageDraw.Draw(layer)
                bbox = ld.textbbox((0, 0), cfg["caption"], font=F_CAP)
                cw = bbox[2] - bbox[0]
                ld.text(((W - cw) / 2, BAR_Y + 110), cfg["caption"], font=F_CAP, fill=GOLD + (int(255*cap_t),))
                im.paste(Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB"), (0, 0))
        return im

    frame_dir = out_mp4.rsplit(".", 1)[0] + "_frames"
    render_video(frame_dir, out_mp4, int(seconds * 30), draw)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    make(cfg, sys.argv[2])
