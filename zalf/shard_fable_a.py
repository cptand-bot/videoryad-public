# -*- coding: utf-8 -*-
"""Белый зал, вторая реализация (часть A: G02, G10, G12).
Запуск: shard_fable_a.py <код> <out.mp4>; один кадр: ZAL_FRAME=1.9 shard_fable_a.py G02 k.png

Числа сняты с плёнки покадрово (polosy/G02_vhod, G10_vhod, G12_vhod, сетки *_setka):
  G02  21.300 «I» · 21.433 «DIDN'T» · 21.633 «GO» · 21.667 «FAR» · 21.933 «ENOUGH.»
       каждое слово — 1 кадр крупнее (~1.2) и смазан, на 2-3-м кадре садится;
       верх тёмный на тросах, низ жёлтый стоит на полу, линия уходит правым концом
       к камере, тень на пол назад-вправо; с 22.4 камера разгоняется и пролетает сквозь.
  G10  243.9 «AND THEY» · 244.0 «ARE» (на тросах) · 244.233-244.367 «RACING.» выезжает
       из пола за 5 кадров (167 мс) с лёгким перелётом; плиты с углями по бокам
       подскакивают в кадр всё ближе к камере; с ~244.5 камера идёт вперёд, разгоняясь.
  G12  макеты ПАДАЮТ с потолка за 3 кадра (100 мс): банк 49.533-49.600, больница
       49.933-50.000, ЛЭП 50.400-50.500; подпись под макетом — через кадр после посадки;
       «+» между макетами; «GRIDS» с жёлтым маркером приходит одним куском 50.900-50.933.
"""
import sys, os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as Z
from zal_core import *

FPS = 30
DT = 1.0 / FPS
CAP = 0.715          # высота капители Arial Black в долях кегля
YEL = (242, 206, 74, 255)
YEL_SIDE = (190, 154, 44)
DARK = (46, 40, 37, 255)
DARK_SIDE = (28, 25, 23)

# ----------------------------------------------------------------- общие вещи

def pop(t0, t, dur=0.10, k0=1.22):
    """вход слова как на плёнке: первый кадр крупнее и прозрачнее, за ~3 кадра садится.
    возвращает (масштаб, непрозрачность) или None, если слова ещё нет"""
    if t < t0 - 1e-6: return None
    u = seg(t, t0, t0 + dur)
    s = k0 + (1.0 - k0) * out_cubic(u)
    op = 0.55 + 0.45 * clamp01(u * 2.2)
    return s, op

def line_frame(center, yaw):
    """оси строки в пространстве: направление вдоль строки и нормаль от камеры.
    yaw > 0 — правый конец дальше от камеры, yaw < 0 — ближе"""
    ux = (math.cos(yaw), 0.0, math.sin(yaw))
    nz = (-math.sin(yaw), 0.0, math.cos(yaw))
    return ux, nz

def word_quad(center, ux, u, v, w, h):
    """углы прямоугольника слова: центр строки + u вдоль строки, v вверх"""
    cx = center[0] + ux[0] * u; cy = center[1] + v; cz = center[2] + ux[2] * u
    hw, hh = w / 2, h / 2
    return [(cx - ux[0] * hw, cy + hh, cz - ux[2] * hw), (cx + ux[0] * hw, cy + hh, cz + ux[2] * hw),
            (cx + ux[0] * hw, cy - hh, cz + ux[2] * hw), (cx - ux[0] * hw, cy - hh, cz - ux[2] * hw)]

def visible(cam, corners, margin=0.35):
    return min(c[2] for c in corners) - cam.z > margin

def extrude_dir(canvas, cam, corners, tex, depth, nz, steps=8, side=(96, 97, 100),
                floor_clip=False, opacity=1.0):
    """объём вдоль произвольной нормали nz; floor_clip — каждую копию резать по
    линии пола на её дальности (так слово растёт из пола, а не всплывает)"""
    lay = canvas if not floor_clip else Image.new("RGBA", (W, H), (0, 0, 0, 0))
    alpha = tex.split()[3]
    # шаг копий — по экранному сдвигу задней грани, чтобы вблизи не было лесенки
    p0 = cam.proj(corners[2]); p1 = cam.proj((corners[2][0] + nz[0] * depth, corners[2][1], corners[2][2] + nz[2] * depth))
    shift = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    steps = int(max(steps, min(48, shift / 2.5)))
    for i in range(steps, -1, -1):
        k = i / steps
        cs = [(c[0] + nz[0] * depth * k, c[1], c[2] + nz[2] * depth * k) for c in corners]
        if not visible(cam, cs): continue
        pts = [cam.proj(p) for p in cs]
        if i == 0:
            t = tex
        else:
            v = [int(side[j] * (0.78 + 0.22 * (1 - k))) for j in range(3)]
            t = Image.new("RGBA", tex.size, (v[0], v[1], v[2], 255)); t.putalpha(alpha)
        if floor_clip:
            sub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            paste_quad(sub, t, pts, opacity)
            zc = sum(c[2] for c in cs) / 4.0
            yf = H / 2 + cam.y * F / max(0.3, zc - cam.z)
            yf = int(max(0, min(H, yf)))
            if yf < H:
                ImageDraw.Draw(sub).rectangle([0, yf, W, H], fill=(0, 0, 0, 0))
            lay.alpha_composite(sub)
        else:
            paste_quad(lay, t, pts, opacity)
    if floor_clip:
        canvas.alpha_composite(lay)

def text_shadow(canvas, cam, corners, tex, ux, off=(0.9, 0.0, 1.4), blur=14, strength=0.30):
    """тень надписи на полу: верх букв уезжает по вектору off (свет спереди-слева)"""
    bl, br = corners[3], corners[2]
    h = corners[0][1] - corners[3][1]
    k = h  # длина тени ~ высоте букв
    sh = [(bl[0] + off[0] * k, 0.012, bl[2] + off[2] * k), (br[0] + off[0] * k, 0.012, br[2] + off[2] * k),
          (br[0], 0.012, br[2]), (bl[0], 0.012, bl[2])]
    if not visible(cam, sh): return
    a = tex.split()[3].point(lambda v: int(v * strength))
    dark = Image.new("RGBA", tex.size, (38, 36, 34, 255)); dark.putalpha(a)
    dark = dark.filter(ImageFilter.GaussianBlur(blur))
    paste_quad(canvas, dark, [cam.proj(p) for p in sh])

def tiles_crop(lines, fsize, hl=None, color=DARK, vertical=False, fname="ArialBlack.ttf", cond=0.80):
    """плитки слов, обрезанные по контуру; (общая ширина, высота, [(плитка, cx, cy, baseline)]).
    cond — сжатие по ширине: шрифт образца уже Arial Black примерно на пятую часть"""
    tw, th, tiles = word_tiles(lines, fsize=fsize, fname=fname, hl=hl, color=color)
    out = []
    tw = tw * cond
    for tile, cx, cy in tiles:
        if cond != 1.0:
            tile = tile.resize((max(4, int(tile.size[0] * cond)), tile.size[1]), Image.LANCZOS)
            cx = cx * cond
        bb = tile.getbbox()
        if bb is None: continue
        if vertical:
            cr = tile.crop(bb)
            out.append((cr, cx - tile.size[0] / 2 + (bb[0] + bb[2]) / 2,
                        cy - tile.size[1] / 2 + (bb[1] + bb[3]) / 2, bb[3] + cy - tile.size[1] / 2))
        else:
            cr = tile.crop((bb[0], 0, bb[2], tile.size[1]))
            out.append((cr, cx - tile.size[0] / 2 + (bb[0] + bb[2]) / 2, cy, None))
    return tw, th, out

def place_words(img, cam, t, words, center, yaw, scale_m, starts, depth, side,
                hang=False, floor=False, shadow=False, floor_clip=False, rise=None,
                wire_per_word=1, extra_op=1.0, k0=1.22):
    """words — плитки из tiles_crop; scale_m — метров на пиксель плитки; starts — t0 каждого слова.
    hang — тросы к потолку; floor — нижняя кромка слова на полу (center[1] = 0);
    rise — (t0, dur) подъём всей строки из пола."""
    tw, th, tiles = words
    ux, nz = line_frame(center, yaw)
    order = list(range(len(tiles)))
    for i in order:
        tile, cx, cy, base = tiles[i]
        p = pop(starts[i], t, k0=k0)
        if p is None: continue
        s, op = p
        op *= extra_op
        w = tile.size[0] * scale_m * s; h = tile.size[1] * scale_m * s
        u = (cx - tw / 2) * scale_m
        if floor:
            v = h / 2
        else:
            v = (th / 2 - cy) * scale_m
        dy = 0.0
        if rise is not None:
            r0, rd = rise
            u = seg(t, r0, r0 + rd)
            k = 1.0 - (1.0 - u) ** 1.6          # 0.30 · 0.56 · 0.77 · 0.92 · 1.0 по кадрам
            k += 0.03 * math.sin(math.pi * seg(t, r0 + rd, r0 + rd + 0.1))   # перелёт 3% на посадке
            dy = -(1.0 - k) * (tile.size[1] * scale_m) * 1.02
        c = word_quad((center[0], center[1] + dy, center[2]), ux, u, v, w, h)
        if not visible(cam, c): continue
        if shadow and dy > -0.02:
            text_shadow(img, cam, c, tile, ux)
        if hang:
            n = wire_per_word if tile.size[0] * scale_m > 0.45 else 1
            for j in range(n):
                f = (j + 0.5) / n
                top = (c[0][0] + (c[1][0] - c[0][0]) * f, c[0][1], c[0][2] + (c[1][2] - c[0][2]) * f)
                wire(img, cam, top, color=(96, 98, 102, 230), width=2)
        if s > 1.08:                                   # первый кадр входа — смазан по горизонтали
            for sh in (-0.05, 0.05):
                cc = word_quad((center[0] + sh * w * ux[0], center[1] + dy, center[2] + sh * w * ux[2]), ux, u, v, w, h)
                paste_quad(img, tile, [cam.proj(q) for q in cc], 0.22)
        extrude_dir(img, cam, c, tile, depth, nz, steps=8, side=side,
                    floor_clip=floor_clip or rise is not None, opacity=op)

def rush_blur(img, k):
    """смаз пролёта: пара увеличенных копий поверх, k — сила 0..1"""
    if k <= 0.01: return img
    base = img.convert("RGB")
    for i, z in enumerate((1.012, 1.028)):
        sw, sh = int(W * z), int(H * z)
        big = base.resize((sw, sh), Image.BILINEAR).crop(((sw - W) // 2, (sh - H) // 2,
                                                            (sw - W) // 2 + W, (sh - H) // 2 + H))
        base = Image.blend(base, big, 0.30 * k)
    return base.convert("RGBA")

# ----------------------------------------------------------------- G02

_G02 = {}
def _g02_words():
    if not _G02:
        _G02["top"] = tiles_crop(["I DIDN'T GO"], 200, color=DARK)
        _G02["bot"] = tiles_crop(["FAR ENOUGH."], 200, color=YEL, vertical=True)
    return _G02

def g02(t):
    """объёмные слова: верх тёмный висит на тросах, низ жёлтый встаёт на полу"""
    # камера: стоит до 1.1 с, потом разгон вперёд и пролёт сквозь строку
    # на плёнке разгон начинается на 22.4 (t=1.1) и за полсекунды пролетает строку;
    # у нас клип длиннее — тот же разгон с постоянным ускорением, строку проходим к 3.6 с
    cz = 1.52 * max(0.0, t - 1.1) ** 2
    # на пролёте камера на плёнке наклоняется к полу (горизонт уходит вверх); у Cam нет
    # наклона, поэтому опускаем её к высоте букв, иначе строка уйдёт под нижний край
    cy = 1.55 - 0.95 * seg(t, 1.6, 3.5) ** 1.5
    cam = Cam(0.0, cy, cz, 0.0)
    img = room(cam)
    wd = _g02_words()
    # верхняя строка: d≈10.2 м, центр на высоте 2.45 м, капитель 0.66 м, правый конец чуть дальше
    top_scale = 0.58 / (CAP * 200)
    place_words(img, cam, t, wd["top"], (0.1, 2.45, 10.2), math.radians(6.0), top_scale,
                [0.0, 0.133, 0.333], depth=0.16, side=DARK_SIDE, hang=True, wire_per_word=2)
    # нижняя строка: стоит на полу на ~9.5 м, правый конец ближе к камере; капитель 0.95 м
    bot_scale = 0.85 / (CAP * 200)
    place_words(img, cam, t, wd["bot"], (0.25, 0.0, 9.5), math.radians(-14.0), bot_scale,
                [0.367, 0.633], depth=0.55, side=YEL_SIDE, floor=True, shadow=True)
    v = 2 * 1.52 * max(0.0, t - 1.1)          # скорость, м/с
    if v > 1.5:
        img = rush_blur(img, clamp01((v - 1.5) / 8.0))
    return img

# ----------------------------------------------------------------- G10

def slab_tex(wm, hm, px=360):
    """тёмная стопка плит: горизонтальные швы через ~0.22 м"""
    w = px; h = int(px * hm / wm)
    img = Image.new("RGBA", (w, h), (34, 31, 30, 255))
    d = ImageDraw.Draw(img)
    step = int(h * 0.22 / hm)
    y = h - 1
    k = 0
    while y > 0:
        d.line([(0, y), (w, y)], fill=(58, 54, 52, 255), width=max(2, px // 90))
        d.line([(0, y - 2), (w, y - 2)], fill=(20, 18, 17, 255), width=1)
        y -= step + (k % 3) * 3; k += 1
    d.rectangle([0, 0, w - 1, h - 1], outline=(24, 22, 21, 255), width=2)
    return img

def slab(img, cam, t, x, z, wm, hm, dm, t0, seed=0, ember=True):
    """плита-стопка на полу: подскакивает в кадр (как слова), угли на верхней кромке"""
    p = pop(t0, t, dur=0.10, k0=1.15)
    if p is None: return []
    s, op = p
    wm2, hm2, dm2 = wm * s, hm * s, dm * s
    # грани: верх, бок к центру зала, фронт
    x0, x1 = x - wm2 / 2, x + wm2 / 2
    z0, z1 = z, z + dm2
    front = [(x0, hm2, z0), (x1, hm2, z0), (x1, 0, z0), (x0, 0, z0)]
    top = [(x0, hm2, z1), (x1, hm2, z1), (x1, hm2, z0), (x0, hm2, z0)]
    if x > 0: sidef = [(x0, hm2, z1), (x0, hm2, z0), (x0, 0, z0), (x0, 0, z1)]
    else:     sidef = [(x1, hm2, z0), (x1, hm2, z1), (x1, 0, z1), (x1, 0, z0)]
    if not visible(cam, front): return []
    ft = slab_tex(wm, hm)
    st = slab_tex(dm, hm)
    tt = Image.new("RGBA", (64, 64), (52, 48, 46, 255))
    # тень на пол
    sh = [(x0 + 0.6, 0.01, z0 + 0.9), (x1 + 0.6, 0.01, z1 + 0.9), (x1, 0.01, z1), (x0, 0.01, z0)]
    shl = Image.new("RGBA", (64, 64), (40, 38, 36, int(70 * op)))
    paste_quad(img, shl.filter(ImageFilter.GaussianBlur(4)), [cam.proj(q) for q in sh])
    paste_quad(img, tt, [cam.proj(q) for q in top], op)
    paste_quad(img, st, [cam.proj(q) for q in sidef], op)
    paste_quad(img, ft, [cam.proj(q) for q in front], op)
    if not ember: return []
    # один крупный уголёк на верхнем ближнем к центру углу, как на плёнке
    ex = x0 + wm2 * (0.25 if x > 0 else 0.75)
    return [(ex, hm2 + 0.10, z0 + 0.10, 0.95)]

_G10 = {}
def _g10_words():
    if not _G10:
        # шрифт этой сцены у́же: ширина/высота строки снята с сетки 244.40
        _G10["top"] = tiles_crop(["AND THEY ARE"], 200, color=(30, 27, 26, 255), cond=0.56)
        _G10["bot"] = tiles_crop(["RACING."], 200, color=(44, 40, 38, 255), vertical=True, cond=0.62)
    return _G10

def g10(t):
    """слово выезжает из пола, вокруг плиты с углями, камера разгоняется сквозь"""
    # на плёнке камера трогается ~244.5 и сквозь слово проходит за 1.4 с (куб по времени);
    # у нас разгон тот же формы, но слово проходим к 3.35 с, дальше летим по залу
    cz = 13.0 * (max(0.0, t - 0.75) / 2.6) ** 3
    cam = Cam(0.0, 1.55, cz, 0.0)
    img = room(cam)
    wd = _g10_words()
    # верх: d≈14, центр 3.45 м, капитель 0.6 м
    place_words(img, cam, t, wd["top"], (0.0, 3.45, 14.0), 0.0, 0.60 / (CAP * 200),
                [0.05, 0.05, 0.15], depth=0.12, side=(18, 16, 15), hang=True, wire_per_word=2,
                k0=1.08)   # на плёнке 243.900 «AND THEY» входят почти без перелёта
    # плиты: пары по бокам, каждая следующая ближе к камере; дальние — за словом,
    # их угли рисуем ДО слова, чтобы буквы их закрывали
    # плиты 1.3-2.6 м (сетка 244.85: правая 36% высоты кадра на ~9 м → 1.8 м)
    far_pts, near_pts = [], []
    for (zz, hh, ww, xx, t0, sd) in ((16.0, 1.3, 0.9, 6.0, 0.0, 1), (13.0, 1.6, 1.0, 5.2, 0.55, 2),
                                     (9.0, 1.9, 1.1, 4.6, 0.95, 3), (6.0, 2.3, 1.2, 4.4, 1.40, 4),
                                     (3.5, 2.6, 1.2, 4.3, 1.85, 5), (22.0, 1.6, 1.0, 5.6, 2.55, 6),
                                     (27.0, 1.9, 1.1, 5.4, 2.85, 7), (32.0, 2.2, 1.2, 5.2, 3.15, 8)):
        for sx in (-1, 1):
            e = slab(img, cam, t, sx * xx, zz, ww, hh, ww * 0.9, t0, seed=sd * 7 + (sx > 0))
            (far_pts if zz > 14.5 else near_pts).extend(e)
    if far_pts:
        img = embers(img, cam, far_pts, t, glow=0.8)
    # низ: RACING. встаёт из пола на 14 м, капитель 2.3 м, за 167 мс
    place_words(img, cam, t, wd["bot"], (0.0, 0.0, 14.0), 0.0, 2.3 / (CAP * 200),
                [-1.0], depth=0.9, side=(26, 23, 22), floor=True, shadow=True,
                rise=(0.383, 0.167))
    if near_pts:
        img = embers(img, cam, near_pts, t, glow=0.8)
    v = 3 * 13.0 * (max(0.0, t - 0.75) / 2.6) ** 2 / 2.6       # скорость, м/с
    if v > 2.0:
        img = rush_blur(img, clamp01((v - 2.0) / 12.0))
    return img

# ----------------------------------------------------------------- G12

def drop(t0, t, dur=0.10, hfrom=3.6):
    """падение с потолка: 3 кадра разгона, посадка с коротким приседом.
    возвращает (dy, смаз_вверх, присед) или None"""
    if t < t0 - 1e-6: return None
    u = seg(t, t0, t0 + dur)
    dy = hfrom * (1 - u * u)
    smear = (1 - u) * 0.9 if u < 1 else 0.0
    sq = 0.0
    if u >= 1:
        b = seg(t, t0 + dur, t0 + dur + 0.10)
        sq = 0.06 * math.sin(b * math.pi)       # присед 6% и возврат
    return dy, smear, sq

def maket(img, cam, t, kind, x, z, size, t0):
    r = drop(t0, t)
    if r is None: return
    dy, smear, sq = r
    tex = maket_tex(kind, 480)
    if kind == "power":                       # опоры ЛЭП на плёнке почти чёрные
        r, g, b, a = tex.split()
        tex = Image.merge("RGBA", (r.point(lambda v: v * 0.45), g.point(lambda v: v * 0.45),
                                   b.point(lambda v: v * 0.45), a))
    else:                       # белый объём: подложка чуть темнее, чтобы читался на светлом
        under = Image.new("RGBA", tex.size, (0, 0, 0, 0))
        a = tex.split()[3].filter(ImageFilter.GaussianBlur(3))
        sh = Image.new("RGBA", tex.size, (150, 154, 160, 255)); sh.putalpha(a)
        under.alpha_composite(sh, (4, 5)); under.alpha_composite(tex)
        tex = under
    h = size * (1 - sq); w = size * (1 + sq * 0.6)
    c = quad((x, dy + h / 2, z), w, h)
    if not visible(cam, c): return
    if dy < 0.02:
        a = tex.split()[3].point(lambda v: int(v * 0.22))
        dark = Image.new("RGBA", tex.size, (40, 40, 42, 255)); dark.putalpha(a)
        dark = dark.filter(ImageFilter.GaussianBlur(12))
        sh = [(x - w / 2 + 0.5, 0.01, z + 0.6), (x + w / 2 + 0.5, 0.01, z + 0.6),
              (x + w / 2, 0.01, z), (x - w / 2, 0.01, z)]
        paste_quad(img, dark, [cam.proj(p) for p in sh])
    if smear > 0:
        for k in (0.35, 0.7):
            cc = quad((x, dy + h / 2 + smear * k * 1.2, z), w, h)
            paste_quad(img, tex, [cam.proj(p) for p in cc], 0.30)
    if kind == "power":
        paste_quad(img, tex, [cam.proj(p) for p in c])
    else:
        extrude_dir(img, cam, c, tex, 0.30, (0.0, 0.0, 1.0), steps=5, side=(170, 174, 180), opacity=1.0)

def label(img, cam, t, text, x, z, t0, hl=None, start_each=None):
    """подпись под макетом: тёмные объёмные слова на полу, hl — слово с жёлтым маркером"""
    words = tiles_crop([text], 200, color=(34, 31, 30, 255), hl=hl, vertical=True, cond=0.7)
    tw, th, tiles = words
    sc = 0.32 / (CAP * 200)        # сетка 50.80: BANKS 11 % ширины кадра, высота ~7 %
    starts = start_each if start_each else [t0] * len(tiles)
    place_words(img, cam, t, words, (x, 0.0, z), 0.0, sc, starts, depth=0.18,
                side=(20, 18, 17), floor=True, shadow=True)

def plus(img, cam, t, x, y, z, t0):
    p = pop(t0, t)
    if p is None: return
    s, op = p
    tex = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(tex)
    d.rectangle([46, 8, 74, 112], fill=(40, 37, 36, 255))
    d.rectangle([8, 46, 112, 74], fill=(40, 37, 36, 255))
    c = quad((x, y, z), 0.55 * s, 0.55 * s)
    extrude_dir(img, cam, c, tex, 0.12, (0, 0, 1.0), steps=3, side=(22, 20, 19), opacity=op)

_G12 = {}
def _g12_words():
    if not _G12:
        _G12["head"] = tiles_crop(["THE KIND HACKERS USE", "TO BREAK INTO"], 200, hl={5},
                                  color=(30, 27, 26, 255), cond=0.65)
    return _G12

def g12(t):
    """макеты падают с потолка, подписи встают под ними, маркер приходит вместе со словом"""
    cam = Cam(0.0, 1.55, 0.22 * t, 0.0)
    img = room(cam)
    wd = _g12_words()
    # заголовок: висит на тросах, d≈11, центр 3.25 м, капитель 0.56 м; сетка 50.80: x 28-93 %, y 10-33 %
    place_words(img, cam, t, wd["head"], (1.15, 3.25, 11.0), 0.0, 0.50 / (CAP * 200),
                [-1.0] * 7, depth=0.14, side=(18, 16, 15), hang=True, wire_per_word=2)
    # макеты на 12.3 м (сетка 50.80): банк x 10-35 % → X≈-3.4, больница 38-61 % → X≈0,
    # ЛЭП 70-96 % → X≈4.0; «+» над больницей — её же крест на крыше, отдельных плюсов нет
    Zm = 12.3
    maket(img, cam, t, "bank", -3.4, Zm, 3.3, 0.133)
    label(img, cam, t, "BANKS", -3.4, Zm - 0.6, 0.233)
    maket(img, cam, t, "hospital", 0.0, Zm, 3.1, 0.533)
    label(img, cam, t, "HOSPITALS", 0.0, Zm - 0.6, 0.633)
    maket(img, cam, t, "power", 3.7, Zm, 3.8, 1.0)
    label(img, cam, t, "POWER GRIDS", 3.55, Zm - 0.6, 1.1, hl={1}, start_each=[1.1, 1.5])
    return img

SCENES = {"G02": (g02, 3.8), "G10": (g10, 4.0), "G12": (g12, 3.8)}

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
