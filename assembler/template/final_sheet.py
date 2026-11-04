#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЛИСТ ПО ГОТОВОМУ MP4 — ПОСЛЕДНЕЕ СИТО ПЕРЕД СДАЧЕЙ.

    python3 final_sheet.py <готовый.mp4> [--scenes <ролик>.scenes.json]
                           [--every 48] [--out final_sheet] [--cols 4]

ЗАЧЕМ. 04.11 две вкладки поймали по готовому файлу то, что не увидел НИКТО:
карту НАТО во весь кадр на 700-й секунде (прошла ОБА захода внешнего агента,
стоя у него в списке «смотри в первую очередь»), детский забег, замощённое
клеймо апскейлера и ПЯТЬ сцен «чужой стороны» — российская бронетехника под
учения коалиции, истребители с красными звёздами под финский аэродром,
американский B-2 под авиацию Франции, советский пульт под европейское
командование.

ПОЧЕМУ ЭТОГО НЕ ВИДЯТ ОСТАЛЬНЫЕ СЛОИ:
  * линтер молчит — запрос ЗАКОННЫЙ («стратегическая авиация Франции»),
    брак прилетел в ВЫДАЧЕ;
  * контактный лист молчит — на плитке 200 px красные звёзды на килях,
    флаги на заднем плане и надписи карты не читаются вовсе;
  * внешний агент молчит — он смотрит по номерам, которые ему назвали, и
    замены между заходами в его поле зрения не попадают.
Остаётся один слой: кадры из ГОТОВОГО файла, полным размером.

СКОЛЬКО КАДРОВ. Шесть мало (замер `usuario-eb` 04.11): пять находок дал
только плотный шаг. Берём ОДИН КАДР НА 48 СЕКУНД — на 20-минутном ролике это
24 кадра и примерно минута работы.

ЧТО ИСКАТЬ, В ПОРЯДКЕ ВАЖНОСТИ:
  1. ПРИНАДЛЕЖНОСТЬ: чьи флаги, чьи звёзды, чья форма, чья техника, чьи
     номера и шильды. «Чужая сторона» — самый дорогой класс: сцена про
     Францию с российскими истребителями выглядит нормальной на плитке;
  2. КАРТА во весь кадр и КРУПНАЯ ЛАТИНИЦА;
  3. клейма и вшитые титры телеканалов, замощённые вотермарки;
  4. дети и детские площадки — запрет жёсткий;
  5. всплывашка не на лице, субтитры поверх всего, текст по-русски.

`-ss` ставится ДО `-i` — это перемотка, а не декодирование: 24 кадра с
20-минутного файла снимаются за секунды и процессор не трогают.
"""
import argparse
import json
import os
import subprocess
import sys

BLOCK_W = 640


def _dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _scene_at(scenes, t):
    """Номер сцены, попавшей на эту секунду (если дан scenes.json)."""
    acc = 0.0
    for s in scenes:
        d = float(s.get("duration_sec") or 0)
        if acc <= t < acc + d:
            return int(s.get("id", 0))
        acc += d
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--scenes", default="")
    ap.add_argument("--every", type=float, default=48.0,
                    help="секунд между кадрами (по умолчанию 48)")
    ap.add_argument("--out", default="final_sheet")
    ap.add_argument("--cols", type=int, default=4)
    a = ap.parse_args()
    if not os.path.isfile(a.video):
        sys.exit("нет файла: %s" % a.video)
    dur = _dur(a.video)
    if dur <= 0:
        sys.exit("не прочитать длительность — это точно видео?")

    scenes = []
    if a.scenes and os.path.isfile(a.scenes):
        try:
            d = json.load(open(a.scenes, encoding="utf-8"))
            scenes = d.get("scenes", d) if isinstance(d, dict) else d
        except (OSError, ValueError):
            scenes = []

    os.makedirs(a.out, exist_ok=True)
    times = []
    t = a.every / 2.0
    while t < dur:
        times.append(t)
        t += a.every
    from PIL import Image, ImageDraw, ImageFont
    try:
        fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fonts", "RobotoCondensed-Bold.ttf")
        font = ImageFont.truetype(fp, 20)
    except Exception:
        font = ImageFont.load_default()

    tiles = []
    for t in times:
        p = os.path.join(a.out, "f_%06d.jpg" % int(t))
        # -ss ДО -i: перемотка, а не декодирование
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t,
                            "-i", a.video, "-frames:v", "1",
                            "-vf", "scale=%d:-2" % BLOCK_W, p],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(p):
            continue
        im = Image.open(p).convert("RGB")
        d = ImageDraw.Draw(im)
        sid = _scene_at(scenes, t) if scenes else 0
        lab = "%02d:%02d" % (int(t) // 60, int(t) % 60)
        if sid:
            lab += "  сцена %d" % sid
        d.rectangle([0, 0, im.width, 26], fill=(0, 0, 0))
        d.text((6, 3), lab, fill=(255, 230, 60), font=font)
        tiles.append(im)

    if not tiles:
        sys.exit("не снялось ни одного кадра")
    cols = max(1, a.cols)
    rows = (len(tiles) + cols - 1) // cols
    w, h = tiles[0].size
    sheets = []
    per = cols * 3                      # по 3 ряда на лист, чтобы не мельчить
    for i in range(0, len(tiles), per):
        part = tiles[i:i + per]
        rr = (len(part) + cols - 1) // cols
        sh = Image.new("RGB", (cols * w, rr * h), (0, 0, 0))
        for k, im in enumerate(part):
            sh.paste(im, ((k % cols) * w, (k // cols) * h))
        op = "%s_%d.jpg" % (a.out, i // per + 1)
        sh.save(op, quality=88)
        sheets.append(op)

    print("кадров снято: %d (шаг %.0f с, длина %.0f с)"
          % (len(tiles), a.every, dur))
    print("листов: %s" % ", ".join(sheets))
    print("смотри В ПОРЯДКЕ ВАЖНОСТИ: 1) принадлежность — чьи флаги, звёзды, "
          "форма, техника; 2) карта во весь кадр и латиница; 3) клейма и "
          "титры; 4) дети; 5) всплывашка не на лице, субтитры поверх всего.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
