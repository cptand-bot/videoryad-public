#!/usr/bin/env python3
"""
Grab a single clean frame from a specific YouTube video at a specific
timestamp - for pulling a real frame out of an official press conference/
briefing livestream or its VOD (Kremlin, White House, EU Council, TASS,
RIA Novosti, a parliament's own channel, etc.) when no still photo exists
yet on Wikimedia/Openverse/Archive/Flickr.

DELIBERATELY MANUAL, not part of fetch_assets_news.py's automatic
waterfall - this needs a human (or Claude, reading the actual video
description/channel) to confirm the video is really the official
source/channel it claims to be, and to pick a moment that actually shows
what the scene needs. Blindly searching YouTube and grabbing the first
result's frame would risk pulling from an unofficial reupload, a
completely unrelated video, or a frame with someone else's captions/logo
burned in by the uploader - exactly the kind of thing this skill exists to
avoid. Only use this once you already know the specific video URL you want.

Usage:
  python3 grab_stream_frame.py <youtube-url> <timestamp> <out.jpg> [ffmpeg-bin]

  <timestamp> - seconds, or mm:ss, or hh:mm:ss

Requires yt-dlp on PATH (already used by the youtube-transcript skill on
this machine).

STATUS (2026-08-23): NOT CURRENTLY WORKING on this machine. YouTube
requires a PoToken for actual video/audio data downloads (unlike caption
text, which the youtube-transcript skill gets fine without one via the
android_vr client) - yt-dlp here has no PoToken provider configured, so
video downloads fail with HTTP 403 regardless of format/client tried.
Fixing this needs a real PoToken provider plugin (e.g.
bgutil-ytdlp-pot-provider, which runs its own small Node server) - a
separate, heavier setup task, not a quick fix. Don't rely on this script
until that's actually set up and verified.
"""
import subprocess
import sys
import tempfile
import os
import glob


def to_seconds(ts):
    parts = [float(p) for p in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def main():
    if len(sys.argv) < 4:
        print("usage: grab_stream_frame.py <youtube-url> <timestamp> <out.jpg> [ffmpeg-bin]")
        sys.exit(1)
    url, timestamp, out_path = sys.argv[1:4]
    ffmpeg = sys.argv[4] if len(sys.argv) > 4 else "ffmpeg"

    # Feeding ffmpeg a direct googlevideo.com URL segfaults with this
    # machine's static ffmpeg build (network/HTTPS input handling issue in
    # that particular build) - download a short local segment via yt-dlp
    # instead (robust, purpose-built downloader) and grab the frame from
    # the local file, sidestepping ffmpeg's network input code entirely.
    t = to_seconds(timestamp)
    start = max(0, t - 1)
    section = f"*{start}-{t + 2}"

    with tempfile.TemporaryDirectory() as tmpdir:
        out_tmpl = os.path.join(tmpdir, "clip.%(ext)s")
        res = subprocess.run(
            [
                "yt-dlp", "-f", "best[height<=1080]",
                "--download-sections", section,
                "-o", out_tmpl, url,
            ],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            print("yt-dlp failed to download the segment:", res.stderr[-800:])
            sys.exit(1)

        clips = glob.glob(os.path.join(tmpdir, "clip.*"))
        if not clips:
            print("yt-dlp reported success but no output file was found")
            sys.exit(1)
        local_clip = clips[0]

        # 1s into the downloaded segment corresponds to the target timestamp
        # (the segment starts 1s before it, clamped to 0 near the video start)
        offset = str(min(1.0, t))
        cmd = [ffmpeg, "-y", "-ss", offset, "-i", local_clip, "-vframes", "1", "-q:v", "2", "-update", "1", out_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print("ffmpeg failed to grab the frame:", res.stderr[-500:])
            sys.exit(1)
    print(f"Saved frame at {timestamp} -> {out_path}")


if __name__ == "__main__":
    main()
