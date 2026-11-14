# -*- coding: utf-8 -*-
"""РИСОВАЛКА ДЛИННЫХ СЦЕН ДЛЯ РАННЕРА (вызывается как `mode: cli`).

ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ, А НЕ СТРОКА В `render_cards.py`. Боевой
`render_cards.py` раскатан по десяти трубам и правится только диспетчером
(и только в конце смены). Задание с `mode: cli` он исполняет БЕЗ единой
правки: запускает `stv/<script> <cfg.json> <out.mp4>`. Значит новый вид
можно обкатать в облаке, не трогая боевой код вообще.

    python3 sceny_cli.py cfg_012.json scene_012.mp4

`cfg.json`: {"view": "prohod", "seconds": 32.0, "fps": 30, "kwargs": {...}}

Пишет рядом постер `.jpg` (его ждёт дашборд) и `.sfx.json` (звуковые
события сцены — их расставляет сама сцена).
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# на раннере скрипт лежит в `cards_render/stv/`, а модули — в `cards_render/`
for p in (HERE, os.path.dirname(HERE),
          os.path.join(os.path.dirname(HERE), "template")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

import sceny_kodom as sk                                  # noqa: E402

W, H = sk.W, sk.H


def render(view, kwargs, seconds, out_mp4, fps=30, t0=0.0):
    """`t0` — С КАКОЙ СЕКУНДЫ НЕПРЕРЫВНОГО ДВИЖЕНИЯ РИСОВАТЬ ЭТОТ КУСОК.

    Так вид и закрывает 2-5 сцен, ничего не меняя в сборщике: сцены 12-15
    получают ОДИН И ТОТ ЖЕ вид четырьмя обычными заданиями, у каждого свой
    `t0` и своя длительность. Путь камеры — чистая функция времени, поэтому
    куски стыкуются кадр в кадр, а раскладка по сценам и субтитры остаются
    прежними. Бонусом куски рисуются ПАРАЛЛЕЛЬНО на разных машинах матрицы:
    клип на 32 с считается за время самого длинного куска, а не целиком.
    """
    # СТРАЖ ПОДМЕНЁННОГО ВРЕМЕНИ (13.11, живой случай: восемь клипов в
    # мусор). В первой версии таймер назывался `t0` и ЗАТЁР этот довод —
    # кадры рисовались со временем 1,76e9 с, камера улетала на 130 млн
    # метров, и в кадре оставался один зал. Прогон при этом отчитался
    # УСПЕХОМ, клипы были нужной длины, и увидеть подмену можно было только
    # глазами по кадру. Теперь такое падает вслух и сразу.
    if float(t0) > 3600.0:
        raise SystemExit("t0 = %r — это не смещение сцены, а чьё-то "
                         "системное время. Рисовать не буду." % t0)
    fn = sk.ВИДЫ[view][0]
    sfx = []
    try:
        fn(t=None, sfx=sfx, **kwargs)
    except TypeError:
        pass
    json.dump(sfx, open(out_mp4.rsplit(".", 1)[0] + ".sfx.json", "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    fn(out=out_mp4.rsplit(".", 1)[0] + ".jpg", t=(t0 or None), **kwargs)
    n = int(round(float(seconds) * fps))
    pr = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", "%dx%d" % (W, H), "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-pix_fmt", "yuv420p", "-threads", "4", out_mp4],
        stdin=subprocess.PIPE)
    _начало = time.time()
    # ВСЕ КАДРЫ РИСУЮТСЯ ПОКАДРОВО, ХВОСТА-НАЕЗДА ЗДЕСЬ НЕТ. У карточки хвост
    # экономит счёт, потому что её картинка к концу замирает. У этих сцен
    # камера едет ВСЮ сцену: замороженный хвост убил бы ровно то, ради чего
    # вид и заведён. Цена кадра поэтому и доведена до 0,14-0,27 с.
    for i in range(n):
        кадр = fn(t=float(t0) + i / float(fps), **kwargs)
        pr.stdin.write(кадр.tobytes())
    pr.stdin.close()
    pr.wait()
    return time.time() - _начало


if __name__ == "__main__":
    cfg_path, out_mp4 = sys.argv[1], sys.argv[2]
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    view = cfg["view"]
    if view not in sk.ВИДЫ:
        raise SystemExit("вид «%s» этой рисовалке не известен: %s"
                         % (view, ", ".join(sorted(sk.ВИДЫ))))
    сек = float(cfg.get("seconds") or sk.ВИДЫ[view][3])
    t = render(view, dict(cfg.get("kwargs") or {}), сек, out_mp4,
               fps=int(cfg.get("fps") or 30), t0=float(cfg.get("t0") or 0.0))
    мб = os.path.getsize(out_mp4) / 1e6 if os.path.exists(out_mp4) else 0
    print("  %s: %.1f с экрана (с %.1f с хода), %.0f с счёта, %.1f МБ"
          % (view, сек, float(cfg.get("t0") or 0.0), t, мб), flush=True)
