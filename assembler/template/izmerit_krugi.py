#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ИЗМЕРЕНИЕ КРУГОВ ФЕТЧА — добор / штатный круг / форс (24.11.2026).

Зачем: разбор «быстрого сборщика» 24.11 показал, что то, что выглядит как
«слишком много мелких заходов в облако», на деле почти всегда — штатные
круги (бюджет 2, см. `refetch.py:ROUND_BUDGET`) плюс отдельные ВЫНУЖДЕННЫЕ
правки реального брака (`--force`, жёсткое нарушение). Батчить форсированные
находки в одну партию — значит откладывать уже найденный брак, этого делать
нельзя (его прямое слово по аналогии с субтитрами). Этот скрипт считает,
сколько на самом деле форса, а не штатной работы — чтобы не чинить то,
что чинить не нужно.

Использование:
    cd ~/projects && python3 ~/.claude/skills/news-video/template/izmerit_krugi.py
    python3 izmerit_krugi.py --dir ~/projects --limit 15
    python3 izmerit_krugi.py planeta-1-xxx 5min-2-yyy   # конкретные проекты

Печатает: по каждому проекту — добор/штатных/форс/всего кругов, причины
форса дословно; в конце — сводку и долю форсированных от небазовых кругов.

ПОВТОРЯТЬ ЗАВТРА НА ВСЕХ ШЕСТИ ТРУБАХ (его прямое поручение 24.11): после
каждого нового ролика на каждой трубе — просто `cd ~/projects && python3
.../izmerit_krugi.py` без аргументов, возьмёт 15 последних папок по mtime.
Копить числа в `D:\\YouTube\\НОВОСТИ\\БЫСТРЫЙ-СБОРЩИК-СОСТОЯНИЕ.txt` вручную
(этот скрипт сам туда не пишет — он печатает в терминал, запись делает тот,
кто его зовёт)."""
import glob
import json
import os
import sys


def load_rounds(proj_dir):
    p = os.path.join(proj_dir, ".refetch_rounds.json")
    if not os.path.isfile(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("  !! не читается %s: %s" % (p, e), file=sys.stderr)
        return None


def classify(rounds):
    fill = budget = forced = 0
    reasons = []
    for r in rounds:
        if r.get("force"):
            forced += 1
            reasons.append(r["force"])
        elif r.get("fill"):
            fill += 1
        else:
            budget += 1
    return fill, budget, forced, reasons


def append_log(proj_dir, log_path):
    """ОДНА строка в копящийся лог — звать из get.sh после КАЖДОГО забора,
    автоматически, без участия человека (его прямое требование 24.11:
    «150% гарантий, что это заведётся и будет работать» — файл, который
    кто-то должен прочитать и вспомнить, такой гарантии не даёт, код,
    который обязан выполниться при заборе ролика, — даёт).

    НИКОГДА не падает и не шумит — это побочный эффект, а не часть
    критического пути get.sh. Пустой/отсутствующий .refetch_rounds.json —
    тихо выходим (fetch-only до первого круга, или круги не нужны были)."""
    import datetime
    try:
        d = load_rounds(proj_dir)
        if d is None:
            return
        fill, budget, forced, reasons = classify(d.get("rounds", []))
        total = fill + budget + forced
        if total == 0:
            return
        name = os.path.basename(os.path.abspath(proj_dir))
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        line = "%s\t%s\tдобор=%d\tштатн=%d\tфорс=%d\tвсего=%d" % (
            ts, name, fill, budget, forced, total)
        if reasons:
            line += "\t" + " | ".join(r.strip()[:80] for r in reasons)
        os.makedirs(os.path.dirname(log_path), exist_ok=True) if os.path.dirname(log_path) else None
        is_new = not os.path.exists(log_path)
        with open(log_path, "a", encoding="utf-8") as f:
            if is_new:
                f.write("# время\tпроект\tдобор\tштатн\tфорс\tвсего\tпричины force\n")
            f.write(line + "\n")
    except Exception:
        pass    # побочный эффект: тихо глотаем любую ошибку, get.sh не падает


def main():
    args = sys.argv[1:]
    base = "."
    limit = 15
    names = []
    i = 0
    while i < len(args):
        if args[i] == "--append-log":
            # --append-log <папка_проекта> <путь_к_логу> — одна строка, тихо
            append_log(args[i + 1], args[i + 2])
            return
        if args[i] == "--dir":
            base = args[i + 1]; i += 2
        elif args[i] == "--limit":
            limit = int(args[i + 1]); i += 2
        else:
            names.append(args[i]); i += 1

    if not names:
        cands = []
        for p in glob.glob(os.path.join(base, "*", ".refetch_rounds.json")):
            cands.append((os.path.getmtime(p), os.path.dirname(p)))
        cands.sort(reverse=True)
        names = [os.path.basename(d) for _t, d in cands[:limit]]

    tot_fill = tot_budget = tot_forced = 0
    all_reasons = {}
    print("%-45s %6s %6s %6s %6s" % ("проект", "добор", "штатн", "форс", "всего"))
    for name in names:
        d = load_rounds(os.path.join(base, name))
        if d is None:
            continue
        fill, budget, forced, reasons = classify(d.get("rounds", []))
        total = fill + budget + forced
        tot_fill += fill; tot_budget += budget; tot_forced += forced
        print("%-45s %6d %6d %6d %6d" % (name, fill, budget, forced, total))
        for r in reasons:
            key = r.strip()
            all_reasons[key] = all_reasons.get(key, 0) + 1

    print()
    denom = tot_budget + tot_forced
    doln = (tot_forced / denom * 100) if denom else 0.0
    print("ИТОГО: добор %d, штатных кругов %d, форсированных %d (%.0f%% от небазовых)"
          % (tot_fill, tot_budget, tot_forced, doln))
    if all_reasons:
        print("\nпричины force:")
        for k, v in sorted(all_reasons.items(), key=lambda x: -x[1]):
            print("  %dx  %s" % (v, k[:90]))


if __name__ == "__main__":
    main()
