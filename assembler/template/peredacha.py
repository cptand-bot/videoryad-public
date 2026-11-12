#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПЕРЕДАЧА СМЕНЫ СОБИРАЕТСЯ МАШИНОЙ, А НЕ ПАМЯТЬЮ ВКЛАДКИ (12.11.2026).

Его страх 12.11, дословно: «боюсь, что при этой пересменке что-то теряется…
открою седьмую вкладку, и она вообще забудет, что там в первой было».

Страх обоснованный: до сих пор фактуру передачи НАБИРАЛА РУКАМИ уходящая
вкладка. Что она забыла или не успела — терялось навсегда, и к седьмой
пересменке терялось семь раз. Здесь всё, что можно, читается из машинного
состояния: реестр занятых тем, замки труб, папки дня на `D:`, журнал правок,
очередь на раскатку, открытые хвосты. Вкладке остаётся дописать только то,
чего в файлах нет — разговор с ним.

    python3 peredacha.py                 # напечатать сводку
    python3 peredacha.py --zapisat       # + в ПЕРЕДАЧА-СМЕНЫ-<дата>.md и
                                         #   в ручную часть НОВОСТИ-СОСТОЯНИЕ.txt
    python3 peredacha.py --ot andrey-43 --slovami "две строки от себя"
"""
import argparse
import datetime
import glob
import io
import json
import os
import re
import subprocess

СКИЛЛ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
НОВОСТИ = "/mnt/d/YouTube/НОВОСТИ"
СОСТОЯНИЕ = "/mnt/d/YouTube/НОВОСТИ-СОСТОЯНИЕ.txt"
КАНАЛЫ = ("ПЛАНЕТА", "5 МИНУТ", "ДИПЛОМАТИЯ СИЛЫ", "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО",
          "ОЛЬКА НОВОСТИ")


def _ч(p):
    try:
        return io.open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def реестр_дня():
    """Темы в работе и сданные — из реестра, а не из головы."""
    try:
        d = json.loads(_ч(os.path.join(СКИЛЛ, "base", "zanyato.json")) or "{}")
    except ValueError:
        return []
    сег = datetime.date.today()
    из = []
    for z in (d.get("записи") or {}).values():
        ts = z.get("ts") or 0
        if ts and (datetime.date.fromtimestamp(ts) - сег).days < -1:
            continue           # старше вчера — не наше дело
        из.append(z)
    из.sort(key=lambda z: z.get("ts") or 0)
    return из


def замки():
    кат = os.path.join(СКИЛЛ, "base", "truby")
    из = []
    for d in sorted(glob.glob(os.path.join(кат, "*"))):
        кто = _ч(os.path.join(d, "kto")).strip()
        мин = int((datetime.datetime.now().timestamp()
                   - os.path.getmtime(d)) / 60)
        из.append((os.path.basename(d), кто, мин))
    return из


def папки_дня():
    """Что лежит на D: по каналам за последние два дня работы."""
    из = []
    for к in КАНАЛЫ:
        корень = os.path.join(НОВОСТИ, к)
        дни = sorted(glob.glob(os.path.join(корень, "*", "[0-3][0-9]-[01][0-9]")))[-2:]
        for д in дни:
            темы = sorted(os.path.basename(t) for t in glob.glob(os.path.join(д, "*"))
                          if os.path.isdir(t))
            if темы:
                из.append((к, os.path.basename(д), темы))
    return из


def журнал(n=8):
    р = subprocess.run(["python3", os.path.join(СКИЛЛ, "template", "pravki.py"),
                        "spisok", "--dni", "2"], capture_output=True, text=True)
    строки = [s for s in (р.stdout or "").splitlines() if s.strip()]
    return строки[-n * 4:] if строки else []


def хвосты():
    из = []
    п = _ч(os.path.join(СКИЛЛ, "ПОДХВАТ.md"))
    if п.strip():
        из.append(("ПОДХВАТ.md", [s for s in п.splitlines()
                                  if s.startswith("- ") or s.startswith("· ")][:10]))
    н = _ч(os.path.join(СКИЛЛ, "НА-РАСКАТКУ.md"))
    м = re.search(r"## ОСТАЛОСЬ(.+?)(?:\n## |\Z)", н, re.S)
    if м:
        из.append(("НА-РАСКАТКУ.md · осталось",
                   [s for s in м.group(1).splitlines() if s.strip()][:14]))
    return из


def собрать(ot, slovami):
    т = datetime.datetime.now()
    L = ["# ПЕРЕДАЧА СМЕНЫ %s — от `%s`" % (т.strftime("%d.%m.%Y %H:%M"), ot),
         "",
         "Собрано машиной (`peredacha.py`): реестр, замки труб, папки дня,",
         "журнал правок и хвосты читаются из состояния, а не из памяти вкладки.",
         ""]
    if slovami:
        L += ["## ОТ СЕБЯ (то, чего в файлах нет)", slovami, ""]
    L += ["## ТЕМЫ В РАБОТЕ И СДАННЫЕ (реестр)"]
    р = реестр_дня()
    if not р:
        L.append("- записей за сегодня-вчера нет")
    for z in р:
        L.append("- [%s] %s · %s · день %s · работа %s · %s"
                 % (z.get("состояние", "?"), z.get("канал", "?"),
                    z.get("тема", "?"), z.get("день", "?"),
                    z.get("работа", "?"), z.get("кто", "?")))
    L += ["", "## ЗАМКИ ТРУБ"]
    з = замки()
    L.append("- свободны все шесть" if not з else "")
    for имя, кто, мин in з:
        L.append("- %s держит %s (%d мин назад%s)"
                 % (имя, кто or "неизвестно", мин,
                    ", СТАРШЕ 4 ЧАСОВ — снимется само" if мин > 240 else ""))
    L += ["", "## ПАПКИ ДНЯ НА D:"]
    for к, д, темы in папки_дня():
        L.append("- %s · %s: %s" % (к, д, " · ".join(темы)))
    L += ["", "## ЖУРНАЛ ПРАВОК ЗА ДВОЕ СУТОК"]
    L += ["    " + s for s in журнал()] or ["- пусто"]
    L += ["", "## ХВОСТЫ"]
    for имя, строки in хвосты():
        L.append("### %s" % имя)
        L += строки
    L += ["",
          "## ЧИТАТЬ ДАЛЬШЕ",
          "`ПОДХВАТ.md` · `НА-РАСКАТКУ.md` · `BUGS-LIVE.md` ·",
          "`pravki.py nayti \"<слово>\"` — что мы уже меняли и зачем.", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="собрать передачу смены машиной")
    ap.add_argument("--ot", default=os.environ.get("VIDEORYAD_KTO", "вкладка"))
    ap.add_argument("--slovami", default="", help="две-три строки от себя")
    ap.add_argument("--zapisat", action="store_true",
                    help="записать в ПЕРЕДАЧА-СМЕНЫ-<дата>.md и в состояние")
    a = ap.parse_args()
    текст = собрать(a.ot, a.slovami)
    print(текст)
    if not a.zapisat:
        return 0
    имя = os.path.join(СКИЛЛ, "ПЕРЕДАЧА-СМЕНЫ-%s.md"
                       % datetime.datetime.now().strftime("%d-%m"))
    io.open(имя, "w", encoding="utf-8").write(текст)
    print("\nзаписано: %s" % имя)
    # ручная часть файла состояния — та же сводка, коротким хвостом
    s = _ч(СОСТОЯНИЕ)
    i = s.find("СОСТОЯНИЕ НОВОСТНОГО СБОРЩИКА")
    голова = s[:i] if i >= 0 else (s + "\n")
    шапка = ("СОСТОЯНИЕ НОВОСТНОГО СБОРЩИКА — %s (%s)\n"
             "(ручная часть собрана peredacha.py; авто-блок выше сам)\n\n"
             % (datetime.datetime.now().strftime("%d.%m.%Y %H:%M"), a.ot))
    io.open(СОСТОЯНИЕ, "w", encoding="utf-8").write(
        голова + шапка + текст.split("## ТЕМЫ В РАБОТЕ", 1)[-1].join(
            ["## ТЕМЫ В РАБОТЕ", ""]))
    print("ручная часть состояния обновлена: %s" % СОСТОЯНИЕ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
