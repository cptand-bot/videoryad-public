#!/usr/bin/env python3
"""Labelled contact sheet for the pre-build audit (SKILL.md 2c).
Each tile = one scene, with scene id + source + query burned in so grid
position can't be miscounted. Videos -> mid frame via ffmpeg.
Usage: python3 contact_sheet.py [scenes.json] [images_dir] [out_dir]
"""
import glob, json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

import glob as _g
scenes_path = sys.argv[1] if len(sys.argv) > 1 else (sorted(_g.glob("*.scenes.json")) or ["scenes.json"])[0]
images_dir = sys.argv[2] if len(sys.argv) > 2 else "images"
out_dir = sys.argv[3] if len(sys.argv) > 3 else "thumbs"
os.makedirs(out_dir, exist_ok=True)

TW, TH, COLS, PER = 300, 205, 5, 20   # 2026-10-12: было 380x260 — ужато на 21% по стороне (-38% площади, -38% токенов на лист). Номер сцены и явный брак читаются так же; мелкие детали всё равно смотрят в полном файле.
BAR = 40
try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    FONT_S = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
except OSError:
    FONT = FONT_S = ImageFont.load_default()

scenes = json.load(open(scenes_path, encoding="utf-8"))["scenes"]
# МАНИФЕСТА МОЖЕТ НЕ БЫТЬ — ЭТО НЕ ПОВОД ПАДАТЬ (2026-10-23, улов
# `usuario-21`; гоча была известна и не чинилась). У `overlays/` манифеста не
# бывает вовсе, и лист по всплывашкам приходилось строить, синтезируя манифест
# руками. Лист — это картинки с подписями, он прекрасно строится по файлам на
# диске; манифест лишь добавляет к подписи источник и статус.
_mpath = os.path.join(images_dir, "manifest.json")
try:
    manifest = {m["id"]: m for m in json.load(open(_mpath, encoding="utf-8"))}
except (OSError, ValueError, KeyError, TypeError):
    manifest = {}
    print("  (манифеста нет — лист строю по файлам на диске, без источника и "
          "статуса в подписи)", flush=True)

tiles = []
for s in scenes:
    sid = s["id"]
    hits = sorted(glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*")))
    m = manifest.get(sid, {})
    src = m.get("source", s["source"])
    status = m.get("status", "?")
    label = f"{sid:02d} [{src}] {status}"
    sub = s["source_query"][:52]

    img = Image.new("RGB", (TW, TH), (30, 30, 34))
    if hits:
        p = hits[0]
        frame = p
        if p.lower().endswith((".mp4", ".mov")):
            frame = os.path.join(out_dir, f"_f{sid:03d}.jpg")
            subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", p, "-vframes", "1",
                            "-vf", f"scale={TW}:{TH-BAR}:force_original_aspect_ratio=increase,crop={TW}:{TH-BAR}",
                            frame], capture_output=True)
        try:
            ph = Image.open(frame).convert("RGB")
            ph.thumbnail((TW, TH - BAR))
            img.paste(ph, ((TW - ph.width) // 2, (TH - BAR - ph.height) // 2))
        except OSError:
            pass
    else:
        ImageDraw.Draw(img).text((10, 100), "NO ASSET", font=FONT, fill=(255, 90, 90))

    d = ImageDraw.Draw(img)
    d.rectangle([0, TH - BAR, TW, TH], fill=(0, 0, 0))
    col = (120, 200, 255) if src == "local_library" else (255, 210, 120)
    d.text((6, TH - BAR + 2), label, font=FONT, fill=col)
    d.text((6, TH - BAR + 21), sub, font=FONT_S, fill=(200, 200, 200))
    tiles.append(img)

for pi in range((len(tiles) + PER - 1) // PER):
    chunk = tiles[pi * PER:(pi + 1) * PER]
    rows = (len(chunk) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * TW, rows * TH), (10, 10, 10))
    for i, t in enumerate(chunk):
        sheet.paste(t, ((i % COLS) * TW, (i // COLS) * TH))
    outp = os.path.join(out_dir, f"sheet_{pi+1}.jpg")
    sheet.save(outp, quality=82)
    print(outp)

for f in glob.glob(os.path.join(out_dir, "_f*.jpg")):
    os.remove(f)
