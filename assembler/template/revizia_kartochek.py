# -*- coding: utf-8 -*-
"""Ревизия карточек ролика по его замечаниям 14.11."""
import json, os, re, sys, glob

СЛУЖ = {"и","а","но","да","или","либо","то","же","ли","бы","не","ни","в","во",
        "на","над","под","за","из","от","до","по","при","про","для","без",
        "через","о","об","обо","с","со","к","ко","у","что","как","чем","это"}

def слова(t):
    return {w.strip(",.!?;:«»\"()—-–").lower() for w in str(t or "").split() if len(w) >= 4}

def ревизия(proj):
    беды = []
    q = os.path.join(proj, "cards", "queue")
    for f in sorted(glob.glob(os.path.join(q, "scene_*.json"))):
        sid = int(re.search(r"scene_(\d+)", f).group(1))
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        k = d.get("kwargs", {}) or {}
        vid = str(d.get("view", ""))
        t = str(k.get("text") or "")
        # 1. дубль крупного слова
        верх = слова(t)
        # ПОДПИСИ И ЛИСТЫ ТОЖЕ НЕ ПОВТОРЯЮТ ФРАЗУ (14.11, его слово по сцене
        # 45 третьей темы: «два раза эта фраза повторяется, верхняя и нижняя
        # — конфигурация НАТО, конфигурация НАТО. Почему здесь не
        # исправлено?»). Первая проверка смотрела только три поля, а дубль
        # сидел в `value_sub`: текст «КОНФИГУРАЦИЯ НАТО» и подпись под
        # числом «конфигурация НАТО».
        for поле in ("na_polu", "kick", "value", "value_sub", "title",
                     "kick_sub", "podpis", "author"):
            зн = str(k.get(поле) or "")
            for w in зн.split():
                w2 = w.strip(",.!?;:«»\"()—-–").lower()
                if len(w2) < 4:
                    continue
                if w2 in верх or any(len(v) >= 5 and v[:5] == w2[:5] for v in верх):
                    беды.append((sid, vid, "ДУБЛЬ: «%s» повторяет текст" % зн))
                    break
        # 2. обрывок фразы
        if t:
            tt = t.strip()
            посл = tt.split()[-1].strip(",.;:—-").lower() if tt.split() else ""
            if not re.search(r"[.!?…]$", tt) and (посл in СЛУЖ or len(tt.split()) >= 4):
                if посл in СЛУЖ:
                    беды.append((sid, vid, "ОБРЫВОК: кончается на «%s»" % посл))
                elif re.search(r"[.!?]\s+\S", tt):
                    беды.append((sid, vid, "ОБРЫВОК: хвост после точки — «%s»" % tt[-28:]))
        # 3. досье без имени / коротко
        for лист in (k.get("sheets") or []):
            for w in str(лист).split():
                w2 = w.strip(",.!?;:«»\"()—-–").lower()
                if len(w2) < 5:
                    continue
                if w2 in верх or any(len(v) >= 5 and v[:5] == w2[:5] for v in верх):
                    беды.append((sid, vid, "ДУБЛЬ В ЛИСТЕ: «%s» повторяет текст" % лист))
                    break
        if "dossier" in vid:
            rows = k.get("rows") or []
            есть_имя = any(re.search(r"\b[А-ЯЁ][а-яё]{2,}", str(r)) for r in rows)
            if not есть_имя:
                беды.append((sid, vid, "ДОСЬЕ без имени человека"))
            if len(rows) < 4:
                беды.append((sid, vid, "ДОСЬЕ строк %d — лист полупустой" % len(rows)))
    # 3-бис. ЗАДАНИЕ НОВЕЕ КЛИПА — ПРАВКА НЕ ДОЕХАЛА ДО КАДРА (14.11, его
    # слово: «дата исправлена только в задании — это как вообще? ты не отдал
    # её на переделку, но вывел мне дашборд»). Ревизия обязана отвечать за
    # то, что видно НА ЭКРАНЕ, а не за то, что лежит в json: иначе «0
    # замечаний» означает лишь «я поправил файлы», и он смотрит старый клип.
    for f in sorted(glob.glob(os.path.join(q, "scene_*.json"))):
        sid = int(re.search(r"scene_(\d+)", f).group(1))
        клип = os.path.join(proj, "images", "scene_%03d.mp4" % sid)
        if not os.path.exists(клип):
            continue
        try:
            if os.path.getmtime(f) > os.path.getmtime(клип) + 1:
                беды.append((sid, "клип",
                             "ЗАДАНИЕ НОВЕЕ КЛИПА — правка в кадр НЕ попала, "
                             "нужна перерисовка"))
        except OSError:
            continue

    # 4. скобки в надписях
    ov = os.path.join(proj, "overlays.json")
    if os.path.exists(ov):
        try:
            d = json.load(open(ov, encoding="utf-8"))
            for k2, v in d.items():
                if isinstance(v, dict) and isinstance(v.get("text"), dict):
                    w = v["text"].get("words")
                    if isinstance(w, str) and w.strip().startswith("["):
                        беды.append((int(k2) if str(k2).isdigit() else 0,
                                     "надпись", "СКОБКИ И КАВЫЧКИ в тексте надписи"))
        except Exception:
            pass
    return беды

for proj in sys.argv[1:]:
    b = ревизия(proj)
    print("=== %s — замечаний %d" % (os.path.basename(proj), len(b)))
    for sid, vid, что in sorted(b):
        print("   сцена %-3s %-18s %s" % (sid, vid, что))
