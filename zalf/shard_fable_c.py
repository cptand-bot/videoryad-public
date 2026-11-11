# -*- coding: utf-8 -*-
"""Белый зал, вторая реализация: G13 (наклейка с перелётом). Запуск: shard_fable_c.py G13 <out>
Один кадр: ZAL_FRAME=0.8 python3 shard_fable_c.py G13 k.png

Снято с плёнки (исходник 13.60-15.90 с, t=0 клипа = 13.60 с):
  · наклейка приходит БЕЗ фейда, сразу целиком: кадр 13.700 пусто, 13.733 — есть;
  · в кадре появления она на ~23% крупнее конечного размера (43% ширины кадра против 35%),
    дальше 1.10 → 1.03 → 1.00: осадка за 3-4 кадра, ~120 мс, хвост выдыхается экспонентой;
  · первый кадр смазан по масштабу (motion blur), со второго — резкая;
  · наклон постоянный: ХАЙП правым концом вверх ≈ +11°, ФЕЙК правым концом вниз ≈ −5°,
    на входе чуть сильнее (ещё ~2°), выравнивается вместе с осадкой;
  · следующие куски: +0.60 с (ФЕЙК, 14.333), +1.10 с (длинное слово, 14.833), +1.57 с (четвёртое, 15.300);
  · по жёлтым пикселям: ХАЙП 0.448 → 0.361 → 0.386 → 0.383 → 0.358 ширины кадра (перелёт 24%, в
    первом кадре смаз, потом лёгкая качка ±5%), ФЕЙК 0.467 → 0.436 → 0.430 → 0.417 → 0.411 → 0.408
    (перелёт 14%, ровная экспонента ~170 мс);
  · камера почти стоит (листы за 0.8 с не растут), едва ползёт вперёд;
  · вокруг — облако белых листов на тросах, ближние размыты глубиной резкости,
    у наклейки мягкая тень на листах позади.
"""
import sys, os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as Z
from zal_core import *

FPS = 30

# ------- текстуры -------
def nakleyka_tex(word, fsize=200, bg=(241, 199, 52, 255), fg=(26, 23, 22, 255)):
    """жёлтый кусок с рваным краем, чёрное слово с лёгкой толщиной"""
    f = font("ArialBlack.ttf", fsize)
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    b = d0.textbbox((0, 0), word, font=f)
    tw, th = b[2] - b[0], b[3] - b[1]
    pw, ph = int(tw + fsize * 0.44), int(th + fsize * 0.42)
    img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(sum(ord(c) for c in word))
    # контур куска: ломаная с мелкими зазубринами по всем четырём сторонам
    pts = []
    n = 14
    for i in range(n + 1):                       # верх
        pts.append((pw * i / n, ph * 0.045 + rng.uniform(-1, 1) * ph * 0.022))
    for i in range(1, 5):                        # правый край
        pts.append((pw - pw * 0.012 + rng.uniform(-1, 1) * pw * 0.008, ph * (0.045 + 0.91 * i / 5)))
    for i in range(n, -1, -1):                   # низ
        pts.append((pw * i / n, ph * 0.955 + rng.uniform(-1, 1) * ph * 0.022))
    for i in range(4, 0, -1):                    # левый край
        pts.append((pw * 0.012 + rng.uniform(-1, 1) * pw * 0.008, ph * (0.045 + 0.91 * i / 5)))
    d.polygon(pts, fill=bg)
    # лёгкая неровность тона бумаги
    shade = Image.new("L", (pw, ph), 0)
    sd = ImageDraw.Draw(shade)
    for k in range(6):
        x0, y0 = rng.uniform(-pw * 0.2, pw), rng.uniform(-ph * 0.3, ph)
        sd.ellipse([x0, y0, x0 + pw * 0.5, y0 + ph * 0.7], fill=int(rng.uniform(14, 30)))
    shade = shade.filter(ImageFilter.GaussianBlur(fsize * 0.25))
    dark = Image.new("RGBA", (pw, ph), (150, 110, 10, 255))
    dark.putalpha(Image.fromarray(np.minimum(np.asarray(shade), np.asarray(img.split()[3])).astype(np.uint8)))
    img.alpha_composite(dark)
    d = ImageDraw.Draw(img)
    x = (pw - tw) / 2 - b[0]; y = (ph - th) / 2 - b[1]
    k = max(2, int(fsize * 0.028))
    d.text((x + k, y + k * 1.4), word, font=f, fill=(78, 70, 52, 255))   # толщина буквы
    d.text((x, y), word, font=f, fill=fg)
    return img

def list_tex(lines, w=640, h=420, fsize=30, footer=None, head=None):
    """белый лист с репликой: две-три строки текста, подпись снизу"""
    img = Image.new("RGBA", (w, h), (251, 251, 250, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(228, 228, 226, 255), width=1)
    fsize = int(fsize * 1.22)                      # Oswald уже Arimo, компенсируем
    y = int(fsize * 0.7)
    if head:
        fh = font("ArialBlack.ttf", int(fsize * 1.25))
        d.text((int(w * 0.06), y), head, font=fh, fill=(28, 28, 30, 255))
        y += int(fsize * 1.8)
        d.line([int(w * 0.06), y, int(w * 0.94), y], fill=(200, 200, 198, 255), width=2)
        y += int(fsize * 0.6)
    f = font("Oswald-Bold.ttf", fsize)
    for ln in lines:
        d.text((int(w * 0.06), y), ln, font=f, fill=(44, 44, 46, 255)); y += int(fsize * 1.22)
    if footer:
        fs = font("Arimo-Bold.ttf", int(fsize * 0.70))
        d.text((int(w * 0.06), h - int(fsize * 1.6)), footer, font=fs, fill=(118, 118, 122, 255))
    return img

# ------- расстановка сцены -------
# листы: (fx, fy, fw, высота/ширина, d, строки, кегль, подпись, заголовок) — доли кадра и дальность
LISTY = [
    (0.18, 0.16, 0.29, 0.50, 7.0, ["Я не спорю с его доводами, но зачем", "писать так, будто завтра конец света?",
                                   "Это подмена фактов эмоцией. И за ней —", "обычная реклама своей конторы."],
     24, "Ответ · 12 ноя 2026", None),
    (0.47, 0.16, 0.30, 0.52, 5.0, ["Читается как типичная заказная", "статья про ИИ. Всерьёз бы", "не брал."],
     36, "Ответ · 11 ноя 2026", None),
    (0.79, 0.14, 0.26, 0.52, 5.5, ["«Что делать: купить платную", "подписку». Вот и весь посыл.", "",
                                   "Страшилка ради продаж."], 30, "Ответ · 9 ноя 2026", None),
    (0.45, 0.46, 0.27, 0.58, 6.0, ["Сравнение с 2020-м уместно: тогда", "тоже все рвали на себе волосы,",
                                   "а потом оказалось — рано. Паника", "прошла, мир остался на месте."], 23,
     "Ответ · 10 ноя 2026", None),
    (0.75, 0.46, 0.37, 0.30, 6.0, ["Как удобно, что апокалипсис наступает именно сейчас,",
                                   "когда инвесторы нервничают. Хорошее совпадение."], 21, None, None),
    (0.18, 0.74, 0.38, 0.46, 4.5, ["ИИ уже читает договоры, пишет справки", "и делает черновую работу не хуже",
                                   "младшего юриста. И в суд его не позовёшь."], 28, "Ответ · 12 ноя 2026", None),
    (0.71, 0.86, 0.42, 0.62, 4.0, ["Нашумевшая колонка о влиянии ИИ на", "офисные профессии строится",
                                   "на спорных допущениях"], 30, "Раздел · ИИ и экономика", "ГАЗЕТА"),
    (0.33, 0.33, 0.18, 0.50, 9.0, ["Это маркетинг.", "Так и называется —", "контент-маркетинг."], 32, None, None),
    (0.62, 0.30, 0.16, 0.45, 10.0, ["Сплошные домыслы,", "ни одной цифры."], 34, None, None),
    (0.90, 0.33, 0.18, 0.45, 8.0, ["Он просто очередной", "продавец страха."], 32, None, None),
    (0.30, 0.56, 0.15, 0.45, 12.0, ["Хватит верить", "каждому посту."], 36, None, None),
    (0.52, 0.72, 0.22, 0.42, 9.0, ["Если он прав — ладно.", "Но пока это пересказ", "чужих прогнозов."], 30, None, None),
    (0.08, 0.46, 0.17, 0.45, 8.0, ["Реклама для своей", "конторы, не больше."], 32, None, None),
    (0.60, 0.60, 0.20, 0.40, 11.0, ["В основном домыслы,", "а не анализ."], 34, None, None),
    (0.10, 0.12, 0.34, 0.46, 1.7, ["Это хайп.", "Перестаньте верить", "такой пропаганде."], 44, "Ответ · 12 ноя", None),
    (0.86, 0.68, 0.30, 0.40, 1.9, ["Он просто разгоняет", "страх ради охватов."], 42, "Ответ · 7 ноя", None),
]

# наклейки: (слово, t_in, fx, fy, fw, крен°, рыскание°)
NAKLEYKI = [
    ("ХАЙП",      0.133, 0.27, 0.27, 0.35,  11.0,  -4.0),
    ("ФЕЙК",      0.733, 0.68, 0.27, 0.37,  -5.0,   7.0),
    ("СТРАШИЛКИ", 1.233, 0.42, 0.53, 0.55,   3.0,  -3.0),
    ("РАЗВОД",    1.700, 0.25, 0.77, 0.31,   6.0,   5.0),
]
D_NAK = 2.6          # дальность наклеек
OVERSHOOT = 0.22     # перелёт по размеру (плёнка: ХАЙП +24% в смазанном кадре, ФЕЙК +14%)
T_OSADKA = 0.30      # окно out_expo: 1.22 → 1.10 → 1.05 → 1.02 → 1.00 по кадрам

_TEX = {}
def _tex(key, fn):
    if key not in _TEX: _TEX[key] = fn()
    return _TEX[key]

def _f2w(fx, fy, fw, d):
    """доля кадра → метры сцены (FOV 52°, камера 1.55)"""
    return ((fx - 0.5) * 0.975 * d, 1.55 + (0.5 - fy) * 0.549 * d, d, fw * 0.975 * d)

def _sheet(img, cam, item):
    fx, fy, fw, asp, d, lines, fs, footer, head = item
    x, y, z, w = _f2w(fx, fy, fw, d)
    tex = _tex(("l", fx, fy), lambda: list_tex(lines, w=640, h=int(640 * asp), fsize=fs, footer=footer, head=head))
    h = w * tex.size[1] / tex.size[0]
    c = quad((x, y, z), w, h, yaw=math.radians((fx - 0.5) * -8))
    dz = z - cam.z
    if dz < 2.6:                                   # близко — вне глубины резкости
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        wire(lay, cam, (x - w * 0.4, y + h / 2, z)); wire(lay, cam, (x + w * 0.4, y + h / 2, z))
        paste_quad(lay, tex, [cam.proj(p) for p in c])
        lay = lay.filter(ImageFilter.GaussianBlur((2.6 - dz) * 5 + 2))
        img.alpha_composite(lay)
    else:
        wire(img, cam, (x - w * 0.4, y + h / 2, z)); wire(img, cam, (x + w * 0.4, y + h / 2, z))
        paste_quad(img, tex, [cam.proj(p) for p in c])

def _nakleyka(img, cam, item, t):
    word, t_in, fx, fy, fw, roll, yaw = item
    dt = t - t_in
    if dt < 0: return
    x, y, z, w = _f2w(fx, fy, fw, D_NAK)
    tex = _tex(("n", word), lambda: nakleyka_tex(word))
    k = 1.0 - out_expo(dt / T_OSADKA)             # 1 на входе → 0 после осадки
    s = 1.0 + OVERSHOOT * k
    r = math.radians(roll + 2.0 * k * (1 if roll >= 0 else -1))
    yw = math.radians(yaw)
    h = w * tex.size[1] / tex.size[0]
    # тень на том, что позади: сдвинута вниз-вправо и чуть дальше
    dark = _tex(("sh", word), lambda: _shadow_tex(tex))
    csh = quad((x + 0.05 * s, y - 0.07 * s, z + 0.12), w * s, h * s, yaw=yw, roll=r)
    paste_quad(img, dark, [cam.proj(p) for p in csh], opacity=0.55 + 0.25 * k)
    # сама наклейка; в первых двух кадрах — смаз по масштабу (три копии, от крупной к точной)
    if dt < 0.07:
        for ss, op in ((s * 1.12, 0.22), (s * 1.06, 0.30)):
            c = quad((x, y, z), w * ss, h * ss, yaw=yw, roll=r)
            paste_quad(img, tex, [cam.proj(p) for p in c], opacity=op)
    c = quad((x, y, z), w * s, h * s, yaw=yw, roll=r)
    paste_quad(img, tex, [cam.proj(p) for p in c])

def _shadow_tex(tex):
    pad = 24
    a = Image.new("L", (tex.size[0] + 2 * pad, tex.size[1] + 2 * pad), 0)
    a.paste(tex.split()[3].point(lambda v: int(v * 0.42)), (pad, pad))
    dark = Image.new("RGBA", a.size, (30, 28, 24, 255))
    dark.putalpha(a)
    return dark.filter(ImageFilter.GaussianBlur(10))

def g13(t):
    cam = Cam(0.0, 1.55, 0.06 * t, 0.0)
    img = room(cam, windows=True, shafts=True, ropes=True)
    # листы: от дальних к ближним, ближние размыты
    far = [it for it in LISTY if it[4] >= 2.6]
    near = [it for it in LISTY if it[4] < 2.6]
    for it in sorted(far, key=lambda q: -q[4]):
        _sheet(img, cam, it)
    for it in NAKLEYKI:
        _nakleyka(img, cam, it, t)
    for it in sorted(near, key=lambda q: -q[4]):
        _sheet(img, cam, it)
    source_line(img, "Реальные ответы · ноябрь 2026 · имена убраны")
    return img

SCENES = {"G13": (g13, 3.3)}

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
