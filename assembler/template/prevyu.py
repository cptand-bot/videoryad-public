#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПЯТЬ ПРЕВЬЮ ДЛЯ YOUTUBE ПО ТЕМЕ СТАТЬИ (07.11.2026).

    python3 prevyu.py "<папка темы>"          # одна тема
    python3 prevyu.py "<папка дня>" --all     # все темы дня

Его ручной шаг, который он делал в чате последним: после описания и
заголовков вставлял в ту же тему промпт на превью. Промпт здесь ДОСЛОВНО
его, менять формулировки нельзя — он проверен работой.

КАК ЭТО РАБОТАЕТ. Внешний агент (Codex) умеет рисовать: инструмент
`image_gen`. Сохранить файл сам он НЕ МОЖЕТ — у него файловая система
только для чтения, — но картинка ложится в `~/.codex/generated_images/`,
и мы забираем её оттуда. Проверено запуском 07.11.

ЧТО КЛАДЁТ: `превью-варианты/ПРЕВЬЮ-1.png` … `-5.png` — В ОТДЕЛЬНУЮ
ПОДПАПКУ (07.11, его слово: «чтобы не загромождать всю эту срань в папке,
генерированные изображения ложи в отдельную папку, чтобы она не мелькала»).
В корне папки темы лежит только ГОТОВОЕ превью с надписями — рядом с
озвучкой, чтобы его было видно сразу. Видео и прочие файлы не трогает.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = "превью-варианты"        # подпапка сырых вариантов
GEN = os.path.expanduser("~/.codex/generated_images")
SKIP_TXT = ("ЗАДАНИЕ", "БРИФ", "ОТВЕТ", "ПРОМПТ", "РЕРАЙТ", "ДОСЬЕ",
            "АУДИТ", "УПАКОВКА", "ГЕОРАДАР", "ПРЕВЬЮ")

# ЕГО ПРОМПТ, ДОСЛОВНО. Ни слова не переписывать.
PROMPT_TAIL = """Сделай кликбейтное превью для YouTube. В светлых тонах, без надписей.
Лица должны выражать ярко выраженные эмоции.
Пять вариантов, каждый вариант — отдельное изображение. Не в одном
изображении пять вариантов, а один вариант — одна картинка.
делать строго по теме написанной статьи.
Не нарушая правил и не допуская появления на изображении детей и подростков.
Не размещать на превью Шольца, Стармера, Трюдо, Орбан и остальных
политиков которые уже сейчас не актуальны. Никаких ноунеймов на превью"""


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", "replace")


def find_text(folder):
    c = [os.path.join(folder, n) for n in os.listdir(folder)
         if n.lower().endswith(".txt")
         and not any(s in n.upper() for s in SKIP_TXT)]
    return max(c, key=os.path.getsize) if c else ""


def fresh_images(since):
    """Картинки, появившиеся у агента ПОСЛЕ начала нашего запроса.
    Берём по времени файла, а не по имени: имя у него случайное."""
    out = []
    for f in glob.glob(os.path.join(GEN, "*", "*.png")):
        try:
            if os.path.getmtime(f) >= since:
                out.append(f)
        except OSError:
            continue
    return sorted(out, key=os.path.getmtime)


def do_one(folder, keep=5):
    src = find_text(folder)
    if not src:
        print("  ✗ нет текста статьи: %s" % folder)
        return False
    text = read_text(src)
    title = os.path.basename(folder)

    task = ("СТАТЬЯ (по ней делается превью):\n"
            "======================================================\n"
            + text[:6000] +
            "\n======================================================\n\n"
            + PROMPT_TAIL +
            "\n\nСгенерируй ВСЕ ПЯТЬ картинок инструментом image_gen, по одной "
            "за раз. После каждой напиши одну строку: «готово N из пяти».\n"
            "Сохранять файлы никуда не нужно — я заберу их сам.")
    os.makedirs(os.path.join(folder, VARIANTS), exist_ok=True)
    tz = os.path.join(folder, VARIANTS, "ЗАДАНИЕ-ПРЕВЬЮ.txt")
    open(tz, "w", encoding="utf-8").write(task)

    print("  %s — рисую пять превью…" % title)
    t0 = time.time() - 2
    subprocess.run(["bash", os.path.join(HERE, "codex_ask.sh"), tz],
                   capture_output=True, text=True, timeout=3600)
    got = fresh_images(t0)
    if not got:
        print("  ✗ картинок не появилось — проверь ЗАДАНИЕ-ПРЕВЬЮ.ОТВЕТ.txt")
        return False
    vdir = os.path.join(folder, VARIANTS)
    os.makedirs(vdir, exist_ok=True)
    n = 0
    for i, f in enumerate(got[:keep], 1):
        dst = os.path.join(vdir, "ПРЕВЬЮ-%d.png" % i)
        shutil.copy2(f, dst)
        n += 1
    print("  ✓ превью: %d шт. в %s/ (%s)"
          % (n, VARIANTS, ", ".join("%.1f МБ" % (os.path.getsize(
              os.path.join(vdir, "ПРЕВЬЮ-%d.png" % i)) / 1048576)
              for i in range(1, n + 1))))
    return n > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--keep", type=int, default=5)
    a = ap.parse_args()
    root = os.path.abspath(a.folder)
    if a.all:
        targets = [os.path.join(root, d) for d in sorted(os.listdir(root))
                   if os.path.isdir(os.path.join(root, d))]
        targets = [t for t in targets if find_text(t)]
    else:
        targets = [root]
    print("ПРЕВЬЮ: %d тем" % len(targets))
    ok = sum(1 for t in targets if do_one(t, a.keep))
    print("готово: %d из %d" % (ok, len(targets)))
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
