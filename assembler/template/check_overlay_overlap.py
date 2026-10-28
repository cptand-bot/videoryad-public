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

BADGE_H = 22          # поле под плиткой для номера сцены (2026-10-19)
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



# --- ТЕКСТОВЫЕ ВСПЛЫВАШКИ: ГЕОМЕТРИЯ ИЗ `build_overlays` (2026-10-18) ---
# До этого схема их НЕ МОДЕЛИРОВАЛА ВООБЩЕ и для текстовой записи рисовала
# рамку по геометрии ФОТО-всплывашки. При преобладании текста схема не молчит,
# а ЛЖЁТ: на ролике с 33 текстовыми из 39 проверяющий выдал 12 вердиктов о
# перекрытии лиц, которые физически не могли быть верными. Вкладка написала
# разовый рендер, им и вскрыла правду — встраиваем, чтобы не писать заново.
# Числа повторяют `_apply_text_overlay`: th = H/6 * scale (клампы 60 и H/2),
# tw = th * пропорция PNG (клампы W*0.92), поле 60, сетка 9 позиций,
# и `force_original_aspect_ratio=decrease` — то есть картинка ВПИСЫВАЕТСЯ в
# tw x th с сохранением пропорций, реальный размер меньше.
def text_geom(sid, spec, tmp_dir):
    ts = spec.get("text") or {}
    words = str(ts.get("words") or "").strip()
    if not words:
        return None
    try:
        from build_overlays import _render_text_png
    except Exception:
        return None
    png = os.path.join(tmp_dir, "ovl_%03d.png" % sid)
    try:
        if not _render_text_png(words, ts.get("color", "white"), png,
                                ts.get("font", "default")):
            return None
        from PIL import Image as _I
        with _I.open(png) as _im:
            pw, ph = _im.size
    except Exception:
        return None
    try:
        msc = max(0.4, min(2.4, float(ts.get("scale", 1.0))))
    except (TypeError, ValueError):
        msc = 1.0
    pos = str(ts.get("pos", "bc")).lower()
    yk = pos[0] if pos[:1] in ("t", "m", "b") else "b"
    xk = pos[1] if len(pos) > 1 and pos[1] in "lcr" else "c"
    th = max(60, min(int(H / 6 * msc), int(H * 0.5)))
    tw = min(int(th * (pw / ph if ph else 6)), int(W * 0.92))
    k = min(tw / pw, th / ph) if pw and ph else 1.0
    rw, rh = max(1, int(pw * k)), max(1, int(ph * k))
    mg = 60
    x = mg if xk == "l" else (W - rw) // 2 if xk == "c" else W - rw - mg
    y = mg if yk == "t" else (H - rh) // 2 if yk == "m" else H - rh - mg
    return x, y, rw, rh, png


def main():
    from PIL import Image, ImageDraw

    proj = sys.argv[1] if len(sys.argv) > 1 else "."
    # ПРИНИМАЕМ И ПАПКУ, И `scenes.json` (28.10, улов вкладки «Круговая
    # оборона»: споткнулась подряд на обоих — соседние инструменты берут
    # scenes.json, а эти ждали ПАПКУ и падали `NotADirectoryError`).
    if proj and not os.path.isdir(proj):
        if proj.endswith(".json"):
            proj = os.path.dirname(os.path.abspath(proj)) or "."
        else:
            print("ОШИБКА: %r — не папка и не scenes.json" % proj, file=sys.stderr)
            sys.exit(2)

    ov_path = os.path.join(proj, "overlays.json")
    images_dir = os.path.join(proj, "images")
    out_dir = os.path.join(proj, "overlap_check")

    import tempfile
    _tmp = tempfile.mkdtemp(prefix="ovlchk_")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
        draw = ImageDraw.Draw(frame)
        # ФОТО-всплывашка — красная рамка, как было
        if spec.get("photo"):
            x, y, dw, dh = overlay_geom(sid, spec, spec.get("photo"), anchor)
            draw.rectangle([x, y, x + dw, y + dh], outline=(255, 0, 0), width=8)
        # ТЕКСТОВАЯ — кладём НАСТОЯЩИЙ отрендеренный текст, а не рамку:
        # проверяющий должен видеть ровно то, что ляжет на кадр
        tg = text_geom(sid, spec, _tmp)
        if tg:
            tx, ty, tw_, th_, tpng = tg
            try:
                with Image.open(tpng) as _t:
                    _t = _t.convert("RGBA").resize((tw_, th_))
                    frame.paste(_t, (tx, ty), _t)
            except Exception:
                pass
            draw.rectangle([tx, ty, tx + tw_, ty + th_], outline=(0, 220, 255), width=5)
        if not spec.get("photo") and not tg:
            continue
        # НОМЕР СЦЕНЫ — ПОД КАДРОМ, А НЕ ПОВЕРХ НЕГО (2026-10-19).
        # Чёрная плашка в левом верхнем углу налезала на начало надписи, и та
        # читалась как обрезанная: два субагента независимо начали аудит с этой
        # ложной тревоги и потратили по кропу на её опровержение. Подпись
        # вынесена в поле высотой BADGE_H под плиткой — кадр больше ничем не
        # закрыт, а номер по-прежнему виден.
        _img = frame.resize((480, 270))
        thumb = Image.new("RGB", (480, 270 + BADGE_H), (0, 0, 0))
        thumb.paste(_img, (0, 0))
        d2 = ImageDraw.Draw(thumb)
        d2.text((4, 270 + 4), str(sid), fill=(255, 255, 0))
        tiles.append((sid, thumb))

    os.makedirs(out_dir, exist_ok=True)
    cols = 5
    n_sheets = (len(tiles) + 19) // 20
    for s in range(n_sheets):
        chunk = tiles[s * 20:(s + 1) * 20]
        rows = (len(chunk) + cols - 1) // cols
        sh = Image.new("RGB", (480 * cols, (270 + BADGE_H) * rows), (20, 20, 20))
        for i, (sid, th) in enumerate(chunk):
            r, c = divmod(i, cols)
            sh.paste(th, (c * 480, r * (270 + BADGE_H)))
        sh.save(os.path.join(out_dir, f"check_{s + 1}.jpg"), quality=85)
    import shutil as _sh
    _sh.rmtree(_tmp, ignore_errors=True)
    print(f"tiles: {len(tiles)}  sheets: {n_sheets}  anchor: {anchor}  ->  {out_dir}/")
    print("  красная рамка = фото-всплывашка, голубая = ТЕКСТОВАЯ "
          "(показан настоящий рендер, не схема)")


if __name__ == "__main__":
    main()
