#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЗАБРАТЬ ПАПКУ ПОЛЬЗОВАТЕЛЯ ЦЕЛИКОМ, ОДНИМ СКОПОМ — ПЕРВЫМ ШАГОМ.

    python3 take_folder.py "<папка пользователя на D:>" <папка проекта>

ПРЯМОЕ СЛОВО ПОЛЬЗОВАТЕЛЯ 04.11, после потерянного получаса:
«зашить во все скиллы, во все репозитарии, во всё, что можно, в память,
чтобы такого больше не повторялось: всё сразу забирать с собой, одним
скопом. И не делать сборку видео, пока не убедитесь, что всё вошло туда».

Повод: озвучка и SRT лежали в его папке с самого начала, вкладка взяла
только `.srt`, а `.mp3` остался там же — и готовый файл на 476 МБ приехал
НЕМЫМ. Правок после `ship.sh` не бывает, значит цена — полная пересборка.

ЧТО ДЕЛАЕТ: копирует из его папки ВСЁ, что может понадобиться сборке
(`.srt`, `.mp3`, `.wav`, `.m4a`, `.txt`, `.ass`, `.json`), приводит озвучку
к имени `narration.<ext>`, запоминает исходную папку в `.source_dir` — её
потом читает `ship.sh`, когда ищет голос, — и печатает, что именно взято.
Ничего не удаляет и не перезаписывает уже существующее без нужды.
"""
import argparse
import os
import shutil
import sys

TAKE = (".srt", ".mp3", ".wav", ".m4a", ".txt", ".ass", ".json")
VOICE = (".mp3", ".wav", ".m4a")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="папка пользователя (та, где лежит SRT)")
    ap.add_argument("dst", help="папка проекта")
    ap.add_argument("--force", action="store_true",
                    help="перезаписать уже лежащие файлы")
    a = ap.parse_args()
    if not os.path.isdir(a.src):
        sys.exit("нет папки: %s" % a.src)
    os.makedirs(a.dst, exist_ok=True)

    took, skipped, voice = [], [], ""
    for name in sorted(os.listdir(a.src)):
        p = os.path.join(a.src, name)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in TAKE:
            continue
        # озвучку кладём под каноническим именем: его ищет ship.sh и облако
        if ext in VOICE and not name.lower().startswith("sfx"):
            out = os.path.join(a.dst, "narration" + ext)
            voice = name
        else:
            out = os.path.join(a.dst, name)
        if os.path.exists(out) and not a.force:
            skipped.append(name)
            continue
        shutil.copy2(p, out)
        took.append("%s → %s" % (name, os.path.basename(out)))

    with open(os.path.join(a.dst, ".source_dir"), "w", encoding="utf-8") as f:
        f.write(os.path.abspath(a.src) + "\n")

    print("забрано из %s:" % a.src)
    for t in took:
        print("  " + t)
    if skipped:
        print("уже лежало (не трогал, --force перезапишет): %s"
              % ", ".join(skipped))
    print("исходная папка запомнена в .source_dir")

    srt = [f for f in os.listdir(a.dst) if f.lower().endswith(".srt")]
    nar = [f for f in os.listdir(a.dst)
           if f.lower().startswith("narration") and
           os.path.splitext(f)[1].lower() in VOICE]
    print()
    print("SRT: %s" % (", ".join(srt) if srt else "НЕТ"))
    print("ОЗВУЧКА: %s" % (nar[0] if nar else "НЕТ"))
    if not srt or not nar:
        print()
        print("!! КОМПЛЕКТ НЕ ПОЛНЫЙ. Полную сборку начинать НЕЛЬЗЯ: "
              "«не делать сборку видео, пока не убедитесь, что всё вошло "
              "туда» (его слово 04.11).", file=sys.stderr)
        print("   Посмотри, что лежит в его папке, и забери руками:",
              file=sys.stderr)
        for n in sorted(os.listdir(a.src))[:30]:
            print("     " + n, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
