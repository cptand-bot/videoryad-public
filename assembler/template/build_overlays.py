"""Corner slide-in photo pop-ups + baked SFX for a видеоряд (news OR esoteric).

Reads overlays.json: {"<scene_id>": {"photo": "<path>", "sound": "<name>", "at": <sec>}}
  - photo: image to pop up (relative to project dir or absolute)
  - sound: base name of a file in <sfx-dir> (e.g. "whoosh" -> whoosh.mp3/.wav)
  - at:    seconds into that scene's clip when the pop-up starts sliding in

УСТАРЕВШЕЕ ПРАВИЛО, СНЯТО 05.11 (улов `usuario-ca`): здесь годами стояло
«всплывашку получают только сцены, где основной клип ВИДЕО», и КОД ЭТОГО НЕ
ПРОВЕРЯЕТ — ставит на любые, в том числе на фото-сцены. Вкладка, поверившая
шапке, поставила бы 2 всплывашки вместо 10 и получила бы отказ `selfcheck`
(ориентир — около десяти фото-всплывашек на ролик). Фото поверх фото в подаче
канала нормально: у всплывашки своя рамка, тень и въезд.
Сцена без годного кадра пропускается с предупреждением — это осталось.

Two stages:
  overlay  — re-render each listed clip with the corner slide-in. Keeps the
             original as clip_NNN.orig.mp4 so a re-run is idempotent.
  sfx      — after the final video is assembled+stretched, bake one audio
             track: silence for the whole runtime + each sound placed at its
             final timeline position (scene-start + at, times the stretch
             factor). Muxes with -c:v copy.

Usage:
  python3 build_overlays.py build <папка проекта>   # собрать overlays.json
  python3 build_overlays.py overlay <scenes.json> <images-dir> <clips-dir> <overlays.json>
  python3 build_overlays.py sfx <scenes.json> <overlays.json> <sfx-dir> <in.mp4> <out.mp4> [stretch-factor]
"""
import json, os, re, sys, subprocess, glob, random, shutil

# ОГРАНИЧЕНИЕ ПОТОКОВ FFMPEG: ЛОКАЛЬНО — ДА, В ОБЛАКЕ — НЕТ (2026-10-19).
# Повод: локальный прогон второго сборщика забрал 522% из восьми ядер
# (load average 8,4) и подвесил дашборд рабочей вкладки. Снаружи не лечится:
# `nice` понижает приоритет, но не число ядер, а скрипт зовёт ffmpeg САМ.
# В облаке потолок не нужен — раннер и должен занимать все ядра, поэтому он
# включается только ВНЕ GitHub Actions. Переопределяется переменной
# VIDEORYAD_FFMPEG_THREADS (0 = без ограничения).
# ПОТОЛОК ВРЕМЕНИ НА КАЖДЫЙ ЗАПУСК ffmpeg (10.11, улов `usuario-ad`).
# Повод: шард `overlays (4)` ролика ПЛАНЕТА · Ультиматум Рябкова встал на
# сцене 052 и МОЛЧА простоял 19,5 минут при норме полторы, пока его не срезал
# `timeout-minutes` джоба — и без его кадров не доделался `assemble`, то есть
# зависание ОДНОГО кадра обнулило работу всех шардов. Ни один вызов ffmpeg
# здесь не имел ни `timeout`, ни `-nostdin`: зависший процесс висел до конца
# джоба, а в журнале после строки с размером всплывашки не было НИЧЕГО.
# Теперь: своя смерть по времени, внятная строка в журнал и клип БЕЗ
# всплывашки вместо потерянной сборки.
FF_TIMEOUT = int(os.environ.get("VIDEORYAD_FF_TIMEOUT", "240"))


def _kadr_chitaem(path, kak_video=False):
    """Файл действительно картинка (или видео), а не страница ошибки.

    Повод — сцена 052 ролика ПЛАНЕТА · Ультиматум Рябкова: под именем
    `scene_052.jpg` лежал HTML «404 Not Found» на 161 байт. Проверяем ДО
    ffmpeg, потому что он на таком входе не падает, а висит."""
    try:
        if not path or not os.path.exists(path) or os.path.getsize(path) < 800:
            return False
        with open(path, "rb") as fh:
            head = fh.read(16).lstrip()
        if head[:1] == b"<" or head[:5] == b"<?xml" or head[:9].lower() == b"<!doctype":
            return False                      # страница ошибки под видом кадра
        if kak_video:
            r = subprocess.run(
                ["ffprobe".join(os.environ.get("FFMPEG_BIN", "ffmpeg").rsplit("ffmpeg", 1)),
                 "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name", "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=30)
            return r.returncode == 0 and bool((r.stdout or "").strip())
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def _run_ff(cmd, sid=None, chto="ffmpeg", timeout=None):
    """Запуск ffmpeg, который не может повиснуть навсегда."""
    cmd = list(cmd)
    if cmd and "-nostdin" not in cmd:
        # без `-nostdin` ffmpeg умеет ждать ввода с терминала вечно
        cmd.insert(1, "-nostdin")
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout or FF_TIMEOUT)
    except subprocess.TimeoutExpired:
        met = f"[{sid:03d}] " if isinstance(sid, int) else ""
        print(f"{met}ffmpeg ВИС {timeout or FF_TIMEOUT} с на шаге «{chto}» — снял его "
              f"и иду дальше (сцена останется без этого слоя, сборка не встанет)",
              flush=True)
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def _threads_args():
    v = os.environ.get("VIDEORYAD_FFMPEG_THREADS")
    if v is None:
        v = "0" if os.environ.get("GITHUB_ACTIONS") else "2"
    return ["-threads", v] if v not in (None, "", "0") else []


_VID_EXT = (".mp4", ".mov", ".webm", ".mkv")

W, H, FPS = 1920, 1080, 30
SLIDE = 0.33               # slide-in / slide-out seconds
LEAD = 0.4                 # всплывашка появляется через долю секунды после старта сцены

# ВСПЛЫВАШКА НЕ ЛЕЗЕТ В ПЕРЕХОД (04.11). Сцена с `"fx": "mosaic|panels|wipe"`
# первые 0,7-1,6 с ещё ПРИЕЗЖАЕТ: кадр рассыпан на плитки, развёрнут панелями
# или наполовину закрыт прошлым кадром. Всплывашка по умолчанию въезжает на
# 0,4 с, то есть легла бы прямо на эту кашу. Поэтому на таких сценах её старт
# отодвигается за конец перехода. Длительности — те же, что в `fx_trans.py`.
FX_TRANS_SEC = {"mosaic": 1.6, "panels": 1.3, "wipe": 0.7,
                "depth": 1.1,   # пятый вид, 05.11
                "tear": 1.3,    # шестой вид, 05.11 (разрыв на куски)
                "flash": 0.6,   # седьмой вид, 06.11 (засвет, A73)
                # шесть приёмов канала «5 МИНУТ», 06.11 — длительности
                # один в один с `fx_trans5.TRANS_SEC`
                "player": 1.8, "curl": 1.6, "slides": 1.5,
                "stamps": 1.6, "torn": 1.4, "filmwin": 1.5}
FX_MIN_AT = {}             # sid -> не раньше этой секунды; заполняется в do_overlay


def _floor_at(sid, at, dur):
    if sid is None:
        return at
    lo = FX_MIN_AT.get(int(sid), 0.0)
    if lo <= 0 or at >= lo:
        return at
    # если сцена короткая и отодвигать некуда — оставляем как было
    return lo if lo < dur - 2 * SLIDE - 1.0 else at
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
# Цикл цветов ДУБЛИРУЕТ review.py (2026-10-22): сборке нужен тот же дефолт,
# что видел пользователь на дашборде, иначе надпись в готовом ролике другого
# цвета, чем на утверждённой карточке.
TEXT_COLOR_CYCLE = ("white", "yellow", "red", "green", "orange")


def text_color_for(sid):
    try:
        return TEXT_COLOR_CYCLE[int(sid) % len(TEXT_COLOR_CYCLE)]
    except (TypeError, ValueError):
        return "white"


_TXT_RGB = {"white": (255, 255, 255), "yellow": (255, 232, 0),
            "red": (255, 34, 28), "green": (46, 214, 94),
            "orange": (255, 146, 10)}

# ВЫБРАННЫЙ ШРИФТ ЕДЕТ ФАЙЛОМ (2026-10-17): файлы лежат рядом, в
# `template/fonts/`, и уходят в облако вместе с template/. Раннер GitHub
# несёт свой случайный набор системных шрифтов, поэтому имя семейства там
# ничего не гарантирует — только файл. Ключи совпадают с кнопками дашборда
# (review.py: TEXT_FONTS).
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_TXT_FONT_FILES = {
    "default": "", "arial": "Arimo-Bold.ttf", "times": "Tinos-Bold.ttf",
    "oswald": "Oswald-Bold.ttf", "montserrat": "Montserrat-Bold.ttf",
    "roboto": "RobotoCondensed-Bold.ttf",
}


def _load_txt_font(fkey, size):
    from PIL import ImageFont
    cand = []
    fn = _TXT_FONT_FILES.get(str(fkey or "default").lower(), "")
    if fn:
        cand.append(os.path.join(_FONT_DIR, fn))
    cand += _TXT_FONTS
    for fp in cand:
        if not os.path.exists(fp):
            continue
        try:
            font = ImageFont.truetype(fp, size)
        except Exception:
            continue
        try:
            font.set_variation_by_name("Bold")
        except Exception:
            pass
        return font
    return ImageFont.load_default()


def _render_text_png(words, color, out_path, fkey="default", style="plate"):
    """Текстовая всплывашка в СОВРЕМЕННОЙ подаче.

    Было до 20.10.2026: жёлтый капс с толстой чёрной обводкой — тот самый
    вид дешёвых роликов, который пользователь назвал колхозным. Обводка
    убрана совсем; вместо неё текст живёт на тёмной пластине, а цвет
    работает узкой акцентной чертой слева. Шрифт по умолчанию — узкий
    RobotoCondensed Bold, с разрядкой: он и читается крупнее при той же
    высоте, и выглядит как экранная графика, а не как подпись в Paint.

    style:
      plate  — тёмная пластина + акцентная черта слева (по умолчанию);
      bar    — текст на сплошной акцентной полосе (цвет = фон, текст тёмный);
      bare   — только текст с мягкой тенью, без плашки.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return False
    txt = " ".join(str(words or "").split()).upper()
    if not txt:
        return False
    accent = _TXT_RGB.get(str(color).lower(), _TXT_RGB["white"])
    fs = 200
    fkey = str(fkey or "default").lower()
    if fkey == "default":
        fkey = "roboto"                      # узкий гротеск вместо DejaVu
    font = _load_txt_font(fkey, fs)
    track = max(2, int(fs * 0.022))          # разрядка

    def _w(t):
        return sum(font.getlength(c) + track for c in t) - track

    tw = _w(txt)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    bb = probe.textbbox((0, 0), txt, font=font)
    th = bb[3] - bb[1]

    pad_x, pad_y = int(fs * 0.34), int(fs * 0.20)
    bar_w = int(fs * 0.075)
    shadow = int(fs * 0.10)
    style = str(style or "plate").lower()

    W_ = int(tw + pad_x * 2 + (bar_w + pad_x * 0.5 if style == "plate" else 0)) + shadow * 2
    H_ = int(th + pad_y * 2) + shadow * 2
    img = Image.new("RGBA", (max(W_, 8), max(H_, 8)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    x0, y0 = shadow, shadow
    x1, y1 = W_ - shadow, H_ - shadow
    if style in ("plate", "bar"):
        # мягкая тень под плашкой — отделяет надпись от любого кадра
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle((x0, y0 + shadow * 0.3, x1, y1 + shadow * 0.3),
                                     fill=(0, 0, 0, 150))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(shadow * 0.8)))
        d = ImageDraw.Draw(img)

    if style == "bar":
        d.rectangle((x0, y0, x1, y1), fill=accent + (248,))
        ink = (16, 16, 18, 255)
        tx = x0 + pad_x
    elif style == "bare":
        ink = (255, 255, 255, 255)
        tx = x0 + pad_x
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gx = tx
        for ch in txt:
            gd.text((gx, y0 + pad_y - bb[1]), ch, font=font, fill=(0, 0, 0, 190))
            gx += font.getlength(ch) + track
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(fs * 0.055)))
        d = ImageDraw.Draw(img)
    else:                                     # plate
        d.rectangle((x0, y0, x1, y1), fill=(12, 12, 14, 214))
        d.rectangle((x0, y0, x0 + bar_w, y1), fill=accent + (255,))
        ink = (255, 255, 255, 255)
        tx = x0 + bar_w + pad_x * 0.5 + pad_x * 0.5

    x = tx
    for ch in txt:
        d.text((x, y0 + pad_y - bb[1]), ch, font=font, fill=ink)
        x += font.getlength(ch) + track

    try:
        img.save(out_path)
        return True
    except OSError:
        return False


# КАНАЛ РОЛИКА — ЧИТАЕТСЯ В `do_overlay` ИЗ scenes.json И ЖИВЁТ ЗДЕСЬ.
# Нужен надписи из-под маски: цвет плашки приходит ПО КАНАЛУ, как у всех
# наших элементов (его слово 07.11 про ПЛАНЕТУ: «будет примерно собираться
# так же, как и на канал 5 МИНУТ»).
CHANNEL_NOW = ""


def _apply_mask_overlay(ffmpeg, ffprobe, base_mp4, out_mp4, ts, dur, sid=None):
    """НАДПИСЬ ИЗ-ПОД МАСКИ — приём, принятый им 07.11 из витрины кандидатов.

    Отличие от обычной текстовой всплывашки: это не один PNG с наплывом, а
    КОРОТКАЯ PNG-СЕКВЕНЦИЯ (0,9 с) — надпись выезжает из-под маски слева
    направо, по краю маски едет полоса. Дальше `eof_action=repeat` держит
    последний кадр до конца сцены, поэтому секвенция короткая и дешёвая.

    Вид задаётся стилем всплывашки в overlays.json:
        "style": "mask"        — без заливки (белый засечный + подзаголовок);
        "style": "mask_plate"  — с заливкой в гамме канала.
    Подзаголовок — ключ "sub" (не обязателен).
    """
    import shutil
    import tempfile
    try:
        import nadpis_maska as NM
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import nadpis_maska as NM

    head = str(ts.get("words") or ts.get("text") or "").strip().upper()
    if not head:
        return False
    sub = str(ts.get("sub") or "").strip()
    plate = str(ts.get("style", "")).lower() == "mask_plate"
    try:
        msc = max(0.4, min(2.4, float(ts.get("scale", 1.0))))
    except (TypeError, ValueError):
        msc = 1.0

    at = float(ts.get("at", LEAD))
    at = _floor_at(sid, at, dur)
    at = max(0.0, min(at, max(0.0, dur - 1.4)))
    t3 = max(at + 1.2, dur)
    t2 = max(at + 1.0, t3 - 0.35)

    pos = str(ts.get("pos", "tc")).lower()
    if pos[:1] == "b":
        print(f"  [надпись-маска] pos={pos} — НИЗ ЗАПРЕЩЁН (субтитры), "
              f"поднял в t{pos[1:] or 'c'}", flush=True)
        pos = "t" + (pos[1:] or "c")
    yk = pos[0] if pos[:1] in ("t", "m") else "t"
    xk = pos[1] if len(pos) > 1 and pos[1] in "lcr" else "c"

    tmp = tempfile.mkdtemp(prefix="maska-")
    try:
        fps = FPS
        n, tw, th = NM.sequence(tmp, head, sub, scale=2.0 * msc,
                                channel=CHANNEL_NOW, fps=fps, plate=plate)
        if tw > int(W * 0.92):          # длинная строка — ужимаем, не режем
            k = (W * 0.92) / tw
            shutil.rmtree(tmp, ignore_errors=True)
            tmp = tempfile.mkdtemp(prefix="maska-")
            n, tw, th = NM.sequence(tmp, head, sub, scale=2.0 * msc * k,
                                    channel=CHANNEL_NOW, fps=fps, plate=plate)
        mg = 60
        px = {"l": mg, "c": int((W - tw) / 2), "r": int(W - tw - mg)}[xk]
        py = {"t": mg, "m": int((H - th) / 2)}[yk]

        fc = (f"[1:v]format=rgba,"
              f"fade=t=out:st={t2:.3f}:d=0.3:alpha=1[t];"
              f"[0:v][t]overlay=x={px}:y={py}:eof_action=repeat:"
              f"enable='between(t,{at:.3f},{t3:.3f})',format=yuv420p[v]")
        tmp_mp4 = out_mp4 + ".mtmp.mp4"
        cmd = [ffmpeg, "-y", *_threads_args(), "-i", base_mp4,
               "-itsoffset", f"{at:.3f}", "-framerate", str(fps),
               "-i", os.path.join(tmp, "pl_%03d.png"),
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "veryfast",
               "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
               "-pix_fmt", "yuv420p", "-t", f"{dur:.3f}", tmp_mp4]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(tmp_mp4):
            os.replace(tmp_mp4, out_mp4)
            return True
        if os.path.exists(tmp_mp4):
            os.remove(tmp_mp4)
        print("   надпись-маска FAIL:", r.stderr[-300:])
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _apply_text_overlay(ffmpeg, ffprobe, base_mp4, out_mp4, ts, dur, sid=None):
    """Отдельная всплывашка-СЛОВО поверх клипа: сетка 9 позиций
    (pos = tl/tc/tr/ml/mc/mr/bl/bc/br), плавное появление/исчезновение,
    без рамки. `base_mp4` уже может нести фото-всплывашку — текст идёт сверху."""
    words = ts.get("words") or ts.get("text") or ""
    if not str(words).strip():
        return False
    # НАДПИСЬ ИЗ-ПОД МАСКИ — свой путь: там секвенция, а не один PNG
    if str(ts.get("style", "")).lower() in ("mask", "mask_plate"):
        return _apply_mask_overlay(ffmpeg, ffprobe, base_mp4, out_mp4, ts,
                                   dur, sid)
    try:
        msc = max(0.4, min(2.4, float(ts.get("scale", 1.0))))
    except (TypeError, ValueError):
        msc = 1.0
    at = float(ts.get("at", LEAD))
    at = _floor_at(sid, at, dur)
    at = max(0.0, min(at, max(0.0, dur - 2 * SLIDE - 0.6)))
    hold = max(0.5, dur - at - 2 * SLIDE - TAIL)
    t0, t2, t3 = at, at + SLIDE + hold, at + 2 * SLIDE + hold
    # ДЕФОЛТ НАДПИСИ — ВЕРХ, А НЕ НИЗ (28.10, прямое слово пользователя:
    # «в нижней части на 5 минут канал никогда они не должны, там идут
    # субтитры, и они друг друга перекрывают»). Было `bc` — низ по центру,
    # ровно под субтитры: на `5min-stubb-2810` все 19 надписей уехали туда,
    # потому что вкладка `pos` не указывала вовсе, а дефолт ставил низ.
    # Вкладка правила не нарушала — нарушал дефолт.
    pos = str(ts.get("pos", "tc")).lower()
    # НИЗ ЗАПРЕЩЁН ВСЕГДА: там субтитры. Нижнюю позицию поднимаем в верх с
    # тем же выравниванием по горизонтали и говорим об этом вслух.
    if pos[:1] == "b":
        print(f"  [надпись] pos={pos} — НИЗ ЗАПРЕЩЁН (субтитры), поднял в "
              f"t{pos[1:] or 'c'}", flush=True)
        pos = "t" + (pos[1:] or "c")
    yk = pos[0] if pos[:1] in ("t", "m", "b") else "b"
    xk = pos[1] if len(pos) > 1 and pos[1] in "lcr" else "c"
    png = out_mp4 + ".txt.png"
    if not _render_text_png(words, ts.get("color") or text_color_for(sid), png,
                            ts.get("font", "default"), ts.get("style", "plate")):
        return False
    pw, ph = _img_wh(ffprobe, png)
    th = max(60, min(int(H / 6 * msc), int(H * 0.5)))
    tw = min(int(th * (pw / ph if ph else 6)), int(W * 0.92))
    mg = 60
    rx = {"l": f"{mg}", "c": "(W-w)/2", "r": f"W-w-{mg}"}[xk]
    ry = {"t": f"{mg}", "m": "(H-h)/2", "b": f"H-h-{mg}"}[yk]
    # ПОЯВЛЕНИЕ МГНОВЕННОЕ (user, 20.10: «просто надпись, бабах и всё»):
    # полсекунды наплыва делали подачу вялой. Уход чуть мягче, чтобы
    # надпись не «отрубалась» на полуслове.
    f_in, f_out = 0.05, 0.16
    fc = (
        f"[1:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,format=rgba,"
        f"fade=t=in:st={t0:.3f}:d={f_in}:alpha=1,"
        f"fade=t=out:st={t2 + SLIDE - f_out:.3f}:d={f_out}:alpha=1[t];"
        f"[0:v][t]overlay=x='{rx}':y='{ry}':enable='between(t,{t0:.3f},{t3:.3f})':"
        f"eval=init,format=yuv420p[v]"
    )
    tmp = out_mp4 + ".ttmp.mp4"
    cmd = [ffmpeg, "-y", *_threads_args(), "-i", base_mp4,
           "-loop", "1", "-t", f"{dur + 1.0:.3f}", "-i", png,
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
           "-pix_fmt", "yuv420p", "-t", f"{dur:.3f}", tmp]
    r = _run_ff(cmd, sid, "текстовая всплывашка")
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


def resolve_photo(path):
    """Путь из overlays.json → реально лежащий файл.

    ПОЛЕ В JSON НЕ РАВНО ФАЙЛУ НА ДИСКЕ (2026-10-22, улов `usuario-92`;
    четвёртый случай этого класса за месяц). Карта из медиатеки приезжает с
    РОДНЫМ расширением — `overlays/scene_033.png`, — а в `overlays.json`
    вкладка пишет привычный `.jpg`. Файл есть, всплывашка пропадает молча:
    `os.path.exists` даёт False, и сборка просто не рисует её.
    Разрешаем по тому же имени с любым расширением (кроме служебного
    `.text.png`, который рисует дашборд как свой предпросмотр).
    """
    if not path:
        return ""
    if os.path.exists(path):
        return path
    stem = os.path.splitext(path)[0]
    for cand in sorted(glob.glob(stem + ".*")):
        if cand.endswith(".text.png") or cand.endswith(".json"):
            continue
        if os.path.getsize(cand) > 0:
            print(f"    всплывашка: в overlays.json указан {os.path.basename(path)}, "
                  f"а на диске лежит {os.path.basename(cand)} — беру его", flush=True)
            return cand
    return ""


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


def _caps_shard(sid):
    """Кусок субтитров для сцены, если они включены. Иначе пустая строка."""
    d = os.environ.get("CAPTIONS_DIR", "")
    if not d:
        return ""
    f = os.path.join(d, "scene_%03d.ass" % int(sid))
    return f if os.path.isfile(f) else ""


def burn_caps(ffmpeg, clip, sid):
    """СУБТИТРЫ — САМЫЙ ВЕРХНИЙ СЛОЙ (03.11, прямое слово пользователя:
    «всплывашки и вся хрень должна идти за субтитрами, чтобы субтитры шли
    впереди, самым верхним слоем, чтобы они перекрывали всё»).

    Раньше они вжигались в build_clips_1080.py, то есть ДО всплывашек, и
    фото- или текстовая всплывашка могла лечь поверх строки. Теперь вжигание
    идёт последним проходом по сцене — после фото-всплывашки и после текста.
    Цена: один лишний прогон кодирования на сцену, но он идёт на тех же 12
    машинах, что и всплывашки, и только по сценам, где субтитры есть.
    """
    f = _caps_shard(sid)
    if not f or not os.path.isfile(clip):
        return False
    esc = f.replace("\\", "/").replace(":", r"\:").replace(",", r"\,")
    fd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    vf = "ass='%s'" % esc
    if os.path.isdir(fd):
        vf = "ass='%s':fontsdir='%s'" % (
            esc, fd.replace("\\", "/").replace(":", r"\:").replace(",", r"\,"))
    tmp = clip + ".caps.mp4"
    r = subprocess.run([ffmpeg, "-y", *_threads_args(), "-i", clip,
                        "-vf", vf + ",format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
                        "-c:a", "copy", tmp], capture_output=True, text=True)
    if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 10000:
        os.replace(tmp, clip)
        print("[%03d] субтитры вжжены ПОВЕРХ всплывашек" % sid, flush=True)
        return True
    if os.path.exists(tmp):
        os.remove(tmp)
    print("[%03d] !! субтитры не вжглись: %s" % (sid, r.stderr[-200:]), flush=True)
    return False


def do_overlay(scenes_path, images_dir, clips_dir, ov_path, ffmpeg="ffmpeg"):
    ffprobe = "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1))
    ov = json.load(open(ov_path, encoding="utf-8"))
    # НА НАШ РИСОВАННЫЙ КАДР НИЧЕГО НЕ КЛАДЁМ (06.11, прямое слово
    # пользователя по дашборду: «наши элементы идут уже без дополнительных
    # спецэффектов, без надписей, без всплывашек, без всего. Если это уже наш
    # элемент — он должен быть без дополнительных деталей. Её нужно было бы
    # куда-то в другое место пиздануть»). Эффекты на карточку не ложились и
    # раньше (проверка в `card_put.py` и в приёмке), а всплывашки —
    # ложились: на сцене 4 ролика про Абу-Даби она встала поверх карточки.
    _card_sids = set()
    try:
        for _sc in json.load(open(scenes_path, encoding="utf-8"))["scenes"]:
            _k = str(_sc.get("fx", "")).strip().lower()
            if _k in FX_TRANS_SEC:
                FX_MIN_AT[int(_sc["id"])] = FX_TRANS_SEC[_k] + 0.2
            if str(_sc.get("source", "")).startswith("card"):
                _card_sids.add(int(_sc["id"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if _card_sids:
        _drop = [k for k in list(ov) if str(k).isdigit() and int(k) in _card_sids]
        for k in _drop:
            ov.pop(k, None)
        if _drop:
            print("всплывашки СНЯТЫ с рисованных кадров (сцены %s): наш элемент "
                  "идёт без всплывашек, надписей и эффектов — его слово 06.11. "
                  "Перенеси их на соседние сцены с обычным кадром."
                  % ", ".join(sorted(_drop, key=int)), flush=True)
    if FX_MIN_AT:
        print("всплывашки на сценах с переходом сдвинуты за его конец: "
              + ", ".join("%d→%.1f с" % (i, v)
                          for i, v in sorted(FX_MIN_AT.items())), flush=True)
    # vertical anchor: "top" for non-Планета channels (user, 2026-09-05),
    # "bottom" (default) for Планета. Whole-file key, sibling to the scene ids.
    # ДЕФОЛТ ЯКОРЯ — ПО КАНАЛУ, А НЕ «bottom» ВСЕГДА (04.11, улов
    # `usuario-31`). Правило «на всех каналах кроме ПЛАНЕТЫ всплывашка
    # вверху» живёт в коде с 05.09, но дефолт здесь стоял жёсткий `bottom`,
    # и `overlays.json`, собранный руками без ключа `anchor`, молча уезжал
    # с нижним якорем на 5 МИНУТ. Теперь: ключ в файле сильнее всего, а если
    # его нет — смотрим канал в scenes.json.
    _chan = ""
    try:
        _d = json.load(open(scenes_path, encoding="utf-8"))
        _chan = str(_d.get("channel", "") if isinstance(_d, dict) else "")
    except (OSError, ValueError):
        _chan = ""
    global CHANNEL_NOW
    CHANNEL_NOW = _chan
    _def_anchor = ("bottom"
                   if _chan.strip().upper().replace("Ё", "Е") == "ПЛАНЕТА"
                   or not _chan.strip() else "top")
    anchor = str(ov.get("anchor", _def_anchor)).lower()   # общий на ролик, его перебивает ключ сцены
    # НИЗ ВНЕ ПЛАНЕТЫ ЗАПРЕЩЁН ПОЛНОСТЬЮ (05.11, прямое слово пользователя:
    # «надписи ни в коем случае не выводить внизу. Или в середине, или
    # вверху. Внизу идут субтитры», «там идут комментарии»). Раньше дефолт
    # был по каналу, но ЯВНЫЙ `bottom` (старый файл, рука, чужой пресет)
    # проходил насквозь. Теперь поднимаем и говорим вслух.
    if anchor == "bottom" and _chan.strip() and \
            _chan.strip().upper().replace("Ё", "Е") != "ПЛАНЕТА":
        print("якорь `bottom` на канале «%s» ЗАПРЕЩЁН (внизу идут субтитры) "
              "— поднимаю наверх" % _chan.strip(), flush=True)
        anchor = "top"
    if "anchor" not in ov:
        print("якорь всплывашек по каналу «%s»: %s (ключа `anchor` в "
              "overlays.json нет)" % (_chan or "не указан", anchor), flush=True)
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
        if sc_anchor not in ("top", "middle", "bottom"):
            sc_anchor = anchor
        if sc_anchor == "bottom" and _chan.strip() and \
                _chan.strip().upper().replace("Ё", "Е") != "ПЛАНЕТА":
            sc_anchor = "top"      # тот же запрет, но и для ключа СЦЕНЫ
        clip = os.path.join(clips_dir, f"clip_{sid:03d}.mp4")
        orig = os.path.join(clips_dir, f"clip_{sid:03d}.orig.mp4")
        photo = resolve_photo(spec.get("photo") or "")
        photo_ok = bool(photo)
        # ВСПЛЫВАШКА МОЖЕТ БЫТЬ ВИДЕО (2026-10-21, просьба пользователя: «а
        # давай сделаем, чтобы поддерживал, будет веселее»).
        # Раньше тут видео принудительно сводилось к ОДНОМУ КАДРУ. Причина
        # была не в принципе, а в том, что путь всплывашки писался вокруг
        # неподвижной картинки: вход подавался как `-loop 1 -i photo.jpg`, и
        # видеопоток в этой конструкции ломал вызов ffmpeg целиком
        # (2026-09-14: так осиротел clip_005.mp4 и весь видеоряд уехал
        # растянутым в 21 раз — см. страховку в конце функции).
        # Теперь видео ведётся КАК ВИДЕО: вход `-stream_loop -1` (короткий
        # источник доигрывает по кругу, пока коробка на экране), выход
        # ограничен `-t` по длине клипа. Звук из всплывашки НЕ берётся —
        # маппинг `0:a?` ниже тянет дорожку только из основного клипа, то
        # есть железное правило «видеоряд немой» не нарушается.
        ov_is_video = bool(photo_ok) and photo.lower().endswith(_VID_EXT)
        if ov_is_video:
            # geq (круг/скругление) считается НА КАЖДЫЙ кадр и на видео
            # обойдётся вдвое-втрое дороже самой нарезки, поэтому форму
            # приводим к дешёвой. Маска одним статическим PNG — отдельная
            # работа, пока не делаем.
            _shape_req = (spec.get("shape") or "rect").lower()
            if _shape_req in ("circle", "rounded"):
                print(f"[{sid:03d}] видео-всплывашка: форма «{_shape_req}» пока "
                      f"только для фото, беру прямоугольник", flush=True)
                spec = dict(spec); spec["shape"] = "rect"
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
                                   orig, clip, tspec, _dur, sid):
                print(f"[{sid:03d}] ТЕКСТ «{tspec.get('words') or tspec.get('text')}» "
                      f"@ {tspec.get('at', LEAD)}s pos={tspec.get('pos','tc')} -> ok", flush=True)
            else:
                print(f"[{sid:03d}] ТЕКСТ -> FAIL", flush=True)
            # СУБТИТРЫ ВЖИГАЕМ И ЗДЕСЬ (04.11, его прямое слово, второй раз
            # за день: «если надпись есть, почему убираем субтитры? Нет,
            # субтитры должны продолжать идти на протяжении всего видео»).
            # Ветка «ТОЛЬКО ТЕКСТ» выходила по `continue` ДО общего вызова
            # `burn_caps` в конце цикла — то есть на каждой сцене, где есть
            # надпись и нет фото-всплывашки, строка не вжигалась ВООБЩЕ.
            # Отсюда и замер `usuario-75`: 22 сцены из 25 «только текст» без
            # субтитров, а все сцены с фото их сохранили (у них `continue`
            # нет). Причина не в пересборке и не в `orig`, а в одной
            # строчке выхода из цикла.
            if not os.path.exists(clip):
                shutil.copyfile(orig, clip)
            burn_caps(ffmpeg, clip, sid)
            continue
        # «секунда» с дашборда = когда всплывашка НАЧИНАЕТ въезжать (по умолчанию
        # LEAD — сразу после старта сцены). Держится до конца сцены минус TAIL.
        at = float(spec.get("at", LEAD))
        at = _floor_at(sid, at, _dur)
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
        rest_y = (f"{margin}" if sc_anchor == "top"
                  else ("(H-h)/2" if sc_anchor == "middle" else f"H-h-{margin}"))

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
        # БИТЫЙ ФАЙЛ ВСПЛЫВАШКИ ДО ffmpeg НЕ ДОПУСКАЕМ (10.11, разбор зависшего
        # шарда). На сцене 052 в `overlays/scene_052.jpg` лежала страница
        # «404 Not Found» в 161 байт — скачавший её шаг сохранил ответ сервера
        # как картинку. ffmpeg на таком входе с `-loop 1` не падает, а ВИСИТ
        # (замерено: срезан по 40 с и с входным `-t`, и без него), и один
        # такой кадр утащил всю сборку ролика.
        if not _kadr_chitaem(photo, ov_is_video):
            print(f"[{sid:03d}] всплывашка ПРОПУЩЕНА: файл не читается как "
                  f"{'видео' if ov_is_video else 'картинка'} "
                  f"({os.path.basename(photo)}, {os.path.getsize(photo) if os.path.exists(photo) else 0} б) "
                  f"— сцена останется без неё, сборка идёт дальше", flush=True)
            photo_ok = False
            tspec = spec.get("text") if isinstance(spec, dict) else None
            if tspec:
                _apply_text_overlay(ffmpeg, "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1)),
                                    orig, clip, tspec, _dur, sid)
            elif os.path.exists(orig) and not os.path.exists(clip):
                os.replace(orig, clip)
            continue
        # ВХОД ОГРАНИЧЕН ПО ВРЕМЕНИ И ДО `-i` ТОЖЕ — но это лишь подстраховка.
        # ЗАМЕРЕНО 10.11 на настоящем файле сцены 052: входной `-t` зависание
        # НЕ снимает. Если картинка битая, ffmpeg крутится в декодере, кадров
        # не выдаёт, выходного времени не набирает — и висит одинаково с `-t`
        # и без него (оба прогона срезаны по 40 с). Реально держат два других
        # рубежа: проверка файла ВЫШЕ (битый до ffmpeg не доходит) и потолок
        # времени в `_run_ff`.
        _lim = f"{_dur + 1.0:.3f}"
        _in2 = (["-stream_loop", "-1", "-t", _lim, "-i", photo] if ov_is_video
                else ["-loop", "1", "-t", _lim, "-i", photo])
        cmd = [ffmpeg, "-y", *_threads_args(), "-i", orig, *_in2,
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", os.environ.get("VIDEORYAD_CRF", "16"),
               "-pix_fmt", "yuv420p", "-t", f"{_dur:.3f}", _text_target]
        r = _run_ff(cmd, sid, "фото-всплывашка")
        ph_ok = os.path.exists(_text_target) and r.returncode == 0
        print(f"[{sid:03d}] всплывашка{' ВИДЕО' if ov_is_video else ''} @ {at}s "
              f"({os.path.basename(photo)}) -> "
              + ("ok" if ph_ok else "FAIL\n" + r.stderr[-400:]))
        # --- вторая, независимая всплывашка: СЛОВО (spec["text"]) ---------
        if tspec:
            base = _text_target if ph_ok else orig
            if _apply_text_overlay(ffmpeg, "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1)),
                                   base, clip, tspec, _dur, sid):
                print(f"[{sid:03d}] + ТЕКСТ «{tspec.get('words') or tspec.get('text')}» "
                      f"@ {tspec.get('at', LEAD)}s pos={tspec.get('pos','tc')} -> ok", flush=True)
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

        # СУБТИТРЫ ПОСЛЕДНИМИ — поверх фото-всплывашки и поверх текста
        burn_caps(ffmpeg, clip, sid)

    # СЦЕНЫ БЕЗ ВСПЛЫВАШЕК ТОЖЕ ПОЛУЧАЮТ СУБТИТРЫ (03.11). Цикл выше идёт по
    # `overlays.json`, а субтитры есть на каждой сцене, где звучит речь —
    # иначе строка пропадала бы ровно там, где всплывашки нет. Шардинг тот же,
    # чтобы машины не делали одну работу дважды.
    if os.environ.get("CAPTIONS_DIR"):
        _done = {int(k) for k in ov if str(k).isdigit()}
        for _f in sorted(glob.glob(os.path.join(os.environ["CAPTIONS_DIR"],
                                                "scene_*.ass"))):
            _m = re.search(r"scene_(\d+)\.ass$", _f)
            if not _m:
                continue
            _sid = int(_m.group(1))
            if _sid in _done:
                continue
            if wc > 1 and (_sid % wc) != wk:
                continue
            _clip = os.path.join(clips_dir, "clip_%03d.mp4" % _sid)
            if os.path.isfile(_clip):
                burn_caps(ffmpeg, _clip, _sid)


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

    # ОЗВУЧКА ВМЕШИВАЕТСЯ В СБОРКУ (03.11, прямое слово пользователя: «пускай
    # она будет в облаке… чтобы звуки всплывашек были процентов мощности, а
    # озвучка полной, стопроцентной громкости»). До этого готовый файл несёл
    # ТОЛЬКО щелчки всплывашек, а голос пользователь накладывал сам.
    # Озвучка ищется в папке ролика: `narration.mp3` либо единственный mp3/wav
    # в корне (его кладёт ship.sh под именем narration.mp3). Нет файла —
    # поведение прежнее, старые потоки не меняются.
    # Громкость: голос 1.0, щелчки 0.18 — числа держатся здесь, рядом с миксом.
    # ТИШЕ НА 40% (08.11, его прямое слово: «эти надписи, всплывашки, звуки
    # надо сделать ещё тише, прям в половину тише, 60% оставить. Слишком
    # громко, они прям по нервам бьют»). Было 0.3 при голосе и 0.9 без него;
    # берём 60% от прежнего: 0.18 и 0.54. Правится ЗДЕСЬ, в одном месте —
    # ship.sh печатает эти же числа, не задаёт их.
    SFX_VOL_WITH_VOICE, SFX_VOL_ALONE, VOICE_VOL = 0.18, 0.54, 1.0
    _voice = os.environ.get("VIDEORYAD_NARRATION") or ""
    if not _voice:
        for _c in ("narration.mp3", "narration.wav", "narration.m4a"):
            if os.path.isfile(_c):
                _voice = _c
                break
    if not _voice:
        _loose = [f for f in sorted(glob.glob("*.mp3")) + sorted(glob.glob("*.wav"))
                  if os.path.dirname(os.path.abspath(f)) == os.path.abspath(".")]
        if len(_loose) == 1:
            _voice = _loose[0]
    sfx_vol = SFX_VOL_ALONE
    if _voice and os.path.isfile(_voice):
        sfx_vol = SFX_VOL_WITH_VOICE
        inputs.extend(["-i", _voice])
        filters.append(f"[{idx[0]}:a]volume={VOICE_VOL}[voice]")
        mixn.append("[voice]")
        print("ОЗВУЧКА: %s — голос %.0f%%, щелчки всплывашек %.0f%%"
              % (_voice, VOICE_VOL * 100, sfx_vol * 100), flush=True)
        idx[0] += 1
    else:
        print("озвучки в папке нет — собираю как раньше, только щелчки "
              "(%.0f%%)" % (sfx_vol * 100), flush=True)

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
        filters.append(f"[{idx[0]}:a]adelay={pos_ms}|{pos_ms},"
                       f"volume={sfx_vol}[s{idx[0]}]")
        mixn.append(f"[s{idx[0]}]")
        print(f"[{sid:03d}] {tag}{sound} @ {pos_ms/1000:.2f}s (финальный таймлайн)")
        idx[0] += 1

    for sid_s, spec in ov.items():
        if not str(sid_s).isdigit():
            continue
        sid = int(sid_s)
        if sid not in starts:
            continue
        if resolve_photo(spec.get("photo") or ""):
            _add(sid, spec.get("sound", "whoosh"), spec.get("at", LEAD), "")
        ts = spec.get("text") if isinstance(spec.get("text"), dict) else None
        if ts and str(ts.get("words") or ts.get("text") or "").strip():
            # дефолт текстовой всплывашки — РАЗНЫЙ по сценам (2026-10-17,
            # просьба пользователя: «нужно, чтобы с разными звуками выходил»)
            _TXT_CYCLE = ("pop", "mashinka", "pshik", "zatvor", "whoosh")
            _add(sid, ts.get("sound") or _TXT_CYCLE[sid % len(_TXT_CYCLE)],
                 ts.get("at", LEAD), "ТЕКСТ ")
    if not mixn:
        print("ни озвучки, ни звуков — просто копирую видео")
        subprocess.run([ffmpeg, "-y", "-i", in_mp4, "-c", "copy", out_mp4], capture_output=True)
        return
    fc = ";".join(filters) + f";[1:a]{''.join(mixn)}amix=inputs={len(mixn)+1}:normalize=0[a]"
    cmd = [ffmpeg, "-y", *_threads_args(), "-i", in_mp4] + inputs + [
        "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 10000
    print(("готово: " + out_mp4) if ok else ("FAIL\n" + r.stderr[-800:]))


# ---------------------------------------------------------------- РЕЖИМ build
# 11.11.2026. Причина: `faza.sh posle_fetcha` звал `build_overlays.py build
# <проект>` — такого режима не было, скрипт печатал usage и возвращал НОЛЬ.
# Снаружи шаг «слои (всплывашки/надписи)» выглядел успешным, а слой не
# собирался вовсе («успех без результата», улов `usuario-fd`).
# Что делает `build`: СОБИРАЕТ `overlays.json` из того, что уже лежит в
# `overlays/` — ровно ту механику, которую вкладки делали инлайновым снипетом
# (он же автор фантомного `approved`, BRIEF-TAB «0-кварт.»). Содержание —
# какой кадр и какие слова — остаётся за вкладкой, код решает только поля.
_SND_CYCLE = ("pop", "whoosh", "ding")      # «чистый» снипет, без zatvor
_SHAPES = ("rect", "rect", "circle")
_SCALES = (1.0, 1.2, 1.0, 1.0)
_PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm")
OV_NORM = (10, 14)          # фото-всплывашек на ролик (BRIEF-TAB, 05.11)


def _scenes_file(proj):
    """Раскадровка проекта. `overlays_fetch`/`maps_fetch` — НЕ она."""
    c = [p for p in sorted(glob.glob(os.path.join(proj, "*.scenes.json")))
         if "overlays_fetch" not in os.path.basename(p)
         and "maps_fetch" not in os.path.basename(p)]
    return c[0] if c else ""


def do_build(proj="."):
    """Собрать слой всплывашек по файлам в `overlays/`. Код 1 = слоя нет."""
    proj = os.path.abspath(proj or ".")
    if not os.path.isdir(proj):
        print("нет такой папки проекта:", proj)
        return 1
    os.chdir(proj)
    sp = _scenes_file(proj)
    if not sp:
        print("в %s нет <проект>.scenes.json — собирать слой не по чему" % proj)
        return 1
    d = json.load(open(sp, encoding="utf-8"))
    scenes = d["scenes"] if isinstance(d, dict) else d
    chan = str(d.get("channel", "")).strip() if isinstance(d, dict) else ""
    planeta = chan.upper().replace("Ё", "Е") == "ПЛАНЕТА" or not chan
    def_anchor = "bottom" if planeta else "top"     # низ вне ПЛАНЕТЫ запрещён
                                                    # (только для отчёта)
    info = {}
    for sc in scenes:
        try:
            info[int(sc["id"])] = sc
        except (KeyError, ValueError, TypeError):
            continue
    cards = {i for i, sc in info.items()
             if str(sc.get("source", "")).startswith("card")}
    for i, sc in info.items():                   # переходы двигают старт
        k = str(sc.get("fx", "")).strip().lower()
        if k in FX_TRANS_SEC:
            FX_MIN_AT[i] = FX_TRANS_SEC[k] + 0.2

    ov_path = os.path.join(proj, "overlays.json")
    ov = {}
    if os.path.exists(ov_path):
        try:
            ov = json.load(open(ov_path, encoding="utf-8"))
        except ValueError as e:
            print("overlays.json битый (%s) — не трогаю его" % e)
            return 1

    # ---- что лежит в overlays/ (служебное и предпросмотр дашборда — мимо)
    found = {}
    for f in sorted(glob.glob(os.path.join(proj, "overlays", "scene_*"))):
        b = os.path.basename(f)
        if b.endswith(".text.png") or not b.lower().endswith(_PHOTO_EXT):
            continue
        try:
            sid = int(b[6:9])
        except ValueError:
            continue
        if os.path.getsize(f) > 0:
            found.setdefault(sid, os.path.join("overlays", b))

    added, skipped_card, i = [], [], 0
    for sid in sorted(found):
        if str(sid) in ov or sid in ov:
            continue                       # запись вкладки/дашборда — не трогаем
        if sid in cards:
            skipped_card.append(sid)       # на рисованном кадре слоёв не бывает
            continue
        dur = float(info.get(sid, {}).get("duration_sec") or 0) or 10.0
        at = _floor_at(sid, 2.2 + 0.2 * i, dur)
        at = min(at, max(0.6, dur - 2 * SLIDE - TAIL - 1.0))
        ov[str(sid)] = {"photo": found[sid],
                        "sound": _SND_CYCLE[i % len(_SND_CYCLE)],
                        "at": round(at, 2),
                        "shape": _SHAPES[i % len(_SHAPES)],
                        "scale": _SCALES[i % len(_SCALES)],
                        "style": _STYLES[sid % len(_STYLES)]}
        # `anchor` НЕ пишем: вертикаль считается по каналу в `do_overlay`
        # (ПЛАНЕТА — низ, остальные — верх), а посценный ключ ставит дашборд
        # кнопкой «по вертикали». Записанный здесь он только заморозил бы
        # выбор. 11.11
        added.append(sid)
        i += 1

    # ---- записи на рисованных кадрах: снимаем, решение пользователя щадим
    dropped, kept_card = [], []
    for k in [k for k in list(ov) if str(k).isdigit() and int(k) in cards]:
        if ov[k].get("dash_ok"):
            kept_card.append(int(k))
        else:
            ov.pop(k); dropped.append(int(k))

    # ---- записи без файла на диске: не удаляем, называем вслух
    nofile = [int(k) for k, v in ov.items()
              if str(k).isdigit() and isinstance(v, dict)
              and (v.get("photo") and not resolve_photo(v["photo"]))]

    if added or dropped:
        tmp = ov_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(ov, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, ov_path)

    photos = [k for k, v in ov.items() if str(k).isdigit()
              and isinstance(v, dict) and v.get("photo")]
    texts = [k for k, v in ov.items() if str(k).isdigit()
             and isinstance(v, dict) and isinstance(v.get("text"), dict)]
    print("канал: %s · сцен %d · файлов в overlays/: %d"
          % (chan or "не указан", len(info), len(found)))
    if added:
        print("ДОБАВЛЕНО записей: %d (сцены %s)"
              % (len(added), ", ".join(map(str, added))))
    if skipped_card:
        print("пропущены рисованные кадры: %s" % ", ".join(map(str, skipped_card)))
    if dropped:
        print("СНЯТЫ записи с рисованных кадров: %s" % ", ".join(map(str, dropped)))
    if kept_card:
        print("на рисованных кадрах остались УТВЕРЖДЁННЫЕ (dash_ok) записи: %s "
              "— снимать только с его слова" % ", ".join(map(str, kept_card)))
    if nofile:
        print("ЗАПИСЬ ЕСТЬ, ФАЙЛА НЕТ (всплывашка пропадёт молча): %s"
              % ", ".join(map(str, sorted(nofile))))
    print("итого в overlays.json: фото-всплывашек %d (норма %d-%d), надписей %d"
          % (len(photos), OV_NORM[0], OV_NORM[1], len(texts)))

    if not photos:
        # Слой НЕ собран. Молчать здесь нельзя — это и был дефект 11.11.
        free = [i for i in sorted(info) if i not in cards]
        plan = free[:1] + free[3::max(1, len(free) // max(1, OV_NORM[0]))]
        print("В overlays/ НЕТ НИ ОДНОГО КАДРА — слой не собран.")
        print("Положи 10-14 файлов `overlays/scene_NNN.jpg` и повтори. "
              "Ровно по ролику ложатся сцены: %s"
              % ", ".join(map(str, plan[:OV_NORM[1]])))
        return 1
    if len(photos) < OV_NORM[0]:
        print("СМОТРИ: фото-всплывашек меньше нормы — добери до %d-%d."
              % OV_NORM)
    if not planeta and not texts:
        print("СМОТРИ: канал «%s» — надписи-слова ОБЯЗАТЕЛЬНЫ (≈3 на минуту), "
              "их ставит вкладка ключом `text`." % chan)
    if planeta and not texts:
        print("СМОТРИ: на ПЛАНЕТЕ обязательна надпись из-под маски "
              "(`style: mask_plate`), норма — %d шт."
              % max(1, round(len([i for i in info if i not in cards]) / 8.5)))
    return 0


if __name__ == "__main__":
    # НЕИЗВЕСТНЫЙ РЕЖИМ = КОД 1 (11.11.2026). Раньше любое чужое слово
    # печатало справку и отвечало НОЛЬ — вызывающая фаза считала шаг
    # выполненным. Молчаливый успех здесь запрещён.
    _MODES = "build | overlay | sfx"
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "build":
        sys.exit(do_build(sys.argv[2] if len(sys.argv) > 2 else "."))
    elif mode == "overlay":
        if len(sys.argv) < 6:
            print("build_overlays.py overlay <scenes.json> <images-dir> "
                  "<clips-dir> <overlays.json>")
            sys.exit(1)
        do_overlay(*sys.argv[2:6])
    elif mode == "sfx":
        if len(sys.argv) < 7:
            print("build_overlays.py sfx <scenes.json> <overlays.json> "
                  "<sfx-dir> <in.mp4> <out.mp4> [stretch-factor]")
            sys.exit(1)
        do_sfx(*sys.argv[2:])
    else:
        print(__doc__)
        print("НЕИЗВЕСТНЫЙ РЕЖИМ %r. Есть только: %s" % (mode, _MODES))
        sys.exit(1)
