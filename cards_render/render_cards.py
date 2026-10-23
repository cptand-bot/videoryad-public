# -*- coding: utf-8 -*-
"""БОЕВЫЕ ВИДЕО-ВЕРСИИ ЦИТАТ: один вид — один клип, параметры как у сборщика.

Рисует принятые 22.10 виды в движении по НОРМЕ БОЕВОГО КОНВЕЙЕРА:
  fps 30  (сборщик клипов работает на 30; смешение частот в concat уже
           однажды растянуло готовый ролик на 20%),
  длительность задаётся сценой, хвост доезжает наездом (без заморозки),
  звуковые события пишутся рядом в .sfx.json.

Запускается и локально, и на раннере: пути к шрифтам берутся из
VIDEORYAD_FONTS, если переменная задана.

    python3 render_cards.py <папка-выхода> [вид ...]
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import style_cards as sc
import quote_paper as qp

# --- шрифты: на раннере своего скилла нет, пути подменяются -----------------
FONTS = os.environ.get("VIDEORYAD_FONTS")
if FONTS:
    sc.NV = FONTS
    sc.F_HEAD = os.path.join(FONTS, "RobotoCondensed-Bold.ttf")
    sc.F_ALT = os.path.join(FONTS, "Oswald-Bold.ttf")
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"):
        if not os.path.exists(cand):
            raise SystemExit(f"нет моноширинного шрифта: {cand}")

import quote_variants as qv

if FONTS:
    qv.F_OSW = sc.F_ALT
    qv.F_SERIF = os.path.join(FONTS, "Tinos-Bold.ttf")
    # рукописный: Segoe Script остаётся на машине (лицензия Microsoft,
    # в публичный репозиторий не кладётся) — на раннере свободный Caveat
    hand = os.path.join(FONTS, "Caveat-Bold.ttf")
    if os.path.exists(hand):
        qv.F_HAND = hand

PHOTO = os.environ.get("VIDEORYAD_PORTRAIT") or os.path.expanduser(
    "~/projects/ds-full-1810/portraits/scene_101.jpg")
WM = os.environ.get("VIDEORYAD_WM", "АРСЕНАЛ")

TXT_A = "Коридор откроется только после того, как стороны согласуют режим проверок"
ACC_A = "режим проверок"
TXT_B = ("Садитесь и договаривайтесь сейчас. Потом будет сложнее, "
         "а потом может стать вообще невозможно")
ACC_B = "вообще невозможно"

# вид → (функция, аргументы, длительность, сколько секунд рисуем покадрово,
#        наезд в хвосте)
VIEWS = {
    "split": (qv.quote_split, dict(
        photo=PHOTO, text="Мы не станем обсуждать маршрут, пока не увидим гарантии на бумаге",
        accent="гарантии на бумаге", author="Имя Фамилия",
        role="должность на момент заявления", source="пресс-подход, 21 октября",
        watermark=WM), 7.0, 2.6, 0.045),
    "tape": (qv.quote_tape, dict(
        kick="поступило по каналу · 21 октября",
        text="Режим проверок вводится с первого числа и действует до особого распоряжения",
        accent="до особого распоряжения", author="текст коммюнике",
        source="коммюнике, пункт 4", watermark=WM), 7.0, 2.4, 0.04),
    "doc": (qv.quote_doc, dict(
        kick="из документа", title="протокол заседания, пункт 4",
        text=("Стороны подтверждают, что любое изменение маршрута требует письменного "
              "согласия всех участников и вступает в силу через тридцать дней"),
        mark="письменного согласия", stamp="копия", source="протокол, пункт 4",
        watermark=WM), 8.0, 3.4, 0.04),
    "strike": (qv.quote_strike, dict(
        kick="что обещали", text="Проверки начнутся через неделю и займут не больше месяца",
        struck="не больше месяца", fix="идёт четвёртый", author="то же ведомство, март",
        source="заявление ведомства, март 2026", watermark=WM), 7.5, 3.0, 0.045),
    "duel": (qv.quote_duel, dict(
        kick="одно событие · два объяснения", title="почему остановили коридор",
        top={"who": "первая сторона", "text": "Движение остановлено из-за технической проверки",
             "accent": "технической проверки", "source": "заявление, 20 октября",
             "speaker_idx": 0},
        bottom={"who": "вторая сторона", "text": "Никакой проверки нет, нам просто закрыли проезд",
                "accent": "закрыли проезд", "source": "заявление, 20 октября",
                "speaker_idx": 2},
        source="оба заявления — 20 октября", watermark=WM), 8.0, 3.2, 0.035),
    "pull": (qv.quote_pull, dict(
        kick="позиция на столе",
        text="Переговоры имеют смысл только тогда, когда обе стороны чем-то рискуют",
        accent="чем-то рискуют", author="Имя Фамилия",
        role="должность на момент заявления", source="интервью, 19 октября",
        watermark=WM), 7.0, 2.6, 0.05),
    "marker_serif": (qv.marker_glyph, dict(
        kick="заявление · 21 октября", text=TXT_A, accent=ACC_A, author="Имя Фамилия",
        role="должность на момент заявления", source="брифинг, 21 октября",
        watermark=WM), 7.0, 2.6, 0.045),
    "paper_typed": (qv.paper_typed, dict(
        kick="Женева · 21 октября 2026", title="что сказано вслух", text=TXT_B,
        accent=ACC_B, source="публичное заявление", watermark=WM), 7.0, 2.8, 0.04),
    "paper_hand": (qv.paper_hand, dict(
        kick="Женева · 21 октября 2026", title="что сказано вслух", text=TXT_B,
        accent=ACC_B, source="публичное заявление", watermark=WM), 7.0, 2.8, 0.04),
}


def render(view, outdir, fps=30):
    fn, kw, dur, anim, zoom = VIEWS[view]
    os.makedirs(outdir, exist_ok=True)
    mp4 = os.path.join(outdir, f"z_q_{view}.mp4")
    jpg = os.path.join(outdir, f"z_q_{view}.jpg")
    t0 = time.time()
    fn(out=jpg, **kw)                       # постер — он же проверка глазами
    sc.render_anim(fn, kw, dur, mp4, fps=fps, anim_seconds=anim,
                   tail_zoom=zoom, sfx_out=True)
    took = time.time() - t0
    size = os.path.getsize(mp4) / 1e6
    print(f"  {view}: {dur:.1f} с, нарисовано {anim:.1f} с, {took:.1f} с счёта, "
          f"{size:.1f} МБ", flush=True)
    return {"view": view, "dur": dur, "anim": anim, "seconds_spent": round(took, 1),
            "mb": round(size, 2)}


# ---------------------------------------------------------------------------
# РЕЖИМ ЗАДАНИЙ: рисуем карточки КОНКРЕТНОГО ролика, а не демо витрины.
# jobs.json кладёт `cards_cloud.py`, имена клипов — как ждёт сборщик.
# ---------------------------------------------------------------------------
# ===========================================================================
# ПОЛНЫЙ КОМПЛЕКТ АРСЕНАЛА В ОБЛАКЕ (2026-10-23)
# Задание может звать ЛЮБУЮ функцию арсенала, но только из этого реестра —
# имя из `jobs.json` не исполняется как код, а ищется в разрешённых модулях.
# Три режима:
#   frame  — функция рисует один кадр (out=..., t=...), оживляем render_anim;
#   clip   — функция сама пишет mp4 (первый позиционный аргумент — путь);
#   scroll — полотно из *_canvas, затем style_cards.scroll_clip по нему.
# ===========================================================================
def patch_fonts(mod, fonts_dir):
    """Шрифты на раннере лежат в одной папке, а модули арсенала помнят путь
    внутри скилла (`~/.claude/skills/.../template/fonts`), которого там нет.
    Поэтому у КАЖДОГО модуля любую строку-путь к .ttf приводим к этой папке.

    Повод (2026-10-23): четыре части прогона упали с `OSError: cannot open
    resource` на `torn_photo._f` — подмена была написана только для цитат.
    """
    import types
    for name in dir(mod):
        if name.startswith("__"):
            continue
        val = getattr(mod, name, None)
        if isinstance(val, str) and val.lower().endswith(".ttf"):
            cand = os.path.join(fonts_dir, os.path.basename(val))
            if os.path.exists(cand):
                setattr(mod, name, cand)
            elif not os.path.exists(val):
                # шрифта нет ни там, ни там (Segoe Script в публичный
                # репозиторий не кладётся) — берём рукописный свободный
                alt = os.path.join(fonts_dir, "Caveat-Bold.ttf")
                if os.path.exists(alt):
                    setattr(mod, name, alt)
        elif isinstance(val, str) and val.endswith("fonts"):
            setattr(mod, name, fonts_dir)


def _registry():
    import cinematic, devices, film, photo_card, poster, torn_photo, torn_split
    import transitions, quote_paper, quote_variants
    return {"style_cards": sc, "cinematic": cinematic, "film": film,
            "devices": devices, "torn_split": torn_split, "torn_photo": torn_photo,
            "photo_card": photo_card, "poster": poster, "transitions": transitions,
            "quote_paper": quote_paper, "quote_variants": quote_variants}


def resolve(view, reg):
    """«модуль.функция» → сама функция. Ничего, кроме реестра, не достать."""
    if "." not in view:
        return None
    mod, fn = view.split(".", 1)
    m = reg.get(mod)
    if m is None or fn.startswith("_"):
        return None
    return getattr(m, fn, None)


def render_jobs(jobs_path, outdir, fps=30, shard=None):
    """shard = (i, n) — рисовать только i-ю часть из n (нумерация с 1).
    Полный комплект арсенала на 62 сцены одним потоком в таймаут не влезает,
    поэтому прогон идёт матрицей: n машин берут по куску заданий."""
    import quote_variants as qv
    FN = {"quote": None, "split": qv.quote_split, "tape": qv.quote_tape,
          "doc": qv.quote_doc, "strike": qv.quote_strike, "duel": qv.quote_duel,
          "pull": qv.quote_pull, "marker_serif": qv.marker_glyph,
          "paper_typed": qv.paper_typed, "paper_hand": qv.paper_hand,
          # КАРТОЧКИ РАЗБОРА — тоже в облако (2026-10-23). До этого дня у них
          # облачного пути НЕ БЫЛО вообще: `template/style_card.py` рисовал их
          # ТОЛЬКО на машине пользователя, а считать там нельзя ничего.
          "bullets": sc.bullets, "forces": sc.forces, "timeline": sc.timeline,
          # ОБЯЗАТЕЛЬНЫЙ СЛОЙ НА ФОТО (2026-10-23, его слово: «никаких
          # пустых фотографий вообще»). `attrib` — кадр с кикером и живой
          # красной точкой, `lower` — кадр с атрибуцией и репликой снизу.
          "attrib": sc.attrib_frame, "lower": sc.lower_third}
    import quote_paper as _qp
    FN["quote"] = _qp.quote_paper
    jobs = json.load(open(jobs_path, encoding="utf-8"))
    if shard:
        i, n = shard
        jobs = [j for k, j in enumerate(jobs) if k % n == (i - 1)]
        print(f"часть {i} из {n}: {len(jobs)} заданий", flush=True)
    os.makedirs(outdir, exist_ok=True)
    rep = []
    for job in jobs:
        view, sid = job["view"], int(job["scene"])
        kw = dict(job.get("kwargs") or {})
        for seq in ("items", "rows", "events"):   # JSON отдаёт списки
            if isinstance(kw.get(seq), list):
                kw[seq] = tuple(kw[seq])
        # фото едет рядом с заданием: путь на машине пользователя раннеру не виден
        # пути к кадрам на машине пользователя раннеру не видны: все файлы
        # приехали рядом с заданием, поэтому любую строку-путь приводим к
        # локальному имени — на любой глубине структуры
        base_dir = os.path.dirname(jobs_path)

        def _local(obj):
            if isinstance(obj, str):
                if obj.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")):
                    return os.path.join(base_dir, os.path.basename(obj))
                return obj
            if isinstance(obj, dict):
                return {k: _local(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_local(v) for v in obj]
            if isinstance(obj, tuple):
                return tuple(_local(v) for v in obj)
            return obj

        kw = _local(kw)
        if job.get("cfg"):
            job["cfg"] = _local(job["cfg"])
        mp4 = os.path.join(outdir, f"scene_{sid:03d}.mp4")
        jpg = os.path.join(outdir, f"scene_{sid:03d}.jpg")
        t0 = time.time()
        # ОДНО УПАВШЕЕ ЗАДАНИЕ НЕ ВАЛИТ ЧАСТЬ (2026-10-23): раньше исключение
        # на одной сцене уносило все десять клипов своей машины.
        try:
            # `mode` берём ЗДЕСЬ (23.10, блокер `usuario-21`): переменная
            # использовалась в вызове, а определялась только ВНУТРИ
            # `_render_one` — NameError бил все виды подряд, 0 из 5 карточек.
            # Снаружи это выглядело как успешный прогон: джоб `success`,
            # артефакт 140 байт, «готово: 0 из 5».
            if not _render_one(FN, job, sid, view, kw, job.get("mode") or "frame",
                               mp4, jpg, jobs_path, fps):
                continue
        except Exception as e:
            print(f"  сцена {sid} ({view}): УПАЛО — {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
            continue
        took = time.time() - t0
        print(f"  сцена {sid} ({view}): {job['dur']} с, {took:.1f} с счёта",
              flush=True)
        rep.append({"scene": sid, "view": view, "dur": job["dur"],
                    "seconds_spent": round(took, 1)})
    json.dump(rep, open(os.path.join(outdir, "report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return rep


def _render_one(FN, job, sid, view, kw, mode, mp4, jpg, jobs_path, fps):
    if True:
        mode = job.get("mode") or "frame"
        reg = _registry()
        if FONTS:
            for _m in reg.values():
                patch_fonts(_m, FONTS)
        fn = FN.get(view) or resolve(view, reg)
        if fn is None:
            print(f"  сцена {sid}: вид «{view}» не разрешён — пропуск", file=sys.stderr,
                  flush=True)
            return False
        if mode == "cli":
            # КАРТОЧКИ ВТОРОГО СКИЛЛА (глава / факт / досье) — отдельные
            # скрипты со своим языком оформления. Едут в облако папкой `stv`.
            import subprocess as _sp
            stv = os.path.join(os.path.dirname(jobs_path), "stv")
            script = os.path.join(stv, job["script"])
            argv = ["python3", script]
            if job.get("cfg"):
                cfgp = os.path.join(os.path.dirname(jobs_path), f"cfg_{sid:03d}.json")
                json.dump(job["cfg"], open(cfgp, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
                argv += [cfgp, mp4]
            else:
                argv += [str(x) for x in job.get("argv", [])] + [mp4, str(job["dur"])]
            r = _sp.run(argv, capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(mp4):
                print(f"  сцена {sid}: {job['script']} упал — "
                      f"{(r.stderr or r.stdout or '').strip()[:200]}",
                      file=sys.stderr, flush=True)
                return False
        elif mode == "clip":
            fn(mp4, seconds=float(job["dur"]), fps=fps, **kw)
        elif mode == "scroll":
            cf = resolve(job["canvas"], reg)
            if cf is None:
                print(f"  сцена {sid}: полотно «{job.get('canvas')}» не разрешено",
                      file=sys.stderr, flush=True)
                return False
            page = cf(**kw)
            sc.scroll_clip(page, mp4, seconds=float(job["dur"]),
                           direction=job.get("direction", "up"), fps=fps)
        else:
            fn(out=jpg, **kw)
            sc.render_anim(fn, kw, float(job["dur"]), mp4, fps=fps,
                           anim_seconds=float(job.get("anim") or 2.6),
                           tail_zoom=float(job.get("tail_zoom") or 0.045), sfx_out=True)
        return True


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:]]
    shard = None
    for a in list(argv):
        if a.startswith("--shard"):
            val = a.split("=", 1)[1] if "=" in a else argv[argv.index(a) + 1]
            i, n = val.split("/")
            shard = (int(i), int(n))
            argv = [x for x in argv if x != a and x != val]
    out = argv[0] if argv else "cards_out"
    jobs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.json")
    if os.path.exists(jobs):                 # есть задания ролика — рисуем их
        rep = render_jobs(jobs, out, shard=shard)
        print("итого:", round(sum(r["seconds_spent"] for r in rep), 1), "с на",
              len(rep), "карточек")
        raise SystemExit(0)
    views = argv[1:] or list(VIEWS)
    rep = [render(v, out) for v in views]
    json.dump(rep, open(os.path.join(out, "report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("итого:", round(sum(r["seconds_spent"] for r in rep), 1), "с на",
          len(rep), "видов")
