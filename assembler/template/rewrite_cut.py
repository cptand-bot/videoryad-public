#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СОКРАЩЕНИЕ ВТОРОЙ СТАТЬИ: РЕШАЕМ МЫ, А НЕ АГЕНТ (08.11.2026).

Его слово, когда я пересказал, как сокращал текст: «ты ему не давай запрос
„просил убрать 1100 знаков“. Так не делается. Ты ему конкретно говори, что
убрать. Ты же сам решил, что нужно убрать — так и пиши: убрать то-то, то-то,
то-то. Всё».

ПОЧЕМУ ЭТО ВЕРНО, ЗАМЕР ДНЯ: задание «убери столько-то знаков» возвращалось
почти нетронутым три раза подряд — из 1100 знаков агент убрал 225, из 3895
убрал 471. Арифметику он не выполняет; закрытую команду выполняет. Это тот же
принцип, что у аудита: «точные и конкретные инструкции, в жёстких рамках, не
давать свободы действий».

ПОРЯДОК РАБОТЫ:
    1) python3 rewrite_cut.py <текст.txt> --спиcок
       печатает абзацы с номерами, длиной и первой строкой — по ним видно
       повторы и подводки;
    2) глазами выбираем, ЧТО выбросить;
    3) python3 rewrite_cut.py <текст.txt> --убрать 8,19,24 --out <готово.txt>
       режет ровно названные абзацы и показывает, сколько стало.

Инструмент НИЧЕГО не решает сам: он не угадывает «лишнее» и не ужимает фразы.
Решение — наше, его дело выполнить и посчитать. Неприкосновенное (авторские
мысли, шутки, числа, утверждённый крючок, два призыва подписаться) он
проверяет после реза и предупреждает, если призывов стало меньше двух или
крючок уехал.
"""

import argparse
import io
import os
import re
import sys


def читать(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", "replace")


def main():
    ap = argparse.ArgumentParser(description="сократить вторую статью названными абзацами")
    ap.add_argument("text")
    ap.add_argument("--спиcок", "--list", action="store_true", dest="show",
                    help="напечатать абзацы с номерами и длиной")
    ap.add_argument("--убрать", "--drop", default="", dest="drop",
                    help="номера абзацев через запятую")
    ap.add_argument("--out", default="")
    ap.add_argument("--цель", "--target", type=int, default=0, dest="target",
                    help="сколько знаков должно остаться (для подсказки)")
    a = ap.parse_args()

    if not os.path.isfile(a.text):
        sys.exit("нет файла: %s" % a.text)
    t = читать(a.text)
    абзацы = [p for p in t.split("\n") if p.strip()]

    if a.show or not a.drop:
        print("абзацев: %d, знаков: %d" % (len(абзацы), len(t)))
        if a.target:
            print("цель: %d знаков — резать %d" % (a.target, max(0, len(t) - a.target)))
        for i, p in enumerate(абзацы):
            print("%3d [%4d] %s" % (i, len(p), p[:100]))
        if not a.drop:
            print("\nдальше: --убрать 8,19,24 --out <готово.txt>")
        return 0

    номера = set()
    for кусок in a.drop.replace(" ", "").split(","):
        if not кусок:
            continue
        if "-" in кусок:
            a1, a2 = кусок.split("-", 1)
            номера.update(range(int(a1), int(a2) + 1))
        else:
            номера.add(int(кусок))

    плохие = [n for n in номера if n < 0 or n >= len(абзацы)]
    if плохие:
        sys.exit("таких абзацев нет: %s (всего %d)" % (плохие, len(абзацы)))

    оставить = [p for i, p in enumerate(абзацы) if i not in номера]
    новый = "\n".join(оставить).strip() + "\n"

    print("убрано абзацев: %d" % len(номера))
    for n in sorted(номера):
        print("  %3d [%4d] %s" % (n, len(абзацы[n]), абзацы[n][:80]))
    print("было %d знаков → стало %d (минус %d)" % (len(t), len(новый), len(t) - len(новый)))
    if a.target:
        print("цель %d — %s" % (a.target, "уложились" if len(новый) <= a.target
                                else "НЕ уложились, резать ещё %d" % (len(новый) - a.target)))

    cta = len(re.findall("подпиш", новый, re.I))
    if cta < 2:
        print("  !! призывов подписаться осталось %d, по правилу их ДВА" % cta)
    if абзацы and абзацы[0] not in оставить:
        print("  !! УБРАН ПЕРВЫЙ АБЗАЦ — проверь, не был ли это утверждённый крючок")
    if новый.count("—"):
        print("  !! в тексте появились тире (%d) — их быть не должно" % новый.count("—"))

    if not a.out:
        print("\n--out не задан, файл не записан")
        return 0
    io.open(a.out, "w", encoding="utf-8").write(новый)
    print("готово: %s" % a.out)
    print("дальше: rewrite_lint.py <оригинал> %s --brief ЗАДАНИЕ-РЕРАЙТ.txt" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
