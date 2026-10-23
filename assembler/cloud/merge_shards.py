#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gather / prep step in the assemble job. Runs for EVERY build.

By now the assemble job has:
  * unpacked project-src (scenes.json + the library images/ the user fetched
    locally, if any),
  * downloaded every matrix shard artifact on top (each shard's web
    scene_NNN.* + manifest.shardK.json), if there were web scenes.

This:
  * merges the per-shard manifests (0 or more) in scene order,
  * repairs md5 collisions (two runners grabbed the same web image for
    different scenes) — keep it on the lowest id, re-fetch the rest serially,
  * rebuilds images/manifest.json from what's actually on disk so QA is
    accurate whether a scene came from the library or the cloud,
  * marks `fetch` done in progress.json so cloud_pipeline.py goes to clips.

    merge_shards.py <scenes.json> <images-dir> <.env> <project-dir>
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "template"))
from fetch_parallel import merge_manifests  # noqa: E402

TPL = os.path.join(HERE, "..", "template")


def _md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def repair_web_collisions(scenes_path, images_dir, env_path, web_ids):
    """Two runners grabbed the same web image for different scenes (their dedup
    sets weren't shared). Keep it on the lowest id, drop the copies, re-fetch
    them serially. ONLY touches web scenes — library frames are never re-fetched
    in the cloud (there is no library here; a re-fetch would pull a web image)."""
    by_hash = {}
    for p in glob.glob(os.path.join(images_dir, "scene_*.*")):
        if os.path.splitext(p)[1].lower() not in (".jpg", ".jpeg", ".png", ".webp", ".mp4"):
            continue
        sid = int(os.path.basename(p).split("_")[1].split(".")[0])
        if sid not in web_ids:
            continue
        by_hash.setdefault(_md5(p), []).append((sid, p))
    victims = []
    for group in by_hash.values():
        if len(group) > 1:
            for sid, p in sorted(group)[1:]:
                os.remove(p)
                victims.append(sid)
    if not victims:
        return False
    print(f"[merge] коллизии веб-кадров у сцен {sorted(victims)} — перекачиваю серийно", flush=True)
    data = json.load(open(scenes_path, encoding="utf-8"))
    sub = {k: data[k] for k in data if k != "scenes"}
    sub["scenes"] = [s for s in data["scenes"] if s["id"] in set(victims)]
    rp = os.path.join(images_dir, ".shards", "repair.scenes.json")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    json.dump(sub, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    env = dict(os.environ)
    env["MANIFEST_NAME"] = "manifest.shardR.json"
    env.pop("FETCH_PACE_DIR", None)
    subprocess.run([sys.executable, os.path.join(TPL, "fetch_assets_news.py"),
                    rp, images_dir, env_path], env=env, check=False)
    return True


def _img_for(images_dir, sid):
    c = sorted(p for p in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*"))
               if os.path.getsize(p) > 0)
    return os.path.basename(c[0]) if c else None


def _collect_overlays(images_dir, proj):
    """Move images/overlays/scene_* (dropped there by merge-multiple) to
    <proj>/overlays/, then drop overlays.json entries with no photo."""
    src = os.path.join(images_dir, "overlays")
    dst = os.path.join(proj, "overlays")
    os.makedirs(dst, exist_ok=True)
    moved = 0
    if os.path.isdir(src):
        for p in glob.glob(os.path.join(src, "scene_*")):
            if os.path.getsize(p) > 0:
                os.replace(p, os.path.join(dst, os.path.basename(p)))
                moved += 1
    ovj = os.path.join(proj, "overlays.json")
    dropped = []
    lost = {}
    # kept_text ОБЪЯВЛЕНА ЗДЕСЬ, А НЕ ВНУТРИ `if` (23.10, блокер). Она лежала
    # внутри блока «если есть overlays.json», а используется в итоговой строке
    # отчёта снаружи — и на ролике БЕЗ всплывашек склейка падала
    # `UnboundLocalError` в самом конце, после всей проделанной работы. Раньше
    # не всплывало: у боевых роликов всплывашки есть всегда. Ролики целиком из
    # элементов арсенала их не имеют, и таких будет больше.
    kept_text = 0
    if os.path.isfile(ovj):
        try:
            ov = json.load(open(ovj, encoding="utf-8"))
        except Exception:
            ov = {}
        for k in [k for k in list(ov) if k.isdigit()]:
            e = ov.get(k) if isinstance(ov.get(k), dict) else {}
            # ТЕКСТОВАЯ ВСПЛЫВАШКА ФАЙЛА НЕ ИМЕЕТ И НЕ ДОЛЖНА ИМЕТЬ
            # (починено 2026-10-16). Прежний цикл выбрасывал ЛЮБУЮ запись, для
            # которой нет scene_NNN.* в overlays/ — то есть весь класс
            # текстовых разом. Живой случай: отправлено 26 записей (9 фото +
            # 17 текстовых), get.sh вернул 9. Для «5 МИНУТ», где текстовые
            # всплывашки обязательны, это означало ролик вообще без текста.
            if (e.get("text") or {}).get("words"):
                kept_text += 1
                continue
            if not glob.glob(os.path.join(dst, f"scene_{int(k):03d}.*")):
                lost[k] = e
                ov.pop(k)
                dropped.append(k)
        json.dump(ov, open(ovj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        # ПЛАН НЕ ТЕРЯТЬ (2026-10-17, улов на planeta-svergnut-1810): раньше
        # запись всплывашки, для которой облако не добыло фото, исчезала
        # молча — вкладка заметила потерю только пересчётом «44 из 45» и
        # восстанавливала запись руками, по памяти. Саму запись в overlays.json
        # оставить нельзя (файла нет — ship.sh/сборка ругаются на сироту),
        # поэтому выкладываем её рядом, вместе с запросом, по которому фото
        # искали: вернуть всплывашку = скопировать запись назад и перезапросить.
        if lost:
            qmap = {}
            ovs = os.path.join(proj, "overlays_fetch.scenes.json")
            if os.path.isfile(ovs):
                try:
                    for s in json.load(open(ovs, encoding="utf-8")).get("scenes", []):
                        qmap[str(s.get("id"))] = {"source": s.get("source"),
                                                 "source_query": s.get("source_query"),
                                                 "visual_prompt": s.get("visual_prompt")}
                except Exception:
                    pass
            out = {k: {"entry": v, "reason": "облако не добыло фото (FAILED)",
                       **({"fetch": qmap[k]} if k in qmap else {})}
                   for k, v in lost.items()}
            dpath = os.path.join(proj, "overlays.dropped.json")
            try:
                if os.path.isfile(dpath):
                    out = {**json.load(open(dpath, encoding="utf-8")), **out}
            except Exception:
                pass
            json.dump(out, open(dpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            for k, v in sorted(out.items(), key=lambda kv: int(kv[0])):
                q = (v.get("fetch") or {}).get("source_query", "?")
                print(f"[merge] ВСПЛЫВАШКА {k} ПОТЕРЯНА: фото не добыто, "
                      f"запрос был '{q}'. План сохранён в overlays.dropped.json "
                      f"— перезапроси и верни запись в overlays.json.", flush=True)
    print(f"[merge] всплывашки: {moved} фото с матрицы"
          + (f", сохранил текстовых: {kept_text}" if kept_text else "")
          + (f", убрал без фото: {dropped}" if dropped else ""), flush=True)


def _sweep_banned(proj, images_dir):
    """Выбросить забаненные кадры ПРЯМО В ОБЛАКЕ, сразу после матрицы.

    Зачем, хотя фетчер баны и так чтит (2026-10-17): за один день дважды
    забаненный md5 оказался в готовой папке — на ПЛАНЕТЕ (путь восстановить
    не удалось) и на 5 МИНУТ (кадр приехал из облачного забора, локальный
    фетч поймал его только кэш-проверкой: «кэш забанен — удалил, качаю
    заново»). Бан-лист в шардах был на месте — в логе 28 строк «бан-лист:
    142 md5». Значит дыра где-то между скачиванием и папкой, и искать её по
    горячим следам нечем. Поэтому ставим сито В КОНЦЕ облачной фазы: файл с
    забаненным md5 удаляется, сцена остаётся без кадра и доберётся локально.
    """
    ban_path = os.environ.get("VIDEORYAD_BANNED_FILE") or os.path.join(proj, ".banned_md5.json")
    try:
        raw = json.load(open(ban_path, encoding="utf-8"))
    except (OSError, ValueError):
        print("[merge] бан-листа нет — сито не работает", flush=True)
        return
    today = time.strftime("%Y-%m-%d")
    ban = {m for m, e in raw.items()
           if not (isinstance(e, dict) and e.get("until")) or e["until"] >= today}
    if not ban:
        return
    hit, seen = [], 0
    for d in (images_dir, os.path.join(proj, "overlays")):
        for f in sorted(glob.glob(os.path.join(d, "scene_*.*"))):
            if f.endswith((".json", ".ovthumb.jpg", ".revframe.jpg")):
                continue
            try:
                h = hashlib.md5(open(f, "rb").read()).hexdigest()
            except OSError:
                continue
            seen += 1
            if h in ban:
                try:
                    os.remove(f)
                    hit.append(os.path.basename(f))
                except OSError:
                    pass
    print(f"[merge] сито бан-листа: {seen} файлов против {len(ban)} активных банов"
          + (f" — УДАЛЕНО {len(hit)}: {hit} (сцены доберутся локально)" if hit else " — чисто"),
          flush=True)


def _placeholder(path, sid):
    """A neutral dark slug so a missing scene keeps its slot (video length
    stays right) and the dashboard shows it — needs_upload.json paints it
    yellow and the user drops a real photo in."""
    try:
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (1920, 1080), (28, 28, 32))
        d = ImageDraw.Draw(im)
        d.text((80, 500), f"СЦЕНА {sid} — НУЖЕН КАДР", fill=(150, 150, 160))
        im.save(path, quality=88)
    except Exception:
        with open(path, "wb") as f:      # 1x1 grey jpeg fallback
            f.write(bytes.fromhex(
                "ffd8ffe000104a46494600010100000100010000ffdb004300"
                "08060606070605080707070909080a0c140d0c0b0b0c191213"
                "0f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30"
                "31343434341f27393d38323c2e333432ffc0000b0801000100"
                "0101110000ffc400140001000000000000000000000000000000"
                "09ffc4001410010000000000000000000000000000000000ff"
                "da0008010100003f00d2cf20ffd9"))


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        raise SystemExit(1)
    scenes_path, images_dir, env_path, proj = sys.argv[1:5]

    data = json.load(open(scenes_path, encoding="utf-8"))
    scenes = data["scenes"]
    web_ids = {s["id"] for s in scenes if str(s.get("source")) != "local_library"}

    # pop-up photos rode the matrix in shard artifacts and merge-multiple put
    # them under images/overlays/ — lift them to <proj>/overlays/ and prune
    # overlays.json entries the matrix couldn't find (no yellow card for a
    # missing pop-up; the user re-adds on the dashboard if he wants one).
    _collect_overlays(images_dir, proj)
    _sweep_banned(proj, images_dir)

    shard_manifests = sorted(glob.glob(os.path.join(images_dir, "manifest.shard*.json")))
    print(f"[merge] {len(shard_manifests)} shard-манифестов, "
          f"{len(glob.glob(os.path.join(images_dir, 'scene_*.*')))} файлов кадров", flush=True)

    if shard_manifests:
        merge_manifests(images_dir, scenes)
        if repair_web_collisions(scenes_path, images_dir, env_path, web_ids):
            merge_manifests(images_dir, scenes)

    # per-id source hint from whatever shard rows we have
    hint = {}
    mp = os.path.join(images_dir, "manifest.json")
    if os.path.isfile(mp):
        try:
            for r in json.load(open(mp, encoding="utf-8")):
                hint[r["id"]] = r.get("source")
        except Exception:
            pass
    rp = os.path.join(images_dir, "manifest.shardR.json")   # repaired rows win
    if os.path.isfile(rp):
        for r in json.load(open(rp, encoding="utf-8")):
            hint[r["id"]] = r.get("source")

    # rebuild the manifest from disk reality; slug + flag the ones with no image
    rows, failed = [], []
    needs = {}
    for s in scenes:
        sid = s["id"]
        f = _img_for(images_dir, sid)
        if f:
            rows.append({"id": sid, "file": f,
                         "source": hint.get(sid, s.get("source", "?")),
                         "status": "ok"})
        else:
            ph = os.path.join(images_dir, f"scene_{sid:03d}.jpg")
            _placeholder(ph, sid)
            rows.append({"id": sid, "file": os.path.basename(ph),
                         "source": "needs_upload", "status": "placeholder"})
            needs[str(sid)] = s.get("source_query", "нужен кадр")
            failed.append(sid)
    json.dump(rows, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    if needs:                             # dashboard paints these yellow
        np = os.path.join(proj, "needs_upload.json")
        cur = {}
        if os.path.isfile(np):
            try:
                cur = json.load(open(np, encoding="utf-8"))
            except Exception:
                cur = {}
        cur.update(needs)
        json.dump(cur, open(np, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"[merge] итог: {len(scenes) - len(failed)}/{len(scenes)} кадров; "
          f"{len(failed)} сцен без кадра -> заглушка + needs_upload: {failed}", flush=True)

    # tell cloud_pipeline.py the fetch step is already done
    pp = os.path.join(proj, "progress.json")
    prog = {"done": [], "started_at": time.time()}
    if os.path.isfile(pp):
        try:
            prog = json.load(open(pp))
        except Exception:
            pass
    if "fetch" not in prog.get("done", []):
        prog.setdefault("done", []).append("fetch")
    prog["updated_at"] = time.time()
    tmp = pp + ".tmp"
    json.dump(prog, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, pp)


if __name__ == "__main__":
    main()
