#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Авто-дедуп: находит md5-дубли между images/ и overlays/, переписывает
source_query проигравших на заведомо новую фразу (не встречающуюся нигде
в текущих scenes.json/overlays_fetch.scenes.json), дорефетчивает и
повторяет, пока дублей не останется или не кончится запас фраз.

Рождён 2026-10-10 на сборке olka-dizelka-vzglyad-1110 (127 сцен) — при
программной генерации запросов для большого числа generic-сцен маленький
пул фраз (8-10 штук) неизбежно коллизирует сам с собой пачками (rule h
SKILL.md, просто в масштабе). Ручная погоня за каждым дублем по одному
не успевает за автогенерацией; этот скрипт закрывает весь цикл
"нашёл-переписал-дорефетчил-перепроверил" без ручного вмешательства.

Usage:
  python3 autodedup.py <main_scenes.json> <images_dir> \
      [--overlays <overlays_fetch.scenes.json> <overlays_dir>] \
      [--overlays-json <overlays.json>] [--env .env] [--max-rounds 5]

Запускать из папки проекта (как и остальные скрипты). Все пути — обычные
scenes.json двух типов, как в остальном пайплайне. Если overlays не
используются — не передавай --overlays.

Печатает прогресс по раундам и финальный список оставшихся дублей (пустой
список = чисто). Возврат кода: 0 всегда (сам скрипт не падает на
оставшихся дублях — если после max-rounds дубли ещё есть, это означает,
что пул фраз исчерпан или сам пайплайн что-то стабильно блокирует,
смотреть глазами).
"""
import argparse, hashlib, glob, json, os, subprocess, sys

BIG_POOL = [
 "lighthouse coastline waves rocks", "vineyard rows field sunset", "steel mill furnace sparks",
 "mining excavator quarry pit", "water treatment plant tanks", "solar panels field aerial",
 "customs checkpoint cargo trucks", "rail yard freight cars", "tollbooth highway cars",
 "cold storage warehouse workers", "greenhouse farm crops rows", "windmill farm countryside",
 "harbor lighthouse sunset silhouette", "train station platform empty", "subway tunnel tracks lights",
 "car wash automated brushes", "tractor plowing field dust", "combine harvester wheat field",
 "shipping dock forklift pallets", "cargo plane loading tarmac", "helicopter landing pad",
 "oil tank farm aerial view", "LNG terminal tanks night", "gas flare tower industrial",
 "steel pipes stacked yard", "crane barge river water", "icebreaker ship arctic",
 "ferry boat crossing river", "cruise ship port dock", "tanker truck gas station",
 "electric car charging station", "hydrogen fuel pump station", "battery factory assembly",
 "data server racks blinking", "satellite uplink dish field", "weather station instruments",
 "observatory telescope dome night", "wind farm offshore turbines", "hydroelectric dam spillway",
 "coal mine conveyor belt", "steel foundry molten metal", "textile factory looms",
 "printing press rolling paper", "bookbindery workshop machines", "glass factory furnace workers",
 "ceramics kiln pottery workshop", "brewery tanks industrial", "bottling plant conveyor line",
 "lumber mill sawdust workshop", "candle factory wax molds", "leather tannery workshop",
 "rice paddy field aerial", "coffee plantation rows hills", "tea plantation terraces aerial",
 "salt flats aerial pattern", "quarry stone cutting workshop", "shipbuilding dry dock crane",
 "aircraft hangar maintenance workers", "racetrack empty grandstand", "stadium empty seats aerial",
]

def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("main_scenes")
    ap.add_argument("images_dir")
    ap.add_argument("--overlays", nargs=2, metavar=("OVERLAYS_FETCH_JSON", "OVERLAYS_DIR"))
    ap.add_argument("--overlays-json", default="overlays.json")
    ap.add_argument("--env", default=".env")
    ap.add_argument("--max-rounds", type=int, default=5)
    a = ap.parse_args()

    files_map = {a.main_scenes: a.images_dir}
    if a.overlays:
        files_map[a.overlays[0]] = a.overlays[1]

    def dedup_groups():
        files = []
        for _, d in files_map.items():
            files += glob.glob(os.path.join(d, "scene_*.*"))
        files = [f for f in files if ".json" not in f and ".ovthumb." not in f and ".text." not in f]
        by_hash = {}
        for f in files:
            by_hash.setdefault(md5(f), []).append(f)
        return [v for v in by_hash.values() if len(v) > 1]

    def parse_path(f):
        d = os.path.dirname(f)
        sid = int(os.path.basename(f).split("_")[1].split(".")[0])
        for sfile, sdir in files_map.items():
            if os.path.normpath(sdir) == os.path.normpath(d):
                return sfile, sdir, sid
        raise ValueError(f"unrecognized dir for {f}")

    for round_n in range(1, a.max_rounds + 1):
        groups = dedup_groups()
        if not groups:
            print(f"=== round {round_n}: CLEAN ===")
            break
        print(f"=== round {round_n}: {len(groups)} duplicate groups ===")

        all_q = set()
        loaded = {}
        for sfile in files_map:
            d = json.load(open(sfile, encoding="utf-8"))
            loaded[sfile] = d
            all_q |= set(s.get("source_query", "") for s in d["scenes"])
        pool_i = 0

        to_fix = {sfile: [] for sfile in files_map}
        for g in groups:
            g_sorted = sorted(g)
            for loser in g_sorted[1:]:
                sfile, sdir, sid = parse_path(loser)
                while pool_i < len(BIG_POOL) and BIG_POOL[pool_i] in all_q:
                    pool_i += 1
                q = BIG_POOL[pool_i] if pool_i < len(BIG_POOL) else f"industrial scene variant {pool_i}"
                pool_i += 1
                all_q.add(q)
                to_fix[sfile].append((sid, q))
                os.remove(loser)
                print("  reassign", loser, "->", q)

        for sfile, items in to_fix.items():
            if not items:
                continue
            d = loaded[sfile]
            idmap = dict(items)
            for s in d["scenes"]:
                if s["id"] in idmap:
                    s["source"] = "pexels_video"
                    s["source_query"] = idmap[s["id"]]
                    s["visual_prompt"] = idmap[s["id"]]
            json.dump(d, open(sfile, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            img_dir = files_map[sfile]
            here = os.path.dirname(os.path.abspath(__file__))
            r = subprocess.run(
                [sys.executable, os.path.join(here, "fetch_assets_news.py"), sfile, img_dir, a.env],
                capture_output=True, text=True, timeout=240)
            print(r.stdout[-1200:])
            if r.returncode != 0:
                print("STDERR", r.stderr[-500:])

        if a.overlays and to_fix.get(a.overlays[0]):
            ov_path = a.overlays_json
            if os.path.exists(ov_path):
                ov = json.load(open(ov_path, encoding="utf-8"))
                for k in list(ov.keys()):
                    if k == "anchor":
                        continue
                    sid = int(k)
                    fs = [f for f in glob.glob(os.path.join(a.overlays[1], f"scene_{sid:03d}.*"))
                          if ".json" not in f]
                    if fs:
                        ov[k]["photo"] = fs[0]
                json.dump(ov, open(ov_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    else:
        print("!!! hit max-rounds, duplicates may remain — check manually")

    groups = dedup_groups()
    print("FINAL remaining duplicate groups:", len(groups))
    for g in groups:
        print(" ", g)

if __name__ == "__main__":
    main()
