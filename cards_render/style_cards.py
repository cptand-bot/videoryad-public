#!/usr/bin/env python3
"""ОФОРМИТЕЛЬСКАЯ СИСТЕМА второго сборщика ("полный цикл").

Снята измерениями с эталонного ролика (разбор 2026-10-17) и сведена в
ОДИН набор правил, потому что "богатство" там держится не отдельными
красивостями, а тем, что система не меняется от первой секунды до
последней:

  роли шрифта   — узкий жирный гротеск (суть), моноширинный в разрядку
                  (данные и подписи), мелкий золотой (служебное);
  роли цвета    — белый суть, золотой служебное, красный акцент/маркер,
                  серый подвал;
  одна сетка    — левое поле 264, эпиграф -> заголовок -> тело -> сноска;
  подвал        — строка-источник есть у КАЖДОГО элемента;
  вотермарка    — всегда в одном углу;
  цвет имени    — у каждого говорящего свой и не меняется весь ролик.

Рисует статичные PNG 1920x1080. Анимация (проявление по очереди) живёт
отдельно и использует эти же функции покадрово.
"""
import math as _math
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1920, 1080

# ---------- цветовые роли ----------
INK      = (10, 10, 11)        # фон
INK_MID  = (23, 23, 24)        # центр виньетки
WHITE    = (232, 232, 232)     # суть
GOLD     = (234, 189, 35)      # служебное: эпиграфы, сноски
RED      = (185, 37, 38)       # маркеры, рамки, кавычки, акцент
GREY     = (145, 145, 145)     # подвал, вотермарка
GREY_DIM = (108, 108, 112)

# цвет закреплён за говорящим на весь ролик — это и держит "систему"
SPEAKER_COLORS = [(214, 58, 52), (72, 187, 120), (168, 130, 232),
                  (236, 170, 54), (86, 170, 232)]

# ---------- шрифтовые роли ----------
NV = os.path.expanduser("~/.claude/skills/news-video/template/fonts")
F_HEAD = os.path.join(NV, "RobotoCondensed-Bold.ttf")   # суть
F_ALT  = os.path.join(NV, "Oswald-Bold.ttf")            # имена
MONO   = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

# ---------- сетка ----------
MARGIN_L = 264        # левое поле текста
MARK_X   = 217        # колонка маркеров — левее текста
FOOT_Y   = 1006       # подвал-источник
WM_Y     = 1032       # вотермарка


_FONT_CACHE = {}


def _f(path, size):
    # шрифт грузился заново на каждый кадр анимации — теперь один раз
    k = (path, size)
    if k not in _FONT_CACHE:
        _FONT_CACHE[k] = ImageFont.truetype(path, size)
    return _FONT_CACHE[k]


# ---------- проявление по очереди ----------
# Пользователь, 2026-10-17: "сделал бы более динамичными эти надписи…
# чтобы они появлялись одна за другой". Не прыжок букв (это снятый игровой
# язык), а выезд строки с затуханием — строго, но живо.
def _ev(sfx, at, role):
    """Звуковое событие на появление элемента. Роли те же, что понимает
    build_sfx_track.py: accent=whoosh, label=pop/клик, quote=ding,
    card=затвор камеры. Пользователь, 2026-10-17: «прямо просятся звуковые
    эффекты, лёгонький саунд-дизайн… приглушённый, но слышимый»."""
    if sfx is not None:
        sfx.append({"at": round(at, 2), "role": role})


REVEAL = 0.26          # сколько едет одна строка
SHIFT = 34             # на сколько пикселей выезжает слева


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _rv(t, at):
    """Возвращает (прозрачность 0..1, сдвиг по x) для элемента, который
    начинает проявляться в момент `at`. t=None — показать целиком."""
    if t is None:
        return 1.0, 0.0
    e = _ease((t - at) / REVEAL)
    return e, (1 - e) * SHIFT


def _put(im, layer_draw_fn, alpha, dx):
    """Нарисовать слой с прозрачностью и сдвигом."""
    if alpha <= 0:
        return im
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer_draw_fn(ImageDraw.Draw(lay))
    if dx:
        lay = lay.transform((W, H), Image.AFFINE, (1, 0, -dx, 0, 1, 0))
    if alpha < 1:
        a = lay.split()[3].point(lambda v: int(v * alpha))
        lay.putalpha(a)
    return Image.alpha_composite(im.convert("RGBA"), lay).convert("RGB")


def render_anim(fn, kwargs, seconds, out_mp4, fps=25, sfx_out=True,
                anim_seconds=None, tail_zoom=0.06, tail_style="step", crf=19):
    """Гонит кадры функции fn(t=...) в ffmpeg. Статичный PNG та же функция
    отдаёт при t=None — одна реализация на оба случая, разъехаться нечему.

    anim_seconds — сколько секунд РИСОВАТЬ покадрово. Дальше идёт хвост:
    последний нарисованный кадр не перерисовывается в PIL, а МЕДЛЕННО
    НАЕЗЖАЕТ — дешёвый resize+crop вместо полной отрисовки. Рисование
    занимает почти всё время рендера, поэтому карточка на 5 секунд с
    anim_seconds=2.0 считается примерно в 2,5 раза быстрее (хвост 4 от
    2026-10-17).

    ЗАЧЕМ ЗУМ В ХВОСТЕ (2026-10-21, слово пользователя про картограммы):
    «области выделил, надписи проанимировал — и она застыла. Когда
    застыло, лучше делай зум, просто приближай, чтобы она не стояла».
    Раньше хвост был буквально замороженным кадром, и на длинной сцене
    карточка стояла мёртвой по 8-10 секунд. Теперь она доезжает до конца
    куска. Амплитуда маленькая и в одну сторону — правило «без тряски,
    только медленный зум» (19.10) соблюдено. tail_zoom=0 возвращает
    прежнюю заморозку."""
    import subprocess, json
    if sfx_out:
        ev = []
        try:
            fn(t=None, sfx=ev, **kwargs)
            json.dump(ev, open(out_mp4.rsplit(".", 1)[0] + ".sfx.json", "w",
                               encoding="utf-8"), ensure_ascii=False, indent=1)
        except TypeError:
            pass          # функция ещё не умеет sfx — не беда
    n = int(round(seconds * fps))
    pr = subprocess.Popen(
        ["nice", "-n", "19", "ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
         # crf регулируется: зернистой плёнке нужен более щадящий поток,
         # иначе файл раздувается до десятков мегабайт (21.10)
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-threads", "4", out_mp4],
        stdin=subprocess.PIPE)
    n_draw = n if anim_seconds is None else min(n, int(round(anim_seconds * fps)))
    buf = None
    last = None
    tail = max(1, n - n_draw)
    for i in range(n):
        if i < n_draw:
            last = fn(t=i / fps, **kwargs)
            buf = last.tobytes()
        elif tail_zoom and last is not None:
            # наезд вместо замороженного кадра: кадр уже нарисован, поэтому
            # это просто resize+crop — дешевле отрисовки
            p = (i - n_draw + 1) / tail
            if tail_style == "step":
                # ПЛАВНО, А НЕ РЫВКОМ (user, 21.10: «не резко зум, а вот он
                # идёт плавно, раз, остановился… у тебя дрык-стоп»). Наезд
                # занимает БОЛЬШУЮ часть ступени и идёт по smoothstep —
                # плавный разгон и плавное торможение, потом пауза.
                tail_sec = tail / fps
                steps = max(2, min(3, int(round(tail_sec / 3.6))))
                rise = 0.80                    # доля шага на сам ход
                q = p * steps
                k = min(steps - 1, int(q))     # номер текущей ступени
                frac = q - k
                x = min(1.0, frac / rise)
                # smootherstep: ноль скорости И ускорения на концах хода
                e = x * x * x * (x * (x * 6 - 15) + 10)
                z = 1.0 + tail_zoom * (k + e) / steps
            else:
                z = 1.0 + tail_zoom * p
            zw, zh = int(W * z), int(H * z)
            im = last.resize((zw, zh), Image.LANCZOS)
            buf = im.crop(((zw - W) // 2, (zh - H) // 2,
                           (zw - W) // 2 + W, (zh - H) // 2 + H)).tobytes()
        pr.stdin.write(buf)
    pr.stdin.close()
    pr.wait()
    return out_mp4


def track(d, xy, text, font, fill, spacing=0):
    """Текст в разрядку. Разрядка — половина фирменного стиля: без неё
    эпиграф и моноширинные подписи читаются как обычный текст."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + spacing
    return x - xy[0]


def track_w(text, font, spacing=0):
    return sum(font.getlength(c) + spacing for c in text) - spacing


_CANVAS_CACHE = {}


def canvas():
    if "im" in _CANVAS_CACHE:
        return _CANVAS_CACHE["im"].copy()
    im = _canvas_build()
    _CANVAS_CACHE["im"] = im
    return im.copy()


def _canvas_build():
    """Фон: не плоская заливка, а мягкая радиальная виньетка плюс зерно —
    у эталона центр #171717, углы #070707."""
    im = Image.new("RGB", (W, H), INK)
    g = Image.new("L", (W // 8, H // 8), 0)
    gd = ImageDraw.Draw(g)
    gd.ellipse((-W // 16, -H // 16, W // 8 + W // 16, H // 8 + H // 16), fill=150)
    g = g.filter(ImageFilter.GaussianBlur(26)).resize((W, H), Image.BILINEAR)
    im = Image.composite(Image.new("RGB", (W, H), INK_MID), im, g)
    # зерно
    import random
    rnd = random.Random(7)
    noise = Image.new("L", (W // 2, H // 2))
    noise.putdata([rnd.randint(0, 16) for _ in range((W // 2) * (H // 2))])
    noise = noise.resize((W, H), Image.BILINEAR)
    im = Image.composite(Image.new("RGB", (W, H), (26, 26, 28)), im,
                         noise.point(lambda v: min(255, v * 11)))
    return im


def footer(d, source, watermark="ДО ПРИГОВОРА"):
    """Строка-источник + вотермарка. У эталона подвал есть у КАЖДОГО
    элемента — именно это и читается как профессиональная подача."""
    f = _f(MONO, 21)
    if source:
        d.text((MARGIN_L, FOOT_Y), source, font=f, fill=GREY_DIM)
    if watermark:
        fw = _f(F_HEAD, 21)
        wtext = watermark.upper()
        w = track_w(wtext, fw, 3)
        d.ellipse((W - 150 - w - 16, WM_Y + 7, W - 150 - w - 8, WM_Y + 15), fill=(118, 29, 34))
        track(d, (W - 150 - w, WM_Y), wtext, fw, GREY, 3)


PULSE_PERIOD = 1.7          # секунд на вдох-выдох точки
PULSE_FLOOR = 0.42          # самая тусклая фаза: точка НЕ исчезает


def pulse(t, period=PULSE_PERIOD, floor=PULSE_FLOOR):
    """Плавная пульсация 0..1 для «живой» красной точки.

    user, 2026-10-17: точка должна ПУЛЬСИРОВАТЬ, а не моргать. Поэтому
    косинус (ровное дыхание) и нижний порог: в самой тусклой фазе точка
    всё равно видна, иначе получается именно моргание.
    t=None — статичный кадр, точка в полную силу.
    """
    if t is None:
        return 1.0
    k = (1 - _math.cos(2 * _math.pi * (t % period) / period)) / 2
    return floor + (1 - floor) * k


def red_dot(d, cx, cy, r=7, t=None, glow=True):
    """Красная точка с пульсирующим ореолом. Одна реализация на все места,
    где точка появляется (кикер, слой атрибуции, засечки схем)."""
    k = pulse(t)
    if glow:
        for i, rr in enumerate((r * 2.9, r * 2.0, r * 1.45)):
            a = int((26 + 16 * i) * k)
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=RED + (a,))
    v = 0.55 + 0.45 * k
    col = (int(RED[0] * v + 40 * k), int(RED[1] * v), int(RED[2] * v))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col + (int(255 * (0.75 + 0.25 * k)),))


def kicker(d, y, text, dot=False, t=None):
    """Золотой эпиграф в разрядку — служебная роль, всегда над заголовком.
    dot=True — рядом живая красная точка (пульсирует, когда задан t)."""
    # ПУСТОЙ ЭПИГРАФ — НИЧЕГО НЕ РИСУЕМ (2026-10-22, улов `usuario-ec`):
    # у карточки без --kick/--title вверху слева оставалась сиротливая красная
    # точка без текста. Косметика, но на тёмном фоне заметна и читается как
    # недорисованный элемент.
    if not (text or "").strip():
        return
    f = _f(F_HEAD, 27)
    x = MARGIN_L
    if dot:
        red_dot(d, MARK_X + 11, y + 14, 7, t)
    track(d, (x, y), text.upper(), f, GOLD, 5)


def bullets(out=None, kick="", items=(), note=None, source="", watermark="ДО ПРИГОВОРА",
            t=None, sfx=None):
    """Список: эпиграф -> красные квадраты -> белые пункты -> золотая сноска.
    Строки проявляются ПО ОЧЕРЕДИ (t=None — сразу все)."""
    im = canvas()
    f = _f(F_HEAD, 72)
    a, dx = _rv(t, 0.15)
    _ev(sfx, 0.15, "accent")
    im = _put(im, lambda d: kicker(d, 300, kick), a, dx)
    y = 392
    for i, it in enumerate(items):
        a, dx = _rv(t, 0.52 + i * 0.24)
        _ev(sfx, 0.52 + i * 0.24, "label")
        yy = y

        def draw(d, yy=yy, it=it):
            d.rectangle((MARK_X, yy + 26, MARK_X + 20, yy + 46), fill=RED + (255,))
            d.text((MARGIN_L, yy), it, font=f, fill=WHITE + (255,))
        im = _put(im, draw, a, dx)
        y += 118
    if note:
        a, dx = _rv(t, 0.52 + len(items) * 0.24 + 0.2)
        im = _put(im, lambda d: d.text((MARGIN_L, y + 22), note, font=_f(MONO, 30),
                                       fill=GOLD + (255,)), a, dx)
    a, _ = _rv(t, 0.9)
    im = _put(im, lambda d: footer(d, source, watermark), a, 0)
    if out:
        im.save(out)
    return im


def person(out=None, name="", photo="", facts=(), kick="", source="",
           watermark="ДО ПРИГОВОРА", t=None, live=True, sfx=None):
    """Карточка человека: фото в тонкой красной рамке слева, имя крупно
    в разрядку справа, под ним красная черта, ниже факты моноширинным.
    Фото ЖИВОЕ (параллакс + съёмка с рук + зерно), строки проявляются
    по очереди."""
    im = canvas()
    PW, PH = 468, 624
    px, py = 236, 228
    ap, _ = _rv(t, 0.12)
    _ev(sfx, 0.12, "card")            # затвор камеры на появление портрета
    if ap > 0:
        ph = live_photo(photo, PW, PH, t if (live and t is not None) else None)
        if ap < 1:                      # проявление вместе с рамкой
            ph = Image.blend(Image.new("RGB", (PW, PH), INK), ph, ap)
        im.paste(ph, (px, py))
        d = ImageDraw.Draw(im)
        d.rectangle((px - 4, py - 4, px + PW + 3, py + PH + 3),
                    outline=tuple(int(c * ap) for c in RED), width=4)

    tx = px + PW + 96
    if kick:
        a, dx = _rv(t, 0.34)
        im = _put(im, lambda d: track(d, (tx, py + 6), kick.upper(),
                                      _f(F_HEAD, 27), GOLD + (255,), 5), a, dx)
    fn = _f(F_ALT, 76)
    a, dx = _rv(t, 0.5)
    _ev(sfx, 0.5, "accent")
    im = _put(im, lambda d: track(d, (tx, py + 54), name.upper(), fn, WHITE + (255,), 4), a, dx)
    nw = track_w(name.upper(), fn, 4)
    # черта под именем ПРОЧЕРЧИВАЕТСЯ, а не возникает
    lg = 1.0 if t is None else _ease((t - 0.72) / 0.35)
    if lg > 0:
        im = _put(im, lambda d: d.rectangle((tx, py + 174, tx + min(nw, 520) * lg, py + 179),
                                            fill=RED + (255,)), 1.0, 0)
    fm = _f(MONO, 31)
    for i, ln in enumerate(facts):
        a, dx = _rv(t, 0.95 + i * 0.17)
        _ev(sfx, 0.95 + i * 0.17, "label")
        yy = py + 226 + i * 56
        im = _put(im, lambda d, ln=ln, yy=yy: track(d, (tx, yy), ln, fm,
                                                    (190, 190, 190, 255), 1), a, dx)
    af, _ = _rv(t, 1.1)
    im = _put(im, lambda d: footer(d, source, watermark), af, 0)
    if out:
        im.save(out)
    return im


def quote(out=None, text="", author="", source="", watermark="ДО ПРИГОВОРА",
          accent=None, t=None, sfx=None):
    """Цитата БЕЗ плашки: крупная красная кавычка, белый узкий жирный текст,
    золотая атрибуция. Строки проявляются ПО ОЧЕРЕДИ, акцентное слово
    приходит красным и коротко подсвечивается (user, 2026-10-18: «всё
    должно быть динамичным — пункты, цитаты, всё»)."""
    im = canvas()
    f = _f(F_HEAD, 70)
    a0, dx0 = _rv(t, 0.05)
    _ev(sfx, 0.05, "quote")
    im = _put(im, lambda d: d.text((MARGIN_L - 26, 318), "««", font=_f(F_HEAD, 128), fill=RED),
              a0, dx0)
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if f.getlength(probe) > 1340 and cur:
            lines.append(cur); cur = w
        else:
            cur = probe
    lines.append(cur)
    y = 440
    for i, ln in enumerate(lines):
        at = 0.2 + i * 0.17
        av, dxv = _rv(t, at)
        if av <= 0:
            y += 92
            continue
        _ev(sfx, at, "label")
        if accent and accent in ln:
            k = ln.index(accent)
            pre, post = ln[:k], ln[k + len(accent):]
            # вспышка на приходе акцента: ярче в первые полсекунды
            hot = 1.0 if t is None else max(0.0, 1 - (t - at) * 2.0)
            acol = (min(255, RED[0] + int(70 * hot)), RED[1] + int(28 * hot), RED[2] + int(28 * hot))
            im = _put(im, lambda d, y=y, pre=pre, post=post, acol=acol:
                      (d.text((MARGIN_L, y), pre, font=f, fill=WHITE),
                       d.text((MARGIN_L + f.getlength(pre), y), accent, font=f, fill=acol),
                       d.text((MARGIN_L + f.getlength(pre + accent), y), post, font=f, fill=WHITE)),
                      av, dxv)
        else:
            im = _put(im, lambda d, y=y, ln=ln: d.text((MARGIN_L, y), ln, font=f, fill=WHITE),
                      av, dxv)
        y += 92
    if author:
        aa, dxa = _rv(t, 0.2 + len(lines) * 0.17 + 0.12)
        im = _put(im, lambda d, y=y: d.text((MARGIN_L, y + 30), "— " + author,
                                            font=_f(MONO, 30), fill=GOLD), aa, dxa)
    d = ImageDraw.Draw(im)
    footer(d, source, watermark)
    if out:
        im.save(out); return out
    return im


def lower_third(out=None, base_photo="", speaker="", words="", speaker_idx=0,
                kick=None, kick_sub=None, watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Реплика поверх кадра: имя говорящего СВОИМ закреплённым цветом,
    слова белым, снизу по центру на градиенте. Плюс кикер слева вверху
    с датой и источником — атрибуция у эталона есть на каждом куске.
    18.10: кадр живой (медленный зум), плашка приходит первой, строки
    выезжают по очереди, красная точка пульсирует."""
    from PIL import ImageOps
    if t is None:
        im = ImageOps.fit(Image.open(base_photo).convert("RGB"), (W, H), Image.LANCZOS)
    else:
        im = live_photo(base_photo, W, H, t=t)
    # затемнение краёв
    v = Image.new("L", (W // 8, H // 8), 0)
    ImageDraw.Draw(v).ellipse((-W // 40, -H // 40, W // 8 + W // 40, H // 8 + H // 40), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(22)).resize((W, H), Image.BILINEAR)
    im = Image.composite(im, Image.new("RGB", (W, H), (0, 0, 0)), v.point(lambda x: 60 + x * 0.76))
    # градиент под реплику
    grad = Image.new("L", (1, H), 0)
    for yy in range(H):
        grad.putpixel((0, yy), 0 if yy < H - 300 else int(205 * (yy - (H - 300)) / 300))
    im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im,
                         grad.resize((W, H), Image.BILINEAR))
    if kick:
        ak, dxk = _rv(t, 0.08)
        _ev(sfx, 0.08, "label")
        if ak > 0:
            scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(scrim).rectangle((0, 0, 1180, 186), fill=(0, 0, 0, 150))
            scrim = scrim.filter(ImageFilter.GaussianBlur(34))
            if ak < 1:
                scrim.putalpha(scrim.split()[3].point(lambda q: int(q * ak)))
            im = Image.alpha_composite(im.convert("RGBA"), scrim).convert("RGB")
            im = _put(im, lambda d: (red_dot(d, 139, 79, 7, t),
                                     track(d, (160, 64), kick.upper(), _f(F_HEAD, 29), WHITE, 4),
                                     kick_sub and d.text((160, 102), kick_sub,
                                                         font=_f(MONO, 23), fill=(176, 176, 176))),
                      ak, dxk)
    col = SPEAKER_COLORS[speaker_idx % len(SPEAKER_COLORS)]
    f = _f(F_HEAD, 42)
    sp = speaker + ": "
    total = f.getlength(sp) + f.getlength(words)
    if total > 1380:
        cut = words.rfind(" ", 0, int(len(words) * 1380 / total))
        rows = [words[:cut], words[cut + 1:]]
    else:
        rows = [words]
    y = H - 196
    for i, r in enumerate(rows):
        at = 0.3 + i * 0.18
        av, dxv = _rv(t, at)
        _ev(sfx, at, "quote" if i == 0 else "label")
        if av <= 0:
            y += 54
            continue
        wtot = (f.getlength(sp) if i == 0 else 0) + f.getlength(r)
        x0 = (W - wtot) / 2
        im = _put(im, lambda d, y=y, r=r, i=i, x0=x0:
                  ((d.text((x0, y), sp, font=f, fill=col) if i == 0 else None),
                   d.text((x0 + (f.getlength(sp) if i == 0 else 0), y), r, font=f,
                          fill=(240, 240, 240))), av, dxv)
        y += 54
    d = ImageDraw.Draw(im)
    if watermark:
        fw = _f(F_HEAD, 21); wt = watermark.upper()
        w = track_w(wt, fw, 3)
        track(d, ((W - w) / 2, H - 46), wt, fw, (150, 150, 150), 3)
    if out:
        im.save(out); return out
    return im


def timeline(out=None, kick="", title="", events=(), note=None, source="",
             watermark="ДО ПРИГОВОРА", gap=None, t=None, sfx=None):
    """Хронология одной линией, с движением (user, 2026-10-17: "чтобы была
    динамика… график ползущий, какой-то динамичный"):
      линия прочерчивается слева направо, засечки зажигаются по очереди,
      горячие пульсируют свечением, подписи выезжают следом, разрыв
      дорисовывается пунктиром, крупное число выскакивает.
    У события можно задать "photo" — рядом всплывёт круглая врезка.
    """
    im = canvas()
    a, dx = _rv(t, 0.1)
    _ev(sfx, 0.1, "accent")
    im = _put(im, lambda d: kicker(d, 236, kick), a, dx)
    a, dx = _rv(t, 0.3)
    im = _put(im, lambda d: d.text((MARGIN_L, 288), title, font=_f(F_HEAD, 64),
                                   fill=WHITE + (255,)), a, dx)

    x0, x1, y = MARGIN_L, W - 300, 616
    n = len(events)
    step = (x1 - x0) / max(n - 1, 1)
    # 2026-10-17: схема шла слишком быстро («очень быстро это раз») —
    # линия ползёт втрое дольше, событиям есть время прочитаться.
    T_LINE, T_LINE_DUR = 0.8, 3.6            # сколько ползёт линия
    grow = 1.0 if t is None else _ease((t - T_LINE) / T_LINE_DUR)
    if grow > 0:
        im = _put(im, lambda d: d.rectangle((x0, y - 1, x0 + (x1 - x0) * grow, y + 2),
                                            fill=(62, 62, 66, 255)), 1.0, 0)
    fm, fb = _f(MONO, 27), _f(F_HEAD, 40)
    for i, e in enumerate(events):
        x = x0 + step * i
        at = T_LINE + T_LINE_DUR * (i / max(n - 1, 1))      # засечка в момент прихода линии
        av, _ = _rv(t, at)
        hot = e.get("hot")
        _ev(sfx, at, "quote" if hot else "label")
        if av <= 0:
            continue
        if hot:
            # пульс: ярче сразу после появления, потом ровное свечение
            ph = 1.0 if t is None else 0.55 + 0.45 * max(0.0, 1 - (t - at) * 1.1)
            glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(glow).rectangle((x - 9, y - 42, x + 9, y + 42),
                                           fill=(214, 46, 46, int(165 * ph * av)))
            im = Image.alpha_composite(im.convert("RGBA"),
                                       glow.filter(ImageFilter.GaussianBlur(16))).convert("RGB")
        col = (RED if hot else (205, 205, 205)) + (255,)
        h2 = 34 * (0.4 + 0.6 * av)
        im = _put(im, lambda d, x=x, h2=h2, col=col:
                  d.rectangle((x - 5, y - h2, x + 5, y + h2), fill=col), av, 0)
        am, dxm = _rv(t, at + 0.08)
        mark = e.get("mark") or e.get("date") or ""   # 18.10: принимаем и "date"
        mw = track_w(mark, fb, 2)
        im = _put(im, lambda d, x=x, mark=mark, mw=mw, hot=hot:
                  track(d, (x - mw / 2, y - 112), mark, fb,
                        (WHITE if hot else (190, 190, 190)) + (255,), 2), am, dxm)
        words, rows, cur = e["text"].split(" "), [], ""
        for wd in words:
            tt = (cur + " " + wd).strip()
            if fm.getlength(tt) > step - 24 and cur:
                rows.append(cur); cur = wd
            else:
                cur = tt
        rows.append(cur)
        at2, dxt = _rv(t, at + 0.16)

        def lab(d, x=x, rows=rows):
            yy = y + 58
            for r in rows:
                rw = track_w(r, fm, 1)
                track(d, (x - rw / 2, yy), r, fm, (168, 168, 168, 255), 1)
                yy += 36
        im = _put(im, lab, at2, dxt)
        if e.get("photo") and os.path.exists(e["photo"]):
            ap, _ = _rv(t, at + 0.3)
            if ap > 0:
                im = _paste_round(im, e["photo"], int(x), y + 190, int(118 * ap), RED)
    if gap:
        a = x0 + step * (gap["after"] - 1); b = a + step
        gt = T_LINE + T_LINE_DUR + 0.25
        ag, _ = _rv(t, gt)
        if ag > 0:
            def dots(d):
                for gx in range(int(a) + 14, int(b) - 10, 22):
                    d.rectangle((gx, y - 1, gx + 11, y + 2), fill=GOLD + (255,))
            im = _put(im, dots, ag, 0)
            # число выскакивает: сперва крупнее, потом садится
            pop = 1.0 if t is None else 1.0 + 0.22 * max(0.0, 1 - (t - gt - 0.1) * 4)
            fsz = int(56 * min(pop, 1.3))
            fg = _f(F_HEAD, fsz)
            gw = track_w(gap["label"], fg, 2)
            an, _ = _rv(t, gt + 0.1)
            _ev(sfx, gt + 0.1, "quote")
            im = _put(im, lambda d: track(d, ((a + b) / 2 - gw / 2, y - 196 - (fsz - 56) / 2),
                                          gap["label"], fg, GOLD + (255,), 2), an, 0)
    if note:
        an, dxn = _rv(t, T_LINE + T_LINE_DUR + 0.45)
        im = _put(im, lambda d: d.text((MARGIN_L, 872), note, font=_f(MONO, 29),
                                       fill=GOLD + (255,)), an, dxn)
    af, _ = _rv(t, 0.9)
    im = _put(im, lambda d: footer(d, source, watermark), af, 0)
    if out:
        im.save(out)
    return im


def _paste_round(im, path, cx, cy, size, ring):
    """Круглая фото-врезка рядом с событием — "маленькая фотография,
    что-то чего-то" (user, 2026-10-17)."""
    if size < 8:
        return im
    from PIL import ImageOps
    ph = ImageOps.fit(Image.open(path).convert("RGB"), (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    im.paste(ph, (cx - size // 2, cy - size // 2), mask)
    d = ImageDraw.Draw(im)
    d.ellipse((cx - size // 2 - 2, cy - size // 2 - 2, cx + size // 2 + 2, cy + size // 2 + 2),
              outline=ring, width=3)
    return im


def forces(out=None, kick="", title="", rows=(), note=None, source="",
           watermark="ДО ПРИГОВОРА", t=None, sfx=None):
    """Расстановка сил: кто и чего хочет. Та же грамматика, что у схемы —
    дорожки, засечки, моноширинные подписи, — но про интересы, а не про
    время. Для аналитических сюжетов, где настоящих цифр нет и рисовать
    столбцы было бы враньём.
    Строки приходят ПО ОЧЕРЕДИ, разделительная черта под каждой
    прочерчивается слева направо (18.10: «всё должно быть динамичным»).
    rows: [{"who": "ВАШИНГТОН", "want": "нужна сделка и фиксация активов"}]
    """
    im = canvas()
    a0, dx0 = _rv(t, 0.1)
    _ev(sfx, 0.1, "accent")
    im = _put(im, lambda d: (kicker(d, 232, kick, t=t),
                             d.text((MARGIN_L, 284), title, font=_f(F_HEAD, 64), fill=WHITE)),
              a0, dx0)
    # вместимость: при четырёх и более сторонах фиксированный шаг 184
    # уводил последнюю строку за нижний край, а сноска ложилась на текст
    # (найдено на витрине арсенала 19.10.2026)
    # ВМЕСТИМОСТЬ. Было: фиксированный шаг 184 — четвёртая сторона уезжала
    # за нижний край. Потом добавили ступени кегля, но черта-разделитель
    # считалась от доли шага и на мелком кегле ложилась ПОВЕРХ имени, а
    # сноска наезжала на последнюю строку (20.10). Теперь геометрия
    # считается от реальной высоты шрифтов, а не от долей.
    nr = max(1, len(rows))
    if nr <= 3:
        fw, fm = _f(F_ALT, 50), _f(MONO, 31)
    elif nr == 4:
        fw, fm = _f(F_ALT, 44), _f(MONO, 28)
    elif nr == 5:
        fw, fm = _f(F_ALT, 38), _f(MONO, 25)
    else:
        fw, fm = _f(F_ALT, 32), _f(MONO, 22)
    h_who = fw.size + 12            # имя
    h_want = fm.size + 10           # строка интереса
    gap = 26 if nr <= 4 else 18     # воздух между сторонами
    block = h_who + h_want + gap
    note_h = 54 if note else 0
    top = 432
    bottom = FOOT_Y - 34 - note_h
    avail = bottom - top
    if block * nr > avail:          # не влезает — поджимаем воздух
        gap = max(8, gap - (block * nr - avail) / nr)
        block = h_who + h_want + gap
    y = top + max(0, (avail - block * nr) / 2)

    for i, r in enumerate(rows):
        at = 0.42 + i * 0.3
        av, dxv = _rv(t, at)
        if av <= 0:
            y += block
            continue
        _ev(sfx, at, "label")
        im = _put(im, lambda d, y=y, r=r:
                  (d.rectangle((MARK_X, y + h_who * .30, MARK_X + 20,
                                y + h_who * .30 + 20), fill=RED),
                   track(d, (MARGIN_L, y), r["who"].upper(), fw, WHITE, 3)), av, dxv)
        # черта идёт ПОД именем, а не сквозь него
        g = 1.0 if t is None else _ease((t - at - 0.12) / 0.4)
        if g > 0:
            ly = y + h_who - 2
            im = _put(im, lambda d, ly=ly, g=g:
                      d.rectangle((MARGIN_L, ly, MARGIN_L + (W - 300 - MARGIN_L) * g,
                                   ly + 1), fill=(52, 52, 56)), 1.0, 0)
        aw, dxw = _rv(t, at + 0.16)
        im = _put(im, lambda d, y=y, r=r:
                  track(d, (MARGIN_L, y + h_who + 8), r["want"], fm,
                        (176, 176, 176), 1), aw, dxw)
        y += block

    if note:
        an, dxn = _rv(t, 0.42 + len(rows) * 0.3 + 0.1)
        ny = min(max(y + 8, FOOT_Y - 62), FOOT_Y - 48)
        im = _put(im, lambda d: d.text((MARGIN_L, ny), note,
                                       font=_f(MONO, 27), fill=GOLD), an, dxn)
    d = ImageDraw.Draw(im)
    footer(d, source, watermark)
    if out:
        im.save(out); return out
    return im


# ---------- прозрачные накладки (ложатся на движущийся кадр) ----------

_SCRIM_CACHE = {}


def kicker_overlay(out=None, text="", sub=None, watermark="ДО ПРИГОВОРА", t=None):
    """Слой атрибуции слева вверху: ПУЛЬСИРУЮЩАЯ красная точка, название
    куска в разрядку, под ним серая строка «дата · статус · источник».
    У эталона такой слой есть на КАЖДОМ куске архива — именно он и
    читается как профессиональная подача.
    t=None — статичный PNG (как раньше), t=секунда — кадр с живой точкой."""
    if "scrim" not in _SCRIM_CACHE:
        sc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sc).rectangle((0, 0, 1180, 196), fill=(0, 0, 0, 155))
        _SCRIM_CACHE["scrim"] = sc.filter(ImageFilter.GaussianBlur(36))
    im = Image.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 0)),
                               _SCRIM_CACHE["scrim"])
    d = ImageDraw.Draw(im)
    red_dot(d, 139, 79, 7, t)
    track(d, (160, 64), text.upper(), _f(F_HEAD, 29), WHITE + (255,), 4)
    if sub:
        d.text((160, 102), sub, font=_f(MONO, 23), fill=(178, 178, 178, 255))
    if watermark:
        fw = _f(F_HEAD, 21); wt = watermark.upper()
        w = track_w(wt, fw, 3)
        track(d, ((W - w) / 2, H - 46), wt, fw, (150, 150, 150, 230), 3)
    if out:
        im.save(out)
        return out
    return im


def attrib_frame(out=None, photo="", text="", sub=None,
                 watermark="ДО ПРИГОВОРА", t=None):
    """КАДР СО СЛОЕМ АТРИБУЦИИ — дежурный вид, которым закрывается ЛЮБАЯ
    сцена-фотография.

    user, 23.10.2026: «никаких пустых фотографий вообще, блин. Вообще».
    Поэтому голый кадр в ролик не попадает: либо на нём слой атрибуции,
    либо плашка-кикер с живой красной точкой — здесь это одно и то же,
    `kicker_overlay` поверх живого кадра (медленный зум + блик).
    """
    base = live_photo(photo, W, H, t=t)
    ov = kicker_overlay(None, text=text, sub=sub, watermark=watermark, t=t)
    im = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
    if out:
        im.save(out, quality=92)
        return out
    return im


def reply_overlay(out, speaker, words, speaker_idx=0):
    """Реплика участника: имя его закреплённым цветом, слова белым, на
    мягком градиенте снизу. Не дорожка субтитров — именно чужая речь."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad = Image.new("L", (1, H), 0)
    for yy in range(H):
        grad.putpixel((0, yy), 0 if yy < H - 320 else int(215 * (yy - (H - 320)) / 320))
    black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    black.putalpha(grad.resize((W, H), Image.BILINEAR))
    im = Image.alpha_composite(im, black)
    d = ImageDraw.Draw(im)
    col = SPEAKER_COLORS[speaker_idx % len(SPEAKER_COLORS)] + (255,)
    f = _f(F_HEAD, 42)
    sp = speaker + ": "
    total = f.getlength(sp) + f.getlength(words)
    if total > 1380:
        cut = words.rfind(" ", 0, int(len(words) * 1380 / total))
        rows = [words[:cut], words[cut + 1:]]
    else:
        rows = [words]
    y = H - 196
    for i, r in enumerate(rows):
        wtot = (f.getlength(sp) if i == 0 else 0) + f.getlength(r)
        x = (W - wtot) / 2
        if i == 0:
            d.text((x, y), sp, font=f, fill=col); x += f.getlength(sp)
        d.text((x, y), r, font=f, fill=(242, 242, 242, 255))
        y += 54
    im.save(out); return out


# ---------- ОЖИВШЕЕ ФОТО (без всякого видео) ----------
# user, 2026-10-17: «оживляем статичное фото… давай пока попробуем простым
# способом». Три слоя движения, все считаются локально и мгновенно:
#   параллакс   — центр кадра (человек) едет чуть сильнее фона, появляется объём;
#   съёмка с рук — микродрожание и дыхание масштаба, кадр перестаёт быть мёртвым;
#   зерно+блик  — живая плёнка и мягкий световой проход.
# Никаких прав и никаких скачиваний. Видео-источники — следующим шагом.
import random as _random

_NOISE_CACHE = {}


def reply_frame(out=None, photo="", speaker="", words="", speaker_idx=0,
                watermark="ДО ПРИГОВОРА", t=None):
    """РЕПЛИКА-ОТВЕТ ПОВЕРХ ЖИВОГО КАДРА — чтобы элемент «реплика» можно
    было поставить на сцену целиком, а не слоем без фона (2026-10-23)."""
    base = live_photo(photo, W, H, t=t)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    import tempfile as _tf
    tmp = os.path.join(_tf.mkdtemp(), "ov.png")
    reply_overlay(tmp, speaker, words, speaker_idx)
    ov = Image.open(tmp).convert("RGBA")
    im = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
    if watermark:
        d = ImageDraw.Draw(im)
        fw = _f(F_HEAD, 21); wt = watermark.upper()
        w = track_w(wt, fw, 3)
        track(d, ((W - w) / 2, H - 46), wt, fw, (150, 150, 150), 3)
    if out:
        im.save(out, quality=92)
        return out
    return im


def _noise1(seed, n=48):
    """Гладкий одномерный шум — ровное «дыхание», а не рывки."""
    if seed not in _NOISE_CACHE:
        r = _random.Random(seed)
        _NOISE_CACHE[seed] = [r.uniform(-1, 1) for _ in range(n)]
    pts = _NOISE_CACHE[seed]

    def f(x):
        p = x * n
        i = int(p) % n
        fr = p - _math.floor(p)
        a, b = pts[i], pts[(i + 1) % n]
        sm = fr * fr * (3 - 2 * fr)
        return a + (b - a) * sm
    return f


def live_photo(path, box_w, box_h, t=None, seed=3, period=11.0, zoom_to=1.09,
               sweep=True):
    """Фото в своём контейнере МЕДЛЕННО ЗУМИТСЯ, и по нему раз в проход
    идёт мягкий блик. Всё.

    user, 2026-10-17, после пробы со слоями и дрожанием: «зерно не надо,
    вот то что пробегает, типа блика, пускай остаётся. И вот это она
    дёргается — мне такое не подходит. Пускай зумится вот в этом
    контейнере, всё, достаточно».
    Поэтому здесь НЕТ: зерна, микродрожания, параллакса по слоям, проездов
    вбок. Не возвращать без прямой просьбы.
    t=None — обычный статичный кадр, та же функция.
    """
    from PIL import ImageOps, ImageChops
    src = Image.open(path).convert("RGB")
    if t is None:
        return ImageOps.fit(src, (box_w, box_h), Image.LANCZOS)

    k = min(1.0, t / period)
    e = k * k * (3 - 2 * k)                  # плавный разгон и торможение
    z = 1.0 + (zoom_to - 1.0) * e
    bw, bh = int(box_w * z), int(box_h * z)
    im = ImageOps.fit(src, (bw, bh), Image.LANCZOS)
    x = (bw - box_w) // 2
    y = (bh - box_h) // 2
    im = im.crop((x, y, x + box_w, y + box_h))

    if sweep:
        ph = (t % period) / period
        if 0.10 < ph < 0.44:
            kk = (ph - 0.10) / 0.34
            band = Image.new("L", (box_w, box_h), 0)
            bd = ImageDraw.Draw(band)
            cx = int(-box_w * 0.4 + kk * box_w * 1.8)
            bd.polygon([(cx, box_h), (cx + box_w // 3, box_h),
                        (cx + box_w // 3 + box_h // 2, 0), (cx + box_h // 2, 0)], fill=34)
            band = band.filter(ImageFilter.GaussianBlur(box_w * 0.07))
            im = ImageChops.add(im, Image.merge("RGB", (band, band, band)))
    return im


# ---------- ПРОКРУТКА «ВЕБ-СТРАНИЦЫ» (user, 2026-10-18) ----------
# «одним из эффектов дороговизности я бы хотел… как прокручиваешь
# интернет-страницу: сверху вниз, или снизу вверх, или справа налево».
# Полотно строится ОДИН раз теми же правилами системы (сетка 264, три
# шрифтовые роли, красные маркеры, строка-источник), а камера едет по нему
# с остановками на блоках — как человек читает и докручивает дальше.

PAGE_W = W                    # ширина полотна = ширина кадра
PAGE_COL = 1392               # ширина текстовой колонки


def _page_bg(w, h):
    """Фон полотна: та же виньетка и зерно, что у карточек, но тянется на
    любую длину (тайлом, иначе шум на 1920x6000 считается секунды)."""
    im = Image.new("RGB", (w, h), INK)
    side = Image.new("L", (w // 8, 1), 0)
    sd = ImageDraw.Draw(side)
    sd.rectangle((w // 32, 0, w // 8 - w // 32, 1), fill=150)
    side = side.filter(ImageFilter.GaussianBlur(14)).resize((w, h), Image.BILINEAR)
    im = Image.composite(Image.new("RGB", (w, h), INK_MID), im, side)
    import random
    rnd = random.Random(11)
    tile = Image.new("L", (256, 256))
    tile.putdata([rnd.randint(0, 16) for _ in range(256 * 256)])
    noise = Image.new("L", (w, h))
    for yy in range(0, h, 256):
        for xx in range(0, w, 256):
            noise.paste(tile, (xx, yy))
    im = Image.composite(Image.new("RGB", (w, h), (26, 26, 28)), im,
                         noise.point(lambda v: min(255, v * 11)))
    return im


def _wrap(text, font, max_w):
    out, cur = [], ""
    for word in text.split(" "):
        probe = (cur + " " + word).strip()
        if font.getlength(probe) > max_w and cur:
            out.append(cur); cur = word
        else:
            cur = probe
    if cur:
        out.append(cur)
    return out


def page_canvas(blocks, kick="", title="", meta="", watermark="ДО ПРИГОВОРА"):
    """Собирает длинное полотно-«страницу» и возвращает
    {"im": Image, "anchors": [y...]} — якоря это начала блоков, на них
    камера и останавливается при прокрутке.

    Блоки (что попадёт внутрь — дело сценария, форма одна):
      {"type":"head",  "text":...}                — подзаголовок
      {"type":"para",  "text":...}                — абзац
      {"type":"quote", "text":..., "author":...}  — врезка с красной кавычкой
      {"type":"bullets","items":[...]}            — пункты с красными квадратами
      {"type":"photo", "path":..., "caption":..., "source":...}
      {"type":"card",  "label":..., "text":...}   — плашка-факт
      {"type":"rule"}                             — разделитель
    """
    f_title = _f(F_HEAD, 104)
    f_head = _f(F_HEAD, 62)
    f_para = _f(F_HEAD, 44)
    f_mono = _f(MONO, 26)
    f_q = _f(F_HEAD, 58)

    # --- первый проход: считаем высоту, собираем план рисования
    plan, y = [], 108
    if kick:
        plan.append(("kick", y, kick)); y += 54
    if title:
        rows = _wrap(title, f_title, PAGE_COL)
        plan.append(("title", y, rows)); y += len(rows) * 116 + 18
    if meta:
        plan.append(("meta", y, meta)); y += 76
    plan.append(("rule", y, None)); y += 58

    anchors = []
    for b in blocks:
        tp = b.get("type")
        anchors.append(y)
        if tp == "head":
            rows = _wrap(b["text"].upper(), f_head, PAGE_COL)
            plan.append(("head", y, rows)); y += len(rows) * 74 + 34
        elif tp == "para":
            rows = _wrap(b["text"], f_para, PAGE_COL)
            plan.append(("para", y, rows)); y += len(rows) * 62 + 46
        elif tp == "quote":
            rows = _wrap(b["text"], f_q, PAGE_COL - 150)
            plan.append(("quote", y, (rows, b.get("author", ""))))
            y += len(rows) * 78 + (74 if b.get("author") else 34) + 40
        elif tp == "bullets":
            plan.append(("bullets", y, b["items"]))
            y += len(b["items"]) * 78 + 40
        elif tp == "photo":
            ph = b.get("height", 620)
            plan.append(("photo", y, (b["path"], b.get("caption", ""), b.get("source", ""), ph)))
            y += ph + 96
        elif tp == "card":
            plan.append(("card", y, (b.get("label", ""), b["text"])))
            y += 236
        elif tp == "rule":
            plan.append(("rule", y, None)); y += 72
    y += 180                      # воздух в конце, чтобы хвост не обрезался

    im = _page_bg(PAGE_W, max(y, H + 200))
    d = ImageDraw.Draw(im)
    for kind, yy, data in plan:
        if kind == "kick":
            red_dot(d, MARK_X + 11, yy + 14, 7, None)
            track(d, (MARGIN_L, yy), data.upper(), _f(F_HEAD, 27), GOLD, 5)
        elif kind == "title":
            for i, r in enumerate(data):
                d.text((MARGIN_L, yy + i * 116), r, font=f_title, fill=WHITE)
        elif kind == "meta":
            track(d, (MARGIN_L, yy), data, f_mono, GREY, 2)
        elif kind == "rule":
            d.rectangle((MARGIN_L, yy, MARGIN_L + PAGE_COL, yy + 1), fill=(48, 48, 52))
        elif kind == "head":
            for i, r in enumerate(data):
                track(d, (MARGIN_L, yy + i * 74), r, f_head, WHITE, 1)
            d.rectangle((MARK_X - 47, yy + 10, MARK_X - 11, yy + 14), fill=RED)
        elif kind == "para":
            for i, r in enumerate(data):
                d.text((MARGIN_L, yy + i * 62), r, font=f_para, fill=(206, 206, 206))
        elif kind == "quote":
            rows, author = data
            d.text((MARGIN_L - 18, yy - 24), "«", font=_f(F_HEAD, 150), fill=RED)
            for i, r in enumerate(rows):
                d.text((MARGIN_L + 112, yy + i * 78), r, font=f_q, fill=WHITE)
            if author:
                track(d, (MARGIN_L + 112, yy + len(rows) * 78 + 18),
                      author.upper(), f_mono, GOLD, 3)
        elif kind == "bullets":
            for i, it in enumerate(data):
                yb = yy + i * 78
                d.rectangle((MARK_X, yb + 18, MARK_X + 18, yb + 36), fill=RED)
                d.text((MARGIN_L, yb), it, font=f_para, fill=WHITE)
        elif kind == "photo":
            path, cap, src, ph = data
            from PIL import ImageOps
            pw = PAGE_COL
            try:
                src_im = ImageOps.fit(Image.open(path).convert("RGB"), (pw, ph), Image.LANCZOS)
                im.paste(src_im, (MARGIN_L, yy))
            except Exception:
                d.rectangle((MARGIN_L, yy, MARGIN_L + pw, yy + ph), fill=(30, 30, 32))
            d.rectangle((MARGIN_L, yy, MARGIN_L + 5, yy + ph), fill=RED)
            if cap:
                track(d, (MARGIN_L, yy + ph + 18), cap.upper(), _f(F_HEAD, 27), WHITE, 3)
            if src:
                d.text((MARGIN_L, yy + ph + 54), src, font=_f(MONO, 21), fill=GREY_DIM)
        elif kind == "card":
            label, text = data
            d.rectangle((MARGIN_L, yy, MARGIN_L + PAGE_COL, yy + 196), fill=(22, 22, 24))
            d.rectangle((MARGIN_L, yy, MARGIN_L + 5, yy + 196), fill=RED)
            track(d, (MARGIN_L + 44, yy + 34), label.upper(), _f(F_HEAD, 27), GOLD, 5)
            rows = _wrap(text, _f(F_HEAD, 48), PAGE_COL - 120)
            for i, r in enumerate(rows[:2]):
                d.text((MARGIN_L + 44, yy + 84 + i * 58), r, font=_f(F_HEAD, 48), fill=WHITE)
    return {"im": im, "anchors": anchors, "watermark": watermark}


def strip_canvas(cards, kick="", watermark="ДО ПРИГОВОРА"):
    """Широкая лента для горизонтальной прокрутки: карточки в ряд.
    cards: [{"photo":путь, "name":..., "note":...}]"""
    from PIL import ImageOps
    CW, GAP = 760, 72
    w = 264 + len(cards) * (CW + GAP) + 264
    im = _page_bg(w, H)
    d = ImageDraw.Draw(im)
    if kick:
        red_dot(d, 150, 118, 7, None)
        track(d, (180, 104), kick.upper(), _f(F_HEAD, 27), GOLD, 5)
    anchors = []
    x = 264
    for c in cards:
        anchors.append(x - 264)
        ph, pw = 560, CW
        try:
            src = ImageOps.fit(Image.open(c["photo"]).convert("RGB"), (pw, ph), Image.LANCZOS)
            im.paste(src, (x, 212))
        except Exception:
            d.rectangle((x, 212, x + pw, 212 + ph), fill=(30, 30, 32))
        d.rectangle((x - 5, 212, x, 212 + ph), fill=RED)
        track(d, (x, 212 + ph + 30), c.get("name", "").upper(), _f(F_HEAD, 42), WHITE, 3)
        if c.get("note"):
            d.text((x, 212 + ph + 92), c["note"], font=_f(MONO, 26), fill=(170, 170, 170))
        x += CW + GAP
    return {"im": im, "anchors": anchors, "watermark": watermark}


def scroll_clip(page, out_mp4, seconds=12.0, direction="up", hold=1.1,
                fps=25, watermark=True, sfx_out=True):
    """Прокрутка полотна, как страницы сайта.

    direction: "up"   — контент уезжает вверх (читаем сверху вниз, обычный скролл)
               "down" — наоборот, снизу вверх
               "left" — лента уезжает влево (читаем слева направо)
               "right"— наоборот
    hold — сколько секунд камера стоит на каждом блоке. Между блоками едет
    с разгоном и торможением (ease-in-out), поэтому движение не механическое.
    """
    import subprocess, json
    im = page["im"]
    horiz = direction in ("left", "right")
    span = (im.width - W) if horiz else (im.height - H)
    span = max(span, 0)
    raw = [a for a in page.get("anchors", []) if 0 <= a <= span]
    stops = sorted(set([0] + raw + [span]))
    # стоянки, которые ближе 120 px друг к другу, сливаем — иначе дёрганье
    merged = [stops[0]]
    for v in stops[1:]:
        if v - merged[-1] > 120:
            merged.append(v)
    stops = merged
    if direction in ("down", "right"):
        stops = stops[::-1]

    n = int(round(seconds * fps))
    n_hold = int(round(hold * fps))
    moves = max(len(stops) - 1, 1)
    n_move = max(n - n_hold * len(stops), moves * 6)
    per = n_move / moves

    wm = None
    if watermark and page.get("watermark"):
        wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dw = ImageDraw.Draw(wm)
        fw = _f(F_HEAD, 21); wt = page["watermark"].upper()
        ww = track_w(wt, fw, 3)
        dw.ellipse((W - 150 - ww - 16, WM_Y + 7, W - 150 - ww - 8, WM_Y + 15), fill=(118, 29, 34))
        track(dw, (W - 150 - ww, WM_Y), wt, fw, GREY + (230,), 3)

    if sfx_out:
        ev, tt = [], 0.0
        for i in range(len(stops)):
            ev.append({"at": round(tt, 2), "role": "label"})
            tt += hold + per / fps
        json.dump(ev, open(out_mp4.rsplit(".", 1)[0] + ".sfx.json", "w",
                           encoding="utf-8"), ensure_ascii=False, indent=1)

    pr = subprocess.Popen(
        ["nice", "-n", "19", "ffmpeg", "-v", "error", "-y", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
         # crf регулируется: зернистой плёнке нужен более щадящий поток,
         # иначе файл раздувается до десятков мегабайт (21.10)
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-threads", "4", out_mp4],
        stdin=subprocess.PIPE)

    sticky = page.get("sticky")

    def frame_at(off):
        off = int(round(off))
        box = ((off, 0, off + W, H) if horiz else (0, off, W, off + H))
        f = im.crop(box)
        if sticky is not None:
            f = Image.alpha_composite(f.convert("RGBA"), sticky).convert("RGB")
        if wm is not None:
            f = Image.alpha_composite(f.convert("RGBA"), wm).convert("RGB")
        return f

    written = 0
    for i, pos in enumerate(stops):
        for _ in range(n_hold):
            pr.stdin.write(frame_at(pos).tobytes()); written += 1
        if i + 1 < len(stops):
            a, b = pos, stops[i + 1]
            steps = int(round(per))
            for k in range(steps):
                x = (k + 1) / steps
                e = x * x * (3 - 2 * x)          # разгон и торможение
                pr.stdin.write(frame_at(a + (b - a) * e).tobytes()); written += 1
    while written < n:                            # добить хвост последним кадром
        pr.stdin.write(frame_at(stops[-1]).tobytes()); written += 1
    pr.stdin.close(); pr.wait()
    return out_mp4


def tape_canvas(events, kick="", title="", watermark="ДО ПРИГОВОРА", kind="chrono",
                step=720):
    """ЛЕНТА-ХРОНОЛОГИЯ ВБОК (user, 2026-10-18: «чтобы материал шёл справа
    налево — типа идёт рейтинг или хронология: год такой-то, появилось
    это, потом это, а первое уходит за прокрутку»).

    Отличие от `timeline()`: та умещает все события в ОДИН кадр, эта
    тянется в длину и читается прокруткой — событий может быть сколько
    угодно, и каждое приезжает крупно.

    events: [{"mark": "1963", "text": "...", "photo": путь, "hot": True}]
    kind:   "chrono" — метка это дата/год; "rank" — метка это место (№1, №2)
    Возвращает то же, что page_canvas: {"im", "anchors"} — дальше
    scroll_clip(..., direction="left").
    """
    from PIL import ImageOps
    n = max(len(events), 1)
    w = 264 + n * step + 420
    im = _page_bg(w, H)
    d = ImageDraw.Draw(im)
    # шапка держится на месте, пока лента едет под ней — иначе название
    # уезжает за край через две секунды и зритель теряет, что он смотрит
    sticky = None
    if kick or title:
        sticky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(scrim).rectangle((0, 0, 1320, 214), fill=(0, 0, 0, 170))
        sticky = Image.alpha_composite(sticky, scrim.filter(ImageFilter.GaussianBlur(40)))
        sd = ImageDraw.Draw(sticky)
        if kick:
            red_dot(sd, 150, 118, 7, None)
            track(sd, (180, 104), kick.upper(), _f(F_HEAD, 27), GOLD + (255,), 5)
        if title:
            sd.text((180, 150), title, font=_f(F_HEAD, 64), fill=WHITE + (255,))

    axis_y = 672
    d.rectangle((264, axis_y, w - 264, axis_y + 2), fill=(58, 58, 62))
    f_mark = _f(F_HEAD, 72)
    f_txt = _f(MONO, 28)
    anchors = []
    x = 264 + step // 2 + 180          # зазор под закреплённую шапку
    for i, e in enumerate(events):
        anchors.append(max(0, x - W // 2))
        hot = e.get("hot")
        mark = str(e.get("mark") or e.get("date") or (f"№{i+1}" if kind == "rank" else ""))
        ph = e.get("photo")
        if ph:
            bw, bh = 452, 240
            ptop = 228                      # ниже закреплённой шапки, выше метки
            try:
                src = ImageOps.fit(Image.open(ph).convert("RGB"), (bw, bh), Image.LANCZOS)
                im.paste(src, (x - bw // 2, ptop))
            except Exception:
                d.rectangle((x - bw // 2, ptop, x + bw // 2, ptop + bh), fill=(30, 30, 32))
            d.rectangle((x - bw // 2, ptop, x - bw // 2 + 5, ptop + bh), fill=RED)
        # метка над осью
        mw = track_w(mark, f_mark, 3)
        track(d, (x - mw / 2, axis_y - 214), mark, f_mark,
              (WHITE if hot else (206, 206, 206)), 3)
        # засечка
        if hot:
            glow = Image.new("RGBA", (w, H), (0, 0, 0, 0))
            ImageDraw.Draw(glow).rectangle((x - 10, axis_y - 54, x + 10, axis_y + 56),
                                           fill=(214, 46, 46, 150))
            im = Image.alpha_composite(im.convert("RGBA"),
                                       glow.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
            d = ImageDraw.Draw(im)
        d.rectangle((x - 5, axis_y - 42, x + 5, axis_y + 44), fill=(RED if hot else (205, 205, 205)))
        # подпись под осью
        rows, cur = [], ""
        for word in str(e.get("text", "")).split(" "):
            probe = (cur + " " + word).strip()
            if f_txt.getlength(probe) > step - 90 and cur:
                rows.append(cur); cur = word
            else:
                cur = probe
        if cur:
            rows.append(cur)
        for r, row in enumerate(rows[:4]):
            rw = track_w(row, f_txt, 1)
            track(d, (x - rw / 2, axis_y + 86 + r * 42), row, f_txt,
                  (226, 226, 226) if hot else (176, 176, 176), 1)
        x += step
    return {"im": im, "anchors": anchors, "watermark": watermark, "sticky": sticky}


# ── ЦИТАТА С ЖЁЛТЫМ МАРКЕРОМ (21.10.2026, просьба пользователя) ──────────
# В `quote()` акцент приходит КРАСНЫМ СЛОВОМ. Здесь ключевая фраза
# подсвечена мазком маркера: жёлтая полоса с неровными краями
# прорисовывается слева направо, текст поверх становится тёмным — как
# провели маркером по бумаге. Нажим к концу мазка слабеет, иначе читается
# как прямоугольная плашка, а не как след маркера.
MARKER = (255, 206, 26)          # жёлтый маркер
ON_MARKER = (22, 20, 16)         # текст поверх маркера — почти чёрный


def _stroke(size, box, seed, grow=1.0):
    """Мазок маркера: полоса с неровным верхом и низом, хвост сходит на нет."""
    w, h = size
    x0, y0, x1, y1 = box
    x1 = x0 + (x1 - x0) * max(0.0, min(1.0, grow))
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, math.tau) for _ in range(4)]
    hh = (y1 - y0)
    for x in range(int(x0), int(x1)):
        u = (x - x0) / max(1.0, (x1 - x0))
        top = y0 + hh * 0.07 * math.sin(u * math.tau * 2.3 + ph[0]) + hh * 0.04 * math.sin(u * math.tau * 7.1 + ph[1])
        bot = y1 + hh * 0.06 * math.sin(u * math.tau * 1.7 + ph[2]) + hh * 0.03 * math.sin(u * math.tau * 9.3 + ph[3])
        # нажим: к концу мазка маркер чуть слабее
        fade = 255 if u < 0.88 else int(255 * (1 - (u - 0.88) / 0.12) ** 0.6)
        d.line([(x, top), (x, bot)], fill=max(0, fade))
    return m.filter(ImageFilter.GaussianBlur(1.6))


def quote_marker(out=None, text="", author="", source="", watermark="ДИПЛОМАТИЯ СИЛЫ",
                 accent=None, t=None, sfx=None):
    im = canvas()
    f = _f(F_HEAD, 70)
    a0, dx0 = _rv(t, 0.05)
    _ev(sfx, 0.05, "quote")
    im = _put(im, lambda d: d.text((MARGIN_L - 26, 318), "««",
                                      font=_f(F_HEAD, 128), fill=RED), a0, dx0)

    words, lines, cur = text.split(" "), [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if f.getlength(probe) > 1340 and cur:
            lines.append(cur); cur = w
        else:
            cur = probe
    lines.append(cur)

    y = 440
    for i, ln in enumerate(lines):
        at = 0.2 + i * 0.17
        av, dxv = _rv(t, at)
        if av <= 0:
            y += 92
            continue
        _ev(sfx, at, "label")
        if accent and accent in ln:
            k = ln.index(accent)
            pre, post = ln[:k], ln[k + len(accent):]
            xs = MARGIN_L + f.getlength(pre)
            wd = f.getlength(accent)
            # мазок прорисовывается за 0.45 с после прихода строки
            grow = 1.0 if t is None else max(0.0, min(1.0, (t - at - 0.1) / 0.45))
            if grow > 0:
                box = (xs - 12, y + 14, xs + wd + 14, y + 78)
                m = _stroke((W, H), box, seed=i * 7 + 3, grow=grow)
                paint = Image.new("RGB", (W, H), MARKER)
                im = Image.composite(paint, im, m.point(lambda v: int(v * 0.92)))
            tcol = ON_MARKER if grow > 0.25 else WHITE
            im = _put(im, lambda d, y=y, pre=pre, post=post, tcol=tcol:
                         (d.text((MARGIN_L, y), pre, font=f, fill=WHITE),
                          d.text((MARGIN_L + f.getlength(pre), y), accent, font=f, fill=tcol),
                          d.text((MARGIN_L + f.getlength(pre + accent), y), post, font=f, fill=WHITE)),
                         av, dxv)
        else:
            im = _put(im, lambda d, y=y, ln=ln: d.text((MARGIN_L, y), ln, font=f, fill=WHITE),
                         av, dxv)
        y += 92

    if author:
        aa, dxa = _rv(t, 0.2 + len(lines) * 0.17 + 0.12)
        im = _put(im, lambda d, y=y: d.text((MARGIN_L, y + 30), "— " + author,
                                               font=_f(MONO, 30), fill=GOLD), aa, dxa)
    d = ImageDraw.Draw(im)
    footer(d, source, watermark)
    if out:
        im.save(out, quality=94); return out
    return im


