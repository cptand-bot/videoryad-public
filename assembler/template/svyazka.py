#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СВЯЗКА «ЗАГОЛОВОК + НАДПИСИ + ПРЕВЬЮ» И ЕЁ СУДЬБА (08.11.2026).

Его слово: «эти названия, которые я ввожу, и надписи, которые я применяю, это
же не значит, что они на сто процентов уверенно зайдут. Это значит, что вот
этот вариант я выбрал. Как они зайдут или не зайдут на тот или иной канал, мы
будем смотреть уже по статистике, через неделю или за три-четыре дня. Вот там
всё будет понятно: залетела эта связка или не залетела. Эту логику тоже надо
зафиксировать».

ОТСЮДА ДВА РАЗНЫХ ФАКТА, И ПУТАТЬ ИХ НЕЛЬЗЯ:
  1. ЧТО ОН ВЫБРАЛ — пишется само, дашбордом упаковки, в день сборки.
     Это его ВКУС, а не доказательство.
  2. КАК ЭТО ЗАШЛО — приходит через 3-7 дней из статистики канала.
     Только это и есть доказательство.

Поэтому обучение на журнале идёт по трём уровням:
  · ЗАЛЕТЕЛО      — связка с подтверждённой статистикой, главный ориентир;
  · НЕ ЗАШЛО      — тоже подтверждено, идёт в задание как «так не делать»;
  · ПОКА БЕЗ ЗАМЕРА — его выбор без статистики, слабый ориентир.

    python3 svyazka.py --список                 # что ждёт замера
    python3 svyazka.py --ждут                   # только созревшие (3+ дня)
    python3 svyazka.py --замер <id> --просмотры 42000 --вердикт залетело
    python3 svyazka.py --замер <id> --просмотры 4100 --ctr 3.1 --вердикт нет

Результаты ложатся в `upakovka_lib/svyazki.jsonl` и подхватываются
`upakovka.py` при следующей упаковке. Статистику вводит ОН или редакция:
у нас доступа к кабинету канала нет, и выдумывать числа запрещено.
"""

import argparse
import io
import json
import os
import sys
import time

ЗДЕСЬ = os.path.dirname(os.path.abspath(__file__))
ЖУРНАЛ = os.path.join(ЗДЕСЬ, "upakovka_lib", "vybor.jsonl")
СВЯЗКИ = os.path.join(ЗДЕСЬ, "upakovka_lib", "svyazki.jsonl")
ВЕРДИКТЫ = ("залетело", "средне", "нет")


def _читать(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def связки():
    """Собираем связки из журнала выбора: канал + тема = одна связка."""
    по_теме = {}
    for e in _читать(ЖУРНАЛ):
        ключ = "%s|%s" % (e.get("канал", ""), e.get("тема", ""))
        с = по_теме.setdefault(ключ, {
            "id": ключ, "канал": e.get("канал", ""), "тема": e.get("тема", ""),
            "дата": (e.get("когда") or "")[:10],
            "заголовок": "", "надписи": [], "превью": None})
        if e.get("событие") == "превью":
            с["превью"] = e.get("выбран_вариант")
            for поле in ("надпись_сверху", "надпись_снизу"):
                if e.get(поле):
                    с["надписи"].append(e[поле])
        elif str(e.get("событие") or "").startswith("свой_заголов"):
            с["заголовок"] = e.get("выбрано", "")
        elif e.get("событие") == "заголовки" and not с["заголовок"]:
            с["заголовок"] = "(скопировал из списка) " + (e.get("выбрано") or "")
    замеры = {z["id"]: z for z in _читать(СВЯЗКИ)}
    for к, с in по_теме.items():
        с["замер"] = замеры.get(к)
    return list(по_теме.values())


def дней_прошло(дата):
    try:
        t = time.mktime(time.strptime(дата, "%Y-%m-%d"))
        return int((time.time() - t) // 86400)
    except (ValueError, TypeError):
        return 0


def main():
    ap = argparse.ArgumentParser(description="связка заголовок+надписи+превью и её статистика")
    ap.add_argument("--список", "--list", action="store_true", dest="show")
    ap.add_argument("--ждут", action="store_true", help="только созревшие без замера (3+ дня)")
    ap.add_argument("--замер", default="", dest="mark", help="id связки")
    ap.add_argument("--просмотры", type=int, default=0)
    ap.add_argument("--ctr", type=float, default=0.0)
    ap.add_argument("--вердикт", default="", choices=("",) + ВЕРДИКТЫ)
    ap.add_argument("--заметка", default="")
    a = ap.parse_args()

    все = связки()

    if a.mark:
        цель = [с for с in все if с["id"] == a.mark]
        if not цель:
            print("связки с таким id нет. Есть:")
            for с in все:
                print("  %s" % с["id"])
            return 2
        if not a.вердикт and not a.просмотры:
            return print("нужен хотя бы --просмотры или --вердикт") or 2
        запись = {"id": a.mark, "когда": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "просмотры": a.просмотры or None, "ctr": a.ctr or None,
                  "вердикт": a.вердикт or ("залетело" if a.просмотры else ""),
                  "заметка": a.заметка}
        os.makedirs(os.path.dirname(СВЯЗКИ), exist_ok=True)
        with io.open(СВЯЗКИ, "a", encoding="utf-8") as f:
            f.write(json.dumps(запись, ensure_ascii=False) + "\n")
        print("записано: %s — %s%s" % (a.mark, запись["вердикт"],
                                       (", просмотров %d" % a.просмотры) if a.просмотры else ""))
        return 0

    if not все:
        print("связок пока нет: он ещё не выбирал заголовки и превью")
        return 0

    for с in все:
        дней = дней_прошло(с["дата"])
        замер = с.get("замер")
        if a.ждут and (замер or дней < 3):
            continue
        статус = ("ЗАМЕР: %s%s" % (замер["вердикт"],
                                   (", %d просмотров" % замер["просмотры"])
                                   if замер.get("просмотры") else "")
                  if замер else ("ЖДЁТ ЗАМЕРА (%d дн.)" % дней if дней >= 3
                                 else "рано, %d дн." % дней))
        print("· %s" % с["id"])
        print("   заголовок: %s" % (с["заголовок"] or "—"))
        print("   надписи:   %s" % (" / ".join(с["надписи"]) or "—"))
        print("   превью:    %s   %s" % (с["превью"] or "—", статус))
    if a.ждут:
        print("\nвписать результат: svyazka.py --замер \"<id>\" --просмотры N --вердикт залетело")
    return 0


if __name__ == "__main__":
    sys.exit(main())
