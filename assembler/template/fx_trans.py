#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПЕРЕХОДЫ МЕЖДУ СЦЕНАМИ ПО ЕГО ОБРАЗЦУ: мозаика плиток · разлёт панелей ·
диагональный вайп. Собирает КЛИП СЦЕНЫ ЦЕЛИКОМ: сначала переход с кадра
прошлой сцены на свой, потом обычный плавный зум до конца сцены.

    python3 fx_trans.py <кадр прошлой сцены> <кадр своей сцены> <куда.mp4> \\
        --kind mosaic|panels|wipe|depth|tear --seconds 11.5 [--trans 1.4] [--channel ПЛАНЕТА]
    python3 fx_trans.py - <кадр своей сцены> <куда.mp4> --kind sticker \\
        --seconds 11.5 --channel «5 МИНУТ» [--words «ФАКТ,ИТОГ»]

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
  flash   (A73 с полки библиотеки, назван им 06.11) — кадр вспыхивает в белое,
          и из вспышки выходит следующий. Самый короткий вид, 0,6 с: под
          поворот сюжета, где смена темы должна быть резкой.
  sticker (G13 с полки прототипа «белый зал», принят им 11.11 — «раскатать
          на наш сборщик новостей, минимум один раз на видеоряд, на каждом
          канале, но в разных цветовых гаммах») — НЕ переход, а НАКЛЕЙКА
          поверх кадра сцены: слово влетает сразу КРУПНЕЕ конечного размера
          на 12-13% и за 75 мс оседает ходом outExpo, края рваные (семь
          перекрывающихся прямоугольников), каждый кусок повёрнут на 3-6°, у
          соседних — в разные стороны, второй приходит через 600 мс после
          первого. Числа померены покадрово с его образца и НЕ меняются.
          Гамма наклейки приходит ПО КАНАЛУ из `palitra.py`: ПЛАНЕТА —
          сталь #4a90e2, «5 МИНУТ» — золото #e0b33a.
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
import random
import re
import shutil
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
FONTS = os.path.join(HERE, "fonts")

W, H, FPS = 1920, 1080, 30
KINDS = ("mosaic", "panels", "wipe", "depth", "tear", "flash", "sticker")
# Длительность самого перехода по умолчанию — замер по образцу.
TRANS_SEC = {"mosaic": 1.6, "panels": 1.3, "wipe": 0.7, "depth": 1.1,
             "tear": 1.3,
             # ЗАСВЕТ (A73 с полки, назван им 06.11) — самый короткий из всех:
             # вспышка держится 0,6 с. Длиннее она читается как брак записи,
             # а не как приём, и на светлом кадре слепит.
             "flash": 0.6,
             # НАКЛЕЙКА (G13, 11.11) — это не переход: кадр сцены виден с
             # первого мгновения. Здесь стоит окно ПРИЛЁТА обеих наклеек
             # (0,45 с до первой + 0,6 с до второй + осадка), чтобы
             # всплывашка не легла поверх летящего слова.
             "sticker": 1.8}

MOS_COLS, MOS_ROWS = 6, 4
PANELS_N = 5
# Потолок сцены для `panels` — см. разбор в main(). Длиннее = flash.
PANELS_MAX_SEC = 10.0
# плита нового кадра в начале перехода — доля экрана, и её снос от центра
DEPTH_S0 = 0.40
DEPTH_DRIFT = (0.045, 0.035)
# разрыв на куски: сколько кусков, сколько кадр ещё цел, толщина кромки
TEAR_PIECES = 7
# ХОД РАЗРЫВА ПОДОБРАН ПО ЛИСТУ КАДРОВ (05.11, первый прогон). Было
# hold 0.16 и разгон ** 1.7: на середине перехода куски отъезжали всего
# на 130 px — на кадре это читалось не как разрыв, а как белая звезда
# трещин поверх ЦЕЛОЙ картинки, и нового кадра в щелях не было видно
# вовсе. Теперь рвёт почти сразу и расходится ровнее: на середине
# щели ~600 px, новый кадр виден, а к концу куски всё равно за краем.
TEAR_HOLD = 0.08
TEAR_EDGE = 15

# ---- НАКЛЕЙКА G13 (11.11). ЧИСЛА ПОМЕРЕНЫ ПОКАДРОВО С ЕГО ОБРАЗЦА — НЕ
# ТРОГАТЬ: приём принят именно в этом виде, «красивее» здесь значит «другой».
STICKER_OVER = 0.125        # прилетает крупнее конечного размера на 12-13%
STICKER_SETTLE = 0.075      # и оседает за 75 мс ходом outExpo
STICKER_AT0 = 0.45          # первая наклейка — после того, как кадр прочитан
STICKER_GAP = 0.60          # вторая приходит через 600 мс после первой
STICKER_ROT = (4.5, -3.5)   # поворот 3-6°, у соседних кусков — в разные стороны
STICKER_PIECES = 7          # рваный край: семь перекрывающихся прямоугольников
STICKER_FSIZE = 190         # кегль исходной текстуры (как в образце)
STICKER_H = 0.155           # высота наклейки — доля кадра
STICKER_POS = ((0.29, 0.63), (0.71, 0.31))   # центры: низ слева, верх справа
STICKER_WORDS = ("ГЛАВНОЕ", "ИТОГ")          # если `--words` не дали
# Контраст слова к фону наклейки считается ЧИСЛОМ (разница яркости по
# Rec.601). Ниже этого — слово уводим в чистый чёрный или чистый белый:
# на золоте «5 МИНУТ» и на стали ПЛАНЕТЫ почти чёрный даёт 166 и 120.
STICKER_MIN_CONTRAST = 90
STICKER_INK = (12, 12, 14)
STICKER_PAPER = (244, 244, 246)
# гамма образца — только для канала, которого нет в палитре
STICKER_BG_БАЗА = (255, 212, 0)
# ЗАМОК КАНАЛА ПОВИДОВЫЙ (11.11). До этого исключение было одно — `flash`;
# наклейку он назвал на ДВА канала, и условие «всё, кроме flash, — только
# ПЛАНЕТА» её бы отбило. None = вид разрешён на всех каналах.
FX_CHANNELS = {"flash": None, "sticker": ("ПЛАНЕТА", "5 МИНУТ")}
DEFAULT_CHANNELS = ("ПЛАНЕТА",)
_LAT_RE = re.compile(r"[A-Za-z]")


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
    # ПОДЛОЖКА — ПРИТЕМНЁННЫЙ НОВЫЙ КАДР, А НЕ ЧЁРНОЕ ПОЛЕ (05.11, дефект
    # найден на листе эффектов, улов `usuario-35`). Плитки A гасли к p=0.30,
    # плитки B зажигались с p=0.22 — на середине перехода экран уходил в
    # ПОЛНЫЙ ЧЁРНЫЙ примерно на 0,3 с, и в ролике это читалось как мигание
    # между сценами. Вид перехода не меняется: плитки те же, порядок тот же,
    # — просто в прорехах теперь виден затемнённый кадр, который и так
    # приедет через мгновение, а не пустота. Плюс B зажигаются раньше (0.12).
    out = Bc.point(lambda v: int(v * 0.32)).convert("RGB")
    gone = int(_smootherstep(min(1.0, p / 0.38)) * n)          # гаснут плитки A
    lit = int(_smootherstep(max(0.0, (p - 0.12) / 0.62)) * n)  # зажигаются B
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
                    "spin": (16 if i % 2 else -13)})
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
        d = far * 1.15 * sp ** 1.2
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


def _flash_frame(p, A, Bc):
    """ЗАСВЕТ (A73): кадр вспыхивает в белое, из вспышки выходит следующий.

    Две фазы с разной крутизной: уход в белое быстрый (0,42 перехода, степень
    0,85), выход из белого чуть медленнее — так глаз успевает прочитать новый
    кадр, а вспышка не выглядит склейкой. Новый кадр выходит с лёгким
    отъездом (1,05 → 1,0): без него выход из белого читается как простое
    проявление, а не как удар.

    Прошлого кадра нет (первая сцена) — просто проявляемся из белого.
    """
    from PIL import Image
    white = Image.new("RGB", (W, H), (255, 255, 255))
    peak = 0.42
    if A is not None and p < peak:
        k = (p / peak) ** 0.85
        return Image.blend(A, white, min(1.0, k))
    q = ((p - peak) / (1.0 - peak)) if A is not None else p
    q = max(0.0, min(1.0, q)) ** 0.8
    im = _zoom_frame(Bc, W, H, 1.0 + 0.05 * (1.0 - q)) if q < 0.999 else Bc
    return Image.blend(white, im, q)


# ------------------------------------------------------------ наклейка G13
def _out_expo(t):
    """Ход осадки из прототипа «белый зал» (`zal_core.out_expo`). ПЕРЕНЕСЁН
    СЮДА, А НЕ ИМПОРТИРОВАН: `skills/prototypes/` в облако не уезжает, и
    импорт оттуда развалил бы сборку на раннере."""
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return 1.0 if t >= 1 else 1 - pow(2, -10 * t)


def _norm_chan(c):
    """Имя канала как в палитре: регистр не важен, «Ё»=«Е», синонимы («5МИНУТ»,
    «ОЛЬКА НОВОСТИ») разбирает `palitra.kanal`."""
    s = str(c or "").strip().upper().replace("Ё", "Е")
    try:
        import palitra
        k = palitra.kanal(s)
        if k:
            return k.upper().replace("Ё", "Е")
    except Exception:
        pass
    return s


def _lum(c):
    """Яркость по Rec.601 — ею и меряем контраст слова к фону наклейки."""
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _sticker_colors(channel):
    """(фон наклейки, цвет слова, разница яркости) — ГАММА ПРИХОДИТ ПО КАНАЛУ.

    Цвета НЕ изобретаются здесь: берётся акцент канала из `palitra.py` —
    того же единственного источника, откуда их берут субтитры, дашборд
    упаковки и рисованные кадры (ПЛАНЕТА — сталь, «5 МИНУТ» — золото).
    В образце наклейка жёлтая (255,212,0); этот цвет остаётся только для
    канала, которого в палитре ещё нет.
    """
    bg = STICKER_BG_БАЗА
    try:
        import palitra
        bg = tuple(palitra.accent(channel, inache=STICKER_BG_БАЗА))
    except Exception as e:
        print("  наклейка: палитра недоступна (%s) — гамма образца" % e,
              file=sys.stderr)
    fg = (STICKER_INK if abs(_lum(bg) - _lum(STICKER_INK))
          >= abs(_lum(bg) - _lum(STICKER_PAPER)) else STICKER_PAPER)
    d = abs(_lum(bg) - _lum(fg))
    if d < STICKER_MIN_CONTRAST:
        fg = (0, 0, 0) if _lum(bg) > 128 else (255, 255, 255)
        d = abs(_lum(bg) - _lum(fg))
        print("  наклейка: слово уведено в предел — контраст к фону был мал",
              file=sys.stderr)
    return tuple(bg) + (255,), tuple(fg) + (255,), d


def _sticker_tex(word, bg, fg, fsize=STICKER_FSIZE):
    """Текстура наклейки с РВАНЫМ КРАЕМ (перенос `zal_core.sticker_tex`).

    Край рвут семь перекрывающихся прямоугольников со случайной высотой.
    Зерно случайности — crc32 слова, а НЕ `hash()` как в прототипе: у
    `hash()` в Python 3 соль своя на каждый процесс, и один и тот же ролик
    пересобирался бы с разным краем (а кадры мы считаем в несколько
    процессов — край разъехался бы прямо внутри клипа).
    """
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(os.path.join(FONTS, "ArialBlack.ttf"), fsize)
    b = ImageDraw.Draw(Image.new("RGBA", (8, 8))).textbbox((0, 0), word, font=f)
    pw = int(b[2] - b[0] + fsize * 0.52)
    ph = int(b[3] - b[1] + fsize * 0.40)
    img = Image.new("RGBA", (max(8, pw), max(8, ph)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rnd = random.Random(zlib.crc32(word.encode("utf-8")))
    d.rectangle([0, ph * 0.04, pw, ph * 0.96], fill=bg)
    for i in range(STICKER_PIECES):
        x0 = pw * i / float(STICKER_PIECES)
        d.rectangle([x0, ph * rnd.uniform(0, 0.05),
                     x0 + pw / float(STICKER_PIECES),
                     ph * (1.0 - rnd.uniform(0, 0.05))], fill=bg)
    d.text(((pw - (b[2] - b[0])) / 2.0 - b[0],
            (ph - (b[3] - b[1])) / 2.0 - b[1]), word, font=f, fill=fg)
    return img


def _sticker_build(words, channel):
    """Список (текстура, когда прилетает, поворот, центр) — считается ОДИН раз
    на весь клип: поворот и масштаб потом делаются по готовой текстуре."""
    ws = list(words or ())[:2]
    while len(ws) < 2:
        ws.append(STICKER_WORDS[len(ws)])
    bg, fg, d = _sticker_colors(channel)
    print("  наклейка: канал «%s», фон rgb%s, слово rgb%s, контраст %.0f"
          % (channel or "?", bg[:3], fg[:3], d), file=sys.stderr)
    return [(_sticker_tex(w, bg, fg), 0.0, STICKER_ROT[i % 2],
             STICKER_POS[i % 2]) for i, w in enumerate(ws)]


def _sticker_times(seconds):
    """Когда прилетает каждая наклейка. На короткой сцене окно поджимается,
    иначе вторая наклейка не успела бы появиться вовсе."""
    at0 = STICKER_AT0
    if seconds < STICKER_AT0 + STICKER_GAP + 0.6:
        at0 = max(0.15, seconds - STICKER_GAP - 0.6)
    return [at0, at0 + STICKER_GAP]


def _sticker_frame(i, total, zoom, stickers):
    """Кадр сцены (с обычным плавным зумом) + наклейки поверх него."""
    from PIL import Image, ImageFilter
    q = i / float(max(1, total - 1))
    out = _zoom_frame(_ST["base"], W, H, 1.0 + zoom * _smootherstep(q))
    t = i / float(FPS)
    for tex, t0, rot, (cx, cy) in stickers:
        if t < t0:
            continue
        k = 1.0 + STICKER_OVER * (1.0 - _out_expo((t - t0) / STICKER_SETTLE))
        h = max(8, int(round(H * STICKER_H * k)))
        w = max(8, int(round(h * tex.width / float(tex.height))))
        im = tex.resize((w, h), Image.LANCZOS).rotate(
            rot, resample=Image.BICUBIC, expand=True)
        x = int(round(W * cx - im.width / 2.0))
        y = int(round(H * cy - im.height / 2.0))
        al = im.getchannel("A")
        # тень: без неё наклейка лежит в одной плоскости с кадром и читается
        # как напечатанная на нём, а не наклеенная сверху
        sh = al.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.45))
        out.paste(Image.new("RGB", im.size, (0, 0, 0)), (x + 10, y + 14), sh)
        out.paste(im.convert("RGB"), (x, y), al)
    return out


# ------------------------------------------------------------------- сборка
_ST = {}


def _init(state):
    _ST.update(state)


def _one(arg):
    i, total, tf, kind, zoom, out_dir = arg
    from PIL import Image
    if kind == "sticker":
        # НАКЛЕЙКА ИДЁТ НА ВСЮ СЦЕНУ, а не на первые кадры: это не переход,
        # делить клип на «переход + зум» здесь нечем.
        im = _sticker_frame(i, total, zoom, _ST.get("stick") or [])
    elif i < tf:
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
        elif kind == "flash":
            im = _flash_frame(p, _ST["A"], _ST["B"])
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


def render_frames(prev_img, img, out_dir, kind, seconds, trans, zoom=0.10,
                  words=(), channel=""):
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
    # наклейки считаются ОДИН раз на весь клип (11.11)
    stick = []
    if kind == "sticker":
        ts = _sticker_times(seconds)
        stick = [(tex, ts[i], rot, pos) for i, (tex, _t, rot, pos)
                 in enumerate(_sticker_build(words, channel))]
    st = {"A": A, "B": B, "Bg": Bg, "base": base, "oo": oo, "oi": oi,
          "Ab": Ab, "pieces": pieces, "tfar": tfar, "stick": stick}
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
    ap.add_argument("--words", default="",
                    help="слова наклеек через запятую, по-русски и "
                         "заглавными (вид `sticker`)")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args()

    # ЗАСВЕТ РАБОТАЕТ НА ЛЮБОМ КАНАЛЕ (06.11), НАКЛЕЙКА — на ПЛАНЕТЕ и
    # «5 МИНУТ» (его слово 11.11), остальные виды — ПЛАНЕТА (03.11).
    # Замок повидовый, как в `fx_put.py`, таблица — `FX_CHANNELS` выше.
    _allow = FX_CHANNELS.get(a.kind, DEFAULT_CHANNELS)
    if _allow is not None and _norm_chan(a.channel) not in \
            tuple(_norm_chan(c) for c in _allow):
        print("!! вид «%s» разрешён только на канале %s (его слово). "
              "Канал «%s» — не ставлю."
              % (a.kind, " / ".join(_allow), a.channel), file=sys.stderr)
        return 2
    # СЛОВА НАКЛЕЕК — ПО-РУССКИ И ЗАГЛАВНЫМИ (11.11). Латиница на наклейке
    # ловится здесь, а не глазом на дашборде: запрет на нерусский текст в
    # кадре общий по сборщику, а правок после `ship.sh` не бывает.
    _words = ()
    if a.kind == "sticker":
        _words = tuple(w.strip().upper() for w
                       in str(a.words or "").replace(";", ",").split(",")
                       if w.strip())
        _lat = [w for w in _words if _LAT_RE.search(w)]
        if _lat:
            print("!! слово наклейки не по-русски: %s — не ставлю"
                  % ", ".join(_lat), file=sys.stderr)
            return 2
    prev = "" if a.prev in ("-", "") else a.prev
    if prev and not os.path.isfile(prev):
        prev = ""
    if not os.path.isfile(a.img):
        sys.exit("нет файла: %s" % a.img)
    # ПОТОЛОК ДЛИТЕЛЬНОСТИ ДЛЯ `panels` (10.11, два провала сборки ПЛАНЕТЫ).
    # Приём задуман на сцены 6,3-8,6 с. На сцене 15,4 с он не падает, а ВИСИТ:
    # каждый кадр разворачивает пять панелей перспективой, на раннере с одним
    # свободным ядром это 17,5 минуты вместо 1,5-2, шард срезается лимитом, и
    # без его кадров `assemble` не доделывается. Два прогона (42822100958 и
    # 42837461101) потеряны целиком именно так — цена одной сцены.
    # Поэтому на длинной сцене молча подменяем на ЗАСВЕТ: он разрешён на всех
    # каналах и считается за секунды. Ровно это вкладка делала руками.
    if a.kind == "panels" and a.seconds > PANELS_MAX_SEC:
        print("!! panels на сцене %.1f с (потолок %.1f) — ставлю flash: "
              "на длинной сцене panels вешает ffmpeg и срезается лимитом"
              % (a.seconds, PANELS_MAX_SEC), file=sys.stderr)
        a.kind = "flash"
    trans = a.trans or TRANS_SEC[a.kind]
    if a.seconds < trans + 1.0:
        trans = max(0.4, a.seconds - 1.0)

    tmp = tempfile.mkdtemp(prefix="fxt_")
    try:
        total, tf = render_frames(prev, a.img, tmp, a.kind, a.seconds, trans,
                                  a.zoom, _words, a.channel)
        cmd = [a.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(FPS), "-i", os.path.join(tmp, "f_%05d.jpg"),
               "-an", "-t", "%.3f" % a.seconds,
               "-c:v", "libx264", "-preset", "veryfast",
               "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
               "-pix_fmt", "yuv420p", a.out]
        # ffmpeg не висит молча: шард всё равно срежут лимитом, но тогда в
        # журнале не остаётся причины. Потолок — вчетверо от длины сцены, но
        # не меньше 300 с (10.11).
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=max(300.0, a.seconds * 4))
        except subprocess.TimeoutExpired:
            print("FAIL: ffmpeg не ответил за %.0f с на сцене %.1f с, вид «%s»"
                  % (max(300.0, a.seconds * 4), a.seconds, a.kind),
                  file=sys.stderr)
            return 1
        ok = r.returncode == 0 and os.path.isfile(a.out) and os.path.getsize(a.out) > 0
        _что = ("наклейка «%s», прилёт %s"
                % ("+".join(_words or STICKER_WORDS[:2]),
                   " и ".join("%.2f с" % x for x in _sticker_times(a.seconds)))
                ) if a.kind == "sticker" else \
               ("переход «%s» %.1f с" % (a.kind, tf / float(FPS)))
        print(("готово: %s (%s из %.1f с сцены)"
               % (a.out, _что, a.seconds)) if ok
              else ("FAIL\n" + r.stderr[-700:]))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
