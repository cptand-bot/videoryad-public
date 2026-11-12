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

ПОВТОР ВНУТРИ РИСОВАННЫХ КАДРОВ ПРОВЕРКА НЕ ВИДЕЛА (09.11, улов вкладки
`usuario-e6`). Один и тот же найденный кадр — флаги у штаб-квартиры НАТО —
лёг в ТРИ разных элемента: ленту плёнки, стену улик и всплывашку, под тремя
разными именами. Зритель видит кадр трижды, а гейт молчал. Причина не в
похожести: фото карточек в сравнение попадали, но у их имён
(`cards/photo/kadr_207.jpg`) НЕТ номера сцены, номер выходил `None`, а группа
идёт в отчёт только когда в ней больше ОДНОЙ сцены — три плитки одного кадра
давали ноль сцен и читались как «одна сцена».
Поэтому номер сцены и НАЗВАНИЕ ЭЛЕМЕНТА берём из заданий карточек: их пишут
`card_put.py`, `element_put.py`, `quote_card.py` и `style_card.py` в
`cards/queue/scene_NNN.json`, в журнал `cards/cards.json` и в поле `card`
самой сцены. Один файл может стоять в НЕСКОЛЬКИХ местах видеоряда, поэтому
на каждое место идёт своя запись, а подпись кадра считается один раз.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

# PIL НУЖЕН ТОЛЬКО ДЛЯ ПОХОЖЕСТИ, А МОДУЛЬ ИМПОРТИРУЮТ И РАДИ РАЗБОРА ЗАДАНИЙ
# КАРТОЧЕК (09.11): `карточные_фото()` зовёт `dossier_use.py`, чтобы зачесть
# кадр досье, попавший внутрь рисованного кадра. Падать на `sys.exit` при
# импорте тогда нельзя — упал бы весь гейт досье. Отказ переехал в `собрать()`,
# где он и нужен, и остался ImportError: `selfcheck.py` ловит именно его.
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None

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


def _целое(x):
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


_РАСШ_ФОТО = (".jpg", ".jpeg", ".png", ".webp")


def _пути_картинок(x, out):
    """Все строки-пути к картинкам внутри задания, на любой глубине.

    По делу: у `wall` снимки лежат списком списков
    (`[[путь, x, y, поворот, подпись], …]`), у `film` — просто списком, у
    `poster` под ключом `hero_photo`. Перечислять ключи по памяти — ровно тот
    способ, которым поле тихо забывают, поэтому обходим задание целиком.
    """
    if isinstance(x, str):
        if x.lower().endswith(_РАСШ_ФОТО):
            out.append(x)
    elif isinstance(x, dict):
        for v in x.values():
            _пути_картинок(v, out)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _пути_картинок(v, out)


def _элемент(j):
    """Короткое имя элемента: код полки и вид, как их записал инструмент."""
    вид = str(j.get("view") or j.get("kind") or "").strip()
    код = str(j.get("код") or j.get("code") or "").strip()
    return " ".join(x for x in (код, вид) if x) or "карточке"


def карточные_фото(folder):
    """Исходные фото рисованных кадров: путь → [(сцена, элемент), …].

    Три источника, потому что путь к фото пишется в три места и ни одно не
    обязательно: задание в очереди (его читает облачная рисовалка), журнал
    `cards/cards.json` (остаётся, когда задание уже снесли) и поле `card`
    самой сцены. Путь приводим к абсолютному: в заданиях он относительный
    (`cards/photo/kadr_207.jpg`), а сверяем с результатами `glob`.
    """
    места = {}

    def добавить(sid, j, пути):
        м = _элемент(j)
        for p in пути:
            ap = p if os.path.isabs(p) else os.path.join(folder, p)
            ключ = os.path.normpath(os.path.abspath(ap))
            было = места.setdefault(ключ, [])
            # одно и то же место из двух источников — не два места
            if not any(s == sid for s, _ in было):
                было.append((sid, м))

    for f in sorted(glob.glob(os.path.join(folder, "cards", "queue", "*.json"))):
        try:
            j = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        пути = []
        _пути_картинок(j.get("kwargs") if isinstance(j.get("kwargs"), dict) else j,
                       пути)
        добавить(_целое(j.get("scene") or j.get("sid") or _sid(f)), j, пути)

    try:
        ж = json.load(open(os.path.join(folder, "cards", "cards.json"),
                           encoding="utf-8"))
    except Exception:
        ж = {}
    if isinstance(ж, dict):
        for k, v in ж.items():
            if isinstance(v, dict):
                пути = []
                _пути_картинок(v, пути)
                добавить(_целое(k), v, пути)

    for f in sorted(glob.glob(os.path.join(folder, "*.scenes.json"))):
        if os.path.basename(f).startswith("."):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        сцены = d.get("scenes", d) if isinstance(d, dict) else d
        if not isinstance(сцены, list):
            continue
        for s in сцены:
            if not isinstance(s, dict) or not isinstance(s.get("card"), dict):
                continue
            j = dict(s["card"])
            j.setdefault("view", str(s.get("source") or "")[5:])
            пути = []
            _пути_картинок(s["card"], пути)
            добавить(_целое(s.get("id")), j, пути)
    return места


def _места_файла(path, вид, места):
    """Куда этот файл попал в видеоряде: [(подпись, сцена), …].

    Запись из задания карточки НЕ ЗАМЕНЯЕТ обычную, а добавляется к ней:
    кадр сцены 4, поставленный ещё и снимком в стену улик сцены 23, стоит в
    ДВУХ местах — именно это и есть повтор.
    """
    зап = места.get(os.path.normpath(os.path.abspath(path))) or []
    своё = _sid(path)
    out = [("фото в " + м, s) for s, м in зап]
    if not зап:
        if вид == "фото карточки":
            вид = "фото карточки НИ В ОДНОМ ЭЛЕМЕНТЕ"
        out.append((вид, своё))
    elif своё is not None and all(s != своё for s, _ in зап):
        # ту же сцену вторым местом не считаем: кадр сцены 25, поставленный
        # фотографией в карточку сцены 25, — это одно место, а не два
        out.append((вид, своё))
    return out


def собрать(folder, с_клипами=True):
    """Все кадры ролика: сцены, всплывашки, фото карточек, досье, клипы."""
    if Image is None:
        raise ImportError("нужен Pillow")
    out = []
    места = карточные_фото(folder)
    видано = set()
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
            # ОБЗОРНЫЕ КАДРЫ КЛИПОВ ТОЖЕ ВЫНУТЫ (12.11, улов `usuario-e5`:
            # ложные пары 9↔83 и 51↔67). `*.mp4.revframe.jpg` — первый кадр
            # клипа карточки, 6 КБ почти белого: у `film_frame`, `dossier` и
            # лоскутов он одинаково пуст ДО появления фото, а сами фото
            # внутри разные. Сравнивать по нему — значит бить тревогу на
            # пустом месте и гнать вкладку на лишний круг.
            if (f.endswith(".text.png") or ".mask" in os.path.basename(f)
                    or ".revframe." in os.path.basename(f)):
                continue
            if os.path.getsize(f) < 1024:
                continue
            h = hash_file(f)
            if h is None:
                continue
            видано.add(os.path.normpath(os.path.abspath(f)))
            out.extend((h, f, в, s) for в, s in _места_файла(f, вид, места))
    # ФОТО ЭЛЕМЕНТА ЛЕЖИТ НЕ ТОЛЬКО В `cards/photo/`: задание принимает любой
    # путь, и вкладки берут кадр из `cards/replaced/` (прежний кадр сцены),
    # из медиатеки и из базы кадров. Такой файл в видеоряде ЕСТЬ — внутри
    # элемента, — а ни под один шаблон выше не попадает.
    for ap in sorted(места):
        if ap in видано or not os.path.isfile(ap):
            continue
        try:
            if os.path.getsize(ap) < 1024:
                continue
        except OSError:
            continue
        h = hash_file(ap)
        if h is None:
            continue
        видано.add(ap)
        out.extend((h, ap, в, s) for в, s in _места_файла(ap, "фото карточки", места))
    if с_клипами:
        for f in sorted(glob.glob(os.path.join(folder, "clips", "scene_*.mp4"))):
            h = hash_video(f)
            if h is not None:
                out.append((h, f, "клип", _sid(f)))
    return out


def повтор(груп):
    """Виден ли один кадр в видеоряде ДВАЖДЫ — и это два РАЗНЫХ файла.

    ОДИН И ТОТ ЖЕ ФАЙЛ, названный в нескольких местах, — это осознанный
    повторный показ: стена улик (A56) и лента плёнки (A68) по устройству
    собираются из кадров ЭТОГО ролика, так написано и в примерах
    `element_put.py` (`--shot images/scene_004.jpg=…`). Блокером это делать
    нельзя: оба элемента в обязательном наборе, и гейт встал бы на каждом
    ролике — прогон 09.11 по четырём сданным роликам дал бы 9, 11 и 12 таких
    отказов. Они уходят в заметку.
    А вот ДВА РАЗНЫХ ФАЙЛА с одной картинкой — это и есть брак 09.11
    (`usuario-e6`): кадр взят дважды и разложен по разным элементам под
    разными именами. Живой замер: `cards/photo/kadr_209.jpg` в стене улик
    сцены 35 и `images/scene_037.jpg` — один кадр, 2200x1467, один md5;
    по досье такие пары отличаются ещё и байтами (пережатая копия), поэтому
    md5-сверка `selfcheck` их не видела, а похожесть видит.
    """
    сцены = {s for _, _, s in груп if s is not None}
    файлы = {os.path.normpath(os.path.abspath(f)) for f, _, s in груп
             if s is not None}
    return len(сцены) > 1 and len(файлы) > 1


def группы(кадры, порог=ПОХОЖЕСТЬ, всё=False):
    """Склейка похожих кадров; в отчёт идёт то, что `повтор()` считает повтором.

    Внутри ОДНОЙ сцены повтор нормален: кадр, его всплывашка и его же клип —
    это одна и та же картинка по делу.

    `всё=True` отдаёт и группы, повтором не являющиеся (один файл показан
    дважды по делу; дубль лежит в папке, но ни в один элемент не поставлен).
    Отчёт печатает их заметкой, а гейт `selfcheck.py` зовёт с умолчанием —
    ложным блокером такой файл быть не должен.
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
        гр = sorted(груп, key=lambda x: (x[2] is None, x[2]))
        if len(гр) > 1 and (всё or повтор(гр)):
            готово.append(гр)
    return готово


def main():
    ap = argparse.ArgumentParser(description="повтор одной картинки по сценам")
    ap.add_argument("folder")
    ap.add_argument("--порог", type=float, default=ПОХОЖЕСТЬ, dest="порог",
                    help="похожесть 0..1, ниже которой кадры считаются разными")
    ap.add_argument("--без-клипов", action="store_true", dest="no_clips")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()

    if Image is None:
        sys.exit("нужен Pillow")
    кадры = собрать(a.folder, not a.no_clips)
    все = группы(кадры, a.порог, всё=True)
    g = [гр for гр in все if повтор(гр)]
    мимо = [гр for гр in все if not повтор(гр)]
    if a.as_json:
        print(json.dumps([[{"файл": f, "вид": в, "сцена": s}
                           for f, в, s in гр] for гр in g],
                         ensure_ascii=False, indent=1))
        return 1 if g else 0

    print("кадров в сравнении: %d (мест в видеоряде, одно фото в двух "
          "элементах считается дважды)" % len(кадры))
    for гр in мимо:
        _сц = sorted({s for _, _, s in гр if s is not None})
        _файлов = len({os.path.abspath(f) for f, _, s in гр if s is not None})
        _почему = ("один и тот же ФАЙЛ показан дважды по делу (мозаика "
                   "собирается из кадров ролика)" if _файлов < 2 else
                   "дубль лежит в папке, но в видеоряд не поставлен")
        print("ЗАМЕТКА (не отказ): %s — сцены %s: %s"
              % (_почему, ", ".join(str(x) for x in _сц) or "нет",
                 ", ".join("%s %s" % (в, os.path.basename(f))
                           for f, в, _ in гр)))
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
