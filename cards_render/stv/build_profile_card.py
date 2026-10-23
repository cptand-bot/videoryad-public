#!/usr/bin/env python3
"""HUD-карточка-досье: по образцу "карточка бойца" (референс пользователя,
2026-10-06) — крупное фото по центру на светящемся кольце-подиуме,
заголовок+подзаголовок справа сверху, два поля-категории сверху, столбик
статистики слева, 1-2 угловые фото-вставки в скобках-рамках снизу. Поля
проявляются по очереди (HUD boot-up), не все разом.

Для "персональных" карточек реальных подозреваемых/объектов исследования
(например, лев-людоед Цаво с его статистикой), не для абстрактных тем —
там лучше build_chart_bars.py / build_chart_slider.py.

Usage: python3 build_profile_card.py <config.json> <out.mp4>

config.json:
{
  "title": "ЛЕВ-ЛЮДОЕД №1",
  "subtitle": "ЦАВО, КЕНИЯ · 1898",
  "main_photo": "images/scene_025.jpg",
  "top_fields": [
    {"label": "КАТЕГОРИЯ", "value": "ВЗРОСЛЫЙ САМЕЦ"},
    {"label": "ГРИВА", "value": "ОТСУТСТВУЕТ"}
  ],
  "stats": [
    {"label": "ЖЕРТВ ПРИПИСАНО", "value": "28–135"},
    {"label": "АКТИВНОСТЬ", "value": "9 МЕСЯЦЕВ"},
    {"label": "ЗАСТРЕЛЕН", "value": "ДЕК. 1898"},
    {"label": "ХРАНИТСЯ", "value": "FIELD MUSEUM"}
  ],
  "insets": [
    {"photo": "images/scene_024.jpg", "label": "ЧУЧЕЛО"},
    {"photo": "images/scene_022.jpg", "label": "ПАТТЕРСОН"}
  ],
  "seconds": 6.0
}
"""
import json
import os
import sys
from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart_common import (W, H, GOLD, TEAL, WHITE, GREY, data_canvas, circle_photo,
                           glow_point, ease_out_cubic, render_video, FONT_ITALIC, FONT_REGULAR)

F_TITLE = ImageFont.truetype(FONT_ITALIC, 56)
F_SUB = ImageFont.truetype(FONT_REGULAR, 28)
F_FIELD_L = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
F_FIELD_V = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
F_STAT_L = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
F_STAT_V = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
F_INSET = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)

MAIN_SZ = 460
MAIN_CX, MAIN_CY = 960, 560
RING_RY = 70

_DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FIELD_V_SIZES = (28, 25, 22, 20)   # кегль значения, от желаемого к аварийному
_FIELD_GAP = 60                     # минимальный зазор между полями
_FIELD_X0 = 100


def _wrap_two(text, font, maxw):
    """Ломает значение по пробелу на две строки так, чтобы длинная половина
    была как можно короче. Без пробела не ломает — вернёт одну строку."""
    if font.getlength(text) <= maxw or " " not in text:
        return [text]
    words = text.split(" ")
    best, best_w = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        w = max(font.getlength(a), font.getlength(b))
        if best_w is None or w < best_w:
            best, best_w = [a, b], w
    return best


def _layout_top_fields(top_fields, x_limit):
    """2026-10-17: два верхних поля налезали друг на друга при длинных
    значениях — шаг был прибит гвоздём (fx += 420) независимо от текста.
    Теперь поля меряются и раскладываются подряд: сперва пробуем штатный
    кегль в одну строку, не влезло — ломаем значение на две строки, всё
    ещё не влезло — опускаем кегль. x_limit это левый край заголовка
    (он прижат вправо и стоит в той же полосе по высоте)."""
    if not top_fields:
        return []
    n = len(top_fields)
    avail = x_limit - _FIELD_X0
    per = (avail - _FIELD_GAP * (n - 1)) / max(n, 1)
    chosen = None
    for size in _FIELD_V_SIZES:
        fv = ImageFont.truetype(_DEJAVU_BOLD, size)
        blocks = []
        for fld in top_fields:
            lines = _wrap_two(fld.get("value", ""), fv, per)
            w = max([F_FIELD_L.getlength(fld.get("label", ""))]
                    + [fv.getlength(x) for x in lines])
            blocks.append({"label": fld.get("label", ""), "lines": lines,
                           "w": w, "font": fv, "size": size})
        total = sum(b["w"] for b in blocks) + _FIELD_GAP * (n - 1)
        chosen = blocks
        if total <= avail:
            break
    x = _FIELD_X0
    for b in chosen:
        b["x"] = x
        x += b["w"] + _FIELD_GAP
    return chosen


def corner_brackets(d, box, color, w=3, ln=22):
    x0, y0, x1, y1 = box
    for (cx, cy, dx, dy) in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
        d.line([(cx, cy), (cx + ln * dx, cy)], fill=color, width=w)
        d.line([(cx, cy), (cx, cy + ln * dy)], fill=color, width=w)


def fade_in(im, t, start, dur=0.35):
    return ease_out_cubic((t - start) / dur)


def make(cfg, out_mp4):
    seconds = float(cfg.get("seconds", 6.0))
    top_fields = cfg.get("top_fields", [])
    stats = cfg.get("stats", [])
    insets = cfg.get("insets", [])

    # ширина заголовка нужна до отрисовки: он прижат к правому краю и стоит
    # в той же горизонтальной полосе, что верхние поля
    _probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    _tb = _probe.textbbox((0, 0), cfg.get("title", ""), font=F_TITLE)
    _sb = _probe.textbbox((0, 0), cfg.get("subtitle", ""), font=F_SUB)
    title_w = max(_tb[2] - _tb[0], _sb[2] - _sb[0])
    field_layout = _layout_top_fields(top_fields, 1860 - title_w - _FIELD_GAP)

    T_PHOTO = 0.2
    T_TITLE = 0.5
    T_FIELDS = 0.9
    T_STATS = 1.3
    T_INSETS = 2.0

    def draw(t):
        im = data_canvas()
        d = ImageDraw.Draw(im)

        # заголовок справа сверху
        ta = fade_in(im, t, T_TITLE)
        if ta > 0:
            layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            a = int(255 * ta)
            bbox = ld.textbbox((0, 0), cfg["title"], font=F_TITLE)
            tw = bbox[2] - bbox[0]
            ld.text((1860 - tw, 90), cfg["title"], font=F_TITLE, fill=WHITE + (a,))
            bbox = ld.textbbox((0, 0), cfg.get("subtitle", ""), font=F_SUB)
            sw = bbox[2] - bbox[0]
            ld.text((1860 - sw, 158), cfg.get("subtitle", ""), font=F_SUB, fill=GOLD + (a,))
            im.paste(Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB"), (0, 0))
            d = ImageDraw.Draw(im)

        # два поля сверху-слева — проявляются по очереди (HUD boot-up), не разом
        for i, b in enumerate(field_layout):
            if fade_in(im, t, T_FIELDS + i * 0.12) > 0:
                d.text((b["x"], 95), b["label"], font=F_FIELD_L, fill=GREY)
                vy = 120
                for ln in b["lines"]:
                    d.text((b["x"], vy), ln, font=b["font"], fill=WHITE)
                    vy += b["size"] + 4

        # кольцо-подиум + фото
        pa = fade_in(im, t, T_PHOTO, dur=0.5)
        if pa > 0:
            ring_w = int(340 * pa)
            glow_point(im, (MAIN_CX, MAIN_CY + MAIN_SZ//2 - 10), TEAL, r=4, glow=int(60*pa), alpha=50)
            d = ImageDraw.Draw(im)
            d.ellipse((MAIN_CX - ring_w, MAIN_CY + MAIN_SZ//2 - 10 - RING_RY//2,
                       MAIN_CX + ring_w, MAIN_CY + MAIN_SZ//2 - 10 + RING_RY//2),
                      outline=TEAL, width=2)
            sz = int(MAIN_SZ * pa)
            if sz > 10:
                circ = circle_photo(cfg["main_photo"], sz, GOLD, border_w=6)
                im.paste(circ, (MAIN_CX - circ.width//2, MAIN_CY - circ.height//2), circ)

        # статистика слева столбиком — тоже по очереди
        sy = 420
        for i, st in enumerate(stats):
            if fade_in(im, t, T_STATS + i * 0.12) > 0:
                d.text((100, sy), st["label"], font=F_STAT_L, fill=GREY)
                d.text((100, sy + 26), st["value"], font=F_STAT_V, fill=TEAL)
            sy += 90

        # инсет-фото снизу — тоже по очереди
        if insets:
            isz = 190
            n = len(insets)
            total_w = n * isz + (n - 1) * 30
            ix0 = W - total_w - 100
            for i, ins in enumerate(insets):
                if fade_in(im, t, T_INSETS + i * 0.15) <= 0:
                    continue
                bx = ix0 + i * (isz + 30)
                by = H - isz - 90
                im2 = Image.open(ins["photo"]).convert("RGB")
                im2 = ImageOps.fit(im2, (isz, isz), Image.LANCZOS)
                im.paste(im2, (bx, by))
                d = ImageDraw.Draw(im)
                corner_brackets(d, (bx, by, bx + isz, by + isz), TEAL)
                if ins.get("label"):
                    bbox = d.textbbox((0, 0), ins["label"], font=F_INSET)
                    lw = bbox[2] - bbox[0]
                    d.text((bx + isz/2 - lw/2, by + isz + 8), ins["label"], font=F_INSET, fill=GREY)

        return im

    frame_dir = out_mp4.rsplit(".", 1)[0] + "_frames"
    render_video(frame_dir, out_mp4, int(seconds * 30), draw)

    # sfx-сайдкар (2026-10-07): появление фото = "затвор камеры", заголовок =
    # whoosh, каждое поле/стат/инсет = свой блип — сводится build_sfx_track.py
    sfx = [{"at": T_PHOTO, "role": "card"}, {"at": T_TITLE, "role": "accent"}]
    sfx += [{"at": T_FIELDS + i * 0.12, "role": "typewriter"} for i in range(len(top_fields))]
    sfx += [{"at": T_STATS + i * 0.12, "role": "typewriter"} for i in range(len(stats))]
    sfx += [{"at": T_INSETS + i * 0.15, "role": "label"} for i in range(len(insets))]
    sfx_path = out_mp4.rsplit(".", 1)[0] + ".sfx.json"
    json.dump(sfx, open(sfx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(sfx)} sfx-событий -> {sfx_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    make(cfg, sys.argv[2])
