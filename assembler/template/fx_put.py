#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ДВЕРЬ ЭФФЕКТОВ: поставить сцене эффект из его образца.

    python3 fx_put.py <ролик>.scenes.json <sid> <видео-врезка.mp4>   # врезка
    python3 fx_put.py <ролик>.scenes.json <sid> --kind mosaic        # переход
    python3 fx_put.py <ролик>.scenes.json <sid> --off                # снять

ЧЕТЫРЕ ВИДА (все из `D:\ЗАГРУЗКИ\Эффекты-1\Эффекты-1.mp4`):
    inset   врезка в рамке + круги-радар + плавный зум (принят 03.11);
            ТРЕБУЕТ видео-врезку аргументом;
    mosaic  кадр рассыпается на плитки, из плиток собирается следующий;
    panels  новый кадр разворачивается вертикальными панелями;
    wipe    новый кадр въезжает по диагонали со светлой линией на стыке;
    depth   новый кадр выходит из глубины плитой, прошлый теряет резкость
            (наш пятый вид, 05.11 — в его образце такого нет);
    tear    прошлый кадр рвётся на семь кусков и уносится за край, под ним
            остаётся новый (перенос его принятого элемента 21.10).
Три последних — ПЕРЕХОДЫ: они начинаются с кадра ПРОШЛОЙ сцены, поэтому
ставятся только на сцену-фотографию и только начиная со второй.

Что делает: кладёт врезку в `insets/scene_NNN.mp4` рядом с scenes.json и
ставит сцене ключ `"fx": "inset"`. Дальше ВСЁ САМО: `ship.sh` везёт папку
`insets/` в облако, шаг clips собирает такую сцену через `fx_inset.py`
(кадр сцены с плавным покадровым зумом + врезка в рамке + независимый слой
кругов), всплывашки и субтитры ложатся поверх обычным порядком.

ГРАНИЦЫ ПОЛЬЗОВАТЕЛЯ (03.11, дословно «шикарно, этот оставляем так, как есть,
и в работу его завтра»), проверяются здесь и ещё раз в сборке:
  * ТОЛЬКО канал ПЛАНЕТА — на другом инструмент откажет;
  * НЕ БОЛЬШЕ ТРЁХ сцен на ролик — НА ВСЕ ВИДЫ ВМЕСТЕ («эффекты не больше
    3 раз на видеоряд»), а не по три каждого;
  * глитча в эффекте нет и не добавляем; круги кадр не трогают.

ПОЧЕМУ ВРЕЗКА ПЕРЕЖИМАЕТСЯ ЗДЕСЬ, А НЕ В ОБЛАКЕ: в самом эффекте она
масштабируется до 620x349, то есть библиотечный клип на 60-160 МБ везти в
GitHub незачем (а тот рубит файлы >100 МБ). Жмём только когда это нужно —
длиннее сцены, шире 1280 или тяжелее 8 МБ; иначе файл просто копируется.
"""
import argparse
import glob
import json
import os
import random
import shutil
import subprocess
import sys

MAX_MB = 8.0
MAX_W = 1280
KINDS = ("inset", "mosaic", "panels", "wipe", "depth", "tear",
         "subscribe")
TRANS = ("mosaic", "panels", "wipe", "depth", "tear")
# В АВТОМАТИЧЕСКУЮ РОТАЦИЮ ВИД ПОПАДАЕТ ТОЛЬКО ПОСЛЕ ЕГО «БЕРЁМ» (05.11).
# Новый эффект ставится руками и показывается ему готовым mp4; до этого
# `--auto` его не расставляет, иначе непринятый приём молча уедет в боевые
# ролики — а принятое у нас приравнено к сданному и назад не отыгрывается.
# 05.11, его слово по показу `54_ПЯТЫЙ-ЭФФЕКТ-кадр-из-глубины.mp4`:
# «пускай внедряет это на планету, это всё на планету» — вид ПРИНЯТ и
# с этой минуты идёт в автоматическую ротацию наравне с тремя первыми.
# 05.11, его слово по показу `55_ШЕСТОЙ-ЭФФЕКТ-разрыв-на-куски.mp4`:
# «да, берём, ставь в ротацию планеты так же самое, три раза этот
# эффект, и все эффекты, которые у нас есть, три раза на видеоряд».
AUTO_TRANS = ("mosaic", "panels", "wipe", "depth", "tear")
# ПОТОЛОК ТРИ — НА КАЖДЫЙ ВИД, А НЕ НА ВЕСЬ РОЛИК (04.11, его прямое слово
# после первого боевого ролика: «не больше 3 раз ОДНОГО эффекта на всём
# протяжении видео… пока этих эффектов мало, пусть будет 3 раза»).
# Утром правило читали наоборот — как три штуки на все виды вместе, — и он
# увидел в ролике по одному разу каждого и сказал, что этого мало.
FX_MAX = 3          # на каждый ВИД


def _probe(ffprobe, src):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", src],
                       capture_output=True, text=True)
    vals = [x for x in r.stdout.split() if x]
    try:
        w, h = int(vals[0]), int(vals[1])
    except Exception:
        w = h = 0
    try:
        dur = float(vals[2])
    except Exception:
        dur = 0.0
    return w, h, dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenes")
    ap.add_argument("sid", type=int, nargs="?", default=None)
    ap.add_argument("video", nargs="?", default="")
    ap.add_argument("--auto", action="store_true",
                    help="расставить три перехода по ролику самому (ПЛАНЕТА)")
    ap.add_argument("--images", default="",
                    help="папка кадров; по умолчанию images/ рядом со сценами")
    ap.add_argument("--kind", default="", choices=("",) + KINDS,
                    help="вид эффекта; по умолчанию inset, если дано видео")
    ap.add_argument("--off", action="store_true", help="снять эффект со сцены")
    ap.add_argument("--ffmpeg", default="")
    a = ap.parse_args()

    kind = a.kind or ("inset" if a.video else "")
    if a.auto:
        kind = kind or "auto"
    if not a.off and not kind:
        return _die("скажи, какой эффект: inset|mosaic|panels|wipe|depth|tear "
                    "(для inset дай ещё путь к видео-врезке)")
    if not a.off and kind == "inset" and not a.video:
        return _die("врезке нужен путь к видео (`inset` — это окно с видео "
                    "в рамке)")
    if not a.off and kind in TRANS and a.video:
        return _die("«%s» — это ПЕРЕХОД, видео ему не нужно: он уезжает с "
                    "кадра прошлой сцены на свой" % kind)
    try:
        data = json.load(open(a.scenes, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _die("не прочитать %s: %s" % (a.scenes, e))
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not scenes:
        return _die("в файле нет сцен")

    chan = str((data or {}).get("channel", "") or "") if isinstance(data, dict) else ""
    if not a.off and chan.strip().upper().replace("Ё", "Е") != "ПЛАНЕТА":
        return _die("канал «%s» — эффект ТОЛЬКО на ПЛАНЕТЕ (его слово 03.11)"
                    % (chan or "не указан в scenes.json"))

    if a.auto:
        return _auto(a, data, scenes)
    if a.sid is None:
        return _die("скажи номер сцены — или поставь --auto, и я расставлю "
                    "три перехода по ролику сам")

    sc = next((s for s in scenes if int(s.get("id", -1)) == a.sid), None)
    if sc is None:
        return _die("сцены %d в файле нет" % a.sid)

    proj = os.path.dirname(os.path.abspath(a.scenes))
    dst = os.path.join(proj, "insets", "scene_%03d.mp4" % a.sid)

    if a.off:
        sc.pop("fx", None)
        if os.path.isfile(dst):
            os.remove(dst)
        _save(a.scenes, data)
        print("сцена %d: эффект снят" % a.sid)
        return 0

    if str(sc.get("source", "")).startswith("card"):
        return _die("сцена %d — рисованная карточка (%s), эффект на наш "
                    "нарисованный кадр не кладём" % (a.sid, sc.get("source")))

    have = sorted(s["id"] for s in scenes
                  if str(s.get("fx", "")).strip().lower() in KINDS)
    same = sorted(s["id"] for s in scenes
                  if str(s.get("fx", "")).strip().lower() == kind)
    if a.sid not in same and len(same) >= FX_MAX:
        return _die("вида «%s» на ролике уже %d (сцены %s) — потолок его "
                    "словом ТРИ НА КАЖДЫЙ ВИД, четвёртый не ставлю"
                    % (kind, len(same), ", ".join(str(i) for i in same)))

    if kind == "subscribe":
        # КНОПКА — НЕ ПЕРЕХОД: ей не нужен ни кадр прошлой сцены, ни файл.
        # Нужна только длина: вся анимация идёт 3,4 с плюс запас, на короткой
        # сцене она не успела бы дойти до «вы подписаны» и обрезалась бы
        # на полужесте.
        dur = float(sc.get("duration_sec") or 0)
        if dur < 4.5:
            return _die("сцена %d всего %.1f с — кнопке «подпишись» нужно "
                        "не меньше 4,5 с (сама анимация 3,4 с)" % (a.sid, dur))
        sc["fx"] = "subscribe"
        if os.path.isfile(dst):
            os.remove(dst)
        _save(a.scenes, data)
        print("сцена %d (%.1f с): кнопка «ПОДПИШИСЬ» ПОСТАВЛЕНА "
              "(угол выберет сборка: правый, левый, правый)" % (a.sid, dur))
        print("кнопок в ролике: %d из %d" % (len(set(same) | {a.sid}), FX_MAX))
        print("файлов не нужно: кадры кнопки рисует облако само")
        return 0

    if kind in TRANS:
        # Переход уезжает с кадра ПРОШЛОЙ сцены: на первой сцене ему не с
        # чего начинать, и он молча поехал бы с чёрного.
        if a.sid <= min(int(s.get("id", 0)) for s in scenes):
            return _die("«%s» — переход с прошлой сцены, на первой сцене "
                        "ролика его ставить не с чего" % kind)
        dur = float(sc.get("duration_sec") or 0)
        if dur < 2.5:
            return _die("сцена %d всего %.1f с — переходу «%s» нужно не "
                        "меньше 2,5 с" % (a.sid, dur, kind))
        sc["fx"] = kind
        # Сцена могла быть врезкой — тогда её файл больше не нужен и в облако
        # поедет мёртвым грузом (а `ship.sh` честно отчитается о врезке,
        # которой в сборке не будет).
        if os.path.isfile(dst):
            os.remove(dst)
            print("прежняя врезка этой сцены удалена — переходу она не нужна")
        _save(a.scenes, data)
        have = sorted(set(have) | {a.sid})
        print("сцена %d (%.1f с): переход «%s» ПОСТАВЛЕН" % (a.sid, dur, kind))
        print("вида «%s» в ролике: %d из %d; эффектов всего %d"
              % (kind, len(set(same) | {a.sid}), FX_MAX,
                 len(set(have) | {a.sid})))
        print("файлов не нужно: кадр прошлой сцены облако возьмёт само")
        return 0

    if not os.path.isfile(a.video):
        return _die("нет файла врезки: %s" % a.video)

    ffmpeg = a.ffmpeg or shutil.which("ffmpeg") or os.path.expanduser("~/.local/bin/ffmpeg")
    ffprobe = "ffprobe".join(ffmpeg.rsplit("ffmpeg", 1))
    dur = float(sc.get("duration_sec") or 10.0)
    w, h, vdur = _probe(ffprobe, a.video)
    mb = os.path.getsize(a.video) / 1048576.0
    need = (mb > MAX_MB) or (w > MAX_W) or (vdur > dur + 2.0)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if need:
        if not os.path.isfile(ffmpeg) and not shutil.which(ffmpeg):
            return _die("нужен пережим (%.1f МБ, %dx%d, %.1f с), а ffmpeg не "
                        "найден" % (mb, w, h, vdur))
        r = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-i", a.video, "-t", "%.2f" % (dur + 1.0), "-an",
             # ТОЛЬКО УМЕНЬШЕНИЕ И БЕЗ ОБРЕЗКИ: в эффекте врезка всё равно
             # ужимается до 620x349, апскейл узкого клипа дал бы вес без
             # качества, а обрезка под 16:9 — съела бы часть кадра дважды
             # (её делает сам fx_inset, вписывая врезку в рамку).
             "-vf", "scale=w='min(1280,iw)':h=-2,fps=30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", dst], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(dst):
            return _die("пережим врезки не удался: " + r.stderr[-300:])
        nw, nh, nd = _probe(ffprobe, dst)
        print("врезка пережата: %.1f МБ %dx%d %.1f с → %.1f МБ %dx%d %.1f с"
              % (mb, w, h, vdur, os.path.getsize(dst) / 1048576.0, nw, nh, nd))
    else:
        shutil.copyfile(a.video, dst)
        print("врезка скопирована как есть: %.1f МБ %dx%d %.1f с"
              % (mb, w, h, vdur))

    sc["fx"] = "inset"
    _save(a.scenes, data)
    have = sorted(set(have) | {a.sid})
    print("сцена %d (%.1f с): эффект-врезка ПОСТАВЛЕН → %s"
          % (a.sid, dur, os.path.relpath(dst, proj)))
    print("вида «inset» в ролике: %d из %d; эффектов всего %d"
          % (len(set(same) | {a.sid}), FX_MAX, len(set(have) | {a.sid})))
    print("дальше ничего не делать: ship.sh везёт insets/ сам, "
          "клип соберёт шаг clips")
    return 0


def _put_subscribe(scenes, by_id, first, n):
    """КНОПКА «ПОДПИШИСЬ» — ТРИ РАЗА НА ДЛИНУ РОЛИКА (05.11, его слово при
    приёмке: «используем её три раза на длину видео. Один раз в правом углу,
    другой раз в левом, один раз в правом. В верхнем углу»).

    Углы чередует САМА СБОРКА по очереди сцен, здесь только места: начало,
    середина, ближе к концу. Кнопка — накладка, а не переход, но ключ `fx`
    у сцены один, поэтому ей нужны сцены БЕЗ перехода и не короче 4,5 с
    (вся анимация идёт 3,4 с).

    Отдельной функцией, а не строчками внутри расстановки переходов: когда
    переходы уже стоят по три, расстановка выходит из работы сразу — и
    кнопки, будь они внутри, не появились бы НИКОГДА на ролике, который
    просто пересобирают.
    """
    sub_have = [int(x.get("id", 0)) for x in scenes
                if str(x.get("fx", "")).strip().lower() == "subscribe"]
    sub_need = max(0, FX_MAX - len(sub_have))
    if not sub_need:
        return []
    busy = set(int(x.get("id", 0)) for x in scenes
               if str(x.get("fx", "")).strip())
    ok = [int(x.get("id", 0)) for x in scenes
          if int(x.get("id", 0)) not in busy
          and float(x.get("duration_sec") or 0) >= 4.5
          and not str(x.get("source", "")).startswith("card")]
    put = []
    for f in (0.12, 0.50, 0.85)[:sub_need]:
        t = first + int(n * f)
        cand = [x for x in ok if x not in put]
        if not cand:
            break
        put.append(min(cand, key=lambda x: (abs(x - t), x)))
    for sid in put:
        by_id[sid]["fx"] = "subscribe"
    if put:
        _ang = ["ПРАВЫЙ", "ЛЕВЫЙ"]
        for i, sid in enumerate(sorted(set(sub_have) | set(put))):
            if sid in put:
                print("сцена %d (%.1f с): кнопка «ПОДПИШИСЬ» — %s верхний угол"
                      % (sid, float(by_id[sid].get("duration_sec") or 0),
                         _ang[i % 2]))
    elif not sub_have:
        print("!! кнопку «подпишись» ставить некуда: нужны сцены без перехода "
              "длиннее 4,5 с", file=sys.stderr)
    return put


def _auto(a, data, scenes):
    """Расставить три перехода по ролику — его слово 04.11: «поставь эти
    эффекты на ролики, это на канал ПЛАНЕТА, и не больше 3 на ролик».

    Почему это отдельный режим, а не памятка вкладке: вкладка забудет, а
    забытый эффект виден только в готовом файле, когда правок уже не бывает.
    Правило «инструмент должен работать сам».

    КОГО БЕРЁМ: сцену-фотографию длиннее 2,5 с, у которой ПРЕДЫДУЩАЯ сцена
    тоже фотография (переход уезжает с её кадра), не первую в ролике, не
    рисованную карточку. Три штуки, разнесённые по ролику примерно на
    четверти, и три РАЗНЫХ вида — чтобы не читалось как один приём.
    Уже стоящие вручную эффекты (в том числе врезки) считаются и место
    занимают: потолок три — на все виды вместе.
    """
    proj = os.path.dirname(os.path.abspath(a.scenes))
    images = a.images or os.path.join(proj, "images")
    ids = [int(s.get("id", 0)) for s in scenes]
    first = min(ids) if ids else 0
    by_id = {int(s.get("id", 0)): s for s in scenes}

    def photo_like(sid):
        """Фото ли это. Если кадр уже скачан — смотрим ФАЙЛ, а не источник:
        после фетча это единственная правда (`library_video` мог приехать
        картинкой и наоборот)."""
        hit = [f for f in glob.glob(os.path.join(images, "scene_%03d.*" % sid))
               if not f.endswith((".json", ".text.png", ".lock", ".ovthumb.jpg"))]
        if hit:
            return not any(h.lower().endswith((".mp4", ".mov", ".webm", ".mkv"))
                           for h in hit)
        src = str(by_id.get(sid, {}).get("source", ""))
        return src in ("press_photo", "web_search", "stock_photo", "local_library")

    have = sorted(s["id"] for s in scenes
                  if str(s.get("fx", "")).strip().lower() in KINDS)
    by_kind = {}
    for s in scenes:
        k = str(s.get("fx", "")).strip().lower()
        if k in KINDS:
            by_kind.setdefault(k, []).append(int(s.get("id", 0)))
    # по ТРИ КАЖДОГО перехода (его слово 04.11). Врезку `inset` автомат не
    # ставит: ей нужна видео-врезка, которую выбирает вкладка глазами.
    need = []
    for k in AUTO_TRANS:
        need += [k] * max(0, FX_MAX - len(by_kind.get(k, [])))
    free = len(need)
    _subs = _put_subscribe(scenes, by_id, first, len(scenes))
    if free <= 0:
        if _subs:
            _save(a.scenes, data)
        print("все переходы уже по %d раза — добавлять нечего" % FX_MAX)
        return 0

    ok = []
    for s in scenes:
        sid = int(s.get("id", 0))
        if sid <= first or sid in have:
            continue
        if str(s.get("source", "")).startswith("card"):
            continue
        if float(s.get("duration_sec") or 0) < 2.5:
            continue
        if not photo_like(sid) or not photo_like(sid - 1):
            continue
        ok.append(sid)
    if not ok:
        print("!! подходящих сцен нет: переходу нужна сцена-фотография "
              "длиннее 2,5 с, у которой предыдущая сцена тоже фотография",
              file=sys.stderr)
        return 1

    # РИСУНОК РАССТАНОВКИ СВОЙ У КАЖДОГО РОЛИКА (04.11, его вопрос: «а если
    # на ПЛАНЕТЕ это будет каждый ролик, каждый ролик?»). Если всегда ставить
    # мозаику-панели-вайп на четвертях, через неделю это читается как штамп
    # канала, а не как приём. Поэтому и ВИДЫ, и МЕСТА гуляют — но ДЕТЕРМИНИРОВАННО
    # по имени папки ролика: пересборка, рефетч и повтор дают тот же рисунок,
    # иначе ролик менял бы вид от прогона к прогону (та же логика, что у
    # слоёв в `build_clips_1080.py`).
    rnd = random.Random("fx|" + os.path.basename(proj))
    n = len(scenes)
    # ПЕРВЫЕ ЭФФЕКТЫ — СРАЗУ, ПОБЛИЖЕ К НАЧАЛУ (05.11, его прямое слово по
    # сданному ролику «Дизелька солянка»: «я пока дошёл до 10 минуты, ничего
    # нет другого… все эти эффекты нужно применять сразу, поближе к началу.
    # Мы разрабатываем, тратим токены на новые эффекты, чтобы потом их не
    # применять в видео?»). Раньше цели стояли РАВНОМЕРНО по ролику: при
    # девяти переходах первый приходился примерно на 10% длины, а зритель,
    # бросивший ролик на десятой минуте, не видел ничего, кроме врезки.
    # Теперь первые ТРИ эффекта садятся в первую шестую часть ролика
    # (доли 0.04 / 0.10 / 0.17), остальные расходятся по хвосту ровно.
    # Доли подобраны ЗАПУСКОМ на 56 сценах: 0.04/0.10/0.17 давали в голове
    # только два эффекта — средний выбивало правилом «не ближе четырёх сцен».
    _head = [0.04, 0.13, 0.24][:free]
    _rest = free - len(_head)
    _tail = [0.34 + (0.95 - 0.34) * (i + 1) / float(_rest + 1)
             for i in range(_rest)]
    targets = [max(first + 2, first + int(n * (f + rnd.uniform(-0.02, 0.02))))
               for f in (_head + _tail)]
    # ШАГ МЕЖДУ ЭФФЕКТАМИ УСТУПАЕТ НОРМЕ «КАЖДЫЙ ВИД ПО ТРИ» (05.11, его
    # прямое слово по сданному ролику про Киев: «Нахуя я разрабатываю каждый
    # раз новый эффект… чтобы применился один? Они все по 3 раза на
    # видеоряд, чтобы ВСЕ эффекты присутствовали»). Шаг в четыре сцены стоял
    # жёстко, и при пяти видах места кончались: на 56 сценах вставало 8
    # эффектов вместо 15, причём виды выпадали целиком. Теперь шаг —
    # уступающее правило: пробуем 4, потом 3, потом 2, и берём первый, при
    # котором помещается ВСЯ норма. Ближе двух сцен не ставим никогда.
    def _pick(gap):
        _p = []
        for t in targets:
            cand = [x for x in ok if x not in _p]
            if not cand:
                break
            _p.append(min(cand, key=lambda x: (abs(x - t), x)))
        _p.sort()
        _keep, _busy = [], list(have)
        for x in _p:
            if all(abs(x - y) >= gap for y in _busy):
                _keep.append(x); _busy.append(x)
        return _keep

    def _fill(sel, gap):
        """Добрать недостающие места жадно: цели иногда схлопываются на одном
        кандидате, и норма недобиралась на одну-две штуки (на 70 сценах
        выходило 14 из 15). Добираем по порядку, соблюдая тот же шаг."""
        busy = list(have) + list(sel)
        for x in ok:
            if len(sel) >= free:
                break
            if x in sel:
                continue
            if all(abs(x - y) >= gap for y in busy):
                sel.append(x); busy.append(x)
        return sorted(sel)

    picked = []
    for _gap in (4, 3, 2):
        picked = _fill(_pick(_gap), _gap)
        if len(picked) >= free:
            if _gap < 4:
                print("шаг между эффектами уменьшен до %d сцен — иначе норма "
                      "«%d каждого вида» не помещается" % (_gap, FX_MAX))
            break
    if not picked:
        print("!! подходящие сцены есть, но все ближе четырёх сцен к уже "
              "стоящим эффектам — ставить не буду", file=sys.stderr)
        return 1

    # ВИДЫ РАЗДАЁМ ПО КРУГУ, А НЕ ИЗ ПЕРЕМЕШАННОЙ КУЧИ (05.11). Мест под
    # эффекты в ролике меньше, чем мест в норме (правило «не ближе четырёх
    # сцен»), и при перемешанном списке первые слоты доставались кому попало:
    # на 56 сценах при четырёх видах вышло panels 3, mosaic 2, wipe 2,
    # depth 1 — то есть принятый вид показывался один раз за ролик. Круговая
    # раздача делит слоты поровну: сколько бы их ни было, виды идут подряд.
    _kinds = [k for k in AUTO_TRANS if need.count(k)]
    rnd.shuffle(_kinds)
    _order = [k for _r in range(FX_MAX) for k in _kinds]
    for i, sid in enumerate(picked):
        by_id[sid]["fx"] = _order[i % len(_order)]

    _save(a.scenes, data)
    allfx = sorted(int(x.get("id", 0)) for x in scenes
                   if str(x.get("fx", "")).strip().lower() in KINDS)
    for sid in picked:
        print("сцена %d (%.1f с): переход «%s» ПОСТАВЛЕН"
              % (sid, float(by_id[sid].get("duration_sec") or 0),
                 by_id[sid]["fx"]))
    _cnt = {}
    for sid in allfx:
        _cnt[by_id[sid]["fx"]] = _cnt.get(by_id[sid]["fx"], 0) + 1
    print("эффектов в ролике: %d — %s (норма по %d на КАЖДЫЙ вид)"
          % (len(allfx),
             ", ".join("%s %d" % kv for kv in sorted(_cnt.items())), FX_MAX))
    # ВРЕЗКА НЕ СТАВИТСЯ АВТОМАТОМ — И ОБ ЭТОМ НАДО ГОВОРИТЬ ГРОМКО
    # (04.11, его прямое слово по сданному ролику: «где этот радар, где эти
    # круги, которые мы делали… ладно, я сказал не больше 3, ты подумал 1.
    # Но ноль сюда не входит»). Вкладка прогнала `--auto`, увидела
    # «эффектов 3 из 3» и посчитала норму закрытой — а счётчик считал
    # ТОЛЬКО переходы. Врезке нужен видеофайл, который выбирает человек,
    # поэтому автомат её не ставит; но молчать об этом нельзя.
    if not _cnt.get("inset"):
        print("")
        print("!! ВРЕЗКИ С КРУГАМИ-РАДАРОМ В РОЛИКЕ НЕТ (0 штук).")
        print("   Автомат её не ставит: нужен видеофайл, который выбираешь "
              "ты. Это ГЛАВНЫЙ эффект канала, ноль — не норма.")
        print("   Поставь так (видео — клип из базы, вложение досье или "
              "скачанный кусок):")
        print("     python3 ~/.claude/skills/news-video/template/fx_put.py "
              "%s <sid> <видео>" % os.path.basename(a.scenes))
    print("файлов не нужно: кадры прошлых сцен облако возьмёт само")
    return 0


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _die(msg):
    print("!! " + msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
