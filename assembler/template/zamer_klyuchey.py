#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СКОЛЬКО КАРТОЧЕК ЗАКРЫВАЕТСЯ БЕЗ АГЕНТА — ЗАМЕР ОДНОЙ КОМАНДОЙ.

    python3 template/zamer_klyuchey.py <ролик>.scenes.json [--spisok]

Считает, сколько карточек комплекта проходят СВОЮ дверь с ключами, которые
выведены из текста сцены машиной (`kartochki_srazu._klyuchi`), и по каждой
непрошедшей печатает ОДНОЙ строкой, чего именно не хватило.

ЗАЧЕМ (14.11.2026, его вопрос «как кратно сократить время сборки»). Узкое
место ролика переехало с поиска кадров на карточки: за них вкладка ходит к
внешнему агенту по четыре раза. Чтобы сокращать это не на ощупь, нужно одно
честное число — сколько карточек закрывается БЕЗ агента. Замер 14.11 на
живом ролике из 56 карточек: было 11, после первой правки вывода — 16.

Ничего не пишет: все вызовы идут с `--dry-run`.
"""
import importlib.util as _u
import json
import io
import os
import re
import subprocess
import sys

T = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(T)
CARD_PUT = os.path.join(SKILL, "fullcycle", "card_put.py")


def _ks():
    sys.path.insert(0, T)
    sp = _u.spec_from_file_location("ks", os.path.join(T, "kartochki_srazu.py"))
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    scenes = args[0]
    if not os.path.isfile(scenes):
        sys.exit("нет файла сцен: %s" % scenes)
    m = _ks()
    d = json.load(io.open(scenes, encoding="utf-8"))
    сц = d.get("scenes", d) if isinstance(d, dict) else d
    ок, всего, плохо = 0, 0, []
    корень = os.path.dirname(os.path.abspath(scenes)) or "."
    for i, s in enumerate(сц, 1):
        ист = str(s.get("source", ""))
        if not ист.startswith("card:"):
            continue
        всего += 1
        вид = ист[len("card:"):].strip()
        текст = (s.get("text") or "").strip()
        ном = int(str(s.get("id") or i))
        дверь = m._dver_vida(вид) or CARD_PUT
        # мерим ровно то, что делает конвейер: запасной длинной фразы нет
        фраза = m._fraza_pod_vid(вид, текст)
        ключи = m._klyuchi(вид, фраза, текст) if фраза else None
        if not ключи:
            плохо.append((ном, вид, "нечем наполнить из текста сцены"))
            continue
        r = subprocess.run([sys.executable, дверь, os.path.basename(scenes),
                            str(ном), вид, "--dry-run", "--force"] + ключи,
                           capture_output=True, text=True, cwd=корень)
        if r.returncode == 0:
            ок += 1
            continue
        стр = [x for x in (r.stderr or "").splitlines() if x.startswith("ОШИБКА")]
        чего = ""
        if стр:
            мм = re.search(r"не хватает: ([^\n]{0,40})", стр[0])
            чего = мм.group(1) if мм else стр[0][7:70]
        else:
            чего = "дверь %s, код %d" % (os.path.basename(дверь), r.returncode)
        плохо.append((ном, вид, чего))
    доля = (100.0 * ок / всего) if всего else 0.0
    print("БЕЗ АГЕНТА ЗАКРЫВАЕТСЯ: %d из %d (%.0f%%)" % (ок, всего, доля))
    if "--spisok" in sys.argv:
        for ном, вид, чего in плохо:
            print("  сцена %-3d %-16s %s" % (ном, вид, чего))
    else:
        print("  (ключ --spisok — чего не хватило по каждой)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
