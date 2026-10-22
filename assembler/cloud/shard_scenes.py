#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Split the scenes that still need a WEB search into N shards for the matrix.

The library stays on the user's machine — library scenes are fetched locally
(disk read, no rate limit) and their images/ ride along. This shards only the
scenes the cloud can actually help with: the ones with NO image yet AND not
`local_library`. Each shard is fetched on its own GitHub runner (its own IP),
so the per-IP Yandex/Wikimedia limits stop being the bottleneck.

    shard_scenes.py <scenes.json> <out-dir> [--images-dir DIR]
                    [--overlays-dir DIR] [--target-per-shard N] [--max-shards M]

Writes <out-dir>/shard0.scenes.json ... and prints the JSON index list
([0,1,...] or []) on stdout for the workflow matrix.

If `overlays_fetch.scenes.json` sits next to <scenes.json>, its scenes are
folded into the same shards tagged `"_dest": "overlays"` (only the ones with
no `<overlays-dir>/scene_NNN.*` yet) so pop-up photos ride the matrix too —
no more serial overlay fetch on one IP in the assemble job.
"""
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "template"))
from fetch_parallel import partition  # noqa: E402

TARGET_PER_SHARD = 4      # was 8 (2026-10-09) -> 4 (2026-10-10, speed test).
                          # ROLLBACK: just set this back to 8, re-run
                          # sync_assembler.sh on all 4 accounts. No other
                          # file depends on this value.
MAX_SHARDS = 20           # GitHub free tier allows ~20 concurrent jobs


def _has_image(images_dir, sid):
    if not images_dir:
        return False
    return bool(glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*")))


def needs_web_fetch(scene, images_dir):
    src = str(scene.get("source") or "")
    if src == "local_library":
        return False
    # card:* — кадр рисуем мы сами (цитата-лоскут и соседи по арсеналу,
    # 2026-10-22). В шард такая сцена попадала и молча пропускалась уже в
    # фетчере: шард тратился впустую, а в манифесте появлялась запись FAILED
    # «карточка ещё не нарисована» — хотя mp4 лежит рядом и едет в сборку.
    if src.startswith("card"):
        return False
    return not _has_image(images_dir, scene["id"])


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    scenes_path, out_dir = sys.argv[1], sys.argv[2]
    per = TARGET_PER_SHARD
    cap = MAX_SHARDS
    images_dir = ""
    overlays_dir = ""
    if "--images-dir" in sys.argv:
        images_dir = sys.argv[sys.argv.index("--images-dir") + 1]
    if "--overlays-dir" in sys.argv:
        overlays_dir = sys.argv[sys.argv.index("--overlays-dir") + 1]
    if "--target-per-shard" in sys.argv:
        per = int(sys.argv[sys.argv.index("--target-per-shard") + 1])
    if "--max-shards" in sys.argv:
        cap = int(sys.argv[sys.argv.index("--max-shards") + 1])
    if not overlays_dir and images_dir:
        overlays_dir = os.path.join(os.path.dirname(images_dir.rstrip("/")), "overlays")

    data = json.load(open(scenes_path, encoding="utf-8"))
    meta = {x: data[x] for x in data if x != "scenes"}
    todo = [s for s in data["scenes"] if needs_web_fetch(s, images_dir)]

    # fold pop-up photo searches into the same shards (own IP per runner)
    n_ov = 0
    ovf = os.path.join(os.path.dirname(os.path.abspath(scenes_path)),
                       "overlays_fetch.scenes.json")
    if os.path.isfile(ovf):
        try:
            ov = json.load(open(ovf, encoding="utf-8")).get("scenes", [])
        except Exception:
            ov = []
        for s in ov:
            if overlays_dir and glob.glob(
                    os.path.join(overlays_dir, f"scene_{s['id']:03d}.*")):
                continue
            todo.append({**s, "_dest": "overlays"})
            n_ov += 1

    if not todo:
        sys.stderr.write("[shard] нет веб-сцен для облака — всё из библиотеки/уже есть\n")
        print("[]")
        return

    k = max(1, min(cap, math.ceil(len(todo) / per)))
    parts = partition(todo, k)

    os.makedirs(out_dir, exist_ok=True)
    idx = []
    for i, part in enumerate(parts):
        sp = os.path.join(out_dir, f"shard{i}.scenes.json")
        json.dump({**meta, "scenes": part}, open(sp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        idx.append(i)

    total = len(data["scenes"])
    sys.stderr.write(
        f"[shard] {len(todo) - n_ov} веб-сцен + {n_ov} всплывашек -> {len(idx)} шардов "
        f"({', '.join(str(len(p)) for p in parts)}); "
        f"{total - (len(todo) - n_ov)} сцен уже с кадром/из библиотеки\n")
    print(json.dumps(idx))


if __name__ == "__main__":
    main()
