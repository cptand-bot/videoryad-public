#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РАЗВЕДКА: ЕСТЬ ЛИ ВООБЩЕ ТАКИЕ КАДРЫ — ДО ФЕТЧА, ЗА ДВАДЦАТЬ СЕКУНД.

Откуда взято: разбор чужого конвейера cinecode 11.11.2026 (его слово:
«внедряй, поехали»). Там это самый дешёвый шаг всего производства — прежде
чем что-то качать, пересчитать, сколько по каждому объекту вообще лежит в
архивах, и сразу сказать, где пусто.

ЗАЧЕМ НАМ. Сейчас порядок такой: вкладка пишет запрос -> качает -> смотрит
контактный лист -> видит, что приехало не то -> переписывает запрос ->
качает заново. Это и есть круги правок: 3 минуты и ~150 К токенов каждый,
сейчас их 3,2 на ролик. Половина кругов уходит не на «нашли плохой кадр», а
на «таких кадров нет в природе»: конкретный человек на конкретном заседании,
свежее событие, частная съёмка. Разведка вскрывает это ДО качки, за секунды,
и такая сцена сразу уходит в карточку или всплывашку, а не в третий круг.

ЗАПУСК:
    python3 nalichie.py <ролик>.scenes.json            # по всем поисковым сценам
    python3 nalichie.py <ролик>.scenes.json --gate     # код возврата 1, если есть ПУСТО
    python3 nalichie.py --zapros "Фридрих Мерц Бундестаг"   # разово, одна строка

ЧТО СЧИТАЕТ (ничего не скачивается, только числа):
    Викисклад · Openverse · Архив Интернета · НАСА — без ключей
    Pexels · Pixabay — если ключи живы (kluchi.env)

КАК ЧИТАТЬ ОТВЕТ:
    ГУСТО        — материала много, сцена идёт в фетч как есть
    ТОНКО        — материал есть, но на один-два кадра: запрос сузить по
                   субъекту или держать замену наготове
    ТОЛЬКО ПОИСК — в АРХИВАХ этого нет. Останется картиночный поиск
                   (яндекс/ddg) — он что-нибудь принесёт всегда, но именно
                   он даёт мимо-тему и чужие клейма, то есть круги правок.
                   Важную сцену закрывать карточкой, всплывашкой или базой,
                   а не надеяться на третий заход.

ЧЕСТНО О ГРАНИЦАХ. Считаются АРХИВЫ (Викисклад, Openverse, Архив Интернета,
НАСА) — верх нашего водопада. Яндекс и DDG, которыми водопад заканчивается,
пересчитать нельзя: они не отдают числа. Поэтому «ТОЛЬКО ПОИСК» — это не
«кадра нет в природе», а «лёгкого и чистого кадра нет, дальше рулетка».
Сток (Pexels, Pixabay) считается ОТДЕЛЬНО и только для сток-сцен: он отвечает
большими числами на любой запрос, включая бессмысленный, и в разведке
конкретного человека или события не участвует вообще — иначе он замажет
пустоту четырёхзначным числом (проверено 11.11 на «Фридрих Мерц Бундестаг»:
архивы по существу пусты, Pexels отвечает 4650).
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    " (KHTML, like Gecko) Chrome/125.0 Safari/537.36"}
OBSHIY = os.path.expanduser("~/.claude/skills/news-video/kluchi.env")

# Источники сцен, за которыми реально идёт поиск в сети. Карточки, база,
# донор и прямые ссылки разведки не требуют — там кадр уже есть.
POISKOVYE = {"press_photo", "wikimedia", "web_search", "yandex", "ddg",
             "openverse", "archive", "pexels_photo", "pexels_video",
             "pixabay_photo", "pixabay_video", "stock_photo", "flickr", "dvids"}


def _chitat(p):
    if not os.path.exists(p):
        return {}
    return dict(l.strip().split("=", 1) for l in open(p, encoding="utf-8")
                if "=" in l and not l.strip().startswith("#"))


def _klyuchi(papka):
    e = _chitat(OBSHIY)
    e.update({k: v for k, v in _chitat(os.path.join(papka, ".env")).items() if v.strip()})
    return e


def _get(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _json(url, headers=None, timeout=12):
    return json.loads(_get(url, headers, timeout))


# ------------------------------------------------------------------ счётчики
# Каждый возвращает ЧИСЛО найденного или None, если источник не ответил.
# None и 0 — разные вещи: лежащий источник не должен выглядеть как «пусто».

def _wikimedia(q):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "list": "search",
        "srsearch": f'{q} filetype:bitmap', "srnamespace": "6", "srlimit": "1",
        "srinfo": "totalhits", "srprop": ""})
    return _json(url).get("query", {}).get("searchinfo", {}).get("totalhits")


def _openverse(q):
    url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": q, "page_size": 1, "license_type": "all-cc"})
    return _json(url, timeout=20).get("result_count")


def _archive(q):
    url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode({
        "q": f'({q}) AND mediatype:(image)', "fl[]": "identifier",
        "rows": "1", "output": "json"})
    return _json(url).get("response", {}).get("numFound")


def _nasa(q):
    url = "https://images-api.nasa.gov/search?" + urllib.parse.urlencode(
        {"q": q, "media_type": "image"})
    return _json(url).get("collection", {}).get("metadata", {}).get("total_hits")


def _pexels(q, key):
    if not key:
        return None
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": q, "per_page": 1})
    return _json(url, headers={"Authorization": key}).get("total_results")


def _pixabay(q, key):
    if not key:
        return None
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode(
        {"key": key, "q": q, "per_page": 3})
    return _json(url).get("totalHits")


# ГОД В ЗАПРОСЕ УБИВАЕТ АРХИВЫ (замер 11.11 на живом ролике kl-cloud: 15 из
# 15 поисковых запросов дали по архивам НОЛЬ, и у всех пятнадцати внутри стоял
# «2026»). Архив подписывает файл событием и местом, а не годом съёмки, и
# лишнее слово выбрасывает всю выдачу. Поэтому разведка считает ВТОРОЙ раз —
# по очищенному запросу — и, если он живой, прямо говорит, что убрать.
ГОД = re.compile(r"\b(19|20)\d{2}\b")
ХВОСТ = {"портрет", "фасад", "вход", "выступление", "здание", "здания", "вечером",
         "зимой", "утром", "ночью", "крупным", "планом", "общий", "план",
         "кадр", "съёмка", "фото", "видео", "тёмная", "тёмные", "улица", "окна"}


def chistyy(q):
    """Запрос без года и без родовых хвостов. Пустой — значит чистить нечего."""
    slova = [w for w in ГОД.sub(" ", q).split()
             if w.lower().strip(".,") not in ХВОСТ]
    novyy = " ".join(slova)
    return novyy if novyy and novyy != q else ""


def razvedka(q, env):
    """Считает по всем источникам разом. Молча терпит лежащие источники."""
    rabota = {
        "Викисклад": lambda: _wikimedia(q),
        "Openverse": lambda: _openverse(q),
        "Архив": lambda: _archive(q),
        "НАСА": lambda: _nasa(q),
        "Pexels": lambda: _pexels(q, env.get("PEXELS_API_KEY")),
        "Pixabay": lambda: _pixabay(q, env.get("PIXABAY_API_KEY")),
    }
    ch = chistyy(q)
    if ch:
        rabota["_чистый"] = lambda: _wikimedia(ch)
    itog = {}
    with ThreadPoolExecutor(max_workers=len(rabota)) as pool:
        futures = {name: pool.submit(fn) for name, fn in rabota.items()}
        for name, f in futures.items():
            try:
                itog[name] = f.result(timeout=25)
            except Exception:
                itog[name] = None
    return itog


# ПОРОГИ. Сняты с живого счёта 11.11: «съезд КПСС» — Викисклад 133, Архив 1;
# «Владимир Путин пресс-конференция» — Викисклад 1; «заседание бундестага
# 7 ноября 2026 года» — везде 0. Решает САМЫЙ ЩЕДРЫЙ архив: один живой архив
# с материалом важнее, чем три пустых.
GUSTO, TONKO = 25, 3
ARHIVY = ("Викисклад", "Openverse", "Архив", "НАСА")
STOK = ("Pexels", "Pixabay")


def verdikt(itog, stokovaya=False):
    """stokovaya=True для сцен источника pexels_*/pixabay_*: там сток и есть
    цель, и считать надо его. Для всех остальных сток не считается вовсе."""
    klyuchi = STOK if stokovaya else ARHIVY
    chisla = [v for k, v in itog.items() if k in klyuchi and isinstance(v, int)]
    if not chisla:
        return "НЕТ СВЯЗИ", 0
    best = max(chisla)
    if best >= GUSTO:
        return "ГУСТО", best
    if best >= TONKO:
        return "ТОНКО", best
    # Архивы по полному запросу пусты — но, может, их убивает одно лишнее слово.
    ch = itog.get("_чистый")
    if not stokovaya and isinstance(ch, int) and ch >= TONKO:
        return "ПОЧИСТИТЬ ЗАПРОС", ch
    return ("ПУСТО" if stokovaya else "ТОЛЬКО ПОИСК"), best


def _scenes(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["scenes"] if isinstance(d, dict) else d


def main():
    ap = argparse.ArgumentParser(description="Разведка наличия кадров до фетча")
    ap.add_argument("scenes", nargs="?", help="<ролик>.scenes.json")
    ap.add_argument("--zapros", help="проверить один запрос и выйти")
    ap.add_argument("--gate", action="store_true",
                    help="код возврата 1, если есть сцены ПУСТО")
    a = ap.parse_args()

    papka = os.path.dirname(os.path.abspath(a.scenes)) if a.scenes else os.getcwd()
    env = _klyuchi(papka)

    if a.zapros:
        itog = razvedka(a.zapros, env)
        v, best = verdikt(itog)
        print(f"{v:<13} {best:>6}  {a.zapros}")
        print("              " + " · ".join(
            f"{k} {('—' if v2 is None else v2)}" for k, v2 in itog.items()
            if k != "_чистый"))
        if isinstance(itog.get("_чистый"), int):
            print(f"              без года и хвостов → {itog['_чистый']}: "
                  f"«{chistyy(a.zapros)}»")
        return 0

    if not a.scenes:
        ap.error("нужен <ролик>.scenes.json или --zapros")

    sc = _scenes(a.scenes)
    # Одинаковые запросы считаем один раз: в ролике их обычно 10-15% повторов.
    zadachi, stok_zapros = {}, {}
    for s in sc:
        if s.get("source") not in POISKOVYE:
            continue
        q = (s.get("source_query") or "").strip()
        if q:
            zadachi.setdefault(q, []).append(s.get("id"))
            stok_zapros[q] = (s.get("source") or "").startswith(("pexels", "pixabay", "stock"))

    if not zadachi:
        print("Поисковых сцен нет — разведка не нужна.")
        return 0

    print(f"РАЗВЕДКА: {len(zadachi)} запросов "
          f"({sum(len(v) for v in zadachi.values())} сцен из {len(sc)})\n")

    rez = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for q, itog in zip(zadachi, pool.map(lambda x: razvedka(x, env), zadachi)):
            rez[q] = itog

    pusto, tonko, chistit = [], [], []
    for q, itog in rez.items():
        v, best = verdikt(itog, stok_zapros.get(q, False))
        sceny = ",".join(str(i) for i in zadachi[q])
        print(f"  {v:<13} {best:>6}  сц.{sceny:<12} {q[:66]}")
        if v == "ПОЧИСТИТЬ ЗАПРОС":
            chistit.append((q, chistyy(q), zadachi[q]))
        elif v in ("ТОЛЬКО ПОИСК", "ПУСТО"):
            pusto.append((q, zadachi[q]))
        elif v == "ТОНКО":
            tonko.append((q, zadachi[q]))

    print()
    if chistit:
        print(f"ПОЧИСТИТЬ ЗАПРОС — {len(chistit)}: по полному архивы молчат, а")
        print("без года и родовых хвостов материал есть. Переписать так:")
        for q, ch, ids in chistit:
            print(f"    сц.{','.join(str(i) for i in ids):<10} «{q[:40]}» → «{ch[:40]}»")
        print()
    if pusto:
        print(f"АРХИВЫ ПУСТЫ — {len(pusto)} запросов. Дальше только картиночный")
        print("поиск, то есть рулетка и круги правок. Важные сцены закрывать")
        print("карточкой (card_put.py / element_put.py), всплывашкой или базой.")
        print("Сцены: " + ", ".join(",".join(str(i) for i in ids) for _, ids in pusto))
    if tonko:
        print(f"ТОНКО — {len(tonko)} запросов: материал есть, но на один-два кадра.")
        print("Запрос сузить по субъекту или держать замену наготове. Сцены: "
              + ", ".join(",".join(str(i) for i in ids) for _, ids in tonko))
    if not pusto and not tonko:
        print("Всё ГУСТО — фетч можно пускать как есть.")

    return 1 if (a.gate and pusto) else 0


if __name__ == "__main__":
    sys.exit(main())
