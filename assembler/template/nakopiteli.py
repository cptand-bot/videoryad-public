#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СТОРОЖ НАКОПИТЕЛЕЙ: КТО МОЛЧИТ И СКОЛЬКО ДНЕЙ (15.11.2026).

Его слово: «я чокнусь каждый пункт тебя контролировать, у меня нет столько
памяти в башке, и у тебя тоже нет».

Накопителей восемь, и половина из них наполняется ИНСТРУМЕНТОМ, который
зовёт человек, — значит не наполняется никем. На 15.11: `vybor.jsonl` жил и
рос каждый день (144 записи), а `svyazki.jsonl` стоял на ОДНОЙ записи с
08.11 и `avtorskoe.jsonl` на трёх. Обнаружилось это случайно, на его
вопросе, через неделю после начала.

Сторож печатает по каждому: сколько записей, когда последняя, сколько дней
молчит и ЧТО ИМЕННО не делается. Зовётся сам из `smena.sh` каждое утро.

    python3 template/nakopiteli.py            # таблица
    python3 template/nakopiteli.py --tiho     # только молчащие (для смены)
"""
import argparse, io, json, os, sys, time

ЛИБА = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upakovka_lib")

# файл · норма молчания в днях · что это значит, если молчит
НАКОПИТЕЛИ = [
    ("vybor.jsonl", 1,
     "его выбор заголовков и превью на дашборде 8811/8820 — пишет сам дашборд"),
    ("svyazki.jsonl", 2,
     "связка «заголовок + надписи + превью» и её судьба; без неё через "
     "3-7 дней НЕЧЕГО сверять со статистикой — `svyazka.py --dobavit`"),
    ("avtorskoe.jsonl", 3,
     "его мысли после прослушивания; уходят в КАЖДОЕ задание писателю — "
     "`avtorskoe.py dobav`"),
    ("codex_zahody.tsv", 1, "заходы к внешнему агенту (окно пятичасовое)"),
    ("bank.txt", 14, "его библиотека формулировок"),
    ("slova.json", 14, "словарь из его текстов, им ловятся опечатки"),
]


def строк(путь):
    try:
        if путь.endswith(".json"):
            d = json.load(io.open(путь, encoding="utf-8"))
            return len(d) if isinstance(d, (list, dict)) else 1
        with io.open(путь, encoding="utf-8", errors="replace") as f:
            return sum(1 for s in f if s.strip())
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiho", action="store_true", help="только молчащие")
    a = ap.parse_args()
    сейчас = time.time()
    молчат = []
    if not a.tiho:
        print("НАКОПИТЕЛИ УПАКОВКИ:")
    for имя, норма, смысл in НАКОПИТЕЛИ:
        п = os.path.join(ЛИБА, имя)
        если_нет = not os.path.exists(п)
        н = строк(п) if not если_нет else 0
        дней = 999 if если_нет else (сейчас - os.path.getmtime(п)) / 86400.0
        плохо = дней > норма
        if плохо:
            молчат.append((имя, н, дней, смысл))
        if not a.tiho:
            print("  %-18s %5d зап. · молчит %4.1f дн. (норма %d) %s"
                  % (имя, н, min(дней, 999), норма, "← МОЛЧИТ" if плохо else ""))
    if молчат:
        print("")
        print("НЕ НАПОЛНЯЕТСЯ (%d из %d):" % (len(молчат), len(НАКОПИТЕЛИ)))
        for имя, н, дней, смысл in молчат:
            print("  %s — записей %d, молчит %.0f дн." % (имя, н, дней))
            print("      %s" % смысл)
        print("")
        print("Накопитель, который наполняет ЧЕЛОВЕК, не наполняется никем:")
        print("вшей вызов в фазу или в дашборд, а не записывай себе в память.")
        return 1
    if not a.tiho:
        print("\nвсе накопители живые")
    return 0


if __name__ == "__main__":
    sys.exit(main())
