#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""КНОПКА «ПОДПИШИСЬ», ВТОРОЙ ВИД — замысловатый, для другого канала.

    python3 fx_subscribe2.py --frames <папка>
    python3 fx_subscribe2.py <клип.mp4> <куда.mp4> [--at 0.3] [--corner right]

Его заказ 05.11, после приёмки первой кнопки: «сделай ещё какой-то другой
вариант кнопки, более замысловатый. Это будем раскатывать на другой канал».

ПОЧЕМУ ОТДЕЛЬНЫЙ ФАЙЛ, А НЕ КЛЮЧ В ПЕРВОМ: первая кнопка ПРИНЯТА и
приравнена к сданному. Любая правка её файла — риск задеть принятое; здесь
не задето ни одной строки.

ЧЕМ ОТЛИЧАЕТСЯ (вариант меняет НАБОР, а не цвет):
  * пластина строгая, со скруглением 20, а не «пилюля»;
  * слева фирменная черта-акцент, как в наших надписях;
  * по периметру бежит световая искра — она и ведёт взгляд к кнопке;
  * нажатие ПЕРЕВОРАЧИВАЕТ пластину вокруг вертикальной оси: тёмная грань →
    красная → тёмная (вместо простой смены заливки);
  * между нажатиями по пластине проходит блик;
  * надпись набрана в разрядку, как заголовок, а не как ярлык.

ГРАНИЦЫ КАНАЛА те же: глитча и тряски нет (двигаются только искра, блик и
курсор), появление и уход мгновенные, типографика наша, углы только верхние.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile

FPS = 30
TOTAL_SEC = 3.6

CW, CH = 580, 240
BTN_W, BTN_H = 440, 104
BTN_X, BTN_Y = 10, 12
RADIUS = 20

DARK = (18, 20, 24)
RED = (214, 25, 22)
ACCENT = (6, 199, 199)          # фирменная бирюза канала
WHITE = (255, 255, 255)

TAPS = (0.55, 1.35, 2.15)       # когда курсор дожимает
FLIP = 0.26                     # длительность переворота
TAP_DOWN = 0.09
T_IN = 0.46
T_LEAVE = 3.10

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_FONTS = ["Oswald-Bold.ttf", "RobotoCondensed-Bold.ttf", "Montserrat-Bold.ttf"]
_SYS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
TEXT = "ПОДПИШИСЬ"


def _font(size):
    from PIL import ImageFont
    for fn in _FONTS:
        fp = os.path.join(_FONT_DIR, fn)
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    for fp in _SYS:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _text_w(f, text, track):
    try:
        w = sum(f.getlength(c) for c in text)
    except AttributeError:
        w = sum(f.getsize(c)[0] for c in text)
    return w + track * max(0, len(text) - 1)


def _fit(text, box_w, track, start=46, low=24):
    """Кегль подбираем ИЗМЕРЕНИЕМ, с учётом разрядки."""
    size = start
    while size > low:
        f = _font(size)
        if _text_w(f, text, track) <= box_w:
            return f
        size -= 2
    return _font(low)


def _draw_tracked(d, xy, text, f, fill, track):
    """Надпись в разрядку: PIL так не умеет, ставим букву за буквой."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill, anchor="lm")
        try:
            x += f.getlength(ch) + track
        except AttributeError:
            x += f.getsize(ch)[0] + track


def _ring_path(x0, y0, x1, y1, r, steps=200):
    """Точки по периметру скруглённого прямоугольника — дорожка для искры."""
    pts = []
    w, h = x1 - x0, y1 - y0
    straight_w, straight_h = max(1.0, w - 2 * r), max(1.0, h - 2 * r)
    arc = math.pi * r / 2.0
    total = 2 * straight_w + 2 * straight_h + 4 * arc
    for i in range(steps):
        d = total * i / float(steps)
        if d < straight_w:                       # верх
            pts.append((x0 + r + d, y0))
            continue
        d -= straight_w
        if d < arc:                              # угол правый верхний
            a = (d / arc) * (math.pi / 2)
            pts.append((x1 - r + r * math.sin(a), y0 + r - r * math.cos(a)))
            continue
        d -= arc
        if d < straight_h:                       # право
            pts.append((x1, y0 + r + d))
            continue
        d -= straight_h
        if d < arc:
            a = (d / arc) * (math.pi / 2)
            pts.append((x1 - r + r * math.cos(a), y1 - r + r * math.sin(a)))
            continue
        d -= arc
        if d < straight_w:                       # низ
            pts.append((x1 - r - d, y1))
            continue
        d -= straight_w
        if d < arc:
            a = (d / arc) * (math.pi / 2)
            pts.append((x0 + r - r * math.sin(a), y1 - r + r * math.cos(a)))
            continue
        d -= arc
        if d < straight_h:                       # лево
            pts.append((x0, y1 - r - d))
            continue
        d -= straight_h
        a = (min(d, arc) / arc) * (math.pi / 2)
        pts.append((x0 + r - r * math.cos(a), y0 + r - r * math.sin(a)))
    return pts


def _ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _press(t):
    for tap in TAPS:
        if abs(t - tap) <= TAP_DOWN:
            return 1.0 - abs(t - tap) / TAP_DOWN
    return 0.0


def _flip_state(t):
    """Угол переворота (0…pi) и какая грань видна."""
    ang = 0.0
    face = 0                       # 0 — тёмная, 1 — красная
    for i, tap in enumerate(TAPS):
        if t >= tap + FLIP:
            face = (i + 1) % 2
        elif t >= tap:
            q = (t - tap) / FLIP
            ang = math.pi * _ease(q)
            face = i % 2 if q < 0.5 else (i + 1) % 2
            return ang, face
    return ang, face


def _face(face, w, h, glare):
    """Грань пластины: заливка, черта-акцент, надпись, блик."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bg = RED if face else DARK
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=RADIUS, fill=bg)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=RADIUS,
                        outline=(255, 255, 255, 60), width=2)
    # фирменная черта слева — как в наших надписях
    d.rounded_rectangle([18, h * 0.24, 27, h * 0.76], radius=4,
                        fill=ACCENT if not face else (255, 255, 255, 230))
    track = 4
    f = _fit(TEXT, w - 96, track)
    tw = _text_w(f, TEXT, track)
    _draw_tracked(d, (38 + (w - 38 - tw) / 2.0, h / 2.0), TEXT, f, WHITE, track)
    # блик: светлая полоса идёт поперёк пластины
    if 0.0 < glare < 1.0:
        gx = -w * 0.4 + (w * 1.8) * glare
        gl = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gl)
        gd.polygon([(gx, h), (gx + w * 0.16, 0),
                    (gx + w * 0.28, 0), (gx + w * 0.12, h)],
                   fill=(255, 255, 255, 46))
        mask = Image.new("L", (int(w), int(h)), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1],
                                               radius=RADIUS, fill=255)
        im.paste(Image.alpha_composite(im, gl), (0, 0), mask)
    return im


def frame(t):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    press = _press(t)
    ang, face = _flip_state(t)
    k = 1.0 - 0.03 * press
    bw, bh = BTN_W * k, BTN_H * k
    bx = BTN_X + (BTN_W - bw) / 2.0
    by = BTN_Y + (BTN_H - bh) / 2.0

    # блик проходит между нажатиями, а не во время переворота
    glare = 0.0
    for g0 in (0.08, 0.88, 1.68, 2.48):
        if g0 <= t <= g0 + 0.42:
            glare = (t - g0) / 0.42

    face_im = _face(face, bw, bh, glare)
    squeeze = max(0.06, abs(math.cos(ang)))        # переворот = сжатие по X
    fw = max(2, int(bw * squeeze))
    face_im = face_im.resize((fw, int(bh)), Image.BICUBIC)
    fx0 = int(bx + (bw - fw) / 2.0)

    d.rounded_rectangle([bx + 4, by + 6, bx + bw + 4, by + bh + 6],
                        radius=RADIUS, fill=(0, 0, 0, 95))
    im.alpha_composite(face_im, (fx0, int(by)))

    # ИСКРА ПО ПЕРИМЕТРУ — она ведёт взгляд к кнопке. Гаснет на перевороте:
    # пластина в этот момент стоит ребром, и дорожки у неё нет.
    if ang < 0.2:
        pts = _ring_path(bx, by, bx + bw, by + bh, RADIUS, 200)
        head = (t * 0.75) % 1.0
        n = len(pts)
        hi = int(head * n)
        # ДВА ПРОХОДА: широкий тусклый ореол и узкая яркая жила. На листе
        # кадров первая версия (одна линия в 3 px) была не видна вовсе —
        # на превью 480 px это меньше пикселя, и «замысловатость» пропадала.
        for width, mul in ((9, 0.30), (4, 1.0)):
            for j in range(56):
                idx = (hi - j) % n
                a = int(245 * mul * (1.0 - j / 56.0) ** 1.5)
                if a < 8:
                    continue
                x, y = pts[idx]
                nx, ny = pts[(idx + 1) % n]
                d.line([x, y, nx, ny], fill=ACCENT + (a,), width=width)

    # курсор-стрелка: та же, что в принятой кнопке — набор один, рука одна
    if t < T_LEAVE + 0.4:
        cur = _arrow(1.35)
        p_in = _ease(t / max(0.01, T_IN))
        x0, y0 = CW + 30, CH + 30
        x1 = BTN_X + BTN_W * 0.66
        y1 = BTN_Y + BTN_H * 0.58
        x = x0 + (x1 - x0) * p_in
        y = y0 + (y1 - y0) * p_in
        if t > T_LEAVE:
            q = _ease((t - T_LEAVE) / 0.4)
            x += (CW + 60 - x) * q
            y += (CH + 60 - y) * q
        x += 4 * press
        y += 4 * press
        im.alpha_composite(cur, (int(x), int(y)))
    return im


def _arrow(scale=1.0):
    from PIL import Image, ImageDraw
    pts = [(0, 0), (0, 36), (9, 27), (15, 41), (22, 38), (16, 25), (27, 24)]
    pts = [(x * scale, y * scale) for x, y in pts]
    im = Image.new("RGBA", (int(32 * scale), int(46 * scale)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon(pts, fill=(255, 255, 255, 255))
    d.line(pts + [pts[0]], fill=(26, 26, 28, 255), width=max(2, int(2 * scale)))
    return im


def render_frames(out_dir, seconds=TOTAL_SEC):
    os.makedirs(out_dir, exist_ok=True)
    n = int(round(seconds * FPS))
    for i in range(n):
        frame(i / float(FPS)).save(os.path.join(out_dir, "sub_%04d.png" % i))
    return n


def put_on_clip(ffmpeg, src, dst, at=0.3, margin=46, seconds=TOTAL_SEC,
                corner="right"):
    tmp = tempfile.mkdtemp(prefix="sub2_")
    try:
        n = render_frames(tmp, seconds)
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-i", src,
               "-framerate", str(FPS), "-start_number", "0",
               "-i", os.path.join(tmp, "sub_%04d.png"),
               "-filter_complex",
               "[1:v]setpts=PTS-STARTPTS+%.3f/TB[b];"
               "[0:v][b]overlay=x=%s:y=%d:eof_action=pass:shortest=0[v]"
               % (float(at),
                  ("%d" % int(margin)) if str(corner).lower().startswith("l")
                  else ("W-w-%d" % int(margin)),
                  int(margin)),
               "-map", "[v]", "-an",
               "-c:v", "libx264", "-preset", "veryfast",
               "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
               "-pix_fmt", "yuv420p", dst]
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = (r.returncode == 0 and os.path.isfile(dst)
              and os.path.getsize(dst) > 0)
        if not ok:
            print("FAIL: " + (r.stderr or "")[-600:], file=sys.stderr)
        else:
            print("кнопка (вид 2) поставлена: %s (%d кадров, угол %s)"
                  % (dst, n,
                     "ЛЕВЫЙ ВЕРХНИЙ"
                     if str(corner).lower().startswith("l")
                     else "ПРАВЫЙ ВЕРХНИЙ"))
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="")
    ap.add_argument("dst", nargs="?", default="")
    ap.add_argument("--frames", default="")
    ap.add_argument("--at", type=float, default=0.3)
    ap.add_argument("--seconds", type=float, default=TOTAL_SEC)
    ap.add_argument("--margin", type=int, default=46)
    ap.add_argument("--corner", default="right", choices=("right", "left"))
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()
    if a.frames:
        print("кадров: %d → %s" % (render_frames(a.frames, a.seconds), a.frames))
        return 0
    if not a.src or not a.dst:
        print("нужен клип и куда класть (или --frames <папка>)",
              file=sys.stderr)
        return 2
    if not os.path.isfile(a.src):
        print("нет файла: %s" % a.src, file=sys.stderr)
        return 2
    return 0 if put_on_clip(a.ffmpeg, a.src, a.dst, a.at, a.margin,
                            a.seconds, a.corner) else 1


if __name__ == "__main__":
    sys.exit(main())
