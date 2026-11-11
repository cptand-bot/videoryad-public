# -*- coding: utf-8 -*-
"""Белый зал, вторая реализация (Fable). Запуск: shard_fable.py <код> <out.mp4>
Сцены живут в двух модулях: shard_fable_a (G02 G10 G12), shard_fable_b (G11 G15 G26)."""
import sys, os, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zal_core as Z

FPS = 30
SCENES = {}
for mod in ("shard_fable_a", "shard_fable_b", "shard_fable_c", "shard_fable_d", "shard_fable_e", "shard_fable_f", "shard_fable_g"):
    try:
        m = __import__(mod)
        SCENES.update(getattr(m, "SCENES", {}))
    except Exception as exc:
        print("нет модуля", mod, ":", exc)

def render(code, out):
    fn, dur = SCENES[code]
    n = int(dur * FPS)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = "ffmpeg"
    p = subprocess.Popen([exe, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{Z.W}x{Z.H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                          "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                         stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(fn(i / FPS).convert("RGB").tobytes())
    p.stdin.close(); p.wait()
    print("готово:", out, n, "кадров")

if __name__ == "__main__":
    code = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else f"{code}.mp4"
    if os.environ.get("ZAL_FRAME"):
        t = float(os.environ["ZAL_FRAME"])
        SCENES[code][0](t).convert("RGB").save(out)
        print("кадр", t, "->", out)
    else:
        render(code, out)
