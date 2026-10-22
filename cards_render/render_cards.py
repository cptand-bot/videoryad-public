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
def render_jobs(jobs_path, outdir, fps=30):
    import quote_variants as qv
    FN = {"quote": None, "split": qv.quote_split, "tape": qv.quote_tape,
          "doc": qv.quote_doc, "strike": qv.quote_strike, "duel": qv.quote_duel,
          "pull": qv.quote_pull, "marker_serif": qv.marker_glyph,
          "paper_typed": qv.paper_typed, "paper_hand": qv.paper_hand}
    import quote_paper as _qp
    FN["quote"] = _qp.quote_paper
    jobs = json.load(open(jobs_path, encoding="utf-8"))
    os.makedirs(outdir, exist_ok=True)
    rep = []
    for job in jobs:
        view, sid = job["view"], int(job["scene"])
        kw = dict(job.get("kwargs") or {})
        # фото едет рядом с заданием: путь на машине пользователя раннеру не виден
        if kw.get("photo"):
            kw["photo"] = os.path.join(os.path.dirname(jobs_path),
                                       os.path.basename(kw["photo"]))
        fn = FN[view]
        mp4 = os.path.join(outdir, f"scene_{sid:03d}.mp4")
        jpg = os.path.join(outdir, f"scene_{sid:03d}.jpg")
        t0 = time.time()
        fn(out=jpg, **kw)
        sc.render_anim(fn, kw, float(job["dur"]), mp4, fps=fps,
                       anim_seconds=float(job.get("anim") or 2.6),
                       tail_zoom=float(job.get("tail_zoom") or 0.045), sfx_out=True)
        took = time.time() - t0
        print(f"  сцена {sid} ({view}): {job['dur']} с, {took:.1f} с счёта", flush=True)
        rep.append({"scene": sid, "view": view, "dur": job["dur"],
                    "seconds_spent": round(took, 1)})
    json.dump(rep, open(os.path.join(outdir, "report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return rep


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "cards_out"
    jobs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.json")
    if os.path.exists(jobs):                 # есть задания ролика — рисуем их
        rep = render_jobs(jobs, out)
        print("итого:", round(sum(r["seconds_spent"] for r in rep), 1), "с на",
              len(rep), "карточек")
        raise SystemExit(0)
    views = sys.argv[2:] or list(VIEWS)
    rep = [render(v, out) for v in views]
    json.dump(rep, open(os.path.join(out, "report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("итого:", round(sum(r["seconds_spent"] for r in rep), 1), "с на",
          len(rep), "видов")
