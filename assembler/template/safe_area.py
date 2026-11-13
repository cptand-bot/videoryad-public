# -*- coding: utf-8 -*-
"""БЕЗОПАСНАЯ ЗОНА КАРТОЧКИ И ПОЛОСА СУБТИТРОВ — проверка по ГОТОВОМУ клипу.

Его прямое слово 13.11, повторяется часто: «на наших карточках, там карты
делаем, там или надписи — нужно делать их с учётом того, что они не вылезут
за кадр, ни вверх, ни вниз, ни справа, ни слева. Чтобы вся главная информация
картинки находилась в центре. И второе — с учётом субтитров, потому что
субтитры порой перекрывают надписи на вот этих карточках наших».

ДВА ТРЕБОВАНИЯ, ОБА СЧИТАЮТСЯ КОДОМ, А НЕ ГЛАЗАМИ:
  1. БЕЗОПАСНАЯ РАМКА — поля 5% по каждой стороне (1920x1080 → 96 px слева и
     справа, 54 сверху и снизу). Ни буква, ни число за неё не выходят.
  2. ПОЛОСА СУБТИТРОВ — нижние 18% кадра (≈194 px) запретны для ЛЮБОГО
     текста карточки: туда ложатся субтитры ролика и перекрывают надпись.

Текст ищется OCR'ом (tesseract, тот же, что ловит клейма в фетче): он даёт
рамку КАЖДОГО слова, поэтому проверка говорит не «где-то внизу что-то есть»,
а «слово „посол“ сидит на 942 px, это на 56 px ниже границы».

    python3 safe_area.py <клип|кадр|папка> [...] [--kadry 3] [--json f.json]
    python3 safe_area.py <папка проекта>/cards            # все карточки разом

Коды возврата: 0 — чисто, 1 — есть нарушения, 2 — нечего проверять/нет OCR.
Ключ `--myagko` печатает находки, но возвращает 0 (для разведки, не для гейта).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

W, H = 1920, 1080

# ПОЛЯ И ПОЛОСА — ЧИСЛА ИЗ ЕГО ТЗ, РУКАМИ НЕ МЕНЯТЬ.
POLE = 0.05            # безопасная рамка: 5% по каждой стороне
POLOSA = 0.18          # полоса субтитров: нижние 18% кадра

# OCR врёт на фактуре: тень на стене, зерно плёнки и рваный край читаются как
# буквы. Поэтому берём только то, что похоже на НАДПИСЬ: уверенность, длина
# слова и правдоподобный кегль. Пороги сняты на живых карточках 13.11.
MIN_CONF = 60          # уверенность tesseract, %
MIN_ZNAKOV = 3         # слово короче — шум (одиночная «|», «—», «i»)
MIN_KEGL, MAX_KEGL = 13, 190   # высота рамки слова в пикселях

_ШУМ = re.compile(r"^[\W_·—–\-|=+~^`'\"]+$", re.UNICODE)

_TESS_BIN = os.path.expanduser("~/tools/tesseract/usr/bin/tesseract")
_TESS_LIB = os.path.expanduser("~/tools/tesseract/usr/lib/x86_64-linux-gnu")
_TESS_DATA = os.path.expanduser("~/tools/tesseract/usr/share/tesseract-ocr/5/tessdata")

ВИДЕО = (".mp4", ".mov", ".mkv", ".webm")
КАДРЫ = (".png", ".jpg", ".jpeg", ".webp")


def _tess_cmd():
    if os.path.exists(_TESS_BIN):
        return _TESS_BIN
    return shutil.which("tesseract")


def _tess_env():
    env = os.environ.copy()
    if os.path.isdir(_TESS_LIB):
        env["LD_LIBRARY_PATH"] = _TESS_LIB + ":" + env.get("LD_LIBRARY_PATH", "")
    if os.path.isdir(_TESS_DATA):
        env["TESSDATA_PREFIX"] = _TESS_DATA
    return env


def _ffmpeg():
    return shutil.which("ffmpeg") or os.path.expanduser("~/.local/bin/ffmpeg")


def _ffprobe():
    return shutil.which("ffprobe") or os.path.expanduser("~/.local/bin/ffprobe")


def _dlit(clip):
    try:
        out = subprocess.run(
            [_ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", clip],
            capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def _vynut_kadry(clip, skolko, papka):
    """Кадры по долям длительности: середина обязательно, дальше хвост и начало.

    Надпись у многих видов ВЫЕЗЖАЕТ — на первом кадре её ещё нет, на последнем
    она уже на месте. Один кадр с середины (как в ТЗ) ловит основное, но хвост
    добавлен не зря: у приёмов зала подпись шкалы доезжает к концу.
    """
    doli = {1: [0.5], 2: [0.5, 0.85], 3: [0.35, 0.6, 0.88]}.get(
        skolko, [0.2, 0.45, 0.7, 0.9][:skolko])
    dur = _dlit(clip)
    if dur <= 0:
        return []
    out = []
    for i, d in enumerate(doli):
        png = os.path.join(papka, f"k{i}.png")
        r = subprocess.run(
            [_ffmpeg(), "-v", "error", "-ss", f"{dur * d:.3f}", "-i", clip,
             "-frames:v", "1", "-y", png],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.exists(png):
            out.append((f"{int(d * 100)}%", png))
    return out


def _slova(png):
    """Рамки слов: [(текст, x1, y1, x2, y2, conf), …]. Пусто — OCR не нашёл."""
    tess = _tess_cmd()
    if not tess:
        return None
    baza = os.path.join(tempfile.mkdtemp(prefix="sa_"), "o")
    try:
        r = subprocess.run(
            [tess, png, baza, "-l", "rus+eng", "--psm", "11", "tsv"],
            capture_output=True, text=True, env=_tess_env(), timeout=180)
        tsv = baza + ".tsv"
        if r.returncode != 0 or not os.path.exists(tsv):
            return None
        наш = []
        with open(tsv, encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) < 12:
                    continue
                try:
                    conf = float(p[10])
                    x, y, w, h = (int(p[6]), int(p[7]), int(p[8]), int(p[9]))
                except ValueError:
                    continue
                txt = p[11].strip()
                if conf < MIN_CONF or len(txt) < MIN_ZNAKOV or _ШУМ.match(txt):
                    continue
                if not (MIN_KEGL <= h <= MAX_KEGL):
                    continue
                наш.append((txt, x, y, x + w, y + h, conf))
        return наш
    except Exception:
        return None
    finally:
        shutil.rmtree(os.path.dirname(baza), ignore_errors=True)


def _granicy(w, h, pole=POLE, polosa=POLOSA):
    return dict(left=int(w * pole), right=int(w * (1 - pole)),
                top=int(h * pole), bottom=int(h * (1 - pole)),
                subtitr=int(h * (1 - polosa)))


def _razobrat_kadr(png, pole=POLE, polosa=POLOSA):
    from PIL import Image
    with Image.open(png) as im:
        w, h = im.size
    g = _granicy(w, h, pole, polosa)
    слова = _slova(png)
    if слова is None:
        return None, g
    беда = []
    for txt, x1, y1, x2, y2, conf in слова:
        # ПОЛОСА СУБТИТРОВ — считаем по НИЗУ слова: буква, свисающая в полосу
        # хвостом «у» или «р», уже перекрыта субтитром.
        if y2 > g["subtitr"]:
            беда.append(dict(вид="полоса субтитров", слово=txt, conf=conf,
                             ramka=[x1, y1, x2, y2],
                             на=y2 - g["subtitr"], granica=g["subtitr"]))
            continue
        наруш = []
        if x1 < g["left"]:
            наруш.append(("слева", g["left"] - x1))
        if x2 > g["right"]:
            наруш.append(("справа", x2 - g["right"]))
        if y1 < g["top"]:
            наруш.append(("сверху", g["top"] - y1))
        if y2 > g["bottom"]:
            наруш.append(("снизу", y2 - g["bottom"]))
        if наруш:
            сторона, на = max(наруш, key=lambda t: t[1])
            беда.append(dict(вид=f"за рамкой {сторона}", слово=txt, conf=conf,
                             ramka=[x1, y1, x2, y2], на=на,
                             granica=g["left"] if сторона == "слева" else
                             g["right"] if сторона == "справа" else
                             g["top"] if сторона == "сверху" else g["bottom"]))
    return беда, g


def proverit(путь, kadry=2, pole=POLE, polosa=POLOSA):
    """Один файл → {'файл', 'кадры': [{'доля','беда':[…]}], 'ocr': bool}."""
    ext = os.path.splitext(путь)[1].lower()
    врем = None
    try:
        if ext in ВИДЕО:
            врем = tempfile.mkdtemp(prefix="sa_k_")
            кадры = _vynut_kadry(путь, kadry, врем)
        elif ext in КАДРЫ:
            кадры = [("кадр", путь)]
        else:
            return None
        итог = {"файл": путь, "кадры": [], "ocr": True}
        for доля, png in кадры:
            беда, g = _razobrat_kadr(png, pole, polosa)
            if беда is None:
                итог["ocr"] = False
                continue
            итог["кадры"].append({"доля": доля, "беда": беда, "границы": g})
        return итог
    finally:
        if врем:
            shutil.rmtree(врем, ignore_errors=True)


def _sobrat(пути):
    файлы = []
    for p in пути:
        if os.path.isdir(p):
            for корень, _, имена in os.walk(p):
                for и in sorted(имена):
                    if os.path.splitext(и)[1].lower() in ВИДЕО + КАДРЫ:
                        файлы.append(os.path.join(корень, и))
        elif os.path.exists(p):
            файлы.append(p)
        else:
            print(f"нет файла: {p}", file=sys.stderr)
    return файлы


def main():
    ap = argparse.ArgumentParser(
        description="безопасная зона карточки и полоса субтитров")
    ap.add_argument("пути", nargs="+", help="клип, кадр или папка")
    ap.add_argument("--kadry", type=int, default=2,
                    help="сколько кадров смотреть у клипа (1-4, по умолчанию 2)")
    ap.add_argument("--pole", type=float, default=POLE,
                    help="доля поля безопасной рамки (по умолчанию 0.05)")
    ap.add_argument("--polosa", type=float, default=POLOSA,
                    help="доля полосы субтитров снизу (по умолчанию 0.18)")
    ap.add_argument("--json", help="куда положить разбор машиной")
    ap.add_argument("--myagko", action="store_true",
                    help="печатать, но возвращать 0")
    a = ap.parse_args()

    файлы = _sobrat(a.пути)
    if not файлы:
        print("нечего проверять", file=sys.stderr)
        return 2
    if not _tess_cmd():
        print("нет tesseract — проверка текста невозможна", file=sys.stderr)
        return 2

    всё, плохих, без_ocr = [], 0, 0
    for ф in файлы:
        итог = proverit(ф, a.kadry, a.pole, a.polosa)
        if итог is None:
            continue
        всё.append(итог)
        имя = os.path.basename(ф)
        if not итог["ocr"] and not итог["кадры"]:
            без_ocr += 1
            print(f"  {имя}: OCR не отработал")
            continue
        беды = [(k["доля"], b) for k in итог["кадры"] for b in k["беда"]]
        if not беды:
            print(f"  {имя}: чисто")
            continue
        плохих += 1
        print(f"  {имя}: НАРУШЕНИЙ {len(беды)}")
        показано = set()
        for доля, b in sorted(беды, key=lambda t: -t[1]["на"]):
            ключ = (b["вид"], b["слово"])
            if ключ in показано:
                continue
            показано.add(ключ)
            x1, y1, x2, y2 = b["ramka"]
            print(f"      кадр {доля}: «{b['слово']}» {b['вид']} "
                  f"на {b['на']} px (рамка {x1},{y1}-{x2},{y2}, "
                  f"граница {b['granica']})")
            if len(показано) >= 6:
                print("      … остальное в --json")
                break

    g = _granicy(W, H, a.pole, a.polosa)
    print(f"\nфайлов {len(всё)} · с нарушениями {плохих}"
          + (f" · без OCR {без_ocr}" if без_ocr else ""))
    print(f"рамка {g['left']}..{g['right']} по ширине, {g['top']}..{g['bottom']} "
          f"по высоте; полоса субтитров ниже {g['subtitr']} px")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(всё, f, ensure_ascii=False, indent=1)
        print(f"разбор: {a.json}")

    if плохих and not a.myagko:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
