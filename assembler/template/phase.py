#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase.py — честный секундомер по фазам сборки ролика.

Зачем: 20.10 часы в журнале ставились НА ГЛАЗ и разошлись до двух часов, из-за
чего разбор «куда уходит время» пришлось делать задним числом по mtime файлов и
временам прогонов GitHub. 21.10 пользователь поставил сокращение времени
нулевым приоритетом — спорить об этом «на глаз» нельзя.

    python3 phase.py <проект> srt_получен
    python3 phase.py <проект> сцены_готовы
    python3 phase.py <проект> --report

Пишет в <проект>/.phases.jsonl (по строке на отметку, две вкладки друг другу
не мешают). `--report` печатает длительность каждой фазы, итог и отношение к
хронометражу ролика — ту самую строку, которую надо отдавать при сдаче.

Имена фаз — свободные, но держись набора, иначе ролики не сравнить:
  srt_получен · сцены_готовы · запросы_готовы · фетч_ушёл · фетч_вернулся ·
  аудит_начат · круг_N · дашборд_отдан · утверждён · сборка_ушла · доставлено
"""
import io
import json
import os
import sys
import time

ORDER = ["srt_получен", "сцены_готовы", "запросы_готовы", "фетч_ушёл",
         "фетч_вернулся", "аудит_начат", "дашборд_отдан", "утверждён",
         "сборка_ушла", "доставлено"]


def _path(proj):
    return os.path.join(os.path.expanduser(proj), ".phases.jsonl")


def mark(proj, name):
    rec = {"t": time.time(), "ts": time.strftime("%H:%M:%S"), "phase": name}
    with io.open(_path(proj), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("%s  %s" % (rec["ts"], name))
    return 0


def report(proj):
    p = _path(proj)
    if not os.path.exists(p):
        print("отметок нет (%s)" % p)
        return 1
    rows = [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]
    rows.sort(key=lambda r: r["t"])
    print("%-18s %-9s %s" % ("фаза", "время", "длилось"))
    for i, r in enumerate(rows):
        d = ""
        if i + 1 < len(rows):
            d = "%.1f мин" % ((rows[i + 1]["t"] - r["t"]) / 60.0)
        print("%-18s %-9s %s" % (r["phase"], r["ts"], d))
    total = (rows[-1]["t"] - rows[0]["t"]) / 60.0
    print("-" * 42)
    print("ИТОГО %s → %s: %.1f мин" % (rows[0]["phase"], rows[-1]["phase"], total))
    # отношение к хронометражу — потолок 3×
    import glob
    sc = [f for f in glob.glob(os.path.join(os.path.expanduser(proj), "*.scenes.json"))
          if "overlay" not in os.path.basename(f)]
    if sc:
        try:
            d = json.load(io.open(sc[0], encoding="utf-8"))
            run = sum(s.get("duration_sec", 0) for s in d.get("scenes", [])) / 60.0
            if run:
                print("хронометраж ролика %.1f мин → потолок %.1f мин, факт %.1f мин (%.1f×)"
                      % (run, run * 3, total, total / run))
        except Exception:
            pass
    return 0


def main():
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        return 2
    proj = args[0]
    if len(args) < 2:
        print(__doc__)
        return 2
    if args[1] in ("--report", "-r"):
        return report(proj)
    return mark(proj, args[1])


if __name__ == "__main__":
    sys.exit(main())
