# -*- coding: utf-8 -*-
"""Белый зал, вторая реализация: G25 (уход в полный экран и обратно).
Запуск: shard_fable_f.py G25 <out.mp4>; один кадр: ZAL_FRAME=1.5 shard_fable_f.py G25 k.png

Что снято с плёнки (кусок 100.0-105.0 и вокруг):
  102.933 → 102.967  вход в эфир — ЖЁСТКАЯ СКЛЕЙКА, один кадр (статья в зале → экран целиком);
  102.967 → 108.933  эфир во весь кадр ровно 6.00 с, картинка не едет, живут только надписи:
                     слова субтитра по одному (0.27 с после входа, далее шаг 0.1-0.4 с),
                     плашка с именем въезжает шторкой слева 103.33 → 103.53;
  108.933 → 108.967  выход — тоже склейка, в зал без панели.
  Плавного ухода в эфир на всём ролике ровно один — 181.00 → 181.73 (0.73 с, панель
  под углом ~18° выпрямляется и заполняет кадр, ширина 0.44 → 0.57 → 0.85 → 1.0 — ход
  почти ровный с лёгким разгоном). Отъезда «обратно в зал» без склейки на плёнке нет —
  он здесь построен зеркально входу, ходом с торможением (out_cubic).
"""
import sys, os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as Z
from zal_core import *

FPS = 30

PANEL_W, PANEL_H = 3.2, 1.8      # панель 16:9, метры
ZP, EYE = 8.0, 1.55              # где висит и на какой высоте (центр на уровне глаз)

# ---- раскладка по времени (клип 5.0 с) ----
T_FLY0 = 0.60                    # зал, панель висит
FLY_IN = 0.73                    # разворот во весь кадр (181.00 → 181.73 на плёнке)
T_FULL = T_FLY0 + FLY_IN         # 1.33 — экран целиком
T_BACK0 = 3.50                   # эфир держится 2.17 с (на плёнке 6.0 с — ужато под клип)
FLY_OUT = 0.95                   # отъезд в зал: быстро отходим, долго садимся
T_BACK1 = T_BACK0 + FLY_OUT      # 4.45 — снова зал

YAW0 = math.radians(30)          # наклон панели в зале (правый край дальше): трапеция должна читаться
YAW1 = math.radians(22)          # наклон после отъезда
XOFF0 = 1.0                      # камера левее оси панели

WHITE = (255, 255, 255, 255)
INK = (24, 26, 34, 255)
RED = (196, 24, 32, 255)
YEL = (255, 208, 0, 255)

# слова субтитра: время от момента заполнения кадра (на плёнке первое слово через 0.27 с)
SUB_WORDS = ["Я", "думаю,", "это", "первый", "случай,", "когда", "нечто", "настолько",
             "автономное", "делает", "подобное."]
SUB_T = [0.27 + i * 0.165 for i in range(len(SUB_WORDS))]
LT_T0, LT_T1 = 0.37, 0.57        # шторка плашки с именем (103.33 → 103.53)


def shadow_text(d, xy, txt, f, fill, shadow=(0, 0, 0, 160), r=2):
    x, y = xy
    for dx, dy in ((r, r), (-r, r), (r, -r), (-r, -r), (0, r + 1)):
        d.text((x + dx, y + dy), txt, font=f, fill=shadow)
    d.text((x, y), txt, font=f, fill=fill)


# ---------- студия: свой задник, свой ведущий, никаких чужих кадров ----------
_STUDIO = None
def studio_parts(w=1920, h=1080):
    """(задник, фигура ведущего отдельным слоем) — фигура потом чуть покачивается"""
    global _STUDIO
    if _STUDIO is not None: return _STUDIO
    img = Image.new("RGBA", (w, h), (16, 40, 112, 255))
    d = ImageDraw.Draw(img)
    for i in range(h):
        k = i / h
        d.line([(0, i), (w, i)], fill=(int(14 + 20 * (1 - k)), int(44 + 36 * (1 - k)),
                                       int(118 + 52 * (1 - k)), 255))
    # концентрические дуги задника — справа крупные, слева помельче
    arcs = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ad = ImageDraw.Draw(arcs)
    for (cx, cy, r0, step, wd) in ((w * 1.06, h * 0.40, 120, 92, 14), (w * -0.12, h * 0.62, 90, 70, 9)):
        for r in range(r0, 1700, step):
            ad.ellipse([cx - r, cy - r * 0.64, cx + r, cy + r * 0.64],
                       outline=(96, 150, 236, 70), width=wd)
    img.alpha_composite(arcs.filter(ImageFilter.GaussianBlur(2.5)))
    # световое пятно за ведущим
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    gd.ellipse([w * 0.22, h * 0.02, w * 0.78, h * 0.80], fill=(120, 170, 255, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))
    # ведущий: плоский силуэт, по центру, как у гостя в эфире
    fig = Image.new("RGBA", (w, h), (0, 0, 0, 0)); fd = ImageDraw.Draw(fig)
    cx = w * 0.50
    fd.polygon([(cx - w * 0.235, h * 1.02), (cx - w * 0.21, h * 0.64), (cx - w * 0.09, h * 0.54),
                (cx + w * 0.09, h * 0.54), (cx + w * 0.21, h * 0.64), (cx + w * 0.235, h * 1.02)],
               fill=(12, 12, 16, 255))                                             # пиджак
    fd.polygon([(cx - w * 0.055, h * 0.54), (cx + w * 0.055, h * 0.54), (cx, h * 0.70)],
               fill=(30, 30, 36, 255))                                             # футболка под пиджаком
    fd.rectangle([cx - w * 0.034, h * 0.42, cx + w * 0.034, h * 0.58], fill=(206, 160, 134, 255))  # шея
    fd.ellipse([cx - w * 0.066, h * 0.13, cx + w * 0.066, h * 0.47], fill=(222, 182, 156, 255))    # голова
    fd.chord([cx - w * 0.070, h * 0.10, cx + w * 0.070, h * 0.33], 180, 360, fill=(74, 50, 34, 255))  # волосы
    fd.chord([cx - w * 0.066, h * 0.30, cx + w * 0.066, h * 0.49], 20, 160, fill=(92, 62, 42, 255))   # борода
    fd.rectangle([cx - w * 0.070, h * 0.22, cx - w * 0.054, h * 0.30], fill=(74, 50, 34, 255))
    fd.rectangle([cx + w * 0.054, h * 0.22, cx + w * 0.070, h * 0.30], fill=(74, 50, 34, 255))
    for sx in (-1, 1):                                                              # глаза и брови
        ex = cx + sx * w * 0.026
        fd.ellipse([ex - 11, h * 0.283, ex + 11, h * 0.303], fill=(40, 30, 28, 255))
        fd.line([(ex - 22, h * 0.262), (ex + 22, h * 0.258)], fill=(60, 40, 30, 255), width=5)
    fd.line([(cx - 16, h * 0.385), (cx + 16, h * 0.385)], fill=(150, 96, 84, 255), width=4)   # рот
    # виньетка по краям и темнее к низу — у студии есть чёрное
    vig = Image.new("L", (w, h), 0); vd = ImageDraw.Draw(vig)
    vd.rectangle([0, 0, w, h], fill=170); vd.ellipse([-w * 0.05, -h * 0.30, w * 1.05, h * 1.05], fill=0)
    vig = vig.filter(ImageFilter.GaussianBlur(140))
    dk = Image.new("RGBA", (w, h), (0, 2, 14, 255)); dk.putalpha(vig)
    img.alpha_composite(dk)
    # тень от фигуры — на задник
    sh = fig.filter(ImageFilter.GaussianBlur(30))
    dark = Image.new("RGBA", (w, h), (4, 6, 30, 255)); dark.putalpha(sh.split()[3].point(lambda v: int(v * 0.6)))
    img.alpha_composite(dark, (int(w * 0.015), int(h * 0.012)))
    _STUDIO = (img, fig)
    return _STUDIO

def studio_tex(t):
    back, fig = studio_parts()
    img = back.copy()
    dx = int(round(4 * math.sin(t * 1.3))); dy = int(round(2.5 * math.sin(t * 0.8 + 1.0)))   # дыхание, покачивание
    img.alpha_composite(fig, (dx, dy))
    return img


def overlay_tex(tt, w=1920, h=1080):
    """оформление эфира: то, что живёт поверх картинки. tt — время от заполнения кадра
    (до него отрицательное: плашка ещё пустая, субтитров нет)"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # мелкая атрибуция сверху слева
    d.text((w * 0.035, h * 0.028), "ТЕЛЕКАНАЛ «ВЗГЛЯД» · 2 августа 2026",
           font=font("Arimo-Bold.ttf", 22), fill=(255, 255, 255, 190))
    # жёлтая черта и подпись сюжета
    d.rectangle([w * 0.035, h * 0.086, w * 0.035 + 6, h * 0.160], fill=YEL)
    fl = font("Oswald-Bold.ttf", 34)
    shadow_text(d, (w * 0.050, h * 0.084), "ТА САМАЯ КОМПАНИЯ,", fl, WHITE)
    shadow_text(d, (w * 0.050, h * 0.122), "КУДА ОНИ ВЛОМИЛИСЬ", fl, WHITE)
    # логотип программы справа
    fs = font("Arimo-Bold.ttf", 24)
    tw = d.textlength("7 КАНАЛ · НОВОСТИ", font=fs)
    d.text((w * 0.965 - tw, h * 0.030), "7 КАНАЛ · НОВОСТИ", font=fs, fill=(255, 255, 255, 200))
    fb = font("Oswald-Bold.ttf", 84)
    for i, word in enumerate(("ГЛАВНЫЙ", "РАЗГОВОР")):
        tw = d.textlength(word, font=fb)
        shadow_text(d, (w * 0.965 - tw, h * 0.062 + i * h * 0.080), word, fb,
                    (255, 255, 255, 255) if i == 0 else (200, 222, 255, 255), r=3)
    # нижняя плашка: красный блок программы + белая полоса под имя
    d.rectangle([0, h * 0.858, w * 0.232, h * 0.912], fill=RED)
    fp = font("Oswald-Bold.ttf", 36)
    d.text((w * 0.044, h * 0.863), "ГЛАВНЫЙ РАЗГОВОР", font=fp, fill=WHITE)
    d.rectangle([w * 0.232, h * 0.858, w * 0.790, h * 0.912], fill=(246, 246, 248, 255))
    d.rectangle([w * 0.232, h * 0.912, w * 0.790, h * 0.934], fill=RED)
    # имя въезжает шторкой слева
    k = seg(tt, LT_T0, LT_T1)
    if k > 0:
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
        ld.text((w * 0.248, h * 0.860), "ИЛЬЯ ГРАНИН", font=font("Oswald-Bold.ttf", 42), fill=INK)
        ld.text((w * 0.248, h * 0.911), "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР, «НЕЙРОЛАБ»",
                font=font("Arimo-Bold.ttf", 18), fill=WHITE)
        ld.rectangle([w * 0.232, h * 0.826, w * 0.300, h * 0.858], fill=RED)
        ld.text((w * 0.240, h * 0.829), "Москва", font=font("Arimo-Bold.ttf", 20), fill=WHITE)
        xcut = int(w * (0.232 + 0.558 * out_cubic(k)))
        mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).rectangle([0, 0, xcut, h], fill=255)
        lay.putalpha(Image.fromarray(np.minimum(np.asarray(lay.split()[3]), np.asarray(mask))))
        img.alpha_composite(lay)
    # субтитр: слова по одному, перенос по ширине
    shown = [wd for wd, t0 in zip(SUB_WORDS, SUB_T) if tt >= t0]
    if shown:
        f = font("Arimo-Bold.ttf", 40)
        lines, cur = [], ""
        for wd in shown:
            trial = (cur + " " + wd).strip()
            if d.textlength(trial, font=f) > w * 0.62 and cur:
                lines.append(cur); cur = wd
            else:
                cur = trial
        lines.append(cur)
        y = h * 0.720
        for ln in lines:
            shadow_text(d, (w * 0.115, y), ln, f, WHITE, r=2)
            y += h * 0.052
    return img


_TV_CACHE = {}
def tv_frame(tt):
    """кадр эфира целиком: студия + оформление на момент tt"""
    key = round(tt, 3)
    if key in _TV_CACHE: return _TV_CACHE[key]
    img = studio_tex(tt)
    img.alpha_composite(overlay_tex(tt))
    _TV_CACHE.clear(); _TV_CACHE[key] = img
    return img


# ---------- камера ----------
def panel_width(dist, yaw, xoff):
    cam = Cam(xoff, EYE, ZP - dist)
    pts = [cam.proj(p) for p in quad((0.0, EYE, ZP), PANEL_W, PANEL_H, yaw=yaw)]
    xs = [p[0] for p in pts]
    return (max(xs) - min(xs)) / W

def dist_for_width(want, yaw, xoff):
    """дальность камеры, при которой панель занимает долю `want` ширины кадра"""
    lo, hi = 1.0, 16.0
    for _ in range(32):
        mid = (lo + hi) / 2
        if panel_width(mid, yaw, xoff) > want: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def camera(t):
    """(cam, yaw, доля ширины) по времени клипа"""
    if t < T_FLY0:                                   # зал: лёгкий дрейф вперёд
        want = 0.42 + 0.02 * (t / T_FLY0)
        yaw, xoff = YAW0, XOFF0
    elif t < T_FULL:                                 # разворот: ширина 0.44 → 0.57 → 0.85 → 1.02
        k = seg(t, T_FLY0, T_FULL)
        want = float(np.interp(k, [0.0, 0.41, 0.82, 1.0], [0.44, 0.57, 0.85, 1.02]))
        e = 1 - (1 - k) ** 2                         # выпрямление и выход на ось — с торможением
        yaw, xoff = YAW0 * (1 - e), XOFF0 * (1 - e)
    elif t < T_BACK0:                                # экран целиком
        want, yaw, xoff = 1.02, 0.0, 0.0
    elif t < T_BACK1:                                # отъезд: быстро отходим, мягко садимся
        k = out_cubic(seg(t, T_BACK0, T_BACK1))
        want = 1.02 + (0.40 - 1.02) * k
        yaw = YAW1 * k
        xoff = 0.7 * k
    else:                                            # зал: дрейф назад продолжается
        want = 0.40 - 0.015 * seg(t, T_BACK1, 5.0)
        yaw, xoff = YAW1, 0.7
    d = dist_for_width(want, yaw, xoff)
    return Cam(xoff, EYE, ZP - d), yaw, want


_LABEL = None
def hall_label():
    global _LABEL
    if _LABEL is None:
        _LABEL = text_tex(["СКАЗАНО В ЭФИРЕ"], fsize=180, cond=0.82)
    return _LABEL


def g25(t):
    tt = t - T_FULL
    tex = tv_frame(tt)
    cam, yaw, want = camera(t)
    pc = (0.0, EYE, ZP)
    corners = quad(pc, PANEL_W, PANEL_H, yaw=yaw)
    if T_FULL <= t < T_BACK0:
        # экран целиком: панель чуть больше кадра (1.02), зала под ней не видно — его не считаем,
        # а картинку кладём тем же paste_quad, что и в зале, чтобы стык был без скачка
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        paste_quad(img, tex, [cam.proj(p) for p in corners])
        return img
    img = room(cam)
    # тросы к верхним углам
    for fx in (0.10, 0.90):
        px = (fx - 0.5) * PANEL_W
        wire(img, cam, (px * math.cos(yaw), EYE + PANEL_H / 2, ZP + px * math.sin(yaw)),
             color=(92, 94, 98, 230), width=3)
    # надпись над панелью
    lab = hall_label()
    lh = 0.34; lw = lh * lab.size[0] / lab.size[1]
    lc = quad((0.0, EYE + PANEL_H / 2 + 0.45, ZP), lw, lh, yaw=yaw)
    extrude(img, cam, lc, lab, depth=0.06, steps=4)
    # тень на полу, отражение в полу, рамка-корпус, сам экран
    floor_shadow(img, cam, corners, tex)
    reflection(img, cam, corners, tex, strength=0.22)
    body = Image.new("RGBA", (16, 9), (26, 26, 30, 255))
    bc = quad((pc[0] + 0.02 * math.sin(yaw), pc[1], pc[2] + 0.03), PANEL_W * 1.03, PANEL_H * 1.05, yaw=yaw)
    paste_quad(img, body, [cam.proj(p) for p in bc])
    paste_quad(img, tex, [cam.proj(p) for p in corners])
    return img


SCENES = {"G25": (g25, 5.0)}

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
