#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""НАДПИСЬ ИЗ-ПОД МАСКИ — ЕДИНСТВЕННЫЙ ПРИЁМ, ПРИНЯТЫЙ ИЗ ВИТРИНЫ 07.11.

Надпись выезжает из-под маски слева направо, по краю маски едет полоса.
Два вида, оба его словом приняты в тот же день:
  БЕЗ ЗАЛИВКИ — заголовок белый засечный, подзаголовок цветом канала,
                под текстом мягкая тень;
  С ЗАЛИВКОЙ  — текст на плашке градиентом в гамме канала, текст тёмный,
                полоса по краю маски белая (`plate=True`).

Его слово 07.11: «пускай будет у нас n-текст с заливкой, попробуем
применить на канал ПЛАНЕТА. Будет примерно собираться так же, как и на
канал 5 МИНУТ» — то есть цвет приходит ПО КАНАЛУ, сам, как у всех наших
элементов.

ПОЧЕМУ ЖИВЁТ В `template/`, А НЕ В `fullcycle/`: в облако основной сборки
уезжают ТОЛЬКО `template/` и `cloud/` (предохранитель `sync_assembler.sh`).
Надпись кладётся на клип в шаге `overlay`, то есть внутри основной сборки —
значит рисовалка обязана быть здесь, иначе на раннере её просто нет.

РАЗМЕР. Он смотрел образец и сказал «крупнее, наверное, раза в два» —
поэтому `scale` по умолчанию 2.0 (кегли 76 и 40, высота 172 px на кадре
1920x1080). Ширина МЕРЯЕТСЯ ШРИФТОМ, а не прикидывается по числу букв.

    python3 nadpis_maska.py --demo <фон.jpg> <выход.mp4> \
            --head ПЕРЕГОВОРЫ --sub "условие названо" \
            --channel ПЛАНЕТА [--plate] [--scale 2]
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ЦВЕТ ПО КАНАЛУ. Таблица повторяет `fullcycle/style_cards.CHANNEL_ACCENT`
# один в один — и это осознанный дубль: `fullcycle/` в облако основной
# сборки не уезжает, импортировать оттуда на раннере нечего. Меняешь цвет
# канала — меняй В ОБОИХ местах.
CHANNEL_ACCENT = {
    "ПЛАНЕТА":                    (74, 144, 226),    # сталь
    "ОЛЬКА":                      (168, 130, 232),   # сирень
    "5 МИНУТ":                    (224, 179, 58),    # золото
    "ДИПЛОМАТИЯ СИЛЫ":            (72, 187, 120),    # зелень
    "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО": (6, 199, 199),     # бирюза
}
RED = (185, 37, 38)

DEJAVU = "/usr/share/fonts/truetype/dejavu/"
F_HEAD = DEJAVU + "DejaVuSerif-Bold.ttf"     # засечный жирный — как в образце
F_SUB = DEJAVU + "DejaVuSans.ttf"

_FC = {}


# ЗАЛИВКА ПЛАШКИ — ЗОЛОТАЯ НА ВСЕХ КАНАЛАХ (08.11, он опознал приём по
# картинке: «да, это оно и тот, оно как бы выезжает»). Исходник приёма —
# «Полнолуние», `tekst.py`, функция `plashka`: ЗОЛОТОЙ градиент, тёмный
# засечный текст (#17130f), подзаголовок темнее фона (#3a2a12), скруглённые
# углы и светлая полоса по краю маски. Моя новостная версия красила плашку
# по каналу (ПЛАНЕТА — сталь, белый текст) и поэтому читалась как ЧУЖОЙ
# формат: он сказал «не он» и велел снять надписи вовсе.
# Поэтому: вид приёма ОДИН на все каналы, цвет канала остаётся в полосе по
# краю маски и в варианте БЕЗ заливки.
ПЛАШКА_ВЕРХ = (236, 196, 78)       # золото, светлый край градиента
ПЛАШКА_НИЗ = (198, 152, 40)        # золото, тёмный край
ПЛАШКА_ТЕКСТ = (23, 19, 15)        # тёмный засечный заголовок
ПЛАШКА_ПОДЗАГ = (58, 42, 18)       # подзаголовок


def accent(channel=None):
    key = (channel or "").strip().upper()
    for name, col in CHANNEL_ACCENT.items():
        if key and (key.startswith(name) or name.startswith(key)):
            return col
    return RED


def channel_of(path):
    """Канал из ПУТИ — как везде в сборщике, отдельно его не спрашиваем."""
    parts = [p.strip().upper() for p in os.path.abspath(str(path)).split(os.sep)]
    for p in parts:
        for name in CHANNEL_ACCENT:
            if p == name or p.startswith(name):
                return name
    return ""


def _f(path, size):
    k = (path, int(size))
    if k not in _FC:
        try:
            _FC[k] = ImageFont.truetype(path, int(size))
        except OSError:
            _FC[k] = ImageFont.load_default()
    return _FC[k]


def _wid(text, path, size, ls=0.0):
    """Ширина строки ШРИФТОМ, а не прикидкой по числу букв."""
    if not text:
        return 0
    return _f(path, size).getlength(str(text)) + ls * max(0, len(str(text)))


def _ease_out(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def _ink(col):
    """Текст на плашке: тёмный на светлой, белый на тёмной."""
    lum = 0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2]
    return ((21, 18, 14), (58, 47, 28)) if lum > 140 else \
           ((255, 255, 255), (230, 230, 234))


def box_size(head, sub="", scale=2.0):
    """Размер надписи целиком — чтобы вызывающий знал, куда её класть."""
    fs_h, fs_s = int(38 * scale), int(20 * scale)
    pad = int(26 * scale)
    w = max(_wid(head, F_HEAD, fs_h, scale) * 1.02,
            _wid(sub, F_SUB, fs_s, scale) * 1.06 if sub else 0) + pad * 2
    h = int((86 if sub else 62) * scale)
    return int(w), h


def frame(head, sub="", p=1.0, scale=2.0, channel=None, plate=False):
    """Один кадр анимации как RGBA-картинка размером с надпись.
    `p` — доля раскрытия от 0 до 1 (уже сглаженная)."""
    fs_h, fs_s = int(38 * scale), int(20 * scale)
    pad = int(26 * scale)
    W, H = box_size(head, sub, scale)
    col = accent(channel)

    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if plate:
        # ЗОЛОТО И ТЁМНЫЙ ТЕКСТ — КАК В ИСХОДНИКЕ ПРИЁМА (08.11). Цвет канала
        # сюда больше не идёт: он опознал вид по картинке, а стальная плашка
        # с белым текстом читалась как другой формат.
        d = ImageDraw.Draw(im)
        for x in range(W):
            k = x / max(1, W - 1)
            d.line([(x, 0), (x, H)],
                   fill=tuple(int(ПЛАШКА_ВЕРХ[i] +
                                  (ПЛАШКА_НИЗ[i] - ПЛАШКА_ВЕРХ[i]) * k)
                              for i in range(3)) + (255,))
        # скруглённые углы, как в оригинале (rx=6 при кегле 38)
        _r = max(4, int(6 * scale))
        _m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(_m).rounded_rectangle((0, 0, W - 1, H - 1), radius=_r, fill=255)
        im.putalpha(_m)
        d = ImageDraw.Draw(im)
        ink, ink_sub = ПЛАШКА_ТЕКСТ, ПЛАШКА_ПОДЗАГ
    else:
        ink, ink_sub = (255, 255, 255), col
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.text((pad, int(fs_h * 0.22)), str(head), font=_f(F_HEAD, fs_h),
                fill=(0, 0, 0, 205))
        if sub:
            sd.text((pad, H - fs_s * 1.75), str(sub), font=_f(F_SUB, fs_s),
                    fill=(0, 0, 0, 190))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(fs_h * 0.07)))

    d = ImageDraw.Draw(im)
    d.text((pad, int(fs_h * 0.22)), str(head), font=_f(F_HEAD, fs_h), fill=ink)
    if sub:
        d.text((pad, H - fs_s * 1.75), str(sub), font=_f(F_SUB, fs_s),
               fill=ink_sub)

    if p >= 1:
        return im
    cut = int(W * max(0.0, p))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if cut > 0:
        out.paste(im.crop((0, 0, cut, H)), (0, 0))
        g = ImageDraw.Draw(out)
        g.rectangle((cut - int(7 * scale), 0, cut - 1, H),
                    fill=(255, 255, 255, 217) if plate else col + (235,))
    return out


def sequence(outdir, head, sub="", scale=2.0, channel=None, dur=0.9,
             fps=30, plate=False):
    """PNG-секвенция анимации. Возвращает (кадров, ширина, высота).
    Кладётся на клип обычным overlay с `eof_action=repeat` — последний
    кадр держится до конца сцены, поэтому секвенция короткая."""
    os.makedirs(outdir, exist_ok=True)
    n = max(2, int(dur * fps))
    W, H = box_size(head, sub, scale)
    for i in range(n):
        frame(head, sub, _ease_out((i + 1) / n), scale, channel, plate).save(
            os.path.join(outdir, "pl_%03d.png" % i))
    return n, W, H


def demo(bg_path, out_mp4, head, sub="", scale=2.0, channel=None,
         seconds=4.0, fps=30, x=None, y=None, plate=False):
    """Клип для показа: надпись раскрывается поверх живого кадра."""
    import subprocess
    import tempfile
    tmp = tempfile.mkdtemp(prefix="nadpis-")
    n, W, H = sequence(tmp, head, sub, scale, channel, fps=fps, plate=plate)
    bg = Image.open(bg_path).convert("RGB")
    if bg.size != (1920, 1080):
        bg = bg.resize((1920, 1080), Image.LANCZOS)
    base = os.path.join(tmp, "bg.png")
    bg.save(base)
    px = int(1920 * 0.075) if x is None else x
    py = int(1080 * 0.62) if y is None else y
    cmd = ["ffmpeg", "-y", "-threads", "2", "-loop", "1", "-framerate",
           str(fps), "-t", str(seconds), "-i", base,
           "-framerate", str(fps), "-i", os.path.join(tmp, "pl_%03d.png"),
           "-filter_complex",
           "[0:v][1:v]overlay=%d:%d:eof_action=repeat,format=yuv420p"
           % (px, py),
           "-t", str(seconds), "-r", str(fps), "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "20", out_mp4]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    fin = frame(head, sub, 1.0, scale, channel, plate)
    still = bg.copy()
    still.paste(fin, (px, py), fin)
    jpg = os.path.splitext(out_mp4)[0] + ".jpg"
    still.save(jpg, quality=92)
    return W, H, jpg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", metavar="ФОН", required=True)
    ap.add_argument("out")
    ap.add_argument("--head", required=True)
    ap.add_argument("--sub", default="")
    ap.add_argument("--channel", default="")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--plate", action="store_true",
                    help="с заливкой (по умолчанию надпись без подложки)")
    a = ap.parse_args()
    ch = a.channel or channel_of(a.out)
    W, H, jpg = demo(a.demo, a.out, a.head.upper(), a.sub, a.scale,
                     ch or None, plate=a.plate)
    print("надпись %dx%d · канал %s · масштаб %.1f%s"
          % (W, H, ch or "—", a.scale, " · с заливкой" if a.plate else ""))
    print("обложка: %s" % jpg)


if __name__ == "__main__":
    main()
