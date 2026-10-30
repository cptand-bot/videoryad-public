# -*- coding: utf-8 -*-
"""ДИАГРАММЫ второго сборщика (полный цикл): линейная, круговая,
накопительная, картограмма.

Закрывает дыру, записанную в арсенале как «диаграмм только две» —
были столбцы и слайдер (и те в документальном сборщике, на чужой
бирюзовой палитре). Здесь четыре типа в ЕДИНОЙ системе style_cards:
та же виньетка с зерном, та же палитра (белый/золотой/красный/серый),
те же три шрифтовые роли, тот же подвал с источником и вотермарка.
Поэтому диаграмма встаёт в ролик рядом с карточкой-персоной и
хронологией и не читается как вставка из другого шаблона.

  line(...)       линейный график: 1-4 серии, прямая или сглаженная
                  кривая, ЛИНЕЙНАЯ ИЛИ ЛОГАРИФМИЧЕСКАЯ шкала, точки-
                  события с подписями, прямые подписи серий у головы.
  pie(...)        круговая и кольцевая: сегменты прорастают по дуге,
                  итог в центре кольца, выносные подписи с долями.
  stack(...)      накопительная: режим "bars" (накопительные столбцы
                  по периодам) и "area" (накопительная площадь во
                  времени), легенда и итог над столбцом.
  cartogram(...)  картограмма: заливка стран по значению (choropleth)
                  или пропорциональные кружки (bubble), легенда-
                  градиент, подписи значений, проявление волной.

ПРАВИЛА ОФОРМЛЕНИЯ, КОТОРЫЕ ЗДЕСЬ СОБЛЮДЕНЫ (иначе диаграмма
развалит систему ролика):

1. ОДНА ОСЬ. Две величины разного масштаба — это две диаграммы или
   приведение к общей базе, никогда не вторая шкала справа.
2. ЦВЕТ РАБОТАЕТ ПО РОЛИ, а не по вкусу. Для НЕупорядоченных серий —
   четыре роли системы (белый = главное, золотой = второе, красный =
   акцент, серый = фон). Для долей и накоплений — упорядоченная
   золотая шкала от яркого к тёмному: доли сравнивают по величине, им
   нужна градация, а не разные цвета. Радуги нет нигде.
3. ИДЕНТИЧНОСТЬ НЕ ЦВЕТОМ. У каждой серии и сегмента есть ПРЯМАЯ
   подпись; легенда идёт дополнением, а не вместо.
4. ЦИФРА НЕ НА КАЖДОЙ ТОЧКЕ. Подписываются только названные события
   и итоги, иначе график превращается в таблицу.
5. ТОНКИЕ МАРКИ, РЕЦЕССИВНАЯ СЕТКА. Сетка темнее линий данных,
   засечки без рамок, подписи осей — серый моноширинный.

ВАЖНО ПРО ЧИСЛА (то же правило, что у дата-карты): нет настоящих
чисел с источником — диаграмма НЕ рисуется. Столбик «на глазок» в
новостном ролике это ложь на экране. Когда чисел нет, работают
хронология (`timeline`), расстановка сил (`forces`) и перечень
(`bullets`) — они оперируют событиями.
"""
import json
import math
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import style_cards as sc

W, H = sc.W, sc.H
GEO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo")

# ---------- геометрия поля диаграммы (та же сетка, что у карточек) ----------
PX0 = sc.MARGIN_L            # левая граница поля = левое поле текста
PX1 = W - 232                # правая граница
PY0 = 452                    # верх поля (ниже заголовка И легенды)
PY1 = 838                    # низ поля (ось X)
AX_LAB_Y = PY1 + 26          # подписи оси X
NOTE_Y = 936                 # сноска-вывод
LEG_Y = 382                  # легенда: своя строка, заголовок её не трогает
HEAD_BOTTOM = 376            # ниже этой черты шапка кончилась

GRID = (44, 44, 48)          # сетка — темнее любых данных
AXIS = (86, 86, 92)          # сама ось
LAB = (150, 150, 156)        # подписи осей

# Упорядоченная шкала для долей и накоплений: один тон, яркое -> тёмное.
# Шаг по светлоте взят предельный: прогон палитры через проверку
# различимости (dataviz/validate_palette) показал, что у монохромной
# шкалы соседние ступени дают ΔE 14 при пороге 15 для категориальных
# наборов — то есть одним цветом доли не опознаются НИКОГДА, сколько
# шкалу ни растягивай. Поэтому к цвету всегда добавлено второе
# кодирование: зазор между сегментами и прямая подпись. По той же
# причине больше ПЯТИ долей не рисуем — остальное сворачивается в
# «прочее» (о чём модуль предупреждает в stderr).
RAMP = [(234, 189, 35), (192, 138, 44), (143, 92, 46),
        (94, 58, 44), (62, 44, 40), (42, 34, 32)]
# Четыре роли системы для НЕупорядоченных серий. Этот набор проверку
# различимости проходит (ΔE 13.6 при дальтонизме, 19.7 при нормальном
# зрении): белый и серый ахроматичны намеренно — это роли системы, а не
# «ещё два цвета».
ROLES = [sc.WHITE, sc.GOLD, sc.RED, (132, 132, 138)]
MAX_PARTS = 5                # больше долей глаз не разбирает


# ───────────────────────────── служебное ────────────────────────────────────

def _col(spec, i=0, ordered=False):
    """Цвет серии/сегмента: имя роли, hex или место в шкале."""
    if isinstance(spec, (tuple, list)) and len(spec) == 3:
        return tuple(int(v) for v in spec)
    if isinstance(spec, str):
        s = spec.strip().lower()
        named = {"white": sc.WHITE, "белый": sc.WHITE, "gold": sc.GOLD,
                 "золотой": sc.GOLD, "red": sc.RED, "красный": sc.RED,
                 "grey": (132, 132, 138), "серый": (132, 132, 138)}
        if s in named:
            return named[s]
        h = s.lstrip("#")
        if len(h) == 6:
            return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))
    pool = RAMP if ordered else ROLES
    # упорядоченная шкала НЕ зациклена: седьмая доля, получив цвет первой,
    # читалась как самая крупная (поймано на дереве долей 20.10)
    return pool[min(i, len(pool) - 1)] if ordered else pool[i % len(pool)]


def _num(v):
    """Число для экрана: тысячи пробелом, дробь — одним знаком."""
    if v is None:
        return ""
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}".replace(",", " ")
    return f"{v:,.1f}".replace(",", " ").replace(".", ",")


def _unit(v, unit):
    """Число с единицей. Процент и градус пишутся слитно — пробел перед
    «%» на экране читается как опечатка."""
    s = _num(v)
    if not unit:
        return s
    return s + unit if unit in ("%", "°", "₽", "$") else f"{s} {unit}"


def _ticks(vmin, vmax, n=4):
    """Круглые риски: шаг из 1/2/2.5/5·10^k, чтобы подписи читались."""
    span = (vmax - vmin) or 1.0
    raw = span / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = mag * 10
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    lo = math.floor(vmin / step) * step
    hi = math.ceil(vmax / step) * step
    out, v = [], lo
    while v <= hi + step * 1e-6:
        out.append(round(v, 10))
        v += step
    return out, lo, hi


def _log_ticks(vmin, vmax):
    """Декады для нелинейной шкалы: 1, 10, 100... Между ними — полудекада,
    когда диапазон узкий, иначе риска всего две и шкала не читается."""
    vmin = max(vmin, 1e-9)
    k0 = math.floor(math.log10(vmin))
    k1 = math.ceil(math.log10(max(vmax, vmin * 1.0001)))
    out = [10 ** k for k in range(int(k0), int(k1) + 1)]
    if len(out) <= 3:
        add = [10 ** k * 3 for k in range(int(k0), int(k1) + 1)]
        out = sorted(set(out + add))
    return out, out[0], out[-1]


def _aa(size, fn, ss=3):
    """Маска, нарисованная с суперсэмплингом: PIL не умеет сглаживать
    линии и дуги, а на тонких марках ступеньки видно сразу."""
    w, h = int(size[0]), int(size[1])
    m = Image.new("L", (w * ss, h * ss), 0)
    fn(ImageDraw.Draw(m), ss)
    return m.resize((w, h), Image.LANCZOS)


def _tint(im, box, mask, color, alpha=1.0):
    """Положить цвет сквозь маску. Один проход, без лишних конвертаций."""
    if alpha < 1.0:
        mask = mask.point(lambda v: int(v * alpha))
    im.paste(Image.new("RGB", mask.size, tuple(int(c) for c in color)),
             (int(box[0]), int(box[1])), mask)


def _glow(im, box, mask, color, k=0.5, blur=14):
    g = mask.filter(ImageFilter.GaussianBlur(blur))
    _tint(im, box, g, color, k)


def _smooth(pts, k=14):
    """Catmull-Rom: сглаженная кривая через заданные точки. Нужна там, где
    величина меняется непрерывно (цена, объём) — ломаная в таком случае
    врёт о характере роста."""
    if len(pts) < 3:
        return list(pts)
    out = []
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[max(i - 1, 0)]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[min(i + 2, n - 1)]
        for j in range(k):
            t = j / k
            t2, t3 = t * t, t * t * t
            out.append((
                0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
                       (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
                0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
                       (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)))
    out.append(tuple(pts[-1]))
    return out


def _head(im, kick, title, t, sfx):
    """Шапка диаграммы: эпиграф и заголовок — как у всех карточек."""
    a, dx = sc._rv(t, 0.1)
    sc._ev(sfx, 0.1, "accent")
    if kick:
        im = sc._put(im, lambda d: sc.kicker(d, 236, kick), a, dx)
    a, dx = sc._rv(t, 0.3)
    if title:
        im = sc._put(im, lambda d: d.text((sc.MARGIN_L, 288), title,
                                          font=sc._f(sc.F_HEAD, 64),
                                          fill=sc.WHITE + (255,)), a, dx)
    return im


def _foot(im, source, watermark, note, t, at_note):
    if note:
        a, dx = sc._rv(t, at_note)
        im = sc._put(im, lambda d: d.text((sc.MARGIN_L, NOTE_Y), note,
                                          font=sc._f(sc.MONO, 29),
                                          fill=sc.GOLD + (255,)), a, dx)
    a, _ = sc._rv(t, 0.9)
    return sc._put(im, lambda d: sc.footer(d, source, watermark), a, 0)


def _legend(im, entries, t, at, y=LEG_Y):
    """Легенда: цветной отрезок + название. Для двух и более серий есть
    всегда, но идентичность она не несёт — её несут прямые подписи."""
    a, dx = sc._rv(t, at)
    if a <= 0:
        return im
    f = sc._f(sc.F_HEAD, 25)

    def draw(d):
        x = sc.MARGIN_L
        for name, color in entries:
            d.rectangle((x, y + 13, x + 26, y + 17), fill=color + (255,))
            d.text((x + 38, y), name.upper(), font=f, fill=(196, 196, 200, 255))
            x += 38 + f.getlength(name.upper()) + 46
    return sc._put(im, draw, a, dx)


def _y_axis(im, ticks, lo, hi, logscale, unit, t, at=0.5, px1=PX1):
    """Шкала значений: риски сеткой через всё поле + подписи слева.
    Сетка темнее данных — она служебная, а не часть картинки."""
    f = sc._f(sc.MONO, 21)

    def pos(v):
        if logscale:
            return PY1 - (math.log10(max(v, 1e-9)) - math.log10(lo)) / \
                   (math.log10(hi) - math.log10(lo)) * (PY1 - PY0)
        return PY1 - (v - lo) / (hi - lo) * (PY1 - PY0)

    a, _ = sc._rv(t, at)
    if a <= 0:
        # шкала ещё не проявилась, но пересчёт значения в координату нужен
        # сразу: по нему считаются первые кадры кривой
        return im, pos

    def draw(d):
        for v in ticks:
            y = pos(v)
            if y < PY0 - 2 or y > PY1 + 2:
                continue
            d.rectangle((PX0, y, px1, y + 1), fill=GRID + (255,))
            s = _num(v)
            d.text((PX0 - 18 - f.getlength(s), y - 13), s, font=f, fill=LAB + (255,))
        d.rectangle((PX0, PY1, px1, PY1 + 2), fill=AXIS + (255,))
        if unit:
            d.text((PX0 - 18 - f.getlength(unit), PY0 - 44), unit,
                   font=f, fill=(120, 120, 126, 255))
    return sc._put(im, draw, a, 0), pos


# ─────────────────────────── 1. ЛИНЕЙНЫЙ ГРАФИК ─────────────────────────────

def line(out=None, kick="", title="", x_labels=(), series=(), marks=(),
         scale="linear", curve=True, fill=True, unit="", note=None,
         source="", watermark="ДО ПРИГОВОРА", baseline=None,
         t=None, sfx=None):
    """Линейный график: как величина менялась во времени.

    Единственная диаграмма, которая показывает ХАРАКТЕР изменения, а не
    только итог: ускорение, перелом, плато. Поэтому для неё обязательна
    непрерывная величина по одной оси и подписанные периоды по другой.

    series — 1-4 ряда: {"name", "values": [...], "color", "dash": True}.
             Пропуск в данных — None, кривая разрывается, а не врёт
             интерполяцией.
    marks   — названные события: {"at": индекс, "text": "...", "series": 0}.
             Только они и подписываются числом — на каждой точке цифра
             превращает график в таблицу.
    scale   — "linear" или "log". Логарифмическая нужна, когда рост
             кратный (в разы), на линейной шкале он выглядит обрывом.
    curve   — сглаженная кривая (непрерывная величина) против ломаной
             (дискретные замеры).
    baseline— {"value": .., "label": ".."} — норма/порог пунктиром.
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    series = [s for s in series if s.get("values")]
    n = max((len(s["values"]) for s in series), default=0)
    if not series or n < 2:
        return _foot(im, source, watermark, note, t, 1.2)

    vals = [v for s in series for v in s["values"] if v is not None]
    logscale = (scale == "log")
    if logscale:
        ticks, lo, hi = _log_ticks(min(vals), max(vals))
    else:
        vmin = min(vals)
        ticks, lo, hi = _ticks(min(0, vmin) if vmin >= 0 else vmin, max(vals))
    # Правое поле отдаём прямым подписям серий: подпись стоит НАПРОТИВ
    # своей головы, а не над ней — иначе на плотном графике белая подпись
    # оказывается над золотой линией и график читается наоборот.
    f_name = sc._f(sc.F_HEAD, 30)
    names = [s.get("name", "") for s in series if s.get("name")]
    pad = max([sc.track_w(s.upper(), f_name, 2) for s in names] or [0])
    px1 = PX1 if not pad else max(W * 0.52, min(PX1, W - 46 - pad))
    im, ypos = _y_axis(im, ticks, lo, hi, logscale, unit, t, px1=px1)

    step = (px1 - PX0) / (n - 1)
    T0, DUR = 0.9, 3.4                      # кривая прочерчивается не спеша
    prog = 1.0 if t is None else sc._ease((t - T0) / DUR)

    # подписи периодов: редеем, если густо — подписи важнее густоты
    a, _ = sc._rv(t, 0.6)
    if a > 0:
        f = sc._f(sc.MONO, 22)
        every = max(1, int(math.ceil(n * 110 / max(px1 - PX0, 1))))

        def xlab(d):
            for i, s in enumerate(x_labels[:n]):
                if i % every and i != n - 1:
                    continue
                s = str(s)
                wd = sc.track_w(s, f, 1)
                sc.track(d, (PX0 + step * i - wd / 2, AX_LAB_Y), s, f,
                         LAB + (255,), 1)
        im = sc._put(im, xlab, a, 0)

    if baseline is not None:
        ab, _ = sc._rv(t, 0.75)
        if ab > 0:
            by = ypos(baseline["value"])

            def bl(d):
                for x in range(int(PX0), int(px1), 26):
                    d.rectangle((x, by, x + 13, by + 1), fill=(118, 118, 124, 255))
                lb = baseline.get("label", "")
                if lb:
                    f = sc._f(sc.MONO, 21)
                    d.text((px1 - f.getlength(lb), by - 30), lb,
                           font=f, fill=(140, 140, 146, 255))
            im = sc._put(im, bl, ab, 0)

    box = (PX0 - 30, PY0 - 60, W - 6, PY1 + 10)
    bw, bh = box[2] - box[0], box[3] - box[1]
    heads = []

    for si, s in enumerate(series):
        color = _col(s.get("color"), si)
        pts_all, cuts = [], []
        for i, v in enumerate(s["values"][:n]):
            if v is None:
                cuts.append(len(pts_all))
                continue
            pts_all.append((PX0 + step * i, ypos(v)))
        if len(pts_all) < 2:
            continue
        poly = _smooth(pts_all) if curve else list(pts_all)
        k = max(2, int(round(prog * (len(poly) - 1))) + 1)
        seen = poly[:k]
        if len(seen) < 2:
            continue
        sc._ev(sfx, T0 + si * 0.1, "label")

        # площадь под кривой: объём читается до того, как глаз дойдёт до
        # шкалы; у второй и дальше серий слабее, иначе каша
        if fill:
            fa = 0.30 if si == 0 else 0.16

            def area(d, ss, seen=seen):
                d.polygon([((x - box[0]) * ss, (y - box[1]) * ss) for x, y in seen] +
                          [((seen[-1][0] - box[0]) * ss, (PY1 - box[1]) * ss),
                           ((seen[0][0] - box[0]) * ss, (PY1 - box[1]) * ss)],
                          fill=255)
            m = _aa((bw, bh), area, ss=2)
            grad = np.linspace(1.0, 0.0, bh, dtype=np.float32)[:, None]
            m = Image.fromarray((np.asarray(m, np.float32) * grad).astype(np.uint8))
            _tint(im, box, m, color, fa)

        def lines(d, ss, seen=seen, s=s):
            wd = max(2, int(round(3 * ss)))
            p = [((x - box[0]) * ss, (y - box[1]) * ss) for x, y in seen]
            if s.get("dash"):
                for i in range(0, len(p) - 1, 2):
                    d.line([p[i], p[i + 1]], fill=255, width=wd)
            else:
                d.line(p, fill=255, width=wd, joint="curve")
        m = _aa((bw, bh), lines)
        _glow(im, box, m, color, 0.34, 12)
        _tint(im, box, m, color)

        hx, hy = seen[-1]
        heads.append((hx, hy, color, s.get("name", ""), si))

    # Названные события рисуются ПЕРВЫМИ и занимают место: они привязаны
    # к конкретной точке и сдвинуться не могут, а подпись серии может.
    occupied = []
    f_mk = sc._f(sc.MONO, 23)
    for mk in marks:
        i = int(mk.get("at", 0))
        si = int(mk.get("series", 0))
        if si >= len(series) or i >= n:
            continue
        v = series[si]["values"][i]
        if v is None:
            continue
        at = T0 + DUR * (i / max(n - 1, 1)) + 0.12
        am, dxm = sc._rv(t, at)
        if am <= 0:
            continue
        sc._ev(sfx, at, "quote")
        x, y = PX0 + step * i, ypos(v)
        txt = mk.get("text", "")
        show_v = mk.get("value", True)
        vs = _unit(v, unit)
        label = f"{txt}  {vs}" if show_v and txt else (txt or vs)
        above = mk.get("above", True)
        wd = f_mk.getlength(label)
        if i >= n - 1:
            # событие в последней точке: плашка уходит ВЛЕВО, внутрь поля.
            # Над головой кривой стоит прямая подпись серии, и две надписи
            # дрались за одно место (поймано на витрине 20.10)
            tx, ty = x - wd - 30, y - 18
        else:
            tx = min(max(x - wd / 2, PX0 + 12), W - 26 - wd)
            ty = y - 56 if above else y + 30

        occupied.append((tx - 12, ty - 7, tx + wd + 12, ty + 32))

        def mark(d, x=x, y=y, tx=tx, ty=ty, label=label):
            sc.red_dot(d, x, y, 7, t)
            d.rectangle((tx - 12, ty - 7, tx + wd + 12, ty + 32),
                        fill=(16, 16, 18, 215))
            d.text((tx, ty), label, font=f_mk, fill=(236, 236, 236, 255))
        im = sc._put(im, mark, am, dxm)


    # головы кривых: светящаяся точка + ПРЯМАЯ подпись серии.
    # Подпись идёт НАД головой с выключкой вправо, а не справа от неё:
    # справа кадр кончается, и длинное название уезжало за край.
    taken_y = []
    for hx, hy, color, name, si in heads:
        def dot(d, ss, hx=hx, hy=hy):
            r = 8 * ss
            d.ellipse(((hx - box[0]) * ss - r, (hy - box[1]) * ss - r,
                       (hx - box[0]) * ss + r, (hy - box[1]) * ss + r), fill=255)
        m = _aa((bw, bh), dot)
        _glow(im, box, m, color, 0.6, 18)
        _tint(im, box, m, (255, 255, 255))
        if not name:
            continue
        an, dxn = sc._rv(t, T0 + 0.5 + si * 0.12)
        if an <= 0:
            continue
        nm = name.upper()
        wd = sc.track_w(nm, f_name, 2)
        lx = min(hx + 20, W - 26 - wd)

        def free(ly):
            b = (lx - 10, ly - 5, lx + wd + 10, ly + 36)
            if any(abs(ly - q) < 42 for q in taken_y):
                return False
            return not any(not (b[2] < q[0] or b[0] > q[2] or
                                b[3] < q[1] or b[1] > q[3]) for q in occupied)
        ly = None
        for cand in [hy - 17] + [hy - 17 + k for k in (-46, 46, -92, 92)]:
            if PY0 - 46 <= cand <= PY1 - 30 and free(cand):
                ly = cand
                break
        if ly is None:
            continue
        taken_y.append(ly)
        occupied.append((lx - 10, ly - 5, lx + wd + 10, ly + 36))
        im = sc._put(im, lambda d, lx=lx, ly=ly, nm=nm, wd=wd, color=color:
                     (d.rectangle((lx - 10, ly - 5, lx + wd + 10, ly + 36),
                                  fill=(14, 14, 16, 190)),
                      sc.track(d, (lx, ly), nm, f_name, color + (255,), 2)),
                     an, dxn)

    if len(series) > 1:
        im = _legend(im, [(s.get("name", ""), _col(s.get("color"), i))
                          for i, s in enumerate(series)], t, 0.45)
    im = _foot(im, source, watermark, note, t, T0 + DUR + 0.3)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 2. КРУГОВАЯ / КОЛЬЦО ───────────────────────────

def pie(out=None, kick="", title="", segments=(), donut=True, total=None,
        center_value=None, center_label="", unit="", sort=True, note=None,
        source="", watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Круговая (и кольцевая) диаграмма: из чего состоит целое.

    Работает ТОЛЬКО когда части складываются в осмысленное целое и их
    немного (2-6). Семь долей по 14% — это перечень, а не диаграмма:
    для такого есть `bullets`. Доли упорядочены по величине, поэтому
    цвет у них градацией одного тона, а не разными цветами: разные
    цвета сказали бы, что доли — независимые сущности.

    segments — [{"label", "value", "accent": True, "color"}]. accent
               красит долю красным и выдвигает её из круга — ровно одна
               на диаграмму, это и есть «вот про что речь».
    donut    — кольцо (в центре помещается итог) против полного круга.
    center_value/center_label — что стоит в центре кольца.
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    segs = [s for s in segments if float(s.get("value", 0)) > 0]
    if not segs:
        return _foot(im, source, watermark, note, t, 1.2)
    if sort:
        segs = sorted(segs, key=lambda s: -float(s["value"]))
    if len(segs) > MAX_PARTS:
        print(f"круговая: {len(segs)} долей — это перечень, а не диаграмма; "
              f"сверни мелкие в «прочее» или возьми bullets", file=sys.stderr)
    tot = float(total) if total else sum(float(s["value"]) for s in segs)

    # Круг стоит по центру кадра, а подписи расходятся на обе стороны:
    # при круге слева длинные названия не помещались, а выноски к колонке
    # справа шли наискось через весь круг.
    CX, CY, R = 952, 650, 206
    RIN = int(R * 0.56) if donut else 0
    GAP_DEG = 1.1                       # зазор между долями: границы читаются
    T0, PER = 0.85, 0.30                # доля за долей, не всё разом

    box = (CX - R - 110, CY - R - 110, CX + R + 110, CY + R + 110)
    bw, bh = box[2] - box[0], box[3] - box[1]
    f_lab = sc._f(sc.F_HEAD, 31)
    f_pct = sc._f(sc.MONO_B, 33)
    f_val = sc._f(sc.MONO, 23)

    ang = -90.0
    rows = []
    for i, s in enumerate(segs):
        share = float(s["value"]) / tot
        sweep = share * 360.0
        at = T0 + i * PER
        gr = 1.0 if t is None else sc._ease((t - at) / 0.55)
        color = _col(s.get("color"), i, ordered=True)
        if s.get("accent"):
            color = sc.RED
        if gr > 0:
            sc._ev(sfx, at, "label")
            a0 = ang + GAP_DEG / 2
            a1 = ang + max(sweep - GAP_DEG / 2, GAP_DEG)
            a1 = a0 + (a1 - a0) * gr
            off = 15 if s.get("accent") else 0
            mid = math.radians((a0 + a1) / 2)
            ox, oy = math.cos(mid) * off, math.sin(mid) * off

            def arc(d, ss, a0=a0, a1=a1, ox=ox, oy=oy):
                cx = (CX - box[0] + ox) * ss
                cy = (CY - box[1] + oy) * ss
                d.pieslice((cx - R * ss, cy - R * ss, cx + R * ss, cy + R * ss),
                           a0, a1, fill=255)
                if RIN:
                    d.ellipse((cx - RIN * ss, cy - RIN * ss,
                               cx + RIN * ss, cy + RIN * ss), fill=0)
            m = _aa((bw, bh), arc, ss=2)
            if s.get("accent"):
                _glow(im, box, m, color, 0.4, 18)
            _tint(im, box, m, color)
        rows.append((s, share, ang, ang + sweep, color, at))
        ang += sweep

    # центр кольца: итог крупно. Диаграмма отвечает «из чего», а число в
    # центре — «сколько всего», без него доли висят в воздухе
    if donut and (center_value is not None or center_label):
        ac, _ = sc._rv(t, T0 + len(segs) * PER + 0.15)
        if ac > 0:
            sc._ev(sfx, T0 + len(segs) * PER + 0.15, "quote")

            def mid_txt(d):
                if center_value is not None:
                    s = center_value if isinstance(center_value, str) else _num(center_value)
                    f = sc._f(sc.F_HEAD, 84)
                    wd = sc.track_w(s, f, 2)
                    sc.track(d, (CX - wd / 2, CY - 74), s, f, sc.WHITE + (255,), 2)
                if center_label:
                    f = sc._f(sc.MONO, 22)
                    wd = sc.track_w(center_label.upper(), f, 3)
                    sc.track(d, (CX - wd / 2, CY + 22), center_label.upper(), f,
                             sc.GOLD + (255,), 3)
            im = sc._put(im, mid_txt, ac, 0)

    # Прямые подписи по обе стороны круга с выноской-ломаной: радиально
    # от своей доли, затем горизонталь к тексту. Доля опознаётся по
    # линии, а не по совпадению цвета с легендой.
    plan = []
    for i, (s, share, a0, a1, color, at) in enumerate(rows):
        mid = math.radians((a0 + a1) / 2)
        right = math.cos(mid) >= -0.08
        pct = f"{share * 100:.0f}%"
        name = s["label"].upper()
        sub = s.get("note") or ""
        if not sub and unit and unit != "%":
            sub = _unit(float(s["value"]), unit)
        wd = f_pct.getlength(pct) + 16 + sc.track_w(name, f_lab, 1)
        y = CY + math.sin(mid) * (R + 54) - 22
        plan.append(dict(i=i, s=s, color=color, at=at, mid=mid, right=right,
                         pct=pct, name=name, sub=sub, wd=wd, y=y))

    # Разведение по вертикали: каждая сторона отдельно. Колонка держится
    # в коридоре между шапкой и подвалом — иначе верхняя подпись при
    # раздвигании уезжает прямо на заголовок.
    TOP, BOT = HEAD_BOTTOM + 28, H - 196
    for side in (True, False):
        col = sorted([p for p in plan if p["right"] == side], key=lambda p: p["y"])
        if not col:
            continue
        gap = min(96, max(74, (BOT - TOP) / max(len(col), 1)))
        for p in col:
            p["y"] = max(TOP, p["y"])
        for k in range(1, len(col)):
            if col[k]["y"] - col[k - 1]["y"] < gap:
                col[k]["y"] = col[k - 1]["y"] + gap
        over = col[-1]["y"] + gap - BOT
        if over > 0:
            for p in col:
                p["y"] = max(TOP, p["y"] - over)

    for p in plan:
        al, dxl = sc._rv(t, p["at"] + 0.18)
        if al <= 0:
            continue
        mid, y, wd = p["mid"], p["y"], p["wd"]
        ex, ey = CX + math.cos(mid) * (R + 8), CY + math.sin(mid) * (R + 8)
        kx, ky = CX + math.cos(mid) * (R + 42), CY + math.sin(mid) * (R + 42)
        if p["right"]:
            tx = max(kx + 26, CX + R + 92)
            tx = min(tx, W - 30 - wd)
            hook = tx - 18
        else:
            tx = min(kx - 26 - wd, CX - R - 92 - wd)
            tx = max(tx, 30)
            hook = tx + wd + 18

        def row(d, p=p, tx=tx, y=y, ex=ex, ey=ey, kx=kx, ky=ky, hook=hook):
            d.line([(ex, ey), (kx, ky)], fill=(96, 96, 102, 255), width=1)
            d.line([(kx, ky), (hook, y + 21)], fill=(96, 96, 102, 255), width=1)
            d.text((tx, y - 4), p["pct"], font=f_pct, fill=p["color"] + (255,))
            sc.track(d, (tx + f_pct.getlength(p["pct"]) + 16, y), p["name"],
                     f_lab, sc.WHITE + (255,), 1)
            if p["sub"]:
                d.text((tx, y + 38), p["sub"], font=f_val, fill=(146, 146, 152, 255))
        im = sc._put(im, row, al, dxl)

    im = _foot(im, source, watermark, note, t, T0 + len(segs) * PER + 0.5)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 3. НАКОПИТЕЛЬНАЯ ───────────────────────────────

def stack(out=None, kick="", title="", cats=(), rows=(), mode="bars",
          unit="", totals=True, note=None, source="",
          watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Накопительная диаграмма: из чего складывается итог и как меняется
    и сам итог, и состав.

    Отвечает на два вопроса одной картинкой — поэтому и нужна там, где
    простые столбцы заставили бы рисовать две диаграммы рядом. Цвета —
    градация одного тона: категории внутри столбца упорядочены и
    сравниваются по величине. Между сегментами зазор 3 px, иначе
    граница доли теряется на тёмном фоне.

    cats — [{"name", "color"}] в порядке укладки снизу вверх.
    rows — [{"mark": "2020", "parts": [v1, v2, ...]}] — по одному
           значению на каждую категорию.
    mode — "bars" (накопительные столбцы по периодам: состав важнее) или
           "area" (накопительная площадь: важнее непрерывный ход).
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    rows = [r for r in rows if r.get("parts")]
    if not rows or not cats:
        return _foot(im, source, watermark, note, t, 1.2)
    nc = len(cats)
    if nc > MAX_PARTS:
        print(f"накопительная: {nc} категорий — соседние ступени шкалы "
              f"уже не различаются, сверни мелкие в «прочее»", file=sys.stderr)
    sums = [sum(float(v or 0) for v in r["parts"][:nc]) for r in rows]
    ticks, lo, hi = _ticks(0, max(sums))
    # в режиме площади подписи категорий стоят справа от своих полос,
    # поэтому поле сужается ровно на самое длинное название
    f_side = sc._f(sc.F_HEAD, 27)
    pad = max([sc.track_w(c.get("name", "").upper(), f_side, 2)
               for c in cats] or [0]) if mode == "area" else 0
    px1 = PX1 if not pad else max(W * 0.52, min(PX1, W - 46 - pad))
    im, ypos = _y_axis(im, ticks, lo, hi, False, unit, t, px1=px1)
    im = _legend(im, [(c.get("name", ""), _col(c.get("color"), i, ordered=True))
                      for i, c in enumerate(cats)], t, 0.45)

    n = len(rows)
    T0, PER = 0.9, 0.42
    f_mark = sc._f(sc.F_HEAD, 30)
    f_tot = sc._f(sc.MONO_B, 31)

    if mode == "area":
        step = (px1 - PX0) / max(n - 1, 1)
        prog = 1.0 if t is None else sc._ease((t - T0) / 3.2)
        box = (PX0 - 10, PY0 - 40, W - 6, PY1 + 10)
        bw, bh = box[2] - box[0], box[3] - box[1]
        acc = [0.0] * n
        for ci, c in enumerate(cats):
            color = _col(c.get("color"), ci, ordered=True)
            low = list(acc)
            for i, r in enumerate(rows):
                acc[i] += float((r["parts"][ci:ci + 1] or [0])[0] or 0)
            k = max(2, int(round(prog * (n - 1))) + 1)
            xs = [PX0 + step * i for i in range(k)]
            if prog < 1 and k < n:
                frac = prog * (n - 1) - (k - 1)
                if frac > 0:
                    xs.append(PX0 + step * (k - 1 + frac))
            if len(xs) < 2:
                continue
            sc._ev(sfx, T0 + ci * 0.12, "label")

            def poly(d, ss, ci=ci, low=low, xs=xs):
                top, bot = [], []
                for x in xs:
                    u = (x - PX0) / step
                    i0 = min(int(u), n - 1)
                    i1 = min(i0 + 1, n - 1)
                    fr = u - i0
                    hi_v = acc[i0] + (acc[i1] - acc[i0]) * fr
                    lo_v = low[i0] + (low[i1] - low[i0]) * fr
                    top.append(((x - box[0]) * ss, (ypos(hi_v) - box[1]) * ss))
                    bot.append(((x - box[0]) * ss, (ypos(lo_v) - box[1]) * ss))
                d.polygon(top + bot[::-1], fill=255)
            m = _aa((bw, bh), poly, ss=2)
            _tint(im, box, m, color, 0.88)

            def edge(d, ss, ci=ci, xs=xs):
                p = []
                for x in xs:
                    u = (x - PX0) / step
                    i0 = min(int(u), n - 1)
                    i1 = min(i0 + 1, n - 1)
                    fr = u - i0
                    v = acc[i0] + (acc[i1] - acc[i0]) * fr
                    p.append(((x - box[0]) * ss, (ypos(v) - box[1]) * ss))
                if len(p) > 1:
                    d.line(p, fill=255, width=max(2, int(2 * ss)), joint="curve")
            me = _aa((bw, bh), edge)
            _tint(im, box, me, (235, 235, 235), 0.5)
            # прямая подпись категории — на своей полосе у правого края
            al, dxl = sc._rv(t, T0 + 0.6 + ci * 0.12)
            if al > 0 and prog > 0.9:
                ymid = (ypos(acc[-1]) + ypos(low[-1])) / 2
                im = sc._put(im, lambda d, ymid=ymid, c=c, color=color:
                             sc.track(d, (px1 + 24, ymid - 16),
                                      c.get("name", "").upper(),
                                      f_side, color + (255,), 2),
                             al, dxl)
        a, _ = sc._rv(t, 0.6)
        if a > 0:
            f = sc._f(sc.MONO, 22)

            def xlab(d):
                every = max(1, int(math.ceil(n * 110 / max(px1 - PX0, 1))))
                for i, r in enumerate(rows):
                    if i % every and i != n - 1:
                        continue
                    s = str(r.get("mark", ""))
                    wd = sc.track_w(s, f, 1)
                    sc.track(d, (PX0 + step * i - wd / 2, AX_LAB_Y), s, f,
                             LAB + (255,), 1)
            im = sc._put(im, xlab, a, 0)
    else:
        slot = (px1 - PX0) / n
        bw_ = min(slot * 0.56, 168)
        for i, r in enumerate(rows):
            at = T0 + i * PER
            gr = 1.0 if t is None else sc._ease((t - at) / 0.6)
            if gr <= 0:
                continue
            sc._ev(sfx, at, "label")
            x = PX0 + slot * i + (slot - bw_) / 2
            base = PY1
            acc = 0.0
            for ci in range(len(cats)):
                v = float((r["parts"][ci:ci + 1] or [0])[0] or 0)
                if v <= 0:
                    continue
                color = _col(cats[ci].get("color"), ci, ordered=True)
                acc_new = acc + v
                y0 = ypos(acc_new) if gr >= 1 else PY1 - (PY1 - ypos(acc_new)) * gr
                y1 = ypos(acc) if gr >= 1 else PY1 - (PY1 - ypos(acc)) * gr
                acc = acc_new
                if y1 - y0 < 1:
                    continue
                im = sc._put(im, lambda d, x=x, y0=y0, y1=y1, color=color:
                             d.rectangle((x, y0, x + bw_, max(y0, y1 - 4)),
                                         fill=color + (255,)), 1.0, 0)
            # итог над столбцом: состав виден по сегментам, а сумма — нет
            if totals:
                aT, _ = sc._rv(t, at + 0.45)
                if aT > 0:
                    s = _num(sums[i])
                    wd = sc.track_w(s, f_tot, 2)
                    ytop = ypos(sums[i])
                    im = sc._put(im, lambda d, x=x, s=s, wd=wd, ytop=ytop:
                                 sc.track(d, (x + bw_ / 2 - wd / 2, ytop - 50), s,
                                          f_tot, sc.WHITE + (255,), 2), aT, 0)
            am, dxm = sc._rv(t, at + 0.1)
            mk = str(r.get("mark", ""))
            if mk and am > 0:
                wd = sc.track_w(mk, f_mark, 2)
                im = sc._put(im, lambda d, x=x, mk=mk, wd=wd:
                             sc.track(d, (x + bw_ / 2 - wd / 2, AX_LAB_Y), mk,
                                      f_mark, (206, 206, 206, 255), 2), am, dxm)

    im = _foot(im, source, watermark, note, t,
               T0 + (len(rows) * PER if mode == "bars" else 3.2) + 0.4)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 4. КАРТОГРАММА ─────────────────────────────────

_CARTO_CACHE = {}
_NAMES_CACHE = {}


def _geo_features(level="country", admin=None):
    """Контуры: страны мира или РЕГИОНЫ внутри страны (области, штаты,
    воеводства). Регионы лежат отдельным файлом — 1926 штук по Европе,
    СНГ, США, Китаю, Индии и Турции, с русскими названиями."""
    key = "country" if level == "country" else "region"
    if key not in _NAMES_CACHE:
        fname = "countries.geojson" if key == "country" else "regions.geojson"
        path = os.path.join(GEO, fname)
        if not os.path.exists(path):
            print(f"картограмма: нет файла {fname} — регионы недоступны",
                  file=sys.stderr)
            _NAMES_CACHE[key] = []
        else:
            _NAMES_CACHE[key] = json.load(open(path, encoding="utf-8"))["features"]
    feats = _NAMES_CACHE[key]
    if key == "region" and admin:
        want = _norm(admin)
        ru2en = {"РОССИЯ": "RUSSIA", "УКРАИНА": "UKRAINE", "БЕЛОРУССИЯ": "BELARUS",
                 "БЕЛАРУСЬ": "BELARUS", "ПОЛЬША": "POLAND", "ГЕРМАНИЯ": "GERMANY",
                 "КАЗАХСТАН": "KAZAKHSTAN", "США": "UNITED STATES OF AMERICA",
                 "ТУРЦИЯ": "TURKEY", "КИТАЙ": "CHINA", "ФИНЛЯНДИЯ": "FINLAND",
                 "ЛИТВА": "LITHUANIA", "ЛАТВИЯ": "LATVIA", "ЭСТОНИЯ": "ESTONIA",
                 "МОЛДАВИЯ": "MOLDOVA", "РУМЫНИЯ": "ROMANIA", "ВЕНГРИЯ": "HUNGARY",
                 "ГРУЗИЯ": "GEORGIA", "ИЗРАИЛЬ": "ISRAEL", "ИРАН": "IRAN",
                 "ФРАНЦИЯ": "FRANCE", "ИТАЛИЯ": "ITALY", "ИСПАНИЯ": "SPAIN",
                 "ШВЕЦИЯ": "SWEDEN", "НОРВЕГИЯ": "NORWAY"}
        want = ru2en.get(want, want)
        feats = [f for f in feats if _norm(f["properties"].get("ADMIN") or "") == want]
    return feats


def _norm(s):
    return str(s).strip().upper().replace("Ё", "Е")


def _find_feature(name, level="country", admin=None):
    """Страна по русскому названию: сверяем и полное имя, и короткое —
    в данных лежит «Российская Федерация», а в ролике говорят «Россия»."""
    want = _norm(name)
    short_to_full = {_norm(v): _norm(k) for k, v in getattr(
        sys.modules.get("datamap", object()), "SHORT_RU", {}).items()}
    # ТОЧНОЕ ИМЯ СНАЧАЛА, ПРЕФИКС — ТОЛЬКО ПОТОМ (2026-10-29).
    # Раньше условия стояли в одном «или», и побеждало то имя, которое
    # встретилось в geojson РАНЬШЕ. Живой счёт на данных: «Нигер»
    # подсвечивал НИГЕРИЮ — страна в кадре другая, никакого сообщения, и
    # проверить это глазами нельзя, если не знать карту Африки. Точное
    # имя «Нигер» в данных есть, просто «Нигерия» лежит перед ним.
    # Префиксное совпадение нужно (в данных «Российская Федерация», в
    # ролике «Россия»), но оно обязано уступать точному и говорить о
    # себе, когда подходит больше одного.
    feats = list(_geo_features(level, admin))
    for f in feats:
        nm = _norm(f["properties"].get("NAME_RU") or "")
        if nm and (want == nm or want == short_to_full.get(want, "")):
            return f
    near = []
    for f in feats:
        nm = _norm(f["properties"].get("NAME_RU") or "")
        if nm and (nm.startswith(want) or want.startswith(nm)):
            near.append((len(nm), nm, f))
    if near:
        near.sort(key=lambda x: x[0])
        if len(near) > 1:
            what = "страну" if level == "country" else "регион"
            print("картограмма: «%s» — точного имени нет, подходят по началу "
                  "%s; беру «%s». Если нужна другая, напиши её имя как в "
                  "данных." % (name, ", ".join("«%s»" % n for _, n, _ in near),
                               near[0][1]), file=sys.stderr)
        return near[0][2]
    return None


def _short_region(name):
    """«Мурманская область» -> «МУРМАНСКАЯ», «Ямало-Ненецкий автономный
    округ» -> «ЯМАЛО-НЕНЕЦКИЙ»: на карте и так понятно, что это регион,
    а полное название не влезает в плашку."""
    s = str(name)
    for tail in (" автономный округ", " автономная область", " область",
                 " край", " Республика", " республика", " автономный"):
        s = s.replace(tail, "")
    return s.strip()


def _region_for_values(feats, pad=7.0):
    """Окно карты по ГЕОМЕТРИИ выбранных территорий, а не по их
    подписям: по подписям Мурманская область уезжала за левый край —
    точка-ярлык попадала в кадр, а сама область нет."""
    xs, ys = [], []
    for f in feats:
        g = f.get("geometry")
        if g:
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            for poly in polys:
                ring = poly[0]
                for x, y in ring[::max(1, len(ring) // 40)]:
                    xs.append(float(x))
                    ys.append(float(y))
        p = f["properties"]
        if p.get("LABEL_X") is not None:
            xs.append(float(p["LABEL_X"]))
            ys.append(float(p["LABEL_Y"]))
    if not xs:
        return (-20, 60, 30, 72)
    lon0, lon1 = min(xs) - pad, max(xs) + pad
    lat0, lat1 = min(ys) - pad * 0.7, max(ys) + pad * 0.7
    klat = math.cos(math.radians((lat0 + lat1) / 2)) or 1.0
    want = (W / H) / klat
    have = (lon1 - lon0) / max(lat1 - lat0, 1e-6)
    if have < want:
        add = ((lat1 - lat0) * want - (lon1 - lon0)) / 2
        lon0, lon1 = lon0 - add, lon1 + add
    else:
        add = ((lon1 - lon0) / want - (lat1 - lat0)) / 2
        lat0, lat1 = lat0 - add, lat1 + add
    return lon0, lon1, lat0, lat1


def _masks(region, names, level="country", admin=None):
    """Маски стран под окно карты. Строятся раз на вызов и кэшируются:
    иначе на каждый кадр уходил бы разбор трёхмегабайтного geojson."""
    key = (tuple(round(v, 3) for v in region), tuple(names), level, admin)
    if key in _CARTO_CACHE:
        return _CARTO_CACHE[key]
    import datamap as dm
    proj = dm._projector(region)
    ss = 2
    out = {}
    for nm in names:
        f = _find_feature(nm, level, admin)
        if f is None:
            what = "страну" if level == "country" else "регион"
            print(f"картограмма: не нашёл {what} «{nm}» в geojson",
                  file=sys.stderr)
            continue
        geom = f["geometry"]
        if geom is None:
            continue
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" \
            else [geom["coordinates"]]
        m = Image.new("L", (W * ss, H * ss), 0)
        d = ImageDraw.Draw(m)
        for poly in polys:
            pts = [(x * ss, y * ss) for x, y in (proj(a, b) for a, b in poly[0])]
            if len(pts) >= 3:
                d.polygon(pts, fill=255)
        p = f["properties"]
        lab = None
        if p.get("LABEL_X") is not None:
            lab = proj(float(p["LABEL_X"]), float(p["LABEL_Y"]))
        out[nm] = (m.resize((W, H), Image.LANCZOS), lab, f)
    _CARTO_CACHE[key] = out
    return out


_GRID_CACHE = {}


def _region_grid(base, region, admin):
    """Тонкая сетка границ всех регионов страны — рисуется один раз и
    кэшируется: 85 областей на кадр заново считать нельзя."""
    key = (tuple(round(v, 3) for v in region), admin)
    if key not in _GRID_CACHE:
        import datamap as dm
        proj = dm._projector(region)
        ss = 2
        m = Image.new("L", (W * ss, H * ss), 0)
        d = ImageDraw.Draw(m)
        for f in _geo_features("region", admin):
            g = f.get("geometry")
            if not g:
                continue
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            for poly in polys:
                pts = [(x * ss, y * ss) for x, y in (proj(a, b) for a, b in poly[0])]
                if len(pts) >= 3:
                    d.line(pts + [pts[0]], fill=255, width=ss)
        _GRID_CACHE[key] = m.resize((W, H), Image.LANCZOS)
    out = base.copy()
    _tint(out, (0, 0, W, H), _GRID_CACHE[key], (96, 100, 108), 0.5)
    return out


def cartogram(out=None, kick="", title="", data=None, mode="choropleth",
              unit="", region=None, relief=True, accent=(), labels=True,
              show_values=True,
              scale_title="", level="country", admin=None, legend=True,
              shade=True, note=None, source="",
              watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Картограмма: величина, разложенная по странам.

    Единственный способ показать географию ЧИСЛА, а не события: дата-
    карта рисует потоки и точки, картограмма — «где больше». Заливка
    идёт одной шкалой от тёмного к золотому: у величины нет «другого
    цвета», у неё есть больше и меньше. Поэтому ни радуги, ни
    красно-зелёного здесь не будет никогда.

    data   — {"Польша": 42, ...} или, при level="region",
             {"Мурманская область": 42, ...} — по русским названиям.
    level  — "country" (страны мира) или "region" (области, края,
             штаты, воеводства ВНУТРИ страны; тогда нужен `admin` —
             название страны по-русски). Регионы есть по Европе, СНГ,
             США, Китаю, Индии, Турции — 1926 штук.
    mode   — "choropleth" (заливка страны) или "bubble" (кружок,
             площадь пропорциональна величине — честнее, когда страны
             сильно разного размера).
    accent — названия стран, которые надо выделить красным: сюжетная
             фигура остаётся отдельной ролью и не теряется в шкале.
    relief — под странами без данных виден затенённый рельеф, карта не
             выглядит школьным атласом.
    """
    import datamap as dm
    # КАРТА БЕЗ ЧИСЕЛ (28.10, прямое слово пользователя: «если нет цифр, не
    # ставим цифры»). `data` можно передать СПИСКОМ областей — тогда карта
    # просто подсвечивает их одну за другой: ни значений, ни шкалы, ни
    # легенды, ни единиц. Это самый частый случай в новостном ролике: речь
    # идёт про Украину — показываем Украину по областям, зритель видит
    # движение и тему, а не статистику.
    _context = isinstance(data, (list, tuple, set))
    if _context:
        names_in = [str(x) for x in data]
        # одинаковая яркость заливки, порядок подсветки — порядок списка
        data = {n: float(len(names_in) - i) for i, n in enumerate(names_in)}
        show_values = False
        legend = False
        unit = ""
        scale_title = ""
    data = {k: float(v) for k, v in (data or {}).items() if v is not None}
    im = sc.canvas()
    if not data:
        im = _head(im, kick, title, t, sfx)
        return _foot(im, source, watermark, note, t, 1.2)

    names = list(data.keys())
    feats = [f for f in (_find_feature(n, level, admin) for n in names)
             if f is not None]
    # ОКНО КАРТЫ — ПО ВСЕЙ СТРАНЕ, А НЕ ПО ПОДСВЕЧЕННЫМ ОБЛАСТЯМ (28.10).
    # Первая проба «Украина по областям» дала кадр, где подсвечен восток,
    # поэтому карта уехала вправо и сама Украина заняла четверть экрана:
    # зритель видел пол-Европы и не понимал, на что смотрит. Когда названа
    # страна, показываем страну целиком — подсветка внутри неё и так видна.
    if region:
        region = tuple(region)
    elif level != "country" and admin:
        _all = list(_geo_features(level, admin))
        # ЗАПАС ВОКРУГ СТРАНЫ — ПОЛТОРА ГРАДУСА, А НЕ СЕМЬ. Семь градусов
        # (умолчание, рассчитанное на одну-две области) раздували окно до
        # половины Европы: Украина занимала четверть кадра и не читалась.
        region = _region_for_values(_all or feats, pad=1.5)
    else:
        region = _region_for_values(feats)
    # подложка не подписывает страны, у которых будет своя плашка со
    # значением — иначе имя страны печатается на карте дважды
    skip = set(names) | {(f["properties"].get("NAME_RU") or "") for f in feats} | \
        {getattr(dm, "SHORT_RU", {}).get(f["properties"].get("NAME_RU"), "")
         for f in feats}
    base = dm.basemap(region, labels=(level == "country"), relief=relief,
                      skip=tuple(x for x in skip if x))
    if level != "country":
        # контуры ВСЕХ регионов страны слабым серым: иначе залитые
        # области висят в пустоте и карта не читается как карта
        base = _region_grid(base, region, admin)
    masks = _masks(region, names, level, admin)

    vmax = max(data.values())
    vmin = min(data.values())
    if _context:
        # шкалы нет: все области горят одинаково, разной остаётся только
        # ОЧЕРЕДЬ появления — именно она и создаёт движение в кадре
        vmin = 0.0
    order = sorted(names, key=lambda n: -data[n])
    T0, PER = 0.95, 0.26

    a_np = np.asarray(base, np.float32)
    for i, nm in enumerate(order):
        if nm not in masks:
            continue
        m, lab, f = masks[nm]
        at = T0 + i * PER
        gr = 1.0 if t is None else sc._ease((t - at) / 0.5)
        if gr <= 0:
            continue
        sc._ev(sfx, at, "label")
        k = (data[nm] - vmin) / (vmax - vmin) if vmax > vmin else 1.0
        # одна шкала: тёмная бронза -> золото. Сюжетная страна НЕ красится
        # красным: цвет на картограмме означает величину, и если им же
        # отмечать «главного», карта начинает врать. Акцент — обводка.
        c0, c1 = np.array((58, 50, 38), np.float32), np.array((208, 162, 46), np.float32)
        col = c0 + (c1 - c0) * (0.22 + 0.78 * k)
        if mode == "choropleth":
            # заливка не глухая: под ней остаётся виден рельеф, иначе
            # крупная страна с максимумом превращается в жёлтое поле
            mm = (np.asarray(m, np.float32) / 255.0)[..., None] * gr * 0.68
            # вспышка на новом и остывание: глаз успевает заметить, какая
            # именно страна зажглась (та же механика, что у дата-карты)
            flash = 0.0 if t is None else max(0.0, 1 - (t - at) * 1.6)
            c = col * (1 - flash) + np.array((238, 238, 238), np.float32) * flash
            a_np = a_np * (1 - mm) + mm * c
    im = Image.fromarray(np.clip(a_np, 0, 255).astype(np.uint8))

    # обводка сюжетной страны: вторичное кодирование поверх шкалы
    if accent and mode == "choropleth":
        from PIL import ImageChops
        want = {_norm(x) for x in accent}
        for i, nm in enumerate(order):
            if nm not in masks or _norm(nm) not in want:
                continue
            at = T0 + i * PER
            gr = 1.0 if t is None else sc._ease((t - at) / 0.5)
            if gr <= 0:
                continue
            m = masks[nm][0]
            edge = ImageChops.subtract(m, m.filter(ImageFilter.MinFilter(5)))
            _glow(im, (0, 0, W, H), edge, sc.RED, 0.40 * gr, 18)
            _tint(im, (0, 0, W, H), edge, (196, 56, 50), 0.92 * gr)

    if mode == "bubble":
        rmax = 118
        for i, nm in enumerate(order):
            if nm not in masks:
                continue
            m, lab, f = masks[nm]
            if lab is None:
                continue
            at = T0 + i * PER
            gr = 1.0 if t is None else sc._ease((t - at) / 0.5)
            if gr <= 0:
                continue
            r = rmax * math.sqrt(data[nm] / vmax) * gr
            col = sc.RED if _norm(nm) in {_norm(x) for x in accent} else sc.GOLD
            # Локальный бокс вокруг круга, а не полный кадр: маска 1920x1080
            # с суперсэмплингом считалась по несколько секунд НА КАЖДЫЙ круг
            # и рендер клипа уходил в десятки минут (поймано 20.10).
            pad = 34
            bx0 = int(max(0, lab[0] - r - pad))
            by0 = int(max(0, lab[1] - r - pad))
            bx1 = int(min(W, lab[0] + r + pad))
            by1 = int(min(H, lab[1] + r + pad))
            if bx1 - bx0 < 4 or by1 - by0 < 4:
                continue
            bsz = (bx1 - bx0, by1 - by0)
            cx, cy = lab[0] - bx0, lab[1] - by0

            def bub(d, ss, cx=cx, cy=cy, r=r):
                d.ellipse(((cx - r) * ss, (cy - r) * ss,
                           (cx + r) * ss, (cy + r) * ss), fill=255)
            mk = _aa(bsz, bub, ss=2)
            _glow(im, (bx0, by0), mk, col, 0.30, 20)
            _tint(im, (bx0, by0), mk, col, 0.42)

            def ring(d, ss, cx=cx, cy=cy, r=r):
                d.ellipse(((cx - r) * ss, (cy - r) * ss,
                           (cx + r) * ss, (cy + r) * ss),
                          outline=255, width=max(2, int(2 * ss)))
            mr = _aa(bsz, ring, ss=2)
            _tint(im, (bx0, by0), mr, col)

    # Шторки сверху и снизу: карта — это картинка во весь кадр, и
    # заголовок с подвалом иначе ложатся на залитую страну или на кружок.
    # Градиент, а не плашка: границы не видно, читаемость полная.
    sh = Image.new("L", (1, H), 0) if shade else None
    px = sh.load() if shade else None
    for y in (range(H) if shade else ()):
        a = 0
        if y < HEAD_BOTTOM + 54:
            a = int(188 * min(1.0, (HEAD_BOTTOM + 54 - y) / (HEAD_BOTTOM + 54)) ** 0.75)
        if y > 876:
            a = max(a, int(178 * min(1.0, (y - 876) / 150.0) ** 0.8))
        px[0, y] = a
    if shade:
        im.paste(Image.new("RGB", (W, H), sc.bg(0.82)), (0, 0), sh.resize((W, H)))

    im = _head(im, kick, title, t, sfx)

    # подписи значений: только там, где есть место, и с плашкой — на
    # рельефе белый текст без подложки не читается
    if labels:
        # шапка и подвал заняты заранее: иначе плашка со значением
        # садится прямо на заголовок — поймано на витрине 20.10
        taken = [(sc.MARGIN_L - 60, 210, 1560, HEAD_BOTTOM + 8),
                 (0, 884, W, H)]
        f_v = sc._f(sc.MONO_B, 30)
        f_n = sc._f(sc.F_HEAD, 25)
        for i, nm in enumerate(order):
            if nm not in masks:
                continue
            m, lab, f = masks[nm]
            if lab is None:
                continue
            at = T0 + i * PER + 0.14
            av, dxv = sc._rv(t, at)
            if av <= 0:
                continue
            # show_values=False — карта просто ПОДСВЕЧИВАЕТ названные
            # области: на плашке остаётся одно название. Нужно там, где
            # в сюжете названы направления, а чисел по ним нет и
            # выдумывать их нельзя (20.10)
            txt = _unit(data[nm], unit) if show_values else ""
            if level == "country":
                short = getattr(dm, "SHORT_RU", {}).get(
                    f["properties"].get("NAME_RU"),
                    f["properties"].get("NAME_RU") or nm)
            else:
                short = _short_region(f["properties"].get("NAME_RU") or nm)
            wv = f_v.getlength(txt) if txt else 0
            wn = sc.track_w(short.upper(), f_n, 2)
            bw_ = max(wv, wn) + 30
            x = max(14, min(W - bw_ - 14, lab[0] - bw_ / 2))

            def busy(b):
                return any(not (b[2] < q[0] or b[0] > q[2] or
                                b[3] < q[1] or b[1] > q[3]) for q in taken)
            bx = None
            for dy in (0, 92, -92, 184, -184):
                y = max(24, min(H - 210, lab[1] - 34 + dy))
                cand = (x, y, x + bw_, y + 74)
                if not busy(cand):
                    bx = cand
                    break
            if bx is None:
                continue
            taken.append(bx)
            accent_on = _norm(nm) in {_norm(z) for z in accent}

            def plate(d, bx=bx, txt=txt, short=short, accent_on=accent_on,
                      lab=lab):
                # если плашку пришлось отодвинуть от территории — тонкая
                # выноска к ней, иначе число висит в стороне и непонятно,
                # к чему относится (видно на тесте по областям 20.10)
                cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
                if abs(cx - lab[0]) > 46 or abs(cy - lab[1]) > 46:
                    d.line([(cx, cy), (lab[0], lab[1])],
                           fill=(120, 120, 128, 190), width=1)
                    d.ellipse((lab[0] - 4, lab[1] - 4, lab[0] + 4, lab[1] + 4),
                              fill=(sc.RED if accent_on else sc.GOLD) + (235,))
                d.rectangle(bx, fill=(12, 12, 14, 212))
                d.rectangle((bx[0], bx[1], bx[0] + 4, bx[3]),
                            fill=(sc.RED if accent_on else sc.GOLD) + (255,))
                d.text((bx[0] + 15, bx[1] + 4), txt, font=f_v,
                       fill=sc.WHITE + (255,))
                sc.track(d, (bx[0] + 15, bx[1] + 44), short.upper(), f_n,
                         (160, 160, 166, 255), 2)
            im = sc._put(im, plate, av, dxv)

    # легенда-градиент: без неё заливка не переводится в величину
    al, _ = sc._rv(t, T0 + 0.3)
    if al > 0 and mode == "choropleth" and legend:
        def leg(d):
            # легенда справа внизу: слева идут сноска и строка-источник,
            # и градиент садился ровно на них
            lx, ly, lw, lh = W - 390, 916, 330, 18
            # плашка под легендой: градиент может лечь на светлую страну
            d.rectangle((lx - 22, ly - 50, lx + lw + 22, ly + lh + 42),
                        fill=(12, 12, 14, 205))
            for k in range(lw):
                q = k / (lw - 1)
                c0 = (58, 50, 38)
                c1 = sc.GOLD
                c = tuple(int(c0[j] + (c1[j] - c0[j]) * (0.22 + 0.78 * q))
                          for j in range(3))
                d.rectangle((lx + k, ly, lx + k + 1, ly + lh), fill=c + (255,))
            f = sc._f(sc.MONO, 21)
            d.text((lx, ly + lh + 9), _unit(vmin, unit), font=f, fill=LAB + (255,))
            s = _unit(vmax, unit)
            d.text((lx + lw - f.getlength(s), ly + lh + 9), s, font=f,
                   fill=LAB + (255,))
            ttl = (scale_title or unit).upper()
            if ttl:
                fh = sc._f(sc.F_HEAD, 23)
                sc.track(d, (lx, ly - 34), ttl, fh, (150, 150, 156, 255), 3)
        im = sc._put(im, leg, al, 0)

    im = _foot(im, source, watermark, note, t, T0 + len(order) * PER + 0.4)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 5. РАЗБРОС ────────────────────────────────────

def scatter(out=None, kick="", title="", points=(), x_title="", y_title="",
            x_unit="", y_unit="", quadrants=None, note=None, source="",
            watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Диаграмма разброса: две величины друг против друга.

    Единственный тип, который показывает СВЯЗЬ: много денег — мало
    результата, много обещаний — мало поставок. Поэтому у каждой точки
    обязательна подпись: без имён это облако ни о чём.

    points    — [{"name", "x", "y", "size", "accent", "note"}].
    quadrants — {"x": значение, "y": значение, "labels": [пр.верх,
                 пр.низ, лев.низ, лев.верх]} — деление на четверти с
                 подписями: «много тратит и мало получает» и так далее.
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    pts = [p for p in points if p.get("x") is not None and p.get("y") is not None]
    if not pts:
        return _foot(im, source, watermark, note, t, 1.2)

    xs = [float(p["x"]) for p in pts]
    ys = [float(p["y"]) for p in pts]
    xt, xlo, xhi = _ticks(min(xs), max(xs))
    yt, ylo, yhi = _ticks(min(ys), max(ys))
    px1 = PX1
    # название вертикальной оси идёт в строку с единицей над шкалой:
    # отдельной строкой под заголовком оно читалось как подзаголовок
    ylab = ", ".join(x for x in (y_title.upper() if y_title else "", y_unit) if x)
    im, ypos = _y_axis(im, yt, ylo, yhi, False, ylab, t, px1=px1)

    def xpos(v):
        return PX0 + (v - xlo) / (xhi - xlo) * (px1 - PX0)

    # риски и подписи оси X
    a, _ = sc._rv(t, 0.55)
    if a > 0:
        f = sc._f(sc.MONO, 21)

        def xlab(d):
            for v in xt:
                x = xpos(v)
                if x < PX0 - 2 or x > px1 + 2:
                    continue
                d.rectangle((x, PY0, x + 1, PY1), fill=GRID + (255,))
                sv = _unit(v, x_unit)
                d.text((x - f.getlength(sv) / 2, AX_LAB_Y), sv, font=f, fill=LAB + (255,))
            if x_title:
                fh = sc._f(sc.F_HEAD, 24)
                w = sc.track_w(x_title.upper(), fh, 3)
                sc.track(d, (px1 - w, AX_LAB_Y + 42), x_title.upper(), fh,
                         (140, 140, 146, 255), 3)
        im = sc._put(im, xlab, a, 0)

    # четверти: именно они превращают облако в утверждение
    if quadrants:
        aq, _ = sc._rv(t, 0.7)
        if aq > 0:
            qx, qy = xpos(float(quadrants["x"])), ypos(float(quadrants["y"]))

            def quad(d):
                for y in range(int(PY0), int(PY1), 22):
                    d.rectangle((qx, y, qx + 1, y + 11), fill=(96, 96, 102, 255))
                for x in range(int(PX0), int(px1), 22):
                    d.rectangle((x, qy, x + 11, qy + 1), fill=(96, 96, 102, 255))
                labs = quadrants.get("labels") or []
                f = sc._f(sc.MONO, 22)
                spots = [(px1 - 16, PY0 + 12, "r"), (px1 - 16, PY1 - 40, "r"),
                         (PX0 + 16, PY1 - 40, "l"), (PX0 + 16, PY0 + 12, "l")]
                for lb, (x, y, al) in zip(labs, spots):
                    w = f.getlength(lb)
                    d.text((x - w if al == "r" else x, y), lb, font=f,
                           fill=(126, 126, 132, 255))
            im = sc._put(im, quad, aq, 0)

    T0, PER = 0.95, 0.22
    box = (PX0 - 60, PY0 - 60, W - 6, PY1 + 60)
    bw, bh = box[2] - box[0], box[3] - box[1]
    f_nm = sc._f(sc.F_HEAD, 27)
    f_sub = sc._f(sc.MONO, 21)
    taken = []
    for i, p in enumerate(sorted(pts, key=lambda q: -float(q.get("size", 1)))):
        at = T0 + i * PER
        gr = 1.0 if t is None else sc._ease((t - at) / 0.45)
        if gr <= 0:
            continue
        sc._ev(sfx, at, "label")
        x, y = xpos(float(p["x"])), ypos(float(p["y"]))
        acc = bool(p.get("accent"))
        r = (13 + 15 * min(float(p.get("size", 1)), 4) / 4) * gr
        col = sc.RED if acc else (sc.GOLD if i == 0 else sc.WHITE)

        def dot(d, ss, x=x, y=y, r=r):
            d.ellipse(((x - box[0] - r) * ss, (y - box[1] - r) * ss,
                       (x - box[0] + r) * ss, (y - box[1] + r) * ss), fill=255)
        m = _aa((bw, bh), dot, ss=2)
        _glow(im, box, m, col, 0.42, 16)
        _tint(im, box, m, col, 0.92)

        # подпись рядом с точкой, со сдвигом, если место занято
        nm = str(p.get("name", ""))
        if not nm:
            continue
        an, dxn = sc._rv(t, at + 0.12)
        if an <= 0:
            continue
        wd = max(sc.track_w(nm.upper(), f_nm, 1),
                 f_sub.getlength(str(p.get("note", ""))))
        cand = [(x + r + 14, y - 18), (x - r - 14 - wd, y - 18),
                (x - wd / 2, y - r - 54), (x - wd / 2, y + r + 16)]
        spot = None
        for cx, cy in cand:
            b = (cx - 8, cy - 6, cx + wd + 8, cy + 56)
            if b[0] < 8 or b[2] > W - 8 or b[1] < PY0 - 70 or b[3] > PY1 + 46:
                continue
            if any(not (b[2] < q[0] or b[0] > q[2] or b[3] < q[1] or b[1] > q[3])
                   for q in taken):
                continue
            spot = (cx, cy, b)
            break
        if spot is None:
            continue
        taken.append(spot[2])

        def lab(d, p=p, nm=nm, cx=spot[0], cy=spot[1], col=col):
            sc.track(d, (cx, cy), nm.upper(), f_nm,
                     (sc.WHITE if not p.get("accent") else sc.RED) + (255,), 1)
            sub = p.get("note") or ""
            if sub:
                d.text((cx, cy + 32), sub, font=f_sub, fill=(146, 146, 152, 255))
        im = sc._put(im, lab, an, dxn)

    im = _foot(im, source, watermark, note, t, T0 + len(pts) * PER + 0.3)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 6. СЕТКА МАЛЫХ ГРАФИКОВ ────────────────────────

def multiples(out=None, kick="", title="", cells=(), x_labels=(), unit="",
              cols=0, same_scale=True, note=None, source="",
              watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Сетка одинаковых мини-графиков: один сюжет, много участников.

    Нужна там, где четыре кривые на одном поле превращаются в клубок:
    каждому участнику свой маленький график, но шкала ОДНА на всех —
    иначе рост на 3% и рост втрое выглядят одинаково. Подписывается
    только последнее значение каждой ячейки.

    cells — [{"name", "values", "accent"}], 2-8 штук.
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    cells = [c for c in cells if c.get("values")]
    if not cells:
        return _foot(im, source, watermark, note, t, 1.2)
    n = len(cells)
    cols = cols or (2 if n <= 4 else (3 if n <= 6 else 4))
    rows = int(math.ceil(n / cols))
    allv = [v for c in cells for v in c["values"] if v is not None]
    _, lo, hi = _ticks(min(min(allv), 0), max(allv))

    GX0, GX1 = PX0, W - 232
    GY0, GY1 = PY0 - 22, PY1 + 30
    cw = (GX1 - GX0) / cols
    chh = (GY1 - GY0) / rows
    pad_x, pad_y = 26, 70
    T0, PER = 0.9, 0.26
    f_nm = sc._f(sc.F_HEAD, 28)
    f_v = sc._f(sc.MONO_B, 27)
    f_x = sc._f(sc.MONO, 19)

    for i, c in enumerate(cells):
        at = T0 + i * PER
        a, dx = sc._rv(t, at)
        if a <= 0:
            continue
        sc._ev(sfx, at, "label")
        r, col = divmod(i, cols)
        x0 = GX0 + col * cw + pad_x
        x1 = GX0 + (col + 1) * cw - pad_x
        y0 = GY0 + r * chh + pad_y
        y1 = GY0 + (r + 1) * chh - 48
        vals = [v for v in c["values"] if v is not None]
        if len(vals) < 2:
            continue
        acc = bool(c.get("accent"))
        color = sc.RED if acc else sc.GOLD
        step = (x1 - x0) / (len(c["values"]) - 1)

        def ypos(v, y0=y0, y1=y1):
            return y1 - (v - lo) / (hi - lo) * (y1 - y0)

        pts = [(x0 + step * k, ypos(v))
               for k, v in enumerate(c["values"]) if v is not None]
        poly = _smooth(pts)
        box = (int(x0 - 16), int(y0 - 26), int(x1 + 150), int(y1 + 16))
        bw, bh = box[2] - box[0], box[3] - box[1]

        def area(d, ss, poly=poly, y1=y1):
            d.polygon([((px - box[0]) * ss, (py - box[1]) * ss) for px, py in poly] +
                      [((poly[-1][0] - box[0]) * ss, (y1 - box[1]) * ss),
                       ((poly[0][0] - box[0]) * ss, (y1 - box[1]) * ss)], fill=255)
        ma = _aa((bw, bh), area, ss=2)
        _tint(im, box, ma, color, 0.22 * a)

        def ln(d, ss, poly=poly):
            d.line([((px - box[0]) * ss, (py - box[1]) * ss) for px, py in poly],
                   fill=255, width=max(2, int(2.4 * ss)), joint="curve")
        ml = _aa((bw, bh), ln)
        _tint(im, box, ml, color, a)

        def deco(d, x0=x0, x1=x1, y1=y1, c=c, pts=pts, color=color):
            d.rectangle((x0, y1 + 2, x1, y1 + 3), fill=(70, 70, 76, 255))
            sc.track(d, (x0, y0 - 44), str(c.get("name", "")).upper(), f_nm,
                     (sc.WHITE if not c.get("accent") else sc.RED) + (255,), 1)
            last = pts[-1]
            d.ellipse((last[0] - 6, last[1] - 6, last[0] + 6, last[1] + 6),
                      fill=(240, 240, 240, 255))
            # итог ячейки держится В СВОЕЙ ячейке: подпись справа от точки
            # залезала на соседний график и за край кадра
            lv = _unit(c["values"][-1], unit)
            lw = f_v.getlength(lv)
            lx = min(last[0] + 12, x1 - lw)
            ly = max(y0 - 30, last[1] - 38)
            d.text((lx, ly), lv, font=f_v, fill=color + (255,))
            if x_labels:
                d.text((x0, y1 + 10), str(x_labels[0]), font=f_x, fill=(118, 118, 124, 255))
                s2 = str(x_labels[-1])
                d.text((x1 - f_x.getlength(s2), y1 + 10), s2, font=f_x,
                       fill=(118, 118, 124, 255))
        im = sc._put(im, deco, a, dx)

    im = _foot(im, source, watermark, note, t, T0 + n * PER + 0.3)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 7. ВОРОНКА ─────────────────────────────────────

def funnel(out=None, kick="", title="", steps=(), unit="", show_loss=True,
           note=None, source="", watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Воронка: сколько осталось на каждом шаге и где потеряли.

    Берётся там, где величина ПАДАЕТ по цепочке: обещано — выделено —
    законтрактовано — поставлено. Главное на ней не сами ступени, а
    ПРОВАЛЫ между ними, поэтому потеря подписывается красным прямо на
    переходе.

    steps — [{"label", "value", "note"}] сверху вниз, по убыванию.
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    steps = [s for s in steps if s.get("value") is not None]
    if len(steps) < 2:
        return _foot(im, source, watermark, note, t, 1.2)
    vals = [float(s["value"]) for s in steps]
    top = max(vals)
    n = len(steps)

    # Воронка стоит в середине: слева подписываются ПОТЕРИ, справа —
    # ступени. На всю ширину кадра она не ставится: обе колонки подписей
    # тогда уезжают за край (поймано на витрине 20.10).
    FX, FW = 452, 760
    FY0, FY1 = PY0 - 30, PY1 + 36
    band = (FY1 - FY0) / n
    T0, PER = 0.9, 0.34
    tight = n > 4
    f_lab = sc._f(sc.F_HEAD, 28 if tight else 32)
    f_val = sc._f(sc.MONO_B, 32 if tight else 38)
    f_sub = sc._f(sc.MONO, 19 if tight else 21)
    f_loss = sc._f(sc.MONO_B, 23 if tight else 25)

    for i, s in enumerate(steps):
        at = T0 + i * PER
        gr = 1.0 if t is None else sc._ease((t - at) / 0.5)
        if gr <= 0:
            continue
        sc._ev(sfx, at, "label")
        v = vals[i]
        w_top = FW * (v / top)
        w_bot = FW * ((vals[i + 1] / top) if i + 1 < n else (v / top) * 0.96)
        y0 = FY0 + band * i
        y1 = y0 + band - 10
        cx = FX + FW / 2
        col = _col(s.get("color"), i, ordered=True)
        if s.get("accent"):
            col = sc.RED
        k = gr
        box = (int(FX - 20), int(y0 - 10), int(FX + FW + 20), int(y1 + 14))
        bw, bh = box[2] - box[0], box[3] - box[1]

        def trap(d, ss, w_top=w_top, w_bot=w_bot, y0=y0, y1=y1, k=k):
            wt, wb = w_top * k, w_bot * k
            d.polygon([((cx - wt / 2 - box[0]) * ss, (y0 - box[1]) * ss),
                       ((cx + wt / 2 - box[0]) * ss, (y0 - box[1]) * ss),
                       ((cx + wb / 2 - box[0]) * ss, (y1 - box[1]) * ss),
                       ((cx - wb / 2 - box[0]) * ss, (y1 - box[1]) * ss)], fill=255)
        m = _aa((bw, bh), trap, ss=2)
        if s.get("accent"):
            _glow(im, box, m, col, 0.34, 18)
        _tint(im, box, m, col)

        a2, dx2 = sc._rv(t, at + 0.12)
        if a2 > 0:
            def lab(d, s=s, v=v, y0=y0, y1=y1, i=i):
                ym = (y0 + y1) / 2
                lx = FX + FW + 56
                sub = s.get("note") or (f"{v / top * 100:.0f}% от начала" if i else "")
                h = 36 + (28 if sub else 0)
                top_y = ym - h / 2 - 8
                sc.track(d, (lx, top_y), str(s["label"]).upper(),
                         f_lab, sc.WHITE + (255,), 1)
                d.text((lx, top_y + 34), _unit(v, unit), font=f_val,
                       fill=sc.GOLD + (255,))
                if sub:
                    d.text((lx, top_y + 34 + f_val.size + 6), sub, font=f_sub,
                           fill=(146, 146, 152, 255))
            im = sc._put(im, lab, a2, dx2)

        # потеря на переходе — главное число воронки
        if show_loss and i + 1 < n:
            loss = v - vals[i + 1]
            if loss > 0:
                a3, _ = sc._rv(t, at + PER * 0.8)
                if a3 > 0:
                    txt = f"-{_unit(loss, unit)}  ({loss / v * 100:.0f}%)"

                    def lo(d, txt=txt, y1=y1):
                        w = f_loss.getlength(txt)
                        d.text((FX - 42 - w, y1 - 16), txt, font=f_loss,
                               fill=(206, 62, 58, 255))
                    im = sc._put(im, lo, a3, 0)

    im = _foot(im, source, watermark, note, t, T0 + n * PER + 0.3)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 8. ТЕПЛОВАЯ КАРТА ──────────────────────────────

def heatmap(out=None, kick="", title="", rows=(), cols=(), values=(),
            unit="", scale_title="", note=None, source="",
            watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Тепловая карта: величина в двух измерениях сразу — что и когда.

    Берётся там, где важен РИТМ: удары по дням недели и часам, звонки по
    месяцам и странам, поставки по кварталам и направлениям. Одна шкала
    от тёмной бронзы к золоту: цвет здесь означает величину, и никакой
    радуги — иначе «много» и «мало» перестают читаться с первого взгляда.

    rows   — подписи строк (что), cols — подписи столбцов (когда),
    values — матрица len(rows) x len(cols); None = данных нет (клетка
             остаётся пустой, а не нулевой — это разные вещи).
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    if not rows or not cols or not values:
        return _foot(im, source, watermark, note, t, 1.2)
    flat = [v for r in values for v in r if isinstance(v, (int, float))]
    if not flat:
        return _foot(im, source, watermark, note, t, 1.2)
    vmin, vmax = min(flat), max(flat)

    f_row = sc._f(sc.F_HEAD, 26)
    f_col = sc._f(sc.MONO, 21)
    f_val = sc._f(sc.MONO_B, 22)
    left = PX0 + max([sc.track_w(str(r).upper(), f_row, 1) for r in rows] + [0]) + 26
    right = W - 232
    top, bottom = PY0 - 4, PY1 - 16
    cw = (right - left) / len(cols)
    ch_ = (bottom - top) / len(rows)
    gap = 3
    T0, PER = 0.9, 0.06

    for i, r in enumerate(rows):
        a, dx = sc._rv(t, T0 + i * PER * len(cols) * 0.35)
        if a > 0:
            im = sc._put(im, lambda d, i=i, r=r:
                         sc.track(d, (PX0, top + ch_ * i + ch_ / 2 - 15),
                                  str(r).upper(), f_row, (206, 206, 206, 255), 1), a, dx)
        for j, c in enumerate(cols):
            v = values[i][j] if j < len(values[i]) else None
            at = T0 + (i * len(cols) + j) * PER
            gr = 1.0 if t is None else sc._ease((t - at) / 0.35)
            if gr <= 0:
                continue
            x0, y0 = left + cw * j, top + ch_ * i
            x1, y1 = x0 + cw - gap, y0 + ch_ - gap
            if v is None:
                im = sc._put(im, lambda d, x0=x0, y0=y0, x1=x1, y1=y1:
                             d.rectangle((x0, y0, x1, y1), outline=(48, 48, 52, 255),
                                         width=1), gr, 0)
                continue
            k = (v - vmin) / (vmax - vmin) if vmax > vmin else 1.0
            c0 = np.array((52, 46, 38), np.float32)
            c1 = np.array((228, 180, 44), np.float32)
            col = tuple(int(x) for x in (c0 + (c1 - c0) * (0.18 + 0.82 * k)))
            im = sc._put(im, lambda d, x0=x0, y0=y0, x1=x1, y1=y1, col=col:
                         d.rectangle((x0, y0, x1, y1), fill=col + (255,)), gr, 0)
            # число пишем только там, где клетка крупная и значение заметное
            if cw > 86 and ch_ > 52 and k > 0.12:
                # в клетке только число: единица стоит в легенде, а «2 судов»
                # на экране читается как опечатка
                txt = _num(v)
                tw = f_val.getlength(txt)
                ink = (22, 20, 16) if k > 0.55 else (228, 228, 228)
                im = sc._put(im, lambda d, x0=x0, y0=y0, txt=txt, tw=tw, ink=ink:
                             d.text((x0 + (cw - gap) / 2 - tw / 2,
                                     y0 + (ch_ - gap) / 2 - 14), txt,
                                    font=f_val, fill=ink + (255,)), gr, 0)
        sc._ev(sfx, T0 + i * 0.12, "label")

    a, _ = sc._rv(t, 0.6)
    if a > 0:
        def collab(d):
            step = max(1, int(math.ceil(len(cols) * 90 / max(right - left, 1))))
            for j, c in enumerate(cols):
                if j % step and j != len(cols) - 1:
                    continue
                s2 = str(c)
                d.text((left + cw * j + (cw - gap) / 2 - f_col.getlength(s2) / 2,
                        bottom + 10), s2, font=f_col, fill=LAB + (255,))
        im = sc._put(im, collab, a, 0)

    al, _ = sc._rv(t, T0 + 0.4)
    if al > 0:
        def leg(d):
            lx, ly, lw, lh = W - 390, 916, 330, 18
            d.rectangle((lx - 22, ly - 50, lx + lw + 22, ly + lh + 42),
                        fill=(12, 12, 14, 205))
            for k in range(lw):
                q = k / (lw - 1)
                c0, c1 = (52, 46, 38), (228, 180, 44)
                col = tuple(int(c0[i] + (c1[i] - c0[i]) * (0.18 + 0.82 * q))
                            for i in range(3))
                d.rectangle((lx + k, ly, lx + k + 1, ly + lh), fill=col + (255,))
            f = sc._f(sc.MONO, 21)
            d.text((lx, ly + lh + 9), _unit(vmin, unit), font=f, fill=LAB + (255,))
            s2 = _unit(vmax, unit)
            d.text((lx + lw - f.getlength(s2), ly + lh + 9), s2, font=f, fill=LAB + (255,))
            ttl = (scale_title or unit).upper()
            if ttl:
                sc.track(d, (lx, ly - 34), ttl, sc._f(sc.F_HEAD, 23),
                         (150, 150, 156, 255), 3)
        im = sc._put(im, leg, al, 0)

    im = _foot(im, source, watermark, note, t, T0 + 1.6)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 9. ДЕРЕВО ДОЛЕЙ ────────────────────────────────

def _squarify(items, x, y, w, h):
    """Раскладка прямоугольников по долям: делим полосу по большей
    стороне, чтобы куски не вырождались в полоски."""
    out = []

    def rec(items, x, y, w, h):
        if not items:
            return
        if len(items) == 1:
            out.append((items[0], x, y, w, h))
            return
        total = sum(i["value"] for i in items)
        acc, cut = 0.0, 1
        for k in range(1, len(items)):
            acc += items[k - 1]["value"]
            if acc >= total / 2:
                cut = k
                break
        a = items[:cut]
        b = items[cut:]
        fa = sum(i["value"] for i in a) / total
        if w >= h:
            rec(a, x, y, w * fa, h)
            rec(b, x + w * fa, y, w * (1 - fa), h)
        else:
            rec(a, x, y, w, h * fa)
            rec(b, x, y + h * fa, w, h * (1 - fa))
    rec(items, x, y, w, h)
    return out


def treemap(out=None, kick="", title="", items=(), unit="", total=None,
            note=None, source="", watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Дерево долей: из чего состоит целое, когда частей много.

    Там, где круговая уже врёт (семь долей по 14% неразличимы), дерево
    честно показывает соотношение площадью. Цвет — та же упорядоченная
    золотая шкала, крупные доли подписаны внутри, мелкие — только
    названием, совсем мелкие не подписываются вовсе: подпись, не
    влезающая в свой прямоугольник, хуже её отсутствия.

    items — [{"label", "value", "accent", "note"}].
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    items = sorted([i for i in items if float(i.get("value", 0)) > 0],
                   key=lambda i: -float(i["value"]))
    if not items:
        return _foot(im, source, watermark, note, t, 1.2)
    tot = float(total) if total else sum(float(i["value"]) for i in items)
    X0, Y0 = PX0, PY0 - 16
    X1, Y1 = W - 232, PY1 + 24
    boxes = _squarify(items, X0, Y0, X1 - X0, Y1 - Y0)
    T0, PER = 0.9, 0.16
    f_big = sc._f(sc.F_HEAD, 40)
    f_small = sc._f(sc.F_HEAD, 26)
    f_pct = sc._f(sc.MONO_B, 30)
    f_note = sc._f(sc.MONO, 20)

    for n, (it, x, y, w, h) in enumerate(boxes):
        at = T0 + n * PER
        gr = 1.0 if t is None else sc._ease((t - at) / 0.4)
        if gr <= 0:
            continue
        sc._ev(sfx, at, "label")
        share = float(it["value"]) / tot
        col = _col(it.get("color"), n, ordered=True)
        if it.get("accent"):
            col = sc.RED
        pad = 3
        im = sc._put(im, lambda d, x=x, y=y, w=w, h=h, col=col:
                     d.rectangle((x + pad, y + pad, x + w - pad, y + h - pad),
                                 fill=col + (255,)), gr, 0)
        if w < 108 or h < 58:
            continue
        big = w > 240 and h > 120
        f_lab = f_big if big else f_small
        label = str(it["label"]).upper()
        if sc.track_w(label, f_lab, 1) > w - 34:
            f_lab = f_small
        if sc.track_w(label, f_lab, 1) > w - 34:
            continue
        ink = (22, 20, 16) if share > 0.14 or it.get("accent") else (232, 232, 232)
        pct = f"{share * 100:.0f}%"
        # когда значения и так в процентах, вторая подпись — тавтология
        val = "" if unit in ("%", "") else _unit(float(it["value"]), unit)

        def lab(d, x=x, y=y, w=w, h=h, label=label, f_lab=f_lab, ink=ink,
                pct=pct, val=val, big=big, it=it):
            sc.track(d, (x + 18, y + 16), label, f_lab,
                     (ink if not it.get("accent") else (255, 236, 232)) + (255,), 1)
            d.text((x + 18, y + 20 + f_lab.size + 6), pct, font=f_pct,
                   fill=(ink if not it.get("accent") else (255, 226, 222)) + (255,))
            if big and val:
                d.text((x + 18 + f_pct.getlength(pct) + 14,
                        y + 24 + f_lab.size + 10), val, font=f_note,
                       fill=(ink[0], ink[1], ink[2], 190))
                if it.get("note"):
                    d.text((x + 18, y + h - 38), str(it["note"])[:40], font=f_note,
                           fill=(ink[0], ink[1], ink[2], 190))
        im = sc._put(im, lab, gr, 0)

    im = _foot(im, source, watermark, note, t, T0 + len(boxes) * PER + 0.3)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 10. ГАНТ ───────────────────────────────────────

def gantt(out=None, kick="", title="", tasks=(), start=None, end=None,
          marks=(), today=None, unit="", note=None, source="",
          watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Диаграмма Ганта: что когда начинается, сколько длится и что с чем
    совпадает по времени.

    Для сюжетов про сроки: сроки поставок, этапы переговоров, графики
    ремонта. Главное, ради чего её берут, — НАЛОЖЕНИЯ: видно, что два
    этапа идут одновременно, а третий начинается только после.

    tasks — [{"label", "from", "to", "accent", "note"}]; from/to —
            числа (день, неделя, месяц) или «2026-03-01».
    marks — вехи: [{"at": ..., "text": "..."}]; today — вертикальная
            линия «сейчас».
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    tasks = [x for x in tasks if x.get("from") is not None and x.get("to") is not None]
    if not tasks:
        return _foot(im, source, watermark, note, t, 1.2)

    def num(v):
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            return y * 372 + mo * 31 + d       # грубая, но монотонная шкала
        return float(re.sub(r"[^\d.]", "", s) or 0)

    lo = num(start) if start is not None else min(num(x["from"]) for x in tasks)
    hi = num(end) if end is not None else max(num(x["to"]) for x in tasks)
    span = (hi - lo) or 1.0

    f_lab = sc._f(sc.F_HEAD, 28)
    f_note = sc._f(sc.MONO, 20)
    f_mark = sc._f(sc.MONO, 21)
    left = PX0 + max([sc.track_w(str(x["label"]).upper(), f_lab, 1)
                      for x in tasks] + [0]) + 28
    right = W - 240
    top, bottom = PY0 - 10, PY1 - 10
    n = len(tasks)
    band = (bottom - top) / n
    bar_h = min(band * 0.52, 46)
    T0, PER = 0.9, 0.26

    def xpos(v):
        return left + (num(v) - lo) / span * (right - left)

    # сетка вех и «сегодня»
    a, _ = sc._rv(t, 0.6)
    if a > 0:
        def grid(d):
            for mk in marks:
                x = xpos(mk["at"])
                for y in range(int(top), int(bottom), 20):
                    d.rectangle((x, y, x + 1, y + 10), fill=(62, 62, 68, 255))
                txt = str(mk.get("text", ""))
                d.text((x - f_mark.getlength(txt) / 2, bottom + 14), txt,
                       font=f_mark, fill=(150, 150, 156, 255))
            if today is not None:
                x = xpos(today)
                d.rectangle((x - 1, top - 12, x + 1, bottom + 6), fill=sc.RED + (235,))
                d.text((x + 10, top - 40), "СЕЙЧАС", font=f_mark, fill=sc.RED + (255,))
        im = sc._put(im, grid, a, 0)

    for i, task in enumerate(tasks):
        at = T0 + i * PER
        gr = 1.0 if t is None else sc._ease((t - at) / 0.45)
        if gr <= 0:
            continue
        sc._ev(sfx, at, "label")
        y = top + band * i + (band - bar_h) / 2
        x0, x1 = xpos(task["from"]), xpos(task["to"])
        x1 = x0 + (x1 - x0) * gr
        # Все полосы одного цвета: у каждой задачи своя строка с подписью,
        # различать их ещё и цветом незачем, а нижние ступени шкалы на
        # тёмном фоне просто пропадали (поймано 20.10).
        col = _col(task.get("color"), 0, ordered=True)
        if task.get("accent"):
            col = sc.RED
        im = sc._put(im, lambda d, y=y, x0=x0, x1=x1, col=col:
                     d.rectangle((x0, y, max(x0 + 3, x1), y + bar_h),
                                 fill=col + (255,)), 1.0, 0)
        a2, dx2 = sc._rv(t, at + 0.08)
        im = sc._put(im, lambda d, i=i, task=task, y=y:
                     sc.track(d, (PX0, y + bar_h / 2 - 16),
                              str(task["label"]).upper(), f_lab,
                              (sc.WHITE if task.get("accent") else (206, 206, 206)) + (255,),
                              1), a2, dx2)
        if task.get("note"):
            a3, _ = sc._rv(t, at + 0.2)
            im = sc._put(im, lambda d, task=task, x0=x0, y=y:
                         d.text((x0 + 12, y + bar_h + 6), str(task["note"])[:48],
                                font=f_note, fill=(150, 150, 156, 255)), a3, 0)

    im = _foot(im, source, watermark, note, t, T0 + n * PER + 0.3)
    if out:
        im.save(out)
    return im


# ─────────────────────────── 11. НАКЛОННЫЙ ГРАФИК ───────────────────────────

def slope(out=None, kick="", title="", items=(), left_label="", right_label="",
          unit="", note=None, source="", watermark="ДО ПРИГОВОРА",
          t=None, sfx=None):
    """Наклонный график «было — стало»: две колонки и линии между ними.

    Самый прямой способ показать, КТО вырос, а кто упал, когда моментов
    всего два. Линия вверх — рост, вниз — падение, и это читается без
    единой подписи оси.

    items — [{"label", "from", "to", "accent"}].
    """
    im = sc.canvas()
    im = _head(im, kick, title, t, sfx)
    items = [i for i in items if i.get("from") is not None and i.get("to") is not None]
    if not items:
        return _foot(im, source, watermark, note, t, 1.2)
    vals = [float(i["from"]) for i in items] + [float(i["to"]) for i in items]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.18 or 1
    lo, hi = lo - pad, hi + pad

    LX, RX = PX0 + 360, W - 560
    TOP, BOT = PY0 + 10, PY1 - 10

    def ypos(v):
        return BOT - (float(v) - lo) / (hi - lo) * (BOT - TOP)

    f_lab = sc._f(sc.F_HEAD, 29)
    f_val = sc._f(sc.MONO_B, 27)
    f_col = sc._f(sc.F_HEAD, 25)

    def _fit_lab(text, avail):
        """Подпись ряда ужимается под свободное место слева от значения.

        ДЕФЕКТ, ПОЙМАННЫЙ 26.10 НА ДВУХ ГРАФИКАХ СРАЗУ (улов `usuario-5a`):
        подпись рисовалась кеглем 29 всегда, а значение — справа от неё на
        фиксированном месте. Длинная подпись («ПОГИБШИЕ МОРЯКИ», «МОРСКОЙ
        ЭКСПОРТ ЗЕРНА») налезала на число, буквы и цифры смешивались, читать
        было нельзя — и рисовалка об этом НЕ ГОВОРИЛА. Вкладка обходила тем,
        что держала подпись в одно короткое слово, а описание уводила в кикер;
        теперь подбор кегля делает код: 29 → 19, ниже не опускаемся, там уже
        нечитаемо — в этом случае подпись обрезается с многоточием.
        """
        up = str(text).upper()
        for size in range(29, 18, -1):
            f = sc._f(sc.F_HEAD, size)
            if sc.track_w(up, f, 1) <= avail:
                return f, up
        f = sc._f(sc.F_HEAD, 19)
        full = up
        while len(up) > 4 and sc.track_w(up + "…", f, 1) > avail:
            up = up[:-1]
        # ОБРЕЗАЛИ — СКАЗАТЬ ВСЛУХ. Молчаливая обрезка это та же «тихая
        # поломка», что была до 26.10: вкладка увидит многоточие только
        # глазами на готовом кадре, то есть кругом позже.
        print("  slope: подпись «%s» не влезает, обрезана до «%s…» — "
              "дай короче или уведи описание в --kick" % (full, up),
              file=__import__("sys").stderr)
        return f, (up + "…")
    T0, PER = 0.9, 0.2

    a, _ = sc._rv(t, 0.6)
    if a > 0:
        def cols(d):
            d.rectangle((LX, TOP - 30, LX + 2, BOT + 20), fill=(58, 58, 64, 255))
            d.rectangle((RX, TOP - 30, RX + 2, BOT + 20), fill=(58, 58, 64, 255))
            if left_label:
                w = sc.track_w(left_label.upper(), f_col, 3)
                sc.track(d, (LX - w / 2, TOP - 74), left_label.upper(), f_col,
                         (150, 150, 156, 255), 3)
            if right_label:
                w = sc.track_w(right_label.upper(), f_col, 3)
                sc.track(d, (RX - w / 2, TOP - 74), right_label.upper(), f_col,
                         (150, 150, 156, 255), 3)
        im = sc._put(im, cols, a, 0)

    box = (PX0 - 10, PY0 - 60, W - 6, PY1 + 40)
    bw, bh = box[2] - box[0], box[3] - box[1]

    # Правые подписи разводим заранее: у двух близких значений (126 и 121)
    # числа садились друг на друга (поймано 20.10).
    right_y = {}
    order = sorted(range(len(items)), key=lambda k: ypos(items[k]["to"]))
    prev = None
    for k in order:
        y = ypos(items[k]["to"])
        if prev is not None and y - prev < 38:
            y = prev + 38
        right_y[k] = y
        prev = y

    for i, it in enumerate(items):
        at = T0 + i * PER
        gr = 1.0 if t is None else sc._ease((t - at) / 0.5)
        if gr <= 0:
            continue
        sc._ev(sfx, at, "label")
        y0, y1 = ypos(it["from"]), ypos(it["to"])
        up = float(it["to"]) >= float(it["from"])
        col = sc.RED if it.get("accent") else (sc.WHITE if up else (150, 150, 156))
        xe = LX + (RX - LX) * gr
        ye = y0 + (y1 - y0) * gr

        def ln(d, ss, y0=y0, xe=xe, ye=ye):
            d.line([((LX - box[0]) * ss, (y0 - box[1]) * ss),
                    ((xe - box[0]) * ss, (ye - box[1]) * ss)],
                   fill=255, width=max(2, int(3 * ss)))
            r = 7 * ss
            for px, py in (((LX - box[0]) * ss, (y0 - box[1]) * ss),
                           ((xe - box[0]) * ss, (ye - box[1]) * ss)):
                d.ellipse((px - r, py - r, px + r, py + r), fill=255)
        m = _aa((bw, bh), ln)
        _glow(im, box, m, col, 0.3, 12)
        _tint(im, box, m, col)

        a2, dx2 = sc._rv(t, at + 0.1)
        _vtxt = _unit(float(it["from"]), unit)
        _vx = LX - 24 - f_val.getlength(_vtxt)
        _flab, _ltxt = _fit_lab(it["label"], max(60, _vx - PX0 - 18))
        im = sc._put(im, lambda d, y0=y0, col=col, _flab=_flab, _ltxt=_ltxt,
                     _vtxt=_vtxt, _vx=_vx:
                     (sc.track(d, (PX0, y0 - 17), _ltxt, _flab, col + (255,), 1),
                      d.text((_vx, y0 - 15), _vtxt,
                             font=f_val, fill=(170, 170, 176, 255))), a2, dx2)
        if gr >= 0.98:
            a3, _ = sc._rv(t, at + 0.45)
            ry = right_y[i]

            def rlab(d, it=it, y1=y1, ry=ry, col=col):
                if abs(ry - y1) > 6:          # подпись отъехала — ведём к точке
                    d.line([(RX + 8, y1), (RX + 18, ry - 2)],
                           fill=(110, 110, 116, 200), width=1)
                d.text((RX + 24, ry - 15), _unit(float(it["to"]), unit),
                       font=f_val, fill=col + (255,))
            im = sc._put(im, rlab, a3, 0)

    im = _foot(im, source, watermark, note, t, T0 + len(items) * PER + 0.3)
    if out:
        im.save(out)
    return im


# ─────────────────────────── запуск из командной строки ─────────────────────

def _config_values(kind, cfg):
    """Числа, которые диаграмма покажет на экране. Подписи периодов
    (годы по оси X, метки столбцов) сюда НЕ идут: сверять надо величины,
    а не разметку."""
    v = []
    if kind == "line":
        for ser in cfg.get("series", []):
            v += [x for x in ser.get("values", []) if isinstance(x, (int, float))]
        if cfg.get("baseline"):
            v.append(cfg["baseline"].get("value"))
    elif kind == "pie":
        v += [s.get("value") for s in cfg.get("segments", [])]
        if isinstance(cfg.get("total"), (int, float)):
            v.append(cfg["total"])
    elif kind == "stack":
        for r in cfg.get("rows", []):
            v += [x for x in r.get("parts", []) if isinstance(x, (int, float))]
    elif kind == "cartogram":
        v += list((cfg.get("data") or {}).values())
    elif kind == "scatter":
        for pt in cfg.get("points", []):
            v += [pt.get("x"), pt.get("y")]
    elif kind == "multiples":
        for c in cfg.get("cells", []):
            v += [x for x in c.get("values", []) if isinstance(x, (int, float))]
    elif kind == "funnel":
        v += [s.get("value") for s in cfg.get("steps", [])]
    elif kind == "heatmap":
        for r in cfg.get("values", []):
            v += [x for x in r if isinstance(x, (int, float))]
    elif kind == "treemap":
        v += [i.get("value") for i in cfg.get("items", [])]
    elif kind == "slope":
        for i in cfg.get("items", []):
            v += [i.get("from"), i.get("to")]
    return [float(x) for x in v if isinstance(x, (int, float))]


def _check_facts(kind, cfg, facts_arg, allow_unverified=False):
    """Сверка чисел диаграммы с досье ролика (георадар + facts.md).

    Правило системы — «нет настоящих чисел с источником, диаграмма не
    рисуется» — до 20.10.2026 держалось на внимательности. Теперь оно
    проверяется: конфиг сверяется с фактами, собранными geo_facts.py.
    Не подтверждено — не рисуем (снять: --allow-unverified)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import geo_facts as gf
    if os.path.isdir(facts_arg):
        facts, _ = gf.collect(facts_arg)
    else:
        data = json.load(open(facts_arg, encoding="utf-8"))
        facts = data.get("facts", data if isinstance(data, list) else [])
    vals = _config_values(kind, cfg)
    if not vals:
        return cfg
    res = gf.verify(vals, facts)
    bad = [v for v, hit in res if hit is None]
    srcs = []
    for v, hit in res:
        if hit and hit.get("src") and hit["src"] not in srcs:
            srcs.append(hit["src"])
    print(f"сверка с досье: подтверждено {len(vals) - len(bad)} из {len(vals)}")
    for v, hit in res:
        if hit is None:
            print(f"  ✗ {v:g} — в досье нет")
        else:
            print(f"  ✓ {v:g} — {hit['text'][:80]}")
    if bad and not allow_unverified:
        print("\nДиаграмма НЕ нарисована: числа без источника на экран не идут.\n"
              "Либо найди их в досье (георадар, ШАГ 0 скилла), либо, если число\n"
              "действительно из другого источника, добавь его в facts.md ролика.\n"
              "Осознанно нарисовать как есть: --allow-unverified")
        raise SystemExit(2)
    if not cfg.get("source") and srcs:
        doms = []
        for u in srcs:
            d = re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", u)
            if d not in doms:
                doms.append(d)
        cfg["source"] = "по данным: " + ", ".join(doms[:3])
        print("источник подставлен из досье:", cfg["source"])
    return cfg


def _cli():
    """python3 charts.py <line|pie|stack|cartogram|scatter|multiples|funnel> \
            <config.json> <out.mp4|png>

    --facts <facts.json | папка проекта>   сверить числа с досье ролика
    --allow-unverified                     нарисовать, даже если не сошлось

    В конфиге — те же поля, что у функций, плюс "dur" (длительность
    клипа) и "anim" (сколько секунд рисовать покадрово; дальше идёт
    статичный хвост, это втрое ускоряет рендер и на экране не меняет
    ничего)."""
    if len(sys.argv) < 4:
        print(_cli.__doc__)
        raise SystemExit(1)
    kind, cfg_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
    facts_arg = None
    if "--facts" in sys.argv:
        facts_arg = sys.argv[sys.argv.index("--facts") + 1]
    fn = {"line": line, "pie": pie, "stack": stack, "cartogram": cartogram,
          "scatter": scatter, "multiples": multiples, "funnel": funnel,
          "heatmap": heatmap, "treemap": treemap, "gantt": gantt,
          "slope": slope}[kind]
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    if facts_arg:
        cfg = _check_facts(kind, cfg, facts_arg,
                           allow_unverified="--allow-unverified" in sys.argv)
    dur = float(cfg.pop("dur", 9.0))
    anim = cfg.pop("anim", None)
    if out.lower().endswith((".png", ".jpg", ".jpeg")):
        fn(out, **cfg)
        print("ok ->", out)
        return
    fn(out.rsplit(".", 1)[0] + ".jpg", **cfg)
    sc.render_anim(fn, cfg, dur, out,
                   anim_seconds=float(anim) if anim else None, sfx_out=True)
    print("ok ->", out)


if __name__ == "__main__":
    _cli()
