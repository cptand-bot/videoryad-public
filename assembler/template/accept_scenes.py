# -*- coding: utf-8 -*-
"""ПРИЁМКА РАСКАДРОВКИ, СДЕЛАННОЙ ДРУГИМ АГЕНТОМ (Codex).

Схема с 2026-10-23: Codex расписывает ролик на сцены и придумывает запросы
(самая думающая и дорогая по токенам часть), а сборку ведёт вкладка здесь.
Он ничего не запускает и о наших проверках не знает — значит его файл надо
принять строго, до того как за него заплачено поиском.

    python3 accept_scenes.py "/mnt/d/СБОРЩИК/ГОТОВО/<имя>.scenes.json" \\
        --srt <путь к .srt> [--out 5min.scenes.json]

Что проверяется:
  * структура: есть scenes, у каждой id/text/start_sec/duration_sec/source;
  * ТАЙМИНГ: сцены идут подряд без разрывов и нахлёстов, конец совпадает с
    озвучкой (это главное — на нём рассыпается весь монтаж);
  * источники из разрешённого списка;
  * нормы: доля стока, плотность карточек, расстояние между ними;
  * язык запроса: press_photo/web_search — по-русски, pexels — латиницей.

Чинит само только то, что чинится однозначно (накопленный дрейф start_sec).
Всё остальное — называет и выходит с кодом 1.
"""
import argparse
import json
import os
import re
import sys

OK_SOURCES = {"press_photo", "web_search", "pexels_photo", "pexels_video",
              "local_library", "direct_url"}
CARD_PREFIX = "card:"


def srt_end(path):
    """Последний таймкод SRT в секундах."""
    try:
        txt = open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return 0.0
    last = 0.0
    for m in re.finditer(r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*"
                         r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})", txt):
        h, mi, s, ms = map(int, m.group(5, 6, 7, 8))
        last = max(last, h * 3600 + mi * 60 + s + ms / 1000.0)
    return last


def main():
    ap = argparse.ArgumentParser(description="принять раскадровку от Codex")
    ap.add_argument("src")
    ap.add_argument("--srt", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--fix", action="store_true", help="починить дрейф start_sec")
    a = ap.parse_args()

    try:
        data = json.load(open(a.src, encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"не прочитать {a.src}: {e}")
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not scenes:
        sys.exit("в файле нет сцен")

    bad, warn = [], []
    # --- поля ---
    for i, sc in enumerate(scenes, 1):
        for f in ("id", "text", "start_sec", "duration_sec", "source"):
            if f not in sc:
                bad.append(f"сцена #{i}: нет поля {f}")
        src = str(sc.get("source", ""))
        if src and not src.startswith(CARD_PREFIX) and src not in OK_SOURCES:
            bad.append(f"сцена {sc.get('id')}: неизвестный источник «{src}»")
        if not src.startswith(CARD_PREFIX) and not str(sc.get("source_query", "")).strip():
            bad.append(f"сцена {sc.get('id')}: пустой source_query")
        d = float(sc.get("duration_sec") or 0)
        if d < 3:
            bad.append(f"сцена {sc.get('id')}: длительность {d:.1f} с — короче трёх секунд")
        elif d > 15:
            warn.append(f"сцена {sc.get('id')}: длительность {d:.1f} с — длиннее пятнадцати")

    # --- тайминг: непрерывность ---
    drift = []
    t = 0.0
    for sc in scenes:
        st = float(sc.get("start_sec") or 0)
        if abs(st - t) > 0.05:
            drift.append((sc.get("id"), st, t))
        t = (st if not a.fix else t) + float(sc.get("duration_sec") or 0)
    if drift and not a.fix:
        bad.append(f"ТАЙМИНГ РАЗЪЕХАЛСЯ у {len(drift)} сцен "
                   f"(первая — сцена {drift[0][0]}: стоит {drift[0][1]:.2f}, "
                   f"должно быть {drift[0][2]:.2f}). Перезапусти с --fix")

    total = sum(float(s.get("duration_sec") or 0) for s in scenes)
    if a.srt:
        end = srt_end(a.srt)
        if end and abs(total - end) > 1.5:
            bad.append(f"ДЛИТЕЛЬНОСТЬ НЕ СХОДИТСЯ: сцены дают {total:.1f} с, "
                       f"озвучка {end:.1f} с (разница {abs(total-end):.1f} с)")

    # --- нормы ---
    n = len(scenes)
    stock = sum(1 for s in scenes if str(s.get("source", "")).startswith("pexels"))
    cards = [i for i, s in enumerate(scenes)
             if str(s.get("source", "")).startswith(CARD_PREFIX)]
    if n:
        pct = 100.0 * stock / n
        if pct > 25:
            warn.append(f"стока {pct:.0f}% — коридор 10-20%")
        elif pct < 5:
            warn.append(f"стока {pct:.0f}% — маловато, начало ролика будет статичным")
    norm = max(1, round(n / 15))
    if len(cards) > norm + 1:
        warn.append(f"карточек {len(cards)} при норме {norm} (+1 допуск)")
    for x, y in zip(cards, cards[1:]):
        if y - x < 8:
            warn.append(f"карточки на сценах {scenes[x]['id']} и {scenes[y]['id']} "
                        f"ближе восьми сцен друг к другу")

    # --- ШАБЛОННОСТЬ: уникальность по СМЫСЛУ, а не по приписке (23.10) ---
    # Живой случай: агент получил замечание «запросы повторяются» и приписал к
    # одному шаблону номер сцены — «переговоры …, 2025, сцена 41 — общий план»,
    # «…, сцена 42 — …». Формально 96 уникальных, по сути три. Плюс «сцена 41»
    # внутри поискового запроса — мусор, который поиску мешает.
    junk = re.compile(r"\s*,?\s*сцена\s*\d+\s*[—–-]?.*$|\s*[—–-]\s*(документальн|полевой|общий план).*$",
                      re.I)
    cores = {}
    for sc in scenes:
        if str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q = str(sc.get("source_query", ""))
        if re.search(r"сцена\s*\d+", q, re.I):
            bad.append(f"сцена {sc.get('id')}: в запросе служебная пометка «сцена N» — "
                       f"это мусор для поиска, убери")
        core = junk.sub("", q).strip().lower()
        core = " ".join(core.split()[:6])          # смысловое ядро запроса
        cores.setdefault(core, []).append(sc.get("id"))
    many = {k: v for k, v in cores.items() if len(v) > 3 and k}
    if many:
        worst = max(many.items(), key=lambda kv: len(kv[1]))
        bad.append(f"ЗАПРОСЫ ШАБЛОННЫЕ: {len(many)} формулировок повторяются более трёх раз. "
                   f"Худшая — «{worst[0][:50]}…» на {len(worst[1])} сценах "
                   f"({', '.join(map(str, worst[1][:6]))}…). Нужен СВОЙ предмет в каждой сцене")

    # ГОЛОВНАЯ ГРУППА СЛОВ — ВОТ ЧТО РЕШАЕТ (23.10, улов `usuario-dd`).
    # Прежняя проверка считала ядро по шести словам и ругалась лишь при более
    # чем трёх повторах — и пропустила подмену: агент взял пул из ~34 фраз и
    # прокрутил его ДВАЖДЫ, меняя только хвост-обстоятельство («…, утренний
    # свет» / «…, рядом с наблюдательной машиной»). Формально 95 уникальных
    # строк, на деле 25 пар одинаковых запросов. Поисковик ранжирует по первым
    # словам, хвост игнорирует (правило h), так что на фетче это дало бы
    # ~26 дублей по md5 и круг правок на ровном месте.
    heads = {}
    for sc in scenes:
        if str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q = junk.sub("", str(sc.get("source_query", ""))).strip().lower()
        h = " ".join(q.split()[:3])
        if h:
            heads.setdefault(h, []).append(sc.get("id"))
    pairs = {k: v for k, v in heads.items() if len(v) > 1}
    if pairs:
        total = sum(len(v) for v in pairs.values())
        worst = max(pairs.items(), key=lambda kv: len(kv[1]))
        msg = (f"ОДИНАКОВОЕ НАЧАЛО ЗАПРОСА у {total} сцен в {len(pairs)} группах "
               f"(худшая — «{worst[0]}…» на сценах {', '.join(map(str, worst[1][:8]))}). "
               f"Поиск ранжирует по ПЕРВЫМ словам, хвост-обстоятельство он игнорирует — "
               f"эти сцены получат один и тот же кадр")
        (bad if total > len(scenes) * 0.15 else warn).append(msg)

    # --- КАРТОЧКА: цитата, а не обрывок ---
    for sc in scenes:
        if not str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q = str(sc.get("source_query", "")).strip()
        if not q:
            continue
        first = q.split()[0] if q.split() else ""
        if first and first[:1].islower():
            warn.append(f"сцена {sc.get('id')}: текст карточки начинается с середины фразы "
                        f"(«{q[:40]}…») — нужна цитата целиком")

    # --- язык запроса ---
    cyr = re.compile(r"[а-яёА-ЯЁ]")
    for s in scenes:
        src, q = str(s.get("source", "")), str(s.get("source_query", ""))
        if src in ("press_photo", "web_search") and q and not cyr.search(q):
            warn.append(f"сцена {s.get('id')}: запрос не по-русски — «{q[:60]}»")
        if src.startswith("pexels") and cyr.search(q):
            bad.append(f"сцена {s.get('id')}: pexels ищет только латиницей — «{q[:60]}»")

    print(f"сцен: {n}, общая длительность {total:.1f} с")
    print(f"источники: press/web {sum(1 for s in scenes if s.get('source') in ('press_photo','web_search'))}, "
          f"сток {stock}, карточек {len(cards)}")
    for w in warn:
        print("  ВНИМАНИЕ:", w)
    for b in bad:
        print("  ОШИБКА:", b, file=sys.stderr)

    if a.fix:
        t = 0.0
        for sc in scenes:
            sc["start_sec"] = round(t, 2)
            t += float(sc.get("duration_sec") or 0)
        print("  тайминг пересчитан подряд от нуля")

    if bad and not a.fix:
        print("\nПРИНИМАТЬ НЕЛЬЗЯ — исправь перечисленное или попроси переделать.",
              file=sys.stderr)
        return 1
    if a.out:
        if isinstance(data, dict):
            data.setdefault("channel", "5 МИНУТ")
            data["scenes"] = scenes
        else:
            data = {"channel": "5 МИНУТ", "scenes": scenes}
        json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\nпринято → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
