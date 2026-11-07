#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""НАДПИСИ НА ПРЕВЬЮ: ДВЕ ПОЛОСЫ ПО ГАММЕ КАНАЛА (07.11.2026).

    python3 prevyu_text.py <превью.png> --top ЭКСТРЕННО --bottom "КИЕВ ОБРЕЧЕН"
    python3 prevyu_text.py <папка темы> --all --top … --bottom …

Его последний ручной шаг: выбрав картинку, он просил модель добавить две
надписи — сверху и снизу, на всю ширину, заглавными, в гамме своего
канала.

ПОЧЕМУ КОДОМ, А НЕ МОДЕЛЬЮ. Полосы с текстом — это геометрия, а не
творчество: точный цвет (#DF0302 обязан быть ровно таким), точная ширина,
одинаковый результат на всех пяти вариантах. Модель каждый раз рисует
чуть иначе и «придумывает своё», чего он прямо запрещает. Здесь же это
доли секунды и ноль расхождений.

ГАММЫ ЗАКРЕПЛЕНЫ ЗА КАНАЛАМИ ЕГО СЛОВОМ:
  5 МИНУТ  — сверху ЧЁРНЫЙ по ЖЁЛТОМУ, снизу БЕЛЫЙ по ЧЁРНОМУ;
  ПЛАНЕТА  — сверху БЕЛЫЙ по #DF0302, снизу ЧЁРНЫЙ по #FDFCFC.
Канал берётся ИЗ ПУТИ, как и всё остальное в сборщике.
"""
import argparse
import glob
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
# ШРИФТ ПО ЕГО ОБРАЗЦУ (07.11): широкий жирный гротеск, буквы во всю
# высоту полосы и почти во всю ширину кадра. Montserrat ближе к образцу,
# чем узкий Oswald; если строка длинная и не влезает — берём Oswald, он
# уже и вмещает больше, но кегль остаётся крупным.
# ARIAL BLACK — ТОТ ЖЕ ШРИФТ, ЧТО НА ЕГО ОБРАЗЦЕ (07.11, проверено
# сравнением четырёх жирных на кириллице). Широкий, очень плотный, с
# полной кириллицей.
# ВАЖНО: `Montserrat-Bold.ttf` в нашем наборе НЕ ЖИРНЫЙ — на кириллице он
# рисуется тонким волоском. Полчаса ушло на то, чтобы понять, что дело не
# в коде и не в обводке, а в самом файле шрифта. Проверять начертание
# глазами, а не по имени файла.
FONT = os.path.join(FONTS, "ArialBlack.ttf")
FONT_NARROW = os.path.join(FONTS, "Oswald-Bold.ttf")

# (цвет текста сверху, фон сверху, цвет текста снизу, фон снизу)
GAMMA = {
    "5 МИНУТ": ((0, 0, 0), (255, 221, 0), (255, 255, 255), (0, 0, 0)),
    "ПЛАНЕТА": ((255, 255, 255), (223, 3, 2), (0, 0, 0), (253, 252, 252)),
}
DEFAULT = GAMMA["5 МИНУТ"]


def theme_name(folder):
    """Имя ролика: берём от озвучки или текста, без расширения. Папка
    темы называется «3-Ультиматум Путина», а ролик — «Ультиматум Путина
    5 минут»: он ищет глазами именно второе."""
    best = ""
    for ext in (".mp3", ".wav", ".m4a", ".txt"):
        c = [n for n in os.listdir(folder) if n.lower().endswith(ext)
             and not any(s in n.upper() for s in
                         ("ЗАДАНИЕ", "БРИФ", "ОТВЕТ", "УПАКОВКА", "ГЕОРАДАР"))]
        if c:
            best = max(c, key=lambda n: os.path.getsize(os.path.join(folder, n)))
            break
    if not best:
        return os.path.basename(folder)
    return os.path.splitext(best)[0]


def channel_of(path):
    parts = [p.strip().upper() for p in os.path.abspath(path).split(os.sep)]
    for name in GAMMA:
        if name in parts:
            return name
    for name in ("ОЛЬКА НОВОСТИ", "ОЛЬКА", "ДИПЛОМАТИЯ СИЛЫ"):
        if name in parts:
            return name
    return ""


def fit_font(draw, text, box_w, max_h, path=FONT):
    """Подобрать кегль так, чтобы строка ЗАНЯЛА ВСЮ ШИРИНУ (его требование
    «на всю ширину изображения»), но не вылезла по высоте полосы."""
    lo, hi, best = 10, max_h * 2, None
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            f = ImageFont.truetype(path, mid)
        except OSError:
            return ImageFont.load_default(), (0, 0, box_w, max_h)
        box = draw.textbbox((0, 0), text, font=f)
        w, h = box[2] - box[0], box[3] - box[1]
        if w <= box_w and h <= max_h:
            best, lo = (f, box), mid + 1
        else:
            hi = mid - 1
    if best is None:
        best = (ImageFont.truetype(path, 12), (0, 0, 10, 10))
    return best


def to_square(im):
    """Горизонтальный кадр → КВАДРАТ 1:1, НЕ ОБРЕЗАЯ (07.11, его образец).

    На образце кадр не подрезан по бокам, а достроен сверху и снизу:
    видно больше интерьера, лица на месте. Делаем так же — ширина
    остаётся, высота дотягивается до неё зеркальным продолжением
    собственных краёв с лёгким размытием. На интерьере и толпе шов не
    виден, а лица и композиция не страдают вовсе.
    """
    from PIL import ImageFilter
    W, H = im.size
    if H >= W:
        return im
    need = W - H
    top_h = need // 2
    bot_h = need - top_h
    # ПОДЛОЖКА — РАСТЯНУТЫЙ И СИЛЬНО РАЗМЫТЫЙ ВЕСЬ КАДР, а не отражение
    # краёв: зеркало повторяет узнаваемые детали (на первой пробе сверху
    # всплыла отражённая голова), и глаз это ловит. Размытая подложка
    # читается как продолжение сцены по цвету и свету, деталей не дублирует.
    # Поверх неё кладётся сам кадр в натуральную величину — он не режется
    # и не масштабируется, лица остаются как были.
    bg = im.resize((W, W), Image.LANCZOS).filter(ImageFilter.GaussianBlur(34))
    out = Image.new("RGB", (W, W))
    out.paste(bg, (0, 0))
    out.paste(im, (0, top_h))
    return out


def put(src, dst, top, bottom, gamma, band=0.16, pad=0.96, square=False):
    """Полоса 16% высоты, текст на 96% ширины — по его образцу 07.11:
    «буквы должны быть большие, все заглавными обязательно, контрастными»."""
    im = Image.open(src).convert("RGB")
    if square:
        im = to_square(im)
    W, H = im.size
    bh = int(H * band)
    d = ImageDraw.Draw(im)
    t_col, t_bg, b_col, b_bg = gamma

    for text, y0, col, bg in ((top, 0, t_col, t_bg),
                              (bottom, H - bh, b_col, b_bg)):
        if not text:
            continue
        d.rectangle((0, y0, W, y0 + bh), fill=bg)
        # ШРИФТ ВСЕГДА ОДИН (07.11, его слово: «и шрифт точно такой же,
        # вообще ничего не меняя, чтобы было один в один»). Прежняя версия
        # переключалась на узкий Oswald, когда тот давал кегль крупнее, — и
        # нижняя короткая строка выходила другим шрифтом, тоньше верхней.
        # Одна надпись одним шрифтом, вторая другим — это и читалось как
        # брак. Не влезает — уменьшаем кегль, но шрифт не меняем.
        f, box = fit_font(d, text, int(W * pad), int(bh * 0.92), FONT)
        w, h = box[2] - box[0], box[3] - box[1]
        # БЕЗ ОБВОДКИ (07.11, первая проба): обводка цветом фона визуально
        # СЪЕДАЕТ букву — белый текст на чёрной полосе стал тонким и
        # блёклым, хотя на его образце он жирный и плотный. Контраст даёт
        # сама полоса, обводка здесь лишняя.
        d.text(((W - w) / 2 - box[0], y0 + (bh - h) / 2 - box[1]),
               text, font=f, fill=col)
    im.save(dst, quality=95)
    return im.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="файл превью или папка темы")
    ap.add_argument("--top", default="", help="надпись сверху")
    ap.add_argument("--bottom", default="", help="надпись снизу")
    ap.add_argument("--all", action="store_true",
                    help="обработать все ПРЕВЬЮ-*.png в папке")
    ap.add_argument("--square", action="store_true",
                    help="сделать квадратным 1:1, достроив кадр по вертикали")
    ap.add_argument("--channel", help="канал вручную, если не читается из пути")
    a = ap.parse_args()

    top = (a.top or "").upper()
    bottom = (a.bottom or "").upper()
    if not top and not bottom:
        sys.exit("нужна хотя бы одна надпись: --top и/или --bottom")

    ch = (a.channel or channel_of(a.target) or "").upper()
    gamma = GAMMA.get(ch, DEFAULT)
    if ch not in GAMMA:
        print("канал «%s» своей гаммы не имеет — беру гамму «5 МИНУТ»"
              % (ch or "не читается из пути"))

    if a.all or os.path.isdir(a.target):
        # ВАРИАНТЫ ЛЕЖАТ В ПОДПАПКЕ, ГОТОВОЕ — В КОРНЕ ТЕМЫ (07.11).
        vdir = os.path.join(a.target, "превью-варианты")
        root = vdir if os.path.isdir(vdir) else a.target
        files = sorted(glob.glob(os.path.join(root, "ПРЕВЬЮ-*.png")))
        files = [f for f in files if "ГОТОВО" not in f]
    else:
        files = [a.target]
    if not files:
        sys.exit("нечего обрабатывать: %s" % a.target)

    print("канал %s · надписи: «%s» / «%s»" % (ch or "—", top, bottom))
    for f in files:
        # готовое кладём В КОРЕНЬ ТЕМЫ, рядом с озвучкой, и НАЗЫВАЕМ ПО
        # НАЗВАНИЮ РОЛИКА (07.11, его слово: «название превью делай по
        # названию темы, по названию ролика»). Имя берём от озвучки — это
        # и есть имя ролика, которое он потом ищет глазами.
        base = os.path.dirname(f)
        if os.path.basename(base) == "превью-варианты":
            base = os.path.dirname(base)
        num = "".join(c for c in os.path.basename(f) if c.isdigit()) or "1"
        dst = os.path.join(base, "%s ПРЕВЬЮ-%s%s.png"
                           % (theme_name(base), num,
                              "-КВАДРАТ" if a.square else ""))
        size = put(f, dst, top, bottom, gamma, square=a.square)
        print("  ✓ %s  %dx%d" % (os.path.basename(dst), size[0], size[1]))
    print("готово: %d шт." % len(files))


if __name__ == "__main__":
    main()
