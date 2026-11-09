#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podmena.py — ВТОРОЙ РУБЕЖ ЗАБОРА: привезли кадры или заглушки.

Зачем отдельная проверка (09.11, улов `usuario-e6` на `5min-ukraina-forma-1011`,
ролик ушёл 1 ч 13 мин при потолке 51 минута). `get.sh … --wait-fetch` отработал
с кодом 0 и отчитался «кадры с матрицы получены, сцен 90, БЕЗ КАДРА 0», а в
заборе лежали ВСЕ 88 кадров заглушками: у каждой сцены подряд одинаковый вес
(~33 КБ) и одинаковая яркость (~28 из 255). В ту же минуту настоящий прогон
показывал двадцать джобов `fetch (N) in_progress` — то есть забран был релиз
ПРОШЛОГО, снятого прогона того же имени.

Почему одной сверки даты релиза с датой отправки мало. Релиз снятого прогона
публикуется НЕ в момент отмены: шаг `Publish result as a Release` успевает
доработать уже ПОСЛЕ того, как вкладка отправила задание заново, и по времени
такой релиз оказывается НОВЕЕ отправки — любая проверка «дата релиза против
даты коммита» его пропускает. Поэтому решает содержимое: настоящий забор
тёмных заглушек не содержит вовсе (замер на живом заборе того же дня: 67
кадров, 0 тёмных), а подмена — почти целиком из них.

Ровно класс «успех значит ничего не сделано»: статус зелёный, число сцен
сходится, «БЕЗ КАДРА 0» — а работы нет. Сложить два числа (яркость и вес) и
сказать вслух — дешевле получаса пересборки.

Яркость считает ГОТОВЫЙ измеритель из `cloud/fetch_report.py` (`_brightness`,
уменьшает кадр до 32x32 и берёт среднее по серому) — своего здесь нет
намеренно: порог и поведение должны быть одни и те же у облачного отчёта и у
забора.

Использование:
    python3 podmena.py <папка забора>            # проверить привезённое
    python3 podmena.py <папка> --tiho            # без подробного перечня

Второй счёт здесь же — КЛИПЫ КАРТОЧЕК (09.11, улов `usuario-2c`): забор
сносил `images/` целиком и кладбищем ложился на 17 отрисованных карточек,
возвращая по ним облачные заглушки. Если у карточки есть постер в `cards/`
(значит её РИСОВАЛИ), а клипа `images/scene_NNN.mp4` нет — работа потеряна, и
молчать об этом нельзя.

Коды возврата:
    0 — чисто (или нечего проверять)
    2 — ПОДМЕНА: большинство кадров — тёмные заглушки
    4 — проверку выполнить не удалось (нет PIL) — это не «чисто»
    5 — пропали клипы отрисованных карточек
"""
import glob
import importlib.util
import json
import os
import statistics
import sys

# Порог заглушки. Тот же, что у облачного отчёта (`fetch_report._DARK`): точный
# ВЕС заглушки не ловится — бывает и 33 999, и 34 002, и 36 864 (ширина номера
# сцены в подписи меняет размер файла, и у каждой свой md5). Ловится яркость.
DARK = 45
# Выше этого веса тёмный кадр — настоящее ночное фото, а не заглушка:
# заглушки облака весят 30-40 КБ, а живые кадры в заборе — от 28 КБ до
# нескольких мегабайт. Поэтому вес не отделяет заглушку сам по себе и стоит
# здесь только отсечкой сверху, чтобы не ругаться на тёмную фотографию.
STUB_MAX = 150 * 1024
# Сколько тёмных кадров подряд считать подменой, а не отдельным браком.
MIN_STUBS = 5
MAJORITY = 0.5      # доля тёмных от всех привезённых кадров
CLUSTER = 0.3       # либо меньше, но с одинаковым весом (разброс ниже SPREAD)
SPREAD = 2 * 1024

_IMG = (".jpg", ".jpeg", ".png", ".webp")


def _load_brightness():
    """Готовый измеритель яркости из cloud/fetch_report.py."""
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "..", "cloud", "fetch_report.py")
    p = os.path.normpath(p)
    if not os.path.exists(p):
        return None
    try:
        spec = importlib.util.spec_from_file_location("_fetch_report", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._brightness
    except Exception:
        return None


def _scenes(proj):
    """Сцены ролика: id -> источник. Нужны, чтобы не считать заглушками то,
    что заглушкой и должно быть: карточки рисуются САМИ (`card:*`) и в заборе
    их кадра может не быть вовсе, а библиотечные кадры (`local_library`) в
    облаке отсутствуют по устройству — медиатеки там нет."""
    out = {}
    cands = [x for x in glob.glob(os.path.join(proj, "*.scenes.json"))
             if "overlays_fetch" not in os.path.basename(x)]
    best = []
    for c in cands:
        try:
            with open(c, encoding="utf-8") as f:
                sc = (json.load(f) or {}).get("scenes") or []
        except (OSError, ValueError):
            continue
        if len(sc) > len(best):
            best = sc
    for s in best:
        try:
            out[int(s.get("id"))] = str(s.get("source") or "")
        except (TypeError, ValueError):
            continue
    return out


def _sid(path):
    try:
        return int(os.path.basename(path).split("_")[1].split(".")[0])
    except (IndexError, ValueError):
        return None


def check(proj, tiho=False):
    bright = _load_brightness()
    if bright is None:
        print("!! ПРОВЕРКА ПОДМЕНЫ НЕ ВЫПОЛНЕНА: не нашёл измеритель яркости")
        print("   (cloud/fetch_report.py). Это НЕ «чисто» — кадры не смотрели.")
        return 4

    src = _scenes(proj)
    frames, skipped = [], 0
    for d in ("images", "overlays"):
        dd = os.path.join(proj, d)
        if not os.path.isdir(dd):
            continue
        for f in sorted(glob.glob(os.path.join(dd, "scene_*"))):
            if not f.lower().endswith(_IMG) or ".ovthumb." in f:
                continue
            i = _sid(f)
            s = src.get(i, "") if i is not None else ""
            if s.startswith("card") or s == "local_library":
                skipped += 1
                continue
            frames.append(f)

    if not frames:
        print("проверка подмены: кадров в заборе нет — проверять нечего")
        return 0

    measured, dark = 0, []
    for f in frames:
        b = bright(f)
        if b is None:
            continue
        measured += 1
        sz = os.path.getsize(f)
        if b < DARK and sz <= STUB_MAX:
            dark.append((f, sz, b))

    if not measured:
        print("!! ПРОВЕРКА ПОДМЕНЫ НЕ ВЫПОЛНЕНА: ни один кадр не измерился")
        print("   (скорее всего нет PIL). Это НЕ «чисто».")
        return 4

    share = len(dark) / float(measured)
    sizes = [s for _, s, _ in dark]
    clustered = False
    if len(sizes) >= MIN_STUBS:
        med = statistics.median(sizes)
        same = [s for s in sizes if abs(s - med) <= SPREAD]
        clustered = len(same) >= 0.8 * len(sizes)

    podmena = len(dark) >= MIN_STUBS and (
        share >= MAJORITY or (share >= CLUSTER and clustered))

    if not podmena:
        if dark:
            print("проверка подмены: тёмных кадров %d из %d — это отдельный "
                  "брак, не подмена" % (len(dark), measured))
            if not tiho:
                for f, sz, b in dark[:10]:
                    print("    %s — %d КБ, яркость %.0f из 255"
                          % (os.path.basename(f), sz // 1024, b))
        else:
            print("проверка подмены: чисто — тёмных заглушек нет (кадров %d%s)"
                  % (measured,
                     ", карточек и библиотечных пропущено %d" % skipped
                     if skipped else ""))
        return 0

    med = statistics.median(sizes)
    bs = [b for _, _, b in dark]
    print("")
    print("!! ЗАБОР ПРИВЁЗ ЗАГЛУШКИ, А НЕ КАДРЫ — ЭТО ПОДМЕНА.")
    print("   тёмных кадров: %d из %d измеренных (%.0f%%)"
          % (len(dark), measured, share * 100))
    print("   яркость: %.0f…%.0f из 255 (порог заглушки %d)"
          % (min(bs), max(bs), DARK))
    print("   вес: медиана %d КБ, %s" % (
        med // 1024,
        "у всех одинаковый (разброс до 2 КБ)" if clustered
        else "разный — но яркость всё равно заглушечная"))
    if not tiho:
        for f, sz, b in dark[:12]:
            print("     %s — %d КБ, яркость %.0f"
                  % (os.path.basename(f), sz // 1024, b))
        if len(dark) > 12:
            print("     … и ещё %d" % (len(dark) - 12))
    print("")
    print("   ЭТО НЕ СБОЙ СЕТИ И НЕ ПОТЕРЯННЫЕ АССЕТЫ: файлы доехали целыми,")
    print("   просто внутри них облачная заглушка «нет кадра». Так выглядит")
    print("   релиз ПРОШЛОГО, снятого прогона того же имени: он публикуется")
    print("   уже ПОСЛЕ твоей новой отправки, поэтому по дате выглядит свежим,")
    print("   а кадров в нём нет — их фетч был снят на полпути.")
    print("")
    print("   ЧТО ДЕЛАТЬ:")
    print("   1) посмотри, идёт ли ТВОЙ прогон (двадцать джобов фетча):")
    print("        gh run list -R <цель> --workflow videoryad-cloud.yml -L 3")
    print("   2) после ЛЮБОЙ отмены жди статус до конца, а не релиз по имени:")
    print("        gh run view <id> --json status   # до completed")
    print("      и только потом зови get.sh ещё раз.")
    print("   3) релиз-обманку снеси, чтобы она не попалась снова:")
    print("        gh release delete <имя> -R <цель> --yes --cleanup-tag")
    print("   Эти кадры в проект НЕ переносить и дашборд на них НЕ собирать.")
    return 2


def cards_lost(proj):
    """Клипы отрисованных карточек на месте? Опора та же, что у `cards_keep.py`."""
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "cards_keep.py")
    if not os.path.exists(p):
        return 0
    try:
        spec = importlib.util.spec_from_file_location("_cards_keep", p)
        ck = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ck)
    except Exception:
        return 0
    work = proj[:-6] if proj.endswith("-cloud") else ""
    if work and not os.path.isdir(work):
        work = ""
    ids = ck.card_ids(proj)
    if not ids:
        return 0
    lost = [i for i in ids
            if not os.path.exists(os.path.join(proj, "images",
                                               "scene_%03d.mp4" % i))
            and ck._was_drawn(proj, work, i)]
    have = len(ids) - len([i for i in ids
                           if not os.path.exists(os.path.join(
                               proj, "images", "scene_%03d.mp4" % i))])
    if not lost:
        print("проверка карточек: рисованных сцен %d, клипов на месте %d"
              % (len(ids), have))
        return 0
    print("")
    print("!! ПРОПАЛИ КЛИПЫ ОТРИСОВАННЫХ КАРТОЧЕК: сцены %s"
          % ", ".join(str(i) for i in lost))
    print("   Постер в `cards/` лежит — значит карточку РИСОВАЛИ, а клипа")
    print("   `images/scene_NNN.mp4` в папке нет. Это не недоделка, это")
    print("   потеря готовой работы: забор сносит `images/` целиком, а")
    print("   облако кладёт по рисованным сценам свою заглушку «нет кадра».")
    print("   ЧТО ДЕЛАТЬ: повтори `cards_cloud` — клипы возьмутся из кэша")
    print("   прогона за полминуты, заново ничего не рисуется.")
    return 5


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    proj = args[0]
    if not os.path.isdir(proj):
        print("нет папки: %s" % proj)
        return 2
    rc = check(proj, tiho="--tiho" in argv)
    rc2 = cards_lost(proj)
    return rc or rc2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
