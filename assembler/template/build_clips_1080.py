#!/usr/bin/env python3
"""
Turns each scene's still image (Ken Burns pan/zoom) or video footage (trimmed/
looped to duration) into a per-scene clip, then writes a concat list ready for
ffmpeg's concat demuxer.

Usage:
  python3 build_clips.py <scenes.json> <images-dir> <clips-dir> [ffmpeg-bin]
"""
import json
import os
import sys
import subprocess
import random

W, H, FPS = 1920, 1080, 30


def find_source(images_dir, sid):
    for ext in ("mp4", "mov", "png", "jpg", "jpeg", "webp"):
        p = os.path.join(images_dir, f"scene_{sid:03d}.{ext}")
        if os.path.exists(p):
            return p, ext
    return None, None


def _img_wh(ffprobe, src):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", src],
                       capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split("x")[:2]
        return int(w), int(h)
    except Exception:
        return W, H


def build_image_clip(ffmpeg, src, out_path, duration, ffprobe="ffprobe"):
    frames = int(duration * FPS)
    w, h = _img_wh(ffprobe, src)
    portrait = (w / h) < 1.15  # portrait / square / 4:3 -> would lose too much to a 16:9 centre-crop

    if portrait:
        # blurred-fill: whole image visible (fit by the frame), sides filled
        # with a darkened, blurred, zoomed copy of the same image. Gentle push
        # on the composite so no edge is ever revealed. Faces never get cut.
        z = ("min(zoom+0.00035,1.08)" if random.random() < 0.5
             else "if(eq(on,0),1.08,max(zoom-0.00035,1.0))")
        vf = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=24:2,eq=brightness=-0.12:saturation=0.65[bgb];"
            f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[base];"
            f"[base]zoompan=z='{z}':d={frames}:s={W}x{H}:fps={FPS},format=yuv420p"
        )
    else:
        zoom_dir = random.choice(["in", "out"])
        zexpr = ("min(zoom+0.0006,1.18)" if zoom_dir == "in"
                 else "if(eq(on,0),1.18,max(zoom-0.0006,1.0))")
        vf = (
            f"scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,"
            f"zoompan=z='{zexpr}':d={frames}:s={W}x{H}:fps={FPS},format=yuv420p"
        )

    cmd = [ffmpeg, "-y", "-loop", "1", "-i", src,
           ("-vf" if not portrait else "-filter_complex"), vf, "-t", str(duration),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", out_path]
    subprocess.run(cmd, check=True, capture_output=True)


def _pick_start(src, sid, src_dur, duration):
    """Interior offset so we never always grab the first N seconds of a source
    clip. Deterministic: same source in the same project -> same offset (stable
    rebuilds); the same source used in a *different* project (video) lands on a
    different offset because the seed folds in the working dir. Short sources
    (no room to move) start at 0."""
    slack = src_dur - duration
    if slack <= 1.0:
        return 0.0
    lo, hi = 0.4, max(0.4, slack - 0.4)
    if hi <= lo:
        return 0.0
    rnd = random.Random(f"{os.path.basename(src)}|{os.path.basename(os.getcwd())}|{sid}")
    return round(rnd.uniform(lo, hi), 2)


def build_video_clip(ffmpeg, ffprobe, src, out_path, duration):
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
        capture_output=True, text=True,
    )
    src_dur = float(probe.stdout.strip() or 0)
    start = _pick_start(src, os.path.basename(out_path), src_dur, duration) if src_dur else 0.0
    # fps=FPS is essential here, not cosmetic: stock video footage keeps its
    # source frame rate (often 25fps) unless forced, while image-based clips
    # are always FPS (zoompan's fps= param) - concatenating a mix of frame
    # rates makes ffmpeg's concat re-encode silently adopt one rate for all
    # clips, stretching/compressing whichever ones don't match (a real bug
    # hit once: 14 stock-video clips at 25fps + 68 generated clips at 30fps
    # concatenated into a video ffprobe reported as 25fps throughout, playing
    # ~20% longer than the sum of the source clips' own durations).
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p"
    loop_args = ["-stream_loop", "-1"] if (src_dur and src_dur < duration) else []
    seek_args = ["-ss", str(start)] if start > 0 else []
    cmd = [ffmpeg, "-y", *loop_args, *seek_args, "-i", src, "-vf", vf, "-t", str(duration),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an", out_path]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    if len(sys.argv) < 4:
        print("usage: build_clips.py <scenes.json> <images-dir> <clips-dir> [ffmpeg-bin]")
        sys.exit(1)
    scenes_path, images_dir, clips_dir = sys.argv[1:4]
    ffmpeg = sys.argv[4] if len(sys.argv) > 4 else "ffmpeg"
    ffprobe = "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1))
    os.makedirs(clips_dir, exist_ok=True)

    with open(scenes_path, encoding="utf-8") as f:
        data = json.load(f)

    _wc = int(os.environ.get("WORKER_COUNT", "1"))
    _wk = int(os.environ.get("WORKER_ID", "0"))
    concat_lines = []
    for scene in data["scenes"]:
        sid, duration = scene["id"], scene["duration_sec"]
        out_path = os.path.join(clips_dir, f"clip_{sid:03d}.mp4")
        if _wc > 1 and (sid % _wc) != _wk:
            continue
        if not os.path.exists(out_path):
            src, ext = find_source(images_dir, sid)
            if not src:
                print(f"[{sid:03d}] MISSING SOURCE, skip")
                continue
            print(f"[{sid:03d}] {'video' if ext=='mp4' else 'image'} -> {duration}s")
            try:
                if ext == "mp4":
                    build_video_clip(ffmpeg, ffprobe, src, out_path, duration)
                else:
                    build_image_clip(ffmpeg, src, out_path, duration, ffprobe)
            except subprocess.CalledProcessError as e:
                print(f"  FAILED: {e.stderr.decode()[-500:]}")
                continue
        # absolute path - ffmpeg's concat demuxer resolves relative entries
        # against the list file's own directory, not the caller's cwd, so a
        # relative out_path here silently breaks unless clips_dir happens to
        # be "." relative to wherever concat is later invoked from.
        concat_lines.append(f"file '{os.path.abspath(out_path)}'")

    concat_file = os.path.join(clips_dir, "concat_list.txt")
    with open(concat_file, "w") as f:
        f.write("\n".join(concat_lines))
    print(f"\n{len(concat_lines)} clips ready. Concat with:")
    print(f"  ffmpeg -f concat -safe 0 -i {concat_file} -c copy <output>.mp4")


if __name__ == "__main__":
    main()
