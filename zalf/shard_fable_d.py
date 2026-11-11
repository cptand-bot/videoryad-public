# -*- coding: utf-8 -*-
"""Белый зал, вторая реализация: G16 (перекидное табло). Запуск: shard_fable_d.py G16 <out>
Один кадр: ZAL_FRAME=1.2 shard_fable_d.py G16 k.png

Числа сняты с плёнки покадрово (polosy/G16_den1, G16_den2, G16_setka, G16_b):
  табло «DAY» живёт в исходнике 40.300-41.300 (склейка в начале и в конце);
  цифры бегут 050 → 123 за 24 кадра (40.300-41.067): шаги по кадрам
  50 58 66 70 72 … 99 103 106 … 113 114 116 117 119 119 120 121 122 122 122 123 —
  ход затухающий, степень ≈2.6; дата под цифрой меняется каждый кадр вместе с числом;
  перекид одной цифры — 1-2 кадра: на кадре смены верхняя половина новая, нижняя старая,
  створка почти ребром; на следующем кадре створка уже легла, остаётся тень-смаз;
  через 3 кадра после остановки (41.167) цифры становятся жёлтыми и в тот же кадр
  в левом верхнем углу появляется ярлык «DAY 123 JUN 12 2026»;
  табло по высоте ≈1.7 м при ширине ≈1.26 (h/w ≈1.35 в пикселях), висит на двух тросах
  на 0.14 и 0.86 ширины, центр чуть левее оси (fx 0.49), низ ≈0.81 м от пола;
  камера наезжает: дальность 5.6 → 4.57 → 3.70 → 3.36 м за 0.8 с (затухание степени ≈2.8);
  ячейки цифр — три тёмно-серых окна на чёрном поле с линией разреза посередине,
  «DAY» мелко слева сверху, дата — ряд мелких ячеек внизу.
"""
import sys, os, math, subprocess, datetime
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as Z
from zal_core import *

FPS = 30
DT = 1.0 / FPS

# ------- табло: геометрия и цвета -------
BW, BH = 1.26, 1.70            # метры (с плёнки: h/w в пикселях ≈1.35)
TW, TH = 800, 1080             # текстура
FACE = (15, 15, 17, 255)       # чёрное поле
FRAME = (92, 92, 95, 255)      # рамка
CELL = (42, 42, 45, 255)       # окно ячейки
SPLIT = (6, 6, 8, 255)         # линия разреза
WHITE = (236, 233, 226, 255)
YEL = (245, 202, 62, 255)
MONTHS = ["", "ЯНВАРЯ", "ФЕВРАЛЯ", "МАРТА", "АПРЕЛЯ", "МАЯ", "ИЮНЯ", "ИЮЛЯ",
          "АВГУСТА", "СЕНТЯБРЯ", "ОКТЯБРЯ", "НОЯБРЯ", "ДЕКАБРЯ"]
DAY0 = datetime.date(2026, 2, 9)   # день N = 9 февраля + N (с плёнки: 050 = 31 марта, 123 = 12 июня)
NDATE = 14                         # ячеек в строке даты

# ------- хронометраж клипа (3.6 с) -------
K_RUN0, K_RUN1 = 16, 40            # кадры бега счётчика (24 кадра, как на плёнке)
V0, V1 = 50, 123

def value_at(k):
    if k <= K_RUN0: return V0
    if k >= K_RUN1: return V1
    u = (k - K_RUN0) / (K_RUN1 - K_RUN0)
    return V0 + int(round((V1 - V0) * (1 - (1 - u) ** 2.6)))

K_YEL = min(k for k in range(K_RUN0, K_RUN1 + 1) if value_at(k) == V1) + 3   # жёлтый + ярлык через 3 кадра после остановки

def date_str(v):
    d = DAY0 + datetime.timedelta(days=v)
    s = f"{d.day} {MONTHS[d.month]} {d.year}"
    pad = NDATE - len(s)
    return " " * (pad // 2) + s + " " * (pad - pad // 2)

def chars_at(k):
    v = value_at(k)
    return f"{v:03d}" + date_str(v)

# ------- одна ячейка перекидного табло -------
_CELL_CACHE = {}

def _glyph(ch, fnt, cw, chh, color):
    """символ, выровненный по капители «0» на середину ячейки"""
    img = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
    if ch.strip():
        d = ImageDraw.Draw(img)
        b0 = fnt.getbbox("0")
        cap = b0[3] - b0[1]
        base = chh / 2 + cap / 2
        w = fnt.getlength(ch)
        if w > cw - 6:
            # широкая буква (Ю, Щ) — ужать по ширине, чтобы не вылезала из ячейки
            tmp = Image.new("RGBA", (int(w) + 8, chh), (0, 0, 0, 0))
            ImageDraw.Draw(tmp).text((4, base), ch, font=fnt, fill=color, anchor="ls")
            tmp = tmp.resize((cw - 6, chh), Image.LANCZOS)
            img.alpha_composite(tmp, (3, 0))
        else:
            d.text(((cw - w) / 2, base), ch, font=fnt, fill=color, anchor="ls")
    return img

def cell_tex(ch_new, ch_old, p, cw, chh, fnt, color):
    """ячейка с перекидом: p — фаза створки 0..1 (1 — створка легла)"""
    key = (ch_new, ch_old, round(p, 3), cw, chh, id(fnt), color)
    if key in _CELL_CACHE: return _CELL_CACHE[key]
    cell = Image.new("RGBA", (cw, chh), CELL)
    mid = chh // 2
    new = _glyph(ch_new, fnt, cw, chh, color)
    if p >= 1.0 or ch_new == ch_old:
        cell.alpha_composite(new)
    else:
        old = _glyph(ch_old, fnt, cw, chh, color)
        # неподвижные половины: сверху новая, снизу старая
        cell.alpha_composite(new.crop((0, 0, cw, mid)), (0, 0))
        cell.alpha_composite(old.crop((0, mid, cw, chh)), (0, mid))
        ang = p * math.pi
        c = math.cos(ang); s = math.sin(ang)
        shade = Image.new("RGBA", (cw, chh - mid), (0, 0, 0, int(110 * s)))
        if p < 0.5:
            # створка со старой верхней половиной падает: сжимается к линии разреза
            flap = Image.new("RGBA", (cw, mid), CELL); flap.alpha_composite(old.crop((0, 0, cw, mid)))
            h = max(1, int(mid * c))
            flap = flap.resize((cw, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1 + 4 * s))
            dark = Image.new("RGBA", (cw, h), (0, 0, 0, int(140 * s))); flap.alpha_composite(dark)
            cell.alpha_composite(shade, (0, mid))          # тень створки на нижней половине
            cell.alpha_composite(flap, (0, mid - h))
        else:
            # створка с новой нижней половиной ложится вниз
            flap = Image.new("RGBA", (cw, chh - mid), CELL); flap.alpha_composite(new.crop((0, mid, cw, chh)))
            h = max(1, int((chh - mid) * (-c)))
            flap = flap.resize((cw, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1 + 4 * s))
            dark = Image.new("RGBA", (cw, h), (0, 0, 0, int(120 * s))); flap.alpha_composite(dark)
            cell.alpha_composite(shade, (0, mid))
            cell.alpha_composite(flap, (0, mid))
    ImageDraw.Draw(cell).line([(0, mid), (cw, mid)], fill=SPLIT, width=max(2, chh // 120))
    _CELL_CACHE[key] = cell
    return cell

def flip_phase(k, i):
    """фаза створки ячейки i на кадре k: кадр смены — 0.45, следующий — 0.90, дальше легла"""
    cur = chars_at(k)
    for back in (0, 1):
        j = k - back
        if j <= 0: break
        if chars_at(j)[i] != chars_at(j - 1)[i]:
            return 0.45 + 0.45 * back, chars_at(j - 1)[i]
    return 1.0, cur[i]

_FONTS = {}
def _f(name, size):
    if (name, size) not in _FONTS: _FONTS[(name, size)] = font(name, size)
    return _FONTS[(name, size)]

def board_tex(k):
    img = Image.new("RGBA", (TW, TH), FRAME)
    d = ImageDraw.Draw(img)
    bd = 11
    d.rectangle([bd, bd, TW - bd - 1, TH - bd - 1], fill=FACE)
    # «ДЕНЬ» слева сверху
    fl = _f("ArialBlack.ttf", 80)
    d.text((TW * 0.075, TH * 0.062), "ДЕНЬ", font=fl, fill=WHITE, anchor="la")
    color = YEL if k >= K_YEL else WHITE
    cur = chars_at(k)
    # три окна цифр
    x0, x1 = TW * 0.06, TW * 0.94
    gap = TW * 0.018
    cw = int((x1 - x0 - 2 * gap) / 3)
    cy0, cy1 = int(TH * 0.165), int(TH * 0.625)
    fd = _f("ArialBlack.ttf", 470)
    for i in range(3):
        p, old = flip_phase(k, i)
        cell = cell_tex(cur[i], old, p, cw, cy1 - cy0, fd, color)
        img.alpha_composite(cell, (int(x0 + i * (cw + gap)), cy0))
    # строка даты: NDATE мелких ячеек
    dw = (x1 - x0) / NDATE
    dgap = 3
    dcw = int(dw - dgap)
    dy0, dy1 = int(TH * 0.70), int(TH * 0.805)
    fs = _f("Arimo-Bold.ttf", 54)
    for i in range(NDATE):
        p, old = flip_phase(k, 3 + i)
        cell = cell_tex(cur[3 + i], old, p, dcw, dy1 - dy0, fs, WHITE)
        img.alpha_composite(cell, (int(x0 + i * dw), dy0))
    return img

def corner_label(img, v):
    """ярлык хронологии в левом верхнем углу (на плёнке появляется в кадр жёлтого)"""
    d = ImageDraw.Draw(img, "RGBA")
    f1 = _f("ArialBlack.ttf", 34); f2 = _f("Arimo-Bold.ttf", 26)
    x, y = W * 0.035, H * 0.052
    s1 = f"ДЕНЬ {v}"
    d.text((x, y), s1, font=f1, fill=(22, 22, 24, 255), anchor="la")
    dt = DAY0 + datetime.timedelta(days=v)
    d.text((x + f1.getlength(s1) + 16, y + 8), f"{dt.day} {MONTHS[dt.month]} {dt.year}",
           font=f2, fill=(96, 98, 102, 255), anchor="la")

# ------- сцена -------
BZ = 6.0                 # табло по z
BX0, BY = -0.04, 1.66    # центр табло: чуть левее оси, низ 0.81 м (с плёнки по двум кадрам)

def cam_dist(t):
    # с плёнки по ширине табло (1.26 м): 5.6 (40.30) → 4.57 (40.43) → 3.70 (40.70) → 3.36 (41.10) → 3.3
    u = seg(t, 0.533, 1.333)
    d = 3.3 + 2.3 * (1 - u) ** 2.8 + 0.15 * (1 - seg(t, 0.0, 0.533))
    return d - 0.2 * seg(t, 1.333, 3.6)

def g16(t):
    k = int(round(t * FPS))
    cam = Cam(0.0, 1.55, BZ - cam_dist(t))
    img = room(cam)
    # качание на тросах: маятник вбок и лёгкий поворот
    L = CEIL - (BY + BH / 2)
    phi = math.radians(1.1) * math.sin(2 * math.pi * t / 2.6 + 0.7)
    yaw = math.radians(2.0) * math.sin(2 * math.pi * t / 3.1 + 1.9)
    roll = math.radians(0.35) * math.sin(2 * math.pi * t / 2.6 + 0.7)
    bx = BX0 + L * math.sin(phi)
    by = BY - L * (1 - math.cos(phi))
    corners = quad((bx, by, BZ), BW, BH, yaw, roll)
    tex = board_tex(k)
    floor_shadow(img, cam, corners, tex)
    # тросы: от потолка (точки крепления неподвижны) к верхней кромке табло
    tl, tr = corners[0], corners[1]
    d = ImageDraw.Draw(img, "RGBA")
    for u in (0.14, 0.86):
        top = cam.proj((BX0 - BW / 2 + u * BW, CEIL, BZ))
        pt = (tl[0] + (tr[0] - tl[0]) * u, tl[1] + (tr[1] - tl[1]) * u, tl[2] + (tr[2] - tl[2]) * u)
        b = cam.proj(pt)
        d.line([(top[0], top[1]), (b[0], b[1])], fill=(58, 60, 64, 235), width=3)
    extrude(img, cam, corners, tex, depth=0.06, steps=4, shade=(58, 58, 60))
    if k >= K_YEL:
        corner_label(img, value_at(k))
    return img

SCENES = {"G16": (g16, 3.6)}

def render(code, out):
    fn, dur = SCENES[code]
    n = int(dur * FPS)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = "ffmpeg"
    p = subprocess.Popen([exe, "-y", "-nostdin", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{Z.W}x{Z.H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                          "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                         stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(fn(i / FPS).convert("RGB").tobytes())
    p.stdin.close(); p.wait()
    print("готово:", out, n, "кадров")

if __name__ == "__main__":
    code = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else f"{code}.mp4"
    if os.environ.get("ZAL_FRAME"):
        t = float(os.environ["ZAL_FRAME"])
        SCENES[code][0](t).convert("RGB").save(out)
        print("кадр", t, "->", out)
    else:
        render(code, out)
