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
import re
import sys
import subprocess
import random


# ОГРАНИЧЕНИЕ ПОТОКОВ FFMPEG: ЛОКАЛЬНО — ДА, В ОБЛАКЕ — НЕТ (2026-10-19).
# Повод: вкладка второго сборщика гоняла локальный прогон, ffmpeg забрал
# 522% из восьми ядер (load average 8,4), дашборд рабочей вкладки и соседние
# сессии встали. Снаружи это не лечится: `nice` понижает приоритет, но не
# число ядер, а эти скрипты зовут ffmpeg САМИ и потолок не выставляли —
# сколько ни ограничивай снаружи, внутрь не действует.
# В облаке ограничивать нельзя — там раннер и должен занимать все ядра,
# поэтому потолок включается только ВНЕ GitHub Actions. Переопределяется
# переменной VIDEORYAD_FFMPEG_THREADS (0 = без ограничения).
def _threads_args():
    v = os.environ.get("VIDEORYAD_FFMPEG_THREADS")
    if v is None:
        v = "0" if os.environ.get("GITHUB_ACTIONS") else "2"
    return ["-threads", v] if v not in (None, "", "0") else []

W, H, FPS = 1920, 1080, 30

# Сцены-карточки арсенала (source «card:...»). На нарисованный нами кадр
# эффекты НЕ КЛАДУТСЯ (2026-10-22): блик-пролёт по листу бумаги, зерно и
# «дыхание» яркости на ровном бумажном поле читаются как брак печати, а не
# как приём. Набор заполняется в main() из scenes.json; пустой — поведение
# ровно прежнее.
CARD_SIDS = set()


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


# Порог «узкого» кадра — тот же, что у отбора в fetch_assets_news.py.
NARROW_W, NARROW_H = 1600, 900


def build_image_clip(ffmpeg, src, out_path, duration, ffprobe="ffprobe"):
    frames = int(duration * FPS)
    w, h = _img_wh(ffprobe, src)
    portrait = (w / h) < 1.15  # portrait / square / 4:3 -> would lose too much to a 16:9 centre-crop
    # УЗКИЙ ГОРИЗОНТАЛЬНЫЙ КАДР — НЕ РАСТЯГИВАЕМ, А ЗАЛИВАЕМ ПОЛЯ (решение
    # пользователя 30.10, дословно: «можем их помещать в середину его
    # реальный размер, а по краям то, что остаётся чёрное, делать размытый
    # его же, только размытым очень размытым фоном, как мы делаем с
    # вертикальными»). Повод: на прифронтовых городах выдача живёт в
    # коридоре 1200-1500 px, снимок растягивался до 2560 (в два раза) и
    # мылился, а вкладка жгла круги правок на поиск более широкого — которого
    # в выдаче просто нет (замер 30.10: 14 узких из 52 до переписи запросов,
    # 13 после, то есть формулировки ширину НЕ лечат).
    narrow = (not portrait) and (w < NARROW_W or h < NARROW_H)
    m = re.search(r"clip_(\d+)", os.path.basename(out_path))
    # -1, а не 0: при нераспознанном имени 0 %% N == 0 включало блик
    # на КАЖДОЙ такой сцене (поймано на тесте 2026-10-16)
    sid = int(m.group(1)) if m else -1
    fxc = _fx_chain(sid)                      # виньетка/дыхание/зерно, пусто если fx.json нет
    fx_in, fx_steps, fx_out = _fx_layers(sid, duration)  # блик/пылинки/дымка
    tail = (("," + fxc) if fxc else "")

    if portrait or narrow:
        # blurred-fill: whole image visible (fit by the frame), sides filled
        # with a darkened, blurred, zoomed copy of the same image. Gentle push
        # on the composite so no edge is ever revealed. Faces never get cut.
        if narrow:
            # Наезд ТОЛЬКО внутрь и мягкий: первый кадр показывает снимок в
            # его родном размере, как и просил пользователь.
            z = "min(zoom+0.00025,1.06)"
            # Коробка переднего плана = родной размер, прижатый рамкой.
            # Пропорции сохраняет сам ffmpeg (decrease), поэтому снимок
            # 1400x900 ляжет 1400x900, а 1500x1200 — 1350x1080.
            fgw, fgh = min(w, W), min(h, H)
        else:
            z = ("min(zoom+0.00035,1.08)" if random.random() < 0.5
                 else "if(eq(on,0),1.08,max(zoom-0.00035,1.0))")
            fgw, fgh = W, H
        core = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=24:2,eq=brightness=-0.12:saturation=0.65[bgb];"
            f"[fg]scale={fgw}:{fgh}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[base];"
            f"[base]zoompan=z='{z}':x='{_ZX}':y='{_ZY}':"
            f"d={frames}:s={W}x{H}:fps={FPS}{tail}"
        )
    else:
        zoom_dir = random.choice(["in", "out"])
        zexpr = ("min(zoom+0.0006,1.18)" if zoom_dir == "in"
                 else "if(eq(on,0),1.18,max(zoom-0.0006,1.0))")
        core = (
            f"[0:v]scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,"
            f"zoompan=z='{zexpr}':x='{_ZX}':y='{_ZY}':"
            f"d={frames}:s={W}x{H}:fps={FPS}{tail}"
        )

    # Субтитры всегда идут ПОСЛЕДНИМИ — поверх эффектов, иначе виньетка
    # притемняет их край, а блик проезжает по тексту.
    if fx_steps:
        vf = f"{core}[vfx];{fx_steps};[{fx_out}]format=yuv420p{_caps(out_path)}[final]"
    else:
        vf = f"{core},format=yuv420p{_caps(out_path)}[final]"
    out_map = ["-map", "[final]"]

    cmd = [ffmpeg, "-y", *_threads_args(), "-loop", "1", "-i", src, *fx_in,
           "-filter_complex", vf, *out_map, "-t", str(duration),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", out_path]
    subprocess.run(cmd, check=True, capture_output=True)


_FX = None


def _fx():
    """Параметры эффектов. Выключатель ФИЗИЧЕСКИЙ, как у субтитров: файл
    `fx.json` в папке проекта. Нет файла — ни один фильтр не добавляется и
    поведение ровно такое же, как было до появления этой функции.

    Формат (все ключи необязательны):
        {"vignette": true,          # затемнение краёв кадра
         "breath": true,            # медленное «дыхание» яркости
         "grain": 0,                # зерно плёнки, 0 = выкл, обычно 4-8
         "flare_every": 6,          # блик-пролёт на каждой N-й сцене, 0 = выкл
         "flare_opacity": 0.28}     # сила блика

    Цена (замер 2026-10-16 на 12-секундном клипе): дыхание +19%, блик +73%,
    виньетка +98%, зерно +111% к КОДИРОВАНИЮ. В облаке кодирование — меньше
    половины джоба (27-40 с из 65-79 с, остальное установка ffmpeg), поэтому
    весь набор добавляет к сборке ролика около минуты, не больше.
    """
    global _FX
    if _FX is None:
        try:
            with open(os.path.join(_fx_dir(), "fx.json"), encoding="utf-8") as fh:
                _FX = json.load(fh)
        except (OSError, ValueError):
            _FX = {}
    return _FX


def _fx_dir():
    """Каталог проекта. В облаке клипы режет ШАГ WORKFLOW, а не
    cloud_pipeline, и рабочий каталог там — корень репозитория, а не папка
    ролика: `fx.json` рядом с cwd не находится и эффекты молча не
    применяются (поймано на первой же пробной сборке 2026-10-16 — ролик
    приехал с субтитрами, но без единого эффекта). Субтитры этим не
    страдали, потому что им путь отдаётся переменной CAPTIONS_DIR. Теперь
    так же: FX_DIR с абсолютным путём, иначе текущий каталог (локальный
    запуск).
    """
    return os.environ.get("FX_DIR", "") or "."


# ЗУМ ИДЁТ ИЗ ЦЕНТРА, А НЕ ОТ УГЛА (28.10, прямое наблюдение пользователя:
# «какой-то странный зум, тянет всё вправо, не по центру зумит… особенно видно
# на цитатах»). У фильтра `zoompan` координаты по умолчанию x=0, y=0 — то есть
# окно зума прижато к ЛЕВОМУ ВЕРХНЕМУ УГЛУ, и кадр на глазах уезжает в
# сторону. Центр надо задавать руками. На карточках-цитатах это било сильнее
# всего: уезжающий текст виден сразу, в отличие от фотографии.
_ZX = "iw/2-(iw/zoom/2)"
_ZY = "ih/2-(ih/zoom/2)"


def _fx_chain(sid):
    """Фильтры эффектов для ОДНОЙ сцены, без ведущей запятой."""
    fx = _fx()
    if not fx or sid in CARD_SIDS:
        return ""
    parts = []
    if fx.get("vignette"):
        parts.append("vignette=PI/5")
    if fx.get("breath"):
        # период 6 с, амплитуда 2% — заметно глазу как «живой» кадр, но не как эффект
        parts.append("eq=brightness='0.02*sin(2*PI*t/6)'")
    g = fx.get("grain") or 0
    if g:
        parts.append(f"noise=alls={int(g)}:allf=t")
    return ",".join(parts)


def _fx_layers(sid, duration):
    """Все световые слои сцены: (доп. входы ffmpeg, кусок фильтра, метка выхода).

    Слоёв два вида:
      flare  — блик-пролёт по широкой картинке `fx_flare.png` (окно едет crop'ом);
      видео  — зацикленные `particles.mp4` / `haze.mp4` из template/fx.

    Смешивание всегда ЭКРАННОЕ и всегда в RGB: у слоёв чёрный фон, при screen
    он не меняет кадр. В yuv420p тот же режим калечит цветовые плоскости и
    кадр уезжает в маджента (поймано 2026-10-16).
    """
    fx = _fx()
    if sid < 0 or not fx or sid in CARD_SIDS:
        return [], "", "vfx"
    ins, steps, cur = [], [], "vfx"
    idx = 1                                   # 0 — сам кадр

    every = int(fx.get("flare_every") or 0)
    flare_png = os.path.join(_fx_dir(), "fx_flare.png")
    if every and sid % every == 0 and os.path.isfile(flare_png):
        ins += ["-loop", "1", "-i", flare_png]
        x = f"(t/{duration})*{4800 - W}"
        nxt = f"v{idx}"
        steps.append(f"[{idx}:v]crop={W}:{H}:x='{x}':y=0,format=gbrp[fl];"
                     f"[{cur}]format=gbrp[b{idx}];[b{idx}][fl]blend=all_mode=screen[{nxt}]")
        cur = nxt; idx += 1

    # СЛОЙ НЕ НА КАЖДУЮ СЦЕНУ (user, 2026-10-17: «делаем примерно рандомно,
    # каждая седьмая-восьмая сцена, не надо на каждую»). `layers_every: N` —
    # слой ложится примерно на каждую N-ю сцену, выбор псевдослучайный, но
    # ДЕТЕРМИНИРОВАННЫЙ по номеру сцены: пересборка, рефетч и повтор шарда
    # дают тот же набор сцен, иначе ролик менял бы вид от прогона к прогону.
    # 0 или ключа нет — поведение прежнее (слой на каждой сцене), на нём
    # держится второй сборщик.
    every_l = int(fx.get("layers_every") or 0)
    if every_l > 1 and sid not in _layer_scenes(every_l):
        return (ins, ";".join(steps), cur) if steps else ([], "", "vfx")

    for name in (fx.get("layers") or []):
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fx", f"{name}.mp4")
        if not os.path.isfile(src):
            continue
        op = float(fx.get("layer_opacity") or 0.55)
        ins += ["-stream_loop", "-1", "-i", src]
        nxt = f"v{idx}"
        steps.append(f"[{idx}:v]scale={W}:{H},format=gbrp,"
                     f"colorchannelmixer=rr={op}:gg={op}:bb={op}[ly{idx}];"
                     f"[{cur}]format=gbrp[b{idx}];[b{idx}][ly{idx}]blend=all_mode=screen[{nxt}]")
        cur = nxt; idx += 1

    if not steps:
        return [], "", "vfx"
    return ins, ";".join(steps), cur

def _layer_scenes(every, upto=400, _cache={}):
    """Номера сцен, на которые ложится видеослой: шаг `every` с разбросом ±1.

    Чистый хеш (первый подход) давал провалы по 20 сцен подряд, а ровный шаг
    выглядит механически. Здесь шаг гуляет 6-8 при `every=7`, и набор
    ДЕТЕРМИНИРОВАН: сид фиксирован, поэтому пересборка, рефетч и повтор
    шарда дают те же сцены, и ролик не меняет вид от прогона к прогону.
    """
    key = (every, upto)
    if key not in _cache:
        import random
        rnd = random.Random(20261017)
        out, sid = set(), max(2, every - 1)
        while sid <= upto:
            out.add(sid)
            sid += every + rnd.choice((-1, 0, 1))
        _cache[key] = out
    return _cache[key]


def _caps(out_path):
    """Добавка фильтра субтитров к цепочке — ТОЛЬКО если они явно включены.

    Включаются присутствием каталога с по-сценными .ass (переменная
    CAPTIONS_DIR, её выставляет workflow, когда в проекте лежит captions.ass).
    Переменной нет или куска для этой сцены нет -> возвращается пустая строка,
    то есть поведение ровно такое же, как было до появления субтитров.
    Стоимость самого вжигания — +2% к кодированию клипа (замер 2026-10-14),
    поэтому делаем это здесь, на 12 машинах, а не одним проходом по финалу.
    """
    d = os.environ.get("CAPTIONS_DIR", "")
    if not d:
        return ""
    m = re.search(r"clip_(\d+)", os.path.basename(out_path))
    if not m:
        return ""
    f = os.path.join(d, f"scene_{int(m.group(1)):03d}.ass")
    if not os.path.isfile(f):
        return ""
    esc = f.replace("\\", "/").replace(":", r"\:").replace(",", r"\,")
    # папку со шрифтами отдаём явно: на раннере GitHub своего Roboto
    # Condensed нет, и без fontsdir субтитры падали бы на системный Arial
    fd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    if os.path.isdir(fd):
        fde = fd.replace("\\", "/").replace(":", r"\:").replace(",", r"\,")
        return f",ass='{esc}':fontsdir='{fde}'"
    return f",ass='{esc}'"


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
    _m = re.search(r"clip_(\d+)", os.path.basename(out_path))
    _fxc = _fx_chain(int(_m.group(1)) if _m else 0)
    # УЗКОЕ ИЛИ ОБРЕЗАННОЕ ВИДЕО — РОДНОЙ РАЗМЕР И ЗАЛИВКА ПОЛЕЙ, А НЕ
    # ДОРЕЗКА (30.10, решение пользователя — то же, что для фото). Повод:
    # у телеканалов знак стоит в углу, `crop_brand.py` срезает полосу с краю,
    # и кадр перестаёт быть 16:9. Старая ветка дорезала его ещё раз под
    # рамку — то есть выбрасывала уже вторую часть картинки. Теперь кадр
    # ставится как есть по центру, поля — размытая притемнённая копия его же.
    try:
        _vw, _vh = _img_wh(ffprobe, src)
    except Exception:
        _vw, _vh = W, H
    _ratio = (_vw / _vh) if _vh else (W / H)
    if _ratio < 1.70:
        _fw, _fh = min(_vw, W), min(_vh, H)
        vf = (f"[0:v]setpts=PTS-STARTPTS,fps={FPS},split=2[bg][fg];"
              f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"boxblur=24:2,eq=brightness=-0.12:saturation=0.65[bgb];"
              f"[fg]scale={_fw}:{_fh}:force_original_aspect_ratio=decrease[fgs];"
              f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
              + ("," + _fxc if _fxc else "") + f",format=yuv420p{_caps(out_path)}")
        _vf_args = ["-filter_complex", vf]
    else:
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"setpts=PTS-STARTPTS,fps={FPS}" + ("," + _fxc if _fxc else "") +
              f",format=yuv420p{_caps(out_path)}")
        _vf_args = ["-vf", vf]
    loop_args = ["-stream_loop", "-1"] if (src_dur and src_dur < duration) else []
    seek_args = ["-ss", str(start)] if start > 0 else []
    cmd = [ffmpeg, "-y", *loop_args, *seek_args, "-i", src, *_vf_args, "-t", str(duration),
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

    CARD_SIDS.update(s["id"] for s in data["scenes"]
                     if str(s.get("source", "")).startswith("card"))
    if CARD_SIDS:
        print("карточки арсенала (без эффектов): "
              + ", ".join(str(i) for i in sorted(CARD_SIDS)))

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
