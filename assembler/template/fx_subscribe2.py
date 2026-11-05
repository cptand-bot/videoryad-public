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

ЧЕМ ОТЛИЧАЕТСЯ (05.11, его замечание по первой попытке: «и в чём же
замысловатость этой кнопки? может, я не туда посмотрел?» — значит приём не
читался, и одной бегущей искры мало):
  * слева КРУГ-ЗНАК канала, вокруг него вращается пунктирное кольцо;
  * надпись НАБИРАЕТСЯ по букве, в разрядку, как заголовок;
  * под надписью черта-акцент ПРОЧЕРЧИВАЕТСЯ слева направо;
  * на нажатии от кнопки расходится ВОЛНА и в стороны летят ИСКРЫ,
    а по пластине косой кромкой НАБЕГАЕТ новая заливка: тёмная → красная →
    тёмная (силуэт при этом не меняется, надпись читается всегда);
  * по периметру бежит световая жила, между нажатиями проходит блик.

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
FILL = 0.30                     # за сколько новая заливка набегает
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


def _fill_state(t):
    """Какая грань сейчас, какая была и насколько новая заливка набежала.

    ПЕРЕВОРОТ ПЛАСТИНЫ ОТМЕНЁН (05.11, по листу кадров): при сжатии силуэта
    кнопка на четверть секунды превращалась в узкий блок с нечитаемой
    надписью — на стоп-кадре это выглядит сбоем, а не приёмом. Вместо
    поворота цвет НАБЕГАЕТ по пластине слева направо косой кромкой: силуэт
    не меняется, надпись читается всегда, а смена состояния видна.
    """
    face, prev, prog = 0, 0, 1.0
    for i, tap in enumerate(TAPS):
        if t >= tap + FILL:
            face = (i + 1) % 2
        elif t >= tap:
            prev = i % 2
            face = (i + 1) % 2
            prog = (t - tap) / FILL
            return face, prev, _ease(prog)
    return face, face, 1.0


def _mark(d, cx, cy, r, t, face):
    """Круг-знак канала и вращающееся вокруг него пунктирное кольцо."""
    col = WHITE if face else ACCENT
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    d.polygon([(cx - r * 0.28, cy - r * 0.42), (cx - r * 0.28, cy + r * 0.42),
               (cx + r * 0.44, cy)],
              fill=(18, 20, 24) if not face else RED)
    rr = r + 9
    base = (t * 70.0) % 360.0
    for i in range(12):
        a0 = base + i * 30.0
        d.arc([cx - rr, cy - rr, cx + rr, cy + rr], a0, a0 + 17,
              fill=col + (235,), width=4)


def _face(face, w, h, glare, t=0.0, typed=1.0, prev=None,
          prog=1.0):
    prev = face if prev is None else prev
    """Грань пластины: заливка, черта-акцент, надпись, блик."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bg = RED if face else DARK
    old_bg = RED if prev else DARK
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=RADIUS, fill=old_bg)
    if prog < 1.0:
        # косая кромка новой заливки — она и «проливает» кнопку
        edge = -w * 0.18 + (w * 1.18) * prog
        lay = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
        ImageDraw.Draw(lay).polygon(
            [(-2, h + 2), (edge - w * 0.10, h + 2),
             (edge + w * 0.10, -2), (-2, -2)], fill=bg + (255,))
        msk = Image.new("L", (int(w), int(h)), 0)
        ImageDraw.Draw(msk).rounded_rectangle([0, 0, w - 1, h - 1],
                                              radius=RADIUS, fill=255)
        im.paste(Image.alpha_composite(im, lay), (0, 0), msk)
        d = ImageDraw.Draw(im)
    else:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=RADIUS, fill=bg)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=RADIUS,
                        outline=(255, 255, 255, 60), width=2)
    # фирменная черта слева — как в наших надписях
    d.rounded_rectangle([18, h * 0.24, 27, h * 0.76], radius=4,
                        fill=ACCENT if not face else (255, 255, 255, 230))
    # круг-знак слева + вращающееся кольцо
    _mark(d, 56, h / 2.0, 22, t, face)
    track = 5
    f = _fit(TEXT, w - 150, track)
    tw = _text_w(f, TEXT, track)
    tx0 = 96 + (w - 96 - tw) / 2.0
    # НАДПИСЬ НАБИРАЕТСЯ ПО БУКВЕ — это видно на любом размере, в отличие от
    # тонкой искры, которой он не разглядел.
    shown = TEXT[:max(0, int(round(len(TEXT) * min(1.0, typed))))]
    _draw_tracked(d, (tx0, h / 2.0 - 6), shown, f, WHITE, track)
    # черта-акцент ПРОЧЕРЧИВАЕТСЯ слева направо под надписью
    uw = tw * min(1.0, typed * 1.15)
    if uw > 2:
        d.rounded_rectangle([tx0, h * 0.74, tx0 + uw, h * 0.74 + 5],
                            radius=2, fill=WHITE if face else ACCENT)
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
    face, prev, prog = _fill_state(t)
    k = 1.0 - 0.03 * press
    bw, bh = BTN_W * k, BTN_H * k
    bx = BTN_X + (BTN_W - bw) / 2.0
    by = BTN_Y + (BTN_H - bh) / 2.0

    # блик проходит между нажатиями, а не во время переворота
    glare = 0.0
    for g0 in (0.08, 0.88, 1.68, 2.48):
        if g0 <= t <= g0 + 0.42:
            glare = (t - g0) / 0.42

    typed = min(1.0, max(0.0, (t - 0.04) / 0.26))
    face_im = _face(face, bw, bh, glare, t, typed, prev, prog)
    fx0 = int(bx)

    d.rounded_rectangle([bx + 4, by + 6, bx + bw + 4, by + bh + 6],
                        radius=RADIUS, fill=(0, 0, 0, 95))
    im.alpha_composite(face_im, (fx0, int(by)))

    # ИСКРА ПО ПЕРИМЕТРУ — она ведёт взгляд к кнопке. Гаснет на перевороте:
    # пластина в этот момент стоит ребром, и дорожки у неё нет.
    if True:
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

    # ВОЛНА И ИСКРЫ ОТ НАЖАТИЯ — главный признак, что кнопку ткнули.
    for tap in TAPS:
        q = (t - tap) / 0.55
        if 0.0 <= q <= 1.0:
            e = _ease(q)
            px, py = bx + bw * 0.66, by + bh * 0.58
            rr = 26 + 150 * e
            a = int(210 * (1.0 - e) ** 1.4)
            if a > 6:
                d.ellipse([px - rr, py - rr * 0.62, px + rr, py + rr * 0.62],
                          outline=ACCENT + (a,), width=max(2, int(6 * (1 - e))))
            for i in range(12):
                ang2 = math.pi * 2 * i / 12.0 + tap
                dist = 18 + 120 * (e ** 0.7)
                sx = px + math.cos(ang2) * dist
                sy = py + math.sin(ang2) * dist * 0.62
                rad = max(1.0, 5.0 * (1.0 - e))
                sa = int(240 * (1.0 - e))
                if sa > 8:
                    d.ellipse([sx - rad, sy - rad, sx + rad, sy + rad],
                              fill=(255, 255, 255, sa))

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
