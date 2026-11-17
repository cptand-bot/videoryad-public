#!/usr/bin/env python3
"""Анимированный столбчатый график с фото-врезками: столбцы растут по
очереди (ease-out), над каждым "выпрыгивает" (overshoot-поп) круглое фото —
например, лев с соответствующим окрасом гривы. Золотая цитата-вывод в конце.

Для научпоп-документалок там, где есть реальное количественное сравнение
(2-5 категорий) — подкреплённое фото, не абстрактные цифры с потолка.
Выведено 2026-10-06 на тесте про гриву льва (user: "побогаче надо, побогаче",
понравилось использовать РЕАЛЬНЫЕ фото под каждый столбец, не просто цвет).

Usage: python3 build_chart_bars.py <config.json> <out.mp4>

config.json:
{
  "title": "Тестостерон и окрас гривы",
  "caption": "чем темнее грива — тем выше уровень тестостерона",
  "seconds": 5.5,
  "bars": [
    {"label": "СВЕТЛАЯ", "color": "D4B896", "value": 0.32, "photo": "trial/mane_light.jpg"},
    {"label": "СРЕДНЯЯ", "color": "9C6B3E", "value": 0.62, "photo": "trial/mane_medium.jpg"},
    {"label": "ТЁМНАЯ",  "color": "4A2F1E", "value": 0.93, "photo": "trial/mane_dark.jpg"}
  ]
}

"value" — относительная высота столбца (0..1), ИЛЛЮСТРАТИВНАЯ, не выдавай
её за точную статистику, если точных чисел исследования нет под рукой —
подпиши источник в caption/отдельным accent, если они есть.
"""
import json
import os
import sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart_common import (W, H, WHITE, GOLD, data_canvas, eyebrow, circle_photo,
                           glow_rect, ease_out_cubic, pop_scale, render_video, hexcolor, FONT_ITALIC)

F_MED = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
# кегли подписи столбца: 34 штатный, 30 и 26 — для длинных подписей, которые
# не влезают даже в две строки (см. перенос ниже, правка 06.11)
_LABEL_FONTS = {_s: ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", _s)
    for _s in (34, 30, 26)}


def _wrap_two(d, text, font, room):
    """Подпись столбца словами в строки шириной не больше `room`."""
    words, lines, cur = str(text).split(), [], ""
    for w_ in words:
        cand = (cur + " " + w_).strip()
        if d.textlength(cand, font=font) <= room or not cur:
            cur = cand
        else:
            lines.append(cur); cur = w_
    if cur:
        lines.append(cur)
    return lines


def _fits_two(d, text, font, room):
    ls = _wrap_two(d, text, font, room)
    return len(ls) <= 2 and all(d.textlength(l_, font=font) <= room for l_ in ls)
F_CAP = ImageFont.truetype(FONT_ITALIC, 28)

BASE_Y = 820
TOP_Y = 420
BAR_W = 220
GAP = 140
CIRCLE_SZ = 128
CIRCLE_CY = 255
BAR_DUR = 0.7
ICON_DELAY = 0.55
ICON_DUR = 0.35
GAP_BETWEEN_BARS = 1.0
FIRST_BAR_AT = 0.4


def make(cfg, out_mp4):
    bars = cfg["bars"]
    n = len(bars)
    total_w = n * BAR_W + (n - 1) * GAP
    x0 = (W - total_w) / 2
    bar_start = [FIRST_BAR_AT + i * GAP_BETWEEN_BARS for i in range(n)]
    caption_at = bar_start[-1] + BAR_DUR + 0.5
    seconds = float(cfg.get("seconds", caption_at + 1.9))

    def draw(t):
        im = data_canvas()
        eyebrow(im, cfg["title"])

        for i, b in enumerate(bars):
            color = hexcolor(b["color"])
            x = x0 + i * (BAR_W + GAP)
            cx = x + BAR_W / 2
            bar_t = ease_out_cubic((t - bar_start[i]) / BAR_DUR)
            if bar_t <= 0:
                continue
            bh = (BASE_Y - TOP_Y) * b["value"] * bar_t
            y1 = BASE_Y - bh
            glow_rect(im, (x, y1, x + BAR_W, BASE_Y), color)
            d = ImageDraw.Draw(im)
            d.rectangle((x, y1, x + BAR_W, BASE_Y), fill=color)
            d.rectangle((x, y1, x + BAR_W, BASE_Y), outline=(255, 255, 255), width=1)
            # ДЛИННАЯ ПОДПИСЬ ПЕРЕНОСИТСЯ НА ДВЕ СТРОКИ (06.11, прямое слово
            # пользователя по сцене 60 ролика про Абу-Даби: «там надпись,
            # буквы наезжают друг на друга. Если большая надпись, как-то
            # делайте в две строки»). Подпись рисовалась ОДНОЙ строкой без
            # ограничения ширины: «США: ПОЛНЫЙ КОНТУР ПОДДЕРЖКИ» при кегле 34
            # занимает ~560 px, а места под столбцом 220 + половина промежутка,
            # то есть ~360 — соседние подписи налезали друг на друга.
            # Порядок: сначала перенос по словам, потом, если и так не влезло,
            # уменьшаем кегль до 26.
            room = BAR_W + GAP * 0.72
            # КЕГЛЬ ОДИН НА ВСЕ ПОДПИСИ (иначе соседние столбцы подписаны
            # разным размером — видно сразу): подбираем по САМОЙ длинной.
            for _fs in (34, 30, 26):
                _f = _LABEL_FONTS[_fs]
                if all(_fits_two(d, str(bb_.get("label", "")), _f, room)
                       for bb_ in cfg["bars"]):
                    break
            lines = _wrap_two(d, b["label"], _f, room)
            # больше двух строк не рисуем: третья уходит под нижний край
            if len(lines) > 2:
                lines = [lines[0], " ".join(lines[1:])]
            _y = BASE_Y + 24
            for l_ in lines:
                _lw = d.textlength(l_, font=_f)
                d.text((x + BAR_W/2 - _lw/2, _y), l_, font=_f, fill=WHITE)
                _y += _fs + 6

            icon_t = (t - bar_start[i] - ICON_DELAY) / ICON_DUR
            if icon_t > 0 and b.get("photo"):
                s = pop_scale(icon_t)
                if s > 0.02:
                    d.line([(cx, CIRCLE_CY + CIRCLE_SZ/2 + 6), (cx, y1)], fill=color, width=2)
                    sz = max(2, int(CIRCLE_SZ * s))
                    circ = circle_photo(b["photo"], sz, color, border_w=max(2, int(7 * s)))
                    im.paste(circ, (int(cx - circ.width/2), int(CIRCLE_CY - circ.height/2)), circ)

        d = ImageDraw.Draw(im)
        d.line([(x0 - 60, BASE_Y), (x0 + total_w + 60, BASE_Y)], fill=(90, 98, 110), width=2)

        if cfg.get("caption"):
            cap_t = ease_out_cubic((t - caption_at) / 0.6)
            if cap_t > 0:
                layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
                ld = ImageDraw.Draw(layer)
                bbox = ld.textbbox((0, 0), cfg["caption"], font=F_CAP)
                cw = bbox[2] - bbox[0]
                ld.text(((W - cw) / 2, BASE_Y + 90), cfg["caption"], font=F_CAP, fill=GOLD + (int(255 * cap_t),))
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
