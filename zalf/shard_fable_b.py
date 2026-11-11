# -*- coding: utf-8 -*-
"""Белый зал, вторая реализация (часть B: G11, G15, G26).
Запуск: shard_fable_b.py <код> <out.mp4>  ·  один кадр: ZAL_FRAME=1.9 shard_fable_b.py G11 k.png

Все числа сняты с плёнки исходника (polosy/G11_a,b, G11_kub30, G15_stolb,
G26_vhod + сетки G11b/G15b/G26b), перевод доли кадра в метры:
X = (fx-0.5)*0.975*d, Y = 1.55 + (0.5-fy)*0.549*d.
"""
import sys, os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as Z
from zal_core import *

FPS = 30
COND = 0.80          # ArialBlack, сжатый по ширине — ближе всего к узкому гротеску образца
INK = (16, 16, 18, 255)
YEL = (255, 208, 0, 255)


def in_pow(t, p=2.2):
    """разгон: медленно трогается, быстро уходит"""
    return clamp01(t) ** p

def out_quad(t):
    t = clamp01(t); return 1 - (1 - t) * (1 - t)


# ---------- блок слов, набирающийся по одному, с опусканием слова на место ----------
def word_block(lines, t, fsize=200, drop=0.10, align="left"):
    """lines: список строк, строка — список (слово, t_появления, жёлтый?).
    Возвращает RGBA-текстуру (сжатую COND по ширине) и высоту прописной в px,
    либо (None, 0), если ещё ни одного слова нет. Слово приходит целиком и за
    `drop` секунд опускается на место с высоты 0.45 строки (на плёнке 74.167
    «WANTED», 36.267 «CUTS», 77.267 «THEY» стоят выше строки первые 2-3 кадра)."""
    f = font("ArialBlack.ttf", fsize)
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sp = d0.textlength(" ", font=f)
    hline = fsize * 1.05
    pad = int(fsize * 0.5)
    rows = []
    for ln in lines:
        ws = [(w, d0.textbbox((0, 0), w, font=f)) for (w, t0, hl) in ln]
        width = sum(b[2] - b[0] for _, b in ws) + sp * (len(ws) - 1)
        rows.append((ln, ws, width))
    total_w = int(max(r[2] for r in rows) + pad * 2)
    total_h = int(len(rows) * hline + pad * 2)
    img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    any_word = False
    y = pad
    for ln, ws, width in rows:
        x = pad if align == "left" else (total_w - width) / 2
        for (w, t0, hl), (_, b) in zip(ln, ws):
            ww = b[2] - b[0]
            if t >= t0:
                any_word = True
                k = seg(t, t0, t0 + drop)
                dy = -0.45 * hline * (1 - out_cubic(k))
                if hl:
                    d.rectangle([x - fsize * 0.06, y + dy + fsize * 0.05,
                                 x + ww + fsize * 0.06, y + dy + fsize * 0.98], fill=YEL)
                d.text((x - b[0], y + dy - b[1] + fsize * 0.16), w, font=f, fill=INK)
            x += ww + sp
        y += hline
    if not any_word:
        return None, 0
    img = img.resize((max(4, int(total_w * COND)), total_h), Image.LANCZOS)
    return img, fsize * 0.72

HEAD = 0.66 / 0.72   # отступ от верха текстуры до верха букв, в прописных (pad 0.5 + 0.16)

def place_block(img, cam, tex, cap_px, cap_m, left, top, z, yaw=0.0, depth=0.06,
                wires=2, rise=0.0, blur_steps=0):
    """вешает текстуру в зал: left — левый край текстуры, top — верх БУКВ первой строки,
    масштаб по прописной. rise — подъём (уезжание вверх), blur_steps — шлейф при быстром ходе."""
    if tex is None: return
    k = cap_m / cap_px
    w, h = tex.size[0] * k, tex.size[1] * k
    cx, cy = left + w / 2, top + HEAD * cap_m - h / 2 + rise
    cq = quad((cx, cy, z), w, h, yaw=yaw)
    if blur_steps > 0 and rise > 0:
        ghost = tex.copy()
        ghost.putalpha(tex.split()[3].point(lambda v: int(v * 0.22)))
        for i in range(blur_steps, 0, -1):
            dy = -rise * 0.45 * i / blur_steps
            paste_quad(img, ghost, [cam.proj((p[0], p[1] + dy, p[2])) for p in cq])
    if wires:
        for fx in (0.10, 0.90):
            ux = (fx - 0.5) * w
            wire(img, cam, (cx + ux * math.cos(yaw), cy + h / 2, z + ux * math.sin(yaw)))
    extrude(img, cam, cq, tex, depth=depth, steps=4)


# ---------- белый постамент на полу ----------
def pedestal(img, cam, x, z, size=2.6, h=0.06):
    s = size / 2
    sh = [cam.proj(p) for p in ((x - s - .25, 0, z - s - .1), (x + s + .25, 0, z - s - .1),
                                (x + s + .35, 0, z + s + .5), (x - s - .35, 0, z + s + .5))]
    shl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shl).polygon([(p[0], p[1]) for p in sh], fill=(60, 62, 66, 70))
    img.alpha_composite(shl.filter(ImageFilter.GaussianBlur(18)))
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    top = [cam.proj(p) for p in ((x - s, h, z - s), (x + s, h, z - s), (x + s, h, z + s), (x - s, h, z + s))]
    front = [cam.proj(p) for p in ((x - s, h, z - s), (x + s, h, z - s), (x + s, 0, z - s), (x - s, 0, z - s))]
    d.polygon([(p[0], p[1]) for p in front], fill=(214, 216, 219, 255))
    d.polygon([(p[0], p[1]) for p in top], fill=(248, 248, 247, 255))
    img.alpha_composite(lay)


# =====================================================================
# G11 · фраза набирается по словам и уезжает вверх, с потолка на тросах
#       спускается стеклянный куб (исходник 73.5-77.9, 1:1)
# =====================================================================
G11_LINES = [[("OPENAI", 0.067, 0), ("WANTED", 0.667, 0), ("TO", 1.000, 0), ("SEE", 1.000, 0)],
             [("JUST", 1.667, 0), ("HOW", 1.867, 0), ("SMART", 2.000, 1)],
             [("SOME", 2.333, 0), ("OF", 2.567, 0), ("ITS", 2.633, 0), ("AIs", 2.767, 0), ("WERE.", 3.233, 0)]]
G11_LINES2 = [[("SO", 3.700, 0), ("THEY", 3.767, 0), ("SEALED", 3.933, 1), ("THEM", 4.300, 0)]]
G11_EXIT = 3.40      # 76.9: блок трогается вверх, 77.133 его нет
G11_CUBE = 3.633     # 77.133: низ куба показывается у верхней кромки кадра
G11_CUBE_DUR = 0.27  # 77.4: сел; падение с разгоном (низ по плёнке: 2.86 → 2.24 → 1.72 → 1.38 → 0.51 → 0.05), без торможения

def g11(t):
    cam = Cam(0.0, 1.55, -0.08 * t)   # камера чуть отплывает назад: угли и текст сходятся к центру
    img = room(cam)
    zc = 7.0                     # куб и постамент: передняя грань на d≈6.2 в 77.47
    pedestal(img, cam, 0.0, zc, size=2.4)
    # первый блок: прописная 8% кадра при d≈7.1 → 0.32 м; левый край fx 0.13 → X=-2.55; верх букв fy 0.14 → Y=2.95
    tex, cap = word_block(G11_LINES, t, fsize=200)
    if tex is not None and t < G11_EXIT + 0.3:
        k = seg(t, G11_EXIT, G11_EXIT + 0.23)
        rise = 4.2 * in_pow(k, 2.0)
        place_block(img, cam, tex, cap, 0.32, -2.55, 2.95, 7.0, rise=rise,
                    blur_steps=4 if k > 0 else 0)
    # второй блок: одна строка, прописная 6.5% при d 6.8 → 0.24 м, левый край fx 0.19 → X=-2.05, верх fy 0.11 → Y=3.0
    tex2, cap2 = word_block(G11_LINES2, t, fsize=200)
    if tex2 is not None:
        place_block(img, cam, tex2, cap2, 0.243, -2.05, 3.0, 6.5)
    # угли на постаменте: тесная горстка из трёх с отражением в плите, ореол ~0.1 кадра
    pts = []
    for (ex, ey, ez, es) in ((-0.26, 0.30, zc - 0.25, 0.62), (0.0, 0.42, zc - 0.35, 0.55), (0.26, 0.34, zc - 0.15, 0.48)):
        pts.append((ex, ey, ez, es))
    img = embers(img, cam, pts, t, glow=1.0)
    # стеклянный куб 2.1 м: падает с потолка, низ от 3.35 м до 0.06 за 0.27 с
    if t >= G11_CUBE:
        k = in_pow(seg(t, G11_CUBE, G11_CUBE + G11_CUBE_DUR), 1.3)
        size = 2.1
        bottom = 3.35 - (3.35 - 0.06) * k
        settle = seg(t, G11_CUBE + G11_CUBE_DUR, G11_CUBE + G11_CUBE_DUR + 0.1)
        bottom -= 0.02 * math.sin(settle * math.pi)      # просадка на 2 см и возврат
        glass_cube(img, cam, (0.0, bottom + size / 2, zc), size, t, wires=True)
    return img


# =====================================================================
# G15 · столбик из жёлтых плит растёт из пола, тёмная плашка на тросах
#       едет вверх рядом, число добегает (исходник 35.0-37.7 → t=0..2.7, дальше держим)
# =====================================================================
G15_T0 = 0.267          # 35.267: плашка с «0» и слово AND
G15_GO = 0.300          # 35.3: пошёл счёт и первая плита
G15_DUR = 2.37          # 37.667: 116 175 и столб встал; кривая outQuad (0.26 на 0.33 с, 0.50 на 0.73 с, 0.76 на 1.23 с)
G15_FINAL = 116175
G15_H = 2.43            # высота столба: верх fy 0.33 при d=9.4
G15_X, G15_Z = 0.46, 9.4
G15_SLAB = 0.92         # плита ~0.9 м в плане
G15_LINES_A = [[("AND", 0.267, 0), ("THIS", 0.300, 0), ("YEAR,", 0.567, 0)]]
G15_LINES_B = [[("JOB", 1.067, 0), ("CUTS", 1.267, 0), ("BLAMED", 1.733, 0), ("ON", 1.933, 0), ("AI", 2.133, 1)]]
G15_SWAP = 0.95         # 35.95-36.03: первая строка уезжает вверх, 36.067 приходит JOB

_rng15 = np.random.default_rng(15)
_SLABS = []
_s = 0.0
while _s < G15_H - 0.02:
    th = min(float(_rng15.uniform(0.12, 0.22)), G15_H - _s)
    _SLABS.append((_s, th, float(_rng15.uniform(-0.035, 0.035)), float(_rng15.uniform(-0.035, 0.035)),
                   float(_rng15.uniform(-2.5, 2.5)) * math.pi / 180))
    _s += th

def _box_faces(cam, cx, cy0, cz, w, th, yaw):
    """грани плиты: крышка/дно, бок, фронт — в порядке рисования"""
    c, s = math.cos(yaw), math.sin(yaw)
    def P(ux, uz, y):
        return (cx + ux * c - uz * s, y, cz + ux * s + uz * c)
    h = w / 2
    y1 = cy0 + th
    corners = {"fbl": P(-h, -h, cy0), "fbr": P(h, -h, cy0), "ftl": P(-h, -h, y1), "ftr": P(h, -h, y1),
               "bbl": P(-h, h, cy0), "bbr": P(h, h, cy0), "btl": P(-h, h, y1), "btr": P(h, h, y1)}
    pr = {k: cam.proj(v) for k, v in corners.items()}
    faces = []
    if cam.y > y1:      # смотрим сверху — крышка
        faces.append(([pr["btl"], pr["btr"], pr["ftr"], pr["ftl"]], (248, 203, 64, 255)))
    elif cam.y < cy0:   # снизу — дно
        faces.append(([pr["bbl"], pr["bbr"], pr["fbr"], pr["fbl"]], (170, 125, 24, 255)))
    if cam.x > corners["fbr"][0]:
        faces.append(([pr["ftr"], pr["btr"], pr["bbr"], pr["fbr"]], (196, 148, 30, 255)))
    else:
        faces.append(([pr["btl"], pr["ftl"], pr["fbl"], pr["bbl"]], (196, 148, 30, 255)))
    faces.append(([pr["ftl"], pr["ftr"], pr["fbr"], pr["fbl"]], (229, 178, 42, 255)))
    return faces

def stack_h(t):
    return G15_H * out_quad(seg(t, G15_GO, G15_GO + G15_DUR))

def slab_stack(img, cam, t):
    h = stack_h(t)
    shl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s = G15_SLAB * 0.75
    sh = [cam.proj(p) for p in ((G15_X - s, 0, G15_Z - s), (G15_X + s, 0, G15_Z - s),
                                (G15_X + s * 1.3, 0, G15_Z + s * 1.6), (G15_X - s * 1.3, 0, G15_Z + s * 1.6))]
    ImageDraw.Draw(shl).polygon([(p[0], p[1]) for p in sh], fill=(50, 50, 54, int(90 * clamp01(h / 0.3))))
    img.alpha_composite(shl.filter(ImageFilter.GaussianBlur(16)))
    items = []
    for (y0, th, dx, dz, yw) in _SLABS:
        if h < y0 + 0.001: break
        # в полёте ровно одна плита: падает с 0.55 м, пока столб дорастает до её крышки (35.633, 36.0 на плёнке)
        drop = 0.55 * (1 - clamp01((h - y0) / th))
        items.append((y0 + drop, th, dx, dz, yw))
    items.sort(key=lambda it: -abs((it[0] + it[1] / 2) - cam.y))   # дальше от уровня глаз — раньше
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for (y0, th, dx, dz, yw) in items:
        for pts, col in _box_faces(cam, G15_X + dx, y0, G15_Z + dz, G15_SLAB, th, yw):
            d.polygon([(p[0], p[1]) for p in pts], fill=col)
    img.alpha_composite(lay)
    return h


def counter_tex(value, frac, w=1040, h=470):
    """тёмная плашка: мелкая белая строка сверху, крупные жёлтые цифры;
    пока число бежит — у цифр вертикальный шлейф, как у табло"""
    img = Image.new("RGBA", (w, h), (66, 58, 48, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, w - 11, h - 11], fill=(26, 23, 20, 255))
    d.rectangle([0, 0, w - 1, h - 1], outline=(92, 82, 68, 255), width=3)
    fs = font("Oswald-Bold.ttf", int(h * 0.27))
    sub = "2026 · JAN–AUG"
    b = d.textbbox((0, 0), sub, font=fs)
    d.text(((w - (b[2] - b[0])) / 2 - b[0], h * 0.09 - b[1]), sub, font=fs, fill=(240, 238, 232, 255))
    fd = font("Oswald-Bold.ttf", int(h * 0.50))
    txt = f"{int(value):,}"
    b = d.textbbox((0, 0), txt, font=fd)
    x = (w - (b[2] - b[0])) / 2 - b[0]
    y = h * 0.42 - b[1]
    if frac < 1.0:
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        for i in range(-3, 4):
            ld.text((x, y + i * h * 0.035), txt, font=fd, fill=(250, 196, 40, 70))
        img.alpha_composite(lay)
        d.text((x, y), txt, font=fd, fill=(250, 196, 40, 190))
    else:
        d.text((x, y), txt, font=fd, fill=(250, 196, 40, 255))
    return img

def g15(t):
    cam = Cam(0.0, 1.55, 0.12 * t)
    img = room(cam)
    h = slab_stack(img, cam, t) if t >= G15_T0 else 0.0
    # плашка 1.83×0.83 м, левый край fx 0.63 → X=1.2 при d 9.4; низ = max(0.26, верх столба − 1.03)
    if t >= G15_T0:
        k = seg(t, G15_GO, G15_GO + G15_DUR)
        tex = counter_tex(G15_FINAL * out_quad(k), k)
        pw, ph = 1.83, 0.83
        bottom = max(0.26, h - 1.03) + 0.35 * (1 - out_cubic(seg(t, G15_T0, G15_T0 + 0.10)))
        cx, cy, cz = 1.2 + pw / 2, bottom + ph / 2, G15_Z - 0.1
        wire(img, cam, (cx - pw * 0.42, cy + ph / 2, cz))
        wire(img, cam, (cx + pw * 0.42, cy + ph / 2, cz))
        extrude(img, cam, quad((cx, cy, cz), pw, ph), tex, depth=0.10, steps=4, shade=(40, 36, 30))
    # строка-фраза вверху по центру: прописная 8% при d 8 → 0.35 м, верх букв fy 0.14 → Y≈3.13
    z_txt, cap_m = 8.0, 0.35
    texA, capA = word_block(G15_LINES_A, t, fsize=200, align="center")
    if texA is not None and t < G15_SWAP + 0.15:
        k = seg(t, G15_SWAP, G15_SWAP + 0.12)
        rise = 2.5 * in_pow(k, 1.8)
        wtx = texA.size[0] * (cap_m / capA)
        place_block(img, cam, texA, capA, cap_m, -wtx / 2, 3.13, z_txt, rise=rise, blur_steps=3 if k > 0 else 0)
    texB, capB = word_block(G15_LINES_B, t, fsize=200, align="center")
    if texB is not None:
        wtx = texB.size[0] * (cap_m / capB)
        place_block(img, cam, texB, capB, cap_m, -wtx / 2, 3.13, z_txt)
    if t >= 0.567:
        source_line(img, "Challenger, Gray & Christmas · 2026")
    return img


# =====================================================================
# G26 · панель эфира подлетает и заполняет кадр, справа столбиком
#       копится расшифровка (исходник 181.0-187.4, 1:1)
# =====================================================================
PANEL_W, PANEL_H = 3.2, 1.8
G26_FILL = 0.73        # 181.733: панель закрыла кадр
_PANEL = None

def panel_tex(w=1920, h=1080):
    """своя студия: синий задник с водяным узором, деревянная стена и световые
    планки слева, ведущий плоским силуэтом, нижняя плашка латиницей"""
    global _PANEL
    if _PANEL is not None: return _PANEL
    img = Image.new("RGBA", (w, h), (38, 30, 110, 255))
    d = ImageDraw.Draw(img)
    for i in range(h):
        k = i / h
        d.line([(0, i), (w, i)], fill=(int(40 + 18 * k), int(30 + 14 * k), int(112 + 34 * k), 255))
    gl = Image.new("RGBA", (w, h), (0, 0, 0, 0)); gd = ImageDraw.Draw(gl)
    gf = font("ArialBlack.ttf", int(h * 0.11))
    for r in range(5):
        for c in range(4):
            gd.text((w * (0.12 + c * 0.27) - r * 60, h * (-0.05 + r * 0.24)), "MORNINGS", font=gf,
                    fill=(255, 255, 255, 13))
    img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(1.5)))
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
    ld.rectangle([0, 0, w * 0.075, h], fill=(118, 78, 44, 255))
    ld.rectangle([w * 0.075, 0, w * 0.10, h], fill=(248, 244, 236, 255))
    ld.rectangle([w * 0.10, 0, w * 0.125, h], fill=(120, 86, 52, 255))
    ld.rectangle([w * 0.125, 0, w * 0.15, h], fill=(238, 236, 232, 255))
    ld.rectangle([w * 0.15, 0, w * 0.20, h], fill=(96, 92, 150, 255))
    ld.rectangle([w * 0.20, 0, w * 0.215, h], fill=(170, 190, 240, 255))
    img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(2)))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    gd.rectangle([w * 0.07, 0, w * 0.23, h], fill=(220, 225, 255, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(40)))
    # ведущий: плоский силуэт с лёгкой тенью
    fig = Image.new("RGBA", (w, h), (0, 0, 0, 0)); fd = ImageDraw.Draw(fig)
    cx = w * 0.43
    fd.polygon([(cx - w * 0.19, h * 1.02), (cx - w * 0.16, h * 0.66), (cx - w * 0.05, h * 0.56),
                (cx + w * 0.05, h * 0.56), (cx + w * 0.17, h * 0.66), (cx + w * 0.20, h * 1.02)],
               fill=(28, 28, 36, 255))
    fd.polygon([(cx - w * 0.045, h * 0.56), (cx + w * 0.045, h * 0.56), (cx, h * 0.72)], fill=(236, 236, 240, 255))
    fd.rectangle([cx - w * 0.028, h * 0.46, cx + w * 0.028, h * 0.60], fill=(214, 172, 146, 255))
    fd.ellipse([cx - w * 0.058, h * 0.19, cx + w * 0.058, h * 0.50], fill=(226, 186, 160, 255))
    fd.chord([cx - w * 0.063, h * 0.16, cx + w * 0.063, h * 0.38], 180, 360, fill=(58, 40, 30, 255))
    fd.rectangle([cx - w * 0.063, h * 0.26, cx - w * 0.045, h * 0.34], fill=(58, 40, 30, 255))
    fd.rectangle([cx + w * 0.045, h * 0.26, cx + w * 0.063, h * 0.34], fill=(58, 40, 30, 255))
    for sx in (-1, 1):
        fd.ellipse([cx + sx * w * 0.031 - w * 0.022, h * 0.31, cx + sx * w * 0.031 + w * 0.022, h * 0.365],
                   outline=(30, 28, 30, 255), width=4)
    fd.line([(cx - w * 0.009, h * 0.335), (cx + w * 0.009, h * 0.335)], fill=(30, 28, 30, 255), width=3)
    fd.line([(cx - w * 0.016, h * 0.44), (cx + w * 0.016, h * 0.44)], fill=(150, 90, 80, 255), width=4)
    sh = fig.filter(ImageFilter.GaussianBlur(28))
    dark = Image.new("RGBA", (w, h), (10, 8, 40, 255)); dark.putalpha(sh.split()[3].point(lambda v: int(v * 0.5)))
    img.alpha_composite(dark, (int(w * 0.012), int(h * 0.01)))
    img.alpha_composite(fig)
    _PANEL = (img, lower_third_tex(w, h))
    return _PANEL

def lower_third_tex(w=1920, h=1080):
    """нижняя плашка отдельным прозрачным слоем: после заполнения кадра картинка
    ещё наезжает, а плашка стоит на месте (181.73 → 182.5 на плёнке)"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, h * 0.785, w * 0.215, h * 0.845], fill=(96, 52, 178, 255))
    d.text((w * 0.028, h * 0.793), "TECH WATCH", font=font("Oswald-Bold.ttf", int(h * 0.046)),
           fill=(255, 255, 255, 255))
    d.polygon([(0, h * 0.955), (w * 0.985, h * 0.955), (w * 0.985, h * 0.968), (0, h * 0.968)],
              fill=(96, 52, 178, 255))
    d.polygon([(0, h * 0.855), (w * 0.985, h * 0.855), (w, h * 0.905), (w * 0.985, h * 0.955),
               (0, h * 0.955)], fill=(246, 247, 250, 255))
    fb = font("ArialBlack.ttf", int(h * 0.040))
    d.ellipse([w * 0.024, h * 0.887, w * 0.024 + h * 0.036, h * 0.887 + h * 0.036], fill=(26, 26, 30, 255))
    d.text((w * 0.052, h * 0.874), "MORNINGS", font=fb, fill=(26, 26, 30, 255))
    d.line([(w * 0.255, h * 0.87), (w * 0.255, h * 0.945)], fill=(120, 122, 130, 255), width=3)
    d.text((w * 0.272, h * 0.869), "AUTHOR OF VIRAL ARTICLE ON A.I. PREDICTIONS",
           font=font("Oswald-Bold.ttf", int(h * 0.052)), fill=(26, 26, 30, 255))
    return img


G26_WORDS_1 = [("by", 1.733), ("the", 2.000), ("end", 2.133), ("of", 2.200), ("this", 2.333), ("year", 2.467),
               ("or", 2.733), ("the", 3.133), ("end", 3.200), ("of", 3.267), ("next", 3.400), ("year,", 3.533)]
G26_WORDS_2 = [("it", 4.267), ("is", 4.267), ("extremely", 4.333), ("likely", 4.800), ("that", 5.200),
               ("AI", 5.467), ("will", 5.667), ("be", 6.000), ("able", 6.133), ("to", 6.267)]
G26_CLEAR = 4.20
G26_HEAD = 1.667

def _shadow_text(d, xy, txt, f, fill, shadow=(0, 0, 0, 150), r=2):
    x, y = xy
    for dx, dy in ((r, r), (-r, r), (r, -r), (-r, -r), (0, r + 1), (0, -r)):
        d.text((x + dx, y + dy), txt, font=f, fill=shadow)
    d.text((x, y), txt, font=f, fill=fill)

def transcript(img, t):
    """правый столбик поверх панели: жёлтая вертикаль, шапка, слова копятся и переносятся"""
    if t < G26_HEAD: return
    d = ImageDraw.Draw(img, "RGBA")
    x0, col_w = W * 0.604, W * 0.26   # 499 px: «or the end of next year,» (481) влезает, «…this year or» (525) переносится
    d.rectangle([W * 0.584, H * 0.051, W * 0.584 + 10, H * 0.185], fill=(255, 208, 0, 255))
    fn = font("Oswald-Bold.ttf", 56); b = d.textbbox((0, 0), "ALEX CARTER", font=fn)
    _shadow_text(d, (x0, H * 0.067 - b[1]), "ALEX CARTER", fn, (255, 255, 255, 255))
    fs = font("Oswald-Bold.ttf", 50); b = d.textbbox((0, 0), "Morning News", font=fs)
    _shadow_text(d, (x0, H * 0.139 - b[1]), "Morning News · Feb 17, 2026", fs, (236, 236, 242, 255))
    words = G26_WORDS_2 if t >= G26_CLEAR else G26_WORDS_1
    shown = [w for w, tw in words if t >= tw]
    if not shown: return
    f = font("Oswald-Bold.ttf", 58)   # шрифт образца шире Oswald: кегль чуть больше, колонка уже, чтобы перенос совпал
    lines, cur = [], ""
    for w in shown:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=f) > col_w and cur:
            lines.append(cur); cur = w
        else:
            cur = trial
    lines.append(cur)
    b = d.textbbox((0, 0), "b", font=f)
    y = H * 0.240 - b[1]
    for ln in lines:
        _shadow_text(d, (x0, y), ln, f, (255, 255, 255, 255))
        y += H * 0.088

def on_national(img, t):
    """«ON NATIONAL TV.» в правом верхнем углу панели, 181.867-182.6"""
    if not (0.867 <= t < 1.667): return
    d = ImageDraw.Draw(img, "RGBA")
    f = font("Oswald-Bold.ttf", 66)
    x, y = W * 0.70, H * 0.045 - d.textbbox((0, 0), "O", font=f)[1]
    _shadow_text(d, (x, y), "ON", f, (255, 255, 255, 255), r=3)
    _shadow_text(d, (x + d.textlength("ON ", font=f), y), "NATIONAL", f, YEL, r=3)
    if t >= 0.933:
        _shadow_text(d, (x, y + H * 0.072), "TV.", f, YEL, r=3)

def panel_width(dist, yaw, xoff, zp):
    cam = Cam(xoff, 1.55, zp - dist)
    pts = [cam.proj(p) for p in quad((0.0, 1.55, zp), PANEL_W, PANEL_H, yaw=yaw)]
    xs = [p[0] for p in pts]
    return (max(xs) - min(xs)) / W

def dist_for_width(want, yaw, xoff, zp):
    """дальность камеры, при которой панель занимает `want` ширины кадра (деление отрезка)"""
    lo, hi = 1.5, 14.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if panel_width(mid, yaw, xoff, zp) > want: lo = mid
        else: hi = mid
    return (lo + hi) / 2

_G26_TEX = None
def g26(t):
    global _G26_TEX
    back, lower = panel_tex()
    if _G26_TEX is None:
        _G26_TEX = back.copy(); _G26_TEX.alpha_composite(lower)
    tex = _G26_TEX
    zp = 8.0
    pc = (0.0, 1.55, zp)
    if t < G26_FILL:
        # панель висит с yaw 18° (правый край дальше), левее центра; камера летит к ней почти равномерно:
        # ширина на экране 0.44 → 0.57 → 0.85 → 1.0 за 0.73 с (d: 7.5 → 5.8 → 3.9 → 3.28)
        k = seg(t, 0.0, G26_FILL)
        yaw = math.radians(18) * (1 - out_quad(k))
        xoff = 1.0 * (1 - out_quad(k))
        want = np.interp(t, [0.0, 0.3, 0.6, G26_FILL], [0.44, 0.57, 0.85, 1.02])
        dist = dist_for_width(want, yaw, xoff, zp)
        cam = Cam(xoff, 1.55, zp - dist)
        img = room(cam)
        for fx in (0.08, 0.92):
            px = (fx - 0.5) * PANEL_W
            wire(img, cam, (px * math.cos(yaw), pc[1] + PANEL_H / 2, zp + px * math.sin(yaw)), width=2)
        # надписи в зале: «I SAID THIS» над панелью, «ON NATIONAL» под ней (NATIONAL приходит в 181.1)
        tA, cA = word_block([[("I", 0, 0), ("SAID", 0, 0), ("THIS", 0, 0)]], 1.0, fsize=200, align="center")
        wa = tA.size[0] * (0.24 / cA)
        place_block(img, cam, tA, cA, 0.24, -wa / 2, pc[1] + PANEL_H / 2 + 0.55, zp, yaw=yaw, wires=0)
        tB, cB = word_block([[("ON", 0, 0), ("NATIONAL", 0.10, 0)]], t, fsize=200, align="center")
        wb = tB.size[0] * (0.24 / cB)
        place_block(img, cam, tB, cB, 0.24, -wb / 2, pc[1] - PANEL_H / 2 - 0.22, zp, yaw=yaw, wires=0)
        fr = Image.new("RGBA", (16, 9), (24, 24, 28, 255))
        paste_quad(img, fr, [cam.proj(p) for p in quad(pc, PANEL_W * 1.025, PANEL_H * 1.04, yaw=yaw)])
        paste_quad(img, tex, [cam.proj(p) for p in quad(pc, PANEL_W, PANEL_H, yaw=yaw)])
    else:
        # зала больше нет: картинка ещё наезжает на 10% за 0.8 с (центр у головы), плашка стоит
        z = 1.0 + 0.10 * out_cubic(seg(t, G26_FILL, G26_FILL + 0.8))
        tw, th = int(W * z), int(H * z)
        big = back.resize((tw, th), Image.BILINEAR)
        img = Image.new("RGBA", (W, H), (20, 18, 40, 255))
        img.alpha_composite(big, (-int((tw - W) * 0.45), -int((th - H) * 0.40)))
        img.alpha_composite(lower)
    on_national(img, t)
    transcript(img, t)
    return img


SCENES = {"G11": (g11, 4.4), "G15": (g15, 5.0), "G26": (g26, 6.4)}

def render(code, out):
    fn, dur = SCENES[code]
    n = int(dur * FPS)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = "ffmpeg"
    p = subprocess.Popen([exe, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
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
