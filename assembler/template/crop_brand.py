#!/usr/bin/env python3
"""СРЕЗАТЬ ЧУЖОЙ ЗНАК С КРАЯ КАДРА (решение пользователя 30.10).

    python3 crop_brand.py <файл.mp4|файл.jpg> [--side left|right|top|bottom]
                          [--pct 15] [--out <куда>] [--check <кадр.jpg>]

Зачем. Официальные каналы ведомств дают чистую картинку, но у телеканалов
(DW, Euronews и т.п.) в углу стоит логотип. Пользователь 30.10: «Просто
кадрирование сделать, чтобы вот этот знак водяной не попадал. А вокруг
заливка чтобы была — как горизонтальное видео мы делаем».

Что делает. Срезает полосу с той стороны, где знак, и всё. Кадр становится
уже 16:9 — и сборщик сам поставит его в РОДНОМ размере по центру, залив поля
размытой копией (та же дорожка, что у вертикальных и у узких фото).

РЕЖИМ «ТОЛЬКО СЕРЕДИНА» (--center, его слово 30.10 про Deutsche Welle):
«Оно не в центре кадра, как правило в начале — да, в центре, а потом по
видеоряду его нету в центре, оно где-то в углу прячется. А мы откадрируем
центр только возьмём, и всё». То есть у телеканала знак в центре стоит
на ЗАСТАВКЕ, а в самом сюжете уезжает в угол. Поэтому: `--skip` выбрасывает
заставку, `--center` срезает сразу все четыре края и оставляет серединную
часть — любой угловой знак уходит вместе с краем, сторону искать не надо.

ЧЕГО ОН НЕ ЛЕЧИТ: знак, который действительно стоит В СЕРЕДИНЕ самого
сюжета — микрофонный куб с логотипом у говорящего, титр по центру нижней
трети, субтитры во всю ширину. Это не край, срезать нечего.
"""
import argparse
import os
import subprocess
import sys

SIDES = ("left", "right", "top", "bottom")


def _wh(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                       capture_output=True, text=True, timeout=60)
    w, h = r.stdout.strip().split("x")[:2]
    return int(w), int(h)


def center_expr(w, h, pct):
    """Оставить середину: срезать `pct` процентов с КАЖДОГО края."""
    nw = (w - 2 * ((w * pct) // 100)) // 2 * 2
    nh = (h - 2 * ((h * pct) // 100)) // 2 * 2
    return f"crop={nw}:{nh}:{(w - nw) // 2}:{(h - nh) // 2}", (nw, nh)


def crop_expr(w, h, side, pct):
    cut_w = (w * pct) // 100 // 2 * 2
    cut_h = (h * pct) // 100 // 2 * 2
    if side == "left":
        return f"crop={w - cut_w}:{h}:{cut_w}:0", (w - cut_w, h)
    if side == "right":
        return f"crop={w - cut_w}:{h}:0:0", (w - cut_w, h)
    if side == "top":
        return f"crop={w}:{h - cut_h}:0:{cut_h}", (w, h - cut_h)
    return f"crop={w}:{h - cut_h}:0:0", (w, h - cut_h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--side", default="left", choices=SIDES,
                    help="с какой стороны стоит знак (по умолчанию левая)")
    ap.add_argument("--center", action="store_true",
                    help="взять только середину: срезать все четыре края сразу "
                         "(телеканалы — знак в любом углу уходит без поиска стороны)")
    ap.add_argument("--skip", type=float, default=0.0,
                    help="выбросить столько секунд с начала (заставка телеканала, "
                         "где знак стоит по центру); только для видео")
    ap.add_argument("--pct", type=int, default=15,
                    help="сколько процентов стороны срезать (по умолчанию 15)")
    ap.add_argument("--out", default="", help="куда писать; по умолчанию рядом, с суффиксом __cut")
    ap.add_argument("--check", default="", help="куда положить кадр для глаз")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        sys.exit("ОШИБКА: файла нет: " + a.src)
    if not 2 <= a.pct <= 40:
        sys.exit("ОШИБКА: --pct вне разумного (2-40)")

    w, h = _wh(a.src)
    if a.center:
        expr, (nw, nh) = center_expr(w, h, a.pct)
    else:
        expr, (nw, nh) = crop_expr(w, h, a.side, a.pct)
    root, ext = os.path.splitext(a.src)
    out = a.out or (root + "__cut" + ext)
    is_video = ext.lower() in (".mp4", ".mov", ".webm", ".mkv", ".m4v")

    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if a.skip > 0 and is_video:
        cmd += ["-ss", "%.2f" % a.skip]
    cmd += ["-i", a.src, "-vf", expr]
    if is_video:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-an"]
    else:
        cmd += ["-q:v", "2"]
    cmd.append(out)
    subprocess.run(cmd, check=True, timeout=900)

    if a.center:
        print("было %dx%d → стало %dx%d (взята середина, срезано %d%% с каждого "
              "края — все четыре угла ушли%s)"
              % (w, h, nw, nh, a.pct,
                 ", заставка %.1f с выброшена" % a.skip if a.skip > 0 and is_video else ""))
    else:
        print("было %dx%d → стало %dx%d (срезано %d%% с края: %s)"
              % (w, h, nw, nh, a.pct, a.side))
    print("соотношение %.2f — %s" % (
        nw / nh,
        "уже 16:9, сборщик поставит родным размером с размытой заливкой"
        if nw / nh < 1.76 else "то же 16:9 или шире, заливки не будет"))
    print(out)

    if a.check:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                        "-ss", "1" if is_video else "0", "-i", out,
                        "-frames:v", "1", "-q:v", "3", a.check], check=False, timeout=120)
        print("кадр для глаз: " + a.check)


if __name__ == "__main__":
    main()
