#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЖУРНАЛ ЗАМЕЧАНИЙ ПОЛЬЗОВАТЕЛЯ — ОДИН НА ВЕСЬ КОНВЕЙЕР (10.11.2026).

ПОВОД, ЕГО СЛОВА: «По дашбордам во вкладках, там проектов, ты принял,
записал или ей придётся записывать? Вот этот момент мне не нравится.
Здесь какая-то дыра. Ты можешь ещё не записать, а она может уже не
записать».

ДЫРА БЫЛА РЕАЛЬНАЯ. Его замечание по дашборду ролика жило только в
переписке: вкладка → координатор → правка кода. На смене координатора
(а она идёт каждые 250 запросов) оно теряется дважды: прежний не успел
записать, новый про него не знает. Файл состояния этого не ловит — он
про ролики, а не про сказанное.

ТЕПЕРЬ: замечание пишет ТА ЖЕ ВКЛАДКА, которой он его сказал, ОДНОЙ
командой и ДО того, как понесёт координатору. Журнал лежит в скилле,
живёт дольше любой вкладки, и `smena.sh` печатает незакрытые первым
блоком — новый координатор видит их сам, без передачи словами.

    python3 zamechanie.py dobav --slova "дословно его слова" \\
        --kanal "5 МИНУТ" --tema "2-ЗЕ готов в Антарктиде" \\
        --gde "дашборд 8792, сцена 3" [--chto "что уже сделала вкладка"]
    python3 zamechanie.py spisok            # незакрытые
    python3 zamechanie.py spisok --vse      # все
    python3 zamechanie.py zakryl Z-0007 --chem "card_put снимает метку"
    python3 zamechanie.py povtor Z-0007 --slova "сказал второй раз"

ПОВТОР — НЕ НОВАЯ ЗАПИСЬ (правило журнала режиссёра, 08.11): счётчик
растёт, запись поднимается в начало, и это ошибка нашего процесса.
"""
import argparse
import json
import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
БАЗА = os.path.join(os.path.dirname(HERE), "base")
ФАЙЛ = os.path.join(БАЗА, "zamechaniya.json")
ГЛАЗАМИ = os.path.join(os.path.dirname(HERE), "ЗАМЕЧАНИЯ-ЖИВЫЕ.md")


def читать():
    try:
        return json.load(open(ФАЙЛ, encoding="utf-8"))
    except (OSError, ValueError):
        return {"версия": 1, "записи": []}


def писать(d):
    os.makedirs(БАЗА, exist_ok=True)
    tmp = ФАЙЛ + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, ФАЙЛ)
    _глазами(d)


def _глазами(d):
    """Копия для чтения глазами: открытые сверху, закрытые ниже."""
    зап = d.get("записи", [])
    откр = [z for z in зап if not z.get("закрыто")]
    закр = [z for z in зап if z.get("закрыто")]
    откр.sort(key=lambda z: (-int(z.get("повторов", 1)), z.get("когда", "")))
    L = ["# ЗАМЕЧАНИЯ ПОЛЬЗОВАТЕЛЯ — ЖИВОЙ ЖУРНАЛ", "",
         "Пишет ВКЛАДКА, которой он сказал, сразу и дословно. Переживает смену",
         "вкладок и координаторов: `smena.sh` печатает незакрытые первым блоком.",
         "", "## НЕЗАКРЫТЫЕ (%d)" % len(откр), ""]
    for z in откр:
        п = (" · СКАЗАНО %d РАЗА" % z["повторов"]) if z.get("повторов", 1) > 1 else ""
        L.append("### %s%s — %s" % (z["id"], п, z.get("когда", "")))
        L.append("**Дословно:** «%s»" % z.get("слова", ""))
        L.append("· где: %s · %s %s · вкладка %s"
                 % (z.get("где", "—"), z.get("канал", "—"),
                    z.get("тема", "—"), z.get("вкладка", "—")))
        if z.get("что"):
            L.append("· вкладка уже сделала: %s" % z["что"])
        L.append("")
    L += ["## ЗАКРЫТЫЕ (%d)" % len(закр), ""]
    for z in закр[-40:]:
        L.append("- %s «%s» → %s (%s)"
                 % (z["id"], z.get("слова", "")[:90], z.get("чем", "закрыто"),
                    z.get("закрыто", "")))
    open(ГЛАЗАМИ, "w", encoding="utf-8").write("\n".join(L) + "\n")


def _новый_id(зап):
    n = 0
    for z in зап:
        try:
            n = max(n, int(str(z.get("id", "Z-0")).split("-")[1]))
        except (IndexError, ValueError):
            pass
    return "Z-%04d" % (n + 1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    a1 = sub.add_parser("dobav")
    a1.add_argument("--slova", required=True, help="ДОСЛОВНО его слова")
    a1.add_argument("--kanal", default="")
    a1.add_argument("--tema", default="")
    a1.add_argument("--gde", default="", help="дашборд и порт, сцена, элемент")
    a1.add_argument("--chto", default="", help="что вкладка уже сделала")
    a1.add_argument("--vkladka", default=os.environ.get("CLAUDE_SESSION_NAME", ""))

    a2 = sub.add_parser("spisok")
    a2.add_argument("--vse", action="store_true")

    a3 = sub.add_parser("zakryl")
    a3.add_argument("id")
    a3.add_argument("--chem", required=True, help="чем именно закрыто")

    a4 = sub.add_parser("povtor")
    a4.add_argument("id")
    a4.add_argument("--slova", default="")

    a = ap.parse_args()
    d = читать()
    зап = d.setdefault("записи", [])
    сейчас = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    if a.cmd == "dobav":
        z = {"id": _новый_id(зап), "когда": сейчас, "слова": a.slova.strip(),
             "канал": a.kanal, "тема": a.tema, "где": a.gde,
             "что": a.chto, "вкладка": a.vkladka, "повторов": 1,
             "закрыто": ""}
        зап.append(z)
        писать(d)
        print("записал %s" % z["id"])
        return 0

    if a.cmd == "spisok":
        отб = зап if a.vse else [z for z in зап if not z.get("закрыто")]
        отб = sorted(отб, key=lambda z: (-int(z.get("повторов", 1)),
                                         z.get("когда", "")))
        if not отб:
            print("незакрытых замечаний нет")
            return 0
        print("ЗАМЕЧАНИЯ ПОЛЬЗОВАТЕЛЯ — %d" % len(отб))
        for z in отб:
            п = (" ×%d" % z["повторов"]) if z.get("повторов", 1) > 1 else ""
            print("  %s%s %s · %s %s · %s"
                  % (z["id"], п, z.get("когда", ""), z.get("канал", ""),
                     z.get("тема", ""), z.get("где", "")))
            print("      «%s»" % z.get("слова", "")[:150])
            if z.get("закрыто"):
                print("      закрыто %s: %s" % (z["закрыто"], z.get("чем", "")))
        return 0

    z = next((x for x in зап if x.get("id") == a.id), None)
    if not z:
        print("нет такого замечания: %s" % a.id, file=sys.stderr)
        return 2

    if a.cmd == "zakryl":
        z["закрыто"] = сейчас
        z["чем"] = a.chem
        писать(d)
        print("%s закрыто" % a.id)
        return 0

    z["повторов"] = int(z.get("повторов", 1)) + 1
    z.setdefault("повторы", []).append({"когда": сейчас, "слова": a.slova})
    z["закрыто"] = ""
    писать(d)
    print("%s сказано %d раза — это ошибка нашего процесса, а не новое "
          "замечание" % (a.id, z["повторов"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
