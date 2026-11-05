#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""КНОПКА «ПОДПИШИСЬ» — анимированная накладка поверх готового клипа.

    python3 fx_subscribe.py --frames <папка>            # PNG-последовательность
    python3 fx_subscribe.py <клип.mp4> <куда.mp4> [--at 0.3]   # наложить на клип

Его заказ 05.11 и его же правка по первому показу, дословно: «Не, просто
подпишись, и там палец как будто нажимает. Не надо „вы подписаны“, не надо
статус менять. Просто подпишись и всё. Было красное, стало чёрное, красное,
чёрное, вот так».

ЧТО ПРОИСХОДИТ (3,4 с, 30 кадров в секунду):
    0,00 с   кнопка «ПОДПИШИСЬ» ПОЯВЛЯЕТСЯ СРАЗУ, целиком — не выплывает;
    0,00-0,42  снизу входит палец;
    дальше   палец нажимает раз за разом, и НА КАЖДОЕ нажатие кнопка
             перекрашивается: красная → чёрная → красная → чёрная;
    3,00-3,40  палец уходит, в конце всё исчезает разом.

Надпись ВСЕГДА одна и та же — «ПОДПИШИСЬ». Ни «вы подписаны», ни колокольчика,
ни смены состояния: первая версия их имела, и он это прямо отменил.

ГРАНИЦЫ КАНАЛА:
  * глитча и тряски нет: двигается только палец, кнопка лишь проседает
    на 4% в момент нажатия;
  * появление и уход мгновенные;
  * типографика наша: узкий гротеск из `template/fonts`;
  * правый верхний угол — внизу субтитры, слева всплывашки.

ПОЧЕМУ КАДРЫ — ОТДЕЛЬНЫЕ PNG С АЛЬФОЙ: mp4 прозрачность не несёт, а кнопку
надо класть поверх живого кадра. Последовательность PNG ffmpeg берёт входом
напрямую, и тот же набор годится для `build_overlays.py`, когда кнопку
повесят по таймкоду ролика.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

FPS = 30
TOTAL_SEC = 3.4

# холст накладки: кнопка плюс место пальцу под ней
CW, CH = 560, 250
BTN_W, BTN_H = 392, 92
BTN_X, BTN_Y = 10, 10
RADIUS = 46

RED = (214, 25, 22)
BLACK = (16, 16, 18)
WHITE = (255, 255, 255)

TAPS = (0.50, 1.05, 1.60, 2.15, 2.70)   # когда палец дожимает
TAP_DOWN = 0.09                          # сколько длится просадка
T_IN = 0.42                              # палец вошёл
T_LEAVE = 3.00                           # палец уходит

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_FONTS = ["RobotoCondensed-Bold.ttf", "Montserrat-Bold.ttf", "Arimo-Bold.ttf"]
_SYS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


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


def _fit_font(text, box_w, start=52, low=28):
    """Кегль подбираем ИЗМЕРЕНИЕМ, а не на глаз."""
    size = start
    while size > low:
        f = _font(size)
        try:
            w = f.getlength(text)
        except AttributeError:
            w = f.getsize(text)[0]
        if w <= box_w:
            return f
        size -= 2
    return _font(low)


def _finger(scale=1.0):
    """Палец, который нажимает: кисть с вытянутым указательным вверх.

    Рисуем сами, как и всё остальное. Белый силуэт с тёмной обводкой читается
    на любом кадре — и на светлом небе, и на тёмном цеху.
    """
    from PIL import Image, ImageDraw
    w, h = int(104 * scale), int(150 * scale)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = scale
    ink = (28, 28, 30, 255)
    # указательный палец
    d.rounded_rectangle([26 * s, 2 * s, 56 * s, 78 * s], radius=15 * s,
                        fill=WHITE + (255,), outline=ink, width=int(3 * s))
    # кисть
    d.rounded_rectangle([18 * s, 56 * s, 92 * s, 140 * s], radius=26 * s,
                        fill=WHITE + (255,), outline=ink, width=int(3 * s))
    # костяшки согнутых пальцев
    for i in range(3):
        x0 = (56 + i * 12) * s
        d.rounded_rectangle([x0, (64 + i * 2) * s, x0 + 14 * s, (92 + i * 2) * s],
                            radius=7 * s, fill=WHITE + (255,), outline=ink,
                            width=int(2 * s))
    # стык пальца и кисти затираем, чтобы силуэт был один
    d.rounded_rectangle([28 * s, 60 * s, 54 * s, 76 * s], radius=10 * s,
                        fill=WHITE + (255,))
    return im


def _ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _press(t):
    """Сила нажатия 0…1 в момент t и номер нажатия (для цвета)."""
    for i, tap in enumerate(TAPS):
        if abs(t - tap) <= TAP_DOWN:
            return 1.0 - abs(t - tap) / TAP_DOWN, i
    return 0.0, -1


def _color(t):
    """КРАСНАЯ → ЧЁРНАЯ → КРАСНАЯ → ЧЁРНАЯ: цвет меняется на каждом нажатии."""
    n = sum(1 for tap in TAPS if t >= tap)
    return BLACK if n % 2 else RED


def frame(t):
    """Один кадр накладки на момент t (секунды от начала показа)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    press, _idx = _press(t)
    k = 1.0 - 0.04 * press
    bw, bh = BTN_W * k, BTN_H * k
    bx = BTN_X + (BTN_W - bw) / 2.0
    by = BTN_Y + (BTN_H - bh) / 2.0

    d.rounded_rectangle([bx + 3, by + 5, bx + bw + 3, by + bh + 5],
                        radius=RADIUS, fill=(0, 0, 0, 90))
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=RADIUS,
                        fill=_color(t))

    text = "ПОДПИШИСЬ"
    f = _fit_font(text, bw - 56)
    tw = f.getlength(text) if hasattr(f, "getlength") else f.getsize(text)[0]
    d.text((bx + (bw - tw) / 2.0, by + bh / 2.0), text, font=f,
           fill=WHITE, anchor="lm")

    # палец: входит снизу, дожимает кнопку, уходит вниз
    if t < T_LEAVE + 0.4:
        fg = _finger(1.0)
        p_in = _ease(t / max(0.01, T_IN))
        y0, y1 = CH + 30, BTN_Y + BTN_H - 18
        x = BTN_X + BTN_W * 0.58
        y = y0 + (y1 - y0) * p_in
        if t > T_LEAVE:
            y += (CH + 40 - y) * _ease((t - T_LEAVE) / 0.4)
        y += 10 * press                     # дожал — палец ушёл в кнопку
        im.alpha_composite(fg, (int(x), int(y)))
    return im


def render_frames(out_dir, seconds=TOTAL_SEC):
    os.makedirs(out_dir, exist_ok=True)
    n = int(round(seconds * FPS))
    for i in range(n):
        frame(i / float(FPS)).save(os.path.join(out_dir, "sub_%04d.png" % i))
    return n


def put_on_clip(ffmpeg, src, dst, at=0.3, margin=46, seconds=TOTAL_SEC):
    """Наложить кнопку на готовый клип. Правый верхний угол."""
    tmp = tempfile.mkdtemp(prefix="sub_")
    try:
        n = render_frames(tmp, seconds)
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-i", src,
               "-framerate", str(FPS), "-start_number", "0",
               "-i", os.path.join(tmp, "sub_%04d.png"),
               "-filter_complex",
               "[1:v]setpts=PTS-STARTPTS+%.3f/TB[b];"
               "[0:v][b]overlay=x=W-w-%d:y=%d:eof_action=pass:shortest=0[v]"
               % (float(at), int(margin), int(margin)),
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
            print("кнопка «подпишись» поставлена: %s (%d кадров, старт %.2f с)"
                  % (dst, n, at))
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="")
    ap.add_argument("dst", nargs="?", default="")
    ap.add_argument("--frames", default="", help="только PNG-кадры в эту папку")
    ap.add_argument("--at", type=float, default=0.3)
    ap.add_argument("--seconds", type=float, default=TOTAL_SEC)
    ap.add_argument("--margin", type=int, default=46)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()
    if a.frames:
        n = render_frames(a.frames, a.seconds)
        print("кадров: %d → %s" % (n, a.frames))
        return 0
    if not a.src or not a.dst:
        print("нужен клип и куда класть (или --frames <папка>)",
              file=sys.stderr)
        return 2
    if not os.path.isfile(a.src):
        print("нет файла: %s" % a.src, file=sys.stderr)
        return 2
    return 0 if put_on_clip(a.ffmpeg, a.src, a.dst, a.at, a.margin,
                            a.seconds) else 1


if __name__ == "__main__":
    sys.exit(main())
