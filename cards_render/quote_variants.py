# -*- coding: utf-8 -*-
"""НАБРОСКИ НОВЫХ ВИДОВ ЦИТАТ — на показ пользователю (22.10.2026).

Было два вида: мазок маркера по строке (`style_cards.quote_marker`) и
лоскут бумаги с подчёркиванием (`quote_paper.quote_paper`). Здесь:

  * тот же мазок и то же подчёркивание, но ОРАНЖЕВЫМ (его просьба);
  * шесть новых видов, каждый под свой повод.

НИЧЕГО БОЕВОГО НЕ ПРАВИТ: цвет маркера подменяется на время вызова,
`quote_paper.py` и `style_cards.py` остаются как есть (их тянет боевой
`template/quote_card.py`, правка там = раскатка на восемь целей).

Правила системы соблюдены: белый суть / золотой служебное / красный акцент,
левое поле 264, подвал и вотермарка у каждого кадра, никаких служебных
пометок в кадре, автор может отсутствовать.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.expanduser("~/.claude/skills/news-video/fullcycle"))
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import style_cards as sc
import quote_paper as qp

W, H = sc.W, sc.H

ORANGE = (240, 126, 26)        # маркер, который он просил попробовать
ORANGE_DIM = (196, 98, 20)
PAPER = (243, 240, 232)
INK = (26, 24, 22)
INK_SOFT = (98, 94, 88)



def _wrap_keep(text, font, max_w, phrase=None):
    """Перенос строк, который НЕ РВЁТ ключевую фразу.

    Гоча, стоившая вида «зачёркнутая цитата» на первой же пробе (22.10) и
    описанная в SKILL.md для боевой карточки: если `accent`/`struck` попал
    на стык строк, рисовалка просто не находит его в строке и молча не
    чертит ни маркер, ни зачёркивание. Здесь фраза склеивается в ОДИН
    токен, поэтому она либо целиком помещается в строку, либо целиком
    уезжает на следующую."""
    if phrase and phrase in text:
        head, tail = text.split(phrase, 1)
        toks = head.split(" ") + ["\x00" + phrase] + tail.split(" ")
        toks = [t for t in toks if t != ""]
    else:
        toks = text.split(" ")
    out, cur = [], ""
    for tok in toks:
        word = tok[1:] if tok.startswith("\x00") else tok
        probe = (cur + " " + word).strip()
        if font.getlength(probe) > max_w and cur:
            out.append(cur)
            cur = word
        else:
            cur = probe
    if cur:
        out.append(cur)
    return out

# ======================================================================
# 1-2. ТЕ ЖЕ ДВА ВИДА, НО МАРКЕР ОРАНЖЕВЫЙ
# ======================================================================
F_OSW = sc.F_ALT                                   # Oswald Bold — узкий акцидентный
F_MONT = os.path.join(sc.NV, "Montserrat-Bold.ttf")  # геометрический гротеск
F_SERIF = os.path.join(sc.NV, "Tinos-Bold.ttf")      # с засечками, газетный
F_HAND = "/mnt/c/Windows/Fonts/segoesc.ttf"          # рукописный (есть только на машине)
INK_PEN = (31, 42, 74)                               # синие чернила на бумаге


def _marker_paint(im, box, seed, grow=1.0, color=ORANGE, alpha=0.92):
    """Мазок маркера. Своя копия, потому что `style_cards._stroke` зовёт
    `random` и `math`, которых в том модуле нет (баг 22.10, отдан на починку)."""
    x0, y0, x1, y1 = box
    x1 = x0 + (x1 - x0) * max(0.0, min(1.0, grow))
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, math.tau) for _ in range(4)]
    hh = y1 - y0
    for x in range(int(x0), int(x1)):
        u = (x - x0) / max(1.0, (x1 - x0))
        top = y0 + hh * 0.07 * math.sin(u * math.tau * 2.3 + ph[0]) + hh * 0.04 * math.sin(u * math.tau * 7.1 + ph[1])
        bot = y1 + hh * 0.06 * math.sin(u * math.tau * 1.7 + ph[2]) + hh * 0.03 * math.sin(u * math.tau * 9.3 + ph[3])
        fade = 255 if u < 0.88 else int(255 * (1 - (u - 0.88) / 0.12) ** 0.6)
        d.line([(x, top), (x, bot)], fill=max(0, fade))
    m = m.filter(ImageFilter.GaussianBlur(1.6))
    paint = Image.new("RGB", (W, H), color)
    return Image.composite(paint, im, m.point(lambda v: int(v * alpha)))


# ======================================================================
# 1. МАЗОК · ГЕОМЕТРИЧЕСКИЙ ГРОТЕСК, ГИГАНТСКАЯ КАВЫЧКА В ФОНЕ
# ======================================================================
def marker_glyph(out=None, kick="", text="", author="", role="", source="",
                 watermark="ДИПЛОМАТИЯ СИЛЫ", accent=None, color=ORANGE,
                 t=None, sfx=None, speaker_idx=0):
    """Шрифт С ЗАСЕЧКАМИ (Tinos Bold) — газетный характер вместо гротеска,
    вместо пары красных шевронов ОДНА гигантская кавычка в фоне слева.
    Мазок оранжевый.

    Montserrat здесь не годится: файл назван `Montserrat-Bold.ttf`, а
    внутри начертание THIN (проверено 22.10 через `ImageFont.getname`),
    текст выходит серым и тонким. Тем же враньём грешат Oswald-Bold и
    RobotoCondensed-Bold — внутри Regular.""" 
    im = sc.canvas()
    col = sc.SPEAKER_COLORS[speaker_idx % len(sc.SPEAKER_COLORS)]
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((112, -120), "“", font=sc._f(F_SERIF, 560),
                             fill=(255, 255, 255, 32))
    im = Image.alpha_composite(im.convert("RGBA"), lay).convert("RGB")

    if kick:
        # кикер ниже кавычки-глифа: на 150 красная точка упиралась в неё
        a0, dx0 = sc._rv(t, 0.05)
        im = sc._put(im, lambda d: sc.kicker(d, 236, kick, dot=True, t=t), a0, dx0)

    f = sc._f(F_SERIF, 60)
    x = 392
    lines = _wrap_keep(text, f, 1180, accent)
    y = 348
    for i, ln in enumerate(lines):
        at = 0.18 + i * 0.16
        av, dxv = sc._rv(t, at)
        if av <= 0:
            y += 96
            continue
        sc._ev(sfx, at, "label" if i else "quote")
        if accent and accent in ln:
            k = ln.index(accent)
            pre, post = ln[:k], ln[k + len(accent):]
            xs = x + f.getlength(pre)
            grow = 1.0 if t is None else max(0.0, min(1.0, (t - at - 0.1) / 0.45))
            if grow > 0:
                bb = f.getbbox(accent)
                im = _marker_paint(im, (xs - 12, y + bb[1] - 8,
                                        xs + f.getlength(accent) + 14, y + bb[3] + 10),
                                   seed=i * 5 + 11, grow=grow, color=color)
            tcol = (22, 20, 16) if grow > 0.25 else sc.WHITE
            im = sc._put(im, lambda d, y=y, pre=pre, post=post, tcol=tcol: (
                d.text((x, y), pre, font=f, fill=sc.WHITE + (255,)),
                d.text((x + f.getlength(pre), y), accent, font=f, fill=tcol + (255,)),
                d.text((x + f.getlength(pre + accent), y), post, font=f,
                       fill=sc.WHITE + (255,))), av, dxv)
        else:
            im = sc._put(im, lambda d, y=y, ln=ln: d.text((x, y), ln, font=f,
                                                          fill=sc.WHITE + (255,)), av, dxv)
        y += 96

    if author:
        aa, dxa = sc._rv(t, 0.18 + len(lines) * 0.16 + 0.12)
        im = sc._put(im, lambda d, y=y: (
            d.text((x, y + 36), author, font=sc._f(F_SERIF, 34), fill=col + (255,)),
            role and d.text((x, y + 84), role, font=sc._f(sc.MONO, 23),
                            fill=sc.GREY + (255,))), aa, dxa)
    d = ImageDraw.Draw(im)
    sc.footer(d, source, watermark)
    if out:
        im.save(out, quality=94)
        return out
    return im


# ======================================================================
# 2А-2Б. ЛОСКУТ: ДРУГОЙ НАБОР, ДРУГИЕ КАВЫЧКИ, ДРУГОЕ ПОДЧЁРКИВАНИЕ
# ======================================================================
def _wave_underline(size, x0, x1, y, seed, grow=1.0, amp=7.0, thick=9):
    """Подчёркивание ВОЛНОЙ — как подчёркивают ручкой, а не маркером."""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    rnd = random.Random(seed)
    ph = rnd.uniform(0, math.tau)
    xe = x0 + (x1 - x0) * max(0.0, min(1.0, grow))
    pts, x = [], x0
    while x < xe:
        u = (x - x0) / max(1.0, x1 - x0)
        pts.append((x, y + amp * math.sin(u * math.tau * 4.2 + ph)))
        x += 5
    if len(pts) > 1:
        d.line(pts, fill=255, width=thick, joint="curve")
    return m.filter(ImageFilter.GaussianBlur(1.1))


def kwargs_quotes(quotes):
    """Пара кавычек: «ёлочки» для моноширинного (лапки там висят в своей
    ячейке и читаются как лишний пробел), иначе типографские лапки."""
    if quotes == "angle":
        return "«", "»"
    return "„", "“"


def paper_variant(out=None, kick="", title="", text="", author="", source="",
                  accent=None, watermark="ДИПЛОМАТИЯ СИЛЫ", color=ORANGE,
                  font_path=None, font_size=52, ink=None, quotes=True,
                  underline="wave", t=None, sfx=None, seed=23, tilt=-0.9):
    """Лоскут бумаги со СВОИМ набором: шрифт, кавычки-лапки и способ
    подчёркивания задаются снаружи. Высота лоскута считается по числу
    строк — у принятого вида она постоянная, и на короткой цитате
    половина бумаги пустая."""
    im = sc.canvas()
    font_path = font_path or sc.MONO
    ink = ink or INK
    if kick:
        a0, dx0 = sc._rv(t, 0.05)
        sc._ev(sfx, 0.05, "label")
        im = sc._put(im, lambda d: sc.kicker(d, 92, kick, dot=True, t=t), a0, dx0)
    if title:
        a1, dx1 = sc._rv(t, 0.14)
        im = sc._put(im, lambda d: sc.track(d, (sc.MARGIN_L - 120, 140), title.upper(),
                                            sc._f(sc.F_HEAD, 46), sc.WHITE + (255,), 2),
                     a1, dx1)

    f = sc._f(font_path, font_size)
    pad, step = 86, int(font_size * 1.36)
    pw = int(W * 0.76)
    qo, qc = kwargs_quotes(quotes)
    body = (qo + text + qc) if quotes else text
    lines = _wrap_keep(body, f, pw - 2 * pad, accent)
    ph_ = 92 + step * len(lines) + (96 if author else 56)
    x0, y0 = (W - pw) // 2, max(300, (H - ph_) // 2 - 20)
    box = (x0, y0, x0 + pw, y0 + ph_)

    ap, _ = sc._rv(t, 0.22)
    if ap <= 0:
        d = ImageDraw.Draw(im)
        sc.footer(d, source, watermark)
        return (im.save(out, quality=94) or out) if out else im
    sc._ev(sfx, 0.22, "accent")

    mask = qp._torn_rect((W, H), box, seed)
    paper = qp._paper_fill((W, H), seed)
    pd = ImageDraw.Draw(paper)

    ty, marks = y0 + 64, []
    for i, ln in enumerate(lines):
        at = 0.34 + i * 0.16
        av, _ = sc._rv(t, at)
        if av <= 0:
            ty += step
            continue
        sc._ev(sfx, at, "label")
        pd.text((x0 + pad, ty), ln, font=f, fill=ink)
        if accent and accent in ln:
            k = ln.index(accent)
            ax0 = x0 + pad + f.getlength(ln[:k])
            ax1 = ax0 + f.getlength(accent)
            grow = 1.0 if t is None else max(0.0, min(1.0, (t - at - 0.12) / 0.5))
            if grow > 0:
                marks.append((ax0 - 8, ax1 + 10, ty + font_size + 12, grow))
        ty += step

    if author:
        aa, _ = sc._rv(t, 0.34 + len(lines) * 0.16 + 0.1)
        if aa > 0:
            pd.text((x0 + pad, ty + 22), "— " + author, font=sc._f(sc.MONO, 24),
                    fill=INK_SOFT)

    for (mx0, mx1, my, grow) in marks:
        if underline == "wave":
            mm = _wave_underline((W, H), mx0, mx1, my, seed + 5, grow)
            al = 0.95
        else:
            mm = qp._marker_underline((W, H), mx0, mx1, my, seed + 5, grow)
            al = 0.88
        paint = Image.new("RGB", (W, H), color)
        paper = Image.composite(paint, paper, mm.point(lambda v: int(v * al)))

    if tilt:
        cen = (W // 2, y0 + ph_ // 2)
        paper = paper.rotate(tilt, resample=Image.BICUBIC, center=cen)
        mask = mask.rotate(tilt, resample=Image.BICUBIC, center=cen)

    sh = mask.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.72))
    sh = sh.transform((W, H), Image.AFFINE, (1, 0, -14, 0, 1, -16))
    base = np.asarray(im, np.float32) * (1 - 0.62 * (np.asarray(sh, np.float32) / 255.0)[..., None])
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    im = Image.composite(paper, im, mask)
    d = ImageDraw.Draw(im)
    sc.footer(d, source, watermark)
    if out:
        im.save(out, quality=94)
        return out
    return im


def paper_typed(out=None, **kw):
    """Лоскут · МАШИНОПИСЬ: моноширинный шрифт, кавычки-лапки, маркер
    ровной полосой. Читается как вырезка из распечатки."""
    kw.setdefault("font_path", sc.MONO)
    kw.setdefault("font_size", 44)
    kw.setdefault("underline", "straight")
    kw.setdefault("quotes", "angle")
    return paper_variant(out, **kw)


def paper_hand(out=None, **kw):
    """Лоскут · ОТ РУКИ: рукописный шрифт синими чернилами, подчёркивание
    волной. Шрифт системный (Segoe Script) — на машине есть, в облаке
    карточка всё равно рисуется локально, но зависимость стоит помнить."""
    kw.setdefault("font_path", F_HAND if os.path.exists(F_HAND) else F_SERIF)
    # у рукописных шрифтов сильно разная высота строчных: Segoe Script при 54
    # и Caveat при 54 — это два разных кегля на глаз (видно на облачном
    # прогоне 22.10), поэтому размер подбирается под шрифт, а не задан числом
    kw.setdefault("font_size", 68 if "caveat" in os.path.basename(kw["font_path"]).lower() else 54)
    kw.setdefault("ink", INK_PEN)
    kw.setdefault("underline", "wave")
    kw.setdefault("quotes", False)
    return paper_variant(out, **kw)


# ======================================================================
# 3. ЦИТАТА-СПЛИТ: портрет и слова, одна граница
# ======================================================================
def quote_split(out=None, photo="", text="", author="", role="", source="",
                watermark="ДИПЛОМАТИЯ СИЛЫ", accent=None, speaker_idx=0,
                t=None, sfx=None, side="left"):
    """Левая половина — тот, кто говорит; правая — что сказал.
    Одна красная граница на стыке (принятый приём «две половины»).
    Повод: именное заявление, когда лицо опознаётся и его стоит показать."""
    im = sc.canvas()
    half = 884
    col = sc.SPEAKER_COLORS[speaker_idx % len(sc.SPEAKER_COLORS)]

    if photo and os.path.exists(photo):
        ph = Image.open(photo).convert("RGB")
        k = max(half / ph.width, H / ph.height)
        ph = ph.resize((int(ph.width * k), int(ph.height * k)), Image.LANCZOS)
        # кроп по верхней трети — лицо обычно там
        ox = max(0, (ph.width - half) // 2)
        oy = max(0, int((ph.height - H) * 0.28))
        ph = ph.crop((ox, oy, ox + half, oy + H))
        x0 = 0 if side == "left" else W - half
        im.paste(ph, (x0, 0))
        # притемнение к стыку, чтобы текст не упирался в светлое
        g = np.asarray(im, np.float32)
        ramp = np.linspace(1.0, 0.42, 300)[None, :, None]
        if side == "left":
            g[:, half - 300:half] *= ramp
        else:
            g[:, x0:x0 + 300] *= ramp[:, ::-1]
        im = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8))

    bx = half + 72 if side == "left" else 96
    maxw = W - bx - 120
    d0 = ImageDraw.Draw(im)
    gx = half if side == "left" else W - half
    d0.rectangle((gx - 3, 0, gx + 3, H), fill=sc.RED)

    a0, dx0 = sc._rv(t, 0.06)
    sc._ev(sfx, 0.06, "quote")
    im = sc._put(im, lambda d: d.text((bx - 8, 168), "«", font=sc._f(sc.F_HEAD, 150),
                                      fill=sc.RED + (255,)), a0, dx0)

    f = sc._f(sc.F_HEAD, 58)
    lines = _wrap_keep(text, f, maxw, accent)
    y = 320
    for i, ln in enumerate(lines):
        at = 0.2 + i * 0.16
        av, dxv = sc._rv(t, at)
        if av <= 0:
            y += 78
            continue
        sc._ev(sfx, at, "label")
        if accent and accent in ln:
            k = ln.index(accent)
            pre, post = ln[:k], ln[k + len(accent):]
            im = sc._put(im, lambda d, y=y, pre=pre, post=post:
                         (d.text((bx, y), pre, font=f, fill=sc.WHITE + (255,)),
                          d.text((bx + f.getlength(pre), y), accent, font=f, fill=ORANGE + (255,)),
                          d.text((bx + f.getlength(pre + accent), y), post, font=f,
                                 fill=sc.WHITE + (255,))), av, dxv)
        else:
            im = sc._put(im, lambda d, y=y, ln=ln: d.text((bx, y), ln, font=f,
                                                          fill=sc.WHITE + (255,)), av, dxv)
        y += 78

    if author:
        aa, dxa = sc._rv(t, 0.2 + len(lines) * 0.16 + 0.1)
        im = sc._put(im, lambda d, y=y: (
            d.rectangle((bx, y + 40, bx + 8, y + 96), fill=col + (255,)),
            d.text((bx + 26, y + 36), author.upper(), font=sc._f(sc.F_ALT, 40),
                   fill=col + (255,)),
            role and d.text((bx + 26, y + 88), role, font=sc._f(sc.MONO, 24),
                            fill=sc.GREY + (255,))), aa, dxa)

    d = ImageDraw.Draw(im)
    # подвал на половине с фото нечитаем (22.10: источник лёг на лицо) —
    # источник ставим в текстовую половину, вотермарку оставляем на месте
    sc.footer(d, "", watermark)
    if source:
        d.text((bx, sc.FOOT_Y), source, font=sc._f(sc.MONO, 21), fill=sc.GREY_DIM)
    if out:
        im.save(out, quality=94)
        return out
    return im


# ======================================================================
# 4. ЦИТАТА-ЛЕНТА: полоса через кадр, как сводка с телетайпа
# ======================================================================
def _perforation(d, x0, x1, y, step=54, r=9, col=(206, 202, 192)):
    x = x0 + step
    while x < x1 - step:
        d.ellipse((x - r, y - r, x + r, y + r), fill=col)
        x += step


def quote_tape(out=None, kick="", text="", author="", source="", accent=None,
               watermark="ДИПЛОМАТИЯ СИЛЫ", t=None, sfx=None, tilt=-1.8, seed=11):
    """Светлая лента поперёк кадра, текст моноширинным, ключевая фраза
    подчёркнута оранжевым. Повод: короткая официальная формулировка,
    сводка, строка из коммюнике — то, что «пришло по каналу».

    Полотно шире кадра с запасом 300 px по бокам и 100 сверху/снизу:
    после поворота углы иначе обрезаются и по краям кадра видна ступенька
    (поймано на первой пробе 22.10)."""
    im = sc.canvas()
    a0, dx0 = sc._rv(t, 0.05)
    if a0 > 0:
        sc._ev(sfx, 0.05, "label")
        im = sc._put(im, lambda d: sc.kicker(d, 150, kick, dot=True, t=t), a0, dx0)

    th = 330
    y0 = (H - th) // 2 + 20
    PADX, PADY = 300, 110
    LW, LH = W + 2 * PADX, th + 2 * PADY

    rng = np.random.default_rng(seed)
    arr = np.zeros((LH, LW, 3), np.float32)
    arr[:] = np.array(PAPER, np.float32)
    arr[:PADY] = 0
    arr[PADY + th:] = 0
    arr[PADY:PADY + th] += rng.normal(0, 3.0, (th, LW, 1))
    lay = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    ld = ImageDraw.Draw(lay)
    _perforation(ld, 0, LW, PADY + 26)
    _perforation(ld, 0, LW, PADY + th - 26)
    ld.line([(0, PADY + 54), (LW, PADY + 54)], fill=(214, 210, 200), width=2)
    ld.line([(0, PADY + th - 54), (LW, PADY + th - 54)], fill=(214, 210, 200), width=2)
    # маска самой ленты — ею же режем тень, чтобы она шла ровно по бумаге
    mk = Image.new("L", (LW, LH), 0)
    ImageDraw.Draw(mk).rectangle((0, PADY, LW, PADY + th), fill=255)

    f = sc._f(sc.MONO_B, 44)
    lines = _wrap_keep(text, f, W - 320, accent)[:2]
    ty = PADY + (92 if len(lines) > 1 else 128)
    marks = []
    for i, ln in enumerate(lines):
        at = 0.26 + i * 0.2
        av, _ = sc._rv(t, at)
        if av <= 0:
            continue
        sc._ev(sfx, at, "label")
        lx = PADX + (W - f.getlength(ln)) / 2
        ld.text((lx, ty), ln, font=f, fill=INK)
        if accent and accent in ln:
            k = ln.index(accent)
            ax0 = lx + f.getlength(ln[:k])
            ax1 = ax0 + f.getlength(accent)
            grow = 1.0 if t is None else max(0.0, min(1.0, (t - at - 0.1) / 0.45))
            if grow > 0:
                marks.append((ax0 - 6, ax1 + 8, ty + 56, grow))
        ty += 72

    for (mx0, mx1, my, grow) in marks:
        mm = qp._marker_underline((LW, LH), mx0, mx1, my, seed + 3, grow, thick=15)
        paint = Image.new("RGB", (LW, LH), ORANGE)
        lay = Image.composite(paint, lay, mm.point(lambda v: int(v * 0.9)))

    ap, _ = sc._rv(t, 0.16)
    if ap > 0:
        cen = (LW // 2, LH // 2)
        lay = lay.rotate(tilt, resample=Image.BICUBIC, center=cen)
        mk = mk.rotate(tilt, resample=Image.BICUBIC, center=cen)
        # тень под лентой
        sh = Image.new("L", (W, H), 0)
        sh.paste(mk.crop((PADX, PADY - 60, PADX + W, PADY - 60 + th + 120)),
                 (0, y0 - 60 + 16))
        sh = sh.filter(ImageFilter.GaussianBlur(20))
        base = np.asarray(im, np.float32) * (1 - 0.55 * (np.asarray(sh, np.float32) / 255.0)[..., None])
        im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))

        box = (PADX, PADY - 60, PADX + W, PADY - 60 + th + 120)
        strip = lay.crop(box)
        smask = mk.crop(box)
        if ap < 1:
            smask = smask.point(lambda v: int(v * ap))
        im.paste(strip, (0, y0 - 60), smask)

    if author:
        aa, dxa = sc._rv(t, 0.26 + len(lines) * 0.2 + 0.14)
        im = sc._put(im, lambda d: d.text((sc.MARGIN_L, y0 + th + 54), "— " + author,
                                          font=sc._f(sc.MONO, 28), fill=sc.GOLD + (255,)),
                     aa, dxa)
    d = ImageDraw.Draw(im)
    sc.footer(d, source, watermark)
    if out:
        im.save(out, quality=94)
        return out
    return im


# ======================================================================
# 5. ЦИТАТА-ДОКУМЕНТ: машинописный лист, фраза обведена от руки
# ======================================================================
def _hand_ellipse(d, box, col, seed=5, width=5, grow=1.0, laps=2):
    """Овал, обведённый от руки: дрожащий радиус, два прохода, разомкнут."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, math.tau) for _ in range(4)]
    total = math.tau * laps * max(0.0, min(1.0, grow))
    pts, a = [], -0.6
    while a < total - 0.6:
        w1 = 1 + 0.035 * math.sin(a * 3.1 + ph[0]) + 0.02 * math.sin(a * 7.7 + ph[1])
        w2 = 1 + 0.045 * math.sin(a * 2.3 + ph[2]) + 0.02 * math.sin(a * 6.1 + ph[3])
        pts.append((cx + rx * w1 * math.cos(a), cy + ry * w2 * math.sin(a)))
        a += 0.06
    if len(pts) > 2:
        d.line(pts, fill=col, width=width, joint="curve")


def quote_doc(out=None, kick="", title="", text="", mark=None, stamp="",
              author="", source="", watermark="ДИПЛОМАТИЯ СИЛЫ",
              t=None, sfx=None, seed=9):
    """Машинописная страница: текст моноширинным, нужная строка обведена
    от руки оранжевым, сбоку штамп. Повод: документ, стенограмма,
    протокол, пункт соглашения — то, что существует на бумаге."""
    im = sc.canvas()
    a0, dx0 = sc._rv(t, 0.05)
    if a0 > 0:
        sc._ev(sfx, 0.05, "label")
        im = sc._put(im, lambda d: sc.kicker(d, 96, kick, dot=True, t=t), a0, dx0)

    pw, ph_ = 1180, 760
    x0, y0 = (W - pw) // 2 + 60, 206
    ap, _ = sc._rv(t, 0.18)
    if ap <= 0:
        d = ImageDraw.Draw(im)
        sc.footer(d, source, watermark)
        return im.save(out, quality=94) or out if out else im
    sc._ev(sfx, 0.18, "card")

    rng = np.random.default_rng(seed)
    page = np.zeros((ph_, pw, 3), np.float32)
    page[:] = np.array(PAPER, np.float32)
    page += rng.normal(0, 3.2, (ph_, pw, 1))
    yy = np.linspace(-1, 1, ph_)[:, None, None]
    page -= 7.0 * np.abs(yy) ** 2
    pg = Image.fromarray(np.clip(page, 0, 255).astype(np.uint8))
    pd = ImageDraw.Draw(pg)

    # шапка документа и линия
    if title:
        pd.text((84, 66), title.upper(), font=sc._f(sc.MONO_B, 30), fill=INK)
    pd.line([(84, 122), (pw - 84, 122)], fill=(188, 184, 174), width=2)
    # дырки под скрепку на левом поле
    for ky in (210, 420):
        pd.ellipse((34, ky, 60, ky + 26), fill=(214, 210, 200))

    f = sc._f(sc.MONO, 34)
    lines = _wrap_keep(text, f, pw - 200, mark)
    ty, box = 180, None
    for i, ln in enumerate(lines):
        at = 0.3 + i * 0.13
        av, _ = sc._rv(t, at)
        if av <= 0:
            ty += 58
            continue
        pd.text((100, ty), ln, font=f, fill=INK)
        if mark and mark in ln:
            k = ln.index(mark)
            mx0 = 100 + f.getlength(ln[:k])
            box = (mx0 - 26, ty - 16, mx0 + f.getlength(mark) + 26, ty + 56)
            box_at = at
        ty += 58

    if author:
        pd.text((100, ty + 34), "— " + author, font=sc._f(sc.MONO, 26), fill=INK_SOFT)

    if box:
        grow = 1.0 if t is None else max(0.0, min(1.0, (t - box_at - 0.15) / 0.6))
        _hand_ellipse(pd, box, ORANGE_DIM, seed=seed + 2, width=5, grow=grow)

    if stamp:
        st = Image.new("RGBA", (470, 150), (0, 0, 0, 0))
        sd = ImageDraw.Draw(st)
        sd.rounded_rectangle((4, 4, 466, 146), radius=10, outline=sc.RED + (205,), width=6)
        sc.track(sd, (40, 48), stamp.upper(), sc._f(sc.F_HEAD, 46), sc.RED + (215,), 4)
        st = st.rotate(-7, resample=Image.BICUBIC, expand=True)
        sa, _ = sc._rv(t, 0.3 + len(lines) * 0.13 + 0.2)
        if sa > 0:
            if sa < 1:
                st.putalpha(st.split()[3].point(lambda v: int(v * sa)))
            pg.paste(st, (pw - 560, ph_ - 250), st)

    # тень листа
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).rectangle((x0 + 16, y0 + 18, x0 + pw + 16, y0 + ph_ + 18), fill=210)
    sh = sh.filter(ImageFilter.GaussianBlur(22))
    base = np.asarray(im, np.float32) * (1 - 0.6 * (np.asarray(sh, np.float32) / 255.0)[..., None])
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    im.paste(pg, (x0, y0))

    d = ImageDraw.Draw(im)
    sc.footer(d, source, watermark)
    if out:
        im.save(out, quality=94)
        return out
    return im


# ======================================================================
# 6. ЦИТАТА С ЗАЧЁРКИВАНИЕМ: что обещали и что оказалось
# ======================================================================
def _hand_strike(size, x0, x1, y, seed=3, grow=1.0, width=7):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, math.tau) for _ in range(3)]
    xe = x0 + (x1 - x0) * max(0.0, min(1.0, grow))
    pts = []
    x = x0
    while x < xe:
        u = (x - x0) / max(1.0, x1 - x0)
        dy = 7 * math.sin(u * math.tau * 1.1 + ph[0]) + 3 * math.sin(u * math.tau * 3.7 + ph[1])
        pts.append((x, y + dy))
        x += 8
    if len(pts) > 1:
        d.line(pts, fill=255, width=width, joint="curve")
    return m.filter(ImageFilter.GaussianBlur(1.1))


def quote_strike(out=None, kick="", text="", struck=None, fix="", author="",
                 source="", watermark="ДИПЛОМАТИЯ СИЛЫ", t=None, sfx=None):
    """Цитата, часть которой зачёркнута от руки, а над зачёркнутым —
    поправка оранжевым. Повод: разбор обещания, которое не выполнено,
    или формулировки, которую сменили. Самый «разборный» вид."""
    im = sc.canvas()
    a0, dx0 = sc._rv(t, 0.05)
    if a0 > 0:
        im = sc._put(im, lambda d: sc.kicker(d, 150, kick, dot=True, t=t), a0, dx0)
    aq, dxq = sc._rv(t, 0.1)
    sc._ev(sfx, 0.1, "quote")
    im = sc._put(im, lambda d: d.text((sc.MARGIN_L - 26, 262), "««",
                                      font=sc._f(sc.F_HEAD, 128), fill=sc.RED + (255,)),
                 aq, dxq)

    f = sc._f(sc.F_HEAD, 66)
    lines = _wrap_keep(text, f, 1340, struck)
    y, hit = 400, None
    for i, ln in enumerate(lines):
        at = 0.24 + i * 0.16
        av, dxv = sc._rv(t, at)
        if av <= 0:
            y += 88
            continue
        sc._ev(sfx, at, "label")
        im = sc._put(im, lambda d, y=y, ln=ln: d.text((sc.MARGIN_L, y), ln, font=f,
                                                      fill=sc.WHITE + (255,)), av, dxv)
        if struck and struck in ln:
            k = ln.index(struck)
            sx0 = sc.MARGIN_L + f.getlength(ln[:k])
            hit = (sx0, sx0 + f.getlength(struck), y + 44, at)
        y += 88

    if hit:
        sx0, sx1, sy, at = hit
        grow = 1.0 if t is None else max(0.0, min(1.0, (t - at - 0.25) / 0.5))
        if grow > 0:
            mm = _hand_strike((W, H), sx0 - 10, sx1 + 10, sy, grow=grow)
            paint = Image.new("RGB", (W, H), sc.RED)
            im = Image.composite(paint, im, mm)
        if fix:
            # поправку ставим ПОД зачёркнутым, а не над: сверху идёт
            # предыдущая строка цитаты и надпись легла прямо на неё
            # (поймано на первой пробе 22.10)
            fa, fdx = sc._rv(t, at + 0.75)
            ff = sc._f(sc.F_HEAD, 40)
            im = sc._put(im, lambda d: (
                d.line([(sx0 + 18, sy + 24), (sx0 + 18, sy + 62)], fill=ORANGE + (255,), width=4),
                d.polygon([(sx0 + 18, sy + 10), (sx0 + 8, sy + 30), (sx0 + 28, sy + 30)],
                          fill=ORANGE + (255,)),
                d.text((sx0 + 44, sy + 44), fix, font=ff, fill=ORANGE + (255,))),
                fa, fdx)
            y += 54

    if author:
        aa, dxa = sc._rv(t, 0.24 + len(lines) * 0.16 + 0.2)
        im = sc._put(im, lambda d, y=y: d.text((sc.MARGIN_L, y + 74), "— " + author,
                                               font=sc._f(sc.MONO, 30), fill=sc.GOLD + (255,)),
                     aa, dxa)
    d = ImageDraw.Draw(im)
    sc.footer(d, source, watermark)
    if out:
        im.save(out, quality=94)
        return out
    return im


# ======================================================================
# 7. ДВЕ ПОЗИЦИИ: кто что говорит об одном
# ======================================================================
def quote_duel(out=None, kick="", title="", top=None, bottom=None, source="",
               watermark="ДИПЛОМАТИЯ СИЛЫ", t=None, sfx=None):
    """Две цитаты встречно, через красную черту: верх и низ — разные
    говорящие, каждый своим закреплённым цветом. Повод: расхождение
    позиций, спор, «одно событие — два объяснения»."""
    im = sc.canvas()
    a0, dx0 = sc._rv(t, 0.05)
    if a0 > 0:
        im = sc._put(im, lambda d: sc.kicker(d, 84, kick, dot=True, t=t), a0, dx0)
    if title:
        a1, dx1 = sc._rv(t, 0.12)
        im = sc._put(im, lambda d: sc.track(d, (sc.MARGIN_L, 150), title.upper(),
                                            sc._f(sc.F_HEAD, 44), sc.WHITE + (255,), 2),
                     a1, dx1)

    f = sc._f(sc.F_HEAD, 52)
    blocks = [(top or {}, 330, 0.22, 0), (bottom or {}, 712, 0.5, 1)]
    for blk, by, at0, idx in blocks:
        txt = blk.get("text", "")
        if not txt:
            continue
        col = sc.SPEAKER_COLORS[blk.get("speaker_idx", idx) % len(sc.SPEAKER_COLORS)]
        lines = _wrap_keep(txt, f, 1300, blk.get("accent"))
        ab, dxb = sc._rv(t, at0)
        sc._ev(sfx, at0, "quote")
        im = sc._put(im, lambda d, by=by, col=col: (
            d.rectangle((sc.MARK_X, by + 10, sc.MARK_X + 10, by + 10 + 62 * 1), fill=col + (255,)),
            d.text((sc.MARGIN_L, by - 58), (blk.get("who", "") or "").upper(),
                   font=sc._f(sc.F_ALT, 36), fill=col + (255,))), ab, dxb)
        y = by
        for i, ln in enumerate(lines):
            at = at0 + 0.1 + i * 0.14
            av, dxv = sc._rv(t, at)
            if av <= 0:
                y += 70
                continue
            acc = blk.get("accent")
            if acc and acc in ln:
                k = ln.index(acc)
                pre, post = ln[:k], ln[k + len(acc):]
                im = sc._put(im, lambda d, y=y, pre=pre, post=post, acc=acc: (
                    d.text((sc.MARGIN_L, y), pre, font=f, fill=sc.WHITE + (255,)),
                    d.text((sc.MARGIN_L + f.getlength(pre), y), acc, font=f, fill=ORANGE + (255,)),
                    d.text((sc.MARGIN_L + f.getlength(pre + acc), y), post, font=f,
                           fill=sc.WHITE + (255,))), av, dxv)
            else:
                im = sc._put(im, lambda d, y=y, ln=ln: d.text((sc.MARGIN_L, y), ln, font=f,
                                                              fill=sc.WHITE + (255,)), av, dxv)
            y += 70
        if blk.get("source"):
            asrc, dxs = sc._rv(t, at0 + 0.1 + len(lines) * 0.14 + 0.08)
            im = sc._put(im, lambda d, y=y: d.text((sc.MARGIN_L, y + 10), blk["source"],
                                                   font=sc._f(sc.MONO, 24), fill=sc.GREY + (255,)),
                         asrc, dxs)

    ad, _ = sc._rv(t, 0.44)
    if ad > 0:
        d = ImageDraw.Draw(im)
        xe = int(sc.MARK_X + (1560 - sc.MARK_X) * min(1.0, ad))
        d.line([(sc.MARK_X, 614), (xe, 614)], fill=sc.RED, width=3)
        d.polygon([(880, 602), (898, 614), (880, 626), (862, 614)], fill=sc.RED)
    d = ImageDraw.Draw(im)
    sc.footer(d, source, watermark)
    if out:
        im.save(out, quality=94)
        return out
    return im


# ======================================================================
# 8. ВРЕЗ: спокойный газетный вариант, без маркера
# ======================================================================
def quote_pull(out=None, kick="", text="", author="", role="", source="",
               watermark="ДИПЛОМАТИЯ СИЛЫ", accent=None, speaker_idx=0,
               t=None, sfx=None):
    """Крупная кавычка-глиф в фоне, красная черта слева, текст большим
    кеглем, имя на плашке. Без маркера и без бумаги — самый спокойный
    вид, годится, когда карточки идут часто и пестрить нельзя."""
    im = sc.canvas()
    col = sc.SPEAKER_COLORS[speaker_idx % len(sc.SPEAKER_COLORS)]
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((1180, 60), "“", font=sc._f(sc.F_HEAD, 760),
                             fill=(255, 255, 255, 20))
    im = Image.alpha_composite(im.convert("RGBA"), lay).convert("RGB")

    a0, dx0 = sc._rv(t, 0.05)
    if a0 > 0 and kick:
        im = sc._put(im, lambda d: sc.kicker(d, 236, kick, dot=True, t=t), a0, dx0)

    f = sc._f(sc.F_HEAD, 78)
    lines = _wrap_keep(text, f, 1290, accent)
    y0 = 330
    y = y0
    for i, ln in enumerate(lines):
        at = 0.18 + i * 0.17
        av, dxv = sc._rv(t, at)
        if av <= 0:
            y += 100
            continue
        sc._ev(sfx, at, "label" if i else "quote")
        if accent and accent in ln:
            k = ln.index(accent)
            pre, post = ln[:k], ln[k + len(accent):]
            im = sc._put(im, lambda d, y=y, pre=pre, post=post: (
                d.text((sc.MARGIN_L, y), pre, font=f, fill=sc.WHITE + (255,)),
                d.text((sc.MARGIN_L + f.getlength(pre), y), accent, font=f, fill=sc.GOLD + (255,)),
                d.text((sc.MARGIN_L + f.getlength(pre + accent), y), post, font=f,
                       fill=sc.WHITE + (255,))), av, dxv)
        else:
            im = sc._put(im, lambda d, y=y, ln=ln: d.text((sc.MARGIN_L, y), ln, font=f,
                                                          fill=sc.WHITE + (255,)), av, dxv)
        y += 100

    ab, _ = sc._rv(t, 0.14)
    if ab > 0:
        d = ImageDraw.Draw(im)
        ye = int(y0 + (y - 24 - y0) * min(1.0, ab))
        d.rectangle((sc.MARK_X, y0 + 14, sc.MARK_X + 9, ye), fill=sc.RED)

    if author:
        aa, dxa = sc._rv(t, 0.18 + len(lines) * 0.17 + 0.12)
        im = sc._put(im, lambda d, y=y: (
            d.rectangle((sc.MARGIN_L, y + 44, sc.MARGIN_L + 8, y + 104), fill=col + (255,)),
            d.text((sc.MARGIN_L + 26, y + 40), author.upper(), font=sc._f(sc.F_ALT, 42),
                   fill=col + (255,)),
            role and d.text((sc.MARGIN_L + 26, y + 96), role, font=sc._f(sc.MONO, 24),
                            fill=sc.GREY + (255,))), aa, dxa)

    d = ImageDraw.Draw(im)
    sc.footer(d, source, watermark)
    if out:
        im.save(out, quality=94)
        return out
    return im
