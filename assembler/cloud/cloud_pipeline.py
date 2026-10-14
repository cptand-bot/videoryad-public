#!/usr/bin/env python3
"""
Checkpointed, resumable, HEAVILY-LOGGED orchestrator for building a news
видеоряд on a throw-away machine (GitHub Actions runner) with NO
media-library access.

Mechanical steps only (everything that is just ffmpeg / HTTP):

  fetch -> overlays_fetch -> clips -> overlays -> concat -> stretch -> sfx -> deliver -> dashboard -> qa

The judgement step (splitting the script + deciding what each scene shows) is
done by Claude Code earlier in the same workflow — see cloud/classify_prompt.md.

Because this runs UNATTENDED, everything is logged so we can chase its
mistakes after the fact:
  <project>/_cloud/pipeline.log   — full transcript: every command + its output
  <project>/_cloud/report.json    — machine-readable per-step metrics
  <project>/_cloud/QA-report.md   — human summary of everything that might be wrong
These three are published alongside the finished video.

Every step records itself in <project>/progress.json; re-running skips
finished steps (fetch/build_clips are themselves incremental), so a killed
job resumes exactly where it stopped.

Usage:
    python3 cloud_pipeline.py <project-dir> [--only STEP] [--from STEP]
"""
import json
import os
import sys
import glob
import time
import shutil
import hashlib
import subprocess

TPL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "template"))
STEPS = ["fetch", "overlays_fetch", "clips", "overlays", "concat", "stretch", "sfx",
         "deliver", "dashboard", "qa"]

_PROJ = None          # set in main(); used by log()
_LOGF = None


def _cloud_dir(proj):
    d = os.path.join(proj, "_cloud")
    os.makedirs(d, exist_ok=True)
    return d


def log(msg=""):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    global _LOGF
    if _LOGF is None and _PROJ:
        _LOGF = open(os.path.join(_cloud_dir(_PROJ), "pipeline.log"), "a", encoding="utf-8")
        _LOGF.write(f"\n\n===== run started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    if _LOGF:
        _LOGF.write(line + "\n")
        _LOGF.flush()


def run(cmd, capture=True, **kw):
    """Run a command; tee stdout+stderr into the pipeline log."""
    log("$ " + " ".join(str(c) for c in cmd))
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True, **kw)
        out = (r.stdout or "") + (r.stderr or "")
        for ln in out.splitlines():
            log("  | " + ln)
        if r.returncode != 0:
            raise SystemExit(f"step failed (exit {r.returncode}): {' '.join(map(str, cmd))}")
        return r
    else:
        r = subprocess.run(cmd, **kw)
        if r.returncode != 0:
            raise SystemExit(f"step failed (exit {r.returncode}): {' '.join(map(str, cmd))}")
        return r


# ---------------------------------------------------------------- state

def prog_path(proj):
    return os.path.join(proj, "progress.json")


def load_prog(proj):
    p = prog_path(proj)
    if os.path.isfile(p):
        try:
            return json.load(open(p))
        except Exception:
            pass
    return {"done": [], "started_at": time.time()}


def save_prog(proj, prog):
    prog["updated_at"] = time.time()
    tmp = prog_path(proj) + ".tmp"
    json.dump(prog, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, prog_path(proj))


def load_report(proj):
    p = os.path.join(_cloud_dir(proj), "report.json")
    if os.path.isfile(p):
        try:
            return json.load(open(p))
        except Exception:
            pass
    return {"steps": {}, "flags": []}


def save_report(proj, rep):
    p = os.path.join(_cloud_dir(proj), "report.json")
    tmp = p + ".tmp"
    json.dump(rep, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ---------------------------------------------------------------- discovery

def find_scenes(proj):
    c = glob.glob(os.path.join(proj, "*.scenes.json"))
    c = [x for x in c if not x.endswith("overlays_fetch.scenes.json")]
    if not c:
        raise SystemExit("no <name>.scenes.json — classification step not done?")
    # Never trust glob order: a project dir can carry leftover scratch scene
    # files (retry*.scenes.json, r2.scenes.json …) from an audit loop. The real
    # script always has the most scenes — pick that one. Ties break on shortest
    # basename (the plain "<niche>.scenes.json", not a "retry" variant).
    def _nscenes(p):
        try:
            return len(json.load(open(p)).get("scenes", []))
        except Exception:
            return -1
    c.sort(key=lambda p: (-_nscenes(p), len(os.path.basename(p))))
    if len(c) > 1:
        log(f"multiple *.scenes.json present, picked {os.path.basename(c[0])} "
            f"({_nscenes(c[0])} scenes) over {[os.path.basename(x) for x in c[1:]]}")
    return c[0]


def find_narration(proj):
    # exclude our own pipeline outputs/intermediates (_silent.mp4, the final
    # "<stem>-ВИДЕОРЯД.mp4", the dashboard snapshot) - "_silent.mp4" sorts
    # alphabetically before a real "narration.mp4"/"<name>.mp4" (underscore <
    # letters), so once step_concat has run, an unfiltered glob picks the
    # intermediate silent render as "narration" instead of the real audio -
    # duration checks then compare the video to itself and always read 0
    # drift, masking real desync. Bit us 2026-09-12 (vybory-predskazateli).
    #
    # Returns None (not a raise) when there's no media file — that's the
    # normal case now: scenes_from_srt.py bakes the exact target length into
    # scenes.json (gap-inclusive, "last scene runs to the SRT's own last cue
    # end") so shipping the narration file at all is no longer required, see
    # narration_duration()/output_stem() below (2026-09-13, user stopped
    # sending the audio file, asked to derive timing from the SRT alone).
    for ext in ("_1080p.mp4", ".mp4", ".wav", ".m4a", ".mp3"):
        c = sorted(x for x in glob.glob(os.path.join(proj, f"*{ext}"))
                   if "ВИДЕОРЯД" not in x and "-дашборд" not in x
                   and not os.path.basename(x).startswith("_"))
        if c:
            return c[0]
    return None


def find_srt(proj):
    c = sorted(glob.glob(os.path.join(proj, "*.srt")))
    return c[0] if c else None


def scenes_total_duration(scenes_json):
    """The length the finished видеоряд must have when there's no narration
    file to probe: scenes_from_srt.py already made this exact (gap-inclusive,
    last scene's end = the SRT's own last cue end), so it's just the max
    scene end time — no ffprobe needed."""
    d = json.load(open(scenes_json, encoding="utf-8"))
    return max((s.get("start_sec", 0) + s.get("duration_sec", 0)
                for s in d.get("scenes", [])), default=0.0)


def narration_duration(proj, scenes_json):
    n = find_narration(proj)
    return _dur(n) if n else scenes_total_duration(scenes_json)


def output_stem(proj, scenes_json):
    n = find_narration(proj)
    if n:
        return os.path.splitext(os.path.basename(n))[0].replace("_1080p", "")
    srt = find_srt(proj)
    if srt:
        stem = os.path.splitext(os.path.basename(srt))[0]
        for suf in ("-caption", "_caption", ".caption"):
            if stem.endswith(suf):
                stem = stem[: -len(suf)]
                break
        return stem
    return os.path.splitext(os.path.basename(scenes_json))[0]


def scenes_classified(scenes_json):
    d = json.load(open(scenes_json))
    bad = [s["id"] for s in d["scenes"]
           if not s.get("source") or not s.get("source_query")
           or str(s.get("source_query")).startswith("TODO")]
    return (len(bad) == 0), bad


def _final_name(proj, scenes_json):
    return f"{output_stem(proj, scenes_json)}-ВИДЕОРЯД.mp4"


def _dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- steps

def step_fetch(proj, scenes_json):
    env = os.path.join(proj, ".env")
    if not os.path.isfile(env):
        open(env, "w").write("PEXELS_API_KEY=\nFLICKR_API_KEY=\n")
    run(["python3", os.path.join(TPL, "fetch_assets_news.py"),
         scenes_json, os.path.join(proj, "images"), env], cwd=proj)


def step_overlays_fetch(proj):
    """Pop-up photos normally arrive from the fetch matrix (shard_scenes.py
    folds overlays_fetch.scenes.json into the shards). This step only mops up
    the few the matrix missed — a serial one-IP fetch of the whole set is what
    used to make the dashboard slow, so never do that here."""
    ovf = os.path.join(proj, "overlays_fetch.scenes.json")
    if not os.path.isfile(ovf):
        log("no overlays_fetch.scenes.json — skipping overlay-photo fetch")
        return
    ovdir = os.path.join(proj, "overlays")
    try:
        want = json.load(open(ovf, encoding="utf-8")).get("scenes", [])
    except Exception:
        want = []
    missing = [s for s in want
               if not glob.glob(os.path.join(ovdir, f"scene_{s['id']:03d}.*"))]
    if not missing:
        log(f"overlay-фото: все {len(want)} уже с матрицы — пропускаю")
        return
    log(f"overlay-фото: матрица не добрала {len(missing)}/{len(want)} — досыпаю серийно")
    sub = os.path.join(ovdir, ".mop.scenes.json")
    os.makedirs(ovdir, exist_ok=True)
    json.dump({"scenes": missing}, open(sub, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    run(["python3", os.path.join(TPL, "fetch_assets_news.py"),
         sub, ovdir, os.path.join(proj, ".env")], cwd=proj)
    try:
        os.remove(sub)
    except OSError:
        pass


def _parallel(argv_list, label):
    procs = [(i, subprocess.Popen(a[1], cwd=a[0], env=a[2])) for i, a in enumerate(argv_list)]
    for i, p in procs:
        rc = p.wait()
        log(f"  {label} worker {i} exit {rc}")
        if rc != 0:
            raise SystemExit(f"{label} worker {i} failed")


def _img_md5(proj, sid):
    for e in (".mp4", ".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(proj, "images", f"scene_{sid:03d}{e}")
        if os.path.isfile(p):
            return hashlib.md5(open(p, "rb").read()).hexdigest()
    return None


def step_clips(proj, scenes_json):
    """Incremental. On a REBUILD (images/.built.json exists) only scenes whose
    source image changed get their clip_NNN.mp4 wiped and rebuilt, and the
    downstream steps (concat/sfx/deliver/dashboard) are re-armed so the new
    frames actually make it into the video."""
    d = json.load(open(scenes_json))
    ids = [s["id"] for s in d["scenes"]]
    built_path = os.path.join(proj, "images", ".built.json")
    built = json.load(open(built_path)) if os.path.isfile(built_path) else {}
    clips = os.path.join(proj, "clips")
    changed = []
    if built:                                  # this is a rebuild
        for sid in ids:
            cur = _img_md5(proj, sid)
            if cur and built.get(str(sid)) != cur:
                changed.append(sid)
                for suff in ("", ".orig"):
                    f = os.path.join(clips, f"clip_{sid:03d}{suff}.mp4")
                    if os.path.exists(f):
                        os.remove(f)
        log(f"rebuild: {len(changed)} сцен изменились -> переклеиваю только их: {changed}")
        if changed:
            prog = load_prog(proj)
            for st in ("concat", "sfx", "deliver", "dashboard"):
                if st in prog["done"]:
                    prog["done"].remove(st)
            save_prog(proj, prog)
    n = int(os.environ.get("CLOUD_WORKERS", "4"))
    base = ["python3", os.path.join(TPL, "build_clips_1080.py"),
            scenes_json, os.path.join(proj, "images"), clips]
    log(f"build_clips: {n} workers")
    _parallel([(proj, base, dict(os.environ, BUILD_APPROVED="1",
                                 WORKER_COUNT=str(n), WORKER_ID=str(w))) for w in range(n)],
              "build_clips")
    run(base, cwd=proj, env=dict(os.environ, BUILD_APPROVED="1", WORKER_COUNT="1", WORKER_ID="0"))
    # record what we built from, for the next rebuild's diff
    json.dump({str(sid): _img_md5(proj, sid) for sid in ids},
              open(built_path, "w"), ensure_ascii=False, indent=1)


def step_overlays(proj, scenes_json):
    ovp = os.path.join(proj, "overlays.json")
    if not os.path.isfile(ovp):
        log("no overlays.json — skipping pop-ups")
        return
    ov = json.load(open(ovp))
    clips = os.path.join(proj, "clips")
    anchor = ov.get("anchor", "bottom")
    # fingerprint each pop-up = its spec + its photo's bytes + the anchor
    def fp(k):
        spec = json.dumps(ov[k], sort_keys=True, ensure_ascii=False)
        ph = os.path.join(proj, str(ov[k].get("photo", "")))
        pm = hashlib.md5(open(ph, "rb").read()).hexdigest() if os.path.isfile(ph) else "-"
        return hashlib.md5((spec + pm + anchor).encode()).hexdigest()
    ids = [k for k in ov if str(k).isdigit()]

    # ── МАТРИЦА ВСПЛЫВАШЕК (2026-10-14) ──────────────────────────────────
    # Этап был последним, кто работал на ОДНОЙ машине по очереди: 146с на 33
    # всплывашки (публичный раннер) против 279-345с на приватных — самый
    # дорогой кусок assemble после того, как клипы разнесли на 12 воркеров.
    # Теперь его точно так же режем по машинам: OVL_SHARD_COUNT/OVL_SHARD_ID
    # приходят из workflow-матрицы, каждая машина берёт свою долю id.
    # ВАЖНО: это НЕ то же самое, что CLOUD_WORKERS — тот делит работу между
    # процессами ВНУТРИ одной машины и продолжает работать как раньше.
    shard_n = int(os.environ.get("OVL_SHARD_COUNT", "1"))
    shard_i = int(os.environ.get("OVL_SHARD_ID", "0"))
    if shard_n > 1:
        ids = [k for k in ids if int(k) % shard_n == shard_i]
        log(f"всплывашки: машина {shard_i} из {shard_n}, её доля — {len(ids)} шт")

    # Отпечатки готовых всплывашек. В режиме матрицы каждая машина пишет СВОЙ
    # файл (.overlaid.<N>.json), иначе 12 машин затёрли бы друг друга. На
    # сборке (shard_n == 1) все такие файлы сливаются в один: id, который
    # какая-то машина не осилила, просто не попадёт в слияние и будет
    # дорисован здесь — то есть падение одной машины не ломает ролик.
    prev_path = os.path.join(clips, f".overlaid.{shard_i}.json" if shard_n > 1
                             else ".overlaid.json")
    prev = json.load(open(prev_path)) if os.path.isfile(prev_path) else {}
    if shard_n == 1:
        merged = dict(prev)
        for f in sorted(glob.glob(os.path.join(clips, ".overlaid.*.json"))):
            if os.path.basename(f) == ".overlaid.json":
                continue
            try:
                merged.update(json.load(open(f)))
            except Exception as e:
                log(f"  не прочитал {os.path.basename(f)}: {e}")
        if len(merged) > len(prev):
            log(f"всплывашки: с машин матрицы пришло готовых {len(merged)} шт")
        prev = merged
    stale = []
    for k in ids:
        rebuilt_clean = not os.path.isfile(os.path.join(clips, f"clip_{int(k):03d}.orig.mp4"))
        if prev.get(k) != fp(k) or rebuilt_clean:
            stale.append(int(k))
    if not stale and prev:
        log("всплывашки: ничего не изменилось — пропускаю")
    else:
        target = stale if prev else [int(k) for k in ids]
        log(f"всплывашки: рендерю {len(target)} шт {target if prev else '(все)'}")
        # limit build_overlays to the target scenes via a temp overlays.json
        sub = {kk: ov[kk] for kk in ov if not str(kk).isdigit() or int(kk) in target}
        tmp = os.path.join(proj, ".overlays_todo.json")
        json.dump(sub, open(tmp, "w"), ensure_ascii=False)
        n = int(os.environ.get("CLOUD_WORKERS", "4"))
        base = ["python3", os.path.join(TPL, "build_overlays.py"), "overlay",
                scenes_json, os.path.join(proj, "images"), clips, tmp]
        _parallel([(proj, base, dict(os.environ, WORKER_COUNT=str(n), WORKER_ID=str(w)))
                   for w in range(n)], "build_overlays")
        os.remove(tmp)
    json.dump({k: fp(k) for k in ids}, open(prev_path, "w"), ensure_ascii=False, indent=1)


def step_concat(proj):
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", os.path.join(proj, "clips", "concat_list.txt"),
         "-c", "copy", "-fflags", "+genpts", os.path.join(proj, "_silent.mp4")], cwd=proj)


def step_stretch(proj, scenes_json):
    """Correct the concat's frame-rounding drift against the REAL target
    length (each per-scene clip's duration rounds to the nearest frame, so a
    195-clip video can end up tens of seconds short of the sum of scenes.json
    durations - see template/assemble_final.py's docstring, same fix, ported
    here since the cloud path never had it). Stays silent - stretches video
    timing only, does not mux narration audio in (default output is a silent
    track the user syncs himself in CapCut). Target length = the real
    narration file's duration when one was shipped, else scenes.json's own
    baked-in total (see narration_duration())."""
    silent = os.path.join(proj, "_silent.mp4")
    dv = _dur(silent)
    dn = narration_duration(proj, scenes_json)

    # Dead zone. Re-encoding the WHOLE video costs ~10 min on a 15-min ролик
    # (measured: 606s to correct 0.45s on planeta-8-mostov-1310, 2026-10-12)
    # and the видеоряд carries no lip-sync — the user lays his own narration
    # over it in the editor, where a sub-2s offset is invisible and trivially
    # nudged. The old 0.3s threshold made almost every SRT-derived build pay
    # that 10 minutes for a drift nobody can see. Real breakage (a dropped
    # clip) shows up as TENS of seconds, far outside this window, so widening
    # it does not hide the failure this step exists to catch.
    if dv <= 0 or abs(dv - dn) < 2.0:
        log(f"stretch: video {dv:.2f}s vs target {dn:.2f}s "
            f"(расхождение {abs(dv - dn):.2f}s) — в пределах допуска 2s, "
            f"перекодирование пропущено (экономит ~10 мин)")
        return

    factor = dn / dv
    # Loud abort instead of the silent catastrophe. If concat dropped most of
    # the clips (ffmpeg concat stops at the first missing entry and happily
    # writes a stub), the old code would time-stretch that stub to full length
    # — this is exactly how a 4-clip stub once got stretched ~21x to fill 9+
    # minutes of slow motion, with every step still reporting exit 0.
    if not (0.8 <= factor <= 1.25):
        log(f"❌ stretch: video {dv:.2f}s vs target {dn:.2f}s -> factor {factor:.3f} "
            f"выходит за разумные пределы (0.8–1.25). Это НЕ дрейф округления, "
            f"а потерянные клипы: склейка собрала огрызок. Растягивать его "
            f"запрещено — сборка остановлена.")
        raise RuntimeError(
            f"stretch factor {factor:.3f} out of sane range — concat produced "
            f"{dv:.2f}s against a {dn:.2f}s target; clips are missing")

    log(f"stretch: video {dv:.2f}s vs target {dn:.2f}s - applying setpts*{factor:.5f}")
    tmp = os.path.join(proj, "_silent_stretched.mp4")
    run(["ffmpeg", "-y", "-i", silent,
         "-vf", f"setpts=PTS*{factor}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-an", tmp], cwd=proj)
    os.replace(tmp, silent)


def step_sfx(proj, scenes_json):
    silent = os.path.join(proj, "_silent.mp4")
    final = os.path.join(proj, _final_name(proj, scenes_json))
    ov = os.path.join(proj, "overlays.json")
    if os.path.isfile(ov):
        run(["python3", os.path.join(TPL, "build_overlays.py"), "sfx",
             scenes_json, ov, os.path.join(proj, "sfx"), silent, final, "1.0"], cwd=proj)
    else:
        shutil.copy(silent, final)


def step_deliver(proj, scenes_json):
    """Hard gate. Nothing downstream re-checks the finished file, and a run's
    top-level GitHub label is NOT evidence (a cancelled helper shard or a
    failed artifact-cleanup job marks the whole run 'cancelled' while the
    video is perfectly fine). So the only trustworthy verdict is made here,
    on the actual bytes: the file exists, every scene became a clip, and the
    length matches the narration. Anything else stops the build loudly rather
    than publishing a quietly-broken видеоряд."""
    final = os.path.join(proj, _final_name(proj, scenes_json))
    if not os.path.isfile(final):
        raise SystemExit("final video not produced")

    n_scenes = len(json.load(open(scenes_json, encoding="utf-8"))["scenes"])
    n_clips = len(glob.glob(os.path.join(proj, "clips", "clip_*.mp4")))
    dv, dn = _dur(final), narration_duration(proj, scenes_json)

    log(f"final = {final}  ({os.path.getsize(final)/1e6:.1f} MB)")
    log(f"duration: video {dv:.2f}s vs target {dn:.2f}s  (diff {dv-dn:+.2f}s)")
    log(f"клипов: {n_clips} / сцен: {n_scenes}")

    problems = []
    if n_clips < n_scenes:
        problems.append(
            f"собрано {n_clips} клипов на {n_scenes} сцен — {n_scenes - n_clips} "
            f"потеряно, склейка выдала огрызок")
    if abs(dv - dn) > 3.0:
        problems.append(
            f"длительность разъехалась на {dv - dn:+.2f}s "
            f"(видео {dv:.2f}s, озвучка {dn:.2f}s)")
    if problems:
        for p in problems:
            log("❌ " + p)
        raise RuntimeError("ГОТОВЫЙ ФАЙЛ НЕ ПРИНЯТ: " + "; ".join(problems))
    log("✅ готовый файл принят: все сцены на месте, длительность сходится")


def step_dashboard(proj, scenes_json):
    prefix = os.path.splitext(os.path.basename(scenes_json))[0]
    run(["python3", os.path.join(TPL, "review.py"), scenes_json,
         os.path.join(proj, "images"),
         os.path.join(proj, f"{prefix}-дашборд.html")], cwd=proj)


# ---------------------------------------------------------------- QA report

def step_qa(proj, scenes_json):
    """Everything an unattended run might have gotten wrong — collected in one
    place so we review it when the video comes back."""
    d = json.load(open(scenes_json))
    scenes = {s["id"]: s for s in d["scenes"]}
    N = len(scenes)
    flags = []
    info = []

    # --- fetch manifest ---
    mpath = os.path.join(proj, "images", "manifest.json")
    man = json.load(open(mpath)) if os.path.isfile(mpath) else []
    by_src = {}
    failed = []
    for m in man:
        by_src[m.get("source", "?")] = by_src.get(m.get("source", "?"), 0) + 1
        if m.get("status") in ("FAILED", "placeholder"):
            failed.append(m["id"])
    npath = os.path.join(proj, "needs_upload.json")
    if os.path.isfile(npath):
        try:
            failed = sorted(set(failed) | {int(k) for k in json.load(open(npath))})
        except Exception:
            pass
    info.append(f"источники кадров: " + ", ".join(f"{k}:{v}" for k, v in sorted(by_src.items())))
    if failed:
        flags.append(f"НЕТ КАДРА ({len(failed)}): сцены {sorted(failed)} — заглушка стоит, "
                     f"нужен ручной кадр (жёлтые на дашборде)")
    # cached manifest entries record the *requested* source, so web_search hides
    # behind press_photo — count press_photo scenes with a Cyrillic query as "web-ish"
    cyr = sum(1 for s in scenes.values()
              if s.get("source") == "press_photo"
              and any("Ѐ" <= ch <= "ӿ" for ch in str(s.get("source_query", ""))))
    web = by_src.get("web_search", 0)
    if web or cyr:
        flags.append(f"~{max(web, cyr)} кадров скорее всего из веб-поиска (Яндекс/Bing) — "
                     f"НЕ CC-лицензия (агентские фото, вотермарки). ОБЯЗАТЕЛЬНО пройти "
                     f"контакт-лист глазами на дашборде — веб-поиск даёт и чужую страну, "
                     f"и реконструкторов, и обложки книг.")

    # --- tiny / broken image files ---
    tiny = []
    portraits = 0
    for f in glob.glob(os.path.join(proj, "images", "scene_*.*")):
        try:
            sz = os.path.getsize(f)
        except OSError:
            continue
        if f.lower().endswith((".jpg", ".jpeg", ".png")) and sz < 15000:
            tiny.append(os.path.basename(f))
        if f.lower().endswith((".jpg", ".jpeg", ".png")):
            try:
                from PIL import Image
                with Image.open(f) as im:
                    if im.width / im.height < 1.0:
                        portraits += 1
            except Exception:
                tiny.append(os.path.basename(f) + " (не читается)")
    if tiny:
        flags.append(f"подозрительные файлы кадров: {tiny}")
    if portraits:
        info.append(f"{portraits} вертикальных кадров → размытая подложка при сборке (норм)")

    # --- md5 dups across final assets ---
    h2f = {}
    for f in glob.glob(os.path.join(proj, "images", "scene_*.*")):
        try:
            hh = hashlib.md5(open(f, "rb").read()).hexdigest()
        except OSError:
            continue
        h2f.setdefault(hh, []).append(os.path.basename(f))
    dups = [v for v in h2f.values() if len(v) > 1]
    if dups:
        flags.append(f"ОДИН И ТОТ ЖЕ ФАЙЛ НА РАЗНЫХ СЦЕНАХ: {dups}")

    # --- video-lead ---
    try:
        r = subprocess.run(["python3", os.path.join(TPL, "check_lead.py"),
                            scenes_json, os.path.join(proj, "images")],
                           capture_output=True, text=True)
        (info if r.returncode == 0 else flags).append(
            "видео-лид: " + ("ok" if r.returncode == 0 else "НАРУШЕН") +
            " — " + r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "видео-лид проверка")
    except Exception as e:
        flags.append(f"check_lead не отработал: {e}")

    # --- overlays ---
    ovp = os.path.join(proj, "overlays.json")
    if os.path.isfile(ovp):
        ov = json.load(open(ovp))
        anchor = ov.get("anchor", "bottom")
        ids = [k for k in ov if str(k).isdigit()]
        nophoto = [k for k in ids if not os.path.exists(os.path.join(proj, str(ov[k].get("photo", ""))))]
        info.append(f"всплывашки: {len(ids)} шт, якорь={anchor} "
                    f"(ПЛАНЕТА обычно снизу, второй канал — сверху; ставит человек)")
        if nophoto:
            flags.append(f"всплывашки без фото (пропущены при сборке): сцены {nophoto}")
        rate = len(ids) / (narration_duration(proj, scenes_json) / 60.0 or 1)
        info.append(f"плотность всплывашек: {rate:.1f}/мин (цель ~3)")
    else:
        info.append("overlays.json нет — видеоряд без всплывашек")

    # --- final duration ---
    final = os.path.join(proj, _final_name(proj, scenes_json))
    if os.path.isfile(final):
        dv, dn = _dur(final), narration_duration(proj, scenes_json)
        info.append(f"длина: видео {dv:.1f}s / озвучка {dn:.1f}s")
        if abs(dv - dn) > 1.0:
            flags.append(f"ДЛИНА НЕ СХОДИТСЯ: video {dv:.1f}s vs narration {dn:.1f}s "
                         f"(разница {dv-dn:+.2f}s > 1s)")
    else:
        flags.append("финального видео нет на диске")

    # --- Claude's own classification report ---
    cr = os.path.join(_cloud_dir(proj), "classify_report.md")
    if os.path.isfile(cr):
        info.append("отчёт классификации от облачного Claude: _cloud/classify_report.md")
    else:
        info.append("облачный Claude не оставил classify_report.md (или классификация была локальной)")

    # --- steps that never ran ---
    # Не всякий непройденный шаг — беда. `overlays_fetch` штатно не
    # выполняется, когда фото всплывашек скачаны заранее (локально или
    # матрицей), и выезжать с ним в раздел «что могло пойти не так» —
    # значит приучать читателя игнорировать этот раздел целиком.
    prog = load_prog(proj)
    _BENIGN = {"overlays_fetch": "фото всплывашек уже были на месте",
               "stretch": "длительность сошлась, перекодирование не понадобилось"}
    skipped = [s for s in STEPS[:-1] if s not in prog["done"]]
    real = [s for s in skipped if s not in _BENIGN]
    benign = [s for s in skipped if s in _BENIGN]
    if real:
        flags.append(f"шаги не выполнены: {real}")
    for s in benign:
        info.append(f"шаг «{s}» пропущен штатно — {_BENIGN[s]}")

    # --- write it ---
    rep = load_report(proj)
    rep["qa"] = {"flags": flags, "info": info, "scenes": N,
                 "generated": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_report(proj, rep)

    md = [f"# QA-отчёт — {os.path.basename(proj)}",
          f"_собрано облаком {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}, {N} сцен_", ""]
    if flags:
        md.append("## ⚠️ Проверить\n")
        md += [f"- {x}" for x in flags]
    else:
        md.append("## ✅ Явных косяков не найдено\n")
    md.append("\n## Инфо\n")
    md += [f"- {x}" for x in info]
    md.append("\n---\nПолный лог: `_cloud/pipeline.log` · метрики: `_cloud/report.json`")
    open(os.path.join(_cloud_dir(proj), "QA-report.md"), "w", encoding="utf-8").write("\n".join(md))

    log("")
    log("================ QA ================")
    for x in flags:
        log("  ⚠️  " + x)
    for x in info:
        log("  ·   " + x)
    log("===================================")

    # GitHub Actions step summary
    gs = os.environ.get("GITHUB_STEP_SUMMARY")
    if gs:
        with open(gs, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")


# ---------------------------------------------------------------- main

_DISPATCH = {
    "fetch": lambda p, s: step_fetch(p, s),
    "overlays_fetch": lambda p, s: step_overlays_fetch(p),
    "clips": lambda p, s: step_clips(p, s),
    "overlays": lambda p, s: step_overlays(p, s),
    "concat": lambda p, s: step_concat(p),
    "stretch": lambda p, s: step_stretch(p, s),
    "sfx": lambda p, s: step_sfx(p, s),
    "deliver": lambda p, s: step_deliver(p, s),
    "dashboard": lambda p, s: step_dashboard(p, s),
    "qa": lambda p, s: step_qa(p, s),
}


def main():
    global _PROJ
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    proj = os.path.abspath(sys.argv[1])
    _PROJ = proj
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    frm = sys.argv[sys.argv.index("--from") + 1] if "--from" in sys.argv else None

    scenes_json = find_scenes(proj)
    ok, bad = scenes_classified(scenes_json)
    if not ok:
        raise SystemExit(f"scenes not fully classified — {len(bad)} missing source/source_query: {bad[:20]}")

    prog = load_prog(proj)
    rep = load_report(proj)
    log(f"project {proj}")
    log(f"scenes  {os.path.basename(scenes_json)}   done so far: {prog['done']}")

    todo = [only] if only else (STEPS[STEPS.index(frm):] if frm else STEPS)
    for st in todo:
        if only is None and st in prog["done"] and st != "qa":
            log(f"skip {st} (already done)")
            continue
        log(f"=== step: {st} ===")
        t0 = time.time()
        try:
            _DISPATCH[st](proj, scenes_json)
        except SystemExit:
            rep["steps"][st] = {"ok": False, "seconds": round(time.time() - t0)}
            save_report(proj, rep)
            raise
        dt = round(time.time() - t0)
        rep["steps"][st] = {"ok": True, "seconds": dt}
        save_report(proj, rep)
        if st not in prog["done"]:
            prog["done"].append(st)
        save_prog(proj, prog)
        log(f"    {st} done in {dt}s")

    log("PIPELINE COMPLETE")


if __name__ == "__main__":
    main()
