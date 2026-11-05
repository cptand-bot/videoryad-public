#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЛИСТ ЭФФЕКТОВ ИЗ ГОТОВОГО ВИДЕО — ГЛАЗА НА ПЕРЕХОДЫ, КОТОРЫХ У НАС НЕ БЫЛО.

    python3 fx_sheet.py <ролик>.scenes.json <готовое.mp4> <куда.jpg>

Зачем (05.11, улов `usuario-35`): новый вид эффекта вкладка проверить НЕ МОЖЕТ.
Контактные листы строятся из КАДРОВ СЦЕН (папка `images`), то есть из того, что
приехало с фетча, — самого перехода там нет по определению. Вытащить кадр из
собранного mp4 на машине пользователя запрещено прямо («ни рендер, ни пробные
прогоны, ни извлечение кадров»), а из облака кадры готового видео не приходили
вовсе. Получалось, что эффект впервые видит ПОЛЬЗОВАТЕЛЬ — и замечание про
«вижу только радар» стоило ровно этого.

Что делает: по сценам с ключом `fx` берёт ТРИ кадра на каждый эффект — вход
(+0,15 с от начала сцены), середина (+0,5 с) и выход (+1,0 с), — и клеит их в
один лист с подписями «сцена N · вид · секунда». Лист едет в релиз вместе с
контактными листами, и вкладка смотрит переход ГЛАЗАМИ до показа пользователю.

Считается в облаке, на машине пользователя не запускается.
"""
import json
import os
import subprocess
import sys


def _starts(scenes):
    """Секунда начала каждой сцены: берём start_sec, иначе копим длительности."""
    out, acc = {}, 0.0
    for s in scenes:
        sid = int(s.get("id", 0))
        st = s.get("start_sec")
        out[sid] = float(st) if st is not None else acc
        acc = out[sid] + float(s.get("duration_sec") or 0)
    return out


def _grab(ffmpeg, src, sec, dst):
    r = subprocess.run([ffmpeg, "-y", "-ss", "%.2f" % max(0.0, sec), "-i", src,
                        "-frames:v", "1", "-q:v", "3", dst],
                       capture_output=True)
    return r.returncode == 0 and os.path.isfile(dst)


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    scenes_path, video, out = sys.argv[1], sys.argv[2], sys.argv[3]
    ffmpeg = os.environ.get("FFMPEG_BIN", "ffmpeg")
    try:
        data = json.load(open(scenes_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit("не прочитать сцены: %s" % e)
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not scenes or not os.path.isfile(video):
        sys.exit("нет сцен или нет готового видео: %s" % video)

    starts = _starts(scenes)
    fx = [(int(s.get("id", 0)), str(s.get("fx", "")).strip().lower())
          for s in scenes if str(s.get("fx", "")).strip()]
    if not fx:
        print("эффектов в ролике нет — лист не нужен")
        return 0

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("нет PIL — лист не собрать")

    tmp = out + ".frames"
    os.makedirs(tmp, exist_ok=True)
    cells = []
    for sid, kind in fx:
        for off in (0.15, 0.5, 1.0):
            sec = starts.get(sid, 0.0) + off
            p = os.path.join(tmp, "fx_%03d_%03d.jpg" % (sid, int(off * 100)))
            if _grab(ffmpeg, video, sec, p):
                cells.append((p, "сцена %d · %s · %.1f с" % (sid, kind, sec)))
    if not cells:
        sys.exit("ни одного кадра вытащить не удалось")

    COLS, CW, CH, PAD, CAP = 3, 480, 270, 8, 22
    rows = (len(cells) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * (CW + PAD) + PAD,
                              rows * (CH + CAP + PAD) + PAD), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    for i, (p, cap) in enumerate(cells):
        x = PAD + (i % COLS) * (CW + PAD)
        y = PAD + (i // COLS) * (CH + CAP + PAD)
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail((CW, CH))
                sheet.paste(im, (x + (CW - im.width) // 2,
                                 y + (CH - im.height) // 2))
        except OSError:
            continue
        d.text((x + 2, y + CH + 4), cap, fill=(230, 230, 235))
    sheet.save(out, "JPEG", quality=88)
    for p, _ in cells:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(tmp)
    except OSError:
        pass
    print("лист эффектов: %s (%d кадров, эффектов %d)"
          % (out, len(cells), len(fx)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
