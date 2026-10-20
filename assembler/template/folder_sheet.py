#!/usr/bin/env python3
"""Contact sheet of a media-library folder, every file labelled with its
filename, so scenes can be assigned exact files instead of round-robin.
Usage: python3 folder_sheet.py "ПОЛИТИКА/VenesuelA" [out_prefix]
"""
import glob, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

def _media_library_dir():
    """Медиатека канала из .env, а не зашитая библиотека-1 (2026-10-19).
    Та же правка, что сделана в check_lead.py 03.10: на каналах, сидящих на
    media-library-2 (5 МИНУТ / ДИПЛОМАТИЯ СИЛЫ / ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО),
    этот скрипт смотрел в ЧУЖУЮ медиатеку и тихо находил ноль файлов —
    молча, без единой ошибки в выводе. Нормализуем и форму
    `MEDIA_LIBRARY_DIR=media-library-2` (имя папки без пути), она описана в
    рабочих заметках и встречается в живых .env."""
    val = os.environ.get("MEDIA_LIBRARY_DIR")
    if not val:
        # .env ищем не только в текущей папке, но и выше по дереву: скрипт
        # часто зовут из подпапки проекта, и тогда он молча брал библиотеку-1
        d = os.path.abspath(".")
        for _ in range(4):
            cand = os.path.join(d, ".env")
            if os.path.exists(cand):
                with open(cand, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("MEDIA_LIBRARY_DIR="):
                            val = line.split("=", 1)[1].strip()
                            break
                if val:
                    break
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    if not val:
        return os.path.expanduser("~/projects/media-library")
    val = os.path.expanduser(val)
    if not os.path.isabs(val):
        val = os.path.expanduser(os.path.join("~/projects", val))
    return val

LIB = _media_library_dir()
print("медиатека:", LIB, "" if os.path.isdir(LIB) else "— ПАПКИ НЕТ", flush=True)
tag = sys.argv[1]
prefix = sys.argv[2] if len(sys.argv) > 2 else "fs_" + os.path.basename(tag)
outdir = "folder_sheets"
os.makedirs(outdir, exist_ok=True)

TW, TH, COLS, PER, BAR = 300, 210, 6, 30, 26
try:
    F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
except OSError:
    F = ImageFont.load_default()

d = os.path.join(LIB, tag)
exts = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")
files = sorted(f for f in os.listdir(d) if f.lower().endswith(exts))
print(f"{tag}: {len(files)} files")

tiles = []
for fn in files:
    p = os.path.join(d, fn)
    img = Image.new("RGB", (TW, TH), (25, 25, 28))
    frame = p
    if p.lower().endswith((".mp4", ".mov")):
        frame = os.path.join(outdir, "_f.jpg")
        subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", p, "-vframes", "1",
                        "-vf", f"scale={TW}:{TH-BAR}:force_original_aspect_ratio=increase,crop={TW}:{TH-BAR}",
                        frame], capture_output=True)
    try:
        ph = Image.open(frame).convert("RGB")
        ph.thumbnail((TW, TH - BAR))
        img.paste(ph, ((TW - ph.width) // 2, (TH - BAR - ph.height) // 2))
    except OSError:
        pass
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, TH - BAR, TW, TH], fill=(0, 0, 0))
    dr.text((4, TH - BAR + 4), fn[:40], font=F, fill=(255, 220, 130))
    tiles.append(img)

for pi in range((len(tiles) + PER - 1) // PER):
    chunk = tiles[pi * PER:(pi + 1) * PER]
    rows = (len(chunk) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * TW, rows * TH), (10, 10, 10))
    for i, t in enumerate(chunk):
        sheet.paste(t, ((i % COLS) * TW, (i // COLS) * TH))
    outp = os.path.join(outdir, f"{prefix}_{pi+1}.jpg")
    sheet.save(outp, quality=80)
    print(outp)

f = os.path.join(outdir, "_f.jpg")
if os.path.exists(f):
    os.remove(f)
