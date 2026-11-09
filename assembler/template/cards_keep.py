#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cards_keep.py — клипы РИСОВАННЫХ сцен забор не трогает.

Зачем (09.11, улов `usuario-2c`, ролик `planeta-ukraina-forma-1011`): вкладка
поставила 17 карточек, `cards_cloud` отрисовал их и разложил готовые клипы
`images/scene_NNN.mp4` — а круг правок через облако (`ship.sh --fetch-only`
плюс `get.sh`) вернул на их место облачные заглушки «нет кадра»
(`images/scene_NNN.jpg`, 33 КБ, яркость 28 из 255). Из семнадцати клипов не
осталось НИ ОДНОГО; уцелели только постеры в `cards/`. Сцены эти матрица и не
искала — у них источник `card:*`, искать там нечего по устройству.

Почему прежняя защита не помогла: фикс 08.11 «забор больше не откатывает
работу» прикрывает `*.scenes.json` и `overlays.json`, а `images/` — нет:
чистка забора сносит папку целиком, архив из облака кладёт свою версию.

Опора — ИСТОЧНИК сцены из сценария, а не расширение файла: у поисковых
видеосцен тоже `.mp4`, и возвращать их старые копии НЕЛЬЗЯ (15.10 так вернулся
забаненный клип и стоил ролика).

Два режима:
    python3 cards_keep.py --snapshot <папка> <куда>     # ДО чистки забора
    python3 cards_keep.py --restore  <папка> <откуда> [--work <рабочая папка>]

Код возврата всегда 0: это страховка, а не гейт — ронять ею забор нельзя.
"""
import glob
import importlib.util
import json
import os
import shutil
import sys

DARK = 45
STUB_MAX = 150 * 1024
_IMG = (".jpg", ".jpeg", ".png", ".webp")
_CLIP = (".mp4", ".mov")


def _brightness():
    """Готовый измеритель яркости из cloud/fetch_report.py (своего не пишем)."""
    p = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "cloud",
        "fetch_report.py"))
    if not os.path.exists(p):
        return lambda _f: None
    try:
        spec = importlib.util.spec_from_file_location("_fr_cards", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._brightness
    except Exception:
        return lambda _f: None


def card_ids(proj):
    """id сцен, кадр которых мы рисуем сами (источник `card:*`)."""
    best = []
    for c in glob.glob(os.path.join(proj, "*.scenes.json")):
        if "overlays_fetch" in os.path.basename(c):
            continue
        try:
            with open(c, encoding="utf-8") as f:
                v = (json.load(f) or {}).get("scenes") or []
        except (OSError, ValueError):
            continue
        if len(v) > len(best):
            best = v
    out = []
    for s in best:
        if not str(s.get("source") or "").startswith("card"):
            continue
        try:
            out.append(int(s.get("id")))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


def snapshot(proj, out):
    ids = card_ids(proj)
    if not ids:
        return 0
    os.makedirs(out, exist_ok=True)
    n = 0
    for i in ids:
        for ext in _CLIP:
            p = os.path.join(proj, "images", "scene_%03d%s" % (i, ext))
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(out, os.path.basename(p)))
                n += 1
    if n:
        print("  клипы карточек отложены на время забора: %d шт" % n)
    return 0


def _stub(path, bright):
    if not path.lower().endswith(_IMG):
        return False
    try:
        if os.path.getsize(path) > STUB_MAX:
            return False
    except OSError:
        return False
    b = bright(path)
    return b is not None and b < DARK


def _was_drawn(proj, work, i):
    """Карточка УЖЕ была отрисована: рядом лежит её постер или резервный клип.
    Только постер-картинка, не `*.sfx.json`: тот пишется вместе с заданием,
    а не с готовым кадром. Заказ в `cards/queue/` признаком не считается —
    он есть и у карточки, которую ещё не рисовали (живой случай 09.11,
    сцена 93: задание в очереди, постера нет, потери нет)."""
    roots = [proj] + ([work] if work else [])
    for r in roots:
        for ext in (".jpg", ".jpeg", ".png"):
            if os.path.exists(os.path.join(r, "cards", "scene_%03d%s" % (i, ext))):
                return True
        for ext in _CLIP:
            if os.path.exists(os.path.join(
                    r, "cards", "clips_backup", "scene_%03d%s" % (i, ext))):
                return True
    return False


def restore(proj, src, work=""):
    ids = card_ids(proj)
    if not ids:
        return 0
    bright = _brightness()
    imgs = os.path.join(proj, "images")
    os.makedirs(imgs, exist_ok=True)
    back, dropped, have, lost = 0, [], 0, []
    for i in ids:
        mine = os.path.join(imgs, "scene_%03d.mp4" % i)
        if not os.path.exists(mine):
            # ищем отложенную копию: сначала снимок перед чисткой, потом
            # рабочая папка ролика, потом backup, который кладёт cards_cloud
            for d in [src, os.path.join(work, "images") if work else "",
                      os.path.join(proj, "cards", "clips_backup"),
                      os.path.join(work, "cards", "clips_backup") if work else ""]:
                if not d:
                    continue
                for ext in _CLIP:
                    p = os.path.join(d, "scene_%03d%s" % (i, ext))
                    if os.path.exists(p) and os.path.getsize(p) > 1000:
                        shutil.copy2(p, os.path.join(
                            imgs, "scene_%03d%s" % (i, ext)))
                        back += 1
                        print("  ВЕРНУЛ КЛИП КАРТОЧКИ сцены %d — забор привёз "
                              "по ней заглушку вместо нашего кадра" % i)
                        break
                if os.path.exists(mine):
                    break
        # заглушку облака по рисованной сцене выбрасываем всегда: матрица её
        # не искала, а рядом с клипом она перебивает его в сборке и в дашборде
        for ext in _IMG:
            p = os.path.join(imgs, "scene_%03d%s" % (i, ext))
            if os.path.exists(p) and _stub(p, bright):
                try:
                    os.remove(p)
                    dropped.append(i)
                except OSError:
                    pass
        if os.path.exists(mine):
            have += 1
        elif _was_drawn(proj, work, i):
            lost.append(i)
    for i in dropped:
        tail = ("твой клип на месте" if os.path.exists(
            os.path.join(imgs, "scene_%03d.mp4" % i))
            else "КЛИПА НЕТ — карточку надо перерисовать")
        print("  !! по сцене %d приехала ЗАГЛУШКА, у неё рисованный кадр — "
              "пропущено, %s" % (i, tail))
    print("  рисованных сцен %d, клипов карточек на месте %d%s"
          % (len(ids), have,
             ", возвращено %d" % back if back else ""))
    if lost:
        print("  !! КЛИПОВ НЕТ У ОТРИСОВАННЫХ КАРТОЧЕК: сцены %s"
              % ", ".join(str(x) for x in lost))
        print("     Постер в `cards/` есть, клипа нет — повтори `cards_cloud`,")
        print("     клипы возьмутся из кэша прогона за полминуты.")
    return 0


def main(argv):
    if "--snapshot" in argv:
        a = [x for x in argv if not x.startswith("--")]
        if len(a) < 2:
            print(__doc__)
            return 0
        return snapshot(a[0], a[1])
    if "--restore" in argv:
        work, a, i = "", [], 0
        while i < len(argv):
            x = argv[i]
            if x == "--work":
                work = argv[i + 1] if i + 1 < len(argv) else ""
                i += 2
                continue
            if not x.startswith("--"):
                a.append(x)
            i += 1
        if len(a) < 2:
            print(__doc__)
            return 0
        return restore(a[0], a[1], work)
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
