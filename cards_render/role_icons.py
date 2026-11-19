#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РОЛЕВЫЕ ИКОНКИ — рисованный довесок по роли персонажа, в бою с 18.11.2026.

Принято из прототипа P7 (`skills/prototypes/proto/role-icons/`) его прямым
словом 18.11: «так, окей, это надо зафиксировать. И на завтра раскатать при
сборке, чтобы было на обоих каналах». Отбор стиля и ролей — тоже его слово
того же дня, по номерам на листе сравнения:

  ОСТАВЛЕНО (KEPT), отбор «оставляем 1, 2, 4, 8, 13, 17, 14. Все»:
    1  чиновник  · контровой силуэт     2  чиновник  · предмет-эмблема (портфель)
    4  военный   · контровой силуэт     8  оратор    · предмет-эмблема (микрофон)
    13 оператор  · контровой силуэт     14 оператор  · предмет-эмблема (гарнитура)
    17 айтишник  · предмет-эмблема (ноутбук)

  ЖЕНСКИЕ (вторая попытка, «по типу 1 и 13», первая — чадра, отклонена):
    22 чиновница · каре       23 чиновница · пучок
    24 оператор-ж · каре      25 оператор-ж · пучок

Два стиля-направления, третий («гравюра») в бой не взят:
  kontrovoy — контровой силуэт (язык принятой сцены N46 «трибуна-силуэт»,
              уменьшенный до иконки): свет из-за спины, ободок по краю, пыль.
  predmet   — предмет-эмблема без фигуры: один крупный предмет в кольце.

Цвет — ТОЛЬКО из `palitra.py` (фон, акцент канала); своей гаммы нет, поэтому
смена канала не требует правки ни одной строки здесь.

РАЗМЕЩЕНИЕ В ЗАЛЕ — отдельно, в `sceny_kodom.py` (функция `_рол_икон` там):
иконка ставится ТЕМ ЖЕ `билборд()`, что и таблички/вехи зала, стоит на полу
В МИРОВЫХ координатах и едет вместе с заездом камеры — не наклейка поверх
экрана. Разбор, почему так и не иначе — его слово 18.11, записано в
`memory/feedback_role_icons_taste.md` и `registry.json` прототипа.
"""
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import palitra  # noqa: E402

SS = 3
CELL = 300
K = SS
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "RobotoCondensed-Bold.ttf")

# номер → (направление, роль) — та же нумерация, по которой он отбирал на листе
NUMER = {
    1: ("kontrovoy", "chinovnik"), 2: ("predmet", "chinovnik"),
    4: ("kontrovoy", "voennyi"),
    8: ("predmet", "orator"),
    13: ("kontrovoy", "operator"), 14: ("predmet", "operator"),
    17: ("predmet", "aytishnik"),
    22: ("kontrovoy", "chinovnica_kare"), 23: ("kontrovoy", "chinovnica_puchok"),
    24: ("kontrovoy", "operatorka_kare"), 25: ("kontrovoy", "operatorka_puchok"),
}


def _f(size):
    return ImageFont.truetype(FONT, size)


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def chaikin(pts, it=3):
    for _ in range(it):
        out = []
        n = len(pts)
        for i in range(n):
            p, q = pts[i], pts[(i + 1) % n]
            out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        pts = out
    return pts


def S(pts, off=(0, 0)):
    return [((x + off[0]) * K, (y + off[1]) * K) for x, y in pts]


def B(box, off=(0, 0)):
    return (((box[0] + off[0]) * K), ((box[1] + off[1]) * K),
            ((box[2] + off[0]) * K), ((box[3] + off[1]) * K))


HEAD = (116, 48, 184, 128)
HOOD = (98, 30, 202, 156)
FACE = (122, 62, 178, 134)

FEMALE = ("chinovnica_kare", "chinovnica_puchok", "operatorka_kare", "operatorka_puchok")
HEAD_F = (121, 52, 179, 128)
BOB = chaikin([(150, 40), (180, 47), (193, 72), (196, 104), (195, 130), (182, 137),
               (118, 137), (105, 130), (104, 104), (107, 72), (120, 47)], 3)
BUN = (135, 24, 165, 54)
FACE_LIT = (126, 58, 174, 128)


def body_pts(role):
    if role in FEMALE:
        sh = 208
        right = [(160, 124), (161, 152), (178, 158), (196, 166), (sh, 178),
                 (sh + 6, 206), (sh + 8, 330)]
    else:
        sh = 238 if role == "ohrannik" else 228
        right = [(163, 122), (167, 140), (192, 147), (214, 156), (sh, 170),
                 (sh + 8, 196), (sh + 12, 330)]
    left = [(300 - x, y) for x, y in reversed(right)]
    return chaikin(right + left, 3)


def arm_pts():
    return [(224, 168), (250, 122), (262, 92)]


LECT = [(98, 214), (202, 214), (210, 330), (90, 330)]
LECT_TOP = (92, 206, 208, 218)
CASE = (212, 212, 268, 256)
SCREEN = [(96, 226), (204, 226), (196, 172), (104, 172)]


def draw_kontrovoy(img, role, pal):
    ink, mid, acc = pal
    F = lerp(ink, (0, 0, 0), 0.35)
    D1 = lerp(F, (255, 255, 255), 0.09)
    D2 = lerp(F, (255, 255, 255), 0.17)
    AD = lerp(acc, F, 0.45)

    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse(B((30, 0, 270, 240)), fill=acc + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=34 * K))
    img.alpha_composite(glow)
    glow2 = Image.new("RGBA", img.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(glow2)
    g.ellipse(B((92, 24, 208, 150)), fill=acc + (120,))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(radius=16 * K))
    img.alpha_composite(glow2)

    dust = Image.new("RGBA", img.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(dust)
    rnd = random.Random(7 + len(role))
    for _ in range(70):
        x = rnd.uniform(130, 296)
        y = rnd.uniform(4, 220)
        if (x - 150) * 0.9 + 40 < y:
            continue
        r = rnd.uniform(0.7, 2.1)
        a = rnd.randint(60, 190)
        g.ellipse(B((x - r, y - r, x + r, y + r)), fill=acc + (a,))
    dust = dust.filter(ImageFilter.GaussianBlur(radius=0.8 * K))
    img.alpha_composite(dust)

    d = ImageDraw.Draw(img)
    OFF = (-2.6, 2.6)

    def rim_poly(pts, fill):
        d.polygon(S(pts), fill=acc)
        d.polygon(S(pts, OFF), fill=fill)

    def rim_ell(box, fill):
        d.ellipse(B(box), fill=acc)
        d.ellipse(B(box, OFF), fill=fill)

    def rim_rrect(box, r, fill):
        d.rounded_rectangle(B(box), radius=r * K, fill=acc)
        d.rounded_rectangle(B(box, OFF), radius=r * K, fill=fill)

    def rim_line(pts, w, fill):
        d.line(S(pts), fill=acc, width=int(w * K), joint="curve")
        d.line(S(pts, OFF), fill=fill, width=int(w * K), joint="curve")

    body = body_pts(role)
    if role == "aytishnik":
        rim_poly(body, F)
        rim_ell(HOOD, F)
        face = Image.new("RGBA", img.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(face)
        fd.ellipse(B(FACE), fill=D1 + (255,))
        lit = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(lit)
        ld.ellipse(B((108, 96, 192, 170)), fill=acc + (150,))
        lit = lit.filter(ImageFilter.GaussianBlur(radius=10 * K))
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).ellipse(B(FACE), fill=255)
        import numpy as np
        lit.putalpha(Image.fromarray(
            (np.asarray(lit.split()[3], dtype=np.float32) * np.asarray(m, dtype=np.float32) / 255).astype(np.uint8)))
        img.alpha_composite(face)
        img.alpha_composite(lit)
        d = ImageDraw.Draw(img)
        halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        hd.polygon(S([(88, 232), (212, 232), (204, 164), (96, 164)]), fill=acc + (170,))
        halo = halo.filter(ImageFilter.GaussianBlur(radius=7 * K))
        img.alpha_composite(halo)
        d = ImageDraw.Draw(img)
        d.polygon(S(SCREEN), fill=D1)
        d.rectangle(B((84, 226, 216, 236)), fill=D2)
        return

    if role in FEMALE:
        rim_poly(body, F)
        d.rectangle(B((139, 118, 161, 156)), fill=F)
        d.line(S([(161, 120), (161, 154)]), fill=acc, width=int(2 * K))
        if role.endswith("_kare"):
            rim_poly(BOB, F)
            d.ellipse(B(FACE_LIT), fill=lerp(F, (255, 255, 255), 0.07))
        else:
            rim_ell(HEAD_F, F)
            rim_ell(BUN, F)
            d.ellipse(B((116, 104, 122, 110)), fill=acc)
            d.ellipse(B((178, 104, 184, 110)), fill=acc)
        d.polygon(S([(138, 156), (162, 156), (150, 208)]), fill=D2)
        d.line(S([(126, 160), (150, 208)]), fill=D1, width=int(2 * K))
        d.line(S([(174, 160), (150, 208)]), fill=D1, width=int(2 * K))
        if role.startswith("chinovnica"):
            d.arc(B((138, 150, 162, 174)), 10, 170, fill=acc, width=int(1.4 * K))
            rim_rrect((212, 212, 262, 250), 5, F)
            d.arc(B((226, 201, 248, 220)), 180, 360, fill=acc, width=int(2.2 * K))
            d.line(S([(214, 230), (260, 230)]), fill=D1, width=int(1.2 * K))
        else:
            top = 24 if role.endswith("_kare") else 14
            d.arc(B((106, top, 194, 128)), 180, 360, fill=AD, width=int(8 * K))
            d.arc(B((106, top, 194, 128)), 190, 350, fill=acc, width=int(2 * K))
            d.rounded_rectangle(B((102, 84, 118, 116)), radius=5 * K, fill=D2)
            d.rounded_rectangle(B((182, 84, 198, 116)), radius=5 * K, fill=D2)
            d.line(S([(194, 114), (188, 126), (166, 130)]), fill=AD, width=int(3.4 * K), joint="curve")
            d.ellipse(B((152, 122, 167, 137)), fill=acc)
        return

    rim_poly(body, F)
    rim_ell(HEAD, F)

    if role == "chinovnik":
        d.polygon(S([(136, 140), (164, 140), (150, 198)]), fill=D2)
        d.line(S([(123, 142), (150, 198)]), fill=D1, width=int(2 * K))
        d.line(S([(177, 142), (150, 198)]), fill=D1, width=int(2 * K))
        d.polygon(S([(150, 144), (144, 151), (149, 202), (151, 202), (156, 151)]), fill=AD)
        rim_rrect(CASE, 5, F)
        d.arc(B((226, 200, 254, 222)), 180, 360, fill=acc, width=int(2.4 * K))
        d.line(S([(214, 232), (266, 232)]), fill=D1, width=int(1.2 * K))

    elif role == "voennyi":
        rim_ell((104, 50, 196, 88), F)
        d.rectangle(B((108, 78, 192, 97)), fill=D1)
        d.pieslice(B((108, 86, 192, 112)), 0, 180, fill=F)
        d.line(S([(110, 97), (190, 97)]), fill=AD, width=int(1.4 * K))
        d.ellipse(B((143, 64, 157, 78)), fill=acc)
        d.ellipse(B((146, 67, 152, 73)), fill=lerp(acc, (255, 255, 255), 0.6))
        d.polygon(S([(186, 150), (226, 166), (224, 172), (184, 156)]), fill=AD)
        d.polygon(S([(114, 150), (74, 166), (76, 172), (116, 156)]), fill=AD)

    elif role == "orator":
        rim_line(arm_pts(), 18, F)
        rim_ell((250, 78, 276, 104), F)
        d.polygon(S(LECT), fill=D1)
        d.rectangle(B(LECT_TOP), fill=D2)
        d.line(S([(178, 206), (176, 186), (168, 172), (160, 164)]), fill=D2, width=int(2.6 * K), joint="curve")
        d.ellipse(B((151, 153, 167, 171)), fill=acc)
        d.ellipse(B((154, 156, 160, 162)), fill=lerp(acc, (255, 255, 255), 0.55))

    elif role == "operator":
        d.arc(B((108, 40, 192, 132)), 180, 360, fill=AD, width=int(9 * K))
        d.arc(B((108, 40, 192, 132)), 190, 350, fill=acc, width=int(2.2 * K))
        d.rounded_rectangle(B((102, 80, 120, 112)), radius=5 * K, fill=D2)
        d.rounded_rectangle(B((180, 80, 198, 112)), radius=5 * K, fill=D2)
        d.line(S([(194, 110), (190, 124), (168, 128)]), fill=AD, width=int(3.6 * K), joint="curve")
        d.ellipse(B((152, 121, 168, 136)), fill=acc)


def draw_predmet(img, role, pal):
    ink, mid, acc = pal
    LINE = (222, 222, 226)
    FILL = lerp(mid, (255, 255, 255), 0.22)
    FILL2 = lerp(mid, (255, 255, 255), 0.12)
    AD = lerp(acc, mid, 0.45)
    d = ImageDraw.Draw(img)
    lw = int(5 * K)

    d.ellipse(B((28, 28, 272, 272)), outline=lerp(mid, (255, 255, 255), 0.3), width=int(1.6 * K))

    if role == "chinovnik":
        d.rounded_rectangle(B((124, 84, 176, 118)), radius=9 * K, outline=LINE, width=lw)
        d.rounded_rectangle(B((70, 108, 230, 220)), radius=12 * K, fill=FILL, outline=LINE, width=lw)
        d.line(S([(72, 150), (228, 150)]), fill=LINE, width=int(3 * K))
        d.rectangle(B((110, 142, 132, 158)), fill=acc)
        d.rectangle(B((168, 142, 190, 158)), fill=acc)
        d.line(S([(134, 150), (166, 150)]), fill=AD, width=int(3 * K))

    elif role == "orator":
        d.ellipse(B((100, 222, 200, 244)), fill=FILL, outline=LINE, width=int(3 * K))
        d.line(S([(150, 232), (150, 176)]), fill=LINE, width=lw)
        d.arc(B((112, 98, 188, 196)), 0, 180, fill=LINE, width=lw)
        d.rounded_rectangle(B((126, 66, 174, 168)), radius=24 * K, fill=acc)
        for y in (92, 108, 124, 140):
            d.line(S([(133, y), (167, y)]), fill=lerp(acc, (0, 0, 0), 0.45), width=int(2 * K))
        d.arc(B((176, 90, 232, 146)), -40, 40, fill=AD, width=int(3 * K))
        d.arc(B((192, 74, 264, 162)), -40, 40, fill=AD, width=int(3 * K))

    elif role == "operator":
        d.arc(B((84, 58, 216, 196)), 180, 360, fill=LINE, width=int(8 * K))
        d.rounded_rectangle(B((70, 118, 104, 174)), radius=8 * K, fill=FILL, outline=LINE, width=lw)
        d.rounded_rectangle(B((196, 118, 230, 174)), radius=8 * K, fill=FILL, outline=LINE, width=lw)
        d.line(S([(214, 174), (214, 198), (178, 210)]), fill=acc, width=int(6 * K), joint="curve")
        d.ellipse(B((156, 200, 180, 222)), fill=acc)

    elif role == "aytishnik":
        d.rounded_rectangle(B((72, 70, 228, 186)), radius=8 * K, fill=FILL2, outline=LINE, width=lw)
        d.rectangle(B((84, 82, 216, 174)), fill=lerp(acc, ink, 0.62))
        d.polygon(S([(56, 190), (244, 190), (254, 214), (46, 214)]), fill=FILL, outline=LINE)
        d.line(S([(56, 190), (244, 190), (254, 214), (46, 214), (56, 190)]), fill=LINE, width=int(3 * K))
        f = ImageFont.truetype(FONT, int(44 * K))
        tw = d.textlength("</>", font=f)
        d.text((150 * K - tw / 2, 102 * K), "</>", font=f, fill=lerp(acc, (255, 255, 255), 0.25))


DRAW = {"kontrovoy": draw_kontrovoy, "predmet": draw_predmet}


def render_cell(direction, role, channel):
    rec = palitra.KANALY[channel]
    ink, mid = rec["fon"]
    acc = rec["accent"]
    Spx = CELL * K
    img = Image.new("RGBA", (Spx, Spx), ink + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((10 * K, 10 * K, Spx - 10 * K, Spx - 10 * K), radius=18 * K, fill=mid + (255,))
    work = img.copy()
    DRAW[direction](work, role, (ink, mid, acc))
    cm = Image.new("L", (Spx, Spx), 0)
    ImageDraw.Draw(cm).rounded_rectangle((10 * K, 10 * K, Spx - 10 * K, Spx - 10 * K), radius=18 * K, fill=255)
    img = Image.composite(work, img, cm)
    return img.convert("RGB").resize((CELL, CELL), Image.LANCZOS)


_КЭШ = {}


def спрайт(номер, channel):
    """RGBA-карточка иконки №`номер` (см. NUMER) в гамме `channel`."""
    ключ = (номер, channel)
    if ключ not in _КЭШ:
        dkey, rkey = NUMER[номер]
        _КЭШ[ключ] = render_cell(dkey, rkey, channel).convert("RGBA")
    return _КЭШ[ключ]
