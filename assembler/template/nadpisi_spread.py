#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РАЗНООБРАЗИЕ НАДПИСЕЙ-СЛОВ: ЦВЕТ И МЕСТО, А НЕ «ВСЁ БЕЛОЕ СВЕРХУ».

Его слово 08.11.2026 по готовому дашборду: «Снова тексты идут одного цвета.
Только белый и только предлагается позиция вверху. Ни справа, ни слева, ни в
середине… Старая грабли, короче».

ЗАМЕР НА ТОМ САМОМ РОЛИКЕ: 31 надпись, из них 20 белых и 26 в одной клетке
`tc` (вверху по центру). Дашборд при этом честно предлагает ПЯТЬ цветов и
ДЕВЯТЬ клеток — выбор есть, им просто никто не пользуется: вкладка ставит
надписи пачкой с одним значением по умолчанию, и так из ролика в ролик.
Поэтому разнообразие теперь не «надо не забыть», а инструмент.

ЧТО ДЕЛАЕТ. Проходит по текстовым всплывашкам `overlays.json` и
переназначает ЦВЕТ и МЕСТО так, чтобы:
  · ни один цвет не занимал больше трети надписей;
  · ни одна клетка не занимала больше трети;
  · соседние надписи не повторяли ни цвет, ни клетку;
  · низ не использовался вообще (там субтитры), только верх и середина.
СЛОВА, ЗВУК, МОМЕНТ ПОЯВЛЕНИЯ И МАСШТАБ НЕ ТРОГАЕТ — это работа вкладки.

ЦВЕТА БЕРУТСЯ ПО КАНАЛУ: у «5 МИНУТ» золото и красный ведущие, у ПЛАНЕТЫ
сталь и зелень — те же пары, что у данных на карточках, чтобы ролик читался
одним набором ([[reference_channel_palettes]] в памяти).

    python3 nadpisi_spread.py <overlays.json> [--scenes <scenes.json>] [--dry-run]
"""

import argparse
import io
import json
import os
import sys

# Клетки без нижнего ряда: внизу идут субтитры (правило 06.11).
КЛЕТКИ = ("tc", "tl", "mc", "tr", "ml", "mr")

# Ведущие цвета канала. Белый остаётся в наборе, но перестаёт быть
# единственным: он идёт наравне с остальными.
# ТОЛЬКО ИМЕНА ИЗ НАБОРА ДАШБОРДА, НЕ HEX (08.11, поймано через час после
# первой версии, улов `usuario-45`). Первая версия ставила цвета вида
# «#ffd23f» — дашборд их не знает: в `review.py` цвет сверяется со списком
# `TEXT_COLORS` (white/yellow/red/green/orange), и всё, чего там нет, молча
# заменяется цветом «по кругу от номера сцены». То есть стоило ему тронуть
# панель надписи — и разведение откатывалось к белому. Вкладка увидела это
# как «утверждение дашборда откатывает разведение»: 34% снова стали 76%.
# Правило: инструмент и дашборд обязаны говорить на одном наборе цветов.
ЦВЕТА = {
    "5 МИНУТ": ("yellow", "white", "red", "orange", "green", "yellow"),
    "ПЛАНЕТА": ("white", "green", "yellow", "orange", "white", "red"),
    "": ("white", "yellow", "red", "green", "orange", "white"),
}


def канал(scenes_path):
    try:
        d = json.load(io.open(scenes_path, encoding="utf-8"))
        if isinstance(d, dict):
            return str(d.get("channel") or "").upper()
    except Exception:
        pass
    return ""


def main():
    ap = argparse.ArgumentParser(description="развести надписи по цвету и месту")
    ap.add_argument("overlays")
    ap.add_argument("--scenes", default="", help="scenes.json — из него берётся канал")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.overlays):
        sys.exit("нет файла: %s" % a.overlays)
    data = json.load(io.open(a.overlays, encoding="utf-8"))

    scenes = a.scenes
    if not scenes:
        рядом = [f for f in os.listdir(os.path.dirname(a.overlays) or ".")
                 if f.endswith(".scenes.json") and "overlays_fetch" not in f]
        scenes = os.path.join(os.path.dirname(a.overlays) or ".", рядом[0]) if рядом else ""
    ch = канал(scenes) if scenes else ""
    палитра = ЦВЕТА.get(ch, ЦВЕТА[""])

    # по порядку сцен, иначе «соседние» теряют смысл
    номера = sorted((k for k in data if str(k).isdigit()), key=lambda x: int(x))
    надписи = [k for k in номера
               if isinstance(data.get(k), dict) and isinstance(data[k].get("text"), dict)]
    if not надписи:
        print("текстовых всплывашек нет — править нечего")
        return 0

    было_цвет = {}
    было_место = {}
    for k in надписи:
        t = data[k]["text"]
        было_цвет[t.get("color", "(нет)")] = было_цвет.get(t.get("color", "(нет)"), 0) + 1
        было_место[t.get("pos", "(нет)")] = было_место.get(t.get("pos", "(нет)"), 0) + 1

    пред_цвет = пред_место = None
    стало_цвет, стало_место = {}, {}
    for i, k in enumerate(надписи):
        t = data[k]["text"]
        # МАСКА — ЭТО ЗАГОЛОВОК БЛОКА, А НЕ НАДПИСЬ-СЛОВО. У неё свои цвет и
        # место по каналу, трогать нельзя (правило 07.11).
        if str(t.get("style") or "").startswith("mask"):
            continue
        цвет = палитра[i % len(палитра)]
        if цвет == пред_цвет:
            цвет = палитра[(i + 1) % len(палитра)]
        место = КЛЕТКИ[i % len(КЛЕТКИ)]
        if место == пред_место:
            место = КЛЕТКИ[(i + 1) % len(КЛЕТКИ)]
        t["color"], t["pos"] = цвет, место
        пред_цвет, пред_место = цвет, место
        стало_цвет[цвет] = стало_цвет.get(цвет, 0) + 1
        стало_место[место] = стало_место.get(место, 0) + 1

    n = sum(стало_место.values())
    print("надписей: %d (канал %s)" % (len(надписи), ch or "не задан"))
    print("  было цветов: %s" % было_цвет)
    print("  было мест:   %s" % было_место)
    print("  стало цветов: %s" % стало_цвет)
    print("  стало мест:   %s" % стало_место)
    if n:
        print("  доля самого частого цвета: %d%%, места: %d%%"
              % (round(100 * max(стало_цвет.values()) / n),
                 round(100 * max(стало_место.values()) / n)))

    if a.dry_run:
        print("--dry-run: файл не записан")
        return 0
    json.dump(data, io.open(a.overlays, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("записано: %s" % a.overlays)
    print("дальше: перерисовать надписи (build_overlays.py) и обновить дашборд")
    return 0


if __name__ == "__main__":
    sys.exit(main())
