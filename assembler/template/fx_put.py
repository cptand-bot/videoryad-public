#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ДВЕРЬ ЭФФЕКТОВ: поставить сцене эффект из его образца.

    python3 fx_put.py <ролик>.scenes.json <sid> <видео-врезка.mp4>   # врезка
    python3 fx_put.py <ролик>.scenes.json <sid> --kind mosaic        # переход
    python3 fx_put.py <ролик>.scenes.json <sid> --off                # снять

ЧЕТЫРЕ ВИДА (все из `D:\ЗАГРУЗКИ\Эффекты-1\Эффекты-1.mp4`):
    inset   врезка в рамке + круги-радар + плавный зум (принят 03.11);
            ТРЕБУЕТ видео-врезку аргументом;
    mosaic  кадр рассыпается на плитки, из плиток собирается следующий;
    panels  новый кадр разворачивается вертикальными панелями;
    wipe    новый кадр въезжает по диагонали со светлой линией на стыке.
Три последних — ПЕРЕХОДЫ: они начинаются с кадра ПРОШЛОЙ сцены, поэтому
ставятся только на сцену-фотографию и только начиная со второй.

Что делает: кладёт врезку в `insets/scene_NNN.mp4` рядом с scenes.json и
ставит сцене ключ `"fx": "inset"`. Дальше ВСЁ САМО: `ship.sh` везёт папку
`insets/` в облако, шаг clips собирает такую сцену через `fx_inset.py`
(кадр сцены с плавным покадровым зумом + врезка в рамке + независимый слой
кругов), всплывашки и субтитры ложатся поверх обычным порядком.

ГРАНИЦЫ ПОЛЬЗОВАТЕЛЯ (03.11, дословно «шикарно, этот оставляем так, как есть,
и в работу его завтра»), проверяются здесь и ещё раз в сборке:
  * ТОЛЬКО канал ПЛАНЕТА — на другом инструмент откажет;
  * НЕ БОЛЬШЕ ТРЁХ сцен на ролик — НА ВСЕ ВИДЫ ВМЕСТЕ («эффекты не больше
    3 раз на видеоряд»), а не по три каждого;
  * глитча в эффекте нет и не добавляем; круги кадр не трогают.

ПОЧЕМУ ВРЕЗКА ПЕРЕЖИМАЕТСЯ ЗДЕСЬ, А НЕ В ОБЛАКЕ: в самом эффекте она
масштабируется до 620x349, то есть библиотечный клип на 60-160 МБ везти в
GitHub незачем (а тот рубит файлы >100 МБ). Жмём только когда это нужно —
длиннее сцены, шире 1280 или тяжелее 8 МБ; иначе файл просто копируется.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

MAX_MB = 8.0
MAX_W = 1280
KINDS = ("inset", "mosaic", "panels", "wipe")
TRANS = ("mosaic", "panels", "wipe")
FX_MAX = 3


def _probe(ffprobe, src):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", src],
                       capture_output=True, text=True)
    vals = [x for x in r.stdout.split() if x]
    try:
        w, h = int(vals[0]), int(vals[1])
    except Exception:
        w = h = 0
    try:
        dur = float(vals[2])
    except Exception:
        dur = 0.0
    return w, h, dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes")
    ap.add_argument("sid", type=int)
    ap.add_argument("video", nargs="?", default="")
    ap.add_argument("--kind", default="", choices=("",) + KINDS,
                    help="вид эффекта; по умолчанию inset, если дано видео")
    ap.add_argument("--off", action="store_true", help="снять эффект со сцены")
    ap.add_argument("--ffmpeg", default="")
    a = ap.parse_args()

    kind = a.kind or ("inset" if a.video else "")
    if not a.off and not kind:
        return _die("скажи, какой эффект: --kind inset|mosaic|panels|wipe "
                    "(для inset дай ещё путь к видео-врезке)")
    if not a.off and kind == "inset" and not a.video:
        return _die("врезке нужен путь к видео (`inset` — это окно с видео "
                    "в рамке)")
    if not a.off and kind in TRANS and a.video:
        return _die("«%s» — это ПЕРЕХОД, видео ему не нужно: он уезжает с "
                    "кадра прошлой сцены на свой" % kind)
    try:
        data = json.load(open(a.scenes, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _die("не прочитать %s: %s" % (a.scenes, e))
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not scenes:
        return _die("в файле нет сцен")

    chan = str((data or {}).get("channel", "") or "") if isinstance(data, dict) else ""
    if not a.off and chan.strip().upper().replace("Ё", "Е") != "ПЛАНЕТА":
        return _die("канал «%s» — эффект ТОЛЬКО на ПЛАНЕТЕ (его слово 03.11)"
                    % (chan or "не указан в scenes.json"))

    sc = next((s for s in scenes if int(s.get("id", -1)) == a.sid), None)
    if sc is None:
        return _die("сцены %d в файле нет" % a.sid)

    proj = os.path.dirname(os.path.abspath(a.scenes))
    dst = os.path.join(proj, "insets", "scene_%03d.mp4" % a.sid)

    if a.off:
        sc.pop("fx", None)
        if os.path.isfile(dst):
            os.remove(dst)
        _save(a.scenes, data)
        print("сцена %d: эффект снят" % a.sid)
        return 0

    if str(sc.get("source", "")).startswith("card"):
        return _die("сцена %d — рисованная карточка (%s), эффект на наш "
                    "нарисованный кадр не кладём" % (a.sid, sc.get("source")))

    have = sorted(s["id"] for s in scenes
                  if str(s.get("fx", "")).strip().lower() in KINDS)
    if a.sid not in have and len(have) >= FX_MAX:
        return _die("на ролике уже %d сцены с эффектами (%s) — потолок его "
                    "словом на ВСЕ виды вместе, четвёртый не ставлю"
                    % (FX_MAX, ", ".join(str(i) for i in have)))

    if kind in TRANS:
        # Переход уезжает с кадра ПРОШЛОЙ сцены: на первой сцене ему не с
        # чего начинать, и он молча поехал бы с чёрного.
        if a.sid <= min(int(s.get("id", 0)) for s in scenes):
            return _die("«%s» — переход с прошлой сцены, на первой сцене "
                        "ролика его ставить не с чего" % kind)
        dur = float(sc.get("duration_sec") or 0)
        if dur < 2.5:
            return _die("сцена %d всего %.1f с — переходу «%s» нужно не "
                        "меньше 2,5 с" % (a.sid, dur, kind))
        sc["fx"] = kind
        # Сцена могла быть врезкой — тогда её файл больше не нужен и в облако
        # поедет мёртвым грузом (а `ship.sh` честно отчитается о врезке,
        # которой в сборке не будет).
        if os.path.isfile(dst):
            os.remove(dst)
            print("прежняя врезка этой сцены удалена — переходу она не нужна")
        _save(a.scenes, data)
        have = sorted(set(have) | {a.sid})
        print("сцена %d (%.1f с): переход «%s» ПОСТАВЛЕН" % (a.sid, dur, kind))
        print("эффектов в ролике: %d из %d (%s)"
              % (len(have), FX_MAX, ", ".join(str(i) for i in have)))
        print("файлов не нужно: кадр прошлой сцены облако возьмёт само")
        return 0

    if not os.path.isfile(a.video):
        return _die("нет файла врезки: %s" % a.video)

    ffmpeg = a.ffmpeg or shutil.which("ffmpeg") or os.path.expanduser("~/.local/bin/ffmpeg")
    ffprobe = "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1))
    dur = float(sc.get("duration_sec") or 10.0)
    w, h, vdur = _probe(ffprobe, a.video)
    mb = os.path.getsize(a.video) / 1048576.0
    need = (mb > MAX_MB) or (w > MAX_W) or (vdur > dur + 2.0)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if need:
        if not os.path.isfile(ffmpeg) and not shutil.which(ffmpeg):
            return _die("нужен пережим (%.1f МБ, %dx%d, %.1f с), а ffmpeg не "
                        "найден" % (mb, w, h, vdur))
        r = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-i", a.video, "-t", "%.2f" % (dur + 1.0), "-an",
             # ТОЛЬКО УМЕНЬШЕНИЕ И БЕЗ ОБРЕЗКИ: в эффекте врезка всё равно
             # ужимается до 620x349, апскейл узкого клипа дал бы вес без
             # качества, а обрезка под 16:9 — съела бы часть кадра дважды
             # (её делает сам fx_inset, вписывая врезку в рамку).
             "-vf", "scale=w='min(1280,iw)':h=-2,fps=30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", dst], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(dst):
            return _die("пережим врезки не удался: " + r.stderr[-300:])
        nw, nh, nd = _probe(ffprobe, dst)
        print("врезка пережата: %.1f МБ %dx%d %.1f с → %.1f МБ %dx%d %.1f с"
              % (mb, w, h, vdur, os.path.getsize(dst) / 1048576.0, nw, nh, nd))
    else:
        shutil.copyfile(a.video, dst)
        print("врезка скопирована как есть: %.1f МБ %dx%d %.1f с"
              % (mb, w, h, vdur))

    sc["fx"] = "inset"
    _save(a.scenes, data)
    have = sorted(set(have) | {a.sid})
    print("сцена %d (%.1f с): эффект-врезка ПОСТАВЛЕН → %s"
          % (a.sid, dur, os.path.relpath(dst, proj)))
    print("эффектов в ролике: %d из %d (%s)"
          % (len(have), FX_MAX, ", ".join(str(i) for i in have)))
    print("дальше ничего не делать: ship.sh везёт insets/ сам, "
          "клип соберёт шаг clips")
    return 0


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _die(msg):
    print("!! " + msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
