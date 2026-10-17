#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_maps.py — наполнение папки КАРТЫ в медиатеке чистыми картами с
Wikimedia Commons.

Зачем: «карта» как класс запроса водопадом НЕ ДОБЫВАЕТСЯ (живой случай
2026-10-17, `planeta-svergnut-1810`: «политическая карта Украины с областями»
— FAILED на двух формулировках, всплывашка потеряна). Причина нашлась в коде:
чистые контурные карты на Commons почти все в SVG, а `fetch_wikimedia` SVG
всегда отбрасывал. Поиском их брать всё равно ненадёжно — на «blank outline
map of Ukraine oblasts» первым результатом приехал контур ЛУГАНСКОЙ ОБЛАСТИ.
Поэтому карты берём не поиском, а из КАТЕГОРИЙ Commons («Category:Blank maps
of Ukraine») и кладём в медиатеку один раз, глазами. Дальше сцены пинятся
файлом из папки — ни запроса, ни языка, ни случайностей.

Лицензии: файлы категорий Blank maps — PD/CC, подписи в кадре отсутствуют
(это и есть «чистая» карта), поэтому правило a1 (текст в кадре) не нарушается.

Использование:
    python3 fetch_maps.py <куда> [регион ...]     # по умолчанию все известные
    python3 fetch_maps.py --list                  # какие регионы знаю
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

UA = {"User-Agent": "news-video/0.1 (personal project)"}
WIDTH = 1600          # ширина растра, в который Commons рендерит svg
PER_REGION = 8        # сколько кандидатов тащить на регион (лишнее отсеют глаза)

# регион → категории Commons. Порядок важен: что выше, то качается первым.
REGIONS = {
    "УКРАИНА":        ["Blank maps of Ukraine"],
    "РОССИЯ":         ["Blank maps of Russia"],
    "ЕВРОПА":         ["Blank maps of Europe"],
    "США":            ["Blank maps of the United States"],
    "БЛИЖНИЙ ВОСТОК": ["Blank maps of the Middle East"],
    "ИРАН":           ["Blank maps of Iran"],
    "ИЗРАИЛЬ":        ["Blank maps of Israel"],
    "ГЕРМАНИЯ":       ["Blank maps of Germany"],
    "ПОЛЬША":         ["Blank maps of Poland"],
    "КИТАЙ":          ["Blank maps of China"],
    "БЕЛАРУСЬ":       ["Blank maps of Belarus"],
    "ВЕНЕСУЭЛА":      ["Blank maps of Venezuela"],
    "ТУРЦИЯ":         ["Blank maps of Turkey"],
    "МОЛДОВА":        ["Blank maps of Moldova"],
    "ВЕНГРИЯ":        ["Blank maps of Hungary"],
    "МИР":            ["Blank maps of the world"],
    # дозаведено 17.10 по дырам, найденным в бою
    "РУМЫНИЯ":        ["Blank maps of Romania"],
    "СЛОВАКИЯ":       ["Blank maps of Slovakia"],
    "ЧЕХИЯ":          ["Blank maps of the Czech Republic"],
    "БОЛГАРИЯ":       ["Blank maps of Bulgaria"],
    # у Молдовы и Израиля категории Blank maps на Commons НЕТ (проверено
    # 17.10): Moldova — 0 файлов, Israel — 3 и все исторические (1947,
    # двенадцать колен). Эти карты надо искать иначе или рисовать.
}

# что в категории не карта, а мусор для нас
SKIP_WORDS = ("flag", "coat of arms", "logo", "diagram", "graph", "chart",
              "timeline", "animation", "gif", "icon", "globe", "1860", "1914",
              "1939", "1941", "1945", "ussr", "sfr", "empire", "historical")


def api(**params):
    # Commons бьёт 429 уже на десятке запросов подряд (поймано 2026-10-17) —
    # отступаем и повторяем, иначе половина регионов остаётся пустой.
    params.setdefault("format", "json")
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                time.sleep(1.2)
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))
    return {}


def category_files(cat, limit=40):
    d = api(action="query", list="categorymembers",
            cmtitle="Category:" + cat, cmtype="file", cmlimit=limit)
    return [m["title"] for m in d.get("query", {}).get("categorymembers", [])]


def rasters(titles):
    """title → (url растра, w, h). SVG отдаётся отрендеренным в PNG."""
    out = []
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        d = api(action="query", titles="|".join(chunk), prop="imageinfo",
                iiprop="url|size|mime", iiurlwidth=WIDTH)
        for p in d.get("query", {}).get("pages", {}).values():
            for ii in p.get("imageinfo", []):
                url = ii.get("thumburl") or ii.get("url")
                w = ii.get("thumbwidth") or ii.get("width") or 0
                h = ii.get("thumbheight") or ii.get("height") or 0
                if url and not url.lower().endswith((".gif", ".tif", ".tiff")):
                    out.append((p["title"], url, w, h))
    return out


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] == "--list":
        print("регионы:", ", ".join(REGIONS))
        return 0
    dest, wanted = argv[0], [a.upper() for a in argv[1:]] or list(REGIONS)
    total = 0
    for reg in wanted:
        cats = REGIONS.get(reg)
        if not cats:
            print(f"[{reg}] нет в списке категорий — пропуск")
            continue
        titles = []
        for c in cats:
            try:
                titles += category_files(c)
            except Exception as exc:
                print(f"[{reg}] категория '{c}': {exc}")
        titles = [t for t in titles
                  if not any(w in t.lower() for w in SKIP_WORDS)]
        got = 0
        outdir = os.path.join(dest, reg)
        os.makedirs(outdir, exist_ok=True)
        for title, url, w, h in rasters(titles):
            if got >= PER_REGION:
                break
            if w < 700 or h < 400:        # мелочь и узкие полоски не берём
                continue
            name = title.replace("File:", "").rsplit(".", 1)[0]
            name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name)[:60]
            ext = ".png" if ".png" in url.lower() else os.path.splitext(url)[1].lower() or ".png"
            path = os.path.join(outdir, f"{name}{ext}")
            if os.path.exists(path):
                continue
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=40) as r:
                    blob = r.read()
            except Exception as exc:
                print(f"[{reg}] {title}: {exc}")
                continue
            if len(blob) < 4000:
                continue
            open(path, "wb").write(blob)
            got += 1
            total += 1
            time.sleep(0.4)
        print(f"[{reg}] взято {got} из {len(titles)} кандидатов → {outdir}", flush=True)
    print(f"итого файлов: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
