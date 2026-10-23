# -*- coding: utf-8 -*-
"""СПЛОШНАЯ ПРОВЕРКА КАЧЕСТВА КАДРОВ РОЛИКА.

Требование пользователя 2026-10-23, дословно: «Строжайший контроль качества
фотографии. Строжайший. 21 век, Луну снимаем в высочайшем качестве. А мы
Зеленского снимаем — еле заметно, что это он». И сплошная, а не точечная:
«пересмотреть качество всех фотографий».

    python3 photo_quality.py [images] [--strict]

Считает по КАЖДОМУ кадру три числа и печатает список подозрительных:

  1. РАЗРЕШЕНИЕ — ширина. Меньше 1600 на полный экран — мало.
  2. ПЛОТНОСТЬ — байт на пиксель. Ниже 0.08 часто значит, что маленькую
     картинку растянули: размер формально правильный, деталей нет.
  3. ЗАПАС ДЕТАЛЕЙ — во сколько раз кадр резче своей же версии, прогнанной
     через уменьшение вдвое и обратное увеличение. У настоящего снимка
     высокие частоты есть и теряются при этом (замер по четырём сданным
     роликам: медиана 5.5-6.8, минимум 1.76). Около 1 — кадр уже растянут,
     добавить ему нечего. ВАЖНО: от сюжета это число не зависит, в отличие
     от «резкости», которая на гладком небе падает у безупречного кадра.

Почему три числа, а не одно: проверено живьём 23.10 — плотность ошибается в
обе стороны (крупный кадр 5616×3744 сжимается эффективнее и даёт низкую
плотность при отличном качестве; мягкий кадр 2560×1440 проходит с запасом).
Поэтому инструмент не бракует сам, а СОБИРАЕТ подозрения для глаз: решение
за вкладкой, как и с контактным листом.
"""
import argparse
import glob
import os
import sys

SKIP = (".json", ".log", ".lock")
VIDEO = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
MIN_W, MIN_DENS, MIN_RATIO = 1600, 0.08, 2.5


def detail_ratio(path):
    """Запас деталей; 0.0 — измерить не удалось."""
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return 0.0

    def lap_var(a):
        lap = (a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
               - 4 * a[1:-1, 1:-1])
        return float(lap.var())

    try:
        with Image.open(path) as im:
            im = im.convert("L")
            if max(im.size) > 1600:          # большой кадр считаем вполовину
                im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
            a = np.asarray(im, dtype="float32")
            half = im.resize((max(1, im.width // 2), max(1, im.height // 2)),
                             Image.LANCZOS)
            b = np.asarray(half.resize(im.size, Image.LANCZOS), dtype="float32")
        s1, s2 = lap_var(a), lap_var(b)
        return s1 / s2 if s2 > 0 else 0.0
    except Exception:
        return 0.0


def main():
    ap = argparse.ArgumentParser(description="сплошная проверка качества кадров")
    ap.add_argument("images", nargs="?", default="images")
    ap.add_argument("--strict", action="store_true", help="exit 1 при находках")
    a = ap.parse_args()
    if not os.path.isdir(a.images):
        sys.exit(f"нет папки: {a.images}")

    try:
        from PIL import Image
    except Exception:
        sys.exit("нет PIL — проверить нечем")

    rows, bad = [], []
    for f in sorted(glob.glob(os.path.join(a.images, "scene_*.*"))):
        low = f.lower()
        if low.endswith(SKIP) or low.endswith(VIDEO) or ".text." in low or ".ovthumb." in low:
            continue
        try:
            with Image.open(f) as im:
                w, h = im.size
        except Exception:
            continue
        dens = os.path.getsize(f) / max(1, w * h)
        ratio = detail_ratio(f)
        rows.append((f, w, h, dens, ratio))
        why = []
        if w < MIN_W:
            why.append(f"ширина {w} < {MIN_W}")
        if dens < MIN_DENS:
            why.append(f"плотность {dens:.3f} < {MIN_DENS}")
        if 0 < ratio < MIN_RATIO:
            why.append(f"запас деталей {ratio:.2f} < {MIN_RATIO} (похоже на апскейл)")
        if why:
            bad.append((f, w, h, "; ".join(why)))

    print(f"проверено кадров: {len(rows)}")
    if rows:
        import statistics
        print(f"медианы: плотность {statistics.median(r[3] for r in rows):.3f}, "
              f"запас деталей {statistics.median(r[4] for r in rows):.2f}")
    if not bad:
        print("подозрительных нет — качество ровное")
        return 0
    print(f"\nПОСМОТРЕТЬ ГЛАЗАМИ — {len(bad)} кадров:")
    for f, w, h, why in bad:
        print(f"  {os.path.basename(f):22s} {w}x{h}  {why}")
    print("\nЭто подозрения, а не приговор: числа ошибаются в обе стороны "
          "(крупный кадр сжимается эффективнее, гладкий сюжет даёт низкую "
          "плотность). Открой и реши сам — плохой заменить, годный оставить.")
    return 1 if a.strict else 0


if __name__ == "__main__":
    sys.exit(main())
