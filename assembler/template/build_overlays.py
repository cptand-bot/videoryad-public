"""Corner slide-in photo pop-ups + baked SFX for a видеоряд (news OR esoteric).

Reads overlays.json: {"<scene_id>": {"photo": "<path>", "sound": "<name>", "at": <sec>}}
  - photo: image to pop up (relative to project dir or absolute)
  - sound: base name of a file in <sfx-dir> (e.g. "whoosh" -> whoosh.mp3/.wav)
  - at:    seconds into that scene's clip when the pop-up starts sliding in

RULE: only scenes whose main clip is VIDEO get a pop-up (news + esoteric) (photo-on-photo looks
flat). A scene id pointing at an image asset is skipped with a warning.

Two stages:
  overlay  — re-render each listed clip with the corner slide-in. Keeps the
             original as clip_NNN.orig.mp4 so a re-run is idempotent.
  sfx      — after the final video is assembled+stretched, bake one audio
             track: silence for the whole runtime + each sound placed at its
             final timeline position (scene-start + at, times the stretch
             factor). Muxes with -c:v copy.

Usage:
  python3 build_overlays.py overlay <scenes.json> <images-dir> <clips-dir> <overlays.json>
  python3 build_overlays.py sfx <scenes.json> <overlays.json> <sfx-dir> <in.mp4> <out.mp4> [stretch-factor]
"""
import json, os, sys, subprocess, glob, random, shutil

_VID_EXT = (".mp4", ".mov", ".webm", ".mkv")

W, H, FPS = 1920, 1080, 30
SLIDE = 0.33               # slide-in / slide-out seconds
LEAD = 0.4                 # всплывашка появляется через долю секунды после старта сцены
TAIL = 0.4                 # и уезжает за долю секунды до конца сцены
# всплывашка держится ПОЧТИ ВСЮ сцену (user 2026-09-06: «а то кадр пошёл,
# всплывашка всплыла и тут же пропала»). Раньше HOLD=1.6с фикс — мелькала.
BORDER = 6                 # white frame px
# pop-ups vary in size and entry per scene (seeded on scene id, so a rebuild
# is identical). Size box: width 360-580, height 300-520 — the ≤520 cap keeps
# it under half the frame HEIGHT (user, 2026-09-02). Entry styles: slide in
# from the left edge, from the right edge, or rise up from the bottom-centre.
# distinct size classes so pop-ups read as clearly small / medium / large
# (a plain uniform range clusters visually). width box; height is capped at
# 540 = half the frame regardless of class.
# overlay box is HEIGHT-driven and clamped to [1/3, 1/2] of the frame height
# (user, 2026-09-02: "не меньше 1/3 высоты", earlier: "не больше половины").
_H_MIN, _H_MAX = H // 3, H // 2                    # 360 .. 540
_H_BY_CLASS = {"s": (_H_MIN, _H_MIN + 55),         # 360-415  (still >= 1/3)
               "m": (_H_MIN + 70, _H_MAX - 45),    # 430-495
               "l": (_H_MAX - 45, _H_MAX)}         # 495-540
_SIZE_PICK = ["s", "s", "m", "m", "m", "l", "l", "l"]
_STYLES = ["right", "right", "left", "left", "up-center", "up-right", "up-left"]

# --- текстовая всплывашка (kind-independent, живёт в spec["text"]) -------
_TXT_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    os.path.expanduser("~/.local/share/fonts/DejaVuSans-Bold.ttf"),
]
_TXT_RGB = {"white": (255, 255, 255), "yellow": (255, 232, 0), "red": (255, 34, 28)}


def _render_text_png(words, color, out_path):
    """Слово капсом, жирный, чёрная обводка, прозрачный фон."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    txt = " ".join(str(words or "").split()).upper()
    if not txt:
        return False
    fill = _TXT_RGB.get(str(color).lower(), _TXT_RGB["white"]) + (255,)
    fs = 220
    font = None
    for fp in _TXT_FONTS:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, fs); break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()
    sw = max(4, int(fs * 0.11))
    bb = ImageDraw.Draw(Image.new("RGBA", (8, 8))).textbbox((0, 0), txt, font=font, stroke_width=sw)
    pad = sw + 14
    w, h = bb[2] - bb[0] + pad * 2, bb[3] - bb[1] + pad * 2
    img = Image.new("RGBA", (max(w, 8), max(h, 8)), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad - bb[0], pad - bb[1]), txt, font=font, fill=fill,
                             stroke_width=sw, stroke_fill=(0, 0, 0, 255))
    try:
        img.save(out_path); return True
    except OSError:
        return False


def _apply_text_overlay(ffmpeg, ffprobe, base_mp4, out_mp4, ts, dur):
    """Отдельная всплывашка-СЛОВО поверх клипа: сетка 9 позиций
    (pos = tl/tc/tr/ml/mc/mr/bl/bc/br), плавное появление/исчезновение,
    без рамки. `base_mp4` уже может нести фото-всплывашку — текст идёт сверху."""
    words = ts.get("words") or ts.get("text") or ""
    if not str(words).strip():
        return False
    try:
        msc = max(0.4, min(2.4, float(ts.get("scale", 1.0))))
    except (TypeError, ValueError):
        msc = 1.0
    at = float(ts.get("at", LEAD))
    at = max(0.0, min(at, max(0.0, dur - 2 * SLIDE - 0.6)))
    hold = max(0.5, dur - at - 2 * SLIDE - TAIL)
    t0, t2, t3 = at, at + SLIDE + hold, at + 2 * SLIDE + hold
    pos = str(ts.get("pos", "bc")).lower()
    yk = pos[0] if pos[:1] in ("t", "m", "b") else "b"
    xk = pos[1] if len(pos) > 1 and pos[1] in "lcr" else "c"
    png = out_mp4 + ".txt.png"
    if not _render_text_png(words, ts.get("color", "white"), png):
        return False
    pw, ph = _img_wh(ffprobe, png)
    th = max(60, min(int(H / 6 * msc), int(H * 0.5)))
    tw = min(int(th * (pw / ph if ph else 6)), int(W * 0.92))
    mg = 60
    rx = {"l": f"{mg}", "c": "(W-w)/2", "r": f"W-w-{mg}"}[xk]
    ry = {"t": f"{mg}", "m": "(H-h)/2", "b": f"H-h-{mg}"}[yk]
    fc = (
        f"[1:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,format=rgba,"
        f"fade=t=in:st={t0:.3f}:d={SLIDE}:alpha=1,"
        f"fade=t=out:st={t2:.3f}:d={SLIDE}:alpha=1[t];"
        f"[0:v][t]overlay=x='{rx}':y='{ry}':enable='between(t,{t0:.3f},{t3:.3f})':"
        f"eval=init,format=yuv420p[v]"
    )
    tmp = out_mp4 + ".ttmp.mp4"
    cmd = [ffmpeg, "-y", "-i", base_mp4, "-loop", "1", "-i", png,
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-t", f"{dur:.3f}", tmp]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        os.remove(png)
    except OSError:
        pass
    if r.returncode == 0 and os.path.exists(tmp):
        os.replace(tmp, out_mp4)
        return True
    if os.path.exists(tmp):
        os.remove(tmp)
    print("   text FAIL:", r.stderr[-300:])
    return False


def _src(images_dir, sid):
    for e in ("mp4", "png", "jpg"):
        p = os.path.join(images_dir, f"scene_{sid:03d}.{e}")
        if os.path.exists(p):
            return p, e
    return None, None


def _img_wh(ffprobe, path):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
                       capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 1200, 800


def do_overlay(scenes_path, images_dir, clips_dir, ov_path, ffmpeg="ffmpeg"):
    ffprobe = "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1))
    ov = json.load(open(ov_path, encoding="utf-8"))
    # vertical anchor: "top" for non-Планета channels (user, 2026-09-05),
    # "bottom" (default) for Планета. Whole-file key, sibling to the scene ids.
    anchor = str(ov.get("anchor", "bottom")).lower()   # общий на ролик, его перебивает ключ сцены
    wc = int(os.environ.get("WORKER_COUNT", "1"))
    wk = int(os.environ.get("WORKER_ID", "0"))
    for sid_s, spec in ov.items():
        if not str(sid_s).isdigit():            # skip "anchor" / meta keys
            continue
        sid = int(sid_s)
        if wc > 1 and (sid % wc) != wk:
            continue
        # ВЕРТИКАЛЬ ПОСЦЕННО (2026-10-17, просьба пользователя «я бы мог её
        # менять… вверху в центре»): запись сцены может задать свой anchor,
        # дашборд пишет его кнопкой «по вертикали». Нет ключа — общий на ролик.
        sc_anchor = str(spec.get("anchor") or anchor).lower()
        if sc_anchor not in ("top", "bottom"):
            sc_anchor = anchor
        clip = os.path.join(clips_dir, f"clip_{sid:03d}.mp4")
        orig = os.path.join(clips_dir, f"clip_{sid:03d}.orig.mp4")
        photo = spec.get("photo") or ""
        photo_ok = bool(photo) and os.path.exists(photo)
        # a popup must be a STILL photo — a local_library overlay pick can
        # land on a video file (the folder mixes both). Feeding `-loop 1`
        # into a video stream below doesn't make it a still and can break
        # the overlay ffmpeg call outright (2026-09-14: silently orphaned
        # clip_005.mp4 — see the restore-on-failure fix a few lines down for
        # the other half of this incident). Grab one frame instead.
        if photo_ok and photo.lower().endswith(_VID_EXT):
            frame_path = os.path.join(clips_dir, f".ov_frame_{sid:03d}.jpg")
            fr = subprocess.run([ffmpeg, "-y", "-ss", "1", "-i", photo, "-frames:v", "1",
                                 frame_path], capture_output=True)
            if fr.returncode == 0 and os.path.exists(frame_path):
                photo = frame_path
            else:
                photo_ok = False
        tspec = spec.get("text") if isinstance(spec.get("text"), dict) else None
        if tspec and not str(tspec.get("words") or tspec.get("text") or "").strip():
            tspec = None
        # НЕЗАВИСИМЫЕ всплывашки: фото и/или СЛОВО. Хотя бы одна нужна.
        if not photo_ok and not tspec:
            print(f"[{sid:03d}] пропуск — ни фото, ни текста")
            continue
        if not os.path.exists(clip) and not os.path.exists(orig):
            print(f"[{sid:03d}] нет {clip}, пропуск")
            continue
        if not os.path.exists(orig):
            os.rename(clip, orig)
        _dur = float(subprocess.run(["ffprobe".join(ffmpeg.rsplit("ffmpeg", 1)),"-v","error",
                     "-show_entries","format=duration","-of","csv=p=0",orig],
                     capture_output=True,text=True).stdout.strip() or 6)
        _text_target = clip + ".p.mp4" if tspec else clip   # куда пишет фото-пасс
        if not photo_ok:
            # только текст — база = чистый orig
            if _apply_text_overlay(ffmpeg, "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1)),
                                   orig, clip, tspec, _dur):
                print(f"[{sid:03d}] ТЕКСТ «{tspec.get('words') or tspec.get('text')}» "
                      f"@ {tspec.get('at', LEAD)}s pos={tspec.get('pos','bc')} -> ok", flush=True)
            else:
                print(f"[{sid:03d}] ТЕКСТ -> FAIL", flush=True)
            continue
        # «секунда» с дашборда = когда всплывашка НАЧИНАЕТ въезжать (по умолчанию
        # LEAD — сразу после старта сцены). Держится до конца сцены минус TAIL.
        at = float(spec.get("at", LEAD))
        at = max(0.0, min(at, max(0.0, _dur - 2*SLIDE - 0.6)))
        hold = max(0.5, _dur - at - 2*SLIDE - TAIL)
        t0, t1, t2, t3 = at, at + SLIDE, at + SLIDE + hold, at + 2 * SLIDE + hold

        rnd = random.Random(sid)               # deterministic per scene
        cls = spec.get("size") or rnd.choice(_SIZE_PICK)
        hlo, hhi = _H_BY_CLASS[cls]
        bh = rnd.randint(hlo, hhi)              # 360..540 -> 1/3..1/2 of frame
        pw, ph = _img_wh(ffprobe, photo)        # box hugs the photo's aspect
        ar = (pw / ph) if ph else 1.4
        if ar < 1.0:                            # вертикальное фото -> всегда в половину кадра по высоте
            bh = _H_MAX
            cls = "l"
        bw = int(bh * ar)
        bw = max(int(bh * 0.75), min(bw, int(W * 0.62)))
        margin = rnd.randint(40, 72)
        style = spec.get("style") or "up-center"
        shape = (spec.get("shape") or "rect").lower()
        if shape not in ("rect", "rounded", "square", "circle"):
            shape = "rect"
        if shape in ("square", "circle"):
            bw = bh                            # квадрат / круг: коробка квадратная
        # ручной масштаб с дашборда (множитель поверх seeded-размера)
        try:
            msc = float(spec.get("scale", 1.0))
        except (TypeError, ValueError):
            msc = 1.0
        msc = max(0.4, min(2.4, msc))
        bh = int(bh * msc)
        bw = int(bw * msc)
        bh = max(120, min(bh, int(H * 0.92)))
        bw = max(90, min(bw, int(W * 0.92)))
        if shape in ("square", "circle"):
            bw = bh

        # resting position by style
        if "left" in style:
            rest_x = f"{margin}"
        elif "right" in style:
            rest_x = f"W-w-{margin}"
        else:                                  # up-center
            rest_x = "(W-w)/2"
        rest_y = f"{margin}" if sc_anchor == "top" else f"H-h-{margin}"

        def _ramp(a, b, ta):                   # linear a->b over SLIDE starting at ta
            return f"({a})+(({b})-({a}))*((t-{ta})/{SLIDE})"

        if style == "left":
            off = "-w-8"
            xexpr = (f"if(lt(t,{t0}),{off},if(lt(t,{t1}),{_ramp(off, rest_x, t0)},"
                     f"if(lt(t,{t2}),{rest_x},if(lt(t,{t3}),{_ramp(rest_x, off, t2)},{off}))))")
            yexpr = rest_y
        elif style == "right":
            off = "W+8"
            xexpr = (f"if(lt(t,{t0}),{off},if(lt(t,{t1}),{_ramp(off, rest_x, t0)},"
                     f"if(lt(t,{t2}),{rest_x},if(lt(t,{t3}),{_ramp(rest_x, off, t2)},{off}))))")
            yexpr = rest_y
        else:                                  # up-center / up-right / up-left: slide vertically
            off = "-h-8" if sc_anchor == "top" else "H+8"   # from above (top anchor) or below
            xexpr = rest_x
            yexpr = (f"if(lt(t,{t0}),{off},if(lt(t,{t1}),{_ramp(off, rest_y, t0)},"
                     f"if(lt(t,{t2}),{rest_y},if(lt(t,{t3}),{_ramp(rest_y, off, t2)},{off}))))")

        if shape == "circle":
            d = bh
            cx, cy = d / 2.0, d / 2.0
            r_out = d / 2.0 - 1
            r_in = d / 2.0 - BORDER - 3
            fc = (
                f"color=white:s={d}x{d}:r={FPS},format=rgba,"
                f"geq=r=255:g=255:b=255:a='if(lte(hypot(X-{cx},Y-{cy}),{r_out}),255,0)'[ring];"
                f"[1:v]scale={d}:{d}:force_original_aspect_ratio=increase,crop={d}:{d},"
                f"format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='if(lte(hypot(X-{cx},Y-{cy}),{r_in}),255,0)'[pic];"
                f"[ring][pic]overlay=0:0,format=rgba[ov];"
                f"[0:v][ov]overlay=x='{xexpr}':y='{yexpr}':eval=frame,format=yuv420p[v]"
            )
        elif shape == "rounded":
            rad = max(14, int(min(bw, bh) * 0.13))
            fc = (
                f"[1:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease,"
                f"pad=iw+{2*BORDER}:ih+{2*BORDER}:{BORDER}:{BORDER}:white,"
                f"pad=iw+6:ih+6:3:3:0x141414,format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='if(lte(hypot(max(max({rad}-X,X-(W-{rad})),0),max(max({rad}-Y,Y-(H-{rad})),0)),{rad}),255,0)'[ov];"
                f"[0:v][ov]overlay=x='{xexpr}':y='{yexpr}':eval=frame,format=yuv420p[v]"
            )
        else:                                  # rect / square
            fc = (
                f"[1:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease,"
                f"pad=iw+{2*BORDER}:ih+{2*BORDER}:{BORDER}:{BORDER}:white,"
                f"pad=iw+6:ih+6:3:3:0x141414,"
                f"format=rgba,colorchannelmixer=aa=1.0[ov];"
                f"[0:v][ov]overlay=x='{xexpr}':y='{yexpr}':eval=frame,format=yuv420p[v]"
            )
        print(f"[{sid:03d}]  {cls}-size {bw}x{bh}  стиль={style} форма={shape} масштаб={msc}", flush=True)
        cmd = [ffmpeg, "-y", "-i", orig, "-loop", "1", "-i", photo,
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-t", f"{_dur:.3f}", _text_target]
        r = subprocess.run(cmd, capture_output=True, text=True)
        ph_ok = os.path.exists(_text_target) and r.returncode == 0
        print(f"[{sid:03d}] всплывашка @ {at}s ({os.path.basename(photo)}) -> "
              + ("ok" if ph_ok else "FAIL\n" + r.stderr[-400:]))
        # --- вторая, независимая всплывашка: СЛОВО (spec["text"]) ---------
        if tspec:
            base = _text_target if ph_ok else orig
            if _apply_text_overlay(ffmpeg, "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1)),
                                   base, clip, tspec, _dur):
                print(f"[{sid:03d}] + ТЕКСТ «{tspec.get('words') or tspec.get('text')}» "
                      f"@ {tspec.get('at', LEAD)}s pos={tspec.get('pos','bc')} -> ok", flush=True)
            elif ph_ok:
                os.replace(_text_target, clip)     # текст упал — оставляем фото
            if _text_target != clip and os.path.exists(_text_target):
                try:
                    os.remove(_text_target)
                except OSError:
                    pass
        # SAFETY NET (user, 2026-09-14, furious — a photo-overlay ffmpeg
        # failure orphaned clip_005.mp4 forever: `os.rename(clip, orig)`
        # above already removed the original, every write-to-`clip` path
        # above is conditional on success, and NOTHING restored it on
        # failure -> concat's `-c copy` demuxer hit "Impossible to open
        # clip_005.mp4", ffmpeg silently produced a 4-clip stub, and the
        # "stretch" step then time-stretched those 4 clips ~21x to fill the
        # full narration length with no error surfaced anywhere in the
        # pipeline. However this scene's overlay attempt(s) went, `clip`
        # must exist afterward — worst case, no popup at all beats a
        # missing scene that silently wrecks the whole видеоряд.
        if not os.path.exists(clip):
            shutil.copyfile(orig, clip)
            print(f"[{sid:03d}] всплывашка не встала — вернул клип без неё "
                  f"(см. FAIL выше)", flush=True)


def do_sfx(scenes_path, ov_path, sfx_dir, in_mp4, out_mp4, factor=1.0, ffmpeg="ffmpeg",
          images_dir="images"):
    scenes = json.load(open(scenes_path, encoding="utf-8"))["scenes"]
    ov = json.load(open(ov_path, encoding="utf-8"))
    factor = float(factor)
    # cumulative pre-stretch start of every scene id present in this cut
    starts, t = {}, 0.0
    for s in scenes:
        starts[s["id"]] = t
        t += s["duration_sec"]
    total = float(subprocess.run(["ffprobe".join(ffmpeg.rsplit("ffmpeg", 1)), "-v", "error",
                                  "-show_entries", "format=duration", "-of", "csv=p=0", in_mp4],
                                 capture_output=True, text=True).stdout.strip())
    inputs, filters, mixn = ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=stereo"], [], []
    idx = [2]  # input 0 = in_mp4 (video), input 1 = silence bed

    def _add(sid, sound, at, tag):
        snd = None
        for e in (".mp3", ".wav", ".m4a", ".ogg"):
            p = os.path.join(sfx_dir, (sound or "whoosh") + e)
            if os.path.exists(p):
                snd = p; break
        if not snd:
            print(f"[{sid:03d}] звук '{sound}' не найден в {sfx_dir}")
            return
        pos_ms = int((starts[sid] + float(at)) * factor * 1000)
        inputs.extend(["-i", snd])
        filters.append(f"[{idx[0]}:a]adelay={pos_ms}|{pos_ms},volume=0.9[s{idx[0]}]")
        mixn.append(f"[s{idx[0]}]")
        print(f"[{sid:03d}] {tag}{sound} @ {pos_ms/1000:.2f}s (финальный таймлайн)")
        idx[0] += 1

    for sid_s, spec in ov.items():
        if not str(sid_s).isdigit():
            continue
        sid = int(sid_s)
        if sid not in starts:
            continue
        if spec.get("photo") and os.path.exists(spec["photo"]):
            _add(sid, spec.get("sound", "whoosh"), spec.get("at", LEAD), "")
        ts = spec.get("text") if isinstance(spec.get("text"), dict) else None
        if ts and str(ts.get("words") or ts.get("text") or "").strip():
            _add(sid, ts.get("sound", "whoosh"), ts.get("at", LEAD), "ТЕКСТ ")
    if not mixn:
        print("нет звуков для наложения — просто копирую видео")
        subprocess.run([ffmpeg, "-y", "-i", in_mp4, "-c", "copy", out_mp4], capture_output=True)
        return
    fc = ";".join(filters) + f";[1:a]{''.join(mixn)}amix=inputs={len(mixn)+1}:normalize=0[a]"
    cmd = [ffmpeg, "-y", "-i", in_mp4] + inputs + [
        "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 10000
    print(("готово: " + out_mp4) if ok else ("FAIL\n" + r.stderr[-800:]))


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "overlay":
        do_overlay(*sys.argv[2:6])
    elif mode == "sfx":
        do_sfx(*sys.argv[2:])
    else:
        print(__doc__)
