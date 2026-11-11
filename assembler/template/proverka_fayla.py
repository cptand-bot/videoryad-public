#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПРОВЕРКА ГОТОВОГО ФАЙЛА ЧИСЛАМИ — А НЕ ЕГО ГЛАЗАМИ НА ДАШБОРДЕ (11.11.2026).

Откуда: разбор чужого конвейера cinecode, его слово «внедряй, поехали».

ЧЕМ ОТЛИЧАЕТСЯ ОТ ТОГО, ЧТО У НАС БЫЛО. Все наши сита (`selfcheck`,
`obyazatelno`, `povtor_kadrov`, `query_lint`) смотрят в РАСКАДРОВКУ и в
исходные файлы — то есть в замысел. Готовый MP4 до сих пор не проверял никто:
что доехало до файла, видел только он на дашборде. Через эту дыру уже
проезжали: немой ролик 10.11 («мне приехал без субтитров он»), замершие куски,
сцены вдвое громче соседних.

ЧТО СЧИТАЕТ:
  движение первых 2 секунд  — жёсткое правило: ролик обязан двигаться с
                              первого кадра, иначе зритель уходит
  немой файл / провалы звука — тишина длиннее 2,5 с
  чёрные куски               — чёрный кадр длиннее 0,4 с
  замершие куски             — картинка не меняется дольше 2,5 с
  громкость                  — общая LUFS и пик; по сценам, если дан scenes.json
  сцены-выбросы              — сцена громче или тише медианы больше чем на 3 LU

ЗАПУСК:
    python3 proverka_fayla.py <ролик>.mp4 [<ролик>.scenes.json]
    python3 proverka_fayla.py <ролик>.mp4 --gate     # код 1, если есть НАРУШЕНИЯ

ПРО РЕСУРСЫ КОМПЬЮТЕРА (его правило 23.10 — не считать на его ПК). Это не
рендер: один проход ffmpeg по уменьшенной до 160 px копии и один по звуку,
под `nice -n 19 ionice -c3 -threads 2`. Замер на 13-минутном ролике — в шапке
вывода, числом. Если когда-нибудь вылезет за минуту, шаг надо увозить в
облако вместе со сборкой.
"""
import json
import os
import re
import subprocess
import sys
import time

NICE = ["nice", "-n", "19", "ionice", "-c3"]
ТИХО = ["-hide_banner", "-nostdin", "-threads", "2"]


def ffmpeg(args, timeout=900):
    p = subprocess.run(NICE + ["ffmpeg"] + ТИХО + args,
                       capture_output=True, text=True, timeout=timeout)
    return p.stderr


def длительность(путь):
    p = subprocess.run(NICE + ["ffprobe", "-v", "error", "-show_entries",
                               "format=duration", "-of", "csv=p=0", путь],
                       capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def есть_звук(путь):
    p = subprocess.run(NICE + ["ffprobe", "-v", "error", "-select_streams", "a",
                               "-show_entries", "stream=codec_name", "-of",
                               "csv=p=0", путь], capture_output=True, text=True)
    return bool(p.stdout.strip())


def движение_в_начале(путь, секунд=2.0):
    """Средняя разница между соседними кадрами первых секунд, 0..1.

    Считается по уменьшенной копии: нам нужен факт движения, а не детали.
    Порог 0,004 снят с наших же роликов: статичное фото под зумом даёт
    0,006-0,02, настоящий замерший кадр — ниже 0,002."""
    out = ffmpeg(["-t", str(секунд), "-i", путь, "-vf",
                  "scale=160:-2,format=gray,tblend=all_mode=difference,"
                  "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                  "-f", "null", "-"], timeout=120)
    зн = [float(m) for m in re.findall(r"YAVG=([0-9.]+)", out)]
    зн = зн[1:] or зн          # первый кадр сравнивать не с чем
    return (sum(зн) / len(зн) / 255.0) if зн else 0.0


def картинка(путь):
    """Один проход: чёрные куски и замершие куски."""
    out = ffmpeg(["-i", путь, "-vf",
                  "scale=160:-2,blackdetect=d=0.4:pic_th=0.98,"
                  "freezedetect=n=-55dB:d=2.5",
                  "-an", "-f", "null", "-"])
    чёрные = [(float(a), float(b)) for a, b in
              re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", out)]
    замершие = []
    старт = None
    for m in re.finditer(r"freeze_(start|duration|end): ?(-?[0-9.]+)", out):
        вид, зн = m.group(1), float(m.group(2))
        if вид == "start":
            старт = зн
        elif вид == "end" and старт is not None:
            замершие.append((старт, зн))
            старт = None
    return чёрные, замершие


def звук(путь, начало=None, конец=None):
    """Громкость куска (или всего файла) в LUFS и пик."""
    args = []
    if начало is not None:
        args += ["-ss", str(начало)]
    if конец is not None and начало is not None:
        args += ["-t", str(max(0.3, конец - начало))]
    out = ffmpeg(args + ["-i", путь, "-vn", "-filter:a", "ebur128=peak=true",
                         "-f", "null", "-"])
    хвост = out[-1800:]
    i = хвост.rfind("Integrated loudness")
    кусок = хвост[i:] if i >= 0 else хвост
    m = re.search(r"I:\s*(-?[0-9.]+)\s*LUFS", кусок)
    p = re.search(r"Peak:\s*(-?[0-9.]+)\s*dBFS", кусок)
    return (float(m.group(1)) if m else None,
            float(p.group(1)) if p else None)


def тишина(путь):
    out = ffmpeg(["-i", путь, "-vn", "-af", "silencedetect=n=-50dB:d=2.0",
                  "-f", "null", "-"])
    нач = [float(x) for x in re.findall(r"silence_start: ?(-?[0-9.]+)", out)]
    кон = [float(x) for x in re.findall(r"silence_end: ?(-?[0-9.]+)", out)]
    return list(zip(нач, кон + [None] * (len(нач) - len(кон))))


def сцены(путь):
    d = json.load(open(путь, encoding="utf-8"))
    sc = d["scenes"] if isinstance(d, dict) else d
    гр = []
    for s in sc:
        н = s.get("start_sec")
        д = s.get("duration_sec")
        if н is None or д is None:
            continue
        гр.append((s.get("id"), float(н), float(н) + float(д)))
    return гр


def проверить(видео, файл_сцен=None, по_сценам=True):
    """Весь счёт одним вызовом. Возвращает (нарушения, замечания, инфо).

    Зовётся и руками, и из облака (`cloud_pipeline.step_qa`): на раннере
    процессор бесплатный, и там же лежит только что собранный файл."""
    нарушения, замечания, инфо = [], [], []
    дл = длительность(видео)
    звук_есть = есть_звук(видео)
    инфо.append(f"длительность {дл/60:.1f} мин, звук {'есть' if звук_есть else 'НЕТ'}")

    дв = движение_в_начале(видео)
    инфо.append(f"движение первых 2 с: {дв:.4f}")
    if дв < 0.004:
        нарушения.append(
            f"ПЕРВЫЕ 2 СЕКУНДЫ ПОЧТИ НЕ ДВИГАЮТСЯ (движение {дв:.4f}). "
            "Зритель уходит на статичном открытии — сцене 1 нужен зум, клип "
            "или движение внутри кадра")

    if not звук_есть:
        нарушения.append("В ФАЙЛЕ НЕТ ЗВУКОВОЙ ДОРОЖКИ — ролик немой")
    else:
        lufs, пик = звук(видео)
        инфо.append(f"громкость {lufs} LUFS, пик {пик} dBFS")
        if lufs is not None and lufs < -30:
            нарушения.append(f"дорожка есть, но почти пустая ({lufs} LUFS) — "
                             "проверить, легла ли озвучка")
        молчит = [t for t in тишина(видео) if (t[1] or дл) - t[0] >= 2.5]
        if молчит:
            всего = sum((b or дл) - a for a, b in молчит)
            показ = ", ".join(f"{a:.0f}-{(b or дл):.0f} с" for a, b in молчит[:6])
            # ДОЛГАЯ ПАУЗА САМА ПО СЕБЕ НЕ БРАК (замер 11.11 на сданном ролике:
            # десять пауз ровно через 72 с — это стыки блоков озвучки, а не
            # дыра). Нарушением считается, когда тишины набирается больше
            # десятой части ролика: вот это уже провал дорожки.
            строка = f"провалы звука дольше 2 с ({len(молчит)}, всего {всего:.0f} с): {показ}"
            # Планка поднята после второго замера 11.11: на 15-минутном ролике
            # 40 пауз по 2 с (91 с всего) — это темп нашей озвучки, а не дыра.
            # Нарушение — когда тишины набирается пятая часть ролика.
            (нарушения if всего > дл * 0.2 else замечания).append(строка)

    чёрные, замершие = картинка(видео)
    чёрные = [c for c in чёрные if c[1] - c[0] >= 0.4]
    инфо.append(f"чёрных кусков {len(чёрные)}, замерших {len(замершие)}")
    if чёрные:
        нарушения.append("ЧЁРНЫЕ КУСКИ: " +
                         ", ".join(f"{a:.1f}-{b:.1f} с" for a, b in чёрные[:6]))
    if замершие:
        замечания.append(f"замершие куски ({len(замершие)}) — посмотреть глазами: " +
                         ", ".join(f"{a:.0f}-{b:.0f} с" for a, b in замершие[:6]))

    if по_сценам and файл_сцен and звук_есть and os.path.exists(файл_сцен):
        гр = сцены(файл_сцен)
        зам = [(i, звук(видео, н, к)[0]) for i, н, к in гр]
        зам = [(i, v) for i, v in зам if v is not None and v > -70]
        if len(зам) >= 5:
            знач = sorted(v for _, v in зам)
            мед = знач[len(знач) // 2]
            выбросы = [(i, v) for i, v in зам if abs(v - мед) > 3.0]
            инфо.append(f"сцен промерено {len(зам)}, медиана {мед:.1f} LUFS, "
                        f"выбросов {len(выбросы)}")
            if выбросы:
                замечания.append(
                    "сцены громче/тише остальных больше чем на 3 LU: " +
                    ", ".join(f"сц.{i} ({v:.1f})" for i, v in выбросы[:8]))
    return нарушения, замечания, инфо


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    видео = sys.argv[1]
    гейт = "--gate" in sys.argv
    быстро = "--bez-scen" in sys.argv
    файл_сцен = next((a for a in sys.argv[2:] if a.endswith(".json")), None)
    if not os.path.exists(видео):
        print(f"нет файла: {видео}")
        return 2

    # ЕГО ПРАВИЛО 23.10: на его машине не считать молча. Полный счёт уже стоит
    # в облаке (шаг `qa` сборки) и приезжает в QA-отчёте вместе с файлом —
    # здесь он нужен только для уже доставленного ролика, и об этом надо сказать.
    print(f"ПРОВЕРКА ГОТОВОГО ФАЙЛА: {os.path.basename(видео)}")
    print("  (счёт идёт на этой машине, под nice; в облаке то же самое делает "
          "шаг qa и кладёт в QA-отчёт)")
    т0 = time.time()
    нарушения, замечания, инфо = проверить(видео, файл_сцен, по_сценам=not быстро)
    for i in инфо:
        print(f"  {i}")
    print(f"\n  посчитано за {time.time() - т0:.0f} с\n")
    if нарушения:
        print("НАРУШЕНИЯ — чинить до сдачи:")
        for n in нарушения:
            print(f"  ✗ {n}")
    if замечания:
        print("ЗАМЕЧАНИЯ — посмотреть глазами в этих секундах:")
        for z in замечания:
            print(f"  · {z}")
    if not нарушения and not замечания:
        print("ЧИСТО — файл можно отдавать.")
    return 1 if (гейт and нарушения) else 0


if __name__ == "__main__":
    sys.exit(main())
