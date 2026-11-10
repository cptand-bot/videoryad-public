# -*- coding: utf-8 -*-
"""ЖУРНАЛ ЗАМЕН КАДРА — ОДНА ДВЕРЬ ДЛЯ ВСЕХ ПУТЕЙ ПРАВКИ.

Повод (10.11, его вопрос «проверь брак… где отсчёт?»): замер `brak.py` читает
только `.refetch_rounds.json`, а его вёл ОДИН инструмент — `refetch.py`.
Вкладки же правят кадры и в обход: `ban_file.py`, ручная подмена, загрузка
кадра с дашборда, карточка вместо поиска. За 10.11 не создано НИ ОДНОГО
журнала при 2-4 кругах правок на ролик, и замер честно ответил «данных нет» —
цифры дня просто неоткуда было взять.

Теперь любой путь замены зовёт `zapisat()`, и журнал тот же самый, что ведёт
`refetch` — формат менять нельзя, его читает `brak.py`.

    from zhurnal_zamen import zapisat
    zapisat(project_dir, 12, kind="images", how="ban_file", query="…")

Замены, пришедшие подряд (по умолчанию в пределах 15 минут), считаются ОДНИМ
кругом: круг — это заход правок, а не каждый отдельный кадр, иначе «кругов на
ролик» раздувается и цель «1-2 круга» теряет смысл.
"""
import json
import os
import time

ROUNDS = ".refetch_rounds.json"
# Сколько времени замены считаются одним заходом правок.
OKNO_KRUGA = int(os.environ.get("VIDEORYAD_KRUG_OKNO", "900"))


def _path(project_dir):
    return os.path.join(project_dir or ".", ROUNDS)


def _load(p):
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {"rounds": [], "tried": {}}


def zapisat(project_dir, sid, kind="images", how="ручная замена", query="",
            source=""):
    """Записать ОДНУ замену кадра. Возвращает номер круга, в который попала."""
    p = _path(project_dir)
    jr = _load(p)
    key = "%s:%s" % (kind, sid)
    now = time.time()

    rounds = [r for r in jr.get("rounds", []) if not r.get("fill")]
    last = jr.get("rounds", [])[-1] if jr.get("rounds") else None
    svezh = False
    if last and not last.get("fill"):
        try:
            t = time.mktime(time.strptime(last.get("ts", ""), "%Y-%m-%d %H:%M:%S"))
            svezh = (now - t) <= OKNO_KRUGA
        except Exception:
            svezh = False

    if svezh:
        n = last.get("n") or len(rounds)
        if key not in last.setdefault("ids", []):
            last["ids"].append(key)
        last["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        last.setdefault("how", [])
        if how not in last["how"]:
            last["how"].append(how)
    else:
        n = len(rounds) + 1
        jr.setdefault("rounds", []).append(
            {"n": n, "fill": False, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
             "ids": [key], "how": [how]})

    jr.setdefault("tried", {}).setdefault(key, []).append(
        {"round": n, "source": source or how, "query": query, "fill": False})
    try:
        json.dump(jr, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except OSError:
        pass
    return n


def tikho(project_dir, sid, kind="images", how="ручная замена", query="",
          source=""):
    """То же, но никогда не роняет вызывающего: журнал не повод терять правку."""
    try:
        return zapisat(project_dir, sid, kind=kind, how=how, query=query,
                       source=source)
    except Exception:
        return None
