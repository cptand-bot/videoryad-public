#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЭФФЕКТ ПЛАНЕТЫ №3: врезка в рамке + круги-радар + ПЛАВНЫЙ зум кадра.

    python3 fx_inset.py <кадр сцены> <видео-врезка> <куда.mp4> --seconds 12
           [--channel ПЛАНЕТА] [--zoom 0.10] [--inset-at 0.7]
           [--rings-xy 960,70] [--inset-xy 120,600]

Принят пользователем 03.11 («шикарно, этот оставляем так, как есть»).
Три правила, которые он назвал тогда же и которые НЕ обсуждаются:
  * эффект применяется ТОЛЬКО на канале ПЛАНЕТА;
  * НЕ БОЛЬШЕ ТРЁХ раз на ролик;
  * глитча (сдвига цветовых каналов) в нём нет — он его отверг: «эффект
    глича — это не то, не к картинке должны применяться».

ПОЧЕМУ ЗУМ СЧИТАЕТСЯ ПОКАДРОВО, А НЕ ФИЛЬТРОМ `zoompan` (замер 03.11):
`zoompan` двигает кадр ЦЕЛЫМИ пикселями, и на медленном наезде это видно как
дёрганье — пользователь поймал его сразу. Померено по соседним кадрам:
у `zoompan` разброс движения 0,13×…3,75× от среднего (рывки), у покадрового
кропа с ДРОБНЫМИ координатами — 0,88×…1,10× (ровный ход). Разгон и
торможение — smootherstep, поэтому начало и конец без толчка.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def smooth_zoom_frames(src_img, out_dir, w, h, frames, zoom, headroom=1.12):
    from PIL import Image
    src = Image.open(src_img).convert("RGB")
    k = max(w / src.width, h / src.height) * headroom
    base = src.resize((int(src.width * k), int(src.height * k)), Image.LANCZOS)
    bw, bh = base.size
    os.makedirs(out_dir, exist_ok=True)
    for i in range(frames):
        p = i / max(1, frames - 1)
        e = p * p * p * (p * (p * 6 - 15) + 10)          # smootherstep
        z = 1.0 + zoom * e
        cw, ch = w / z, h / z
        m = (cw / w, 0, (bw - cw) / 2.0, 0, ch / h, (bh - ch) / 2.0)
        base.transform((w, h), Image.AFFINE, m, Image.BICUBIC).save(
            os.path.join(out_dir, "z_%04d.jpg" % i), quality=95)
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("inset")
    ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--channel", default="ПЛАНЕТА")
    ap.add_argument("--zoom", type=float, default=0.10)
    ap.add_argument("--inset-at", type=float, default=0.7, dest="inset_at")
    ap.add_argument("--inset-xy", default="120,600")
    ap.add_argument("--rings-xy", default="960,70")
    ap.add_argument("--rings-size", type=int, default=880)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--captions", default="", help="готовый .ass — ляжет ПОВЕРХ всего")
    a = ap.parse_args()

    if a.channel.strip().upper().replace("Ё", "Е") != "ПЛАНЕТА":
        print("!! ЭФФЕКТ ТОЛЬКО ДЛЯ КАНАЛА ПЛАНЕТА (его слово 03.11). "
              "Канал «%s» — не ставлю." % a.channel, file=sys.stderr)
        return 2
    for f in (a.scene, a.inset):
        if not os.path.isfile(f):
            sys.exit("нет файла: %s" % f)

    tmp = tempfile.mkdtemp(prefix="fx3_")
    try:
        frames = int(a.seconds * a.fps)
        rings = os.path.join(tmp, "rings")
        sys.path.insert(0, HERE)
        import fx_rings
        fx_rings.render(rings, size=a.rings_size, frames=180)
        zdir = os.path.join(tmp, "zoom")
        if a.scene.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
            base_in = ["-stream_loop", "-1", "-i", a.scene]
            base_chain = ("[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                          "crop=1920:1080,fps=%d,setsar=1[base];" % a.fps)
        else:
            smooth_zoom_frames(a.scene, zdir, 1920, 1080, frames, a.zoom)
            base_in = ["-framerate", str(a.fps), "-i", os.path.join(zdir, "z_%04d.jpg")]
            base_chain = "[0:v]setsar=1[base];"
        ix, iy = a.inset_xy.split(",")
        rx, ry = a.rings_xy.split(",")
        t_in = a.inset_at
        fc = (base_chain +
              "[2:v]scale=%d:%d,format=rgba,colorchannelmixer=aa=0.8[ring];"
              "[base][ring]overlay=x=%s:y=%s:shortest=0[withring];"
              "[1:v]scale=620:349,setsar=1,pad=iw+8:ih+8:4:4:white,"
              "pad=iw+6:ih+6:3:3:0x141414[pip];"
              "[withring][pip]overlay=x='if(lt(t,%.2f),-700+((t-%.2f)/1.0)*820,%s)':"
              "y=%s:enable='gt(t,%.2f)'[v0]"
              % (a.rings_size, a.rings_size, rx, ry,
                 t_in + 1.0, t_in, ix, iy, t_in))
        last = "[v0]"
        if a.captions and os.path.isfile(a.captions):
            fc += ";[v0]ass='%s'[v]" % a.captions.replace("\\", "/").replace(":", r"\:")
            last = "[v]"
        cmd = (["ffmpeg", "-y", "-hide_banner"] + base_in +
               ["-stream_loop", "-1", "-i", a.inset,
                "-framerate", str(a.fps), "-stream_loop", "-1",
                "-i", os.path.join(rings, "r_%03d.png"),
                "-filter_complex", fc, "-map", last, "-an",
                "-t", "%.3f" % a.seconds,
                "-c:v", "libx264", "-preset", "veryfast",
                "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
                "-pix_fmt", "yuv420p", a.out])
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.isfile(a.out)
        print(("готово: " + a.out) if ok else ("FAIL\n" + r.stderr[-700:]))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
