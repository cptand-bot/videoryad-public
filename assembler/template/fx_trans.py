#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПЕРЕХОДЫ МЕЖДУ СЦЕНАМИ ПО ЕГО ОБРАЗЦУ: мозаика плиток · разлёт панелей ·
диагональный вайп. Собирает КЛИП СЦЕНЫ ЦЕЛИКОМ: сначала переход с кадра
прошлой сцены на свой, потом обычный плавный зум до конца сцены.

    python3 fx_trans.py <кадр прошлой сцены> <кадр своей сцены> <куда.mp4> \\
        --kind mosaic|panels|wipe|depth|tear --seconds 11.5 [--trans 1.4] [--channel ПЛАНЕТА]

Образец пользователя — `D:\\ЗАГРУЗКИ\\Эффекты-1\\Эффекты-1.mp4`, четыре эффекта.
Третий («врезка + круги») принят 03.11 и живёт в `fx_inset.py`; здесь — три
остальных, разобранные по кадрам того же файла:

  mosaic  (в образце 1,8-4,0 с) — кадр рассыпается на сетку 6x4, плитки гаснут,
          потом по одной зажигаются плитками СЛЕДУЮЩЕГО кадра: зелёная рамка и
          светло-зелёный налёт, как на мониторе. Когда сетка собрана, налёт и
          рамки гаснут и остаётся чистый кадр.
  panels  (6,3-8,6 с) — кадр собран из вертикальных панелей, которые стоят к нам
          ребром и разворачиваются: каждая панель — трапеция с перспективой,
          разворот идёт слева направо с запаздыванием.
  wipe    (17,2-18,2 с) — новый кадр въезжает по диагонали, на стыке светлая
          линия с мягким ореолом.
  tear    (его принятый элемент второго сборщика, перенесён 05.11) — прошлый
          кадр рвётся на семь кусков с толстой бумажной кромкой, все куски
          уносит за край, под ними остаётся новый кадр как есть.
  depth   (наш, 05.11, в образце его нет) — новый кадр ВЫХОДИТ ИЗ ГЛУБИНЫ
          плитой со светлой кромкой и тенью, а прошлый кадр остаётся на
          месте и теряет резкость с затемнением. Это ход камеры, а не
          геометрия: ни сетки (mosaic), ни разворота (panels), ни кромки
          поперёк экрана (wipe) — чтобы вид читался своим, а не вариантом.

ПОЧЕМУ ВЕСЬ КЛИП РИСУЕТСЯ ЗДЕСЬ, А НЕ СКЛЕИВАЕТСЯ ИЗ ДВУХ КУСКОВ: склейка двух
mp4 демуксером `concat` требует побитового совпадения параметров и ломает
тайминг при малейшем расхождении, а у нас потом ещё всплывашки, субтитры и
общий concat всего ролика. Здесь один проход кодирования и ровно одна длина —
та, что стоит в сцене. Зум после перехода считается ПОКАДРОВО (дробный `box`),
как в `fx_inset.py`: `zoompan` двигает целыми пикселями и дёргает.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

W, H, FPS = 1920, 1080, 30
KINDS = ("mosaic", "panels", "wipe", "depth", "tear")
# Длительность самого перехода по умолчанию — замер по образцу.
TRANS_SEC = {"mosaic": 1.6, "panels": 1.3, "wipe": 0.7, "depth": 1.1,
             "tear": 1.3}

MOS_COLS, MOS_ROWS = 6, 4
PANELS_N = 5
# плита нового кадра в начале перехода — доля экрана, и её снос от центра
DEPTH_S0 = 0.40
DEPTH_DRIFT = (0.045, 0.035)
# разрыв на куски: сколько кусков, сколько кадр ещё цел, толщина кромки
TEAR_PIECES = 7
TEAR_HOLD = 0.16
TEAR_EDGE = 15


# ---------------------------------------------------------------- общий кадр
def _cover(img, w, h, headroom=1.0):
    """Вписать с перекрытием: кадр накрывает рамку целиком, пропорции целы."""
    from PIL import Image
    k = max(w / img.width, h / img.height) * headroom
    im = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))),
                    Image.LANCZOS)
    l, t = (im.width - w) / 2.0, (im.height - h) / 2.0
    return im.crop((int(l), int(t), int(l) + w, int(t) + h))


def _zoom_frame(base, w, h, z):
    """Кадр плавного зума: окно режется ДРОБНЫМ box, без округления."""
    from PIL import Image
    bw, bh = base.size
    cw, ch = w / z, h / z
    l, t = (bw - cw) / 2.0, (bh - ch) / 2.0
    return base.resize((w, h), Image.BICUBIC, box=(l, t, l + cw, t + ch))


def _smootherstep(p):
    p = min(1.0, max(0.0, p))
    return p * p * p * (p * (p * 6 - 15) + 10)


# ------------------------------------------------------------------ мозаика
def _mosaic_frame(p, A, Bc, Bg, order_out, order_in):
    """Одна плитка = один прямоугольник сетки. p — ход перехода 0…1."""
    from PIL import Image, ImageDraw
    n = MOS_COLS * MOS_ROWS
    cw, ch = W / MOS_COLS, H / MOS_ROWS
    out = Image.new("RGB", (W, H), (0, 0, 0))
    gone = int(_smootherstep(min(1.0, p / 0.30)) * n)          # гаснут плитки A
    lit = int(_smootherstep(max(0.0, (p - 0.22) / 0.58)) * n)  # зажигаются B
    tint = 1.0 - _smootherstep(max(0.0, (p - 0.66) / 0.34))    # налёт и рамки
    draw = ImageDraw.Draw(out)
    for idx in range(n):
        r, c = divmod(idx, MOS_COLS)
        box = (int(c * cw), int(r * ch), int((c + 1) * cw), int((r + 1) * ch))
        if order_in[idx] < lit:
            # НАЛЁТ ГАСНЕТ ПЛАВНО, А НЕ СКАЧКОМ. Первая версия переключала
            # зелёную копию на чистую по порогу 0,5 — на глаз это был щелчок
            # на последней трети перехода (видно на контактном листе: кадр
            # целиком зелёный, следующий целиком чистый).
            if tint <= 0.02:
                out.paste(Bc.crop(box), box[:2])
            elif tint >= 0.98:
                out.paste(Bg.crop(box), box[:2])
            else:
                out.paste(Image.blend(Bc.crop(box), Bg.crop(box), tint),
                          box[:2])
            if tint > 0.02:
                g = int(255 * tint)
                draw.rectangle([box[0], box[1], box[2] - 1, box[3] - 1],
                               outline=(60, g, 90), width=3)
        elif A is not None and order_out[idx] >= gone:
            out.paste(A.crop(box), box[:2])
    return out


# ------------------------------------------------------------------ панели
def _persp_coeffs(dst, src):
    """Коэффициенты PIL PERSPECTIVE: решаем 8x8 методом Гаусса, без numpy
    (на раннере ставится только pillow)."""
    m, rhs = [], []
    for (dx, dy), (sx, sy) in zip(dst, src):
        m.append([dx, dy, 1, 0, 0, 0, -dx * sx, -dy * sx]); rhs.append(sx)
        m.append([0, 0, 0, dx, dy, 1, -dx * sy, -dy * sy]); rhs.append(sy)
    for i in range(8):
        piv = max(range(i, 8), key=lambda r: abs(m[r][i]))
        if abs(m[piv][i]) < 1e-9:
            return None
        m[i], m[piv] = m[piv], m[i]
        rhs[i], rhs[piv] = rhs[piv], rhs[i]
        d = m[i][i]
        m[i] = [v / d for v in m[i]]; rhs[i] /= d
        for r in range(8):
            if r == i:
                continue
            f = m[r][i]
            if f:
                m[r] = [a - f * b for a, b in zip(m[r], m[i])]
                rhs[r] -= f * rhs[i]
    return rhs


def _panels_frame(p, A, Bc):
    """Панели разворачиваются из положения «ребром» слева направо."""
    from PIL import Image
    import math
    out = A.copy() if A is not None else Image.new("RGB", (W, H), (0, 0, 0))
    pw = W / float(PANELS_N)
    for i in range(PANELS_N):
        lag = 0.10 * i                       # запаздывание слева направо
        q = _smootherstep((p - lag) / max(0.05, 1.0 - 0.10 * (PANELS_N - 1)))
        if q <= 0.001:
            continue
        ang = (1.0 - q) * (math.pi / 2.0) * 0.92   # 0 — плашмя к зрителю
        x0, x1 = i * pw, (i + 1) * pw
        cx = (x0 + x1) / 2.0
        half = (pw / 2.0) * math.cos(ang)
        if half < 0.7:
            continue
        # Грубая перспектива: дальняя кромка панели уходит и становится ниже.
        k = 0.38 * math.sin(ang)
        hl = 1.0 - k            # левая кромка
        hr = 1.0 + k * 0.35     # правая кромка
        hl, hr = max(0.05, hl), max(0.05, hr)
        lx, rx = cx - half, cx + half
        quad = [(lx, H / 2.0 - H / 2.0 * hl), (rx, H / 2.0 - H / 2.0 * hr),
                (rx, H / 2.0 + H / 2.0 * hr), (lx, H / 2.0 + H / 2.0 * hl)]
        bx0, bx1 = int(math.floor(min(lx, rx))), int(math.ceil(max(lx, rx)))
        by0 = int(math.floor(min(q2[1] for q2 in quad)))
        by1 = int(math.ceil(max(q2[1] for q2 in quad)))
        bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)
        dst = [(x - bx0, y - by0) for (x, y) in quad]
        src = [(x0, 0), (x1, 0), (x1, H), (x0, H)]
        co = _persp_coeffs(dst, src)
        if not co:
            continue
        piece = Bc.transform((bw, bh), Image.PERSPECTIVE, co, Image.BICUBIC)
        mask = Image.new("L", (bw, bh), 0)
        from PIL import ImageDraw
        ImageDraw.Draw(mask).polygon(dst, fill=255)
        # притемнение на развороте — панель «ловит свет», когда встала плашмя
        if q < 0.98:
            from PIL import ImageEnhance
            piece = ImageEnhance.Brightness(piece).enhance(0.55 + 0.45 * q)
        out.paste(piece, (bx0, by0), mask)
    return out


# -------------------------------------------------------------------- вайп
def _wipe_frame(p, A, Bc):
    """Диагональный заезд нового кадра со светлой линией на стыке."""
    from PIL import Image, ImageDraw, ImageFilter
    e = _smootherstep(p)
    slope = 0.55                       # наклон кромки (вправо-вниз)
    span = W + slope * H
    c = -slope * H + e * (span + 160)  # где кромка пересекает y=0
    out = A.copy() if A is not None else Image.new("RGB", (W, H), (0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(
        [(-10, -10), (c, -10), (c - slope * (H + 20), H + 10), (-10, H + 10)],
        fill=255)
    out.paste(Bc, (0, 0), mask)
    # светлая линия с мягким ореолом — на стыке, поверх обоих кадров
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    gd.line([(c, -10), (c - slope * (H + 20), H + 10)], fill=120, width=26)
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    gd = ImageDraw.Draw(glow)
    gd.line([(c, -10), (c - slope * (H + 20), H + 10)], fill=255, width=4)
    out.paste(Image.new("RGB", (W, H), (255, 255, 255)), (0, 0), glow)
    return out


# -------------------------------------------------------- разрыв на куски
def _tear_seams(seed):
    """Рубленые радиальные швы от центра — по ним кадр и рвётся.

    Шов считается ОДИН РАЗ и используется ДВУМЯ соседними кусками, поэтому
    куски стыкуются без щелей. Если ломать каждый кусок своей ломаной, между
    ними остаётся светлая полоса нового кадра — разрыв виден ещё до разрыва.
    """
    import math
    import random
    rnd = random.Random(seed)
    cx, cy = W * 0.5, H * 0.46
    far = math.hypot(W, H) * 1.25
    seams, step = [], math.tau / TEAR_PIECES
    for i in range(TEAR_PIECES):
        a = i * step + rnd.uniform(-0.16, 0.16)
        pts = []
        for j in range(10):
            r = far * j / 9.0
            aa = a + (0.0 if j == 0 else rnd.uniform(-0.085, 0.085))
            pts.append((cx + math.cos(aa) * r, cy + math.sin(aa) * r))
        seams.append((a, pts))
    return seams, (cx, cy), far


def _tear_pieces(A, seed):
    """Куски прошлого кадра с ЗАПЕЧЁННОЙ бумажной кромкой — считаются один раз.

    Кусок хранится обрезанным по своей рамке, а не во весь кадр: на каждом
    кадре его только поворачивают и сдвигают, и поворот мелкой картинки стоит
    в разы меньше поворота полного 1920x1080.
    """
    import math
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    seams, (cx, cy), far = _tear_seams(seed)
    out, n = [], TEAR_PIECES
    for i in range(n):
        a0, p0 = seams[i]
        a1, p1 = seams[(i + 1) % n]
        if a1 < a0:
            a1 += math.tau
        poly = list(p0)
        for j in range(5):                      # дуга далеко за кадром
            aa = a0 + (a1 - a0) * (j + 1) / 6.0
            poly.append((cx + math.cos(aa) * far * 1.05,
                         cy + math.sin(aa) * far * 1.05))
        poly += list(reversed(p1))
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).polygon(poly, fill=255)
        bb = m.getbbox()
        if not bb:
            continue
        e = TEAR_EDGE + 4
        bb = (max(0, bb[0] - e), max(0, bb[1] - e),
              min(W, bb[2] + e), min(H, bb[3] + e))
        mc = m.crop(bb)
        k = TEAR_EDGE if TEAR_EDGE % 2 else TEAR_EDGE + 1
        grown = mc.filter(ImageFilter.MaxFilter(k))
        band = ImageChops.subtract(grown, mc)
        piece = Image.new("RGB", (bb[2] - bb[0], bb[3] - bb[1]), (0, 0, 0))
        piece.paste(A.crop(bb), (0, 0))
        # КРОМКА БУМАЖНАЯ И ТОЛСТАЯ (21.10, его правка по разлёту кусков:
        # «швы рубленые, чуть толще — как у фотографии, которая разъезжается»).
        piece.paste(Image.new("RGB", piece.size, (242, 240, 234)), (0, 0), band)
        rgba = piece.convert("RGBA")
        rgba.putalpha(grown)
        am = (a0 + a1) / 2.0
        out.append({"img": rgba, "at": (bb[0], bb[1]),
                    "dir": (math.cos(am), math.sin(am)),
                    "spin": (13 if i % 2 else -11)})
    return out, far


def _tear_frame(p, A, pieces, far, Bc):
    """Прошлый кадр рвётся на куски и уносится; под ним — новый кадр КАК ЕСТЬ.

    Три его правила по этому приёму (21.10): улетают ВСЕ куски, центр тоже —
    на месте ничего не держится; нижний слой не затемняем и не размываем;
    куски уходят ЗА КРАЙ полностью, а не застревают у рамки (поэтому ход
    больше диагонали кадра и с разгоном к концу).
    """
    from PIL import Image, ImageFilter
    if p <= TEAR_HOLD or not pieces:
        return (A if A is not None else Bc).copy()
    sp = _smootherstep((p - TEAR_HOLD) / (1.0 - TEAR_HOLD))
    out = Bc.copy()
    for pc in pieces:
        d = far * 1.1 * sp ** 1.7
        ox = pc["dir"][0] * d
        oy = pc["dir"][1] * d - 90 * sp
        ang = pc["spin"] * sp
        im = pc["img"]
        if abs(ang) > 0.3:
            im = im.rotate(ang, resample=Image.BICUBIC, expand=True)
        x = int(round(pc["at"][0] + ox)) - (im.width - pc["img"].width) // 2
        y = int(round(pc["at"][1] + oy)) - (im.height - pc["img"].height) // 2
        if x > W or y > H or x + im.width < 0 or y + im.height < 0:
            continue
        al = im.getchannel("A")
        sh = al.filter(ImageFilter.GaussianBlur(7)).point(lambda v: int(v * 0.5))
        out.paste(Image.new("RGB", im.size, (0, 0, 0)), (x + 14, y + 18), sh)
        out.paste(im.convert("RGB"), (x, y), al)
    return out


# ------------------------------------------------------------------ глубина
def _depth_frame(p, A, Ab, Bc):
    """Новый кадр выходит из глубины плитой, прошлый уходит в расфокус.

    ЗАЧЕМ ИМЕННО ТАК. Зум-аута в канале нет (его слово), поэтому «отъехать»
    прошлым кадром нельзя — глубину даёт РАСФОКУС фона плюс растущая плита с
    тенью: передний план приближается, задний остаётся на месте и размывается.
    Плита идёт не из центра, а с небольшим сносом вправо-вниз — без сноса ход
    читается как обычный зум картинки, а не как движение камеры.
    """
    from PIL import Image, ImageDraw, ImageEnhance
    e = _smootherstep(p)
    if A is None:
        out = Image.new("RGB", (W, H), (8, 10, 12))
    else:
        k = min(1.0, e * 1.3)
        if k <= 0.02 or Ab is None:
            out = A.copy()
        elif k >= 0.98:
            out = Ab.copy()
        else:
            out = Image.blend(A, Ab, k)
        if e > 0.01:
            out = Image.blend(out, Image.new("RGB", (W, H), (0, 0, 0)),
                              0.50 * e)
    s = DEPTH_S0 + (1.0 - DEPTH_S0) * e
    pw = max(2, int(round(W * s)))
    ph = max(2, int(round(H * s)))
    if pw >= W and ph >= H:
        out.paste(Bc, (0, 0))
        return out
    dx = int(round(W * DEPTH_DRIFT[0] * (1.0 - e)))
    dy = int(round(H * DEPTH_DRIFT[1] * (1.0 - e)))
    x0, y0 = (W - pw) // 2 + dx, (H - ph) // 2 + dy
    piece = Bc.resize((pw, ph), Image.BICUBIC)
    # плита, пока она в глубине, стоит в тени — к концу выходит на полный свет
    piece = ImageEnhance.Brightness(piece).enhance(0.80 + 0.20 * e)
    # тень под плитой: без неё плита лежит в одной плоскости с фоном
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([x0 + 10, y0 + 14, x0 + pw + 10, y0 + ph + 14],
                                 fill=(0, 0, 0, int(120 * (1.0 - e))))
    out = Image.alpha_composite(out.convert("RGBA"), sh).convert("RGB")
    out.paste(piece, (x0, y0))
    # светлая кромка — та же строгая черта, что в надписях канала; к концу
    # перехода гаснет, чтобы на сцене остался ЧИСТЫЙ кадр без рамки
    a = int(230 * (1.0 - e) ** 0.7)
    if a > 3:
        ed = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ed).rectangle([x0, y0, x0 + pw - 1, y0 + ph - 1],
                                     outline=(255, 255, 255, a), width=3)
        out = Image.alpha_composite(out.convert("RGBA"), ed).convert("RGB")
    return out


# ------------------------------------------------------------------- сборка
_ST = {}


def _init(state):
    _ST.update(state)


def _one(arg):
    i, total, tf, kind, zoom, out_dir = arg
    from PIL import Image
    if i < tf:
        p = i / float(max(1, tf - 1))
        if kind == "mosaic":
            im = _mosaic_frame(p, _ST["A"], _ST["B"], _ST["Bg"],
                               _ST["oo"], _ST["oi"])
        elif kind == "panels":
            im = _panels_frame(p, _ST["A"], _ST["B"])
        elif kind == "depth":
            im = _depth_frame(p, _ST["A"], _ST.get("Ab"), _ST["B"])
        elif kind == "tear":
            im = _tear_frame(p, _ST["A"], _ST.get("pieces") or [],
                             _ST.get("tfar") or 0.0, _ST["B"])
        else:
            im = _wipe_frame(p, _ST["A"], _ST["B"])
    else:
        q = (i - tf) / float(max(1, total - tf - 1))
        im = _zoom_frame(_ST["base"], W, H, 1.0 + zoom * _smootherstep(q))
    im.save(os.path.join(out_dir, "f_%05d.jpg" % i), quality=95)
    return i


def _workers():
    v = os.environ.get("VIDEORYAD_FX_WORKERS")
    if v:
        return max(1, int(v))
    n = os.cpu_count() or 2
    return max(1, n if os.environ.get("GITHUB_ACTIONS") else min(2, n))


def render_frames(prev_img, img, out_dir, kind, seconds, trans, zoom=0.10):
    import random
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    B = _cover(Image.open(img).convert("RGB"), W, H)
    A = _cover(Image.open(prev_img).convert("RGB"), W, H) if prev_img else None
    # светло-зелёный «мониторный» налёт из образца
    Bg = Image.blend(B, Image.new("RGB", (W, H), (190, 255, 190)), 0.55)
    base = _cover(Image.open(img).convert("RGB"), W, H, headroom=1.12)
    # размытую копию прошлого кадра считаем ОДИН РАЗ на весь переход: полный
    # GaussianBlur по 1920x1080 на каждом кадре стоил бы дороже самой сцены.
    Ab = None
    if kind == "depth" and A is not None:
        from PIL import ImageFilter
        Ab = A.filter(ImageFilter.GaussianBlur(12))
    # куски разрыва тоже считаются ОДИН РАЗ на весь переход
    pieces, tfar = [], 0.0
    if kind == "tear":
        pieces, tfar = _tear_pieces(A if A is not None else B, 20261105)
    n = MOS_COLS * MOS_ROWS
    rnd = random.Random(20261104)
    oo = list(range(n)); rnd.shuffle(oo)
    oi = list(range(n)); rnd.shuffle(oi)
    total = int(round(seconds * FPS))
    tf = min(total - 2, int(round(trans * FPS)))
    st = {"A": A, "B": B, "Bg": Bg, "base": base, "oo": oo, "oi": oi,
          "Ab": Ab, "pieces": pieces, "tfar": tfar}
    args = [(i, total, tf, kind, zoom, out_dir) for i in range(total)]
    nw = min(_workers(), 8)
    if nw > 1 and total > 30:
        import multiprocessing as mp
        try:
            with mp.get_context("fork").Pool(nw, _init, (st,)) as pool:
                for _ in pool.imap_unordered(_one, args, chunksize=6):
                    pass
            return total, tf
        except Exception as e:
            print("  кадры в один поток (%s)" % e, file=sys.stderr)
    _init(st)
    for a in args:
        _one(a)
    return total, tf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prev", help="кадр прошлой сцены (или '-' если его нет)")
    ap.add_argument("img", help="кадр своей сцены")
    ap.add_argument("out")
    ap.add_argument("--kind", default="wipe", choices=KINDS)
    ap.add_argument("--seconds", type=float, default=11.5)
    ap.add_argument("--trans", type=float, default=0.0)
    ap.add_argument("--zoom", type=float, default=0.10)
    ap.add_argument("--channel", default="ПЛАНЕТА")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()

    if a.channel.strip().upper().replace("Ё", "Е") != "ПЛАНЕТА":
        print("!! ЭФФЕКТЫ ТОЛЬКО ДЛЯ КАНАЛА ПЛАНЕТА (его слово 03.11). "
              "Канал «%s» — не ставлю." % a.channel, file=sys.stderr)
        return 2
    prev = "" if a.prev in ("-", "") else a.prev
    if prev and not os.path.isfile(prev):
        prev = ""
    if not os.path.isfile(a.img):
        sys.exit("нет файла: %s" % a.img)
    trans = a.trans or TRANS_SEC[a.kind]
    if a.seconds < trans + 1.0:
        trans = max(0.4, a.seconds - 1.0)

    tmp = tempfile.mkdtemp(prefix="fxt_")
    try:
        total, tf = render_frames(prev, a.img, tmp, a.kind, a.seconds, trans,
                                  a.zoom)
        cmd = [a.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(FPS), "-i", os.path.join(tmp, "f_%05d.jpg"),
               "-an", "-t", "%.3f" % a.seconds,
               "-c:v", "libx264", "-preset", "veryfast",
               "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
               "-pix_fmt", "yuv420p", a.out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.isfile(a.out) and os.path.getsize(a.out) > 0
        print(("готово: %s (переход «%s» %.1f с из %.1f с сцены)"
               % (a.out, a.kind, tf / float(FPS), a.seconds)) if ok
              else ("FAIL\n" + r.stderr[-700:]))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
