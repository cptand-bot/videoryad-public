#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЛИСТ НА ЗАМОЩЁННОЕ КЛЕЙМО АПСКЕЙЛЕРА (Magnific и родня).

    python3 wm_sheet.py <папка | файлы…> [--out wm.jpg] [--cols 4]

ЗАЧЕМ. Клеймо апскейлера — не угловой логотип, а полупрозрачная надпись,
ЗАМОЩЁННАЯ по всему кадру. На обычном контактном листе его не видно совсем:
контраст надписи к небу — единицы уровней из 255. Поймано 04.11 вкладкой
`usuario-af` в НАШЕЙ ЖЕ базе кадров (4 файла в двух папках), то есть часть
базы собрана через апскейлер.

ПОЧЕМУ ЛИСТ, А НЕ ПРОВЕРКА ЧИСЛОМ. Автоматику пробовали трижды и она не
отделяет: OCR и спектр отвергнуты ещё раньше, а 04.11 проверены ещё два
подхода на той же папке из десяти файлов — доля энергии в «текстовых»
частотах (помеченные 0,23 и 0,25 против чистых 0,35 и 0,26 — не отделяет)
и пик автокорреляции (помеченные 0,65 и 0,12 против чистого 0,27 — не
отделяет). Глазом же на вытянутом по контрасту ровном участке клеймо
читается мгновенно. Поэтому инструмент делает ровно одно: вытягивает те
участки, где клеймо видно, и складывает их в лист.

КАК СМОТРЕТЬ. На плитке листа ищешь ПОВТОРЯЮЩУЮСЯ по диагонали надпись
(«Magnific», «Phil and Garth .com», что угодно). Нашёл — файл в бан:
    python3 ~/.claude/skills/news-video/template/ban_file.py <файл>
Ровный шум и разводы — это не клеймо, а зерно и JPEG.
"""
import argparse
import glob
import os
import sys

BLOCK = 320


def _flattest(im, n=BLOCK):
    """Самый ровный квадрат кадра: там нет деталей и клеймо не маскируется."""
    import numpy as np
    a = np.asarray(im.convert("L"), dtype=np.float32)
    H, W = a.shape
    best, bv = (0, 0), 1e9
    for y in range(0, max(1, H - n), max(40, n // 4)):
        for x in range(0, max(1, W - n), max(40, n // 4)):
            b = a[y:y + n, x:x + n]
            if b.shape != (n, n):
                continue
            v = float(abs(b - b.mean()).mean())
            if v < bv:
                bv, best = v, (y, x)
    return best, bv


def tile_for(path):
    from PIL import Image, ImageFilter, ImageDraw, ImageOps
    im = Image.open(path).convert("RGB")
    w, h = im.size
    k = 1600.0 / max(w, h)
    if k < 1:
        im = im.resize((int(w * k), int(h * k)), Image.LANCZOS)
    (y, x), flat = _flattest(im)
    crop = im.crop((x, y, x + BLOCK, y + BLOCK)).convert("L")
    # высокие частоты = кадр минус сильно размытая копия; клеймо живёт тут
    hp = Image.fromarray(
        _hp(crop)).convert("L")
    hp = ImageOps.autocontrast(hp, cutoff=0.5)
    out = hp.convert("RGB")
    d = ImageDraw.Draw(out)
    name = os.path.basename(path)[:26]
    d.rectangle([0, 0, BLOCK, 22], fill=(0, 0, 0))
    # ШРИФТ БЕРЁМ СВОЙ: у PIL по умолчанию нет кириллицы, и подпись на листе
    # выходит квадратиками (поймано на первом же листе 04.11).
    d.text((4, 4), "%s  ровность %.1f" % (name, flat), fill=(255, 230, 60),
           font=_font())
    return out


def _font(size=15, _c={}):
    from PIL import ImageFont
    if "f" not in _c:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "fonts", "RobotoCondensed-Bold.ttf")
        try:
            _c["f"] = ImageFont.truetype(p, size)
        except Exception:
            _c["f"] = ImageFont.load_default()
    return _c["f"]


def _hp(gray):
    import numpy as np
    from PIL import ImageFilter
    a = np.asarray(gray, dtype=np.float32)
    b = np.asarray(gray.filter(ImageFilter.GaussianBlur(5)), dtype=np.float32)
    d = a - b
    d = d - d.min()
    m = d.max() or 1.0
    return (d * (255.0 / m)).astype("uint8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", default="wm.jpg")
    ap.add_argument("--cols", type=int, default=4)
    a = ap.parse_args()
    files = []
    for p in a.paths:
        if os.path.isdir(p):
            for e in ("jpg", "jpeg", "png", "webp"):
                files += sorted(glob.glob(os.path.join(p, "*." + e)))
        elif os.path.isfile(p):
            files.append(p)
    if not files:
        sys.exit("нечего смотреть: файлов не нашёл")
    from PIL import Image
    tiles = [tile_for(f) for f in files]
    cols = max(1, a.cols)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * BLOCK, rows * BLOCK), (0, 0, 0))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * BLOCK, (i // cols) * BLOCK))
    sheet.save(a.out, quality=92)
    print("лист на клеймо апскейлера: %d файлов → %s" % (len(files), a.out))
    print("смотри ПОВТОРЯЮЩУЮСЯ по диагонали надпись; нашёл — ban_file.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
