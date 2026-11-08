#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОДНА КАРТИНКА — ОДИН РАЗ НА ВЕСЬ ВИДЕОРЯД (08.11.2026).

Его слово по ролику ПЛАНЕТА «Украина катастрофа»: «вот этот генератор, блин,
синего цвета, голубой, он гуляет… У нас же есть строгий запрет, не больше
одного кадра. Одну картинку взяли — всё, забыли про неё в этом видеоряде. Не
надо её пихать куда-то ещё в другое место».

ПОЧЕМУ СТАРАЯ ПРОВЕРКА ЭТОГО НЕ ВИДЕЛА. `selfcheck` сравнивал md5 файлов в
`images/` и `overlays/`. Три дыры сразу:
  1. клон-конвейер (`unikalizaciya.py`) отдаёт донора ЗЕРКАЛЬНЫМ и подрезанным
     — у одинаковой картинки разный md5;
  2. фото рисованных карточек лежат в `cards/photo/` и в `dossier/`, то есть
     вне сравнения вообще;
  3. готовый клип сцены (`clips/scene_NNN.mp4`) мог приехать из того же
     исходника, что и чужой `images/scene_NNN.jpg`.
Живой счёт по тому ролику: md5 — ноль дублей, перцептивный хеш — шесть групп,
в главной ПЯТЬ сцен с одним и тем же кадром.

КАК СЧИТАЕМ. Средний хеш (average hash) 8×8 по серой уменьшенной копии; для
каждого кадра берём минимум из хеша и хеша ЗЕРКАЛА — иначе отражённый донор
читается как другая картинка. Расстояние Хэмминга ≤ порога (по умолчанию 5
бит из 64) — считаем, что это одна и та же картинка.

    python3 povtor_kadrov.py <папка проекта> [--порог 5] [--json]

Печатает группы «одна картинка на нескольких сценах». Внутри ОДНОЙ сцены
повтор нормален (кадр, его всплывашка и его же клип) — такие пары молчат.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("нужен Pillow")

РАЗМЕР = 8          # грубый хеш — быстрый отсев заведомо разных кадров
СЕТКА = 16          # сетка для точного сравнения
ПОРОГ_ХЕША = 16     # бит различия, выше которого даже не считаем похожесть
ПОХОЖЕСТЬ = 0.93    # ниже этого — разные картинки (замерено 08.11, см. ниже)

# ПОЧЕМУ ИМЕННО ТАК, А НЕ ОДИН ХЕШ (замер 08.11 на ролике «Украина катастрофа»).
# Средний хеш 8×8 с порогом 5 бит дал ЛОЖНЫЕ срабатывания: портовый кран и
# горящее здание Кабмина разошлись всего на 5 бит. Разностный хеш (dHash),
# наоборот, в упор не видел ПОДРЕЗАННЫЙ дубль: один и тот же автовокзал в
# сцене 40 и на фото карточки 70 разошёлся на 104 бита из 240.
# Поэтому считаем ПОХОЖЕСТЬ: нормированная корреляция по сетке 16×16 серого,
# и сравниваем не только кадр с кадром, а кадр с его центральными вырезами
# 80% и 65% — тогда зум и обрезка перестают маскировать повтор.
# Числа замера: одна картинка → 0,94…1,00 · разные → 0,02…0,80.


def _grid(im, n=СЕТКА):
    g = im.convert("L").resize((n, n), Image.BILINEAR)
    px = [p / 255.0 for p in list(g.getdata())]
    m = sum(px) / len(px)
    d = (sum((p - m) ** 2 for p in px) / len(px)) ** 0.5 or 1e-6
    return [(p - m) / d for p in px]


def _ahash(im):
    g = im.convert("L").resize((РАЗМЕР, РАЗМЕР), Image.BILINEAR)
    px = list(g.getdata())
    avg = sum(px) / float(len(px))
    bits = 0
    for i, p in enumerate(px):
        if p >= avg:
            bits |= 1 << i
    return bits


def _varianty(im):
    """Сам кадр и два центральных выреза — против зума и обрезки."""
    w, h = im.size
    out = [im]
    for k in (0.80, 0.65):
        dw, dh = int(w * (1 - k) / 2), int(h * (1 - k) / 2)
        out.append(im.crop((dw, dh, w - dw, h - dh)))
    return out


def описание(im):
    """Подпись кадра: грубый хеш + сетки вырезов, свои и зеркальные."""
    вар = _varianty(im)
    сетки = [_grid(c) for c in вар] + [_grid(ImageOps.mirror(c)) for c in вар]
    a = min(_ahash(im), _ahash(ImageOps.mirror(im)))
    return a, сетки


def похожесть(о1, о2):
    _, с1 = о1
    _, с2 = о2
    n = len(с1[0])
    лучшее = -1.0
    for x in с1[:3]:                     # вырезы левого кадра
        for y in с2:                     # вырезы правого, включая зеркальные
            c = sum(p * q for p, q in zip(x, y)) / n
            if c > лучшее:
                лучшее = c
    return лучшее


def hash_file(path):
    try:
        im = Image.open(path)
        im.load()
    except Exception:
        return None
    return описание(im)


def hash_video(path, сек=None):
    """Кадр из начала клипа во временный файл и его подпись."""
    if сек is None:
        сек = 1.0
    tmp = path + ".__phash.jpg"
    r = subprocess.run(["ffmpeg", "-nostdin", "-ss", str(сек), "-i", path,
                        "-frames:v", "1", "-vf", "scale=320:-1", "-y", tmp],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.exists(tmp):
        return None
    h = hash_file(tmp)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return h


def _sid(path):
    m = re.search(r"scene_(\d+)", os.path.basename(path))
    return int(m.group(1)) if m else None


def собрать(folder, с_клипами=True):
    """Все кадры ролика: сцены, всплывашки, фото карточек, досье, клипы."""
    out = []
    образцы = [("images/scene_*.jpg", "кадр"), ("images/scene_*.png", "кадр"),
               ("images/scene_*.jpeg", "кадр"),
               ("overlays/scene_*.jpg", "всплывашка"),
               ("overlays/scene_*.png", "всплывашка"),
               ("cards/photo/*.jpg", "фото карточки"),
               ("cards/photo/*.png", "фото карточки"),
               ("dossier/*.jpg", "досье"), ("dossier/*.png", "досье"),
               ("insets/*.jpg", "врез")]
    for шаблон, вид in образцы:
        for f in sorted(glob.glob(os.path.join(folder, шаблон))):
            # НАДПИСИ-ПЛАШКИ ИЗ СРАВНЕНИЯ ВЫНУТЫ: `*.text.png` — это текст на
            # прозрачном фоне, они похожи друг на друга по построению, а не
            # по картинке. Иначе проверка ловит каждую пару надписей.
            if f.endswith(".text.png") or ".mask" in os.path.basename(f):
                continue
            if os.path.getsize(f) < 1024:
                continue
            h = hash_file(f)
            if h is not None:
                out.append((h, f, вид, _sid(f)))
    if с_клипами:
        for f in sorted(glob.glob(os.path.join(folder, "clips", "scene_*.mp4"))):
            h = hash_video(f)
            if h is not None:
                out.append((h, f, "клип", _sid(f)))
    return out


def группы(кадры, порог=ПОХОЖЕСТЬ):
    """Склейка похожих кадров; группа идёт в отчёт, если сцен в ней больше одной.

    Внутри ОДНОЙ сцены повтор нормален: кадр, его всплывашка и его же клип —
    это одна и та же картинка по делу.
    """
    остаток = list(кадры)
    готово = []
    while остаток:
        о0, f0, в0, s0 = остаток.pop(0)
        груп = [(f0, в0, s0)]
        прочее = []
        for о, f, в, s in остаток:
            if bin(о[0] ^ о0[0]).count("1") > ПОРОГ_ХЕША:
                прочее.append((о, f, в, s))
                continue
            if похожесть(о0, о) >= порог:
                груп.append((f, в, s))
            else:
                прочее.append((о, f, в, s))
        остаток = прочее
        сцены = {s for _, _, s in груп if s is not None}
        if len(груп) > 1 and len(сцены) > 1:
            готово.append(sorted(груп, key=lambda x: (x[2] is None, x[2])))
    return готово


def main():
    ap = argparse.ArgumentParser(description="повтор одной картинки по сценам")
    ap.add_argument("folder")
    ap.add_argument("--порог", type=float, default=ПОХОЖЕСТЬ, dest="порог",
                    help="похожесть 0..1, ниже которой кадры считаются разными")
    ap.add_argument("--без-клипов", action="store_true", dest="no_clips")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()

    кадры = собрать(a.folder, not a.no_clips)
    g = группы(кадры, a.порог)
    if a.as_json:
        print(json.dumps([[{"файл": f, "вид": в, "сцена": s}
                           for f, в, s in гр] for гр in g],
                         ensure_ascii=False, indent=1))
        return 1 if g else 0

    print("кадров в сравнении: %d" % len(кадры))
    if not g:
        print("повторов нет: каждая картинка стоит ровно в одной сцене")
        return 0
    print("ПОВТОР ОДНОЙ КАРТИНКИ НА РАЗНЫХ СЦЕНАХ — %d групп(ы):" % len(g))
    for гр in g:
        сцены = sorted({s for _, _, s in гр if s is not None})
        print("  сцены %s:" % ", ".join(str(x) for x in сцены))
        for f, в, s in гр:
            print("     %-14s %s" % (в, f))
    print("\nЛечение: оставить картинку В ОДНОЙ сцене, остальным дать новый")
    print("кадр (`zamena.py` / `ban_file.py` + добор). Зеркало и обрезка")
    print("повтором быть не перестают — проверка считает их той же картинкой.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
