# -*- coding: utf-8 -*-
"""ГАЗЕТНАЯ ВЫРЕЗКА — настоящее фото персоны в мультстиле канала.

Два вида, оба утверждены пользователем 06.11:

  `gazeta` — вырезка ПРЯМОУГОЛЬНИКОМ с рваным краем («берут официальное
      фото, режут, как будто вырезка из газеты, вот так вот хаотично
      вырезают»). Его слово по двум цветным образцам: «они 100%, прям
      фотографии… мы должны их утвердить и раскатать на сборщики новостей».

  `figura` — вырезка ПО КОНТУРУ ФИГУРЫ («как бы он обрезан вот прям по
      контуру там головы, и уши там… И вот каёмочка такая, рваная что ли.
      Ободок такой»). Силуэт даёт маска `rembg` (модель `u2net_human_seg`),
      край рвётся шумом, вдоль контура идёт бумажный ободок.

Зачем это вообще: рисовать лица политиков кодом нельзя — три захода 06.11
дали «пять похожих мужчин», узнаваемости нет. Вырезка решает это тем, что
лицо НЕ рисуется: берётся настоящий кадр, а мультстиль держат бумага,
рваный край, обрывки колонок и подпись на оторванной полоске.

ГАММА ПРИХОДИТ ПО КАНАЛУ САМА: фон берётся из `style_cards.canvas()`, то
есть ПЛАНЕТА получает свою чёрную виньетку, «5 МИНУТ» — бордовую,
ДИПЛОМАТИЯ СИЛЫ — зелёную. Своих фоновых цветов здесь нет ни одного.

Рисуется ТОЛЬКО в облаке, как все карточки (его слово 22-23.10).
"""
import math
import os
import random

import numpy as np
from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter,
                 ImageFont, ImageOps)

import cinematic as cn
import style_cards as sc

W, H = sc.W, sc.H
SERIF = os.path.join(sc.NV, "Tinos-Bold.ttf")      # подпись: газетная антиква
BUMAGA = (255, 252, 240)                           # бумага каймы
NEWS_TONE = (228, 220, 198)                        # обрывки колонок

# КЭШ НА ВЕСЬ КЛИП, А НЕ НА КАДР. Рисовальщик зовёт функцию 30 раз в секунду
# (`sc.render_anim`), и всё, что берётся из случайных чисел, ОБЯЗАНО быть
# посчитано один раз: иначе рваный край пересобирается каждый кадр и вместо
# бумаги получается кипящая кромка. Та же причина у маски `rembg` — она
# стоит полторы секунды, и 30 вызовов в секунду сделали бы прогон вечным.
_CACHE = {}


# ───────────────────────────── рваная кромка ────────────────────────────────
def _noise(size, blur, seed):
    rnd = np.random.default_rng(seed)
    n = Image.fromarray(rnd.integers(0, 256, (size[1], size[0]), dtype=np.uint8))
    return np.asarray(n.filter(ImageFilter.GaussianBlur(blur)), np.float32) - 128.0


def ragged(mask, amp=7.0, coarse=3.0, fiber=0.8, seed=1):
    """Рвёт край маски по ЛЮБОМУ контуру: размываем, подмешиваем два слоя
    шума (крупные надрывы и ворс) и режем по порогу. Прямые линии так же
    рвутся, как и силуэт, поэтому вид один и тот же инструмент на оба."""
    soft = np.asarray(mask.filter(ImageFilter.GaussianBlur(amp * 0.85)), np.float32)
    v = soft + _noise(mask.size, coarse, seed) * 1.45 \
             + _noise(mask.size, fiber, seed + 7) * 0.85
    return Image.fromarray(np.where(v > 128, 255, 0).astype(np.uint8), "L") \
                .filter(ImageFilter.GaussianBlur(0.5))


def grow(mask, px):
    """Расширение маски: размытие + низкий порог. Дешевле MaxFilter(2k+1) и
    даёт мягкий контур, по которому потом идёт ободок."""
    return mask.filter(ImageFilter.GaussianBlur(px * 0.85)).point(
        lambda v: 255 if v > 46 else 0)


def _rect_torn(size, jag=12, step=24, seed=1):
    """Рваный прямоугольник — край вырезки, которую рвали руками."""
    rnd = random.Random(seed)
    w, h = size
    pts = []

    def side(x0, y0, x1, y1):
        n = max(3, int(math.hypot(x1 - x0, y1 - y0) // step))
        for i in range(n):
            t = i / n
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            nx, ny = -(y1 - y0), (x1 - x0)
            L = math.hypot(nx, ny) or 1
            d = rnd.uniform(-jag, jag)
            pts.append((x + nx / L * d, y + ny / L * d))

    m = 10
    side(m, m, w - m, m); side(w - m, m, w - m, h - m)
    side(w - m, h - m, m, h - m); side(m, h - m, m, m)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    noise = Image.effect_noise(size, 42).filter(ImageFilter.GaussianBlur(1.2))
    edge = mask.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(3))
    rough = ImageChops.subtract(mask, ImageChops.multiply(edge, ImageOps.invert(noise)))
    return rough.filter(ImageFilter.GaussianBlur(0.6))


# ──────────────────────────── тонировка снимка ──────────────────────────────
def _halftone(img, cell=5, angle=20):
    """Газетный растр точками. Левая пара образцов 06.11 сделана им, и он
    сказал про неё «немножко неузнаваемые» — поэтому по умолчанию ВЫКЛЮЧЕН,
    а цветная вырезка идёт как утверждённая."""
    g = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=2)
    g = g.point(lambda v: int(60 + v * 0.72))
    g = g.rotate(angle, resample=Image.BICUBIC, expand=True)
    w, h = g.size
    out = Image.new("L", (w * 2, h * 2), 255)
    d = ImageDraw.Draw(out)
    px = g.load()
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            v = px[min(x, w - 1), min(y, h - 1)]
            r = (1 - v / 255) * cell * 0.86
            if r > 0.4:
                d.ellipse([x * 2 - r, y * 2 - r, x * 2 + r, y * 2 + r], fill=0)
    out = out.resize((w, h), Image.LANCZOS).rotate(-angle, resample=Image.BICUBIC)
    cx, cy = out.size[0] // 2, out.size[1] // 2
    ow, oh = img.size
    return out.crop((cx - ow // 2, cy - oh // 2, cx - ow // 2 + ow, cy - oh // 2 + oh))


def _tone(im, gray):
    if gray:
        ht = _halftone(im)
        im = Image.merge("RGB", (ht, ht, ht))
        return ImageChops.multiply(im, Image.new("RGB", im.size, (244, 238, 218)))
    im = ImageEnhance.Color(im).enhance(0.72)
    return ImageChops.multiply(im, Image.new("RGB", im.size, (248, 242, 226)))


# ───────────────────────────── силуэт фигуры ────────────────────────────────
def _bust_line(alpha):
    """Где резать фигуру снизу. Голова узкая, на плечах силуэт резко
    расширяется — режем чуть ниже этой линии, и полноростовой кадр
    становится погрудным портретом с крупным лицом."""
    a = np.asarray(alpha, np.uint8) > 24
    w = a.sum(axis=1)
    rows = np.nonzero(w)[0]
    if rows.size < 20:
        return alpha.size[1]
    y0, y1 = int(rows[0]), int(rows[-1])
    head = np.median(w[y0:y0 + max(4, int((y1 - y0) * 0.16))])
    if head <= 0:
        return alpha.size[1]
    wide = np.nonzero(w[y0:y1] > head * 2.0)[0]
    if wide.size == 0:
        return y1
    y_sh = y0 + int(wide[0])
    return min(y1, y_sh + int((y_sh - y0) * 0.62))


def _mask_figure(im):
    """Маска человека. Рядом с фото может лежать готовая `<фото>.alpha.png` —
    тогда модель не зовётся вовсе. Нет её и нет `rembg` — падаем вслух, а не
    рисуем молча прямоугольник: подменённый вид не виден до готового ролика."""
    try:
        from rembg import new_session, remove
    except ImportError as exc:
        raise RuntimeError(
            "виду «vyrezka_kontur» нужен rembg (маска фигуры), его нет на "
            "раннере: pip install 'rembg[cpu]'. Прямоугольной вырезкой "
            "подменять нельзя — это другой вид."
        ) from exc
    if "sess" not in _CACHE:
        _CACHE["sess"] = new_session("u2net_human_seg")
    return remove(im, session=_CACHE["sess"]).split()[3]


def _проверить_маску(a, photo):
    """ПУСТАЯ МАСКА ПАДАЕТ ВСЛУХ, А НЕ РИСУЕТ ПУСТОЙ КАДР (09.11, улов
    `usuario-e6`).

    Живой случай: в задание сцены 58 ролика «Орешник» уехал не портрет
    Кличко, а кадр самой сцены — жёлтый автобус. `u2net_human_seg` человека
    на нём не нашёл, но и не вернул чистый ноль: 0,67% кадра рассыпанными
    пятнами (у портрета 42,9%). Дальше всё считалось «успешно»: bbox пятен
    растянулся на весь кадр, вырезка получилась полосой 5409x1326, уехала за
    край холста — и в ролик приехала карточка, где ободок и подпись есть, а
    силуэта нет. Ни одна проверка этого не видела, потому что файл был на
    месте и джоб отчитался `success`.

    Три числа, замеренные на 16 кадрах этого ролика (`cards/photo/*.jpg`):
      • доля маски в кадре: портреты 3,6-42,9%, брак 0,06-1,0%;
      • заполнение bbox: портреты 41-69%, рассыпанные пятна 0,1-0,9%;
      • пропорция bbox: портреты 0,48-1,58, полоса из пятен 2,5-4,4.
    Пороги взяты с запасом НИЖЕ худшего портрета и ВЫШЕ лучшего брака.
    """
    arr = np.asarray(a, np.uint8) > 24
    всего = arr.size
    доля = arr.sum() / всего * 100.0
    имя = os.path.basename(photo)
    if доля < 1.5:
        raise RuntimeError(
            "маска силуэта пустая (%s): человек на кадре не найден — "
            "фигура занимает %.2f%% кадра при норме от 3,6%%. Так бывает на "
            "кадре без человека (техника, улица, схема), на общем плане и на "
            "однородном фоне.\n"
            "   КАДР САМОЙ СЦЕНЫ ПЕРЕСНИМАТЬ НЕ НАДО — есть два готовых пути "
            "(09.11, живой круг правок вкладки ДИПЛОМАТИЯ СИЛЫ: она отдала "
            "портрет сцены 18 под карточку и пересняла сцену на фасад "
            "штаб-квартиры):\n"
            "   1) ПОРТРЕТ ИЗ `dossier/` — вложения постов, скачанные в начале "
            "работы (`tg_media.py`). Они не принадлежат сценам, и гейт повтора "
            "такой кадр дублем НЕ считает, если он больше нигде не стоит:\n"
            "        --photo dossier/<имя>.jpg\n"
            "      Копию в `cards/photo/` заберёт `cards_queue` сам, а "
            "`dossier_use` зачтёт кадр как поставленный (сверка по md5).\n"
            "   2) ЗАКАЗАТЬ КАДР ПОД КАРТОЧКУ отдельной записью в "
            "`overlays_fetch.scenes.json` — тем же прогоном, что всплывашки, "
            "под псевдо-id 201, 202, … (так делает вкладка 5 МИНУТ: 14 кадров "
            "id 201-214 одним заходом). Запрос — «<ИМЯ ПЕРСОНЫ> портрет "
            "крупным планом, лицо в кадр». Готовый файл ПЕРЕНЕСТИ из "
            "`overlays/scene_2NN.jpg` в `cards/photo/kadr_2NN.jpg` (имя БЕЗ "
            "`scene_`, иначе гейт повтора прочтёт номер как сцену) и указать "
            "оттуда: такой кадр не принадлежит сцене и повтором не "
            "считается.\n"
            "   Третий путь — прямоугольная вырезка `vyrezka` вместо "
            "`vyrezka_kontur`: ей маска не нужна, но это ДРУГОЙ вид."
            % (имя, доля))
    ys, xs = np.nonzero(arr)
    bw = int(xs.max() - xs.min() + 1)
    bh = int(ys.max() - ys.min() + 1)
    заполн = arr.sum() / float(bw * bh) * 100.0
    if заполн < 18.0:
        raise RuntimeError(
            "маска силуэта рассыпалась (%s): пятна занимают %.1f%% своей "
            "рамки при норме от 41%% — цельной фигуры нет, вырезка выйдет "
            "пустой. Возьми другой кадр." % (имя, заполн))
    if bw / float(bh) > 2.2:
        raise RuntimeError(
            "маска силуэта вытянута в полосу (%s): рамка %dx%d, пропорция "
            "%.2f при норме до 1,6 — это не фигура человека, а размазанные "
            "по кадру пятна. Возьми другой кадр."
            % (имя, bw, bh, bw / float(bh)))


def _silhouette(photo, height, pad=0.06, bust=True, max_w=0):
    im = Image.open(photo).convert("RGB")
    im.thumbnail((1400, 1400), Image.LANCZOS)
    side = photo + ".alpha.png"
    a = Image.open(side).convert("L").resize(im.size, Image.LANCZOS) \
        if os.path.exists(side) else _mask_figure(im)
    # проверка ДО обрезки по плечам: `_bust_line` на пустой маске молча
    # возвращает всю высоту, и брак проходит дальше незамеченным
    _проверить_маску(a, photo)
    if bust:
        yb = _bust_line(a)
        # ОБРЕЗКА ПО ПЛЕЧАМ НЕ ДОЛЖНА РЕЗАТЬ ЛИЦО (13.11, его прямое слово по
        # сцене 58: «человек должен быть узнаваемый, а не обрезан по брови»).
        # `_bust_line` написана под ПОЯСНОЙ портрет. На крупном плане головы
        # она честно находит «плечи» там, где на самом деле подбородок, и
        # срезает пол-лица: в кадр уехал лоб с бровью, узнать человека
        # нельзя. Поэтому режем, только если отрезается не больше трети
        # маски и остаток ещё похож на фигуру (выше, чем шире).
        _bb = a.point(lambda v: 255 if v > 24 else 0).getbbox()
        _hm = (_bb[3] - _bb[1]) if _bb else im.size[1]
        _wm = (_bb[2] - _bb[0]) if _bb else im.size[0]
        _srez = max(0, im.size[1] - yb)
        if yb < im.size[1] - 4 and _hm and _srez <= _hm * 0.34 \
                and yb >= _wm * 1.05:
            im = im.crop((0, 0, im.size[0], yb))
            a = a.crop((0, 0, a.size[0], yb))
        elif yb < im.size[1] - 4:
            print("  вырезка: обрезку по плечам НЕ применяю — срезало бы "
                  "%d%% фигуры, лицо ушло бы из кадра"
                  % int(100.0 * _srez / max(1, _hm)))
    box = a.point(lambda v: 255 if v > 24 else 0).getbbox() or (0, 0, *im.size)
    x0, y0, x1, y1 = box
    dx, dy = int((x1 - x0) * pad), int((y1 - y0) * pad)
    x0, y0 = max(0, x0 - dx), max(0, y0 - dy)
    x1, y1 = min(im.size[0], x1 + dx), min(im.size[1], y1 + dy)
    im, a = im.crop((x0, y0, x1, y1)), a.crop((x0, y0, x1, y1))
    # ЧЕЛОВЕК ОБЯЗАН БЫТЬ УЗНАВАЕМ (13.11, его прямое слово по сцене 58:
    # «должен быть узнаваемый силуэт или портрет человека, а не обрезан по
    # брови»). Масштаб считался ТОЛЬКО по высоте, ширина не ограничивалась
    # ничем: когда маска выделила крупный план головы, фигура разъехалась
    # шире кадра, и в сцену попал кусок лба с бровью — узнать человека
    # нельзя. Теперь фигура ВПИСЫВАЕТСЯ в рамку: по высоте и по ширине, что
    # меньше. Лицо помещается целиком, поля честные.
    k = height / im.size[1]
    if max_w:
        k = min(k, float(max_w) / max(1, im.size[0]))
    size = (max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k)))
    return im.resize(size, Image.LANCZOS), a.resize(size, Image.LANCZOS)


# ───────────────────────────────── вырезки ──────────────────────────────────
def cut_figure(photo, height=820, rim=15, amp=8.0, tilt=-4, gray=False, seed=3,
               max_w=0):
    """Вырезка ПО КОНТУРУ: фигура + рваный бумажный ободок вдоль силуэта."""
    key = ("fig", photo, height, rim, amp, tilt, gray, seed, max_w)
    if key in _CACHE:
        return _CACHE[key]
    im, a = _silhouette(photo, height, max_w=max_w)
    marg = rim + int(amp * 2) + 14
    canv = (im.size[0] + marg * 2, im.size[1] + marg * 2)
    base = Image.new("L", canv, 0); base.paste(a, (marg, marg))
    body = Image.new("RGB", canv, (0, 0, 0)); body.paste(im, (marg, marg))
    body = _tone(body, gray)

    body_mask = ragged(base, amp=amp * 0.62, coarse=2.4, fiber=0.7, seed=seed)
    rim_mask = ragged(grow(base, rim), amp=amp, coarse=3.4, fiber=0.9, seed=seed + 31)
    rim_mask = ImageChops.lighter(rim_mask, body_mask)

    paper = Image.new("RGB", canv, BUMAGA)
    nz = Image.effect_noise(canv, 10).point(lambda v: int(208 + v * 0.18))
    paper = ImageChops.multiply(paper, Image.merge("RGB", (nz, nz, nz)))
    inner = ImageChops.subtract(rim_mask, body_mask).filter(ImageFilter.GaussianBlur(2.5))
    paper = ImageChops.subtract(
        paper, Image.merge("RGB", (inner, inner, inner)).point(lambda v: int(v * 0.07)))

    layer = Image.new("RGBA", canv, (0, 0, 0, 0))
    rl = paper.convert("RGBA"); rl.putalpha(rim_mask)
    layer = Image.alpha_composite(layer, rl)
    bl = body.convert("RGBA"); bl.putalpha(body_mask)
    layer = Image.alpha_composite(layer, bl)
    out = layer.rotate(tilt, resample=Image.BICUBIC, expand=True)
    _CACHE[key] = out
    return out


def cut_rect(photo, w=660, h=810, jag=15, tilt=-5, gray=False, seed=3):
    """Вырезка ПРЯМОУГОЛЬНИКОМ с рваным краем — утверждённый вид."""
    key = ("rect", photo, w, h, jag, tilt, gray, seed)
    if key in _CACHE:
        return _CACHE[key]
    im = ImageOps.fit(Image.open(photo).convert("RGB"), (w, h),
                      Image.LANCZOS, centering=(0.5, 0.32))
    im = _tone(im, gray)
    m = _rect_torn((w, h), jag=jag, seed=seed)
    cut = Image.new("RGBA", (w, h))
    cut.paste(im, (0, 0)); cut.putalpha(m)
    edge = m.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(1.5))
    white = Image.new("RGBA", (w, h), BUMAGA + (0,))
    white.putalpha(edge.point(lambda v: int(v * 0.8)))
    out = Image.alpha_composite(cut, white).rotate(tilt, resample=Image.BICUBIC,
                                                   expand=True)
    _CACHE[key] = out
    return out


# ──────────────────────────── обрывки колонок ───────────────────────────────
def _column(size, seed=5):
    """Обрывок газетной колонки: бумага и имитация набора, без читаемых слов —
    чужой текст в кадр не ставим."""
    img = Image.new("RGB", size, NEWS_TONE)
    n = Image.effect_noise(size, 14).convert("L")
    img = ImageChops.multiply(img, Image.merge("RGB", (n, n, n)).point(
        lambda v: int(206 + v * 0.20)))
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    y = 14
    while y < size[1] - 10:
        x = 12
        while x < size[0] - 16:
            wlen = rnd.randint(14, 54)
            if x + wlen > size[0] - 14:
                break
            d.rectangle([x, y, x + wlen, y + 5], fill=(104, 100, 94))
            x += wlen + 8
        y += 11
    lay = img.convert("RGBA")
    lay.putalpha(_rect_torn(size, jag=10, seed=seed + 3))
    return lay


def _shadow(layer, blur=16, dx=12, dy=16, op=130):
    a = layer.split()[3]
    s = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    s.putalpha(a.point(lambda v: int(v * op / 255)))
    s = s.filter(ImageFilter.GaussianBlur(blur))
    o = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    o.paste(s, (dx, dy), s)
    return o


def _paste(dst, layer, x, y, alpha=1.0):
    if alpha <= 0:
        return dst
    if alpha < 1.0:
        l = layer.copy()
        l.putalpha(l.split()[3].point(lambda v: int(v * alpha)))
        layer = l
    o = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o.paste(layer, (int(x), int(y)), layer)
    return Image.alpha_composite(dst, o)


def _strip(author, role, width=760):
    """Подпись на оторванной полоске: имя антиквой, должность — мелко."""
    key = ("strip", author, role, width)
    if key in _CACHE:
        return _CACHE[key]
    TH = 132 if role else 94
    tape = Image.new("RGBA", (width, TH), (246, 240, 214, 238))
    d = ImageDraw.Draw(tape)

    def fit(txt, path, start, maxw):
        k = start
        while k > 16:
            f = ImageFont.truetype(path, k)
            if d.textlength(txt, font=f) <= maxw:
                return f
            k -= 2
        return f

    d.text((26, 12), author, font=fit(author, SERIF, 56, width - 52), fill=(26, 24, 22))
    if role:
        d.text((28, 80), role, font=fit(role, sc.F_HEAD, 30, width - 56),
               fill=(92, 84, 74))
    tape.putalpha(ImageChops.multiply(tape.split()[3], _rect_torn((width, TH), jag=6, seed=9)))
    out = tape.rotate(-2, resample=Image.BICUBIC, expand=True)
    _CACHE[key] = out
    return out


# ──────────────────────────────── сам кадр ──────────────────────────────────
def _scene(photo, *, figure, author, role, kick, title, sub, watermark,
           seconds, t, sfx, gray, seed, tilt):
    tt = seconds if t is None else t
    im = sc.canvas().convert("RGBA")          # гамма канала приходит отсюда

    # обрывки колонок — позади вырезки, приходят по очереди
    for i, (w, h, x, y, ang, at) in enumerate(
            [(300, 420, 150, 112, -9, 0.10), (268, 390, 1560, 560, 7, 0.22),
             (250, 300, 300, 740, 5, 0.34)]):
        a, dx = sc._rv(t, at)
        if a <= 0:
            continue
        col = _CACHE.setdefault(("col", i), _column((w, h), seed=5 + i * 4)
                                .rotate(ang, resample=Image.BICUBIC, expand=True))
        im = _paste(im, _shadow(col, 9, 6, 8, 70), x - dx, y, a * 0.9)
        im = _paste(im, col, x - dx, y, a * 0.92)
    sc._ev(sfx, 0.12, "label")

    cut = cut_figure(photo, height=int(H * 0.80), tilt=tilt, gray=gray, seed=seed,
                     max_w=int(W * 0.52)) \
        if figure else cut_rect(photo, tilt=tilt, gray=gray, seed=seed)
    cw, ch = cut.size
    cx, cy = int(W * 0.60) - cw // 2, int(H * 0.50) - ch // 2 - 10

    a_cut, _ = sc._rv(t, 0.44)
    if a_cut > 0:
        # ЛЁГКАЯ ПОСАДКА, А НЕ ПРЫЖОК: вырезка приходит чуть крупнее и
        # садится на место. Тряски нет — его правило «только медленный зум».
        k = 1.0 + 0.055 * (1 - a_cut)
        lay = cut if k <= 1.001 else cut.resize(
            (int(cw * k), int(ch * k)), Image.LANCZOS)
        ox, oy = cx - (lay.size[0] - cw) // 2, cy - (lay.size[1] - ch) // 2
        im = _paste(im, _shadow(lay), ox, oy, a_cut)
        im = _paste(im, lay, ox, oy, a_cut)
        sc._ev(sfx, 0.44, "card")

    if author:
        tape = _strip(author, role)
        a_s, dy = sc._rv(t, 1.02)
        if a_s > 0:
            tx = cx + max(0, (cw - tape.size[0]) // 2)
            # ПОЛОСКА С ИМЕНЕМ — ВЫШЕ ПОЛОСЫ СУБТИТРОВ (13.11, пункт 0-В):
            # было H-48, и на живом ролике «Владимир Зеленский / президент
            # Украины» сидел на 898-993 — ровно под титром.
            ty = min(sc.SUB_Y - tape.size[1] - 8, cy + ch - 46)
            im = _paste(im, _shadow(tape, 9, 5, 7, 110), tx, ty + dy, a_s)
            im = _paste(im, tape, tx, ty + dy, a_s)
            sc._ev(sfx, 1.02, "quote")

    im = cn._head(im.convert("RGB"), kick, title, sub, watermark, t)
    return im


def gazeta(out=None, *, photo="", author="", role="", kick="", title="", sub="",
           watermark="ПЛАНЕТА", seconds=8.0, t=None, sfx=None, gray=False,
           seed=3, tilt=-5):
    """Вырезка прямоугольником с рваным краем (утверждена 06.11)."""
    im = _scene(photo, figure=False, author=author, role=role, kick=kick,
                title=title, sub=sub, watermark=watermark, seconds=seconds,
                t=t, sfx=sfx, gray=gray, seed=seed, tilt=tilt)
    if out:
        im.save(out, quality=94)
    return im


def figura(out=None, *, photo="", author="", role="", kick="", title="", sub="",
           watermark="ПЛАНЕТА", seconds=8.0, t=None, sfx=None, gray=False,
           seed=3, tilt=-4):
    """Вырезка по контуру фигуры с рваным ободком (заказ 06.11)."""
    im = _scene(photo, figure=True, author=author, role=role, kick=kick,
                title=title, sub=sub, watermark=watermark, seconds=seconds,
                t=t, sfx=sfx, gray=gray, seed=seed, tilt=tilt)
    if out:
        im.save(out, quality=94)
    return im
