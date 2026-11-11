# -*- coding: utf-8 -*-
"""Белый зал: псевдо-3D сцена на numpy+PIL.
Камера смотрит вдоль +z, пол y=0, потолок y=CEIL, стены x=±WALL.
Всё, что кладём в кадр, — четырёхугольник в пространстве: проецируем углы и
натягиваем на них картинку перспективным преобразованием.
"""
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FOV = 52.0
F = (W / 2) / math.tan(math.radians(FOV / 2))
CEIL, WALL, FAR = 5.0, 6.2, 70.0

FONTDIR = os.environ.get("ZAL_FONTS", os.path.join(os.path.dirname(__file__), "fonts"))
def font(name, size):
    p = os.path.join(FONTDIR, name)
    return ImageFont.truetype(p, size)

# ---------- ход движения ----------
def clamp01(x): return 0.0 if x < 0 else (1.0 if x > 1 else x)
def out_expo(t):
    t = clamp01(t); return 1.0 if t >= 1 else 1 - pow(2, -10 * t)
def out_back(t, s=1.70158):
    t = clamp01(t) - 1.0
    return t * t * ((s + 1) * t + s) + 1.0
def out_cubic(t): t = clamp01(t); return 1 - pow(1 - t, 3)
def seg(t, a, b): return clamp01((t - a) / max(1e-6, b - a))

# ---------- камера ----------
class Cam:
    def __init__(s, x=0.0, y=1.55, z=0.0, yaw=0.0):
        s.x, s.y, s.z, s.yaw = x, y, z, yaw
    def proj(s, p):
        dx, dy, dz = p[0] - s.x, p[1] - s.y, p[2] - s.z
        if s.yaw:
            c, si = math.cos(-s.yaw), math.sin(-s.yaw)
            dx, dz = dx * c - dz * si, dx * si + dz * c
        if dz < 0.08: dz = 0.08
        k = F / dz
        return (W / 2 + dx * k, H / 2 - dy * k, dz)

def quad(center, w, h, yaw=0.0, roll=0.0):
    """углы прямоугольника в пространстве: TL,TR,BR,BL"""
    cx, cy, cz = center
    pts = [(-w/2, h/2), (w/2, h/2), (w/2, -h/2), (-w/2, -h/2)]
    out = []
    cr, sr = math.cos(roll), math.sin(roll)
    cy_, sy_ = math.cos(yaw), math.sin(yaw)
    for ux, uy in pts:
        rx, ry = ux * cr - uy * sr, ux * sr + uy * cr
        out.append((cx + rx * cy_, cy + ry, cz + rx * sy_))
    return out

# ---------- натягивание картинки на четырёхугольник ----------
def _coeffs(dst, src):
    m = []
    for (dx, dy), (sx, sy) in zip(dst, src):
        m.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        m.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
    A = np.array(m, dtype=np.float64)
    B = np.array(src, dtype=np.float64).reshape(8)
    res, *_ = np.linalg.lstsq(A, B, rcond=None)
    return res

def paste_quad(canvas, tex, pts2d, opacity=1.0):
    """tex — RGBA; pts2d — четыре экранные точки TL,TR,BR,BL"""
    xs = [p[0] for p in pts2d]; ys = [p[1] for p in pts2d]
    x0, x1 = int(math.floor(min(xs))), int(math.ceil(max(xs)))
    y0, y1 = int(math.floor(min(ys))), int(math.ceil(max(ys)))
    x0, y0 = max(x0, -W), max(y0, -H)
    x1, y1 = min(x1, 2 * W), min(y1, 2 * H)
    bw, bh = x1 - x0, y1 - y0
    if bw < 2 or bh < 2 or x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H: return
    if bw * bh > 40_000_000: return
    dst = [(p[0] - x0, p[1] - y0) for p in pts2d]
    tw, th = tex.size
    src = [(0, 0), (tw, 0), (tw, th), (0, th)]
    try:
        c = _coeffs(dst, src)
    except Exception:
        return
    warped = tex.transform((bw, bh), Image.PERSPECTIVE, c, Image.BICUBIC)
    if opacity < 1.0:
        a = warped.split()[3].point(lambda v: int(v * opacity))
        warped.putalpha(a)
    canvas.alpha_composite(warped, (max(0, x0), max(0, y0)),
                           (max(0, -x0), max(0, -y0), bw, bh))

# ---------- зал ----------
def _poly(d, pts, fill):
    d.polygon([(p[0], p[1]) for p in pts], fill=fill)

def room(cam, windows=True, dark=0.0, shafts=True, ropes=True):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    g = Image.new("L", (1, H))
    for y in range(H):
        t = y / H
        g.putpixel((0, y), int(234 - 24 * abs(t - 0.5) * 2))
    base = g.resize((W, H))
    img = Image.merge("RGBA", (base, base, base.point(lambda v: min(255, v + 3)),
                               Image.new("L", (W, H), 255)))
    d = ImageDraw.Draw(img, "RGBA")
    hor = H / 2 + (cam.y - 0.0) * 0  # горизонт на уровне взгляда
    d.rectangle([0, hor, W, H], fill=(197, 200, 204, 255))      # пол
    d.rectangle([0, 0, W, hor], fill=(230, 232, 235, 255))      # дальняя стена/воздух
    # стены
    for sx in (-1, 1):
        p = [cam.proj((sx * WALL, CEIL, cam.z + 2.0)), cam.proj((sx * WALL, CEIL, cam.z + FAR)),
             cam.proj((sx * WALL, 0.0, cam.z + FAR)), cam.proj((sx * WALL, 0.0, cam.z + 2.0))]
        _poly(d, p, (222, 225, 229, 255))
    # окна
    if windows:
        z0 = math.floor((cam.z + 3) / 7.0) * 7.0
        for i in range(10):
            zz = z0 + i * 7.0
            for sx in (-1, 1):
                p = [cam.proj((sx * WALL, 3.75, zz)), cam.proj((sx * WALL, 3.75, zz + 3.1)),
                     cam.proj((sx * WALL, 1.15, zz + 3.1)), cam.proj((sx * WALL, 1.15, zz))]
                _poly(d, p, (251, 252, 253, 255))
                for k in range(1, 4):
                    yy = 1.15 + 2.6 * k / 4
                    a = cam.proj((sx * WALL, yy, zz)); b = cam.proj((sx * WALL, yy, zz + 3.1))
                    d.line([(a[0], a[1]), (b[0], b[1])], fill=(226, 229, 233, 255), width=2)
    # световые полосы на полу
    if shafts:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dl = ImageDraw.Draw(lay, "RGBA")
        z0 = math.floor((cam.z + 3) / 7.0) * 7.0
        for i in range(9):
            zz = z0 + i * 7.0
            for sx in (-1, 1):
                p = [cam.proj((sx * (WALL - 0.2), 0.0, zz + 0.6)),
                     cam.proj((sx * (WALL - 0.2), 0.0, zz + 3.5)),
                     cam.proj((sx * (WALL - 3.4), 0.0, zz + 5.2)),
                     cam.proj((sx * (WALL - 3.4), 0.0, zz + 2.3))]
                dl.polygon([(q[0], q[1]) for q in p], fill=(255, 255, 255, 120))
        lay = lay.filter(ImageFilter.GaussianBlur(9))
        img.alpha_composite(lay)
    if ropes:
        rng = np.random.default_rng(5)
        dr = ImageDraw.Draw(img, "RGBA")
        z0 = math.floor((cam.z + 4) / 3.0) * 3.0
        for i in range(26):
            zz = z0 + (i % 13) * 3.0 + float(rng.uniform(-1.0, 1.0))
            xx = float(rng.uniform(-4.6, 4.6))
            yy = float(rng.uniform(0.9, 2.4))
            if zz - cam.z < 1.5: continue
            a = cam.proj((xx, CEIL, zz)); b = cam.proj((xx, yy, zz))
            dr.line([(a[0], a[1]), (b[0], b[1])], fill=(150, 152, 156, 255), width=1)
    if dark > 0:
        sh = Image.new("RGBA", (W, H), (8, 7, 6, int(235 * clamp01(dark))))
        img.alpha_composite(sh)
    return img

# ---------- угли ----------
_SPR = None
def _sprite():
    global _SPR
    if _SPR is None:
        n = 192
        yy, xx = np.mgrid[0:n, 0:n]
        r = np.sqrt((xx - n/2) ** 2 + (yy - n/2) ** 2) / (n / 2)
        a = np.clip(1 - r, 0, 1) ** 1.15
        core = np.clip(1 - r * 1.75, 0, 1) ** 1.1
        rgb = np.zeros((n, n, 3), np.float32)
        rgb[..., 0] = 255 * (0.60 * a + 0.40 * core)
        rgb[..., 1] = 255 * (0.30 * a + 0.70 * core)
        rgb[..., 2] = 255 * (0.06 * a + 0.94 * core)
        _SPR = (rgb, a)
    return _SPR

def cluster(x, y, z, s, n=4, seed=0, mirror=True):
    """горстка углей вокруг точки + их отражение в полу"""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        dx = rng.uniform(-0.45, 0.45); dy = rng.uniform(-0.06, 0.22); dz = rng.uniform(-0.5, 0.5)
        ss = s * rng.uniform(0.45, 1.0)
        out.append((x + dx, max(0.04, y + dy), z + dz, ss))
        if mirror:
            out.append((x + dx, -(max(0.04, y + dy)) * 0.9, z + dz, ss * 0.8))
    return out

def embers(img, cam, pts, t, glow=0.95):
    """оранжевые угли: ядро кроет собой фон, вокруг — аддитивный ореол"""
    rgb, al = _sprite()
    add = np.zeros((H, W, 3), np.float32)
    ca = np.zeros((H, W, 1), np.float32)
    for i, (x, y, z, s) in enumerate(pts):
        pulse = 0.82 + 0.18 * math.sin(t * 3.4 + i * 1.7)
        px, py, dz = cam.proj((x, y, z))
        if dz < 0.3: continue
        size = max(10, int(s * F / dz * pulse))
        if size > 1400 or px < -size or px > W + size or py < -size or py > H + size: continue
        sp = np.array(Image.fromarray(rgb.astype(np.uint8)).resize((size, size), Image.BILINEAR), np.float32)
        sa = np.array(Image.fromarray((al * 255).astype(np.uint8)).resize((size, size), Image.BILINEAR), np.float32) / 255.0
        x0, y0 = int(px - size / 2), int(py - size / 2)
        X0, Y0 = max(0, x0), max(0, y0); X1, Y1 = min(W, x0 + size), min(H, y0 + size)
        if X1 <= X0 or Y1 <= Y0: continue
        sub = sp[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
        suba = sa[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0][..., None]
        add[Y0:Y1, X0:X1] += sub * suba * pulse * 0.55
        ca[Y0:Y1, X0:X1] = np.maximum(ca[Y0:Y1, X0:X1], np.clip(suba * 2.6 - 0.45, 0, 1))
    if ca.max() <= 0 and add.max() <= 0:
        return img
    halo = np.asarray(Image.fromarray(np.clip(add, 0, 255).astype(np.uint8))
                      .filter(ImageFilter.GaussianBlur(46)), np.float32)
    arr = np.asarray(img.convert("RGB"), np.float32)
    core = np.array([255.0, 182.0, 92.0], np.float32)
    arr = arr * (1 - ca) + core * ca
    arr = arr + add * 0.5 + halo * glow
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")

# ---------- текстуры ----------
def text_tex(words, fsize=210, fname="ArialBlack.ttf", pad=26, line_gap=14, cond=1.0,
             color=(14, 14, 16, 255), hl=None, hl_color=(255, 212, 0, 255)):
    """words — список строк; hl — множество индексов слов с жёлтым маркером"""
    f = font(fname, fsize)
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    rows = []
    for ln in words:
        ws = ln.split(" ")
        sizes = [tmp.textbbox((0, 0), w, font=f) for w in ws]
        rows.append((ws, sizes))
    sp = tmp.textlength(" ", font=f)
    wmax = 0; hline = fsize * 1.02
    for ws, sizes in rows:
        wd = sum(s[2] - s[0] for s in sizes) + sp * (len(ws) - 1)
        wmax = max(wmax, wd)
    tw = int(wmax + pad * 2)
    th = int(len(rows) * hline + (len(rows) - 1) * line_gap + pad * 2)
    img = Image.new("RGBA", (max(tw, 8), max(th, 8)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    idx = 0
    y = pad
    for ws, sizes in rows:
        x = pad
        for w, s in zip(ws, sizes):
            ww = s[2] - s[0]
            if hl and idx in hl:
                d.rectangle([x - 10, y + fsize * 0.10, x + ww + 10, y + fsize * 0.98], fill=hl_color)
            d.text((x - s[0], y - s[1]), w, font=f, fill=color)
            x += ww + sp
            idx += 1
        y += hline + line_gap
    if cond != 1.0:
        img = img.resize((max(4, int(img.size[0] * cond)), img.size[1]), Image.LANCZOS)
    return img

def sticker_tex(word, fsize=190, bg=(255, 212, 0, 255), fg=(12, 12, 14, 255)):
    f = font("ArialBlack.ttf", fsize)
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    b = d0.textbbox((0, 0), word, font=f)
    pw, ph = b[2] - b[0] + fsize * 0.52, b[3] - b[1] + fsize * 0.40
    img = Image.new("RGBA", (int(pw), int(ph)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # рваные края: несколько прямоугольников внахлёст
    rng = np.random.default_rng(abs(hash(word)) % 9999)
    d.rectangle([0, ph * 0.04, pw, ph * 0.96], fill=bg)
    for i in range(7):
        x0 = pw * i / 7.0
        d.rectangle([x0, ph * (0.0 + rng.uniform(0, .05)), x0 + pw / 7.0,
                     ph * (1.0 - rng.uniform(0, .05))], fill=bg)
    d.text(((pw - (b[2] - b[0])) / 2 - b[0], (ph - (b[3] - b[1])) / 2 - b[1]), word, font=f, fill=fg)
    return img

def sheet_tex(lines, w=620, h=400, fsize=25):
    img = Image.new("RGBA", (w, h), (252, 252, 251, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(214, 214, 212, 255), width=2)
    f = font("Arimo-Bold.ttf", fsize)
    y = 26
    for ln in lines:
        d.text((24, y), ln, font=f, fill=(34, 34, 36, 255)); y += fsize + 9
    fs = font("Arimo-Bold.ttf", int(fsize * 0.72))
    for i in range(9):
        d.line([24, y + 14 + i * 15, w - 24 - (i % 3) * 70, y + 14 + i * 15],
               fill=(205, 206, 208, 255), width=5)
    return img

def extrude(canvas, cam, corners, tex, depth=0.30, steps=9, shade=(96, 97, 100)):
    """объёмная плашка: копии в глубину от дальней к ближней"""
    for i in range(steps, 0, -1):
        k = i / steps
        cs = [(c[0], c[1], c[2] + depth * k) for c in corners]
        pts = [cam.proj(p) for p in cs]
        v = int(shade[0] + (150 - shade[0]) * (1 - k) * 0.35)
        solid = Image.new("RGBA", tex.size, (v, v, v + 2, 255))
        solid.putalpha(tex.split()[3])
        paste_quad(canvas, solid, pts)
    paste_quad(canvas, tex, [cam.proj(p) for p in corners])

def floor_shadow(canvas, cam, corners, tex, spread=0.55):
    """тень объекта на полу"""
    bl, br = corners[3], corners[2]
    far = 0.75
    sh = [(bl[0], 0.01, bl[2]), (br[0], 0.01, br[2]),
          (br[0] + 0.1, 0.01, br[2] + far), (bl[0] - 0.1, 0.01, bl[2] + far)]
    a = tex.split()[3].point(lambda v: int(v * 0.26))
    dark = Image.new("RGBA", tex.size, (40, 42, 46, 255)); dark.putalpha(a)
    dark = dark.filter(ImageFilter.GaussianBlur(26))
    paste_quad(canvas, dark, [cam.proj(p) for p in sh])

def reflection(canvas, cam, corners, tex, strength=0.10):
    mir = [(c[0], -c[1], c[2]) for c in (corners[3], corners[2], corners[1], corners[0])]
    t = tex.filter(ImageFilter.GaussianBlur(18))
    a = t.split()[3].point(lambda v: int(v * strength))
    t.putalpha(a)
    paste_quad(canvas, t, [cam.proj(p) for p in mir])

def wire(canvas, cam, top_point, color=(118, 120, 124, 210), width=2):
    a = cam.proj((top_point[0], CEIL, top_point[2]))
    b = cam.proj(top_point)
    d = ImageDraw.Draw(canvas, "RGBA")
    d.line([(a[0], a[1]), (b[0], b[1])], fill=color, width=width)

def source_line(canvas, text):
    d = ImageDraw.Draw(canvas, "RGBA")
    f = font("Arimo-Bold.ttf", 25)
    d.text((54, H - 62), text, font=f, fill=(96, 98, 102, 255))


# ---------- разбор текста на отдельные слова (для набора по словам) ----------
def word_tiles(lines, fsize=220, fname="ArialBlack.ttf", hl=None,
               color=(14, 14, 16, 255), hl_color=(255, 212, 0, 255),
               line_gap=16, pad=20):
    """возвращает (общая ширина, общая высота, [(картинка слова, cx, cy)])
    cx, cy — центр слова в координатах общего блока."""
    f = font(fname, fsize)
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sp = d0.textlength(" ", font=f)
    rows = []
    for ln in lines:
        ws = ln.split(" ")
        bb = [d0.textbbox((0, 0), w, font=f) for w in ws]
        width = sum(b[2] - b[0] for b in bb) + sp * (len(ws) - 1)
        rows.append((ws, bb, width))
    total_w = max(r[2] for r in rows) + pad * 2
    hline = fsize * 1.02
    total_h = len(rows) * hline + (len(rows) - 1) * line_gap + pad * 2
    tiles = []
    idx = 0
    y = pad
    for ws, bb, width in rows:
        x = (total_w - width) / 2
        for w, b in zip(ws, bb):
            ww, hh = b[2] - b[0], b[3] - b[1]
            mark = bool(hl and idx in hl)
            tw = int(ww + fsize * 0.14)
            th = int(hline)
            tile = Image.new("RGBA", (max(tw, 4), max(th, 4)), (0, 0, 0, 0))
            td = ImageDraw.Draw(tile)
            if mark:
                td.rectangle([0, hline * 0.12, tw, hline * 0.95], fill=hl_color)
            td.text(((tw - ww) / 2 - b[0], (th - hh) / 2 - b[1]), w, font=f, fill=color)
            tiles.append((tile, x + ww / 2, y + hline / 2))
            x += ww + sp
            idx += 1
        y += hline + line_gap
    return total_w, total_h, tiles

# ---------- панель «эфира»: наша, без чужих кадров ----------
def tv_tex(caption=None, w=960, h=540, t=0.0):
    img = Image.new("RGBA", (w, h), (46, 34, 104, 255))
    d = ImageDraw.Draw(img, "RGBA")
    for i in range(h):
        k = i / h
        d.line([(0, i), (w, i)], fill=(int(52 + 26 * k), int(38 + 20 * k), int(118 + 40 * k), 255))
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rectangle([w * 0.00, 0, w * 0.085, h], fill=(126, 84, 46, 255))      # деревянная панель слева
    ld.rectangle([w * 0.085, 0, w * 0.125, h], fill=(206, 212, 236, 210))   # светящаяся полоса
    ld.ellipse([w * 0.10, -h * 0.35, w * 0.55, h * 1.15], fill=(190, 200, 240, 60))
    ld.ellipse([w * 0.55, -h * 0.25, w * 1.05, h * 0.95], fill=(120, 110, 220, 55))
    img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(26)))
    gf = font("ArialBlack.ttf", int(h * 0.085))
    gl = Image.new("RGBA", (w, h), (0, 0, 0, 0)); gd = ImageDraw.Draw(gl)
    for r in range(4):
        for c in range(3):
            gd.text((w * (0.20 + c * 0.28), h * (0.10 + r * 0.22)), "ЭФИР", font=gf,
                    fill=(255, 255, 255, 11))
    img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(2)))
    # нижняя плашка
    d.rectangle([0, h * 0.775, w * 0.30, h * 0.845], fill=(78, 48, 152, 255))
    d.text((w * 0.022, h * 0.787), "НОВОСТИ ДНЯ", font=font("ArialBlack.ttf", int(h * 0.040)),
           fill=(255, 255, 255, 255))
    d.polygon([(0, h * 0.855), (w * 0.985, h * 0.855), (w, h * 0.905), (w * 0.985, h * 0.955),
               (0, h * 0.955)], fill=(246, 247, 250, 255))
    d.text((w * 0.025, h * 0.879), "ТЕЛЕКАНАЛ", font=font("ArialBlack.ttf", int(h * 0.044)),
           fill=(26, 26, 30, 255))
    d.line([(w * 0.235, h * 0.872), (w * 0.235, h * 0.942)], fill=(120, 122, 130, 255), width=3)
    d.text((w * 0.256, h * 0.879), "ЗАЯВЛЕНИЕ ПО ИТОГАМ ПЕРЕГОВОРОВ",
           font=font("ArialBlack.ttf", int(h * 0.044)), fill=(26, 26, 30, 255))
    if caption:
        f = font("Arimo-Bold.ttf", int(h * 0.062))
        y = h * 0.60
        for ln in caption:
            tw = d.textlength(ln, font=f)
            d.text(((w - tw) / 2, y), ln, font=f, fill=(255, 255, 255, 255))
            y += h * 0.078
    return img


# ---------- разбор текста на отдельные слова (для набора по словам) ----------
def word_tiles(lines, fsize=220, fname="ArialBlack.ttf", hl=None,
               color=(14, 14, 16, 255), hl_color=(255, 212, 0, 255),
               line_gap=16, pad=20):
    """возвращает (общая ширина, общая высота, [(картинка слова, cx, cy)])
    cx, cy — центр слова в координатах общего блока."""
    f = font(fname, fsize)
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sp = d0.textlength(" ", font=f)
    rows = []
    for ln in lines:
        ws = ln.split(" ")
        bb = [d0.textbbox((0, 0), w, font=f) for w in ws]
        width = sum(b[2] - b[0] for b in bb) + sp * (len(ws) - 1)
        rows.append((ws, bb, width))
    total_w = max(r[2] for r in rows) + pad * 2
    hline = fsize * 1.02
    total_h = len(rows) * hline + (len(rows) - 1) * line_gap + pad * 2
    tiles = []
    idx = 0
    y = pad
    for ws, bb, width in rows:
        x = (total_w - width) / 2
        for w, b in zip(ws, bb):
            ww, hh = b[2] - b[0], b[3] - b[1]
            mark = bool(hl and idx in hl)
            tw = int(ww + fsize * 0.14)
            th = int(hline)
            tile = Image.new("RGBA", (max(tw, 4), max(th, 4)), (0, 0, 0, 0))
            td = ImageDraw.Draw(tile)
            if mark:
                td.rectangle([0, hline * 0.12, tw, hline * 0.95], fill=hl_color)
            td.text(((tw - ww) / 2 - b[0], (th - hh) / 2 - b[1]), w, font=f, fill=color)
            tiles.append((tile, x + ww / 2, y + hline / 2))
            x += ww + sp
            idx += 1
        y += hline + line_gap
    return total_w, total_h, tiles

# ---------- панель «эфира»: наша, без чужих кадров ----------
def build_block(items, t, start=0.0, step=0.25, maxlines=3):
    """items: ('w', слово, жёлтый?) или ('br',). Возвращает (строки, множество жёлтых индексов)"""
    rows, flags = [[]], [[]]
    k = 0
    for it in items:
        if it[0] == "br":
            rows.append([]); flags.append([]); continue
        if t < start + k * step: break
        rows[-1].append(it[1]); flags[-1].append(bool(it[2])); k += 1
    rows = [r for r in rows if r]; flags = [f for f in flags if f]
    if not rows: return [], set()
    if len(rows) > maxlines:
        rows = rows[-maxlines:]; flags = flags[-maxlines:]
    hl, idx = set(), 0
    for f in flags:
        for v in f:
            if v: hl.add(idx)
            idx += 1
    return [" ".join(r) for r in rows], hl

def hang_block(img, cam, lines, hl, center, line_h, fsize=170,
               fname="Oswald-Bold.ttf", wires=True, depth=0.07):
    if not lines: return
    tex = text_tex(lines, fsize=fsize, fname=fname, hl=hl)
    h = line_h * len(lines) + 0.10
    w = h * tex.size[0] / tex.size[1]
    cx, cy, cz = center
    c = quad((cx + w / 2, cy - h / 2, cz), w, h)   # прижат влево от точки подвеса
    if wires:
        wire(img, cam, (cx + w * 0.12, cy, cz))
        wire(img, cam, (cx + w * 0.88, cy, cz))
    extrude(img, cam, c, tex, depth=depth, steps=4)

# ---------- стеклянный куб ----------
def glass_cube(img, cam, center, size, t=0.0, wires=True):
    cx, cy, cz = center
    s = size / 2
    v = [(cx - s, cy - s, cz - s), (cx + s, cy - s, cz - s), (cx + s, cy - s, cz + s), (cx - s, cy - s, cz + s),
         (cx - s, cy + s, cz - s), (cx + s, cy + s, cz - s), (cx + s, cy + s, cz + s), (cx - s, cy + s, cz + s)]
    p = [cam.proj(q) for q in v]
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for f in ((0,1,5,4),(1,2,6,5),(3,2,6,7),(0,3,7,4)):
        d.polygon([(p[i][0], p[i][1]) for i in f], fill=(214, 226, 240, 40))
    for e0, e1 in ((0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)):
        d.line([(p[e0][0], p[e0][1]), (p[e1][0], p[e1][1])], fill=(52, 54, 58, 255), width=7)
    if wires:
        for i in (4, 5, 6, 7):
            top = cam.proj((v[i][0], CEIL, v[i][2]))
            d.line([(top[0], top[1]), (p[i][0], p[i][1])], fill=(120, 122, 126, 255), width=2)
    img.alpha_composite(lay)

# ---------- белые объёмные макеты ----------
def maket_tex(kind, px=420):
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = (236, 238, 241, 255); edge = (120, 124, 130, 255)
    if kind == "bank":
        d.polygon([(px*0.06, px*0.36), (px*0.5, px*0.10), (px*0.94, px*0.36)], fill=ink, outline=edge, width=3)
        d.rectangle([px*0.08, px*0.36, px*0.92, px*0.44], fill=ink, outline=edge, width=3)
        for i in range(5):
            x = px * (0.15 + i * 0.175)
            d.rectangle([x, px*0.44, x + px*0.075, px*0.86], fill=ink, outline=edge, width=3)
        d.rectangle([px*0.05, px*0.86, px*0.95, px*0.95], fill=ink, outline=edge, width=3)
    elif kind == "hospital":
        d.rectangle([px*0.18, px*0.22, px*0.82, px*0.95], fill=ink, outline=edge, width=3)
        for r in range(4):
            for c in range(3):
                d.rectangle([px*(0.26 + c*0.18), px*(0.32 + r*0.15),
                             px*(0.36 + c*0.18), px*(0.42 + r*0.15)], fill=(196, 200, 206, 255))
        d.rectangle([px*0.46, px*0.06, px*0.54, px*0.22], fill=ink, outline=edge, width=3)
        d.rectangle([px*0.38, px*0.11, px*0.62, px*0.17], fill=ink, outline=edge, width=3)
    else:  # power
        edge = (78, 80, 84, 255)
        for sx in (0.28, 0.72):
            d.line([(px*(sx-0.14), px*0.95), (px*sx, px*0.16)], fill=edge, width=5)
            d.line([(px*(sx+0.14), px*0.95), (px*sx, px*0.16)], fill=edge, width=5)
            d.line([(px*(sx-0.11), px*0.72), (px*(sx+0.11), px*0.72)], fill=edge, width=4)
            d.line([(px*(sx-0.07), px*0.46), (px*(sx+0.07), px*0.46)], fill=edge, width=4)
            d.line([(px*(sx-0.13), px*0.26), (px*(sx+0.13), px*0.26)], fill=edge, width=4)
            for j in range(4):
                y0 = px*(0.30 + j*0.16); y1 = px*(0.30 + (j+1)*0.16)
                k0 = 0.07 + j*0.022; k1 = 0.07 + (j+1)*0.022
                d.line([(px*(sx-k0), y0), (px*(sx+k1), y1)], fill=edge, width=2)
                d.line([(px*(sx+k0), y0), (px*(sx-k1), y1)], fill=edge, width=2)
        d.line([(px*0.28, px*0.26), (px*0.72, px*0.30)], fill=edge, width=3)
        d.line([(px*0.28, px*0.46), (px*0.72, px*0.50)], fill=edge, width=3)
    return img

# ---------- тёмная плашка со значением ----------
def plate_tex(value, sub=None, px=520, color=(255, 196, 42, 255)):
    h = int(px * 0.46)
    img = Image.new("RGBA", (px, h), (96, 82, 64, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([14, 14, px - 15, h - 15], fill=(30, 26, 22, 255))
    d.rectangle([0, 0, px - 1, h - 1], outline=(120, 104, 80, 255), width=4)
    f = font("Oswald-Bold.ttf", int(h * 0.62))
    b = d.textbbox((0, 0), value, font=f)
    d.text(((px - (b[2] - b[0])) / 2 - b[0], (h - (b[3] - b[1])) / 2 - b[1]), value, font=f,
           fill=color)
    return img

# ---------- вертикальная шкала-столб ----------
def scale_column(img, cam, x, z, top=4.4, wdt=0.13):
    tex = Image.new("RGBA", (40, 400), (44, 40, 36, 255))
    c = quad((x, top / 2, z), wdt, top)
    extrude(img, cam, c, tex, depth=wdt, steps=3, shade=(38, 35, 32))


def put_above_floor(canvas, cam, corners, tex, depth=0.0, steps=1, shade=(96, 97, 100)):
    """кладёт объект, обрезая всё, что ниже линии пола на этой дальности —
    так слово «вырастает из пола», а не появляется целиком"""
    zc = sum(c[2] for c in corners) / 4.0
    dz = max(0.3, zc - cam.z)
    y_floor = H / 2 + cam.y * F / dz
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if depth > 0:
        extrude(lay, cam, corners, tex, depth=depth, steps=steps, shade=shade)
    else:
        paste_quad(lay, tex, [cam.proj(p) for p in corners])
    yf = int(max(0, min(H, y_floor)))
    if yf < H:
        ImageDraw.Draw(lay).rectangle([0, yf, W, H], fill=(0, 0, 0, 0))
    canvas.alpha_composite(lay)
