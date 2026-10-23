# -*- coding: utf-8 -*-
"""ПОСМОТРЕТЬ СПОРНУЮ ПЛИТКУ, НЕ ТАЩА В КОНТЕКСТ ПОЛНЫЙ КАДР.

Замер 2026-10-23: за день в субагентов ушло 1190 изображений (141 МБ), один
проверяющий прочитал 222 полных кадра за 112 шагов — и каждый следующий шаг
перечитывал их все. Это 82% объёма дня. При этом качество от полных кадров
не выросло: крупный логотип во всю ширину прошёл мимо трёх проверяющих, а
нашла его вкладка на листе.

Поэтому порядок такой: субагент смотрит ЛИСТ, называет подозрительные сцены,
и только по ним зовётся этот инструмент.

    python3 zoom.py images/scene_041.jpg            # кадр ужат до 1000 px
    python3 zoom.py images/scene_041.jpg --corners  # 4 угла + центр, 1:1
    python3 zoom.py images 7 19 42                  # несколько сцен разом

`--corners` — для КЛЕЙМ: берёт четыре угла и центр в НАТУРАЛЬНОМ масштабе и
клеит в одну картинку. Мелкая подпись агентства, нечитаемая и на плитке, и в
ужатом кадре, здесь читается, а стоит одно изображение вместо полного кадра.
"""
import argparse
import glob
import os
import sys

OUT = "thumbs"


def _save(im, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    im.convert("RGB").save(path, "JPEG", quality=88)
    return path


def shrink(src, side=1000):
    from PIL import Image
    with Image.open(src) as im:
        w, h = im.size
        k = min(1.0, side / max(w, h))
        if k < 1.0:
            im = im.resize((int(w * k), int(h * k)), Image.LANCZOS)
        out = os.path.join(OUT, "zoom_" + os.path.basename(src))
        return _save(im, out), im.size, (w, h)


def corners(src, n=420):
    """Четыре угла и центр в масштабе 1:1 — там живут клейма и подписи."""
    from PIL import Image
    with Image.open(src) as im:
        W, H = im.size
        n = min(n, W // 2, H // 2) or 1
        spots = [(0, 0), (W - n, 0), (0, H - n), (W - n, H - n),
                 ((W - n) // 2, (H - n) // 2)]
        sheet = Image.new("RGB", (n * 3 + 16, n * 2 + 8), (24, 24, 28))
        pos = [(0, 0), (n + 8, 0), (0, n + 8), (n + 8, n + 8), (n * 2 + 16, n // 2)]
        for (x, y), (px, py) in zip(spots, pos):
            sheet.paste(im.crop((x, y, x + n, y + n)), (px, py))
        out = os.path.join(OUT, "corners_" + os.path.basename(src))
        return _save(sheet, out), sheet.size, (W, H)


def main():
    ap = argparse.ArgumentParser(description="дешёвый просмотр спорной плитки")
    ap.add_argument("target", help="файл кадра ИЛИ папка (тогда перечисли сцены)")
    ap.add_argument("ids", nargs="*", type=int, help="номера сцен, если дана папка")
    ap.add_argument("--corners", action="store_true", help="углы и центр 1:1 (клейма)")
    ap.add_argument("--side", type=int, default=1000, help="сторона при ужатии")
    a = ap.parse_args()

    files = []
    if os.path.isdir(a.target):
        for sid in a.ids:
            got = [f for f in glob.glob(os.path.join(a.target, "scene_%03d.*" % sid))
                   if not f.lower().endswith((".json", ".mp4", ".mov", ".webm"))]
            files += got[:1] or []
        if not a.ids:
            sys.exit("дана папка — перечисли номера сцен: zoom.py images 7 19 42")
    else:
        files = [a.target]
    if not files:
        sys.exit("нечего смотреть")

    for f in files:
        if not os.path.isfile(f):
            print(f"  нет файла: {f}")
            continue
        out, size, orig = (corners(f) if a.corners else shrink(f, a.side))
        kind = "углы+центр 1:1" if a.corners else "ужат"
        print(f"  {os.path.basename(f)}: {orig[0]}x{orig[1]} → {kind} {size[0]}x{size[1]}")
        print(f"    {out}")
    print("\nЧитай ЭТИ файлы, а не исходные кадры: полный кадр остаётся в "
          "контексте до конца работы агента и перечитывается на каждом шаге.")


if __name__ == "__main__":
    main()
