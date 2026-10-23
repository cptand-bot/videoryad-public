# -*- coding: utf-8 -*-
"""AI-ПАРТИЯ В ПАПКЕ МЕДИАТЕКИ — ОПОЗНАТЬ ЧИСЛАМИ, А НЕ ГЛАЗОМ.

Находка вкладки `usuario-ad` 22.10, подтверждённая числами 23.10 на
`planeta-zapad-front-2410`: у пачки сгенерированных клипов РОВНО одинаковая
длительность и РОВНО одинаковый кадр — 10.000 с / 854×480 (вся ПОЛЬША, 7
файлов), 5.2 с / 832×464, 9.0 с / 832×464 (ЛИТВА). Настоящая съёмка так не
бывает: у неё длительности дробные и разные. Глаз на отдельном клипе этого
не решает, ffprobe по папке решает за секунды.

    python3 ai_batch.py <папка> [--min 3] [--recursive]

Печатает партии (что с чем совпало), подозрительные имена и итог. Ничего не
банит и не удаляет — решение за вкладкой: бан через `ban_file.py`.
"""
import argparse
import collections
import glob
import os
import re
import subprocess
import sys

VIDEO = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
# имена, которые оставляют генераторы
NAME_MARKS = [
    (re.compile(r"task_[0-9a-z]{10,}", re.I), "имя задания генератора (task_…)"),
    (re.compile(r"simple_compose", re.I), "сборка генератора (simple_compose)"),
    (re.compile(r"^new video", re.I), "безымянный вывод генератора (New Video…)"),
    (re.compile(r"(runway|pika|kling|sora|veo|luma|minimax|hailuo)", re.I),
     "имя генератора в названии"),
]


def probe(path):
    """(длительность, ширина, высота) или None — одним вызовом ffprobe."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True)
    vals = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
    if len(vals) < 3:
        return None
    try:
        w, h, d = int(vals[0]), int(vals[1]), float(vals[2])
    except ValueError:
        return None
    return d, w, h


def main():
    ap = argparse.ArgumentParser(description="опознать AI-партию по длительностям")
    ap.add_argument("folder")
    ap.add_argument("--min", type=int, default=3,
                    help="сколько совпадений считать партией (по умолчанию 3)")
    ap.add_argument("--recursive", action="store_true")
    a = ap.parse_args()

    if not os.path.isdir(a.folder):
        sys.exit(f"нет папки: {a.folder}")
    pat = "**/*" if a.recursive else "*"
    files = [f for f in glob.glob(os.path.join(a.folder, pat), recursive=a.recursive)
             if f.lower().endswith(VIDEO)]
    if not files:
        print("видео в папке нет — проверять нечего")
        return

    groups, broken = collections.defaultdict(list), []
    for f in sorted(files):
        got = probe(f)
        if got is None:
            broken.append(f)
            continue
        d, w, h = got
        # ключ — длительность с точностью до миллисекунды и кадр: именно
        # РОВНОЕ совпадение выдаёт партию, «примерно похоже» не годится
        groups[(round(d, 3), w, h)].append(f)

    batches = {k: v for k, v in groups.items() if len(v) >= a.min}
    print(f"видео в папке: {len(files)}"
          + (f", не прочитались: {len(broken)}" if broken else ""))

    for (d, w, h), fs in sorted(batches.items(), key=lambda kv: -len(kv[1])):
        exact = "РОВНО" if abs(d - round(d, 1)) < 0.0005 else "одинаково"
        print(f"\nПАРТИЯ: {len(fs)} файлов, {exact} {d:g} с, {w}×{h}")
        for f in fs:
            print("   ", os.path.basename(f))

    named = []
    for f in sorted(files):
        for rx, why in NAME_MARKS:
            if rx.search(os.path.basename(f)):
                named.append((os.path.basename(f), why))
                break
    if named:
        print("\nПОДОЗРИТЕЛЬНЫЕ ИМЕНА:")
        for n, why in named:
            print(f"    {n} — {why}")

    inside = sum(len(v) for v in batches.values())
    print(f"\nИТОГ: в партиях {inside} из {len(files)} видео"
          + (f", плюс {len(named)} по имени" if named else ""))
    if inside or named:
        print("Это признак сгенерированной пачки, а не съёмки. На сцены такую "
              "папку не расписывай не глядя: посмотри глазами и, если это AI, "
              "бань через ban_file.py.")
    else:
        print("Партий не видно: длительности разные — похоже на настоящую съёмку.")


if __name__ == "__main__":
    main()
