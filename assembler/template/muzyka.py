#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ФОНОВАЯ МУЗЫКА ПОД ГОТОВЫЙ ВИДЕОРЯД — ТОЛЬКО КАНАЛ ПЛАНЕТА (11.11.2026).

Его заказ дословно: «поставь вот эти два аудиофайла один после другого
фоновой музыкой… чтобы она шла на протяжении всего ролика… в конце чтобы
громкость падала и сводилась до нуля… только исключительно на канале
Планета».

УРОВЕНЬ ВЫВЕРЕН ИМ НА СЛУХ, ЧЕТЫРЕ ПРОБЫ ПОДРЯД: 20% → 40% → 10% от голоса →
40% от того → 50% от того. Принято последнее. В числах: музыка выводится на
−20 dB относительно голоса и ещё вдвое тише дважды, итог ≈2% громкости
голоса (в паузах озвучки фон −52 dB). Менять только по его слову.

ПОЧЕМУ СЧИТАЕМ ЛОКАЛЬНО, А НЕ В ОБЛАКЕ. Треки лежат на `D:`, раннер их не
видит; везти 12 МБ чужой музыки в ПУБЛИЧНЫЙ репозиторий ради этого не надо.
Видео не перекодируется (`-c:v copy`), работы на 13-минутном ролике — 30 с.

    python3 muzyka.py <готовый.mp4> [--out файл] [--канал ПЛАНЕТА]
    python3 muzyka.py <готовый.mp4> --proba 60     # минутный кусок с конца
"""
import argparse
import os
import re
import subprocess
import sys

# Его два трека, порядок важен: сначала Eyes of Glory, следом Invincible.
МЕДИОТЕКА = "/mnt/d/YouTube/МЕДИОТЕКА"
ТРЕКИ = [
    "Eyes of Glory - Aakash Gandhi-тревожный саундтрек.mp3",
    "Invincible - Aakash Gandhi-тревожный саундтрек.mp3",
]
ГРОМКОСТЬ = 0.02046      # ≈2% от голоса — утверждено им 11.11 на слух
ЗАТУХАНИЕ = 10.0         # секунд в самом конце, до нуля
КАНАЛЫ = ("ПЛАНЕТА",)    # больше нигде музыки нет — его прямое слово


def канал_из_пути(путь):
    ч = os.path.abspath(путь).replace("\\", "/").split("/")
    for i, x in enumerate(ч):
        if x.upper() == "НОВОСТИ" and i + 1 < len(ч):
            return ч[i + 1]
    return ""


def канал_проекта(путь):
    """Канал по файлу рядом (`.channel`) или по `.source_dir` проекта."""
    d = os.path.dirname(os.path.abspath(путь)) or "."
    к = канал_из_пути(путь)
    if к:
        return к
    for имя in (".channel", ".kanal"):
        try:
            with open(os.path.join(d, имя), encoding="utf-8") as f:
                з = f.read().strip()
            if з:
                return з
        except OSError:
            continue
    try:
        with open(os.path.join(d, ".source_dir"), encoding="utf-8") as f:
            return канал_из_пути(f.read().strip())
    except OSError:
        return ""


def длительность(путь):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1", путь],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def собрать_пару(куда):
    """Два трека подряд одним файлом; дальше его крутим по кругу."""
    пути = [os.path.join(МЕДИОТЕКА, т) for т in ТРЕКИ]
    нет = [p for p in пути if not os.path.isfile(p)]
    if нет:
        print("!! нет трека: %s" % ", ".join(os.path.basename(x) for x in нет),
              file=sys.stderr)
        return ""
    список = os.path.join(куда, "_muz_list.txt")
    with open(список, "w", encoding="utf-8") as f:
        for p in пути:
            f.write("file '%s'\n" % p.replace("'", "'\\''"))
    пара = os.path.join(куда, "_muz_para.m4a")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat",
                        "-safe", "0", "-i", список, "-ar", "44100",
                        "-ac", "1", "-c:a", "aac", "-b:a", "160k", пара],
                       capture_output=True, text=True)
    os.remove(список)
    if r.returncode != 0 or not os.path.isfile(пара):
        print("!! склейка треков не вышла: %s" % r.stderr.strip()[:300],
              file=sys.stderr)
        return ""
    return пара


def наложить(видео, out, пара, громкость=ГРОМКОСТЬ, затухание=ЗАТУХАНИЕ):
    dur = длительность(видео)
    if dur <= 0:
        print("!! не читается длительность: %s" % видео, file=sys.stderr)
        return False
    st = max(0.0, round(dur - затухание, 3))
    фильтр = ("[1:a]atrim=0:%.3f,volume=%.5f,afade=t=out:st=%.3f:d=%.1f[mus];"
              "[0:a][mus]amix=inputs=2:duration=first:normalize=0[a]"
              % (dur, громкость, st, затухание))
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", видео,
                        "-stream_loop", "-1", "-i", пара,
                        "-filter_complex", фильтр,
                        "-map", "0:v", "-map", "[a]",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(out):
        print("!! микс не вышел: %s" % r.stderr.strip()[:300], file=sys.stderr)
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description="фоновая музыка под готовый ролик")
    ap.add_argument("video")
    ap.add_argument("--out", default="", help="куда писать; по умолчанию "
                                              "<имя> С МУЗЫКОЙ.mp4 рядом")
    ap.add_argument("--канал", default="", dest="kanal",
                    help="канал явно, если из пути не виден")
    ap.add_argument("--na-mesto", action="store_true", dest="na_mesto",
                    help="заменить исходный файл (прежний рядом .bez_muzyki)")
    ap.add_argument("--proba", type=float, default=0,
                    help="вывести только кусок С КОНЦА такой длины, секунд")
    ap.add_argument("--gromkost", type=float, default=ГРОМКОСТЬ,
                    help="коэффициент громкости музыки (по умолчанию его)")
    a = ap.parse_args()

    if not os.path.isfile(a.video):
        sys.exit("нет файла: %s" % a.video)
    канал = (a.kanal or канал_проекта(a.video)).strip()
    if канал.upper().replace("Ё", "Е") not in КАНАЛЫ:
        print("канал «%s» — музыка НЕ накладывается (она только на %s, его "
              "прямое слово 11.11)" % (канал or "не определён",
                                       ", ".join(КАНАЛЫ)))
        return 0

    рабочая = os.path.dirname(os.path.abspath(a.video)) or "."
    пара = собрать_пару(рабочая)
    if not пара:
        return 3
    корень, расш = os.path.splitext(a.video)
    out = a.out or (корень + " С МУЗЫКОЙ" + расш)
    if a.na_mesto and not a.out:
        out = корень + ".muz_tmp" + расш
    ок = наложить(a.video, out, пара, громкость=a.gromkost)
    try:
        os.remove(пара)
    except OSError:
        pass
    if not ок:
        return 3

    if a.proba > 0:
        dur = длительность(out)
        начало = max(0.0, dur - a.proba)
        кусок = корень + " ПРОБА МУЗЫКИ" + расш
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % начало,
                        "-t", "%.3f" % a.proba, "-i", out,
                        "-c:v", "copy", "-c:a", "copy", кусок],
                       capture_output=True, text=True)
        os.remove(out)
        print("проба (%.0f с с конца): %s" % (a.proba, кусок))
        return 0

    if a.na_mesto and not a.out:
        прежний = корень + ".bez_muzyki" + расш
        try:
            if not os.path.exists(прежний):
                os.replace(a.video, прежний)
            else:
                os.remove(a.video)
            os.replace(out, a.video)
            out = a.video
            print("музыка вшита НА МЕСТЕ (прежний файл: %s)"
                  % os.path.basename(прежний))
        except OSError as e:
            print("!! не удалось заменить на месте (%s), результат: %s"
                  % (e, out), file=sys.stderr)
    print("музыка ПЛАНЕТЫ наложена: громкость %.5f (≈2%% от голоса), "
          "затухание %.0f с в конце" % (a.gromkost, ЗАТУХАНИЕ))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
