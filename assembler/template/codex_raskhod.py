#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РАСХОД ОКНА ВНЕШНЕГО АГЕНТА — ЧТОБЫ РАЗНОСИТЬ ЗАХОДЫ (08.11.2026).

Его уточнение: у Codex ПЯТИЧАСОВОЕ окно, не дневная квота. Значит три
раскадровки и три аудита подряд съедают его за один присест, а дальше сорок
минут простоя. Разносить заходы можно, только если их видно.

`codex_ask.sh` пишет строку на каждый вызов (время, задание, размер ответа).
Этот инструмент показывает, сколько заходов было за последние пять часов и
когда был первый — от него и считается сброс.

    python3 codex_raskhod.py          # последние пять часов
    python3 codex_raskhod.py --все    # весь журнал
"""

import argparse
import io
import os
import sys
import time

ЖУРНАЛ = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "upakovka_lib", "codex_zahody.tsv")


def main():
    ap = argparse.ArgumentParser(description="расход окна внешнего агента")
    ap.add_argument("--все", action="store_true", dest="all")
    ap.add_argument("--часов", type=float, default=5.0, dest="hours")
    a = ap.parse_args()
    if not os.path.exists(ЖУРНАЛ):
        print("журнал заходов пуст — ни одного вызова ещё не было")
        return 0
    порог = time.time() - a.hours * 3600
    строки = []
    for line in io.open(ЖУРНАЛ, encoding="utf-8"):
        части = line.rstrip("\n").split("\t")
        if len(части) < 2:
            continue
        try:
            t = time.mktime(time.strptime(части[0], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        if a.all or t >= порог:
            строки.append((t, части[0][11:16], части[1],
                           части[2] if len(части) > 2 else "?"))
    if not строки:
        print("за последние %.0f ч заходов не было — окно свободно" % a.hours)
        return 0
    print("заходов за последние %.0f ч: %d" % (a.hours, len(строки)))
    for _, когда, задание, размер in строки:
        print("  %s  %-44s ответ %s байт" % (когда, задание[:44], размер))
    первый = строки[0][0]
    сброс = первый + a.hours * 3600
    осталось = int((сброс - time.time()) // 60)
    print("окно отсчитывается от %s; если упрётся — освободится примерно в %s"
          % (строки[0][1], time.strftime("%H:%M", time.localtime(сброс))))
    if осталось > 0:
        print("то есть через %d мин" % осталось)
    return 0


if __name__ == "__main__":
    sys.exit(main())
