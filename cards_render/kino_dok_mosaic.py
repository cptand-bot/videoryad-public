# -*- coding: utf-8 -*-
"""D3 ИЗ KINO-DOK, ПЕРЕНЕСЕНО ОДИН В ОДИН С ПАРАМЕТРИЗАЦИЕЙ (24.11.2026,
его слово: «D6 и D3, но не обязательными — желательными. Если не набирается
достаточно информации, их не выводим»).

Источник — фильм «Последний прогноз Киссинджера» (скилл `kino-dok`),
`~/kino-kissinger/engine/hook.py` (`s7_mosaic`/`panel_look`) и
`core.py` (`Vid`). Геометрия окон, тайминг открытия и зернистость
панелей — КАК В ОРИГИНАЛЕ. Единственная правка по смыслу: в фильме
четыре окна были жёстко прибиты к конкретным архивным файлам и
подписям («ЧТО ГОВОРИЛ»/«ЧТО СБЫЛОСЬ»/«ГДЕ ОШИБСЯ»/карта) — здесь оба
параметра (путь к клипу и подпись) приходят СНАРУЖИ, окон РОВНО
ЧЕТЫРЕ, других вариантов нет.

    card:dok_mosaic   D3   четыре окна с живым видео открываются по
                            очереди, в каждом своя подпись снизу

НЕ ОБЯЗАТЕЛЬНЫЙ вид (его слово 24.11): ставить ТОЛЬКО когда для сцены
реально нашлись ЧЕТЫРЕ РАЗНЫХ клипа по теме — иначе этот вид не
подходит, берётся обычная карточка. `card_put.py` поэтому требует
ровно 4 окна и падает `_fail`, если дано меньше — решение «не
набралось» видно сразу на этапе раскладки, а не тонет в рендере.

Возвращает RGB-кадр 1920×1080 (этого ждёт `style_cards.render_anim`).
"""
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080
SS = 2
SAFE_X, SAFE_Y = 96, 54
FPS = 25

BG = (9, 9, 11)
WHITE = (240, 238, 234)
RED = (204, 34, 30)
GREY = (150, 148, 144)

FONTS = os.path.join(HERE, "fonts")
F_HEAD = os.path.join(FONTS, "Oswald-Bold.ttf")

# ОКНА — ТА ЖЕ СЕТКА, ЧТО В ОРИГИНАЛЕ (hook.py:s7_mosaic): четыре
# прямоугольника 958×538 с зазором 4 px.
PANEL_W, PANEL_H = 958, 538
PANEL_POS = [(0, 0), (962, 0), (0, 542), (962, 542)]
STEP = 0.35       # интервал открытия окон, как «c_p[i]-c_segod» в оригинале
POP = 0.35        # длительность появления одного окна

_fc = {}


def font(size):
    size = max(4, int(round(size)))
    if size not in _fc:
        _fc[size] = ImageFont.truetype(F_HEAD, size)
    return _fc[size]


def clamp(x, a=0.0, b=1.0):
    return a if x < a else (b if x > b else x)


def seg(t, a, b):
    return clamp((t - a) / max(1e-6, b - a))


def out_cubic(t):
    t = clamp(t)
    return 1 - pow(1 - t, 3)


def layer():
    return Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))


def done(im):
    return im.resize((W, H), Image.LANCZOS)


def text_w(d, text, fnt, track=0.0):
    return sum(d.textlength(ch, font=fnt) for ch in text) + \
        track * fnt.size * max(0, len(text) - 1)


def tracked(d, x, y, text, fnt, fill, track=0.0, anchor="ls"):
    tw = text_w(d, text, fnt, track)
    if anchor[0] == "m":
        x -= tw / 2
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill, anchor="ls")
        x += d.textlength(ch, font=fnt) + track * fnt.size
    return tw


def _ffmpeg():
    return "ffmpeg"


def _placeholder(size, label="НЕТ КЛИПА"):
    w, h = size
    im = Image.new("RGB", (w, h), (28, 27, 30))
    d = ImageDraw.Draw(im)
    d.rectangle([2, 2, w - 3, h - 3], outline=GREY, width=2)
    f = font(int(min(w, h) * 0.07))
    d.text((w / 2, h / 2), label, font=f, fill=GREY, anchor="mm")
    return im


class _Vid:
    """Кадры клипа по времени сцены — ПОРТ core.py:Vid БЕЗ архивных путей:
    `path` — готовый абсолютный/относительный путь к файлу сцены, не имя
    в папке архива фильма. Читается последовательно, прыжок далеко назад
    или вперёд — переоткрытие (как в оригинале)."""

    def __init__(self, path, size=(PANEL_W, PANEL_H), fps=FPS):
        self.path = path
        self.size = size
        self.fps = fps
        self.ok = bool(path) and os.path.exists(path)
        self.p = None
        self.i = -1
        self.t_open = None
        self.last = None
        self.eof = False

    def _open(self, t):
        if self.p is not None:
            try:
                self.p.kill()
            except Exception:
                pass
        w, h = self.size
        vf = ("scale=%d:%d:force_original_aspect_ratio=increase,"
              "crop=%d:%d" % (w, h, w, h))
        self.p = subprocess.Popen(
            [_ffmpeg(), "-nostdin", "-loglevel", "error", "-ss", "%.3f" % max(0.0, t),
             "-i", self.path, "-vf", vf + ",fps=%d" % self.fps,
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 7)
        self.t_open = t
        self.i = -1
        self.eof = False

    def at(self, t):
        if not self.ok:
            return _placeholder(self.size)
        want = int(round((t - (self.t_open or 0.0)) * self.fps)) if self.t_open is not None else 0
        if self.p is None or want < self.i or want - self.i > self.fps * 3:
            self._open(t)
            want = 0
        w, h = self.size
        while self.i < want and not self.eof:
            raw = self.p.stdout.read(w * h * 3)
            if len(raw) < w * h * 3:
                self.eof = True
                break
            self.last = Image.frombytes("RGB", (w, h), raw)
            self.i += 1
        return self.last if self.last is not None else _placeholder(self.size)


_vids = {}


def _panel_look(fr, k=0.3):
    """окно мозаики: лёгкое обесцвечивание — панель читается архивно без
    полной плёночной обработки (та работает только на кадре целиком)."""
    g = fr.convert("L").convert("RGB")
    return Image.blend(fr, g, k)


def _red_line(k, x0, x1, y, w=5):
    if k <= 0:
        return None
    im = layer()
    d = ImageDraw.Draw(im)
    d.rectangle([x0 * SS, y * SS, (x0 + (x1 - x0) * out_cubic(k)) * SS, (y + w) * SS],
                fill=RED + (255,))
    return done(im)


def dok_mosaic(out=None, t=None, windows=None, channel="", watermark="",
              dur=0.0, sfx=None, **_):
    """D3. `windows` — РОВНО 4 пары (путь_к_клипу, подпись), в порядке
    открытия. Окна открываются по очереди каждые 0,35 с."""
    windows = list(windows or [])[:4]
    full = dur if dur > 0 else 6.0
    # ПОСТЕР (t=None) — все четыре окна уже открыты, как и у dok_word/
    # dok_title (гоча 24.11: t=0 даёт пустой/неполный постер).
    tt = (STEP * 3 + POP) if t is None else max(0.0, t)

    img = Image.new("RGB", (W, H), BG)
    lays = []
    for i in range(4):
        path, cap = (windows[i] if i < len(windows) else (None, ""))
        open_at = i * STEP
        k = seg(tt, open_at, open_at + POP)
        if k <= 0:
            continue
        if path not in _vids:
            _vids[path] = _Vid(path, size=(PANEL_W, PANEL_H))
        fr = _vids[path].at(max(0.0, tt - open_at))
        fr = _panel_look(fr)
        kk = out_cubic(k)
        sc = 0.9 + 0.1 * kk
        fw, fh = int(PANEL_W * sc), int(PANEL_H * sc)
        frs = fr.resize((fw, fh), Image.LANCZOS).convert("RGBA")
        frs.putalpha(int(255 * clamp(k * 2)))
        x, y = PANEL_POS[i]
        img.paste(frs, (x + (PANEL_W - fw) // 2, y + (PANEL_H - fh) // 2), frs)
        if cap:
            lay = layer()
            d = ImageDraw.Draw(lay)
            a = int(255 * clamp(k * 2))
            tracked(d, (x + PANEL_W / 2) * SS, (y + PANEL_H - 28) * SS,
                    cap.strip().upper(), font(30 * SS), WHITE + (a,), 0.04, "ms")
            lays.append(done(lay))
        lays.append(_red_line(seg(tt, open_at + 0.2, open_at + 0.7),
                               x + PANEL_W // 2 - 40, x + PANEL_W // 2 + 40,
                               y + PANEL_H - 44))

    out_img = img.convert("RGBA")
    for l in lays:
        if l is not None:
            out_img = Image.alpha_composite(out_img, l)
    rgb = out_img.convert("RGB")
    if out:
        rgb.save(out, quality=92)
        return out
    return rgb


if __name__ == "__main__":
    import sys
    demo = [(p, c) for p, c in
            [(sys.argv[i] if i < len(sys.argv) else "", "ОКНО %d" % (i - 0))
             for i in range(1, 5)]]
    im = dok_mosaic(t=1.5, windows=demo, dur=6.0)
    im.save("/tmp/dok_mosaic_test.jpg", quality=92)
    print("готово: /tmp/dok_mosaic_test.jpg")
