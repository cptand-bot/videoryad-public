#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СВЕРКА КАРТОЧЕК — есть ли у каждой сцены `card:*` ЗАДАНИЕ и КАДР.

Зачем. Гейты (`obyazatelno.py`, `accept_scenes.py`) засчитывают сцену по
СТРОКЕ источника `card:<вид>`, а не по наличию задания в `cards/queue/`.
Поэтому вид, которого у двери нет (12.11: улов `usuario-0d` и `usuario-e3`),
проходит приёмку пустым: в ролике на его месте заглушка, а дашборд зелёный.
Шесть видов живут НЕ в `card_put.py`, а в других дверях:
  A6 poster · A4 bars · A5 slider · A56 wall · A64 dof → `element_put.py`
  A34 photo                                          → `style_card.py`
Внешний агент назначает их как `card:poster` / `card:bars` и т.д., задание не
создаётся, и сцена молча теряется.

Второе, что здесь считается, — забор клипов: `cards/_down` считается по числу
MP4, а не по числу файлов и каталогов (там лежат `report.json` и пустые
каталоги прогонов, из-за них забор печатает «клип на месте» без клипа).

Гоняется ПЕРЕД дашбордом, ничего не меняет:
    python3 template/sverka_kartochek.py <ролик>.scenes.json
    python3 template/sverka_kartochek.py <ролик>.scenes.json --proekt <папка>
Код возврата 1 — есть сцены без задания (дашборд не отдавать).
"""
import argparse
import glob
import json
import os
import sys

# Вид → чем ставится. Всё, чего нет в таблице, ставится `card_put.py`.
ДРУГАЯ_ДВЕРЬ = {
    "poster": ("A6", "element_put.py"),
    "bars":   ("A4", "element_put.py"),
    "slider": ("A5", "element_put.py"),
    "wall":   ("A56", "element_put.py"),
    "dof":    ("A64", "element_put.py"),
    "photo":  ("A34", "style_card.py"),
}


def сцены(путь):
    with open(путь, encoding="utf-8") as f:
        д = json.load(f)
    return д.get("scenes", д) if isinstance(д, dict) else д


def главное():
    p = argparse.ArgumentParser(description="сверка сцен card:* с заданиями и кадрами")
    p.add_argument("scenes", help="файл <ролик>.scenes.json")
    p.add_argument("--proekt", default="", help="папка проекта (по умолчанию — папка scenes.json)")
    p.add_argument("--tiho", action="store_true", help="печатать только проблемы")
    a = p.parse_args()

    корень = a.proekt or os.path.dirname(os.path.abspath(a.scenes)) or "."
    очередь = os.path.join(корень, "cards", "queue")
    кадры = os.path.join(корень, "cards")
    забор = os.path.join(корень, "cards", "_down")

    без_задания, без_кадра, готовы = [], [], []
    for с in сцены(a.scenes):
        источник = str(с.get("source", ""))
        if not источник.startswith("card:"):
            continue
        вид = источник[5:]
        try:
            sid = int(с.get("id", 0))
        except (TypeError, ValueError):
            continue
        имя = "scene_%03d" % sid
        задание = os.path.join(очередь, имя + ".json")
        кадр = os.path.join(кадры, имя + ".jpg")
        клип = glob.glob(os.path.join(забор, "**", имя + "*.mp4"), recursive=True)
        if not os.path.exists(задание):
            без_задания.append((sid, вид))
        elif not (os.path.exists(кадр) or клип):
            без_кадра.append((sid, вид))
        else:
            готовы.append((sid, вид))

    всего = len(без_задания) + len(без_кадра) + len(готовы)
    if not a.tiho:
        print("сцен card:* — %d: готовы %d · без кадра %d · БЕЗ ЗАДАНИЯ %d"
              % (всего, len(готовы), len(без_кадра), len(без_задания)))

    if os.path.isdir(забор):
        mp4 = len(glob.glob(os.path.join(забор, "**", "*.mp4"), recursive=True))
        файлов = len(os.listdir(забор))
        if файлов and not mp4:
            print("!! cards/_down: файлов и каталогов %d, а MP4 ни одного — "
                  "забор решит, что клипы уже на месте. Лечение: "
                  "rm -rf cards/_down и забрать прогон заново." % файлов)
        elif not a.tiho:
            print("cards/_down: MP4 %d (всего записей в папке %d)" % (mp4, файлов))

    if без_кадра:
        print("\nЗАДАНИЕ ЕСТЬ, КАДРА НЕТ — ждут облачного прогона карточек:")
        for sid, вид in без_кадра:
            print("  сцена %-3d card:%s" % (sid, вид))

    if без_задания:
        print("\nБЕЗ ЗАДАНИЯ — В РОЛИКЕ НА ЭТИХ МЕСТАХ ПУСТОТА, гейт их засчитывает:")
        for sid, вид in без_задания:
            if вид in ДРУГАЯ_ДВЕРЬ:
                код, дверь = ДРУГАЯ_ДВЕРЬ[вид]
                print("  сцена %-3d card:%-10s вид НЕ у `card_put.py` — это %s, "
                      "ставить: python3 template/%s %s %d %s"
                      % (sid, вид, код, дверь, os.path.basename(a.scenes), sid,
                         вид if дверь == "style_card.py" else код))
            else:
                print("  сцена %-3d card:%-10s задание не создалось — повтори "
                      "`card_put.py %s %d %s` и смотри его вывод"
                      % (sid, вид, os.path.basename(a.scenes), sid, вид))
        print("\nДашборд не отдавать, пока список не опустеет или сцены не "
              "переведены на другой источник.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(главное())
