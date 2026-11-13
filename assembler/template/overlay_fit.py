# -*- coding: utf-8 -*-
"""ЛОЖИТСЯ ЛИ ВСПЛЫВАШКА В ЭТОТ КАДР (13.11.2026, его прямое слово).

Повод дословно: «ты потратил кучу времени на подбор этой всплывашки, чтобы
поставить её на картинку, чтобы она перекрыла нафиг человека, лицо человека.
Может надо сначала провести анализ исходной картинки и посмотреть, ложится ли
туда вообще всплывашка в этот кадр или нет, и если нет, то не принимать
решение делать всплывашку».

Сцена 10 ролика «5 МИНУТ» 13.11: всплывашка легла ровно на лицо. Подбор,
скачивание, круг правок — всё это было потрачено ДО того, как кто-нибудь
посмотрел, есть ли в кадре свободное место. Проверка стоит доли секунды и
обязана идти ПЕРВОЙ.

ЧЕМ СУДИМ (без opencv — его на машине нет, и ставить ради этого нечего):
  · КОЖА в зоне — грубый, но надёжный признак лица: классический диапазон
    (R>95, G>40, B>20, max-min>15, |R-G|>15, R>G, R>B). Доля кожи выше 6%
    зоны означает «там человек»;
  · ПЛОТНОСТЬ КРАЁВ (Sobel по яркости) — сколько в зоне мелкой фактуры:
    текст, лица, толпа, техника. Ровное небо и стена дают около нуля;
  · КОНТРАСТ зоны (стандартное отклонение) — ровная заливка значит «можно
    класть», пёстрая — «съест и всплывашку, и кадр».

Зона считается ПО ЯКОРЮ канала и реальному размеру всплывашки: у «5 МИНУТ»
и прочих она вверху, у ПЛАНЕТЫ внизу (правило 05.09, дефолт по каналу —
04.11), ширина около 36% кадра, высота около 30%, отступ 4%.
"""
import os
import sys

import numpy as np
from PIL import Image

# доля кадра, которую занимает всплывашка (сверено с build_overlays)
W_DOLYA, H_DOLYA, OTSTUP = 0.36, 0.30, 0.04
# пороги: сняты на кадрах 13.11 (лицо в зоне → кожа 11-34%, край 0.14-0.22;
# небо и стена → кожа 0-1%, край 0.01-0.03)
KOZHA_STOP = 0.06
KRAY_STOP = 0.12
KONTRAST_STOP = 62.0


def _zona(w, h, anchor, storona="right"):
    """Прямоугольник всплывашки в пикселях: (x0, y0, x1, y1)."""
    bw, bh = int(w * W_DOLYA), int(h * H_DOLYA)
    m = int(min(w, h) * OTSTUP)
    x0 = w - bw - m if storona == "right" else m
    y0 = m if str(anchor) == "top" else h - bh - m
    return max(0, x0), max(0, y0), min(w, x0 + bw), min(h, y0 + bh)


def _kozha(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    m = ((r > 95) & (g > 40) & (b > 20) & ((mx - mn) > 15) &
         (np.abs(r.astype(np.int16) - g) > 15) & (r > g) & (r > b))
    return float(m.mean())


def _kray(y):
    gx = np.abs(np.diff(y, axis=1))[:-1, :]
    gy = np.abs(np.diff(y, axis=0))[:, :-1]
    g = np.hypot(gx, gy)
    return float((g > 28).mean())


_VID = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


def _kadr_iz_video(path):
    """Один кадр с середины клипа — иначе видеосцены проверка пропускает.

    Сцена 10 ролика 13.11, на которую он показал, как раз и была ВИДЕО: PIL
    его не открыл, функция честно ответила «не мешаю», и всплывашка легла на
    лицо. Вынимаем ровно один кадр (доли секунды, не рендер).
    """
    import subprocess
    import tempfile
    out = os.path.join(tempfile.gettempdir(),
                       "ovfit_%s.jpg" % os.path.basename(path).rsplit(".", 1)[0])
    try:
        dl = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration", "-of",
                             "default=nw=1:nk=1", path],
                            capture_output=True, text=True, timeout=20)
        sek = max(0.0, float((dl.stdout or "0").strip() or 0) / 2.0)
    except Exception:
        sek = 1.0
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.2f" % sek,
                        "-i", path, "-frames:v", "1", out],
                       capture_output=True, timeout=60)
    except Exception:
        return ""
    return out if os.path.isfile(out) else ""


def ocenka(path, anchor="top", storona="right"):
    """Вердикт по одному кадру: (ложится?, причина, числа)."""
    if str(path).lower().endswith(_VID):
        _k = _kadr_iz_video(path)
        if not _k:
            return True, "кадр из видео не вынулся — не мешаю", {}
        path = _k
    try:
        im = Image.open(path).convert("RGB")
    except Exception as exc:
        return True, "кадр не прочитался (%s) — не мешаю" % type(exc).__name__, {}
    w, h = im.size
    x0, y0, x1, y1 = _zona(w, h, anchor, storona)
    kusok = np.asarray(im.crop((x0, y0, x1, y1)), dtype=np.uint8)
    if kusok.size == 0:
        return True, "зона пустая", {}
    y = kusok.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    chisla = {"кожа": round(_kozha(kusok), 3),
              "край": round(_kray(y), 3),
              "контраст": round(float(y.std()), 1),
              "зона": "%s/%s" % (anchor, storona)}
    if chisla["кожа"] >= KOZHA_STOP:
        return False, ("в зоне всплывашки ЧЕЛОВЕК: кожи %.0f%% (порог %.0f%%) "
                       "— она ляжет на лицо"
                       % (chisla["кожа"] * 100, KOZHA_STOP * 100)), chisla
    if chisla["край"] >= KRAY_STOP:
        return False, ("зона плотная: мелкой фактуры %.0f%% (порог %.0f%%) — "
                       "текст, толпа или техника, всплывашка съест кадр"
                       % (chisla["край"] * 100, KRAY_STOP * 100)), chisla
    if chisla["контраст"] >= KONTRAST_STOP:
        return False, ("зона пёстрая: контраст %.0f (порог %.0f)"
                       % (chisla["контраст"], KONTRAST_STOP)), chisla
    return True, "зона свободна", chisla


def luchshaya(path, anchor="top"):
    """Какая из двух сторон свободна. Возвращает (сторона|None, причина)."""
    for st in ("right", "left"):
        ok, pochemu, _ = ocenka(path, anchor, st)
        if ok:
            return st, pochemu
    return None, "обе стороны заняты"


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Ложится ли всплывашка в кадр: анализ ДО подбора картинки")
    ap.add_argument("kadr", nargs="+", help="файл кадра сцены")
    ap.add_argument("--anchor", default="top", choices=["top", "bottom"])
    ap.add_argument("--storona", default="", choices=["", "right", "left"])
    a = ap.parse_args()
    plohih = 0
    for p in a.kadr:
        if a.storona:
            ok, pochemu, ch = ocenka(p, a.anchor, a.storona)
        else:
            st, pochemu = luchshaya(p, a.anchor)
            ok = st is not None
            ch = {"сторона": st or "—"}
            if ok:
                pochemu = "свободна сторона %s" % st
        print("%-46s %s  %s  %s"
              % (os.path.basename(p), "ЛОЖИТСЯ" if ok else "НЕ ЛОЖИТСЯ",
                 pochemu, ch))
        plohih += 0 if ok else 1
    if plohih:
        print("\nНА %d КАДРАХ ВСПЛЫВАШКИ НЕТ МЕСТА — не подбирай её туда "
              "вовсе (его слово 13.11). Сцена остаётся без всплывашки, это "
              "НЕ брак; норма наложений считается от остальных." % plohih)
    return 0


if __name__ == "__main__":
    sys.exit(main())
