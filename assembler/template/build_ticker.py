#!/usr/bin/env python3
"""Верхняя бегущая строка (ticker) — отдельный, НЕОБЯЗАТЕЛЬНЫЙ модуль.

Намеренно изолирован от всего остального пайплайна (user, 2026-10-03: "чтобы
если упала эта херня, то и не посыпалось всё остальное" + "чтобы отключили
одним махом"):

  - Данные живут в своём файле ticker.json (не в overlays.json), читает и
    пишет его только review.py-функции load_ticker/save_ticker/drop_ticker,
    никогда не пересекается с overlays.json/_overlays_txn.
  - Если ticker.json в папке проекта не создан — дашборд не показывает НИ
    ОДНОЙ панели этой фичи, карточки выглядят ровно как раньше.
  - Рендер (bake) работает НЕ на отдельных клипах и не встроен в
    build_overlays.py/ship.sh/облачный workflow — он накладывается ОДНИМ
    отдельным проходом ffmpeg на уже ГОТОВЫЙ финальный видеоряд (тот самый
    файл, который get.sh скачал после облачной сборки), и пишет НОВЫЙ файл,
    не трогая исходный. Значит: облачный pipeline (clips/overlays/concat/
    sfx/Release) этой фичи вообще не видит и не может из-за неё сломаться.
  - "Не понравилось" = просто не брать файл с суффиксом _ticker.mp4,
    доставить как обычно оригинал. Никакого отдельного "undo" не нужно —
    ничего не перезаписывается на месте.

ticker.json: {"<scene_id>": {"text": "ЗАГОЛОВОК", "approved": true}, ...}

Режимы:
  propose <scenes.json> <ticker.json> [every_n=10]
      Создаёт черновые предложения на каждую N-ю сцену (approved:false —
      ничего не запечётся, пока пользователь не утвердит на дашборде).
      Не трогает записи, которые уже есть в ticker.json.

  bake <scenes.json> <final.mp4> <ticker.json> <final_ticker.mp4>
      Один проход ffmpeg по готовому финальному видео: во время каждой
      УТВЕРЖДЁННОЙ (approved:true) сцены сверху кадра едет полупрозрачная
      чёрная полоса с бегущим текстом. Если утверждённых строк нет —
      просто копирует вход в выход (-c copy), без перекодирования.

  one <in.mp4> <text> <out.mp4>
      Запекает строку на ВСЮ длину одного короткого клипа (0..конец) —
      используется дашбордом (`▶ превью`) для немедленного визуального
      предпросмотра одной карточки, без полной финальной сборки.
"""
import json
import os
import shutil
import subprocess
import sys

# ВАЖНО (user, 2026-10-04: "надо сделать так чтобы оно не брало все ресы
# процессора..я ничего не могу делать") — этот bake-проход запекается
# ЛОКАЛЬНО на машине пользователя (см. docstring выше — специально НЕ в
# облаке), поэтому в отличие от облачного раннера здесь нельзя просто занять
# все ядра: пользователь в это время работает за тем же компьютером.
# Ограничиваем явно двумя способами: `-threads N` (ffmpeg сам не хватает
# больше ядер, чем нужно) и `nice`/`ionice` (сам процесс уступает CPU/диск
# любой интерактивной задаче). 2026-10-07: "половина ядер" на практике
# всё равно ощутимо грузила слабую машину пользователя на серии клипов
# подряд (script-to-video/frame_clips.py) — жёсткий потолок 2, не доля ядер.
_THREADS = 2


def _throttled(cmd):
    prefix = []
    if shutil.which("ionice"):
        prefix += ["ionice", "-c", "3"]
    if shutil.which("nice"):
        prefix += ["nice", "-n", "15"]
    return prefix + cmd


W = 1920             # ширина кадра — тот же холст, что и весь остальной пайплайн
BAR_H = 64          # высота плашки, px
MARGIN_TOP = 18      # отступ сверху кадра, px
SLIDE = 0.4          # заезд/выезд строки, сек
MARGIN_X = 40        # отступ строки от левого края внутри плашки, px

_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    os.path.expanduser("~/.local/share/fonts/DejaVuSans-Bold.ttf"),
]


def _render_strip(text, out_png):
    # ВАЖНО (user, 2026-10-03: "не успела пройти... не прочитать до конца") —
    # строка больше НЕ едет бесконечной каруселью на фиксированной скорости:
    # короткая сцена (6-10с) физически не даёт бегущей строке прокрутиться
    # и прочитаться за один проход. Вместо этого — заезжает один раз слева
    # направо до упора, ЗАСТЫВАЕТ целиком видимой (можно прочитать), потом
    # уезжает. Чтобы застыть ЦЕЛИКОМ видимой, текст должен физически
    # влезать в ширину кадра — поэтому размер шрифта подбирается "сверху
    # вниз", пока строка не влезет в (W - 2*MARGIN_X).
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    txt = " ".join(str(text or "").split()).upper()
    if not txt:
        return None
    max_w = W - 2 * MARGIN_X
    font = None
    fs = 44
    while fs >= 22:
        cand = None
        for fp in _FONTS:
            if os.path.exists(fp):
                try:
                    cand = ImageFont.truetype(fp, fs)
                    break
                except Exception:
                    pass
        if cand is None:
            font = ImageFont.load_default()
            break
        bb = ImageDraw.Draw(Image.new("RGB", (8, 8))).textbbox((0, 0), txt, font=cand)
        if bb[2] - bb[0] <= max_w or fs <= 22:
            font = cand
            break
        fs -= 2
    pad = 24
    bb = ImageDraw.Draw(Image.new("RGB", (8, 8))).textbbox((0, 0), txt, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    strip_w = max(min(tw + pad * 2, max_w + pad * 2), 8)
    img = Image.new("RGBA", (strip_w, BAR_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((pad - bb[0], (BAR_H - th) // 2 - bb[1]), txt, font=font, fill=(255, 255, 255, 255))
    try:
        img.save(out_png)
    except OSError:
        return None
    return strip_w


def _slide_xexpr(start, end):
    """Заезд слева-направо до упора у левого края, пауза (читается целиком),
    выезд. Не непрерывная карусель — короткая сцена физически не даёт
    бесконечной прокрутке закончить проход и прочитаться."""
    dur = max(0.5, end - start)
    slide = min(SLIDE, max(0.05, dur / 2 - 0.05))
    hold = max(0.3, dur - 2 * slide)
    t0, t1 = start, start + slide
    t2 = start + slide + hold
    t3 = start + 2 * slide + hold
    rest, off = f"{MARGIN_X}", "W+8"

    def ramp(a, b, ta):
        return f"(({a})+(({b})-({a}))*((t-{ta:.3f})/{slide:.3f}))"

    return (f"if(lt(t,{t0:.3f}),{off},if(lt(t,{t1:.3f}),{ramp(off, rest, t0)},"
            f"if(lt(t,{t2:.3f}),{rest},if(lt(t,{t3:.3f}),{ramp(rest, off, t2)},{off}))))")


def propose(scenes_path, ticker_path, every_n="10"):
    scenes = json.load(open(scenes_path, encoding="utf-8"))["scenes"]
    try:
        tk = json.load(open(ticker_path, encoding="utf-8"))
    except (OSError, ValueError):
        tk = {}
    n = max(1, int(every_n))
    added = 0
    for i, s in enumerate(scenes, start=1):
        if i % n:
            continue
        sid = str(s["id"])
        if sid in tk:
            continue
        words = " ".join(str(s.get("text", "")).split())
        headline = words[:70].rsplit(" ", 1)[0] if len(words) > 70 else words
        if not headline:
            continue
        tk[sid] = {"text": headline, "approved": False}
        added += 1
    with open(ticker_path, "w", encoding="utf-8") as f:
        json.dump(tk, f, ensure_ascii=False, indent=2)
    print(f"предложено {added} заголовков -> {ticker_path} "
          f"(ничего не запечётся, пока не утвердишь на дашборде)")


def _scene_windows(scenes):
    starts, t = {}, 0.0
    for s in scenes:
        starts[s["id"]] = (t, t + s["duration_sec"])
        t += s["duration_sec"]
    return starts


def _duration(ffmpeg, path):
    ffprobe = "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1))
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                       "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def bake(scenes_path, in_mp4, ticker_path, out_mp4, ffmpeg="ffmpeg"):
    scenes = json.load(open(scenes_path, encoding="utf-8"))["scenes"]
    windows = _scene_windows(scenes)
    try:
        tk = json.load(open(ticker_path, encoding="utf-8"))
    except (OSError, ValueError):
        print("ticker.json не найден/пуст — копирую видео без изменений")
        subprocess.run([ffmpeg, "-y", "-i", in_mp4, "-c", "copy", out_mp4], capture_output=True)
        return

    items = []
    for sid_s, spec in tk.items():
        if not str(sid_s).isdigit():
            continue
        if not spec.get("approved") or not str(spec.get("text", "")).strip():
            continue
        sid = int(sid_s)
        if sid not in windows:
            continue
        start, end = windows[sid]
        items.append((sid, spec["text"], start, end))
    items.sort(key=lambda x: x[2])

    if not items:
        print("нет утверждённых строк — копирую видео без изменений")
        subprocess.run([ffmpeg, "-y", "-i", in_mp4, "-c", "copy", out_mp4], capture_output=True)
        return

    outdir = os.path.dirname(os.path.abspath(out_mp4)) or "."
    inputs, filters, pngs = [], [], []
    chain = "[0:v]"
    for i, (sid, text, start, end) in enumerate(items):
        png = os.path.join(outdir, f".tick_{sid:03d}.png")
        if _render_strip(text, png) is None:
            print(f"[{sid:03d}] не вышло отрендерить текст, пропуск")
            continue
        pngs.append(png)
        inputs += ["-loop", "1", "-i", png]
        in_idx = len(pngs)
        bg, txtl, outl = f"bg{i}", f"t{i}", f"v{i}"
        filters.append(
            f"{chain}drawbox=x=0:y={MARGIN_TOP-6}:w=iw:h={BAR_H+12}:color=black@0.55:t=fill:"
            f"enable='between(t,{start:.3f},{end:.3f})'[{bg}]"
        )
        filters.append(f"[{in_idx}:v]format=rgba[{txtl}]")
        filters.append(
            f"[{bg}][{txtl}]overlay=x='{_slide_xexpr(start, end)}':y={MARGIN_TOP}:"
            f"eval=frame:enable='between(t,{start:.3f},{end:.3f})'[{outl}]"
        )
        chain = f"[{outl}]"
        print(f"[{sid:03d}] бегущая строка «{text}» @ {start:.1f}-{end:.1f}s")

    if not pngs:
        print("ни одной строки не отрендерилось — копирую видео без изменений")
        subprocess.run([ffmpeg, "-y", "-i", in_mp4, "-c", "copy", out_mp4], capture_output=True)
        return

    # КРИТИЧНО: без явного -t выход никогда не останавливается на длине
    # оригинала. `-loop 1` на PNG-вход картинки бесконечен, и у overlay
    # дефолтный eof_action просто повторяет последний кадр того входа, что
    # закончился раньше (здесь — основное видео), поэтому кодирование
    # продолжается НАВСЕГДА, а не обрывается на настоящей длине ролика.
    # Поймано живьём 2026-10-03: без -t ffmpeg молча кодировал synthetic-
    # тест и затем реальный 8-секундный клип бесконечно (>100x дольше, чем
    # сам клип), съедая 100% CPU, пока процесс не убили руками.
    total = _duration(ffmpeg, in_mp4)
    fc = ";".join(filters) + f";{chain}format=yuv420p[vout]"
    cmd = _throttled([ffmpeg, "-y", "-i", in_mp4] + inputs + [
        "-filter_complex", fc, "-map", "[vout]", "-map", "0:a?",
        "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-threads", str(_THREADS),
        "-c:a", "copy", out_mp4,
    ])
    r = subprocess.run(cmd, capture_output=True, text=True)
    for p in pngs:
        try:
            os.remove(p)
        except OSError:
            pass
    ok = r.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 10000
    if ok:
        print(f"готово: {out_mp4} ({len(items)} заголовков). "
              f"Оригинал {in_mp4} не тронут — сравни и выбери, что доставлять.")
    else:
        print("FAIL\n" + r.stderr[-800:])


def bake_one(in_mp4, text, out_mp4, ffmpeg="ffmpeg"):
    """Одна строка на всю длину одного клипа — для ▶ превью на дашборде.
    Возвращает True/False, никогда не бросает исключение наружу (вызывающая
    сторона — review.py — должна просто получить False и показать клип без
    строки, а не сломать весь предпросмотр из-за этой необязательной фичи)."""
    try:
        dur = _duration(ffmpeg, in_mp4)
        if dur <= 0:
            return False
        png = out_mp4 + ".tick.png"
        if _render_strip(text, png) is None:
            return False
        fc = (
            f"[0:v]drawbox=x=0:y={MARGIN_TOP-6}:w=iw:h={BAR_H+12}:color=black@0.55:t=fill[bg];"
            f"[1:v]format=rgba[t];"
            f"[bg][t]overlay=x='{_slide_xexpr(0, dur)}':y={MARGIN_TOP}:eval=frame[v]"
        )
        cmd = _throttled([ffmpeg, "-y", "-i", in_mp4, "-loop", "1", "-i", png,
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
               "-t", f"{dur:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-threads", str(_THREADS),
               "-c:a", "copy", out_mp4])
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            os.remove(png)
        except OSError:
            pass
        return r.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 10000
    except Exception:
        return False


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "propose":
        propose(*sys.argv[2:5])
    elif mode == "bake":
        bake(*sys.argv[2:6])
    elif mode == "one":
        ok = bake_one(sys.argv[2], sys.argv[3], sys.argv[4])
        print("ok" if ok else "FAIL")
    else:
        print(__doc__)
