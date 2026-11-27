#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Поиск lon/lat по названию места в тексте сцены — словарь театра
Украина/Россия/Чёрное море (24.11.2026, его прямое слово «давай, сделай»).
Не геокодер общего назначения: только наш локальный список
data/places_ua_theater.json, подстрокой по стему (падежи сохраняют основу).

    from place_lookup import find_in_text, point
    find_in_text("Радар под Одессой")  -> [{"name": "Одесса", "lon":..., "lat":..., "side": "ua"}]
    point("Киев")                      -> (30.5234, 50.4501)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "places_ua_theater.json")

_places = None


def _norm(s):
    return s.replace("ё", "е").replace("Ё", "Е").lower()  # ё→е, И→и


def _load():
    global _places
    if _places is None:
        with open(DATA, encoding="utf-8") as f:
            _places = json.load(f)["places"]
    return _places


def find_in_text(text):
    """Все места словаря, чей стем встречается в тексте. Порядок — как
    встретились в тексте (по позиции первого вхождения), без дублей по имени."""
    t = _norm(text)
    hits = []
    for p in _load():
        pos = t.find(_norm(p["stem"]))
        if pos >= 0:
            hits.append((pos, p))
    hits.sort(key=lambda x: x[0])
    seen = set()
    out = []
    for _, p in hits:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        out.append(p)
    return out


def point(name_or_text):
    """Первое совпадение как (lon, lat), или None, если ничего не нашлось.
    Принимает и точное имя места, и произвольный текст сцены."""
    hits = find_in_text(name_or_text)
    if not hits:
        return None
    return (hits[0]["lon"], hits[0]["lat"])


def by_name(name):
    """Точка по точному имени словаря (как в поле name), без поиска по тексту."""
    for p in _load():
        if p["name"] == name:
            return (p["lon"], p["lat"])
    return None


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Удар по Одессе, ответ прилетел из Ростова-на-Дону"
    for p in find_in_text(q):
        print(f"{p['name']:20s} {p['side']:8s} lon={p['lon']:.4f} lat={p['lat']:.4f}")
