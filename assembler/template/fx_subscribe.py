#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""КНОПКА «ПОДПИШИСЬ» — анимированная накладка поверх готового клипа.

    python3 fx_subscribe.py --frames <папка>            # PNG-последовательность
    python3 fx_subscribe.py <клип.mp4> <куда.mp4> [--at 0.3]   # наложить на клип

Его заказ 05.11: «есть кнопка „Подпишись“, ютубовская — можешь сделать, чтобы
она была анимированная?». Делаем своим кодом (PIL), как и всё остальное:
никаких скачанных гифок и чужих шаблонов.

ЧТО ПРОИСХОДИТ (3,4 с, 30 кадров в секунду):
    0,00 с  кнопка ПОЯВЛЯЕТСЯ СРАЗУ, целиком — не выплывает и не мигает
            (его правило: появление мгновенное);
    0,00-0,45  курсор входит в кадр и идёт к кнопке;
    0,45-0,55  нажатие: кнопка проседает на 4% и возвращается;
    0,55    кнопка переключается в «ВЫ ПОДПИСАНЫ» и рядом встаёт колокольчик;
    0,55-1,25  колокольчик качается с затуханием (±18°);
    1,25-3,00  держится;
    3,00-3,40  курсор уходит, в конце всё исчезает разом.

ГРАНИЦЫ КАНАЛА, соблюдены буквально:
  * глитча и тряски нет: дрожит только колокольчик, и это его собственное
    движение, а не камера;
  * появление и уход — мгновенные, без выплывания;
  * типографика наша: узкий гротеск из `template/fonts`, не жёлтый с обводкой;
  * кнопка садится в ПРАВЫЙ ВЕРХНИЙ угол — внизу живут субтитры, слева
    всплывашки, и перекрывать их нельзя.

ПОЧЕМУ КАДРЫ — ОТДЕЛЬНЫЕ PNG С АЛЬФОЙ, А НЕ ВИДЕО: mp4 прозрачность не
несёт, а накладывать кнопку надо поверх живого кадра. Последовательность
PNG ffmpeg берёт входом напрямую, и тот же набор кадров годится и для
`build_overlays.py`, когда кнопку поставят по таймкоду ролика.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile

FPS = 30
TOTAL_SEC = 3.4

# холст накладки: кнопка + место курсору и размаху колокольчика
CW, CH = 620, 210
BTN_W, BTN_H = 430, 92
BTN_X, BTN_Y = 10, 58          # кнопка в холсте
RADIUS = 46

RED = (214, 25, 22)            # «ПОДПИШИСЬ»
GREY = (44, 44, 46)            # «ВЫ ПОДПИСАНЫ»
WHITE = (255, 255, 255)
DIM = (226, 226, 228)

T_CLICK = 0.45                 # когда курсор дожал
T_DOWN = 0.10                  # сколько держится нажатие
T_RING = 0.70                  # сколько качается колокольчик
T_LEAVE = 3.00                 # курсор уходит

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


def _fit_font(text, box_w, start=44, low=26):
    """Размер подбираем ИЗМЕРЕНИЕМ, а не на глаз: «ВЫ ПОДПИСАНЫ» длиннее
    «ПОДПИШИСЬ», и на фиксированном кегле вылезало за кнопку."""
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


def _bell(h=46):
    """Колокольчик рисуем сами: купол, юбка, язычок. Отдельной картинкой —
    чтобы крутить его вокруг верхней точки, а не вместе с кнопкой."""
    from PIL import Image, ImageDraw
    w = int(h * 0.95)
    im = Image.new("RGBA", (w + 8, h + 14), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = (w + 8) / 2.0
    d.ellipse([cx - 4, 2, cx + 4, 10], fill=DIM)                 # ушко
    d.pieslice([cx - w * 0.42, 8, cx + w * 0.42, 8 + h * 0.95],
               180, 360, fill=DIM)                               # купол
    d.rectangle([cx - w * 0.42, 8 + h * 0.46, cx + w * 0.42, 8 + h * 0.72],
                fill=DIM)                                        # стенки
    d.rounded_rectangle([cx - w * 0.54, 8 + h * 0.70,
                         cx + w * 0.54, 8 + h * 0.80],
                        radius=4, fill=DIM)                      # юбка
    d.ellipse([cx - 5, 8 + h * 0.82, cx + 5, 8 + h * 0.92], fill=DIM)
    return im


def _cursor(scale=1.0):
    """Курсор-стрелка: белая с тёмной обводкой, как в системе."""
    from PIL import Image, ImageDraw
    pts = [(0, 0), (0, 34), (8, 26), (14, 39), (20, 36), (14, 24), (25, 23)]
    pts = [(x * scale, y * scale) for x, y in pts]
    im = Image.new("RGBA", (int(30 * scale), int(44 * scale)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon(pts, fill=(255, 255, 255, 255), outline=(20, 20, 20, 255))
    d.line(pts + [pts[0]], fill=(20, 20, 20, 255), width=2)
    return im


def _ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def frame(t):
    """Один кадр накладки на момент t (секунды от начала показа)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    done = t >= T_CLICK
    # нажатие: кнопка проседает и возвращается — короткий, честный отклик
    press = 0.0
    if T_CLICK - T_DOWN <= t <= T_CLICK + T_DOWN:
        press = 1.0 - abs(t - T_CLICK) / T_DOWN
    k = 1.0 - 0.04 * press
    bw, bh = BTN_W * k, BTN_H * k
    bx = BTN_X + (BTN_W - bw) / 2.0
    by = BTN_Y + (BTN_H - bh) / 2.0

    # тень под кнопкой — иначе она лежит в одной плоскости с кадром
    d.rounded_rectangle([bx + 3, by + 5, bx + bw + 3, by + bh + 5],
                        radius=RADIUS, fill=(0, 0, 0, 90))
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=RADIUS,
                        fill=GREY if done else RED)

    text = "ВЫ ПОДПИСАНЫ" if done else "ПОДПИШИСЬ"
    pad = 92 if done else 46          # место колокольчику слева от текста
    f = _fit_font(text, bw - pad)
    tw = f.getlength(text) if hasattr(f, "getlength") else f.getsize(text)[0]
    tx = bx + (bw - tw) / 2.0 + (18 if done else 0)
    d.text((tx, by + bh / 2.0), text, font=f,
           fill=DIM if done else WHITE, anchor="lm")

    if done:
        # КОЛОКОЛЬЧИК КАЧАЕТСЯ С ЗАТУХАНИЕМ, а не дрожит: одно движение,
        # которое успокаивается, — это не тряска кадра, запрещённая правилом.
        q = (t - T_CLICK) / T_RING
        ang = 0.0
        if q < 1.0:
            ang = 18.0 * math.cos(q * math.pi * 3.0) * (1.0 - _ease(q))
        bell = _bell(46)
        rot = bell.rotate(ang, resample=Image.BICUBIC, expand=True,
                          center=(bell.width / 2.0, 6))
        im.alpha_composite(rot, (int(bx + 34 - (rot.width - bell.width) / 2),
                                 int(by + bh / 2 - 30)))

    # курсор: входит справа снизу, дожимает кнопку и уходит
    cur = _cursor(1.25)
    if t < T_LEAVE + 0.4:
        p_in = _ease(t / max(0.01, T_CLICK))
        tx0, ty0 = CW + 30, CH + 20
        tx1, ty1 = BTN_X + BTN_W * 0.62, BTN_Y + BTN_H * 0.60
        cx = tx0 + (tx1 - tx0) * p_in
        cy = ty0 + (ty1 - ty0) * p_in
        if t > T_LEAVE:
            p_out = _ease((t - T_LEAVE) / 0.4)
            cx += (CW + 60 - cx) * p_out
            cy += (CH + 40 - cy) * p_out
        if press > 0:
            cx += 3 * press
            cy += 3 * press
        im.alpha_composite(cur, (int(cx), int(cy)))
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
