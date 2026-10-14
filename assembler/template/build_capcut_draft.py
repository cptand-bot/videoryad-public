#!/usr/bin/env python3
"""Emit an editable per-scene CapCut project from a finished scenes.json +
fetched assets — the alternative to `assemble_final.py`'s flat MP4.

This does NOT touch the ffmpeg сборщик. Run both: the MP4 is the safe
fallback, the CapCut draft is what the user opens to tweak each scene by
hand (transitions, Ken Burns, pop-ups) and then exports himself.

  python3 build_capcut_draft.py <scenes.json> <images-dir> <draft-name> [--fps 30]

What it does:
  1. clones a known-good CapCut draft folder as the skeleton (keeps all of
     CapCut International's boilerplate: canvas_config 1920x1080, color
     space, config blocks, new_version 185…);
  2. copies every scene asset into <draft>/Resources/ and references it by
     an absolute D:\\ path (same convention as the user's own projects);
  3. lays one segment per scene on a single video track, each segment's
     target_timerange = that scene's duration from scenes.json (so the
     whole thing already matches the narration length);
  4. writes draft_content.json + patches draft_meta_info.json + adds the
     root_meta_info.json entry so CapCut lists it on the home screen.

CapCut draft root on this machine:
  D:\\CapCut\\Projects\\CapCut Drafts\\   (see project_capcut_moved_to_d memory)
"""
import json
import os
import shutil
import subprocess
import sys
import uuid

DRAFT_ROOT_WIN = "D:/CapCut/Projects/CapCut Drafts"
DRAFT_ROOT = "/mnt/d/CapCut/Projects/CapCut Drafts"
# Skeleton donor: a real project that imported N PLAIN FILE clips onto one
# track (extra_type_option 0, not a "combination" compound clip). Its segment
# and video-material objects are cloned as prototypes so every regenerated
# clip carries CapCut's full ~68-field / ~50-field shape. If this folder is
# gone, point TEMPLATE at any project whose videos[0].type == "video" with a
# real file path.
TEMPLATE = "ЖИВОТНЫЕ ру - объекты"
NEW_VERSION = "185.0.0"                  # CapCut International 9.4.x draft version
CONTENT_VERSION = 360000
VID_EXT = (".mp4", ".mov", ".webm", ".mkv")
PHOTO_SENTINEL = 10_800_000_000          # CapCut's "still image" source duration


def uid():
    return str(uuid.uuid4()).upper()


def probe(path):
    """(width, height, duration_us) — duration 0 for stills."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
        st = j.get("streams", [{}])[0]
        w, h = int(st.get("width", 1920)), int(st.get("height", 1080))
        dur = float(j.get("format", {}).get("duration", 0) or 0)
        return w, h, int(dur * 1_000_000)
    except (ValueError, KeyError, IndexError):
        return 1920, 1080, 0


def per_segment_materials(mats):
    """Create the 7 boiler-plate per-segment material objects, append them to
    the right arrays, return their ids in extra_material_refs order."""
    spec = [
        ("speeds", {"type": "speed", "mode": 0, "speed": 1.0, "curve_speed": None}),
        ("placeholder_infos", {"type": "placeholder_info", "meta_type": "none",
                               "res_path": "", "res_text": "", "error_path": "", "error_text": ""}),
        ("canvases", {"type": "canvas_color", "color": "", "blur": 0.0, "image": "",
                      "album_image": "", "image_id": "", "image_name": "",
                      "source_platform": 0, "team_id": ""}),
        ("sound_channel_mappings", {"type": "none", "audio_channel_mapping": 0,
                                    "is_config_open": False}),
        ("material_animations", {"type": "sticker_animation", "animations": [],
                                 "multi_language_current": "none"}),
        ("material_colors", {"is_color_clip": False, "is_gradient": False, "solid_color": "",
                             "gradient_colors": [], "gradient_percents": [],
                             "gradient_angle": 90.0, "width": 0.0, "height": 0.0}),
        ("vocal_separations", {"type": "vocal_separation", "choice": 0, "removed_sounds": [],
                               "time_range": None, "production_path": "", "final_algorithm": "",
                               "enter_from": ""}),
    ]
    refs = []
    for arr, obj in spec:
        obj = dict(obj, id=uid())
        mats.setdefault(arr, []).append(obj)
        refs.append(obj["id"])
    return refs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fps = 30.0
    if "--fps" in sys.argv:
        fps = float(sys.argv[sys.argv.index("--fps") + 1])
    if len(args) < 3:
        print("usage: build_capcut_draft.py <scenes.json> <images-dir> <draft-name> [--fps 30]")
        sys.exit(1)
    scenes_path, images_dir, name = args[0], args[1], args[2]
    scenes = json.load(open(scenes_path, encoding="utf-8"))["scenes"]

    src_dir = os.path.join(DRAFT_ROOT, TEMPLATE)
    dst_dir = os.path.join(DRAFT_ROOT, name)
    if not os.path.isdir(src_dir):
        print(f"template folder missing: {src_dir}"); sys.exit(1)
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir)
    # copy ONLY the skeleton — never the template's Resources/materials/caches
    # (those run to >1 GB and DrvFs copy would take forever). draft_content.json
    # is rewritten below; the rest are per-draft config CapCut expects to exist.
    SKELETON = ["draft_meta_info.json", "draft_settings", "draft.extra",
                "draft_biz_config.json", "draft_agency_config.json", "key_value.json",
                "crypto_key_store.dat", "crypto_key_store.dat.bak", "attachment_editing.json",
                "attachment_pc_common.json", "draft_virtual_store.json", "template-2.tmp",
                "performance_opt_info.json", "timeline_layout.json"]
    for fn in SKELETON:
        sp = os.path.join(src_dir, fn)
        if os.path.isfile(sp):
            shutil.copy(sp, os.path.join(dst_dir, fn))
    for d in ("common_attachment", "adjust_mask", "matting", "smart_crop", "qr_upload",
              "Timelines", "materials", "subdraft", "loudness", "video", "video_effect"):
        os.makedirs(os.path.join(dst_dir, d), exist_ok=True)
    res_dir = os.path.join(dst_dir, "Resources")
    os.makedirs(res_dir, exist_ok=True)

    D = json.load(open(os.path.join(src_dir, "draft_content.json"), encoding="utf-8"))
    D["id"] = uid()
    D["fps"] = fps
    D["name"] = name
    D["new_version"] = NEW_VERSION
    D["version"] = CONTENT_VERSION
    D["canvas_config"] = {"ratio": "original", "width": 1920, "height": 1080, "background": None}
    mats = D["materials"]

    # --- pull REAL prototype objects from the template's first clip so every
    # regenerated segment / material carries CapCut's full field set. Building
    # these from scratch drops ~50 fields and CapCut's strict loader then
    # silently refuses the whole draft (it never appears on the home screen).
    def clone(o):
        return json.loads(json.dumps(o))

    seg_proto = D["tracks"][0]["segments"][0]
    vid_proto = mats["videos"][0]
    by_id = {}
    for arr, items in mats.items():
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and it.get("id"):
                    by_id[it["id"]] = (arr, it)
    # per-segment material prototypes, keyed by their array, in ref order —
    # skip the "drafts" (combination) ref: a plain clip is not a compound clip
    ref_protos = []           # list of (array_name, proto_obj)
    for r in seg_proto["extra_material_refs"]:
        arr, obj = by_id.get(r, (None, None))
        if arr and arr != "drafts":
            ref_protos.append((arr, obj))

    # wipe the arrays we regenerate; keep every other global block intact
    for k in ("videos", "transitions", "drafts", "audios",
              *{a for a, _ in ref_protos}):
        mats[k] = []

    segments = []
    t = 0
    for s in scenes:
        sid = s["id"]
        hits = [f for f in os.listdir(images_dir)
                if f.startswith(f"scene_{sid:03d}.") and not f.endswith(".json")]
        if not hits:
            print(f"  scene {sid}: no asset, skipped"); continue
        asset = os.path.join(images_dir, hits[0])
        ext = os.path.splitext(hits[0])[1].lower()
        is_vid = ext in VID_EXT
        shutil.copy(asset, os.path.join(res_dir, hits[0]))
        win_path = f"{DRAFT_ROOT_WIN}/{name}/Resources/{hits[0]}"
        w, h, adur = probe(asset)
        dur_us = int(round(s["duration_sec"] * 1_000_000))

        mat = clone(vid_proto)
        mat.update({
            "id": uid(), "type": "video" if is_vid else "photo",
            "path": win_path, "material_name": f"сцена {sid:02d}",
            "width": w, "height": h,
            "duration": adur if is_vid else PHOTO_SENTINEL,
            "has_audio": is_vid,
        })
        mats["videos"].append(mat)

        refs = []
        for arr, proto in ref_protos:
            obj = clone(proto)
            obj["id"] = uid()
            if arr == "speeds":
                obj["speed"] = 1.0
                obj["curve_speed"] = None
            mats[arr].append(obj)
            refs.append(obj["id"])

        seg = clone(seg_proto)
        src_dur = dur_us if not is_vid else min(dur_us, adur or dur_us)
        seg.update({
            "id": uid(), "material_id": mat["id"],
            "source_timerange": {"start": 0, "duration": src_dur},
            "target_timerange": {"start": t, "duration": dur_us},
            "speed": 1.0, "extra_material_refs": refs,
            "clip": {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0,
                     "transform": {"x": 0.0, "y": 0.0},
                     "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0},
            "uniform_scale": {"on": True, "value": 1.0},
            "keyframe_refs": [], "common_keyframes": [], "group_id": "",
        })
        seg.setdefault("hdr_vivid_settings", None)   # present in 185, absent in older donors
        segments.append(seg)
        t += dur_us

    D["duration"] = t
    trk = clone(D["tracks"][0])
    trk.update({"id": uid(), "segments": segments})
    D["tracks"] = [trk]

    for fn in ("draft_content.json", "draft_content.json.bak"):
        json.dump(D, open(os.path.join(dst_dir, fn), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    # cover thumbnail (CapCut's home-screen card) — first scene's frame
    cover = os.path.join(dst_dir, "draft_cover.jpg")
    first = next((os.path.join(images_dir, f) for f in sorted(os.listdir(images_dir))
                  if f.startswith("scene_001.") and not f.endswith(".json")), None)
    if first:
        subprocess.run(["ffmpeg", "-y", "-i", first, "-frames:v", "1", "-vf",
                        "scale=720:-2", cover], capture_output=True)

    # patch draft_meta_info.json (cloned from template)
    mip = os.path.join(dst_dir, "draft_meta_info.json")
    try:
        mi = json.load(open(mip, encoding="utf-8"))
    except (OSError, ValueError):
        mi = {}
    did = uid()
    mi.update({
        "draft_id": did, "draft_name": name,
        "draft_fold_path": f"{DRAFT_ROOT_WIN}/{name}",
        "draft_root_path": DRAFT_ROOT_WIN,
        "draft_cover": f"{DRAFT_ROOT_WIN}/{name}/draft_cover.jpg",
        "tm_duration": t,
    })
    json.dump(mi, open(mip, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # register in root_meta_info.json so CapCut's home screen lists it.
    # CapCut's parser needs the FULL ~53-field entry shape — a minimal entry is
    # silently ignored. So clone an existing entry and override only identity.
    import time
    now_us = int(time.time() * 1_000_000)
    rp = os.path.join(DRAFT_ROOT, "root_meta_info.json")
    root = json.load(open(rp, encoding="utf-8"))
    store = root.setdefault("all_draft_store", [])
    store[:] = [e for e in store if e.get("draft_name") != name]
    proto = next((e for e in store if e.get("draft_name")), None)
    entry = json.loads(json.dumps(proto)) if proto else {}
    entry.update({
        "draft_id": did, "draft_name": name,
        "draft_fold_path": f"{DRAFT_ROOT_WIN}/{name}",
        "draft_root_path": DRAFT_ROOT_WIN,
        "draft_json_file": f"{DRAFT_ROOT_WIN}/{name}\\draft_content.json",
        "draft_cover": f"{DRAFT_ROOT_WIN}/{name}\\draft_cover.jpg",
        "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_duration": t, "tm_draft_removed": 0,
        "draft_materials": [], "draft_materials_copied_info": [],
        "draft_segment_extra_info": [],
    })
    store.append(entry)
    root["draft_ids"] = max(root.get("draft_ids", 0), len(store) + 12)
    json.dump(root, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"\nCapCut draft written: {dst_dir}")
    print(f"  {len(segments)} segments · {t/1_000_000:.1f}s · assets in Resources/")
    print(f"  Open CapCut → it should be on the home screen as «{name}».")


if __name__ == "__main__":
    main()
