"""Build a scenes.json skeleton straight from the narration's own SRT +
audio, with GAP-INCLUSIVE durations so the assembled видеоряд matches the
narration timeline natively — no global setpts stretch needed afterwards.

Why: SRT cues cover only spoken words; summing cue [start,end] leaves out
the pauses between sentences (≈15-20 s over a 12-min script) and the lead/
tail silence, so the naive sum comes out short and needs a ×1.02 stretch.
Here each scene's duration = (next scene's start − this scene's start), the
first scene starts at 0, and the last scene runs to the audio's end. Sum =
exact narration length → concat the clips with `-c copy` (instant) and skip
the stretch entirely.

  python3 scenes_from_srt.py <caption.srt> <narration.(mp4|wav|m4a|...)> <out.scenes.json>
  python3 scenes_from_srt.py <caption.srt> <out.scenes.json>   # no media file:
      total duration = the SRT's own last cue end-time (no ffprobe needed).

Emits scenes with text + duration_sec + start_sec and TODO source fields.
Claude then fills `source` / `source_query` / `visual_prompt` per scene
(the classification is judgement, not automatable), fetches, builds.
"""
import json
import re
import subprocess
import sys

SENT_END = tuple(".!?»")
MIN_SCENE = 5.0       # don't cut a scene shorter than this on a sentence end —
                      # raised from 3.2 (user, 2026-09-28: too many cuts, short
                      # connective one-liners ("Совпадение? Возможно.") don't
                      # need their own image — a held/zoomed photo is enough,
                      # no need to source extra video for them). Absorbing
                      # these into the neighbouring beat cuts total scene
                      # count ~20% (measured on 3 same-day scripts: 139->112,
                      # 98->77, 58->45) without touching dashboard/schema.
MAX_SCENE = 12.0      # force a cut here even mid-sentence — raised from 9.0
                      # to match: at MIN_SCENE=5.0 a 9s cap fired mid-sentence
                      # far more often (26x on a test script vs 9x at 12.0)
                      # for no reduction in scene count (the natural sentence
                      # end usually lands a beat later anyway) — 12.0 avoids
                      # the extra awkward mid-sentence cuts for free.


def ts(s):
    h, m, rest = s.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def parse_srt(path):
    cues = []
    blocks = open(path, encoding="utf-8-sig").read().strip().split("\n\n")
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 2:
            continue
        m = re.search(r"(\d\d:\d\d:\d\d,\d+)\s*-->\s*(\d\d:\d\d:\d\d,\d+)", lines[1])
        if not m:
            continue
        text = " ".join(x.strip() for x in lines[2:]).strip()
        cues.append([ts(m.group(1)), ts(m.group(2)), text])
    return cues


def media_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())


def main():
    args = sys.argv[1:]
    if len(args) == 2:
        srt, out = args
        media = None
    elif len(args) == 3:
        srt, media, out = args
    else:
        print(__doc__)
        raise SystemExit(1)
    cues = parse_srt(srt)
    total = media_duration(media) if media else cues[-1][1]

    # merge cues into scene beats
    scenes, cur = [], None
    for st, en, tx in cues:
        if cur is None:
            cur = [st, en, tx]
        else:
            cur[1] = en
            cur[2] = (cur[2] + " " + tx).strip()
        dur = cur[1] - cur[0]
        if (cur[2].rstrip().endswith(SENT_END) and dur >= MIN_SCENE) or dur >= MAX_SCENE:
            scenes.append(cur)
            cur = None
    if cur:
        if scenes and (cur[1] - cur[0]) < 2.0:
            scenes[-1][1] = cur[1]
            scenes[-1][2] += " " + cur[2]
        else:
            scenes.append(cur)

    # gap-inclusive: scene start = cue start (scene 1 forced to 0),
    # duration = next start - this start; last runs to media end
    starts = [0.0] + [s[0] for s in scenes[1:]]
    out_scenes = []
    for i, (s, start) in enumerate(zip(scenes, starts)):
        nxt = starts[i + 1] if i + 1 < len(starts) else total
        out_scenes.append({
            "id": i + 1,
            "text": s[2],
            "start_sec": round(start, 2),
            "duration_sec": round(nxt - start, 2),
            "visual_prompt": "",
            "source": "TODO",       # Claude fills: local_library / wikimedia / press_photo / pexels_photo / pexels_video
            "source_query": "",
        })

    json.dump({"scenes": out_scenes}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    summed = sum(x["duration_sec"] for x in out_scenes)
    src_label = "narration" if media else "SRT last cue"
    print(f"{len(cues)} cues -> {len(out_scenes)} scenes")
    print(f"{src_label} {total:.1f}s  |  scenes sum {summed:.1f}s  |  diff {summed - total:+.2f}s "
          f"({'OK — no stretch needed' if abs(summed - total) < 0.5 else 'CHECK'})")
    print(f"wrote {out}\n")
    for x in out_scenes:
        print(f"{x['id']:3} [{x['start_sec']:6.1f} +{x['duration_sec']:4.1f}] {x['text'][:76]}")


if __name__ == "__main__":
    main()
