# -*- coding: utf-8 -*-
"""ИМЯ ПОД КАДРОМ ОБЯЗАНО СОВПАДАТЬ С ЧЕЛОВЕКОМ НА КАДРЕ (14.11).

Его слово по сцене 24 ролика `planeta-3-priznalis-peregovory`: «Кая Каллас,
а там заседание Совета НАТО, какой-то кабинет… Надо проверять, что ты
пишешь и что там на картинке. Чтобы это было соответствие».

Инструмент печатает список сцен, где под кадром стоит ИМЯ, а в пути к файлу
фамилии нет — то есть подтверждения, что на снимке именно он, не было.
Это не доказательство брака: кадр мог быть верным, а файл назван иначе.
Но каждую такую сцену обязан посмотреть человек или агент.

    python3 imena_pod_kadrom.py <папка проекта> [ещё папки…]
"""
import glob
import json
import os
import re
import sys


def проверить(proj):
    плохо = []
    for f in sorted(glob.glob(os.path.join(proj, "cards", "queue", "scene_*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        k = d.get("kwargs", {}) or {}
        авт = str(k.get("author") or k.get("source") or "").strip()
        фото = str(k.get("photo") or "")
        if not авт or not фото:
            continue
        фам = re.findall(r"[А-ЯЁ][а-яё]{3,}", авт)
        if фам and not any(ф.lower()[:5] in фото.lower() for ф in фам):
            m = re.search(r"scene_(\d+)", f)
            плохо.append((int(m.group(1)) if m else 0, авт, фото))
    return плохо


for proj in sys.argv[1:]:
    п = проверить(proj)
    print("=== %s — имён без подтверждения: %d" % (os.path.basename(proj), len(п)))
    for sid, авт, фото in п:
        print("   сцена %-3d «%s» ← %s" % (sid, авт, os.path.basename(фото)))
    if п:
        print("   Посмотри кадры глазами: на снимке должен быть НАЗВАННЫЙ человек.")
        print("   Кадр верный — переименуй файл фамилией или поставь "
              "--photo-kto «Фамилия». Человека нет — убери имя или смени вид.")
