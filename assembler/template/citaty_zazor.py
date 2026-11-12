#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЦИТАТЫ НЕ ИДУТ ПОДРЯД — зазор минимум одна НЕцитатная сцена.

Его правка 12.11 по дашборду 8795 (сцены 4 strike + 5 marker_serif +
6 paper_typed шли встык), дословно: «вот прям подряд цитаты, цитаты, цитаты.
Не надо цитаты прям подряд. Лучше хотя бы через раз. Цитата, потом идёт
какая-то другая наша карточка, там цитата, опять другая наша карточка. А то
мы одни цитаты подряд влупим, и будет как презентация PowerPoint. Я такого
не хочу».

ЧТО СЧИТАЕТСЯ ЦИТАТОЙ. Виды, которые показывают ЧЬИ-ТО СЛОВА текстом на
экране: `quote`, `split`, `pull`, `marker_serif`, `strike`, `tape`,
`paper_typed`, `paper_hand`, `duel`, `doc`. Сцены зала (`card:zal*`) в семью
НЕ входят: там объёмный павильон, а не лист с текстом, и по виду он от
цитаты отличается полностью.

ЧЕМ ЛЕЧИТЬ. В паре подряд ОДНУ сцену переводить на нецитатный вид по смыслу
её текста: три числовых факта — `bars`/`slope`/`pie`/`waterfall`; связь
событий — `wall`/`network`; место — `map`/`map_regions`/`map_dist`; один
человек или предмет — `dof`/`film_frame`/`vyrezka`; экран устройства —
`device`. Снятый вид верни на другую сцену, иначе отобьёт
`obyazatelno.py --gate dashboard`.

Зовётся вкладкой и ГЕЙТОМ `selfcheck.py`:
    python3 template/citaty_zazor.py <ролик>.scenes.json
Код возврата 1 — есть цитаты подряд, дашборд не отдавать.
"""
import argparse
import json
import os
import sys

СЕМЬЯ = ("quote", "split", "pull", "marker_serif", "strike", "tape",
         "paper_typed", "paper_hand", "duel", "doc")

ЗАМЕНА = ("числа в тексте — bars/slope/pie/waterfall · связь событий — "
          "wall/network · место — map/map_regions/map_dist · один человек "
          "или предмет — dof/film_frame/vyrezka · экран — device")


def _вид(с):
    и = str(с.get("source", ""))
    return и[5:] if и.startswith("card:") else ""


def сцены(путь):
    with open(путь, encoding="utf-8") as f:
        д = json.load(f)
    return д.get("scenes", д) if isinstance(д, dict) else д


def пары(список):
    """Соседние сцены, обе из цитатной семьи. Список кортежей ((id,вид),(id,вид))."""
    найдено, пред = [], None
    for с in список:
        try:
            i = int(с.get("id", 0))
        except (TypeError, ValueError):
            continue
        в = _вид(с)
        если_цитата = в in СЕМЬЯ
        if если_цитата and пред and пред[0] == i - 1:
            найдено.append((пред, (i, в)))
        пред = (i, в) if если_цитата else None
    return найдено


def нарушения(путь_scenes):
    """Для гейта: список строк-отказов (пустой — чисто)."""
    try:
        п = пары(сцены(путь_scenes))
    except (OSError, ValueError) as e:
        return ["цитатный зазор: не прочитать %s (%s)" % (путь_scenes, e)]
    if not п:
        return []
    куски = ", ".join("%d %s + %d %s" % (a[0], a[1], b[0], b[1]) for a, b in п)
    return ["ЦИТАТЫ ПОДРЯД (его правка 12.11, зазор минимум одна нецитатная "
            "сцена): %s. В каждой паре одну сцену на нецитатный вид — %s. "
            "Снятый вид верни на другую сцену." % (куски, ЗАМЕНА)]


def главное():
    p = argparse.ArgumentParser(description="цитаты не идут подряд")
    p.add_argument("scenes", help="файл <ролик>.scenes.json")
    p.add_argument("--tiho", action="store_true", help="печатать только нарушения")
    a = p.parse_args()

    список = сцены(a.scenes)
    цит = [(int(с["id"]), _вид(с)) for с in список if _вид(с) in СЕМЬЯ]
    п = пары(список)
    if not a.tiho:
        print("цитатных карточек %d из %d сцен" % (len(цит), len(список)))
    if not п:
        if not a.tiho:
            print("✅ подряд ни одной — зазор соблюдён")
        return 0
    print("❌ ЦИТАТЫ ПОДРЯД — %d мест%s:" % (len(п), "о" if len(п) == 1 else ""))
    for a_, b_ in п:
        print("  сцена %-3d card:%-13s + сцена %-3d card:%s" % (a_[0], a_[1], b_[0], b_[1]))
    print("\nВ каждой паре ОДНУ сцену перевести на нецитатный вид по смыслу "
          "её текста:\n  %s" % ЗАМЕНА)
    print("Сцены зала (`card:zal*`) цитатой НЕ считаются — ими разбивать можно.")
    print("Снятый вид верни на другую сцену, иначе отобьёт "
          "`obyazatelno.py --gate dashboard`.")
    return 1


if __name__ == "__main__":
    sys.exit(главное())
