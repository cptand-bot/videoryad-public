#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ГЕЙТ ЧИТАЕМОСТИ РИСОВАННЫХ КАДРОВ — ловит карточку, которая на экране пустая.

Повод (его прямое слово 14.11 вечером): «там половина все карточки наши
бракованные». Класс один: графика на тёмной гамме канала рисуется тонкими
линиями низкого контраста и мелким кеглем — формально кадр нарисован, прогон
рапортует успехом, а зритель видит чёрный прямоугольник.

Замер по 55 карточкам сданного ролика `5min-3-priznalis-peregovory-1511`
(доля «чернил» — пикселей, отличающихся от фона больше чем на 18 из 255;
размах — перепад яркости между 1-м и 99-м процентилем):

    пустые:   map_dist 0,9% · duel 2,2% · slope 2,5% · radar 2,8% ·
              network 2,9% · strike 3,3% · waterfall 3,9% · marker_serif 5,0% ·
              pull 5,4% · pie 5,6%
    бледные:  map_dist размах 18 · line 55
    норма:    приёмы зала 44-70% · вырезка 24-32% · плёнка 34-42%

Отсюда пороги: ЧЕРНИЛ меньше 6% или РАЗМАХ меньше 60 — отказ; меньше 9% —
предупреждение. Белый зал и фото-виды проходят с большим запасом.

    python3 template/chitaemost.py <кадр.jpg | папка | проект> [--json f] [--tiho]

Код возврата: 0 — чисто, 1 — есть брак, 2 — нечего мерить.
"""
import argparse, glob, json, os, sys

PORG_INK_FAIL = 0.06      # доля пикселей, отличных от фона (диаграммы)
PORG_INK_WARN = 0.09
PORG_RAZMAH   = 60.0      # перепад яркости p99-p1
PORG_KONTRAST = 0.0035    # доля пикселей, отличных от фона БОЛЬШЕ ЧЕМ НА 110
PORG_KONTRAST_TEXT = 0.005

# ТЕКСТОВЫЕ ВИДЫ МЕРЯЮТСЯ ИНАЧЕ. У цитаты крупные буквы занимают 2-3%
# площади — по доле «чернил» это «пусто», а с экрана читается прекрасно
# (проверено глазами на `duel` ролика 15-11: две реплики кеглем 52).
# Поэтому у них спрашивается только КОНТРАСТ: есть ли в кадре что-то,
# отличное от фона больше чем на 110 из 255, то есть настоящая надпись.
TEKSTOVYE = {
    "duel", "pull", "strike", "marker_serif", "quote", "repliki", "doc",
    "tape", "paper_typed", "paper_hand", "split", "torn", "prolog",
    "mask_plate", "lenta",
}

# ПАВИЛЬОНЫ И ИЗОБРАЗИТЕЛЬНЫЕ ВИДЫ: содержание несёт сама картинка, подписи
# в них мелкие и служебные. У них спрашивается только наполненность кадра.
# Повод: `prohod` (колоннада с двумя плашками) по контрасту давал 0,21% и
# попадал в брак, хотя глазами это один из лучших кадров ролика.
PAVILONY = {
    "prohod", "kreslo", "tribuna", "mehanizm", "relsy", "globus_map",
    "film", "film_frame", "wall", "photo", "vyrezka", "vyrezka_kontur",
    "dof", "poster", "pechat", "device",
}


# КАРТЫ МЕРЯЮТСЯ ТРЕТЬИМ СПОСОБОМ. Контуры стран тонкие, заливка ровная —
# по «чернилам» карта всегда бедна, но с экрана читается. Решает ПОДПИСЬ:
# карта без единой читаемой надписи и есть «жёлтая заливка во весь материк»
# из его разбора 14.11. Замер по ролику 15-11: map_dist с двумя городами
# 0,21% · map с заливкой без подписей 0,12% · map_regions 0,04%.
# `radar` добавлен 15.11 (улов `usuario-27`, проверено глазами): шестиугольник
# с шестью читаемыми подписями и значениями даёт контраст 0,33% — больше, чем
# хорошая карта (0,13%), и меньше порога. На тёмной гамме контраст не отличает
# здоровую карточку от пустой НИ В ОДНУ сторону, поэтому осевые диаграммы
# судятся глазами, как карты.
KARTY = {"map", "map_dist", "map_regions", "bubbles", "cartogram",
         "globus_map", "relief", "radar"}
PORG_KONTRAST_KARTA = 0.0015


def _pavilon(vid):
    return vid in PAVILONY or vid.startswith("zal")


def mera(put):
    """(чернила, яркость, размах) у кадра; None — файл не читается."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(put).convert("L")
    except Exception:
        return None
    if im.width < 32 or im.height < 32:
        return None
    im = im.resize((480, 270))
    a = np.asarray(im).astype("float32")
    hist, _ = np.histogram(a, bins=32, range=(0, 255))
    fon = (int(hist.argmax()) + 0.5) * 255.0 / 32.0
    d = abs(a - fon)
    ink = float((d > 18).mean())
    kontrast = float((d > 110).mean())
    p1, p99 = float(np.percentile(a, 1)), float(np.percentile(a, 99))
    return ink, float(a.mean()), p99 - p1, kontrast


def vidy_proekta(pdir):
    """{номер сцены: вид} по раскадровке проекта."""
    svoy = os.path.join(pdir, os.path.basename(pdir.rstrip("/")) + ".scenes.json")
    cands = [svoy] if os.path.exists(svoy) else sorted(
        f for f in glob.glob(os.path.join(pdir, "*.scenes.json"))
        if not os.path.basename(f).startswith(("codex", "lib_", "raw"))
        and "donor" not in os.path.basename(f)
        and not any(w in os.path.basename(f)
                    for w in ("overlays_fetch", "maps_fetch", "cards_fetch")))
    if not cands:
        return {}
    try:
        d = json.load(open(cands[0], encoding="utf-8"))
    except Exception:
        return {}
    sc = d.get("scenes") if isinstance(d, dict) else d
    out = {}
    for s in sc or []:
        src = str(s.get("source") or "")
        if src.startswith("card:"):
            try:
                out[int(s.get("id") or s.get("sid") or 0)] = src.split(":", 1)[1]
            except Exception:
                pass
    return out


def kadry(cel):
    """Список (номер сцены, файл) по кадру, папке cards/ или папке проекта."""
    if os.path.isfile(cel):
        return [(0, cel)], {}
    cards = cel if os.path.basename(cel.rstrip("/")) == "cards" else os.path.join(cel, "cards")
    pdir = os.path.dirname(cards.rstrip("/")) if os.path.basename(cards.rstrip("/")) == "cards" else cel
    files = sorted(glob.glob(os.path.join(cards, "scene_*.jpg"))
                   + glob.glob(os.path.join(cards, "scene_*.png")))
    out = []
    for f in files:
        try:
            sid = int(os.path.basename(f).split("_")[1].split(".")[0])
        except Exception:
            sid = 0
        out.append((sid, f))
    return out, vidy_proekta(pdir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cel", help="кадр, папка cards/ или папка проекта")
    ap.add_argument("--json", dest="js", help="куда положить разбор")
    ap.add_argument("--tiho", action="store_true", help="печатать только брак")
    a = ap.parse_args()

    spisok, vidy = kadry(a.cel)
    if not spisok:
        print("chitaemost: нечего мерить в %s" % a.cel, file=sys.stderr)
        return 2

    brak, slabo, rows = [], [], []
    for sid, f in spisok:
        m = mera(f)
        if m is None:
            continue
        ink, yark, razmah, kontrast = m
        vid = vidy.get(sid, "?")
        if vid in TEKSTOVYE:
            # у надписи спрашиваем только, читается ли она
            pusto = kontrast < PORG_KONTRAST_TEXT
            bledno = False
        elif vid in KARTY:
            # КАРТЫ МЕТРИКОЙ НЕ СУДЯТСЯ (15.11, проверено глазами). Порог по
            # контрасту, заведённый утром, забраковал ДВЕ ХОРОШИЕ карты:
            # земли Германии с подсветкой и подписями (контраст 0,00% после
            # ужатия, 0,13% на полном кадре) и Кишинёв—Бухарест с пунктиром
            # и «358 км» (0,7% чернил — карта просто тёмная). При этом
            # «жёлтая заливка без подписей» из его разбора давала 0,26%, то
            # есть БОЛЬШЕ хорошей. Разделить их числом нельзя: карта тёмная
            # и мелкоконтрастная по устройству. Поэтому гейт карты
            # пропускает и помечает «смотреть глазами» — решает дашборд.
            pusto = False
            bledno = False
        elif _pavilon(vid):
            pusto = ink < PORG_INK_FAIL
            bledno = False
        else:
            pusto = ink < PORG_INK_FAIL
            # «жёлтая заливка во весь материк, подписей нет» — его слово о
            # карте 14.11: чернил много, а читаемой надписи в кадре нет
            bledno = razmah < PORG_RAZMAH or kontrast < PORG_KONTRAST
        rows.append({"sid": sid, "vid": vid, "fayl": os.path.basename(f),
                     "chernil": round(ink * 100, 1), "yarkost": round(yark, 1),
                     "razmah": round(razmah, 1),
                     "kontrast": round(kontrast * 100, 2),
                     "verdikt": "пусто" if pusto else ("бледно" if bledno else
                                ("карта — глазами" if vid in KARTY else
                                 ("слабо" if (vid not in TEKSTOVYE
                                              and ink < PORG_INK_WARN) else "ок")))})
        if pusto or bledno:
            brak.append(rows[-1])
        elif vid not in TEKSTOVYE and ink < PORG_INK_WARN:
            slabo.append(rows[-1])

    if not a.tiho:
        print("sid  вид             чернил%  контр%  размах  вердикт")
        for r in sorted(rows, key=lambda x: x["kontrast"]):
            print("%3d  %-15s %6.1f %6.2f %6.1f  %s"
                  % (r["sid"], r["vid"][:15], r["chernil"], r["kontrast"],
                     r["razmah"], r["verdikt"]))
    if a.js:
        json.dump({"kadry": rows, "brak": brak}, open(a.js, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    if brak:
        print("")
        print("НЕЧИТАЕМЫХ КАРТОЧЕК: %d из %d — на экране это пустой кадр."
              % (len(brak), len(rows)))
        for r in brak:
            print("   сцена %d · %s · чернил %.1f%% · контраст %.2f%% · размах %.0f (%s)"
                  % (r["sid"], r["vid"], r["chernil"], r["kontrast"],
                     r["razmah"], r["verdikt"]))
        print("Лечение: сменить вид на изобразительный (`card_put.py … --view`),")
        print("либо дать виду больше данных — у диаграмм на тёмной гамме")
        print("тонкая линия и мелкая подпись в кадре не видны.")
        return 1
    if slabo and not a.tiho:
        print("")
        print("НА ГРАНИ (не отказ): %s"
              % ", ".join("%d/%s %.1f%%" % (r["sid"], r["vid"], r["chernil"])
                          for r in slabo))
    if not a.tiho:
        print("")
        print("читаемость: брака нет (%d кадров)" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
