#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РАСКАДРОВКА КЛОНА БЕРЁТСЯ У ДОНОРА, А НЕ ЗАКАЗЫВАЕТСЯ ЗАНОВО (12.11.2026).

Его слово 12.11 по третьему варианту темы: «От какого агента ты ждёшь
раскадровку? Есть же, ещё раз говорю, вчера мы делали эти темы две. Какая ещё
раскадровка тебе нужна?»

Было: вкладка звала внешнего агента на полную раскадровку клона (10-20 минут
ожидания и сожжённый заход), хотя у двух доноров той же темы лежат готовые,
УЖЕ УТВЕРЖДЁННЫЕ сцены с запросами и карточками. `kadry_klon.py` умеет брать
их КАДРЫ, но только когда у клона уже есть свой scenes.json.

Стало: сцены донора переносятся на НАШ тайминг. Состав сцен, запросы,
источники и карточки — донорские (их он утвердил вчера); длительности
пересчитаны под нашу озвучку, текст сцены взят из НАШЕГО srt по окну времени.
Дальше обычный ход клона: `kadry_klon.py` (кадры донора по запросу — теперь
совпадение точное) → фетч ТОЛЬКО по остатку → сита → сдача.

    python3 scenes_klon.py <донор.scenes.json> <наш.srt> --out <проект>.scenes.json
"""
import argparse
import json
import os
import re
import sys


def сцены(path):
    d = json.load(open(path, encoding="utf-8"))
    return (d.get("scenes", d) if isinstance(d, dict) else d), d


def время(s):
    ч, м, ост = s.split(":")
    сек, мс = ост.replace(",", ".").split(".")
    return int(ч) * 3600 + int(м) * 60 + int(сек) + int(mс_норм(мс)) / 1000.0


def mс_норм(мс):
    return (мс + "000")[:3]


def куски_srt(path):
    """[(начало, конец, текст)] из srt в любой из наших кодировок."""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit("srt не читается ни в одной из наших кодировок: %s" % path)
    куски = []
    for блок in re.split(r"\n\s*\n", txt.replace("\r", "")):
        стр = [s for s in блок.split("\n") if s.strip()]
        if len(стр) < 2:
            continue
        м = re.search(r"(\d\d:\d\d:\d\d[,.]\d+)\s*-->\s*(\d\d:\d\d:\d\d[,.]\d+)",
                      блок)
        if not м:
            continue
        текст = " ".join(стр[стр.index([l for l in стр if "-->" in l][0]) + 1:])
        куски.append((время(м.group(1)), время(м.group(2)), текст.strip()))
    return куски


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("donor")
    ap.add_argument("srt")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    донор, обёртка = сцены(a.donor)
    куски = куски_srt(a.srt)
    if not куски:
        sys.exit("в srt нет ни одной реплики: %s" % a.srt)
    всего = куски[-1][1]

    # ДЛИТЕЛЬНОСТИ МАСШТАБИРУЕМ, А НЕ ПЕРЕСЧИТЫВАЕМ ПО РЕПЛИКАМ: ритм сцен
    # донора он утвердил, и ломать его из-за разницы в полминуты незачем.
    д_всего = sum(float(s.get("duration_sec") or 0) for s in донор) or всего
    к = всего / д_всего

    новые, t = [], 0.0
    for i, s in enumerate(донор):
        д = float(s.get("duration_sec") or 0) * к
        if i == len(донор) - 1:
            д = max(0.5, всего - t)
        текст = " ".join(тк for н, кн, тк in куски if н < t + д and кн > t)
        новые.append({
            "id": s.get("id") or ("scene_%03d" % (i + 1)),
            "start_sec": round(t, 3),
            "duration_sec": round(д, 3),
            "text": текст or (s.get("text") or ""),
            "source": s.get("source"),
            "source_query": s.get("source_query"),
        })
        t += д

    итог = {"scenes": новые}
    if isinstance(обёртка, dict):
        for ключ, знач in обёртка.items():
            if ключ != "scenes":
                итог[ключ] = знач
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(итог, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.out)
    print("раскадровка клона: %s" % a.out)
    print("  сцен: %d (у донора %d) · озвучка %.1f с · ритм донора × %.3f"
          % (len(новые), len(донор), всего, к))
    print("  источники донора сохранены: карточек %d, поиск %d, медиатека %d"
          % (sum(1 for s in новые if str(s["source"]).startswith("card")),
             sum(1 for s in новые if s["source"] in ("press_photo", "web_search",
                                                     "pexels_photo", "pexels_video")),
             sum(1 for s in новые if s["source"] == "local_library")))


if __name__ == "__main__":
    main()
