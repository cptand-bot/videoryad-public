#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ПРЕВЬЮ ДЛЯ КЛОНИРОВАННОГО КАНАЛА — БЕЗ ЕДИНОЙ НОВОЙ ГЕНЕРАЦИИ (08.11.2026).

Его слово: «на клонированные каналы могут уходить и оригиналы, те, которые я
утвердил… просто её отзеркаливаем. И пишем, может быть, даже те же надписи. Но
генерировать, перегенерировать точно не будем. Генерация может быть только на
„Планете“ и на „5 минутах“».

И раньше, про пять вариантов: «из трёх нечего будет выбрать. Я почему пять
оставил — что наверняка хоть одно мне подойдёт». То есть пять вариантов на
оригинале ОСТАЮТСЯ, а клоны живут тем, что уже нарисовано.

ОТКУДА БЕРЁМ КАРТИНКУ, по порядку:
  1. НЕИСПОЛЬЗОВАННЫЙ вариант донора — он их видел и не взял, значит они
     свободны (`превью-варианты/ПРЕВЬЮ-N.png`, кроме того, что он утвердил);
  2. если свободных нет — УТВЕРЖДЁННОЕ превью донора; оно зеркалится, чтобы
     в ленте не читалось как та же картинка.

ЧТО ДЕЛАЕМ С НЕЙ: зеркалим (по его слову), кладём надписи в гамме НОВОГО
канала и делаем квадрат 1:1 — ровно как на оригинале. Надписи можно взять
донорские (`--надписи донор`) или свои (`--верх`/`--низ`).

    python3 prevyu_klon.py "<папка донора>" "<папка клона>" \\
            [--верх "ДОИГРАЛИСЬ"] [--низ "ПРИШЛА РАСПЛАТА"] [--без-зеркала]

Ни одного обращения к внешнему агенту этот инструмент не делает.
"""

import argparse
import io
import os
import re
import sys

ЗДЕСЬ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ЗДЕСЬ)
import prevyu_text as _pt                                    # noqa: E402

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("нужен Pillow")


def варианты(folder):
    d = os.path.join(folder, "превью-варианты")
    if not os.path.isdir(d):
        return []
    out = []
    for n in sorted(os.listdir(d)):
        m = re.match(r"ПРЕВЬЮ-(\d+)\.png$", n)
        if m:
            out.append((int(m.group(1)), os.path.join(d, n)))
    return out


def утверждённые(folder):
    """Номера вариантов, которые он уже взял в работу на канале-доноре."""
    взято = set()
    for n in os.listdir(folder):
        m = re.search(r"ПРЕВЬЮ-(\d+)(?:-КВАДРАТ)?\.png$", n)
        if m:
            взято.add(int(m.group(1)))
    return взято


def main():
    ap = argparse.ArgumentParser(description="превью клона из готовых вариантов донора")
    ap.add_argument("донор")
    ap.add_argument("клон")
    ap.add_argument("--верх", default="", dest="top")
    ap.add_argument("--низ", default="", dest="bottom")
    ap.add_argument("--надписи", default="свои", choices=("свои", "донор"),
                    help="«донор» — взять надписи с утверждённого превью донора")
    ap.add_argument("--без-зеркала", action="store_true", dest="no_mirror")
    ap.add_argument("--номер", type=int, default=0,
                    help="взять конкретный вариант донора")
    a = ap.parse_args()

    for p in (a.донор, a.клон):
        if not os.path.isdir(p):
            sys.exit("нет папки: %s" % p)

    все = варианты(a.донор)
    if not все:
        sys.exit("у донора нет вариантов превью (%s/превью-варианты/)" % a.донор)
    занятые = утверждённые(a.донор)

    if a.номер:
        выбор = [(n, p) for n, p in все if n == a.номер]
        if not выбор:
            sys.exit("варианта %d у донора нет" % a.номер)
        n, src = выбор[0]
        откуда = "вариант %d (назван ключом)" % n
    else:
        свободные = [(n, p) for n, p in все if n not in занятые]
        if свободные:
            n, src = свободные[0]
            откуда = "НЕиспользованный вариант %d донора" % n
        else:
            n, src = все[0]
            откуда = "утверждённое превью донора (свободных не осталось)"

    канал = _pt.channel_of(a.клон) if hasattr(_pt, "channel_of") else ""
    gamma = _pt.GAMMA.get((канал or "").upper(), _pt.DEFAULT)
    имя = _pt.theme_name(a.клон)

    # ЗЕРКАЛО — ЕГО ПРЯМОЕ СЛОВО: одна и та же картинка на двух каналах не
    # должна читаться как одна и та же картинка.
    tmp = os.path.join(a.клон, ".prevyu_klon_tmp.png")
    im = Image.open(src).convert("RGB")
    if not a.no_mirror:
        im = ImageOps.mirror(im)
    im.save(tmp)

    top, bottom = a.top.upper(), a.bottom.upper()
    if a.надписи == "донор" and not (top or bottom):
        print("  надписи донора в файле не хранятся — задай --верх/--низ")

    dst = os.path.join(a.клон, "%s ПРЕВЬЮ-%d.png" % (имя, n))
    _pt.put(tmp, dst, top, bottom, gamma)
    _pt.put(tmp, os.path.join(a.клон, "%s ПРЕВЬЮ-%d-КВАДРАТ.png" % (имя, n)),
            top, bottom, gamma, square=True)
    os.remove(tmp)

    print("взято: %s" % откуда)
    print("канал клона: %s%s" % (канал or "не определён",
                                 "" if a.no_mirror else ", кадр отзеркалён"))
    print("готово: %s" % dst)
    print("        + квадрат рядом")
    print("генерация НЕ запускалась: превью рисуются только на «5 МИНУТ» и ПЛАНЕТЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
