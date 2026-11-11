# -*- coding: utf-8 -*-
"""Белый зал, вторая реализация: G17 (счётчик кадров). Запуск: shard_fable_e.py G17 <out>
Один кадр: ZAL_FRAME=1.5 shard_fable_e.py G17 k.png

Числа сняты с плёнки покадрово (polosy/G17_vhod, G17_b, G17_c, сетки G17*_setka);
t=0 моего клипа = 261.700 исходника:
  камера: панель заполняет кадр (ширина 87%) и камера отъезжает: ширина панели
          76% на +0.10 с · 59% на +0.17 · 47% на +0.30 · 40% на +0.60 · 39% дальше,
          то есть дальность 3.5 → 7.9 м по ходу 1−exp(−8.8·t^1.7); дальше стоит.
  панель: 31–69% × 11–61% кадра на 7.9 м → 2.9–3.0 × 2.1 м, центр на высоте 2.16,
          на двух тросах к потолку (x ≈ ±0.8), тонкая тёмная рамка.
  плашка: 36–64% × 64–74% кадра → 2.1 × 0.43 м, центр на высоте 0.72, висит под
          панелью на двух коротких тросах (зазор ≈ 0.15 м); тёмная с серой каймой,
          «FRAME» кремовый слева (7–38% ширины), число жёлтое справа (50–93%).
  счётчик: была под нижней кромкой кадра ещё до отъезда (тёмная полоса на 261.700);
          261.767 → 7 855 · 261.800 → 7 856 · 262.000 → 7 861/862 · 263.533 → 7 903
          · 265.600 → 7 968: +1 на каждый кадр = номер кадра самого ролика (t·30 − 1).
          Единицы на половине кадров смазаны — цифра катится, как в одометре.
  слова:  «ONE» 262.000 · «MORE» 262.300 · «THING.» 262.633 — висят над панелью
          (y 4–8%, слева от x=33%), 263.300 смазываются вверх и исчезают;
          «I» 263.533 · «DIDN'T» 263.867 · «MAKE» 264.100 · «THIS» 264.433 ·
          «VIDEO.» 264.667 — стоят на полу слева (x от 19%, низ на 88%, высота 8%).
"""
import sys, os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as Z
from zal_core import *

FPS = 30
DT = 1.0 / FPS

# ---- геометрия, снятая с плёнки (метры) ----
PANEL_Z = 7.9            # панель стоит здесь; камера в конце в z=0
PANEL_W, PANEL_H = 3.0, 2.12
PANEL_Y = 2.16           # центр панели по высоте В КОНЦЕ отъезда
# на плёнке панель в упор 87×87% кадра (пропорция 1.78), в конце 39×50% (1.4):
# она не жёсткая — пока камера отъезжает, панель подтягивается тросами вверх и
# вытягивается в высоту 1.69 → 2.12 м, центр 1.58 → 2.16 м (снято по пяти кадрам)
PANEL_H0, PANEL_Y0 = 1.69, 1.58
PLATE_W, PLATE_H = 1.95, 0.40
PLATE_GAP0, PLATE_GAP = 0.02, 0.15   # зазор между низом панели и верхом плашки: в упор 2%, в конце 3% кадра
D0, D1 = 3.5, 7.9        # дальность камеры: старт → стоп
N0 = 7853                # число на счётчике в кадре t=0

YEL = (247, 201, 44, 255)
CREAM = (240, 232, 208, 255)
INK = (24, 23, 24, 255)


# ---------------------------------------------------------------- ход камеры
def hod(t):
    """ход отъезда 0→1: медленный старт, быстрый разгон, плавная остановка к 0.7 с"""
    if t <= 0: return 0.0
    return 1.0 - math.exp(-8.8 * (t ** 1.7))

def dist(t):
    """дальность камеры до панели: быстрый отъезд с остановкой, как на плёнке"""
    return D0 + (D1 - D0) * hod(t) + 0.02 * max(0.0, t - 0.8)   # дальше еле заметно дрейфует

def panel_geom(t):
    """(центр по высоте, высота) панели в момент t"""
    f = hod(t)
    return PANEL_Y0 + (PANEL_Y - PANEL_Y0) * f, PANEL_H0 + (PANEL_H - PANEL_H0) * f


def pop(t0, t, k0=1.22, dur=0.10):
    """вход слова как на плёнке: первый кадр крупнее и бледнее, за три кадра садится"""
    if t < t0 - 1e-6: return None
    u = seg(t, t0, t0 + dur)
    return k0 + (1.0 - k0) * out_cubic(u), 0.55 + 0.45 * clamp01(u * 2.2)


# ---------------------------------------------------------------- текстуры (считаются один раз)
_CACHE = {}

def panel_tex():
    """содержимое панели — своя мини-сцена зала, без чужих кадров"""
    if "panel" in _CACHE: return _CACHE["panel"]
    mc = Cam(0.0, 1.55, 0.0)
    img = room(mc)
    # большая надпись на тросах
    tex = text_tex(["ОНО ЗДЕСЬ"], fsize=260, cond=0.92)
    h = 0.72; w = h * tex.size[0] / tex.size[1]            # ≈3.9 м — целиком в поле панели
    c = quad((-0.2, 2.45, 5.6), w, h)
    for xx in (-0.2 - w * 0.36, -0.2 + w * 0.36):
        wire(img, mc, (xx, 2.45 + h / 2, 5.6))
    extrude(img, mc, c, tex, depth=0.25, steps=7, shade=(60, 60, 64))
    # макеты на полу: жёлтые бруски, глобус, проволочный куб, белый макет
    yel = Image.new("RGBA", (40, 160), (236, 196, 40, 255))
    for i, (x, hh) in enumerate(((-2.6, 1.2), (-2.15, 1.5), (-1.7, 1.0))):
        extrude(img, mc, quad((x, hh / 2, 12.0), 0.3, hh), yel, depth=0.3, steps=4, shade=(150, 120, 20))
    gl = Image.new("RGBA", (300, 300), (0, 0, 0, 0)); gd = ImageDraw.Draw(gl)
    gd.ellipse([4, 4, 296, 296], fill=(236, 196, 40, 255))
    gd.chord([30, 40, 200, 260], 20, 200, fill=(40, 38, 36, 255))
    gd.ellipse([170, 60, 270, 200], fill=(40, 38, 36, 255))
    paste_quad(img, gl, [mc.proj(p) for p in quad((-0.9, 0.65, 11.8), 1.3, 1.3)])
    glass_cube(img, mc, (1.0, 0.7, 12.2), 1.4, wires=False)
    paste_quad(img, maket_tex("bank", 420), [mc.proj(p) for p in quad((3.0, 0.7, 12.0), 1.4, 1.4)])
    # стопка белых кубиков справа — четыре куска
    cube_tex = Image.new("RGBA", (60, 60), (238, 240, 243, 255))
    for j in range(4):
        extrude(img, mc, quad((4.2 + (j % 2) * 0.05, 0.3 + j * 0.6, 12.3), 0.6, 0.6), cube_tex,
                depth=0.6, steps=3, shade=(150, 152, 156))
    # оранжевое свечение справа вверху
    img = embers(img, mc, [(2.4, 2.7, 7.6, 0.75)], 0.0, glow=1.1)
    # обрезаем бока до пропорции панели, наклейка «ДЕНЬ 243» внизу, рамка
    tw = int(H * PANEL_W / PANEL_H)
    img = img.crop(((W - tw) // 2, 0, (W - tw) // 2 + tw, H))
    st = text_tex(["ДЕНЬ 243"], fsize=120, hl={1})
    sh = int(H * 0.075); sw = int(sh * st.size[0] / st.size[1])
    img.alpha_composite(st.resize((sw, sh), Image.LANCZOS), ((tw - sw) // 2, int(H * 0.84)))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, tw - 1, H - 1], outline=(42, 42, 46, 255), width=14)
    _CACHE["panel"] = img
    return img


def plate_base():
    """пустая плашка: серая кайма, тёмное поле, слово «КАДР»"""
    if "plate" in _CACHE: return _CACHE["plate"]
    pw = 1260; ph = int(pw * PLATE_H / PLATE_W)
    img = Image.new("RGBA", (pw, ph), (98, 98, 102, 255))
    d = ImageDraw.Draw(img)
    b = int(ph * 0.075)
    d.rectangle([b, b, pw - b - 1, ph - b - 1], fill=(27, 27, 29, 255))
    f = font("Oswald-Bold.ttf", int(ph * 0.50))      # буквы ≈ 48% высоты плашки, как на плёнке
    bb = d.textbbox((0, 0), "КАДР", font=f)
    d.text((pw * 0.07 - bb[0], (ph - (bb[3] - bb[1])) / 2 - bb[1]), "КАДР", font=f, fill=CREAM)
    fd = font("Oswald-Bold.ttf", int(ph * 0.56))     # цифры чуть крупнее слова, как на плёнке
    bd = ImageDraw.Draw(img).textbbox((0, 0), "0123456789", font=fd)
    _CACHE["plate"] = (img, fd, bd[1], bd[3] - bd[1])
    return _CACHE["plate"]


def plate_tex(n, roll=0.0):
    """плашка с числом n. Цифры в ячейках одной ширины — не прыгают.
    roll ∈ [0,1) — насколько единицы уже укатились к следующей цифре (след одометра)."""
    base, f, ty, th = plate_base()
    img = base.copy()
    d = ImageDraw.Draw(img)
    pw, ph = img.size
    cell = max(d.textlength(c, font=f) for c in "0123456789") * 1.16
    gap = cell * 0.55                                   # пробел между разрядами
    s = f"{n:,}".replace(",", " ")
    width = sum(cell if ch != " " else gap for ch in s)
    x = pw * 0.715 - width / 2                          # число стоит в поле 50–93% ширины
    y = (ph - th) / 2 - ty
    for k, ch in enumerate(s):
        if ch == " ":
            x += gap; continue
        cw = d.textlength(ch, font=f)
        cx = x + (cell - cw) / 2
        if k == len(s) - 1 and roll > 0:
            # единица поймана на ходу: предыдущая цифра ещё просвечивает, обе чуть смазаны по вертикали
            prev = str((n - 1) % 10)
            lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
            ld.text((cx, y + th * 0.10 * roll), ch, font=f, fill=YEL)
            g = Image.new("RGBA", img.size, (0, 0, 0, 0)); gd = ImageDraw.Draw(g)
            gd.text((cx, y - th * 0.12 * roll), prev, font=f, fill=YEL[:3] + (int(255 * 0.8 * roll),))
            lay.alpha_composite(g)
            lay = lay.filter(ImageFilter.GaussianBlur(th * 0.025))
            img.alpha_composite(lay)
        else:
            d.text((cx, y), ch, font=f, fill=YEL)
        x += cell
    return img


def floor_patch(img, cam, cx, z0, z1, hw, alpha=70):
    """мягкое пятно тени на полу под висящей панелью"""
    tex = Image.new("RGBA", (300, 160), (0, 0, 0, 0))
    ImageDraw.Draw(tex).rounded_rectangle([30, 20, 270, 140], 50, fill=(38, 40, 44, alpha))
    tex = tex.filter(ImageFilter.GaussianBlur(22))
    pts = [(cx - hw, 0.01, z1), (cx + hw, 0.01, z1), (cx + hw, 0.01, z0), (cx - hw, 0.01, z0)]
    paste_quad(img, tex, [cam.proj(p) for p in pts])


def words_line(img, cam, words, times, t, left_x, base_y, z, fsize, h, on_floor, depth, exit_t=None):
    """строка, набирающаяся по словам слева направо; каждое слово входит с перелётом"""
    if exit_t is not None and t >= exit_t + DT - 1e-6: return
    tw, th, tiles = word_tiles([" ".join(words)], fsize=fsize, pad=0)
    k = h / th
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for (tile, cx, cy), t0 in zip(tiles, times):
        p = pop(t0, t)
        if p is None: continue
        sc, op = p
        ww, hh = tile.size[0] * k * sc, tile.size[1] * k * sc
        wx = left_x + cx * k
        wy = (base_y + hh / 2) if on_floor else base_y
        c = quad((wx, wy, z), ww, hh)
        if on_floor:
            floor_shadow(lay, cam, c, tile)
        if depth > 0:
            extrude(lay, cam, c, tile, depth=depth, steps=5, shade=(58, 58, 62))
        else:
            paste_quad(lay, tile, [cam.proj(q) for q in c])
        if op < 1.0:
            a = lay.split()[3].point(lambda v: int(v * op)); lay.putalpha(a)
    if exit_t is not None and t >= exit_t - 1e-6:
        # последний кадр: строка смазывается вверх и исчезает
        sm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for i in range(6):
            g = lay.copy(); g.putalpha(g.split()[3].point(lambda v: int(v * 0.40)))
            sm.alpha_composite(g, (0, 0), (0, int(i * H * 0.035), W, H))
        lay = sm.filter(ImageFilter.GaussianBlur(3))
    img.alpha_composite(lay)


# ---------------------------------------------------------------- сама сцена
def g17(t):
    d = dist(t)
    cam = Cam(0.0, 1.55, PANEL_Z - d)
    img = room(cam)
    # тень от панели и плашки на полу
    floor_patch(img, cam, 0.4, PANEL_Z - 0.4, PANEL_Z + 2.6, 2.2, alpha=64)

    # панель на двух тросах
    ptex = panel_tex()
    py, ph = panel_geom(t)
    pc = quad((0.0, py, PANEL_Z), PANEL_W, ph)
    for xx in (-0.8, 0.8):
        wire(img, cam, (xx, py + ph / 2, PANEL_Z), color=(96, 98, 102, 230), width=3)
    extrude(img, cam, pc, ptex, depth=0.10, steps=4, shade=(70, 70, 74))

    # плашка со счётчиком: +1 на каждый кадр, единицы катятся как в одометре
    i = int(round(t * FPS))
    roll = 0.0 if i % 2 == 0 else 0.42        # через кадр единица поймана на ходу — так и на плёнке
    ltex = plate_tex(N0 + i, roll)
    gap = PLATE_GAP0 + (PLATE_GAP - PLATE_GAP0) * hod(t)
    plate_y = py - ph / 2 - gap - PLATE_H / 2
    lc = quad((0.0, plate_y, PANEL_Z), PLATE_W, PLATE_H)
    for xx in (-0.66, 0.66):
        a = cam.proj((xx, py - ph / 2, PANEL_Z)); b = cam.proj((xx, plate_y + PLATE_H / 2, PANEL_Z))
        ImageDraw.Draw(img, "RGBA").line([(a[0], a[1]), (b[0], b[1])], fill=(90, 92, 96, 230), width=2)
    extrude(img, cam, lc, ltex, depth=0.12, steps=4, shade=(72, 72, 76))

    # «И ЕЩЁ ОДНО.» над панелью — по словам, в 1.60 с смазывается вверх
    words_line(img, cam, ["И", "ЕЩЁ", "ОДНО."], [0.27, 0.57, 0.90], t,
               left_x=-1.3, base_y=3.44, z=PANEL_Z - 0.3, fsize=200, h=0.24,
               on_floor=False, depth=0.06, exit_t=1.60)
    # «Я НЕ ДЕЛАЛ ЭТО ВИДЕО.» встаёт на пол слева, слово за словом
    words_line(img, cam, ["Я", "НЕ", "ДЕЛАЛ", "ЭТО", "ВИДЕО."], [1.83, 2.17, 2.40, 2.73, 2.97], t,
               left_x=-2.24, base_y=0.0, z=7.4, fsize=200, h=0.30,
               on_floor=True, depth=0.14)
    return img


SCENES = {"G17": (g17, 4.0)}


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
