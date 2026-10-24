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
    python3 fetch_maps.py --check [папка КАРТЫ]   # проверить, что уже лежит
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

UA = {"User-Agent": "news-video/0.1 (personal project)"}

# КОНТРАСТ КАРТЫ ВАЖНЕЕ ЕЁ ТОЧНОСТИ — ТЕПЕРЬ ПРОВЕРЯЕТ КОД (2026-10-19).
# Правило известно с 18.10 и подтверждено числом 19.10 (обе утверждённые
# пользователем карты — тёмной заливки, светлую он снял), но выполнялось
# глазами, а глаз на карты работает плохо: контактный лист и OCR для них
# бесполезны. Признак, который РАЗДЕЛЯЕТ: доля насыщенных пикселей. У карты
# с подсвеченной страной 2-4% (Молдова в Европе 2,1%, Израиль в регионе 3,7%,
# утверждённые украинские 1,6% и 24%), у плоского контура «светлое на
# светлом» — 0,25-0,40%. Порог 1% разделяет чисто на всех шести проверенных.
# Карту ниже порога не выбрасываем молча, а помечаем в выводе: решение всё
# равно за человеком, но смотреть он будет уже подсказанное.
SAT_MIN = float(os.environ.get("MAPS_SAT_MIN", "1.0"))

# ПОРОГ ПО ВСЕМУ КАДРУ ДАЁТ ЛОЖНОПОЛОЖИТЕЛЬНЫЕ (2026-10-22, улов `usuario-ad`:
# из пяти библиотечных карт порог прошли четыре, глазами годны ДВЕ). Причина:
# насыщенность набирают ГОЛУБАЯ ВОДА и цветные границы по всему кадру, а
# решает подсветка САМОЙ СТРАНЫ. «Ближний Восток» 1,35% и «Китай» 1,98%
# набрали проценты морем — страна на них не выделена вовсе.
# Меряем два признака, карта годна, если сработал ХОТЬ ОДИН:
#   центр кадра (средние 50%) насыщен — страна-герой всегда в центре;
#   есть заметное КРАСНОЕ пятно — стандартная заливка локаторных карт.
# Проверено на 25 файлах медиатеки: оба ложноположительных отсекаются,
# все утверждённые пользователем карты проходят (включая 4-цветную
# украинскую, у которой красного нет вовсе, но центр насыщен на 43%).
CENTER_MIN = float(os.environ.get("MAPS_CENTER_MIN", "2.5"))
RED_MIN = float(os.environ.get("MAPS_RED_MIN", "0.8"))


def map_metrics(path):
    """(насыщенность всего кадра, насыщенность центра, доля красного), %."""
    from PIL import Image
    im = Image.open(path).convert("HSV").resize((400, 225))
    W, H = im.size
    hb = im.split()[0].tobytes()
    sb = im.split()[1].tobytes()
    vb = im.split()[2].tobytes()
    n = len(sb) or 1
    sat = sum(1 for x in sb if x >= 100) / n * 100
    red = sum(1 for i in range(n)
              if (hb[i] <= 14 or hb[i] >= 241) and sb[i] >= 90 and vb[i] >= 70) / n * 100
    c = im.crop((int(W * .25), int(H * .25), int(W * .75), int(H * .75)))
    cs = c.split()[1].tobytes()
    cn = len(cs) or 1
    center = sum(1 for x in cs if x >= 100) / cn * 100
    return sat, center, red


def _flat_map_warning(path):
    """Вернуть текст предупреждения, если карта плоская (нет подсветки)."""
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return ""
    try:
        sat, center, red = map_metrics(path)
    except Exception:
        return ""
    if center < CENTER_MIN and red < RED_MIN:
        return ("  ВНИМАНИЕ: %s — центр %.2f%%, красного %.2f%% (нужно %.1f%% "
                "или %.1f%%): страна на карте НЕ ПОДСВЕЧЕНА, это «светлое на "
                "светлом». Общая насыщенность %.2f%% тут обманывает — её дают "
                "вода и границы." % (os.path.basename(path), center, red,
                                     CENTER_MIN, RED_MIN, sat))
    return ""

WIDTH = 1600          # ширина растра, в который Commons рендерит svg
# сколько кандидатов тащить на регион (лишнее отсеют глаза). Переопределяется
# переменной MAPS_PER_REGION: у «Blank maps of Ukraine» на Commons 26 файлов, а
# в медиатеку с дефолтной восьмёркой доехало всего два — и этого не хватило
# (2026-10-18: сюжет просил карту Украины трижды, лимит «файл ровно один раз за
# сборку» оставил третью сцену без карты).
PER_REGION = int(os.environ.get("MAPS_PER_REGION", "8"))

# регион → категории Commons. Порядок важен: что выше, то качается первым.
REGIONS = {
    "УКРАИНА":        ["Blank maps of Ukraine"],
    "РОССИЯ":         ["Blank maps of Russia"],
    "ЕВРОПА":         ["Blank maps of Europe"],
    "США":            ["Blank maps of the United States"],
    "БЛИЖНИЙ ВОСТОК": ["Blank maps of the Middle East"],
    # ИРАН — ТОЛЬКО ТОЧЕЧНО (2026-10-22, улов `usuario-f1`). «Blank maps of
    # Iran» дала шесть карт, и ВСЕ светлые: насыщенность 0,0 / 0,0 / 0,0 / 1,5
    # / 12,9 / 13,2 %, причём те 13% — голубая вода, сама страна кремовая на
    # светло-сером. По правилу 19.10 («контраст важнее точности») такие не
    # ставятся вовсе, то есть по Ирану карты фактически не было.
    # «Locator maps of Iran» целиком брать нельзя — там 49 файлов, и почти всё
    # это карты ВНУТРИ Ирана (уезды, провинции), ровно та же ловушка, что с
    # Израилем. Поэтому берём поимённо: Иран красным на фоне региона (8,95%) и
    # на фоне Азии (2,75%), обе 1920 по ширине, обе просмотрены глазами.
    "ИРАН":           ["file:Iran in its region.svg", "file:Iran in Asia.svg"],
    "ИЗРАИЛЬ":        ["Blank maps of Israel"],
    "ГЕРМАНИЯ":       ["Blank maps of Germany"],
    # ПОЛЬША и ЧЕХИЯ — ТОЧЕЧНО, как Иран (2026-10-22, улов `usuario-92`):
    # в обеих папках ВСЕ файлы оказались плоскими (0,00-0,38% насыщенности),
    # то есть по правилу 19.10 карта не ставилась вовсе, хотя география в
    # сценарии названа. Добраны локаторные «страна красным на кремовом»:
    # Польша 7,02% (регион) и 3,47% (Европа), Чехия 4,15% и 2,33%.
    "ПОЛЬША":         ["file:Poland in its region.svg",
                       "file:Poland in Europe.svg"],
    "КИТАЙ":          ["Blank maps of China"],
    "БЕЛАРУСЬ":       ["Blank maps of Belarus"],
    "ВЕНЕСУЭЛА":      ["Blank maps of Venezuela"],
    "ТУРЦИЯ":         ["Blank maps of Turkey"],
    # МОЛДОВА И ИЗРАИЛЬ — ЧЕРЕЗ ЛОКАТОРНЫЕ КАРТЫ (2026-10-19, хвост с 17.10).
    # Категории «Blank maps of…» для них мертвы: у Молдовы её нет вовсе
    # (0 файлов), у Израиля три файла и все исторические (1947, двенадцать
    # колен). Живые категории — локаторные: страна подсвечена на фоне региона,
    # для всплывашки это даже лучше чистого силуэта (тот же приём, что у
    # «Украина на фоне Европы»). Проверено запросом к Commons: Молдова 24
    # файла, Израиль 50.
    # ВНИМАНИЕ: ключ в словаре один. Ниже по файлу стояла ВТОРАЯ строка
    # "МОЛДОВА": ["Blank maps of Moldova"], и она затирала эту — то есть
    # правка 19.10 для Молдовы не работала вовсе, качалась та самая мёртвая
    # категория (поймано 22.10 при доборе Ирана). У Израиля повезло: его
    # локаторная строка стояла ПОСЛЕ, поэтому побеждала.
    "МОЛДОВА":        ["Locator maps of Moldova", "SVG maps of Moldova"],
    "ИЗРАИЛЬ":        ["Locator maps of Israel"],
    "ВЕНГРИЯ":        ["Blank maps of Hungary"],
    "МИР":            ["Blank maps of the world"],
    # дозаведено 17.10 по дырам, найденным в бою
    "РУМЫНИЯ":        ["Blank maps of Romania"],
    "СЛОВАКИЯ":       ["Blank maps of Slovakia"],
    "ЧЕХИЯ":          ["file:Czech Republic in its region.svg",
                       "file:Czechia in Europe.svg"],
    "БОЛГАРИЯ":       ["Blank maps of Bulgaria"],
    # --- ЗАПАДНЫЕ ЗЕМЛИ УКРАИНЫ, дозаведено 18.10 по дыре, найденной в бою ---
    # Повод (5min-okkupaciya-1910): четыре сцены подряд про исторические границы
    # Галиции, Волыни, Закарпатья и Буковины — ни одной карты под них, пришлось
    # закрывать текстовыми надписями «ДО 1939 ГОДА — ПОЛЬША». Надписи сработали,
    # но карта с заштрихованной областью сказала бы это сама.
    # ВНИМАНИЕ: это НЕ категории «Blank maps» — в обычных «Maps of …» лежит много
    # тематического и исторического мусора, поэтому просмотр глазами В ПОЛНЫЙ
    # РАЗМЕР здесь обязателен даже строже обычного.
    # «Maps of Galicia» на Commons пуста (проверено 18.10) — за Галицию работает
    # Львовская область.
    # Брать надо категории ОБЛАСТЕЙ, а не исторических земель: «Maps of
    # Volhynia» и «Maps of Bukovina» — это архив XVII-XIX веков целиком
    # (французские и немецкие гравюры 1712, 1895, ирредентистские проекты
    # 1943), ни одного годного файла из 10 и 9 соответственно. Проверено
    # 18.10, не повторять.
    "ЗАКАРПАТЬЕ":     ["Maps of Zakarpattia Oblast"],
    "ВОЛЫНЬ":         ["Maps of Volyn Oblast"],
    "БУКОВИНА":       ["Maps of Chernivtsi Oblast"],
    "ГАЛИЦИЯ":        ["Maps of Lviv Oblast"],
    # ДОНБАСС добавлен 24.10: ролик «Эвакуация Славянск-Краматорск» целиком
    # про цепочку городов одной области, а в медиатеке были только четыре
    # карты Украины целиком — они этих городов не показывают.
    "ДОНБАСС":        ["Maps of Donetsk Oblast", "Maps of Luhansk Oblast"],
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


def check_dir(root):
    """Прогнать метрики по готовой папке КАРТЫ и сказать, что снимать."""
    bad = 0
    for reg in sorted(os.listdir(root)):
        d = os.path.join(root, reg)
        if not os.path.isdir(d) or reg.startswith("_"):
            continue
        print("== %s" % reg)
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if os.path.isdir(p):
                continue
            try:
                sat, center, red = map_metrics(p)
            except Exception as e:
                print("   ? %s (%s)" % (f[:50], e))
                continue
            ok = center >= CENTER_MIN or red >= RED_MIN
            if not ok:
                bad += 1
            print("   %s центр %6.2f%%  красного %5.2f%%  (весь %6.2f%%)  %s"
                  % ("OK " if ok else "СНЯТЬ", center, red, sat, f[:46]))
    print("\nплоских (снять): %d" % bad)
    return 1 if bad else 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--check":
        return check_dir(argv[1] if len(argv) > 1
                         else os.path.expanduser("~/projects/media-library/КАРТЫ"))
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
            # "file:<имя>" — взять ИМЕННО этот файл, мимо категории: нужно
            # там, где категория есть, но забита мусором (2026-10-22, Иран)
            if c.lower().startswith("file:"):
                # category_files отдаёт заголовки С префиксом «File:» — его же
                # ждёт rasters(); без префикса API молча вернёт пусто
                titles.append("File:" + c[5:].strip())
                continue
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
            # ПРОЗРАЧНОСТЬ СПЛЮЩИВАЕМ НА БЕЛОЕ И КЛАДЁМ JPEG (2026-10-18).
            # Commons отдаёт контурные карты почти всегда PNG с альфа-каналом
            # (проверено: 6 из 6 отобранных — RGBA/LA). ffmpeg кладёт прозрачность
            # ЧЁРНЫМ, то есть карта приехала бы в ролик чёрным прямоугольником с
            # белым контуром — и заметить это можно было бы только на готовом
            # видео. Поэтому сохраняем всегда плоский JPEG на белом фоне.
            try:
                from PIL import Image
                import io as _io
                im = Image.open(_io.BytesIO(blob))
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    flat = Image.new("RGB", im.size, (255, 255, 255))
                    flat.paste(im, mask=im.split()[-1])
                    im = flat
                else:
                    im = im.convert("RGB")
                path = os.path.splitext(path)[0] + ".jpg"
                if os.path.exists(path):
                    continue
                im.save(path, "JPEG", quality=92)
            except Exception as exc:
                print(f"[{reg}] {title}: не смог сплющить ({exc}) — пропускаю")
                continue
            got += 1
            total += 1
            time.sleep(0.4)
        print(f"[{reg}] взято {got} из {len(titles)} кандидатов → {outdir}", flush=True)
        # сразу говорим, какие из скачанных плоские — чтобы просмотр начинался
        # с подозрительных, а не со всех подряд (2026-10-19)
        flat = [w for w in (_flat_map_warning(os.path.join(outdir, f))
                            for f in sorted(os.listdir(outdir))) if w]
        for w in flat:
            print(w, flush=True)
        if flat:
            print(f"[{reg}] плоских: {len(flat)} — их смотреть в полный размер в первую очередь", flush=True)
    print(f"итого файлов: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
