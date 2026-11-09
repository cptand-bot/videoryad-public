#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brak.py — СТАЛО ЛИ МЕНЬШЕ БРАКА. Ответ числом, по журналам роликов.

    python3 brak.py                 # все ролики за 3 суток + сравнение до/после
    python3 brak.py --dni 7
    python3 brak.py <папка проекта>  # один ролик

Он спрашивает словами «проверь брак» — и должен получить ОДНУ строку: стало
меньше или нет. Повод (09.11): вечером правлен выбор кадра — чистота углов
вошла в счёт кандидата, а замена из запаса берёт первый ЧИСТЫЙ, а не самый
большой. Обещано: брак первого прохода 28-48% → ниже 20%, повторные замены
25-36% → ниже 10%. Проверяется ТОЛЬКО замером, не ощущением.

ЧТО СЧИТАЕТСЯ (всё из `<проект>/.refetch_rounds.json`, который ведёт refetch):
  сцен        — сколько сцен в ролике (из <проект>.scenes.json);
  заменено    — сколько сцен пришлось менять ХОТЯ БЫ РАЗ = БРАК ПЕРВОГО
                ПРОХОДА: столько кадров поиск отдал негодными;
  повторных   — сколько из заменённых пришлось менять ДВА и больше раз: это
                брак САМОЙ ЗАМЕНЫ, то есть прямая цена старого выбора
                «по площади»;
  кругов      — заходов на правку; круг стоит ~3 минуты и ~150 К токенов
                независимо от числа кадров в нём.

Замены, которые пользователь делает руками на дашборде, здесь НЕ видны и
кругом не считаются (его слово 04.11) — считается только работа вкладки.
"""
import argparse
import datetime
import glob
import json
import os
import sys

РУБЕЖ = os.environ.get("VIDEORYAD_BRAK_RUBEZH", "2026-11-09 20:00")
ЦЕЛЬ_БРАК = 20.0
ЦЕЛЬ_ПОВТОР = 10.0


def сцен_в_проекте(p):
    for f in sorted(glob.glob(os.path.join(p, "*.scenes.json"))):
        if f.endswith(".iz_oblaka"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        sc = d.get("scenes") if isinstance(d, dict) else d
        if isinstance(sc, list) and sc:
            return len(sc)
    return 0


def разбор(p):
    j = os.path.join(p, ".refetch_rounds.json")
    if not os.path.exists(j):
        return None
    try:
        d = json.load(open(j, encoding="utf-8"))
    except Exception:
        return None
    rounds = d.get("rounds") or []
    tried = d.get("tried") or {}
    сцены = сцен_в_проекте(p)
    заменено = len([k for k in tried if k.startswith("images:")]) or \
        len({i for r in rounds for i in (r.get("ids") or []) if i.startswith("images:")})
    повторных = len([k for k, v in tried.items()
                     if k.startswith("images:") and isinstance(v, list) and len(v) > 1])
    когда = ""
    for r in rounds:
        когда = r.get("ts", "") or когда
    if not когда:
        когда = datetime.datetime.fromtimestamp(os.path.getmtime(j)).strftime("%Y-%m-%d %H:%M")
    return {"проект": os.path.basename(p), "когда": когда, "сцен": сцены,
            "заменено": заменено, "повторных": повторных, "кругов": len(rounds)}


def проц(a, b):
    return (100.0 * a / b) if b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", nargs="?", default="")
    ap.add_argument("--dni", type=int, default=3)
    a = ap.parse_args()

    if a.project:
        пути = [os.path.abspath(a.project)]
    else:
        порог = datetime.datetime.now() - datetime.timedelta(days=a.dni)
        пути = [p for p in sorted(glob.glob(os.path.expanduser("~/projects/*")))
                if os.path.isdir(p) and os.path.exists(os.path.join(p, ".refetch_rounds.json"))
                and datetime.datetime.fromtimestamp(
                    os.path.getmtime(os.path.join(p, ".refetch_rounds.json"))) > порог]
    ряды = [r for r in (разбор(p) for p in пути) if r]
    if not ряды:
        print("журналов правок за %d суток нет — ни один ролик пока не чинился" % a.dni)
        return 0

    print("%-34s %-16s %5s %10s %11s %7s" % ("ролик", "когда", "сцен", "заменено", "повторных", "кругов"))
    до, после = [], []
    for r in sorted(ряды, key=lambda x: x["когда"]):
        б = проц(r["заменено"], r["сцен"])
        п = проц(r["повторных"], r["заменено"])
        print("%-34s %-16s %5d %6d %3.0f%% %6d %3.0f%% %7d"
              % (r["проект"][:34], r["когда"][:16], r["сцен"],
                 r["заменено"], б, r["повторных"], п, r["кругов"]))
        (после if r["когда"] >= РУБЕЖ else до).append((б, п, r["кругов"]))

    def свод(xs, имя):
        if not xs:
            print("  %-8s данных нет" % имя)
            return None
        б = sum(x[0] for x in xs) / len(xs)
        п = sum(x[1] for x in xs) / len(xs)
        к = sum(x[2] for x in xs) / len(xs)
        print("  %-8s роликов %d · брак первого прохода %.0f%% · повторных замен %.0f%% · кругов в среднем %.1f"
              % (имя, len(xs), б, п, к))
        return б, п, к

    print("\nСРАВНЕНИЕ (рубеж — правка выбора кадра, %s):" % РУБЕЖ)
    d = свод(до, "ДО:")
    a_ = свод(после, "ПОСЛЕ:")

    print("\nВЕРДИКТ:")
    if not a_:
        print("  рано: после правки не сдан ни один ролик с правками. Нужен хотя бы один,")
        print("  лучше три. Цели: брак первого прохода < %.0f%%, повторные замены < %.0f%%."
              % (ЦЕЛЬ_БРАК, ЦЕЛЬ_ПОВТОР))
        return 0
    б, п, к = a_
    ok_б = б < ЦЕЛЬ_БРАК
    ok_п = п < ЦЕЛЬ_ПОВТОР
    if d:
        print("  брак первого прохода: %.0f%% → %.0f%% (%s)"
              % (d[0], б, "лучше" if б < d[0] else "хуже или так же"))
        print("  повторные замены:     %.0f%% → %.0f%% (%s)"
              % (d[1], п, "лучше" if п < d[1] else "хуже или так же"))
        print("  кругов на ролик:      %.1f → %.1f" % (d[2], к))
    print("  цели %s: брак <%.0f%% — %s · повторные <%.0f%% — %s"
          % ("ВЗЯТЫ" if (ok_б and ok_п) else "НЕ ВЗЯТЫ",
             ЦЕЛЬ_БРАК, "да" if ok_б else "нет",
             ЦЕЛЬ_ПОВТОР, "да" if ok_п else "нет"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
