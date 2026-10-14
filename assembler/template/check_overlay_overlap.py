#!/usr/bin/env python3
"""Render each overlay scene's REAL 1920x1080 composite (base image cover-
cropped the way build_clips_1080.py frames it) with a red rectangle showing
exactly where the pop-up photo will sit (overlay_geom's own seeded math,
copied from review.py so it stays in lockstep). Tiles the results into
contact sheets under <project>/overlap_check/.

Why this exists: a pop-up's corner position is seeded per scene id and has
no idea where a face sits in the base photo — for a single person speaking
to camera (very common: podiums, interviews, press conferences) the face is
often dead-center-top or center, which is exactly where an `anchor: top`
channel's pop-ups land by default. Caught live (user, 2026-10-04, ОЛЬКА
"Алиев" build): 13 of 39 pop-ups landed squarely on the speaker's face.

Usage: python3 check_overlay_overlap.py [project_dir]
   (defaults to cwd)

Fix for a flagged scene: edit overlays.json directly, add/adjust that
scene's "style" (left/right/up-center/up-left/up-right) and/or "scale"
(0.4-2.4) to push the box into empty space, then re-run this script to
confirm before handing the dashboard over. No rebuild needed — this reads
overlays.json fresh every run.
"""
import json
import os
import random
import subprocess
import sys

W, H = 1920, 1080


def overlay_geom(sid, spec, photo_path, anchor):
    HMIN, HMAX = H // 3, H // 2
    HBY = {"s": (HMIN, HMIN + 55), "m": (HMIN + 70, HMAX - 45), "l": (HMAX - 45, HMAX)}
    PICK = ["s", "s", "m", "m", "m", "l", "l", "l"]
    rnd = random.Random(sid)
    cls = spec.get("size") or rnd.choice(PICK)
    hlo, hhi = HBY.get(cls, HBY["m"])
    bh = rnd.randint(hlo, hhi)
    ar = 1.4
    if photo_path and os.path.exists(photo_path):
        try:
            from PIL import Image
            with Image.open(photo_path) as _im:
                ar = _im.width / _im.height
        except Exception:
            pass
    if ar < 1.0:
        bh = HMAX
        cls = "l"
    bw = int(bh * ar)
    bw = max(int(bh * 0.75), min(bw, int(W * 0.62)))
    margin = rnd.randint(40, 72)
    style = spec.get("style") or "up-center"
    shape = (spec.get("shape") or "rect").lower()
    if shape not in ("rect", "rounded", "square", "circle"):
        shape = "rect"
    if shape in ("square", "circle"):
        bw = bh
    try:
        msc = float(spec.get("scale", 1.0))
    except (TypeError, ValueError):
        msc = 1.0
    msc = max(0.4, min(2.4, msc))
    bh = max(120, min(int(bh * msc), int(H * 0.92)))
    bw = max(90, min(int(bw * msc), int(W * 0.92)))
    if shape in ("square", "circle"):
        bw = bh
    dw, dh = bw + 18, bh + 18
    if shape == "circle":
        dw = dh = bh
    if "left" in style:
        x = margin
    elif "right" in style:
        x = W - dw - margin
    else:
        x = (W - dw) // 2
    y = margin if str(anchor).lower() == "top" else H - dh - margin
    return x, y, dw, dh


def base_frame(images_dir, sid):
    for ext in (".jpg", ".jpeg", ".png", ".mp4", ".mov"):
        p = os.path.join(images_dir, f"scene_{sid:03d}{ext}")
        if os.path.exists(p):
            if ext in (".mp4", ".mov"):
                out = f"/tmp/overlap_check_base_{sid:03d}.jpg"
                subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", p, "-frames:v", "1",
                                 "-update", "1", out], capture_output=True)
                return out
            return p
    return None


def cover_crop(im, w, h):
    iw, ih = im.size
    scale = max(w / iw, h / ih)
    nw, nh = int(iw * scale) + 1, int(ih * scale) + 1
    im2 = im.resize((nw, nh))
    x0 = (nw - w) // 2
    y0 = (nh - h) // 2
    return im2.crop((x0, y0, x0 + w, y0 + h))


def main():
    from PIL import Image, ImageDraw

    proj = sys.argv[1] if len(sys.argv) > 1 else "."
    ov_path = os.path.join(proj, "overlays.json")
    images_dir = os.path.join(proj, "images")
    out_dir = os.path.join(proj, "overlap_check")

    ov = json.load(open(ov_path, encoding="utf-8"))
    anchor = ov.get("anchor", "bottom")

    ids = sorted(int(k) for k in ov if k.isdigit())
    tiles = []
    for sid in ids:
        spec = ov[str(sid)]
        bp = base_frame(images_dir, sid)
        if not bp:
            continue
        base_im = Image.open(bp).convert("RGB")
        frame = cover_crop(base_im, W, H)
        x, y, dw, dh = overlay_geom(sid, spec, spec.get("photo"), anchor)
        draw = ImageDraw.Draw(frame)
        draw.rectangle([x, y, x + dw, y + dh], outline=(255, 0, 0), width=8)
        thumb = frame.resize((480, 270))
        d2 = ImageDraw.Draw(thumb)
        d2.rectangle([0, 0, 60, 24], fill=(0, 0, 0))
        d2.text((4, 4), str(sid), fill=(255, 255, 0))
        tiles.append((sid, thumb))

    os.makedirs(out_dir, exist_ok=True)
    cols = 5
    n_sheets = (len(tiles) + 19) // 20
    for s in range(n_sheets):
        chunk = tiles[s * 20:(s + 1) * 20]
        rows = (len(chunk) + cols - 1) // cols
        sh = Image.new("RGB", (480 * cols, 270 * rows), (20, 20, 20))
        for i, (sid, th) in enumerate(chunk):
            r, c = divmod(i, cols)
            sh.paste(th, (c * 480, r * 270))
        sh.save(os.path.join(out_dir, f"check_{s + 1}.jpg"), quality=85)
    print(f"tiles: {len(tiles)}  sheets: {n_sheets}  anchor: {anchor}  ->  {out_dir}/")


if __name__ == "__main__":
    main()
