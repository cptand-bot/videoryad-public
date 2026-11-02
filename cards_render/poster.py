# -*- coding: utf-8 -*-
"""ПЛАКАТ-ИНФОГРАФИКА: один кадр, в котором собран весь сюжет.

Снят с образца, который пользователь дал 20.10.2026 (плакат про амурского
тигра: слева колонка фактов с иконками, в центре герой во весь рост,
справа карта ареала, особенности и график численности, внизу призыв).
Там это печатный лист; у нас — КАДР РОЛИКА, поэтому формат 16:9
(«работаем только с прямоугольным», прямое слово пользователя).

Что умеет:
  • левая колонка  — эпиграф, заголовок, подзаголовок, плашка-статус,
                     блок фактов «иконка + подпись + значение»;
  • центр          — фотография героя с мягким градиентом по краям,
                     чтобы колонки не упирались в кадр встык;
  • правая колонка — мини-карта с выделенной территорией (теми же
                     геоданными, что у картограммы), список особенностей
                     с круглыми иконками и мини-график динамики;
  • подвал         — источник и вотермарка, как у всех карточек.

Иконки рисуются КОДОМ, а не берутся картинками: у плаката их десяток,
и любой набор извне тащил бы за собой чужую стилистику. Набор:
снежинка, лапа, глаз, дерево, огонь, щит, корабль, молния, дом, часы,
карта, стрелка, груз, якорь, предупреждение.

Палитра и шрифты — те же, что у всего второго сборщика (style_cards).

  python3 poster.py <config.json> <out.png|out.mp4>
"""
import json
import math
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import style_cards as sc

W, H = sc.W, sc.H

# сетка плаката: три колонки
L_X, L_W = 72, 560                      # левая колонка
C_X, C_W = 672, 616                     # центр (фото)
R_X, R_W = 1336, 512                    # правая колонка
TOP = 62
BOT = 958                               # ниже — нижняя лента и подвал


# ───────────────────────────── иконки ───────────────────────────────────────

def icon(d, name, cx, cy, r, color, width=3):
    """Простые пиктограммы одним росчерком. Рисуются в круге радиуса r."""
    n = (name or "").lower()
    c = color + (255,) if len(color) == 3 else color
    k = r * 0.62

    def ln(x1, y1, x2, y2, w=width):
        d.line([(cx + x1, cy + y1), (cx + x2, cy + y2)], fill=c, width=w)

    if n in ("снежинка", "лёд", "мороз", "snow"):
        for a in range(0, 180, 60):
            dx, dy = math.cos(math.radians(a)) * k, math.sin(math.radians(a)) * k
            ln(-dx, -dy, dx, dy)
            for s in (1, -1):
                bx, by = dx * 0.55, dy * 0.55
                ln(bx * s, by * s, bx * s + dy * 0.28 * s, by * s - dx * 0.28 * s, 2)
                ln(bx * s, by * s, bx * s - dy * 0.28 * s, by * s + dx * 0.28 * s, 2)
    elif n in ("лапа", "след", "paw"):
        d.ellipse((cx - k * 0.62, cy - k * 0.1, cx + k * 0.62, cy + k * 0.85), fill=c)
        for sx in (-0.62, -0.2, 0.2, 0.62):
            d.ellipse((cx + k * sx - k * 0.22, cy - k * 0.78,
                       cx + k * sx + k * 0.22, cy - k * 0.3), fill=c)
    elif n in ("глаз", "наблюдение", "eye"):
        d.arc((cx - k, cy - k * 0.8, cx + k, cy + k * 0.8), 200, 340, fill=c, width=width)
        d.arc((cx - k, cy - k * 0.8, cx + k, cy + k * 0.8), 20, 160, fill=c, width=width)
        d.ellipse((cx - k * 0.28, cy - k * 0.28, cx + k * 0.28, cy + k * 0.28), fill=c)
    elif n in ("дерево", "лес", "tree"):
        ln(0, k * 0.9, 0, k * 0.2, width + 1)
        for i, s in enumerate((0.95, 0.72, 0.5)):
            y = k * (0.2 - i * 0.42)
            d.polygon([(cx, y + cy - k * 0.5), (cx - k * s * 0.7, cy + y),
                       (cx + k * s * 0.7, cy + y)], outline=c, width=width)
    elif n in ("огонь", "пожар", "fire"):
        d.polygon([(cx, cy - k), (cx + k * 0.7, cy + k * 0.2),
                   (cx + k * 0.35, cy + k * 0.85), (cx - k * 0.35, cy + k * 0.85),
                   (cx - k * 0.7, cy + k * 0.2)], outline=c, width=width)
        ln(0, k * 0.5, 0, -k * 0.25, 2)
    elif n in ("щит", "защита", "shield"):
        d.polygon([(cx, cy - k), (cx + k * 0.78, cy - k * 0.55),
                   (cx + k * 0.6, cy + k * 0.55), (cx, cy + k),
                   (cx - k * 0.6, cy + k * 0.55), (cx - k * 0.78, cy - k * 0.55)],
                  outline=c, width=width)
    elif n in ("корабль", "судно", "ship"):
        d.polygon([(cx - k, cy + k * 0.2), (cx + k, cy + k * 0.2),
                   (cx + k * 0.62, cy + k * 0.8), (cx - k * 0.62, cy + k * 0.8)],
                  outline=c, width=width)
        ln(0, k * 0.2, 0, -k * 0.9, width)
        ln(0, -k * 0.9, k * 0.6, -k * 0.3, 2)
    elif n in ("молния", "энергия", "bolt"):
        d.polygon([(cx + k * 0.25, cy - k), (cx - k * 0.55, cy + k * 0.1),
                   (cx - k * 0.05, cy + k * 0.1), (cx - k * 0.3, cy + k),
                   (cx + k * 0.6, cy - k * 0.15), (cx + k * 0.08, cy - k * 0.15)],
                  outline=c, width=width)
    elif n in ("дом", "здание", "house"):
        d.polygon([(cx, cy - k), (cx + k * 0.85, cy - k * 0.15),
                   (cx + k * 0.85, cy + k * 0.85), (cx - k * 0.85, cy + k * 0.85),
                   (cx - k * 0.85, cy - k * 0.15)], outline=c, width=width)
        d.rectangle((cx - k * 0.22, cy + k * 0.25, cx + k * 0.22, cy + k * 0.85),
                    outline=c, width=2)
    elif n in ("часы", "время", "clock"):
        d.ellipse((cx - k, cy - k, cx + k, cy + k), outline=c, width=width)
        ln(0, 0, 0, -k * 0.55, width)
        ln(0, 0, k * 0.42, 0, width)
    elif n in ("карта", "территория", "map"):
        d.polygon([(cx - k, cy - k * 0.55), (cx - k * 0.2, cy - k * 0.85),
                   (cx + k * 0.3, cy - k * 0.45), (cx + k, cy - k * 0.75),
                   (cx + k, cy + k * 0.6), (cx + k * 0.3, cy + k * 0.85),
                   (cx - k * 0.2, cy + k * 0.5), (cx - k, cy + k * 0.8)],
                  outline=c, width=width)
    elif n in ("груз", "контейнер", "box"):
        d.rectangle((cx - k * 0.85, cy - k * 0.6, cx + k * 0.85, cy + k * 0.8),
                    outline=c, width=width)
        ln(-k * 0.85, -k * 0.1, k * 0.85, -k * 0.1, 2)
        ln(-k * 0.2, -k * 0.6, -k * 0.2, k * 0.8, 2)
    elif n in ("якорь", "порт", "anchor"):
        d.ellipse((cx - k * 0.22, cy - k, cx + k * 0.22, cy - k * 0.56),
                  outline=c, width=width)
        ln(0, -k * 0.56, 0, k * 0.85, width)
        ln(-k * 0.5, -k * 0.3, k * 0.5, -k * 0.3, 2)
        d.arc((cx - k * 0.8, cy + k * 0.1, cx + k * 0.8, cy + k * 1.0),
              20, 160, fill=c, width=width)
    elif n in ("внимание", "риск", "warn"):
        d.polygon([(cx, cy - k), (cx + k, cy + k * 0.8), (cx - k, cy + k * 0.8)],
                  outline=c, width=width)
        ln(0, -k * 0.35, 0, k * 0.25, width)
        d.ellipse((cx - 3, cy + k * 0.45, cx + 3, cy + k * 0.45 + 6), fill=c)
    elif n in ("стрелка", "рост", "arrow"):
        ln(-k * 0.85, k * 0.6, k * 0.7, -k * 0.6, width)
        ln(k * 0.7, -k * 0.6, k * 0.15, -k * 0.6, width)
        ln(k * 0.7, -k * 0.6, k * 0.7, -k * 0.05, width)
    else:                                   # точка-заглушка
        d.ellipse((cx - k * 0.3, cy - k * 0.3, cx + k * 0.3, cy + k * 0.3), fill=c)


# ──────────────────────── анимация: кэши и счётчики ─────────────────────────

_PHOTO_CACHE = {}
_MAP_CACHE = {}


def _count_text(value, k):
    """Число в строке набегает от нуля: «96 дней» -> 0, 41, 78, 96 дней.
    Нечисловые значения (Arc7, «пересчёт») просто проявляются целиком."""
    s = str(value)
    if k >= 1.0:
        return s
    m = re.search(r"\d[\d  \u202f]*\d|\d", s)
    if not m:
        return s
    # «Arc7», «Ту-95», «COP29» — это коды, а не величины: счётчик там
    # выглядит поломкой, поэтому считаем только отдельно стоящее число
    if m.start() > 0 and s[m.start() - 1].isalpha():
        return s
    raw = m.group(0).rstrip(" \u202f ")
    num = float(raw.replace(" ", "").replace("\u202f", "").replace(" ", ""))
    cur = num * max(0.0, min(1.0, k))
    out = f"{int(round(cur)):,}".replace(",", " ")
    # хвостовой пробел числа возвращаем на место: «96 дней» при счёте
    # превращалось в «19дней» — пробел съедался вместе с цифрами
    return s[:m.start()] + out + s[m.start() + len(raw):]


def _pop(k):
    """Перелёт-«бульк» для иконки: 0 -> 1.18 -> 1."""
    k = max(0.0, min(1.0, k))
    return (k / 0.6) * 1.18 if k < 0.6 else 1.18 - (k - 0.6) / 0.4 * 0.18


# ──────────────────────────── части плаката ─────────────────────────────────

def _ribbon(d, x, y, w, text, color=sc.RED, ink=(246, 246, 246)):
    """Плашка-ленточка с косым краем — ею в образце отбиты заголовки блоков."""
    h = 40
    d.polygon([(x, y), (x + w, y), (x + w - 14, y + h), (x, y + h)],
              fill=color + (255,))
    f = sc._f(sc.F_HEAD, 25)
    sc.track(d, (x + 16, y + 6), text.upper(), f, ink + (255,), 3)
    return y + h + 18


def _photo_block(im, path, box, fade=True, zoom=1.0, alpha=1.0):
    """Фотография в центре: вписывается и растушёвывается по бокам, чтобы
    колонки не упирались в неё встык."""
    x0, y0, x1, y1 = box
    w, h = int(x1 - x0), int(y1 - y0)
    key = (path, w, h)
    if key not in _PHOTO_CACHE:
        try:
            # с запасом по краям: по нему и идёт наезд, без пересчёта файла
            big = ImageOps.fit(Image.open(path).convert("RGB"),
                               (int(w * 1.14), int(h * 1.14)), Image.LANCZOS)
        except Exception:
            big = Image.new("RGB", (int(w * 1.14), int(h * 1.14)), (30, 30, 32))
        _PHOTO_CACHE[key] = big
    big = _PHOTO_CACHE[key]
    z = max(1.0, min(1.14, zoom))
    cw, ch = int(big.width / 1.14 * (1.14 / z)), int(big.height / 1.14 * (1.14 / z))
    cw, ch = min(cw, big.width), min(ch, big.height)
    src = big.crop(((big.width - cw) // 2, (big.height - ch) // 2,
                    (big.width - cw) // 2 + cw,
                    (big.height - ch) // 2 + ch)).resize((w, h), Image.LANCZOS)
    if fade:
        m = Image.new("L", (w, h), 255)
        md = ImageDraw.Draw(m)
        g = max(10, int(w * 0.10))
        for i in range(g):
            a = int(255 * (i / g) ** 0.7)
            md.line([(i, 0), (i, h)], fill=a)
            md.line([(w - 1 - i, 0), (w - 1 - i, h)], fill=a)
        for i in range(int(h * 0.06)):
            a = int(255 * (i / (h * 0.06)) ** 0.7)
            md.line([(0, i), (w, i)], fill=min(a, m.getpixel((w // 2, i))))
        if alpha < 1:
            m = m.point(lambda v: int(v * alpha))
        im.paste(src, (int(x0), int(y0)), m)
    else:
        if alpha < 1:
            m = Image.new("L", (w, h), int(255 * alpha))
            im.paste(src, (int(x0), int(y0)), m)
        else:
            im.paste(src, (int(x0), int(y0)))


def _mini_map(im, box, region_data, admin=None, level="region", accent=(),
              reveal=1.0, sweep=None):
    """Мини-карта в правой колонке: те же геоданные, что у картограммы."""
    import charts as ch
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0, y1 - y0
    ckey = (tuple(sorted(region_data.items())), admin, level, tuple(accent), w, h)
    if ckey in _MAP_CACHE:
        crop = _MAP_CACHE[ckey]
        _map_paste(im, crop, (x0, y0, x1, y1), reveal, sweep)
        return
    try:
        full = ch.cartogram(None, data=region_data, level=level, admin=admin,
                            accent=list(accent), labels=False, relief=False,
                            legend=False, shade=False, kick="", title="",
                            source="", watermark="", t=None)
    except Exception as e:
        print("мини-карта не собралась:", e, file=sys.stderr)
        return
    # карта уже кадрирована по своим данным — вписываем её целиком,
    # дополнительный кроп обрезал как раз выделенные территории
    src_r, dst_r = full.width / full.height, w / h
    if dst_r > src_r:                       # блок шире — режем по высоте
        nh = int(full.width / dst_r)
        full = full.crop((0, (full.height - nh) // 2, full.width,
                          (full.height - nh) // 2 + nh))
    else:
        nw = int(full.height * dst_r)
        full = full.crop(((full.width - nw) // 2, 0,
                          (full.width - nw) // 2 + nw, full.height))
    crop = full.resize((w, h), Image.LANCZOS)
    _MAP_CACHE[ckey] = crop
    _map_paste(im, crop, (x0, y0, x1, y1), reveal, sweep)


def _map_paste(im, crop, box, reveal=1.0, sweep=None):
    """Карта проявляется, и по ней один раз проходит мягкая световая
    полоса — так взгляд цепляется за блок, а не пропускает его."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0, y1 - y0
    layer = crop
    if sweep is not None and 0 <= sweep <= 1:
        layer = crop.copy()
        band = Image.new("L", (w, h), 0)
        bd = ImageDraw.Draw(band)
        cx = int(-w * 0.4 + sweep * w * 1.8)
        for i in range(-90, 91):
            a = int(120 * (1 - abs(i) / 90) ** 2)
            bd.line([(cx + i, 0), (cx + i, h)], fill=a)
        band = band.filter(ImageFilter.GaussianBlur(10))
        layer.paste(Image.new("RGB", (w, h), (255, 240, 190)), (0, 0), band)
    if reveal < 1:
        m = Image.new("L", (w, h), int(255 * max(0.0, min(1.0, reveal))))
        im.paste(layer, (x0, y0), m)
    else:
        im.paste(layer, (x0, y0))
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle((x0, y0, x1, y1), outline=(70, 70, 76, 255), width=1)


def _mini_chart(im, box, values, labels=(), unit="", color=sc.GOLD, draw_k=1.0):
    """Мини-график динамики — как «бумажка с графиком» в образце."""
    x0, y0, x1, y1 = (int(v) for v in box)
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle((x0, y0, x1, y1), fill=(22, 22, 24, 235))
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < 2:
        return
    lo, hi = min(vals), max(vals)
    pad = 26
    gw, gh = (x1 - x0) - pad * 2, (y1 - y0) - pad * 2 - 16
    step = gw / (len(vals) - 1)
    pts = [(x0 + pad + step * i,
            y0 + pad + gh - (v - lo) / ((hi - lo) or 1) * gh)
           for i, v in enumerate(vals)]
    # кривая прочерчивается слева направо
    k = max(0.0, min(1.0, draw_k))
    if k < 1:
        n_full = max(1, int(k * (len(pts) - 1)))
        frac = k * (len(pts) - 1) - n_full
        head = pts[:n_full + 1]
        if n_full < len(pts) - 1 and frac > 0:
            ax, ay = pts[n_full]
            bx, by = pts[n_full + 1]
            head = head + [(ax + (bx - ax) * frac, ay + (by - ay) * frac)]
        pts = head if len(head) > 1 else pts[:2]
    d.line([(x0 + pad, y0 + pad + gh + 6), (x1 - pad, y0 + pad + gh + 6)],
           fill=(64, 64, 70, 255), width=1)
    d.line(pts, fill=color + (255,), width=3, joint="curve")
    for p in (pts[0], pts[-1]):
        d.ellipse((p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5), fill=(240, 240, 240, 255))
    f = sc._f(sc.MONO, 19)
    if labels:
        d.text((x0 + pad, y1 - 28), str(labels[0]), font=f, fill=(140, 140, 146, 255))
        s = str(labels[-1])
        d.text((x1 - pad - f.getlength(s), y1 - 28), s, font=f, fill=(140, 140, 146, 255))
    fb = sc._f(sc.MONO_B, 24)
    shown = vals[min(len(vals) - 1, int(k * (len(vals) - 1)))]
    s = f"{shown:g}{(' ' + unit) if unit else ''}"
    d.text((pts[-1][0] - fb.getlength(s) - 6, pts[-1][1] - 34), s, font=fb,
           fill=color + (255,))


def poster(out=None, *, kick="", title="", subtitle="", lead="", status=None,
           hero_photo="", facts=(), features=(), map_block=None,
           chart_block=None, bottom="", source="", watermark="ДО ПРИГОВОРА",
           t=None, sfx=None):
    """Плакат-инфографика целиком. Все блоки необязательны: чего нет, то
    просто не рисуется, а соседние блоки занимают его место.

    С 20.10.2026 плакат ОЖИВАЕТ (`t` — секунды): фотография едет наездом,
    шапка и плашки выезжают по очереди, иконки «булькают», цифры
    НАБЕГАЮТ счётчиком от нуля, по карте один раз проходит световая
    полоса, кривая графика прочерчивается, нижняя лента выезжает снизу.
    `t=None` — статичный кадр, как раньше.
    """
    A = (lambda at, dur=0.42: 1.0 if t is None
         else max(0.0, min(1.0, (t - at) / dur)))      # прогресс блока
    E = (lambda at, dur=0.42: sc._ease(A(at, dur)))    # он же со смягчением
    im = sc.canvas()
    d = ImageDraw.Draw(im, "RGBA")

    # ── центр: фотография с медленным наездом
    if hero_photo:
        k = E(0.0, 0.8)
        # Только приближение, медленно и в одну сторону: зум туда-сюда и
        # дрожь утомляют глаз (user, 20.10, прямым словом).
        zoom = 1.0 if t is None else 1.0 + 0.045 * min(1.0, (t or 0) / 9.0)
        _photo_block(im, hero_photo, (C_X, TOP, C_X + C_W, BOT),
                     zoom=zoom, alpha=0.25 + 0.75 * k)
        d = ImageDraw.Draw(im, "RGBA")

    # ── левая колонка
    y = TOP + 6
    if kick:
        a, dx = sc._rv(t, 0.15)
        if a > 0:
            f = sc._f(sc.F_HEAD, 26)
            im = sc._put(im, lambda dd, y=y: sc.track(dd, (L_X - dx, y),
                                                      kick.upper(), f,
                                                      sc.GOLD + (255,), 5), a, dx)
            d = ImageDraw.Draw(im, "RGBA")
        y += 44
    if title:
        f = sc._f(sc.F_HEAD, 86)
        for i, line in enumerate(_wrap(title.upper(), f, L_W, d)):
            a, dx = sc._rv(t, 0.3 + i * 0.12)
            if a > 0:
                im = sc._put(im, lambda dd, line=line, y=y:
                             dd.text((L_X, y), line, font=f,
                                     fill=sc.WHITE + (int(255 * a),)), a, dx)
                d = ImageDraw.Draw(im, "RGBA")
            y += int(f.size * 0.98)
        y += 8
    if subtitle:
        a, dx = sc._rv(t, 0.55)
        f = sc._f(sc.MONO, 26)
        if a > 0:
            im = sc._put(im, lambda dd, y=y: dd.text((L_X, y), subtitle, font=f,
                                                     fill=(168, 168, 174, 255)), a, dx)
            d = ImageDraw.Draw(im, "RGBA")
        y += 46
    if status:
        k = E(0.7, 0.35)
        if k > 0:
            sc._ev(sfx, 0.7, "accent")
            wdt = min(L_W, 420) * k
            _ribbon(d, L_X, y + 6, wdt, status.get("label", "") if k > 0.75 else "",
                    color=_c(status.get("color"), sc.RED))
        y += 58
    if lead:
        f = sc._f(sc.MONO, 23)
        for i, line in enumerate(_wrap(lead, f, L_W, d)):
            a, dx = sc._rv(t, 0.85 + i * 0.08)
            if a > 0:
                im = sc._put(im, lambda dd, line=line, y=y:
                             dd.text((L_X, y), line, font=f,
                                     fill=(196, 196, 200, int(255 * a))), a, dx)
                d = ImageDraw.Draw(im, "RGBA")
            y += 34
        y += 10

    if facts:
        k = E(1.25, 0.3)
        if k > 0:
            _ribbon(d, L_X, y + 4, 300 * k, "цифры" if k > 0.75 else "")
        y += 58
        for i, fct in enumerate(facts[:4]):
            at = 1.5 + i * 0.35
            a = A(at, 0.5)
            if a <= 0:
                y += 84
                continue
            sc._ev(sfx, at, "label")
            sz = _pop(a) if t is not None else 1.0
            icon(d, fct.get("icon", ""), L_X + 28, y + 26, 26 * sz,
                 _c(fct.get("color"), sc.GOLD))
            f1 = sc._f(sc.F_HEAD, 25)
            f2 = sc._f(sc.MONO_B, 34)
            sc.track(d, (L_X + 74, y + 2), str(fct.get("label", "")).upper(), f1,
                     (170, 170, 176, int(255 * min(1, a * 1.6))), 2)
            # цифра набегает от нуля и в конце коротко вспыхивает белым
            val = _count_text(fct.get("value", ""), a)
            flash = 0 if t is None else max(0.0, 1 - abs(a - 1.0) * 14)
            ink = tuple(int(c + (255 - c) * flash) for c in sc.WHITE)
            d.text((L_X + 74, y + 30), val, font=f2, fill=ink + (255,))
            y += 84

    # ── правая колонка
    ry = TOP + 6
    if map_block:
        k = E(1.1, 0.3)
        if k > 0:
            _ribbon(d, R_X, ry, 320 * k,
                    map_block.get("title", "где это") if k > 0.75 else "")
        ry += 58
        rev = A(1.35, 0.55)
        sweep = None if t is None else ((t - 1.9) / 1.1 if 1.9 <= t <= 3.0 else None)
        if rev > 0:
            _mini_map(im, (R_X, ry, R_X + R_W, ry + 268),
                      map_block.get("data", {}), map_block.get("admin"),
                      map_block.get("level", "region"), map_block.get("accent", ()),
                      reveal=rev, sweep=sweep)
            d = ImageDraw.Draw(im, "RGBA")
        ry += 268 + 14
        if map_block.get("note"):
            a, dx = sc._rv(t, 1.9)
            if a > 0:
                f = sc._f(sc.MONO, 21)
                im = sc._put(im, lambda dd, ry=ry: dd.text(
                    (R_X, ry), map_block["note"][:48], font=f,
                    fill=(150, 150, 156, 255)), a, dx)
                d = ImageDraw.Draw(im, "RGBA")
            ry += 34

    if features:
        k = E(2.2, 0.3)
        if k > 0:
            _ribbon(d, R_X, ry + 6, 360 * k, "особенности" if k > 0.75 else "")
        ry += 64
        for i, ft in enumerate(features[:4]):
            at = 2.45 + i * 0.3
            a = A(at, 0.45)
            if a <= 0:
                ry += 76
                continue
            sc._ev(sfx, at, "label")
            cx, cy = R_X + 30, ry + 28
            rr = 28 * (_pop(a) if t is not None else 1.0)
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                      fill=(26, 26, 28, 255), outline=(64, 64, 70, 255), width=2)
            icon(d, ft.get("icon", ""), cx, cy, 22, _c(ft.get("color"), sc.GOLD), 2)
            f = sc._f(sc.MONO, 22)
            lines = _wrap(str(ft.get("text", "")), f, R_W - 82, d)[:2]
            yy = ry + (6 if len(lines) > 1 else 18)
            for line in lines:
                d.text((R_X + 76, yy), line, font=f,
                       fill=(206, 206, 210, int(255 * min(1, a * 1.5))))
                yy += 30
            ry += 76

    if chart_block:
        k = E(3.6, 0.3)
        if k > 0:
            _ribbon(d, R_X, ry + 6, 360 * k,
                    chart_block.get("title", "динамика") if k > 0.75 else "")
        ry += 64
        ck = A(3.85, 1.5)
        if ck > 0:
            sc._ev(sfx, 3.85, "accent")
            _mini_chart(im, (R_X, ry, R_X + R_W, ry + 190),
                        chart_block.get("values", []), chart_block.get("labels", ()),
                        chart_block.get("unit", ""),
                        _c(chart_block.get("color"), sc.GOLD), draw_k=ck)
            d = ImageDraw.Draw(im, "RGBA")
        ry += 190 + 12
        if chart_block.get("note"):
            a, dx = sc._rv(t, 5.2)
            if a > 0:
                f = sc._f(sc.MONO, 21)
                for line in _wrap(chart_block["note"], f, R_W, d)[:2]:
                    im = sc._put(im, lambda dd, ry=ry, line=line: dd.text(
                        (R_X, ry), line, font=f, fill=(150, 150, 156, 255)), a, dx)
                    ry += 28
                d = ImageDraw.Draw(im, "RGBA")

    # ── нижняя лента: выезжает снизу
    band_y = BOT + 18
    bk = E(5.4, 0.5)
    if bk > 0:
        off = int((1 - bk) * (H - band_y))
        d.rectangle((0, band_y + off, W, H + off), fill=(24, 20, 14, 255))
        d.rectangle((0, band_y + off, W, band_y + 4 + off), fill=sc.GOLD + (255,))
        if bottom:
            f = sc._f(sc.F_HEAD, 34)
            sc.track(d, (L_X, band_y + 20 + off), bottom.upper(), f,
                     sc.GOLD + (255,), 3)
        if source:
            f = sc._f(sc.MONO, 20)
            d.text((L_X, band_y + 68 + off), source, font=f,
                   fill=(136, 136, 142, 255))
        if watermark:
            fw = sc._f(sc.F_HEAD, 21)
            wt = watermark.upper()
            wd_ = sc.track_w(wt, fw, 3)
            d.ellipse((W - 150 - wd_ - 16, band_y + 42 + off,
                       W - 150 - wd_ - 8, band_y + 50 + off), fill=(118, 29, 34, 255))
            sc.track(d, (W - 150 - wd_, band_y + 34 + off), wt, fw,
                     sc.GREY + (255,), 3)

    if out:
        im.save(out, quality=94)
    return im


def _wrap(text, font, max_w, d):
    words, rows, cur = str(text).split(" "), [], ""
    for wd in words:
        probe = (cur + " " + wd).strip()
        if font.getlength(probe) > max_w and cur:
            rows.append(cur)
            cur = wd
        else:
            cur = probe
    if cur:
        rows.append(cur)
    return rows


def _c(spec, default):
    if isinstance(spec, (list, tuple)) and len(spec) == 3:
        return tuple(int(v) for v in spec)
    if isinstance(spec, str):
        named = {"gold": sc.GOLD, "золотой": sc.GOLD, "red": sc.RED,
                 "красный": sc.RED, "white": sc.WHITE, "белый": sc.WHITE,
                 "grey": (132, 132, 138), "серый": (132, 132, 138)}
        if spec.lower() in named:
            return named[spec.lower()]
        h = spec.lstrip("#")
        if len(h) == 6:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return default


def _cli():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2]
    dur = float(cfg.pop("dur", 8.0))
    if out.lower().endswith((".png", ".jpg", ".jpeg")):
        poster(out, **cfg)
        print("ok ->", out)
        return
    poster(out.rsplit(".", 1)[0] + ".jpg", **cfg)
    sc.render_anim(poster, cfg, dur, out, sfx_out=False, anim_seconds=0.2)
    print("ok ->", out)


if __name__ == "__main__":
    _cli()
