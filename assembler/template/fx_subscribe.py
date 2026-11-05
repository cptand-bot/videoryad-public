#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""КНОПКА «ПОДПИШИСЬ» — анимированная накладка поверх готового клипа.

    python3 fx_subscribe.py --frames <папка>            # PNG-последовательность
    python3 fx_subscribe.py <клип.mp4> <куда.mp4> [--at 0.3]   # наложить на клип

Его заказ 05.11 и его же правка по первому показу, дословно: «Не, просто
подпишись, и там курсор нажимает. Не надо „вы подписаны“, не надо
статус менять. Просто подпишись и всё. Было красное, стало чёрное, красное,
чёрное, вот так».

ЧТО ПРОИСХОДИТ (3,4 с, 30 кадров в секунду):
    0,00 с   кнопка «ПОДПИШИСЬ» ПОЯВЛЯЕТСЯ СРАЗУ, целиком — не выплывает;
    0,00-0,42  справа снизу входит курсор-стрелка;
    дальше   курсор нажимает раз за разом, и НА КАЖДОЕ нажатие кнопка
             перекрашивается: красная → чёрная → красная → чёрная;
    3,00-3,40  курсор уходит, в конце всё исчезает разом.

Надпись ВСЕГДА одна и та же — «ПОДПИШИСЬ». Ни «вы подписаны», ни колокольчика,
ни смены состояния: первая версия их имела, и он это прямо отменил.

ГРАНИЦЫ КАНАЛА:
  * глитча и тряски нет: двигается только курсор, кнопка лишь проседает
    на 4% в момент нажатия;
  * появление и уход мгновенные;
  * типографика наша: узкий гротеск из `template/fonts`;
  * только ВЕРХНИЕ углы — внизу субтитры; угол чередуется
    по ролику: правый, левый, правый.

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

# холст накладки: кнопка плюс место курсору справа снизу
CW, CH = 560, 250
BTN_W, BTN_H = 392, 92
BTN_X, BTN_Y = 10, 10
RADIUS = 46

RED = (214, 25, 22)
BLACK = (16, 16, 18)
WHITE = (255, 255, 255)

TAPS = (0.50, 1.05, 1.60, 2.15, 2.70)   # когда курсор дожимает
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


def _arrow(scale=1.0):
    """Курсор-СТРЕЛКА — его правка 05.11: палец отменён, нужна стрелка.

    Белая с тёмной обводкой, как системный курсор: читается и на светлом
    небе, и на тёмном цеху, и не спорит с кадром.
    """
    from PIL import Image, ImageDraw
    pts = [(0, 0), (0, 36), (9, 27), (15, 41), (22, 38), (16, 25), (27, 24)]
    pts = [(x * scale, y * scale) for x, y in pts]
    im = Image.new("RGBA", (int(32 * scale), int(46 * scale)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon(pts, fill=(255, 255, 255, 255))
    d.line(pts + [pts[0]], fill=(26, 26, 28, 255), width=max(2, int(2 * scale)))
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

    # курсор: входит справа снизу, дожимает кнопку и уходит
    if t < T_LEAVE + 0.4:
        cur = _arrow(1.35)
        p_in = _ease(t / max(0.01, T_IN))
        x0, y0 = CW + 30, CH + 30
        x1 = BTN_X + BTN_W * 0.64
        y1 = BTN_Y + BTN_H * 0.56
        x = x0 + (x1 - x0) * p_in
        y = y0 + (y1 - y0) * p_in
        if t > T_LEAVE:
            q = _ease((t - T_LEAVE) / 0.4)
            x += (CW + 60 - x) * q
            y += (CH + 60 - y) * q
        x += 4 * press                      # дожал — курсор чуть вдавился
        y += 4 * press
        im.alpha_composite(cur, (int(x), int(y)))
    return im


def render_frames(out_dir, seconds=TOTAL_SEC):
    os.makedirs(out_dir, exist_ok=True)
    n = int(round(seconds * FPS))
    for i in range(n):
        frame(i / float(FPS)).save(os.path.join(out_dir, "sub_%04d.png" % i))
    return n


def put_on_clip(ffmpeg, src, dst, at=0.3, margin=46, seconds=TOTAL_SEC,
                corner="right"):
    """Наложить кнопку на готовый клип. Верхний угол — правый или левый.

    УГОЛ ЧЕРЕДУЕТСЯ ПО РОЛИКУ (05.11, его слово при приёмке): «используем её
    три раза на длину видео. Один раз в правом углу, другой раз в левом,
    один раз в правом. В верхнем углу». Низ не трогаем ни при каком угле —
    там субтитры.
    """
    tmp = tempfile.mkdtemp(prefix="sub_")
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
            print("кнопка «подпишись» поставлена: %s (%d кадров, старт "
                  "%.2f с, угол %s)"
                  % (dst, n, at,
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
    ap.add_argument("--frames", default="", help="только PNG-кадры в эту папку")
    ap.add_argument("--at", type=float, default=0.3)
    ap.add_argument("--seconds", type=float, default=TOTAL_SEC)
    ap.add_argument("--margin", type=int, default=46)
    ap.add_argument("--corner", default="right", choices=("right", "left"))
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
                            a.seconds, a.corner) else 1


if __name__ == "__main__":
    sys.exit(main())
