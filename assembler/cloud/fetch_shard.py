#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One matrix runner's fetch step. A shard may hold BOTH main-scene web
searches and overlay-photo searches (overlay scenes carry `"_dest": "overlays"`
— shard_scenes.py folds `overlays_fetch.scenes.json` into the same shards so
pop-up photos ride the matrix too, instead of being fetched serially on one IP
in the assemble job).

Splits the shard by `_dest` and runs the normal fetcher once per target dir:
  main scenes    -> <proj>/images/     (manifest = $MANIFEST_NAME)
  overlay scenes -> <proj>/overlays/   (manifest = <MANIFEST_NAME stem>.ov.json)

    fetch_shard.py <shard.scenes.json> <project-dir> <.env>
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "..", "template")


def _run(scenes, dest_dir, env_path, manifest_name, proj_root=None):
    if not scenes:
        return
    os.makedirs(dest_dir, exist_ok=True)
    tmp = os.path.join(dest_dir, ".shard_part.scenes.json")
    json.dump({"scenes": scenes}, open(tmp, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    env = dict(os.environ)
    if manifest_name:
        env["MANIFEST_NAME"] = manifest_name
    # Бан-лист, приехавший в очереди (ship.sh кладёт обезличенную копию):
    # без него забаненный кадр спокойно возвращается облачным фетчем —
    # ровно это случилось 2026-10-15 на planeta-territorii-1610.
    #
    # 2026-10-16: путь к проекту теперь передаётся ЯВНО, а не выводится из
    # dest_dir через dirname. Прежний вывод был верен ровно тогда, когда
    # кадры лежат на один уровень ниже проекта, и молча промахивался в любом
    # другом раскладе: ветка `if os.path.exists` ничего не печатала ни при
    # успехе, ни при промахе, а fetch_assets_news.py без переменной спокойно
    # брал локальный путь медиатеки, которого на раннере нет — load_banned_md5()
    # возвращал ПУСТОЙ набор. Снаружи это выглядит как «бан-лист доехал, все
    # проверки исправны», а бан не действует. Поймано на 5min-svergnut-1710:
    # забаненный 2026-10-08 кадр приехал со статусом "ok" (реально скачан).
    # Теперь путь однозначен, а результат ПЕЧАТАЕТСЯ — молчания больше нет.
    ban = os.path.join(proj_root, ".banned_md5.json") if proj_root else ""
    if ban and os.path.exists(ban):
        env["VIDEORYAD_BANNED_FILE"] = ban
        try:
            _n = len(json.load(open(ban, encoding="utf-8")))
        except Exception:
            _n = "?"
        print(f"[fetch_shard] бан-лист: {_n} md5 из {ban}", flush=True)
    else:
        print(f"[fetch_shard] ВНИМАНИЕ: бан-листа нет по пути {ban or '(не задан)'} "
              f"— забаненные кадры НЕ БУДУТ отсеяны", flush=True)
    subprocess.run([sys.executable, os.path.join(TPL, "fetch_assets_news.py"),
                    tmp, dest_dir, env_path], env=env, check=False)
    try:
        os.remove(tmp)
    except OSError:
        pass


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(1)
    shard_path, proj, env_path = sys.argv[1:4]
    data = json.load(open(shard_path, encoding="utf-8"))
    scenes = data.get("scenes", [])
    main_scenes = [s for s in scenes if s.get("_dest") != "overlays"]
    ov_scenes = [s for s in scenes if s.get("_dest") == "overlays"]

    mf = os.environ.get("MANIFEST_NAME", "manifest.shard.json")
    ov_mf = mf[:-5] + ".ov.json" if mf.endswith(".json") else mf + ".ov"

    _run(main_scenes, os.path.join(proj, "images"), env_path, mf, proj)
    _run(ov_scenes, os.path.join(proj, "overlays"), env_path, ov_mf, proj)
    print(f"[fetch_shard] main={len(main_scenes)} overlays={len(ov_scenes)}", flush=True)


if __name__ == "__main__":
    main()
