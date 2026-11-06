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
# НАСКОЛЬКО КРУПНО СТАВИТЬ УЗКИЙ КАДР В РАМКУ 16:9 (2026-10-31, прямое слово
# пользователя, с руганью). Правило 30.10 говорило «родной размер по центру,
# поля — размытая копия», и это дало беду: превью телеграма 800x450 занимало
# 42% ширины и 42% высоты экрана, вокруг — размытое поле. Его слова: «Почему
# фотографии такие маленькие, в центре? Это что, под микроскопом люди будут её
# смотреть? Чуть-чуть больше, чтобы рассмотреть можно было, что там. А то она
# такая же, как всплывашка. Ну и нахер она всралась тогда? А вокруг всё
# размытое».
# Поэтому кадр теперь ВПИСЫВАЕТСЯ в рамку: занимает FILL_K по той стороне,
# которая упирается первой, с мягким ограничением апскейла (выше MAX_UP
# картинка начинает мылиться, и смысла в этом нет). Заливка полей остаётся —
# просто поля становятся узкими, а не половиной экрана.
# Вертикальный кадр при этом по-прежнему уменьшается до высоты рамки: для него
# множитель выходит меньше единицы, и это правильно.
FILL_K = 0.88
MAX_UP = 2.2
# Во сколько раз допустимо растянуть кадр, чтобы накрыть рамку целиком.
# Выше этого — мыло, и кадр идёт с размытой заливкой полей (01.11).
MAX_COVER_UP = 1.35


def video_fit_mode(vw, vh, sid):
    """Как ставить ВИДЕО в рамку 16:9: ("fill"|"cover", ширина, высота).

    `fill` — кадр как есть по центру, поля — размытая притемнённая копия;
    `cover` — кадр накрывает рамку целиком (лёгкий апскейл допустим).

    Два повода уйти в `fill`:
      · пропорция не 16:9 (узкое, вертикальное, срезанный знак) — с 30.10;
      · ВЛОЖЕНИЕ ТЕЛЕГРАМА, которому нужен апскейл больше MAX_COVER_UP
        (05.11, прямое решение пользователя «и видео из Telegram так же»).
        Пропорция у вложения обычно родная (848x464 — это 1,83), поэтому
        прежняя ветка по пропорции его НЕ ловила: ffmpeg растягивал кадр во
        весь экран в 2,26 раза, и это то самое мыло, из-за которого вложения
        считались негодными в сцену.
    Вынесено отдельной функцией, чтобы решение проверялось без ffmpeg.
    """
    ratio = (vw / float(vh)) if vh else (W / float(H))
    cover = max(W / float(vw), H / float(vh)) if (vw and vh) else 1.0
    # Ниже 720p по высоте — ровно то, что прежний гейт фетчера ОТКЛОНЯЛ, то
    # есть прибавка, а не переделка: 720p и выше по-прежнему накрывают рамку
    # целиком, как накрывали, и ни одна уже собранная сцена не меняется.
    tg_lowres = ((sid in DIRECT_SIDS) and vh and vh < 700
                 and cover > MAX_COVER_UP)
    if ratio < 1.70 or tg_lowres:
        fw, fh = _fit_box(vw, vh, W, H)
        return "fill", fw, fh
    return "cover", W, H


def _fit_box(w, h, W, H):
    """(ширина, высота) переднего кадра: вписать в FILL_K рамки, не мылить."""
    if not w or not h:
        return min(w or W, W), min(h or H, H)
    f = min(W * FILL_K / float(w), H * FILL_K / float(h))
    f = min(f, MAX_UP)
    return max(2, int(round(w * f)) // 2 * 2), max(2, int(round(h * f)) // 2 * 2)


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

# Сцены, кадр которых приехал ГОТОВЫМ АДРЕСОМ из досье (source «direct_url» —
# вложение телеграм-поста). Для них порог сцены 800 px по длинной стороне, и
# мелкое видео ставится РОДНЫМ размером с размытой заливкой полей, а не
# растягивается во весь экран (05.11, прямое решение пользователя: «и видео
# из Telegram так же»). Набор заполняется в main() из scenes.json.
DIRECT_SIDS = set()


# ЭФФЕКТ №3 «ВРЕЗКА + КРУГИ-РАДАР + ПЛАВНЫЙ ЗУМ» В ШТАТНОЙ СБОРКЕ (04.11).
# 03.11 пользователь принял эффект словами «шикарно, этот оставляем так, как
# есть, и в работу его завтра», но инструмент работал ОТДЕЛЬНОЙ командой по
# готовому кадру — то есть вручную и уже после сборки. Теперь он живёт на
# этапе clips, где кадр сцены ещё отдельный файл: сцена помечается ключом
#     "fx": "inset"
# а видео-врезка лежит в проекте как `insets/scene_NNN.mp4` (кладёт её
# `template/fx_put.py`, в облако везёт `ship.sh`).
#
# ТРИ ЕГО ГРАНИЦЫ ПРОВЕРЯЮТСЯ ЗДЕСЬ, А НЕ ТОЛЬКО В ПРИЁМКЕ:
#   * канал ТОЛЬКО ПЛАНЕТА (берётся из поля `channel` самого scenes.json);
#   * НЕ БОЛЬШЕ ТРЁХ сцен на ролик — лишние идут обычным кадром;
#   * глитча нет и не добавляем, круги — независимый слой.
# Ограничения считаются по ПОЛНОМУ списку сцен, а не по шарду: каждый из 12
# раннеров читает один и тот же scenes.json, поэтому «первые три» у всех
# совпадают и ролик не меняет вид от прогона к прогону.
#
# ОТКАЗ ЭФФЕКТА НЕ ВАЛИТ СЦЕНУ: нет файла врезки, не тот канал, упал ffmpeg —
# печатается причина и кадр собирается ОБЫЧНЫМ путём. Пустых сцен из-за
# украшения не бывает.
HERE = os.path.dirname(os.path.abspath(__file__))
# ЧЕТЫРЕ ВИДА ЭФФЕКТА ИЗ ЕГО ОБРАЗЦА. `inset` — принятый 03.11 («врезка +
# круги-радар»), остальные три — переходы между сценами, разобранные 04.11 по
# тому же файлу `Эффекты-1.mp4`: мозаика плиток, разлёт вертикальных панелей,
# диагональный вайп со светлой линией.
# ПОТОЛОК ТРИ — НА ВСЕ ЭФФЕКТЫ ВМЕСТЕ, А НЕ НА КАЖДЫЙ ВИД: его слово звучало
# «эффекты не больше 3 раз на видеоряд», то есть считается ролик целиком.
# `subscribe` — не переход и не врезка: кнопка ложится ПОВЕРХ уже
# собранного клипа сцены (его заказ 05.11). Поэтому она есть в FX_KINDS
# (чтобы попасть в разбор и в потолок), но нет в FX_TRANS.
# Шесть приёмов канала «5 МИНУТ» (06.11) рисует ДРУГОЙ модуль — `fx_trans5.py`.
# Принятые приёмы ПЛАНЕТЫ в нём не трогаются вовсе, регрессии невозможны.
FX_FIVE = ("player", "curl", "slides", "stamps", "torn", "filmwin")
FX_KINDS = ("inset", "mosaic", "panels", "wipe", "depth", "tear", "flash",
            "subscribe", "subscribe2") + FX_FIVE
FX_TRANS = ("mosaic", "panels", "wipe", "depth", "tear", "flash") + FX_FIVE
FX_MAX = 3
FX_OF = {}                  # sid -> вид эффекта (уже с потолком и каналом)
INSET_SIDS = set()          # из них те, что «врезка» (для совместимости)
CHANNEL = ""


def _inset_src(sid):
    return os.path.join(_fx_dir(), "insets", f"scene_{sid:03d}.mp4")


def build_inset_clip(ffmpeg, src, out_path, duration, sid):
    """Кадр сцены + врезка + круги. True — собрал, False — зови обычный путь."""
    inset = _inset_src(sid)
    if not os.path.isfile(inset):
        print(f"  !! эффект-врезка: нет файла {inset} — собираю обычный кадр",
              flush=True)
        return False
    cmd = [sys.executable, os.path.join(HERE, "fx_inset.py"), src, inset,
           out_path, "--seconds", f"{float(duration):.3f}",
           "--channel", CHANNEL or "ПЛАНЕТА", "--ffmpeg", ffmpeg]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    if ok:
        print(f"  эффект-врезка ПОСТАВЛЕН ({os.path.getsize(out_path)//1024} КБ)",
              flush=True)
        return True
    if os.path.isfile(out_path):
        os.remove(out_path)
    print("  !! эффект-врезка НЕ ВСТАЛ, собираю обычный кадр: "
          + ((r.stdout or "") + (r.stderr or ""))[-400:].replace("\n", " "),
          flush=True)
    return False


def build_trans_clip(ffmpeg, ffprobe, src, out_path, duration, sid, kind,
                     images_dir):
    """Клип сцены с переходом в голове. True — собрал, False — обычный путь."""
    if src.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
        print("  !! переход «%s»: сцена на ВИДЕО — переход кладём только на "
              "фотокадр, собираю обычный клип" % kind, flush=True)
        return False
    prev_src, prev_ext = find_source(images_dir, sid - 1)
    prev = prev_src or "-"
    tmpf = ""
    if prev_src and prev_ext in ("mp4", "mov"):
        # у прошлой сцены видео — берём из него один кадр, иначе переходу
        # не с чего уезжать (и он молча поехал бы с чёрного)
        tmpf = os.path.join(os.path.dirname(out_path), f".prev_{sid:03d}.jpg")
        r = subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", "1", "-i",
                            prev_src, "-frames:v", "1", tmpf],
                           capture_output=True, text=True)
        prev = tmpf if (r.returncode == 0 and os.path.isfile(tmpf)) else "-"
    mod = "fx_trans5.py" if kind in FX_FIVE else "fx_trans.py"
    cmd = [sys.executable, os.path.join(HERE, mod), prev, src,
           out_path, "--kind", kind, "--seconds", f"{float(duration):.3f}",
           "--channel", CHANNEL or "ПЛАНЕТА", "--ffmpeg", ffmpeg]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if tmpf and os.path.isfile(tmpf):
        os.remove(tmpf)
    ok = r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    if ok:
        print("  переход «%s» ПОСТАВЛЕН%s (%d КБ)"
              % (kind, "" if prev != "-" else ", с чёрного (кадра прошлой сцены нет)",
                 os.path.getsize(out_path) // 1024), flush=True)
        return True
    if os.path.isfile(out_path):
        os.remove(out_path)
    print("  !! переход «%s» НЕ ВСТАЛ, собираю обычный кадр: %s"
          % (kind, ((r.stdout or "") + (r.stderr or ""))[-400:].replace("\n", " ")),
          flush=True)
    return False


def _sub_corner(sid):
    """Угол кнопки для этой сцены: правый, левый, правый — по порядку в ролике.

    Считается от ПОЛНОГО списка кнопок ролика, а не от шарда: каждый из 12
    раннеров читает один и тот же scenes.json, поэтому очередь у всех
    совпадает и ролик не меняет вид от прогона к прогону.
    """
    order = sorted(i for i, k in FX_OF.items()
                   if k in ("subscribe", "subscribe2"))
    try:
        return "right" if order.index(int(sid)) % 2 == 0 else "left"
    except ValueError:
        return "right"


def build_subscribe_clip(ffmpeg, out_path, sid):
    """Кнопка «подпишись» поверх УЖЕ СОБРАННОГО клипа сцены.

    Отдельным проходом, а не внутри сборки кадра: кнопка одинаково ложится и
    на фото-сцену, и на видео-сцену, и на сцену с переходом — ей всё равно,
    чем кадр был до неё. Не встала — клип остаётся как был, сцена не теряется.
    """
    tmp = out_path + ".sub.mp4"
    tool = ("fx_subscribe2.py" if FX_OF.get(sid) == "subscribe2"
            else "fx_subscribe.py")
    cmd = [sys.executable, os.path.join(HERE, tool),
           out_path, tmp, "--at", "0.3", "--ffmpeg", ffmpeg,
           "--corner", _sub_corner(sid)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = (r.returncode == 0 and os.path.isfile(tmp)
          and os.path.getsize(tmp) > 0)
    if ok:
        os.replace(tmp, out_path)
        print("  кнопка «подпишись» ПОСТАВЛЕНА", flush=True)
        return True
    if os.path.isfile(tmp):
        os.remove(tmp)
    print("  !! кнопка «подпишись» НЕ ВСТАЛА, клип без неё: "
          + ((r.stdout or "") + (r.stderr or ""))[-400:].replace("\n", " "),
          flush=True)
    return False


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
    # ЗАЛИВКА ПОЛЕЙ — ТОЛЬКО ДЛЯ ТЕХ, КТО НА ПОЛНЫЙ ЭКРАН НЕ ТЯНЕТ (01.11,
    # прямое слово пользователя со скриншотом: «зачем начал делать так
    # картинки высокого качества? Почему их не делать на полный экран? Мы
    # договаривались так делать с теми, что не вмещается в экран, точнее
    # маленьких размеров, плохого качества»). Порог стоял по АБСОЛЮТНОМУ
    # размеру (ширина < 1600 или высота < 900) и ловил нормальные снимки:
    # 1500x1000 при кадре 1920x1080 это апскейл всего 1,28× — мыла нет,
    # такой кадр обязан идти на полный экран. Теперь решает НЕ размер, а
    # НЕОБХОДИМЫЙ АПСКЕЙЛ: сколько нужно, чтобы накрыть кадр целиком.
    # До 1,35× — полный экран; больше — родной размер по центру и размытая
    # копия по полям. Телеграмные превью 800 px (2,4×) и прочая мелочь, ради
    # которой правило и писалось, по-прежнему идут с заливкой.
    _cover = max(W / float(w), H / float(h)) if (w and h) else 1.0
    narrow = (not portrait) and _cover > MAX_COVER_UP
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
            # Наезд ТОЛЬКО внутрь и мягкий.
            z = "min(zoom+0.00025,1.06)"
            # Коробка переднего плана — вписанная в рамку, не родной размер:
            # см. `_fit_box` выше. Пропорции сохраняет сам ffmpeg (decrease).
            fgw, fgh = _fit_box(w, h, W, H)
            print("  узкий кадр %dx%d → %dx%d (%.2f× рамки по ширине), "
                  "поля — размытая копия" % (w, h, fgw, fgh, fgw / float(W)),
                  flush=True)
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
           "-c:v", "libx264", "-preset", "veryfast", "-crf", os.environ.get("VIDEORYAD_CRF", "16"), "-pix_fmt", "yuv420p", out_path]
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
    # СУБТИТРЫ БОЛЬШЕ НЕ ЖГУТСЯ ЗДЕСЬ (03.11, прямое слово пользователя:
    # «субтитры должны идти впереди, самым верхним слоем, перекрывать всё»).
    # Клип кодируется ДО всплывашек, поэтому строка, вожжённая тут, уезжала
    # ПОД фото- и текстовую всплывашку. Теперь её жжёт `build_overlays.py`
    # последним проходом по сцене (функция `burn_caps`), на тех же 12
    # машинах. Переменная оставлена: если её всё же выставить для клипов —
    # сработает прежнее поведение, но по умолчанию оно выключено.
    if os.environ.get("CAPTIONS_IN_CLIPS") != "1":
        return ""
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
    _mode, _fw, _fh = video_fit_mode(_vw, _vh, int(_m.group(1)) if _m else -1)
    if _mode == "fill":
        print("  видео %dx%d → %dx%d (%.2f× рамки по ширине), поля — размытая "
              "копия%s" % (_vw, _vh, _fw, _fh, _fw / float(W),
                           "; вложение досье" if (_m and int(_m.group(1))
                                                  in DIRECT_SIDS) else ""),
              flush=True)
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
           "-c:v", "libx264", "-preset", "veryfast", "-crf", os.environ.get("VIDEORYAD_CRF", "16"), "-pix_fmt", "yuv420p", "-an", out_path]
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
    DIRECT_SIDS.update(s["id"] for s in data["scenes"]
                       if str(s.get("source", "")) == "direct_url")
    if DIRECT_SIDS:
        print("вложения досье (мелкое видео — родным размером с заливкой "
              "полей): " + ", ".join(str(i) for i in sorted(DIRECT_SIDS)))
    if CARD_SIDS:
        print("карточки арсенала (без эффектов): "
              + ", ".join(str(i) for i in sorted(CARD_SIDS)))

    # --- эффекты: кому они разрешены в этом ролике ---
    global CHANNEL
    CHANNEL = str(data.get("channel", "") or "")
    _want = sorted((sc["id"], str(sc.get("fx", "")).strip().lower())
                   for sc in data["scenes"]
                   if str(sc.get("fx", "")).strip().lower() in FX_KINDS)
    if _want:
        # У КАЖДОГО КАНАЛА СВОЙ НАБОР ВИДОВ (05.11): кнопка вида 2 —
        # «5 МИНУТ», всё остальное — ПЛАНЕТА.
        _ch = CHANNEL.strip().upper().replace("Ё", "Е")
        # ТАБЛИЦА КАНАЛОВ БЕРЁТСЯ ИЗ `fx_put.py`, А НЕ ПЕРЕПИСЫВАЕТСЯ ЗДЕСЬ
        # (06.11). Копия ниже — только запасная, на случай, если модуль не
        # поднялся. Живой случай того же дня: шесть приёмов канала «5 МИНУТ»
        # были вписаны в `fx_put.CHANNEL_FX`, а здешняя копия про них не
        # знала и выдавала им дефолт «ПЛАНЕТА» — на «5 МИНУТ» все шесть
        # молча отбрасывались, сборка проходила «успешно», и в готовом файле
        # не было ни одного приёма. Ровно та же мина уже жила в
        # `accept_scenes.py` и была там вылечена так же.
        _allow = {"subscribe2": ("5 МИНУТ",),
                  # кнопка вида 1 — на всех каналах, кроме «5 МИНУТ» (06.11)
                  "subscribe": ("ПЛАНЕТА", "ОЛЬКА", "ДИПЛОМАТИЯ СИЛЫ",
                                "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО", "РЕЗЕРВ"),
                  # засвет (A73, 06.11) — на всех каналах, см. fx_put.py
                  "flash": ("ПЛАНЕТА", "5 МИНУТ", "ОЛЬКА",
                            "ДИПЛОМАТИЯ СИЛЫ", "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО")}
        try:
            sys.path.insert(0, HERE)
            import fx_put as _fxp
            _allow = dict(_fxp.CHANNEL_FX)
        except Exception as _e:
            print("  !! таблицу каналов беру запасную (%s)" % _e)
        _want = [(i, k) for i, k in _want
                 if _ch in tuple(x.upper().replace("Ё", "Е")
                                 for x in _allow.get(k, ("ПЛАНЕТА",)))]
        _plan = bool(_want)
        if not _plan:
            print("эффекты: канал «%s» — НЕ ставлю (его слово 03.11: только "
                  "ПЛАНЕТА). Сцены %s пойдут обычным кадром"
                  % (CHANNEL, ", ".join(str(i) for i, _ in _want)))
        else:
            # ПОТОЛОК СЧИТАЕТСЯ ПО ВИДУ (04.11, его уточнение): три
            # `mosaic` + три `panels` + три `wipe` + три `inset` законны.
            _seen = {}
            for sid_, kind_ in _want:
                _seen.setdefault(kind_, 0)
                if _seen[kind_] >= FX_MAX:
                    continue
                _seen[kind_] += 1
                FX_OF[sid_] = kind_
                if kind_ == "inset":
                    INSET_SIDS.add(sid_)
            print("эффекты: " + ", ".join("сцена %d — %s" % (i, k)
                                          for i, k in sorted(FX_OF.items()))
                  + " (потолок %d на КАЖДЫЙ вид)" % FX_MAX)
            _extra = [(i, k) for i, k in _want if i not in FX_OF]
            if _extra:
                print("  сверх потолка своего вида и БЕЗ эффекта: "
                      + ", ".join("%d (%s)" % (i, k) for i, k in _extra))

    _wc = int(os.environ.get("WORKER_COUNT", "1"))
    _wk = int(os.environ.get("WORKER_ID", "0"))
    concat_lines = []
    for scene in data["scenes"]:
        sid, duration = scene["id"], scene["duration_sec"]
        out_path = os.path.join(clips_dir, f"clip_{sid:03d}.mp4")
        if _wc > 1 and (sid % _wc) != _wk:
            continue
        if not os.path.exists(out_path):
            # СТАРЫЙ `.orig.mp4` ПОСЛЕ ПЕРЕСБОРКИ — ЯД (04.11, улов
            # `usuario-75`, разбор по пикселям: субтитры пропали на 22 сценах
            # из 73). `build_overlays` хранит чистый клип как
            # `clip_NNN.orig.mp4` и при повторном прогоне берёт базу ИЗ НЕГО.
            # Если клип пересобран (новый кадр, новые субтитры), прошлый
            # `orig` — это кадр ДО субтитров, и текстовая всплывашка
            # затирает ими вожжённую строку. Фото-ветка идёт через
            # `.p.mp4` и не страдает, поэтому дефект бил ТОЛЬКО сцены с
            # «только текстом» и ТОЛЬКО со второй сборки одного имени.
            # Раз клип делается заново — всё производное от прежнего клипа
            # недействительно.
            for _stale in (out_path.replace(".mp4", ".orig.mp4"),
                           out_path + ".p.mp4"):
                if os.path.exists(_stale):
                    os.remove(_stale)
                    print(f"  убран устаревший {os.path.basename(_stale)} "
                          f"(клип пересобран)", flush=True)
            src, ext = find_source(images_dir, sid)
            if not src:
                print(f"[{sid:03d}] MISSING SOURCE, skip")
                continue
            print(f"[{sid:03d}] {'video' if ext=='mp4' else 'image'} -> {duration}s")
            try:
                _kind = FX_OF.get(sid, "")
                if _kind == "inset" and build_inset_clip(
                        ffmpeg, src, out_path, duration, sid):
                    pass
                elif _kind in FX_TRANS and build_trans_clip(
                        ffmpeg, ffprobe, src, out_path, duration, sid, _kind,
                        images_dir):
                    pass
                elif ext == "mp4":
                    build_video_clip(ffmpeg, ffprobe, src, out_path, duration)
                else:
                    build_image_clip(ffmpeg, src, out_path, duration, ffprobe)
                if _kind in ("subscribe", "subscribe2") \
                        and os.path.exists(out_path):
                    build_subscribe_clip(ffmpeg, out_path, sid)
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
