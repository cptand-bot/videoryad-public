#!/usr/bin/env python3
"""РВАНЫЙ ШОВ МЕЖДУ ДВУМЯ КАДРАМИ — три направления (21.10.2026).

Сосед `torn_photo.py` делает «тогда/сейчас»: архивная ПОЛОСА в центре и
два разрыва. Здесь другое: ДВА кадра и ОДИН шов между ними, как на сцене
2 ролика «РФ забирает себе» (user, 20.10: «с одной половины Герасимов, с
другой карта, всё — зачем три границы»).

Направления шва (user, 21.10 — «надо сделать такие варианты, разнообразные»):

  vertical    — шов сверху вниз, половины съезжаются слева и справа;
  diagonal    — шов из левого верхнего угла в правый нижний, половины
                приезжают наискось (снизу-слева и сверху-справа);
  horizontal  — шов по горизонту, кадры сходятся сверху и снизу.

Край во всех трёх случаях процедурный: крупная волна + зазубрины +
волокна, белая кромка переменной ширины и тень от верхнего листа. Для
наклонных швов маска строится на большом квадратном холсте и
поворачивается — так один и тот же генератор края работает на любой угол,
и зубцы не «причёсываются» масштабированием.

  python3 torn_split.py <режим> <A.jpg> <B.jpg> <out.jpg|out.mp4> [секунды]
"""
import functools
import math
import os
import random
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torn_photo as tp
import style_cards as sc
import cinematic as cn
from PIL import ImageFilter

W, H, FPS = 1920, 1080, 25
MODES = ("vertical", "diagonal", "horizontal")


def _angle(mode):
    """Угол поворота вертикальной маски, градусы (PIL — против часовой)."""
    if mode == "vertical":
        return 0.0
    if mode == "horizontal":
        return 90.0
    if mode == "diagonal":
        # шов идёт ПО ДИАГОНАЛИ КАДРА — из левого верхнего угла в правый
        # нижний. Вертикаль нужно завалить на 90°-atan(H/W), а не на
        # atan(H/W): иначе линия выходит почти отвесной и уходит в другую
        # сторону (поймано глазами 21.10 на первой же пробе).
        return math.degrees(math.atan2(W, H))
    raise ValueError(f"режим шва неизвестен: {mode}")


@functools.lru_cache(maxsize=8)
def _masks(mode, seed, size=(W, H), amp=46, teeth=11, edge_px=17):
    """Маска «что лежит по ту сторону шва», кромка и тень — для режима.

    Кэшируется: форма шва за клип не меняется, а поворот холста под
    наклонный шов стоит дороже самого кадра — без кэша рендер семи
    секунд уходил в минуты.
    """
    w, h = size
    S = int(math.hypot(w, h)) + 80            # холст с запасом под поворот
    xs = tp._edge(S, S // 2, seed, amp, teeth, fibers=True)

    big = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(big)
    for y in range(S):
        d.line([(int(xs[y]), y), (S, y)], fill=255)
    band = tp._edge_band((S, S), xs, edge_px, seed)

    ang = _angle(mode)
    if ang:
        big = big.rotate(ang, resample=Image.BICUBIC, center=(S / 2, S / 2))
        band = band.rotate(ang, resample=Image.BICUBIC, center=(S / 2, S / 2))
    x0, y0 = (S - w) // 2, (S - h) // 2
    box = (x0, y0, x0 + w, y0 + h)
    m = big.crop(box)
    bd = band.crop(box)
    sh = m.filter(ImageFilter.GaussianBlur(16))
    return m, bd, sh


def _shift_vector(mode):
    """Куда уезжает дальняя половина до стыковки (единичный вектор)."""
    if mode == "vertical":
        return (1.0, 0.0)
    if mode == "horizontal":
        return (0.0, 1.0)
    n = math.hypot(H, W)
    return (H / n, -W / n)                    # перпендикуляр к диагонали


def _move(img, dx, dy):
    return img.transform(img.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy),
                         resample=Image.BILINEAR)


def _fit(path, zoom=1.0, shift=0.0, size=(W, H)):
    w, h = size
    im = Image.open(path).convert("RGB")
    k = max(w / im.width, h / im.height) * zoom
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    free = max(0, im.width - w)
    x = int(free * (0.5 + shift / 2.0))
    y = max(0, (im.height - h) // 2)
    return im.crop((x, y, x + w, y + h))


def torn_split(out=None, *, mode="vertical", a_path="", b_path="",
               a_shift=0.0, b_shift=0.0, title="", subtitle="",
               watermark="", seed=23, zoom=1.0, offset=0.0, size=(W, H),
               labels=True):
    """Кадр: A по одну сторону рваного шва, B по другую.

    offset 0..1 — насколько дальняя половина ещё не доехала (для клипа).
    """
    w, h = size
    a = _fit(a_path, zoom, a_shift, size)
    b = _fit(b_path, zoom, b_shift, size)
    m, band, sh = _masks(mode, seed, size)

    if offset:
        vx, vy = _shift_vector(mode)
        d = offset * math.hypot(w, h) * 0.55
        m = _move(m, vx * d, vy * d)
        band = _move(band, vx * d, vy * d)
        sh = _move(sh, vx * d, vy * d)
        b = _move(b, vx * d, vy * d)

    mn = (np.asarray(m, np.float32) / 255.0)[..., None]
    shn = (np.asarray(sh, np.float32) / 255.0)[..., None]
    base = np.asarray(a, np.float32) * (1.0 - 0.62 * np.clip(shn - mn, 0, 1))
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    im.paste(b, (0, 0), m)

    paper = Image.new("RGB", size, (242, 240, 234))
    im.paste(paper, (0, 0), band)

    if labels and (title or subtitle or watermark):
        _labels(im, title, subtitle, watermark)
    if out:
        im.save(out, quality=94)
    return im


def _labels(im, title, subtitle, watermark):
    d = ImageDraw.Draw(im, "RGBA")
    if title:
        d.rectangle((0, 0, 980, 230), fill=(8, 8, 9, 150))
        d.text((96, 74), title, font=tp._f(tp.F_HEAD, 52), fill=(255, 255, 255, 255))
    if subtitle:
        d.text((96, 142), subtitle, font=tp._f(tp.F_HEAD, 34), fill=(214, 214, 218, 235))
    if watermark:
        f = tp._f(tp.F_HEAD, 26)
        d.text((W - 60 - d.textlength(watermark, font=f), H - 58), watermark,
               font=f, fill=(210, 210, 214, 120))


def torn_split_clip(out_mp4, *, seconds=7.0, fps=FPS, hit_at=1.5, zoom_to=1.02,
                    ffmpeg="ffmpeg", **kw):
    """Движение: дальняя половина приезжает перпендикулярно шву и встаёт,
    дальше весь кадр едет медленным зумом (без тряски — правило 19.10)."""
    kw.pop("out", None)
    tmp = tempfile.mkdtemp()
    n = int(seconds * fps)
    for i in range(n):
        t = i / fps
        p = min(1.0, max(0.0, t / hit_at))
        e = 1 - (1 - p) ** 3
        zoom = 1.0 + (zoom_to - 1.0) * min(1.0, t / max(0.1, seconds))
        torn_split(os.path.join(tmp, f"{i:04d}.jpg"), offset=(1 - e), zoom=zoom, **kw)
    cmd = [ffmpeg, "-v", "error", "-framerate", str(fps), "-i",
           os.path.join(tmp, "%04d.jpg"), "-c:v", "libx264", "-preset", "medium",
           "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "2", "-y", out_mp4]
    subprocess.run(["nice", "-n", "19"] + cmd, check=True)
    return out_mp4



# ─────────────── ЛЮБОЕ ФОТО — ЧЕРЕЗ ШОВ (user, 21.10) ────────────────────
# «Все фотографии, которые ты будешь брать, делай вот этими швами, с этим
# эффектом». Второго кадра для шва обычно нет, поэтому вторую половину
# делаем из самого снимка: крупный фрагмент рядом с общим планом. Это
# классическая пара «общий план + деталь», она же решает проблему мёртвого
# фото на длинной сцене.

def _focus_auto(path, part=0.52):
    """Где на снимке самое «насыщенное» место — туда и наводим деталь.

    Без распознавания лиц (opencv в системе нет и ставить его ради этого
    незачем): берём карту локальной детальности — сумму перепадов яркости —
    и ищем окно нужного размера с максимумом. На портрете это почти всегда
    лицо, на технике — сама техника, на карте — подписи и значки. Центр
    кадра как точка по умолчанию давал деталь «мимо героя» (поймано 21.10
    на снимке Лукашенко: в деталь попал кусок интерьера).
    """
    im = Image.open(path).convert("L")
    small = im.resize((160, max(1, int(160 * im.height / im.width))), Image.BILINEAR)
    a = np.asarray(small, np.float32)
    gx = np.abs(np.diff(a, axis=1, prepend=a[:, :1]))
    gy = np.abs(np.diff(a, axis=0, prepend=a[:1, :]))
    g = gx + gy
    ww = max(2, int(small.width * part))
    hh = max(2, int(small.height * part))
    ii = np.cumsum(np.cumsum(g, 0), 1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    best, bxy = -1.0, (0.5, 0.5)
    for y in range(0, small.height - hh + 1, 4):
        for x in range(0, small.width - ww + 1, 4):
            v = (ii[y + hh, x + ww] - ii[y, x + ww] - ii[y + hh, x] + ii[y, x])
            if v > best:
                best = v
                bxy = ((x + ww / 2) / small.width, (y + hh / 2) / small.height)
    return bxy


def _detail(path, part=0.52, focus=(0.5, 0.42)):
    """Крупный фрагмент снимка: кроп доли кадра вокруг точки интереса."""
    im = Image.open(path).convert("RGB")
    cw, ch = int(im.width * part), int(im.height * part)
    cx = int(im.width * focus[0] - cw / 2)
    cy = int(im.height * focus[1] - ch / 2)
    cx = max(0, min(im.width - cw, cx))
    cy = max(0, min(im.height - ch, cy))
    return im.crop((cx, cy, cx + cw, cy + ch))


def _step_zoom(p, amp, steps=3, rise=0.80):
    """МЕДЛЕННЫЙ ход — остановка — снова медленный ход.

    История правок, чтобы не вернуть обратно:
      1-я версия — четверть ступени на наезд, ease-out: «дрык, стоп»;
      2-я версия — две трети, smoothstep: всё ещё заметен старт;
      3-я (эта) — 80% ступени на ход и smootherstep (6t⁵-15t⁴+10t³):
        скорость в начале и конце хода равна нулю ВМЕСТЕ С УСКОРЕНИЕМ,
        поэтому глаз не ловит ни трогания, ни остановки.
    User, 21.10: «просто медленно идёт зум, медленно. Потом раз,
    остановился. Потом опять медленно. Рывки не дают эффекта зрителю».
    """
    q = max(0.0, min(1.0, p)) * steps
    k = min(steps - 1, int(q))
    frac = q - k
    x = min(1.0, frac / rise)
    e = x * x * x * (x * (x * 6 - 15) + 10)      # smootherstep
    return 1.0 + amp * (k + e) / steps


def photo_seam(out=None, *, photo="", mode=None, side="detail", title="",
               subtitle="", watermark="", seed=23, part=0.52,
               focus="auto", zoom=1.0, offset=0.0, second=None):
    """Одно фото, поданное через рваный шов: общий план и крупный фрагмент.

    second — путь ко второму снимку, если он есть; тогда деталь не нужна.
    mode   — шов; None = выбирается по seed (вертикаль или диагональ),
             чтобы соседние сцены не повторяли друг друга.
    """
    import tempfile
    if mode is None:
        mode = ("vertical", "diagonal")[seed % 2]
    if focus == "auto":
        focus = _focus_auto(photo, part)
    if second:
        b_path = second
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        _detail(photo, part, focus).save(tmp.name, quality=95)
        b_path = tmp.name
    a, b = (photo, b_path) if side == "detail" else (b_path, photo)
    return torn_split(out, mode=mode, a_path=a, b_path=b, title=title,
                      subtitle=subtitle, watermark=watermark, seed=seed,
                      zoom=zoom, offset=offset)


def photo_seam_clip(out_mp4, *, seconds=7.0, fps=FPS, hit_at=1.4,
                    zoom_amp=0.06, steps=3, ffmpeg="ffmpeg", **kw):
    """Фото через шов В ДВИЖЕНИИ: половины доезжают (без дёрганья), дальше
    ступенчатый наезд до конца куска."""
    import os
    import tempfile as _tf
    kw.pop("out", None)
    tmp = _tf.mkdtemp()
    n = int(seconds * fps)
    for i in range(n):
        t = i / fps
        p = min(1.0, max(0.0, t / hit_at))
        e = 1 - (1 - p) ** 3
        tail_p = 0.0 if t <= hit_at else (t - hit_at) / max(0.1, seconds - hit_at)
        photo_seam(os.path.join(tmp, f"{i:04d}.jpg"), offset=(1 - e),
                   zoom=_step_zoom(tail_p, zoom_amp, steps), **kw)
    subprocess.run(["nice", "-n", "19", ffmpeg, "-v", "error", "-framerate", str(fps),
                    "-i", os.path.join(tmp, "%04d.jpg"), "-c:v", "libx264", "-preset",
                    "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "2",
                    "-y", out_mp4], check=True)
    return out_mp4



# ───────────── РАЗОРВАННОЕ ФОТО: куски поверх целого кадра ──────────────
def torn_apart(out=None, *, photo="", cuts=(0.34, 0.66), seed=23, under=0.52,
               tilt=1.2, kick="", title="", subtitle="",
               watermark="ДИПЛОМАТИЯ СИЛЫ", seconds=7.0, t=None, sfx=None,
               spread=None, hold=1.3):
    """Фото рвётся на куски, под ними остаётся тот же кадр целиком.

    Идея пользователя (21.10): «берёт фотографию и вот этими рваными швами
    её как бы разрывает, а внизу остаётся та же фотография, исходник».

    cuts   — где проходят разрывы (доли ширины); 1 разрыв = две половины
    spread — насколько разъехались куски; None = считается от t:
             кадр держится целым `hold` секунд, затем рвётся за 0,9 с
    under  — насколько притушен нижний, целый слой
    """
    if spread is None:
        if t is None:
            spread = 1.0
        else:
            x = max(0.0, min(1.0, (t - hold) / 0.9))
            spread = x * x * x * (x * (x * 6 - 15) + 10)   # тот же плавный профиль
            if 0 < x < 0.12:
                sc._ev(sfx, t, "accent")
    base = cn._fit(photo)
    # НИЖНИЙ СЛОЙ — ТОТ ЖЕ КАДР, но мягче и темнее: так щель читается как
    # «под разрывом лежит исходник», а не как тёмная грязь (правка 21.10)
    under_im = base.filter(ImageFilter.GaussianBlur(5))
    under_im = Image.fromarray(np.clip(np.asarray(under_im, np.float32) * under,
                                       0, 255).astype(np.uint8))
    im = under_im.copy()

    # линии разрыва
    edges = [tp._edge(H, W * c, seed + i * 37, 44, 11, True) for i, c in enumerate(cuts)]
    bounds = [None] + edges + [None]

    # куски: крайние уезжают сильнее, средний почти на месте
    n = len(cuts) + 1
    for k in range(n):
        left, right = bounds[k], bounds[k + 1]
        m = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(m)
        for y in range(H):
            x0 = 0 if left is None else int(left[y])
            x1 = W if right is None else int(right[y])
            if x1 > x0:
                d.line([(x0, y), (x1, y)], fill=255)

        piece = Image.new("RGB", (W, H), (0, 0, 0))
        piece.paste(base, (0, 0), m)

        # вектор разъезда: наружу от центра, с лёгким наклоном
        c = (k - (n - 1) / 2) / max(1, (n - 1) / 2)
        dx = int(c * 118 * spread)
        dy = int(abs(c) * 34 * spread + 10 * spread)
        ang = tilt * c * spread

        if ang:
            piece = piece.rotate(ang, resample=Image.BICUBIC, center=(W // 2, H // 2))
            m = m.rotate(ang, resample=Image.BICUBIC, center=(W // 2, H // 2))
        piece = piece.transform((W, H), Image.AFFINE, (1, 0, -dx, 0, 1, -dy), resample=Image.BILINEAR)
        m = m.transform((W, H), Image.AFFINE, (1, 0, -dx, 0, 1, -dy), resample=Image.BILINEAR)

        # тень под куском
        sh = m.filter(ImageFilter.GaussianBlur(16))
        a = np.asarray(im, np.float32) * (1 - 0.72 * spread *
                                          (np.asarray(sh, np.float32) / 255.0)[..., None])
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        im.paste(piece, (0, 0), m)

        # белая кромка по рваным краям куска
        band = Image.new("L", (W, H), 0)
        for xs in (left, right):
            if xs is None:
                continue
            b = tp._edge_band((W, H), xs, 15, seed)
            b = b.rotate(ang, resample=Image.BICUBIC, center=(W // 2, H // 2)) if ang else b
            b = b.transform((W, H), Image.AFFINE, (1, 0, -dx, 0, 1, -dy), resample=Image.BILINEAR)
            band = Image.fromarray(np.maximum(np.asarray(band), np.asarray(b)))
        band = Image.fromarray((np.asarray(band, np.float32) *
                                (np.asarray(m, np.float32) / 255.0) * spread).astype(np.uint8))
        im.paste(Image.new("RGB", (W, H), (242, 240, 234)), (0, 0), band)

    im = cn._head(im, kick, title, subtitle, watermark, t)
    if out:
        im.save(out, quality=94)
    return im



if __name__ == "__main__":
    mode, a, b, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    secs = float(sys.argv[5]) if len(sys.argv) > 5 else 7.0
    if out.endswith(".mp4"):
        torn_split_clip(out, seconds=secs, mode=mode, a_path=a, b_path=b)
    else:
        torn_split(out, mode=mode, a_path=a, b_path=b)
    print("готово:", out)
