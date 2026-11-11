# -*- coding: utf-8 -*-
"""ШЕСТЬ СЦЕН «БЕЛОГО ЗАЛА» — РИСОВАННЫЕ КАДРЫ РОЛИКА (заведены 11.11).

ЧТО ЭТО. Продолжение вида `zal` (`template/zal_scene.py`, приём G13): тот же
белый павильон, но шесть других приёмов образца. Каждый — ЦЕЛАЯ СЦЕНА, а не
наклейка поверх чужого кадра (его слово 11.11: «там целая панорама, там
внутри комната… полностью с объёмом, сцены»):

    zal_slova   G02  две объёмные строки: верхняя висит на тросах,
                     нижняя стоит на полу цветом канала, слова встают по одному
    zal_pol     G10  ударное слово ВЫЕЗЖАЕТ ИЗ ПОЛА, по бокам встают
                     тёмные плиты с тлеющими углями
    zal_kub     G11  фраза набирается по словам и уезжает вверх, с потолка
                     на тросах спускается стеклянный куб на постамент
    zal_makety  G12  белые макеты (банк, больница, ЛЭП) падают с потолка,
                     под каждым встаёт подпись, в заголовке слово под маркером
    zal_shkala  G15  столб плит цвета канала растёт из пола, рядом едет вверх
                     тёмная плашка, на которой добегает число
    zal_efir    G26  панель эфира подлетает и заполняет кадр, справа
                     столбиком копится расшифровка сказанного

ОТКУДА СНЯТО. Разбор присланного образца «SOMETHINGBIG AI» (скилл
`belyy-zal`), числа движения сняты с плёнки покадрово: вход слова ~100 мс с
перелётом 1,22 и смазом на первом кадре; падение макета 100 мс с приседом
6%; выезд слова из пола 167 мс; спуск куба 270 мс без торможения; рост
столба — outQuad. Эти числа НЕ подбирались на глаз и меняться не должны.

ЧТО ПАРАМЕТРИЗОВАНО (главный смысл переноса в бой). В образце и в разборе
фразы вписаны прямо в код — это демонстрация. Здесь из кода убрано ВСЁ, что
относится к конкретной новости: фраза сцены, слово под маркером, подписи
макетов, число и подпись шкалы, имя, должность и источник на панели эфира,
текст расшифровки, строки листов в глубине зала. Всё это приходит полями
задания сцены. Зашитыми остались только геометрия зала и времена движений.

ВСЕ НАДПИСИ ПО-РУССКИ. Демонстрационные варианты были латиницей
(`AND THEY ARE RACING`, `JOB CUTS BLAMED ON AI`) — в бою так нельзя ни на
одном канале. Латиницу в словах отбивает дверь `fullcycle/card_put.py`.

ШИРИНА МЕРИТСЯ ШРИФТОМ, А НЕ ПРИКИДЫВАЕТСЯ. Русские слова длиннее
английских («ЭНЕРГОСЕТИ» против `GRIDS`), и первая же проба боевым текстом у
вида `zal` дала четыре дефекта: надпись уехала за край, наклейки налезли
друг на друга и на надпись. Поэтому здесь работает ТОТ ЖЕ механизм, что в
`zal_scene.py`: считается ЭКРАННАЯ коробка (проекция четырёх углов), размер
ужимается, пока коробка не влезет в свою долю кадра, и только потом объект
ставится на экранное место, которое переводится в мировые координаты. Доли
разных элементов разнесены и не пересекаются по построению.

ГАММА ПРИХОДИТ ПО КАНАЛУ, в коде сцены не задаётся: акцент берётся из
`template/palitra.py` (ПЛАНЕТА — сталь, «5 МИНУТ» — золото) тем же кодом,
что у вида `zal`. Жёлтый образца остаётся только там, где канала в палитре
нет.

КАК СТАВИТСЯ. Обычной дверью карточек (фетч за такой сценой не идёт):

    python3 fullcycle/card_put.py <scenes.json> <сцена> zal_slova \\
        --text "ЕВРОПА ЗАПЛАТИЛА" --accent "И НЕ ПОЛУЧИЛА НИЧЕГО" \\
        --sheet "Счёт за газ" --sheet "Заводы стоят"

    python3 fullcycle/card_put.py <scenes.json> <сцена> zal_makety \\
        --text "ПОД УДАРОМ ОКАЗАЛИСЬ" --accent "ОКАЗАЛИСЬ" \\
        --maket "банк=БАНКИ" --maket "больница=КЛИНИКИ" --maket "лэп=ЭНЕРГОСЕТИ"

Рисует на раннере `fullcycle/render_cards.py` (вид `zal_slova` →
`zal_scenes2.zal_slova` и так далее), на машине пользователя не считается
ничего.
"""
import math
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as zc
# ЦВЕТ КАНАЛА И РАЗБИВКУ ФРАЗЫ БЕРЁМ У ВИДА `zal`, А НЕ ПИШЕМ СВОИ.
# Иначе источник цветов стал бы вторым, и правка палитры доезжала бы до
# одной сцены из семи (класс «список целей из памяти, а не из конфига»).
import zal_scene as _zs

W, H = zc.W, zc.H

# ---- общие константы --------------------------------------------------------
SAFE = 0.06                 # поле от края кадра; больше требуемых 3% — в хвосте
                            # сцены идёт наезд `tail_zoom` и подрезает края
INK = (20, 19, 21, 255)     # тёмные буквы и макеты
INK_SIDE = (30, 27, 25)     # боковая грань тёмного объёма
PAPER = (250, 250, 248)
CAP = 0.715                 # высота прописной Arial Black в долях кегля
FSIZE = 200                 # кегль, которым набираются плитки слов (потом
                            # масштабируется в мир — сам по себе роли не играет)
COND = 0.86                 # сжатие по ширине: узкий гротеск образца. Для
                            # кириллицы мягче латинских 0,80 — иначе «Ш» и «Щ»
                            # слипаются в сплошную гребёнку
POP_DUR = 0.10              # вход слова: 3 кадра
STEP = 0.13                 # шаг между словами одной строки

# ЛИСТЫ В ГЛУБИНЕ ОТОДВИНУТЫ К СТЕНАМ (|x| ≥ 3,3, z ≥ 11), а не взяты от вида
# `zal`: там в центре кадра только надпись, а здесь стоят макеты, столб,
# постамент и куб — на прежних местах листы оказались бы ровно за ними.
SHEETS = [(-3.5, 2.55, 11.0, 16), (3.4, 2.75, 12.5, -14),
          (-4.0, 2.05, 15.0, 10), (3.9, 2.35, 17.0, -9),
          (-4.3, 2.95, 20.0, 12), (4.2, 2.45, 22.5, -10)]


# ---------------------------------------------------------------------------
# ГАММА, ТЕКСТ, ВРЕМЯ
# ---------------------------------------------------------------------------
def цвета(channel):
    """(акцент канала RGBA, чернила на нём RGBA). Один источник — палитра."""
    bg, fg, _d = _zs.цвета(channel)
    return bg, fg


def _строки(text, строк=2, знаков=18):
    """Фраза сцены → строки заглавными, рвём по словам (общий код с `zal`)."""
    return _zs.разбить(text, строк=строк, знаков=знаков)


def _маркер(строки, accent):
    """Индексы слов фразы, попадающих в `accent` — их накроет маркер.

    Сверяем по СЛОВАМ, а не по подстроке: иначе «ЦЕНА» подсветила бы кусок
    слова «ЦЕНАМИ», и маркер лёг бы на половину буквы.
    """
    acc = [w for w in str(accent or "").upper().split() if w]
    if not acc or not строки:
        return None
    слова = " ".join(строки).split(" ")
    n = len(acc)
    for i in range(len(слова) - n + 1):
        if [w.strip(".,:;!?»«—-") for w in слова[i:i + n]] == \
           [w.strip(".,:;!?»«—-") for w in acc]:
            return set(range(i, i + n))
    return None


def _ev(sfx, at, role):
    if sfx is not None:
        sfx.append({"at": round(float(at), 2), "role": role})


def _знак(img, watermark):
    """Подпись канала в левом нижнем углу — как у вида `zal`."""
    if not watermark:
        return
    ImageDraw.Draw(img, "RGBA").text(
        (54, H - 62), str(watermark), font=zc.font("Arimo-Bold.ttf", 25),
        fill=(96, 98, 102, 255))


def _подпись_источника(img, text):
    """Источник ВЫШЕ знака канала: иначе две строки легли бы одна на другую."""
    if not text:
        return
    ImageDraw.Draw(img, "RGBA").text(
        (54, H - 104), str(text), font=zc.font("Arimo-Bold.ttf", 26),
        fill=(104, 106, 110, 255))


# ---------------------------------------------------------------------------
# ГЕОМЕТРИЯ: мир ↔ экран. ШИРИНА МЕРИТСЯ ПРОЕКЦИЕЙ, А НЕ ПРИКИДЫВАЕТСЯ.
# ---------------------------------------------------------------------------
def _короб(cam, corners):
    """Экранная коробка четырёхугольника: (x0, y0, x1, y1)."""
    pts = [cam.proj(p) for p in corners]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _в_мир(cam, x_scr, y_scr, z):
    """Экранная точка на глубине z → мировые x, y (центр объекта)."""
    dz = max(0.3, z - cam.z)
    return (cam.x + (x_scr - W / 2.0) * dz / zc.F,
            cam.y - (y_scr - H / 2.0) * dz / zc.F)


def _пол_на_экране(cam, z):
    """Экранная высота линии пола на глубине z."""
    return H / 2.0 + cam.y * zc.F / max(0.3, z - cam.z)


def _вписать(cam, z, аспект, доля_w, доля_h, yaw=0.0, roll=0.0, h0=1.2):
    """Мировая ВЫСОТА объекта, при которой его экранная коробка влезает в
    свою долю кадра. Считается проекцией углов и ужимается, пока не влезет.

    Аспект — ширина/высота картинки. Объект меряем в середине кадра: от
    горизонтального сдвига экранная коробка при наших углах не меняется.
    """
    h = float(h0)
    for _ in range(5):
        c = zc.quad((cam.x, cam.y, z), h * аспект, h, yaw=yaw, roll=roll)
        x0, y0, x1, y1 = _короб(cam, c)
        k = min(доля_w * W / max(1.0, x1 - x0), доля_h * H / max(1.0, y1 - y0))
        if 0.995 < k < 1.005:
            break
        h *= k
    return max(0.02, h)


def _коробка_мира(cam, z, w, h, yaw=0.0, roll=0.0):
    """Экранные ширина и высота объекта (w×h м) на глубине z."""
    c = zc.quad((cam.x, cam.y, z), w, h, yaw=yaw, roll=roll)
    x0, y0, x1, y1 = _короб(cam, c)
    return x1 - x0, y1 - y0


def _поставить(cam, z, w, h, x_доля, верх_px, yaw=0.0):
    """Мировой центр объекта, у которого на экране верх стоит на `верх_px`,
    а середина по горизонтали — на доле `x_доля` кадра."""
    bw, bh = _коробка_мира(cam, z, w, h, yaw=yaw)
    return _в_мир(cam, x_доля * W, верх_px + bh / 2.0, z) + (bh,)


def _на_полу(cam, z, аспект, доля_w, доля_h, yaw=0.0, зазор_сверху=0.0):
    """Высота предмета, СТОЯЩЕГО НА ПОЛУ: кроме своей доли он ограничен
    ещё и местом между линией пола и верхним полем (или заданным зазором).

    Без этой поправки высокое слово на полу молча уезжало бы за верхний
    край: доля по высоте про положение ничего не знает.
    """
    пол = _пол_на_экране(cam, z)
    потолок = max(SAFE * H, зазор_сверху)
    доля_h = min(доля_h, max(0.04, (пол - потолок) / H))
    return _вписать(cam, z, аспект, доля_w, доля_h, yaw=yaw)


# ---------------------------------------------------------------------------
# СЛОВА В ПРОСТРАНСТВЕ: плитки, объём, тень, расстановка по строке
# ---------------------------------------------------------------------------
def _pop(t0, t, dur=POP_DUR, k0=1.22):
    """Вход слова, как на плёнке: первый кадр крупнее и прозрачнее, за три
    кадра садится. Возвращает (масштаб, непрозрачность) или None."""
    if t < t0 - 1e-6:
        return None
    u = zc.seg(t, t0, t0 + dur)
    return k0 + (1.0 - k0) * zc.out_cubic(u), 0.55 + 0.45 * zc.clamp01(u * 2.2)


def _ось(yaw):
    """Направление вдоль строки и нормаль от камеры при повороте `yaw`."""
    return ((math.cos(yaw), 0.0, math.sin(yaw)),
            (-math.sin(yaw), 0.0, math.cos(yaw)))


def _квад_слова(center, ux, u, v, w, h):
    """Углы прямоугольника слова: центр строки + u вдоль строки, v вверх."""
    cx = center[0] + ux[0] * u
    cy = center[1] + v
    cz = center[2] + ux[2] * u
    hw, hh = w / 2.0, h / 2.0
    return [(cx - ux[0] * hw, cy + hh, cz - ux[2] * hw),
            (cx + ux[0] * hw, cy + hh, cz + ux[2] * hw),
            (cx + ux[0] * hw, cy - hh, cz + ux[2] * hw),
            (cx - ux[0] * hw, cy - hh, cz - ux[2] * hw)]


def _видно(cam, corners, margin=0.35):
    return min(c[2] for c in corners) - cam.z > margin


def _объём(canvas, cam, corners, tex, depth, nz, steps=8, side=(96, 97, 100),
           floor_clip=False, opacity=1.0):
    """Объём вдоль нормали `nz`. `floor_clip` — каждую копию режем по линии
    пола на её дальности: так слово РАСТЁТ ИЗ ПОЛА, а не всплывает целиком."""
    lay = canvas if not floor_clip else Image.new("RGBA", (W, H), (0, 0, 0, 0))
    alpha = tex.split()[3]
    p0 = cam.proj(corners[2])
    p1 = cam.proj((corners[2][0] + nz[0] * depth, corners[2][1],
                   corners[2][2] + nz[2] * depth))
    shift = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    steps = int(max(steps, min(48, shift / 2.5)))
    for i in range(steps, -1, -1):
        k = i / float(steps)
        cs = [(c[0] + nz[0] * depth * k, c[1], c[2] + nz[2] * depth * k)
              for c in corners]
        if not _видно(cam, cs):
            continue
        pts = [cam.proj(p) for p in cs]
        if i == 0:
            t = tex
        else:
            v = [int(side[j] * (0.78 + 0.22 * (1 - k))) for j in range(3)]
            t = Image.new("RGBA", tex.size, (v[0], v[1], v[2], 255))
            t.putalpha(alpha)
        if floor_clip:
            sub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            zc.paste_quad(sub, t, pts, opacity)
            zm = sum(c[2] for c in cs) / 4.0
            yf = int(max(0, min(H, _пол_на_экране(cam, zm))))
            if yf < H:
                ImageDraw.Draw(sub).rectangle([0, yf, W, H], fill=(0, 0, 0, 0))
            lay.alpha_composite(sub)
        else:
            zc.paste_quad(lay, t, pts, opacity)
    if floor_clip:
        canvas.alpha_composite(lay)


def _тень_слова(canvas, cam, corners, tex, off=(0.9, 0.0, 1.4), blur=14,
                strength=0.30):
    """Тень надписи на полу: верх букв уезжает назад-вправо (свет спереди)."""
    bl, br = corners[3], corners[2]
    k = corners[0][1] - corners[3][1]
    sh = [(bl[0] + off[0] * k, 0.012, bl[2] + off[2] * k),
          (br[0] + off[0] * k, 0.012, br[2] + off[2] * k),
          (br[0], 0.012, br[2]), (bl[0], 0.012, bl[2])]
    if not _видно(cam, sh):
        return
    a = tex.split()[3].point(lambda v: int(v * strength))
    dark = Image.new("RGBA", tex.size, (38, 36, 34, 255))
    dark.putalpha(a)
    zc.paste_quad(canvas, dark.filter(ImageFilter.GaussianBlur(blur)),
                  [cam.proj(p) for p in sh])


def _плитки(lines, hl=None, color=INK, hl_color=(255, 212, 0, 255),
            hl_ink=None, vertical=False, cond=COND):
    """Строки → (ширина блока, высота блока, [(плитка, cx, cy)]) в пикселях.

    Плитки обрезаны по контуру буквы: иначе объём «выдавливался» бы из
    пустого поля вокруг слова и давал серую плиту вместо букв.
    `vertical=True` — резать и сверху-снизу (нужно словам на полу: их
    нижняя кромка обязана совпасть с нижней кромкой буквы).
    """
    tw, th, tiles = zc.word_tiles(lines, fsize=FSIZE, hl=hl, color=color,
                                  hl_color=hl_color)
    if hl and hl_ink:
        # на маркере канальной гаммы буквы иногда должны менять цвет: сталь
        # ПЛАНЕТЫ тёмная, чёрное слово на ней не читается
        tw2, th2, tiles2 = zc.word_tiles(lines, fsize=FSIZE, hl=hl,
                                         color=hl_ink, hl_color=hl_color)
        tiles = [tiles2[i] if i in hl else tiles[i] for i in range(len(tiles))]
    out = []
    tw *= cond
    for tile, cx, cy in tiles:
        if cond != 1.0:
            tile = tile.resize((max(4, int(tile.size[0] * cond)),
                                tile.size[1]), Image.LANCZOS)
            cx *= cond
        bb = tile.getbbox()
        if bb is None:
            continue
        if vertical:
            cr = tile.crop(bb)
            out.append((cr, cx - tile.size[0] / 2.0 + (bb[0] + bb[2]) / 2.0,
                        cy - tile.size[1] / 2.0 + (bb[1] + bb[3]) / 2.0))
        else:
            cr = tile.crop((bb[0], 0, bb[2], tile.size[1]))
            out.append((cr, cx - tile.size[0] / 2.0 + (bb[0] + bb[2]) / 2.0, cy))
    return tw, th, out


def _ширина_строки(плитки):
    """Ширина и высота блока плиток В ПИКСЕЛЯХ — мерка для вписывания."""
    tw, th, tiles = плитки
    if not tiles:
        return 1.0, 1.0
    x0 = min(cx - t.size[0] / 2.0 for t, cx, cy in tiles)
    x1 = max(cx + t.size[0] / 2.0 for t, cx, cy in tiles)
    y0 = min(cy - t.size[1] / 2.0 for t, cx, cy in tiles)
    y1 = max(cy + t.size[1] / 2.0 for t, cx, cy in tiles)
    return max(1.0, x1 - x0), max(1.0, y1 - y0)


def _строка_слов(img, cam, t, плитки, центр, yaw, scale_m, старты, depth,
                 side, hang=False, floor=False, shadow=False, rise=None,
                 k0=1.22):
    """Слова строки в пространстве. `scale_m` — метров на пиксель плитки.

    floor — нижняя кромка слова лежит на полу (центр строки по y = 0);
    hang  — к каждому слову идёт трос к потолку;
    rise  — (t0, dur) подъём слова из пола с перелётом 3% на посадке.
    """
    tw, th, tiles = плитки
    ux, nz = _ось(yaw)
    for i, (tile, cx, cy) in enumerate(tiles):
        p = _pop(старты[min(i, len(старты) - 1)], t, k0=k0)
        if p is None:
            continue
        s, op = p
        w = tile.size[0] * scale_m * s
        h = tile.size[1] * scale_m * s
        u = (cx - tw / 2.0) * scale_m
        v = h / 2.0 if floor else (th / 2.0 - cy) * scale_m
        dy = 0.0
        if rise is not None:
            r0, rd = rise
            k = 1.0 - (1.0 - zc.seg(t, r0, r0 + rd)) ** 1.6
            k += 0.03 * math.sin(math.pi * zc.seg(t, r0 + rd, r0 + rd + 0.1))
            dy = -(1.0 - k) * (tile.size[1] * scale_m) * 1.02
        c = _квад_слова((центр[0], центр[1] + dy, центр[2]), ux, u, v, w, h)
        if not _видно(cam, c):
            continue
        if shadow and dy > -0.02:
            _тень_слова(img, cam, c, tile)
        if hang:
            n = 2 if tile.size[0] * scale_m > 0.45 else 1
            for j in range(n):
                f = (j + 0.5) / n
                top = (c[0][0] + (c[1][0] - c[0][0]) * f, c[0][1],
                       c[0][2] + (c[1][2] - c[0][2]) * f)
                zc.wire(img, cam, top, color=(96, 98, 102, 230), width=2)
        if s > 1.08:                       # первый кадр входа смазан вдоль строки
            for sh in (-0.05, 0.05):
                cc = _квад_слова((центр[0] + sh * w * ux[0], центр[1] + dy,
                                  центр[2] + sh * w * ux[2]), ux, u, v, w, h)
                zc.paste_quad(img, tile, [cam.proj(q) for q in cc], 0.22)
        _объём(img, cam, c, tile, depth, nz, steps=8, side=side,
               floor_clip=(rise is not None), opacity=op)


def _листы(img, cam, sheets):
    """Короткие строки задания → листы на тросах в глубине зала."""
    src = [str(s).strip() for s in (sheets or ()) if str(s).strip()]
    for (x, y, z, rot), s in zip(SHEETS, src[:len(SHEETS)]):
        if z - cam.z < 0.6:
            continue
        слова, строки, тек = s.split(), [], ""
        for w in слова:
            проба = (тек + " " + w).strip()
            if тек and len(проба) > 24:
                строки.append(тек)
                тек = w
            else:
                тек = проба
        if тек:
            строки.append(тек)
        tex = zc.sheet_tex(строки[:3])
        c = zc.quad((x, y, z), 1.55, 1.0, yaw=math.radians(rot))
        zc.wire(img, cam, (x - 0.6, y + 0.5, z))
        zc.wire(img, cam, (x + 0.6, y + 0.5, z))
        zc.paste_quad(img, tex, [cam.proj(p) for p in c])


# ---------------------------------------------------------------------------
# БЛОК, НАБИРАЮЩИЙСЯ ПО СЛОВАМ (G11, G15, G26)
# ---------------------------------------------------------------------------
def _блок(lines, t, hl=None, hl_color=(255, 212, 0, 255), hl_ink=None,
          step=0.18, start=0.0, align="center"):
    """Строки → одна текстура, в которой слова проявились по порядку.

    Слово приходит целиком и за 100 мс опускается на место с высоты 0,45
    строки (на плёнке так входят `WANTED`, `CUTS`, `THEY`). Возвращает
    (текстура, высота прописной в пикселях, время последнего слова) или
    (None, 0, 0), если ещё ни одного слова нет.
    """
    f = zc.font("ArialBlack.ttf", FSIZE)
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sp = d0.textlength(" ", font=f)
    hline = FSIZE * 1.05
    pad = int(FSIZE * 0.5)
    rows = []
    for ln in lines:
        ws = [(w, d0.textbbox((0, 0), w, font=f)) for w in ln.split(" ") if w]
        width = sum(b[2] - b[0] for _, b in ws) + sp * (len(ws) - 1)
        rows.append((ws, width))
    total_w = int(max(r[1] for r in rows) + pad * 2)
    total_h = int(len(rows) * hline + pad * 2)
    img = Image.new("RGBA", (max(total_w, 8), max(total_h, 8)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    есть = False
    idx = 0
    y = pad
    послед = start
    for ws, width in rows:
        x = pad if align == "left" else (total_w - width) / 2.0
        for w, b in ws:
            ww = b[2] - b[0]
            t0 = start + idx * step
            послед = t0
            if t >= t0:
                есть = True
                k = zc.seg(t, t0, t0 + 0.10)
                dy = -0.45 * hline * (1 - zc.out_cubic(k))
                ink = INK
                if hl and idx in hl:
                    d.rectangle([x - FSIZE * 0.06, y + dy + FSIZE * 0.05,
                                 x + ww + FSIZE * 0.06, y + dy + FSIZE * 0.98],
                                fill=hl_color)
                    if hl_ink:
                        ink = hl_ink
                d.text((x - b[0], y + dy - b[1] + FSIZE * 0.16), w, font=f, fill=ink)
            x += ww + sp
            idx += 1
        y += hline
    if not есть:
        return None, 0.0, послед
    img = img.resize((max(4, int(total_w * COND)), total_h), Image.LANCZOS)
    return img, FSIZE * 0.72, послед


# отступ от верха текстуры блока до верха букв, в долях прописной
_ГОЛОВА = 0.66 / 0.72


def _вписать_блок(cam, tex, cap_px, z, доля_w, доля_h, yaw=0.0):
    """Метров на прописную, при которых блок влезает в свою долю кадра."""
    аспект = tex.size[0] / float(tex.size[1])
    h = _вписать(cam, z, аспект, доля_w, доля_h, yaw=yaw)
    return h * cap_px / float(tex.size[1])


def _место_блока(img, cam, tex, cap_px, cap_m, z, x_доля, верх_px, yaw=0.0,
                 depth=0.06, wires=2, rise=0.0, blur_steps=0):
    """Блок в зале: размер по прописной, место — ЭКРАННОЕ (доля по ширине и
    верх в пикселях), переведённое в мир. `rise` — уезжание вверх со шлейфом."""
    if tex is None:
        return
    k = cap_m / cap_px
    w, h = tex.size[0] * k, tex.size[1] * k
    bw, bh = _коробка_мира(cam, z, w, h, yaw=yaw)
    cx, cy = _в_мир(cam, x_доля * W, верх_px + bh / 2.0, z)
    cy += rise
    cq = zc.quad((cx, cy, z), w, h, yaw=yaw)
    if blur_steps > 0 and rise > 0:
        ghost = tex.copy()
        ghost.putalpha(tex.split()[3].point(lambda v: int(v * 0.22)))
        for i in range(blur_steps, 0, -1):
            dy = -rise * 0.45 * i / blur_steps
            zc.paste_quad(img, ghost,
                          [cam.proj((p[0], p[1] + dy, p[2])) for p in cq])
    if wires:
        for fx in (0.10, 0.90):
            ux = (fx - 0.5) * w
            zc.wire(img, cam, (cx + ux * math.cos(yaw), cy + h / 2.0,
                               z + ux * math.sin(yaw)))
    zc.extrude(img, cam, cq, tex, depth=depth, steps=4)
