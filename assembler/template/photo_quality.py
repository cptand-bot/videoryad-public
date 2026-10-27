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
import json
import os
import re
import sys

SKIP = (".json", ".log", ".lock")
VIDEO = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
MIN_W, MIN_DENS, MIN_RATIO = 1600, 0.08, 2.5
# ВСПЛЫВАШКА РИСУЕТСЯ КОРОБКОЙ 330-700 px (классы s/m/l в build_overlays), и
# мерить её порогом полного экрана — шум: 23.10 так помечались 5-7 штук на
# ролик только за ширину 800-1500, то есть при двукратном запасе (улов
# `usuario-fa`). Для них свой порог.
MIN_W_OVERLAY = 800


def _scene_sources(images_dir):
    """{id сцены: (источник, путь-запрос)} — из scenes.json рядом с папкой.

    Нужно для двух поправок 23.10: карты из медиатеки по определению имеют
    низкую плотность (две заливки и линия границы), а библиотечные пины
    пользователь запретил менять и банить по качеству (его слово 18.10) —
    показывать их в общем списке значит давать вкладке работу, которой она
    сделать НЕ МОЖЕТ.
    """
    out = {}
    base = os.path.dirname(os.path.abspath(images_dir)) or "."
    for sp in sorted(glob.glob(os.path.join(base, "*.scenes.json"))):
        try:
            data = json.load(open(sp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for sc in (data.get("scenes") if isinstance(data, dict) else data) or []:
            try:
                out.setdefault(int(sc.get("id", -1)),
                               (str(sc.get("source", "")), str(sc.get("source_query", ""))))
            except (TypeError, ValueError):
                pass
    return out


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

    srcs = _scene_sources(a.images)
    rows, bad, lib_bad = [], [], []
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

        m = re.search(r"scene_(\d+)", os.path.basename(f))
        sid = int(m.group(1)) if m else -1
        src, sq = srcs.get(sid, ("", ""))
        is_overlay = os.path.basename(os.path.dirname(os.path.abspath(f))) == "overlays"
        is_map = "КАРТЫ/" in sq.replace("\\", "/") or "/КАРТЫ" in sq.replace("\\", "/")
        is_lib = src == "local_library"

        why = []
        w_min = MIN_W_OVERLAY if is_overlay else MIN_W
        if w < w_min:
            why.append(f"ширина {w} < {w_min}")
        if dens < MIN_DENS and not is_map:
            why.append(f"плотность {dens:.3f} < {MIN_DENS}")
        # У ВСПЛЫВАШКИ АПСКЕЙЛ ВИДЕН ТОЛЬКО ЕСЛИ ЕЙ НЕЧЕГО УЖИМАТЬ (23.10,
        # наблюдение `usuario-fa`): кадр 5700 px, нарисованный коробкой 500 px,
        # ужимается в одиннадцать раз — растянутость туда просто не доживает.
        # Поэтому для overlays меряем запас деталей, лишь когда ширина мала и
        # запаса на ужатие нет.
        if 0 < ratio < MIN_RATIO and (not is_overlay or w < 1200):
            why.append(f"запас деталей {ratio:.2f} < {MIN_RATIO} (похоже на апскейл)")
        # РОВНЫЙ КВАДРАТ — ПРИЗНАК AI ИЛИ КАТАЛОГА, ВИДЕН ДО ПРОСМОТРА
        # (26.10, замер `usuario-64`: из трёх кадров ровно 1024x1024 два
        # оказались AI-рендерами — глянцевый небоскрёб вместо балкона,
        # открыточный фонарь в снегопаде; 2000x2000 дали каталожные товарные
        # снимки на белом). Новостная съёмка квадратной не бывает почти
        # никогда: это либо генератор с его стандартным холстом, либо
        # товарная карточка магазина. Карты и библиотечные пины не трогаем.
        if w == h and w in (512, 768, 1024, 1536, 2048, 2000) and not (is_map or is_lib):
            why.append(f"ровный квадрат {w}x{h} — типичный холст AI-генератора "
                       "или каталожного снимка на белом")
        if why:
            (lib_bad if is_lib else bad).append((f, w, h, "; ".join(why)))

    # ЖУРНАЛ ФЕТЧА: что он сам признал мелким, когда лучшего не нашлось
    lowres = {}
    for jf in glob.glob(os.path.join(a.images, ".lowres.*")):
        try:
            lowres.update(json.load(open(jf, encoding="utf-8")))
        except (OSError, ValueError):
            pass
    if lowres:
        print(f"фетч сам отметил как мелкие {len(lowres)} сцен: "
              + ", ".join(f"{k} ({v})" for k, v in sorted(lowres.items(), key=lambda x: int(x[0]))[:8])
              + ("…" if len(lowres) > 8 else ""))
        print("  это значит «лучшего не нашлось» — тут нужен другой ЗАПРОС, "
              "а не повторный фетч тем же.")
    # НОЛЬ КАДРОВ — ЭТО ОТКАЗ, А НЕ «КАЧЕСТВО РОВНОЕ» (2026-10-27, улов
    # `usuario-02`). На папке, где файлы названы иначе, чем `scene_NNN.jpg`,
    # скрипт печатал «проверено кадров: 0 · подозрительных нет — качество
    # ровное» и выходил нулём: читалось как пройденная проверка, хотя не
    # сделано НИЧЕГО. После переименования та же папка дала два реальных
    # подозрения из пяти. Тот же класс, что битый ffmpeg из кэша и «OCR
    # вернул: текста нет»: проверять надо результатом, а молчание об отсутствии
    # работы — худший вид лжи инструмента.
    if not rows:
        have = [os.path.basename(x) for x in sorted(
            glob.glob(os.path.join(a.images, "*")))[:6]]
        print("!! ПРОВЕРКА НЕ СОСТОЯЛАСЬ: в %s нет ни одного файла вида "
              "`scene_NNN.jpg` — проверено НОЛЬ кадров, и это НЕ «качество "
              "ровное»." % a.images)
        if have:
            print("   что лежит в папке: %s%s"
                  % (", ".join(have), "…" if len(have) == 6 else ""))
        print("   Переименуй файлы в `scene_NNN.jpg` (или укажи правильную "
              "папку) и прогони заново.")
        return 2
    print(f"проверено кадров: {len(rows)}")
    if rows:
        import statistics
        print(f"медианы: плотность {statistics.median(r[3] for r in rows):.3f}, "
              f"запас деталей {statistics.median(r[4] for r in rows):.2f}")
    if lib_bad:
        print(f"\nиз медиатеки, МЕНЯТЬ НЕЛЬЗЯ (его слово 18.10) — {len(lib_bad)}: "
              + ", ".join(f"{os.path.basename(f)} ({w}x{h})" for f, w, h, _ in lib_bad[:6])
              + ("…" if len(lib_bad) > 6 else ""))
        print("  это к сведению, а не к работе: библиотечные пины по качеству "
              "не бракуем и не баним.")
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
