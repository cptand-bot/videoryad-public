#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cards_keep.py — ГОТОВЫЙ ФАЙЛ СЦЕНЫ ЗАБОР НЕ ТРОГАЕТ.

Правило одно и работает ПО ПРИНЦИПУ, а не по списку источников: если кадр
сцены облако НЕ ИСКАЛО, значит файл в `images/` — наша работа, и привезённое
по этой сцене её не затирает. Поисковых источников всего несколько и они
перечислены в `ПОИСК`; ВСЁ ОСТАЛЬНОЕ (`card:*`, `local_library`,
`direct_url`, пометка `local_ready`, любой новый источник, о котором этот
файл ещё не знает) защищено. Направление отказа выбрано сознательно:
незнакомый источник лучше защитить лишний раз и сказать об этом строкой, чем
молча снести готовую работу.

Два живых случая, на которых правило и выросло:

1) 09.11, улов `usuario-2c`, ролик `planeta-ukraina-forma-1011`: вкладка
   поставила 17 карточек, `cards_cloud` отрисовал их и разложил клипы
   `images/scene_NNN.mp4` — а круг правок через облако вернул на их место
   облачные заглушки «нет кадра» (33 КБ, яркость 28 из 255). Из семнадцати
   клипов не осталось НИ ОДНОГО, уцелели только постеры в `cards/`.

2) 09.11, ролик `5min-porazhenie-1011`: `images/scene_001.mp4` — клип из
   БАЗЫ КАДРОВ, источник сцены `local_library` — исчезал и заменялся на
   `scene_001.jpg` яркостью 28 ТРИЖДЫ ПОДРЯД, после каждого забора.
   Защита по `card:*` к тому времени уже работала, а по библиотеке — нет:
   прежняя проверка в `get.sh` считала заглушкой файл МЕНЬШЕ 20 КБ, а
   заглушка весит 33 КБ и проходила как настоящий кадр.

Почему прежние защиты не закрывали: фикс 08.11 «забор не откатывает работу»
прикрывает `*.scenes.json` и `overlays.json`, до `images/` не доходит, а
чистка забора сносит `images/` целиком — то, что вкладка сделала в ПАПКЕ
ЗАБОРА (а дашборд работает именно там), не сохранялось вовсе.

Опора — ИСТОЧНИК сцены из сценария, а не расширение файла: у поисковых
видеосцен тоже `.mp4`, и возвращать их старые копии НЕЛЬЗЯ (15.10 так
вернулся забаненный клип и стоил ролика).

Отдельное правило про РОД файла: картинкой видео не затирается даже когда
картинка настоящая. У библиотечной сцены на месте лежит `.mp4`, а из облака
приезжает `.jpg` — такая подмена молча менять смысл сцены не должна.
Приехавшее не выбрасывается: оно ложится в `images/_iz_oblaka/`, и строка
говорит, где именно. Решает вкладка, а не забор.

Три режима:
    python3 cards_keep.py --snapshot <папка> <куда>     # ДО чистки забора
    python3 cards_keep.py --restore  <папка> <откуда> [--work <рабочая папка>]
    python3 cards_keep.py --spisok   <папка>            # что защищено (чтение)

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
_CLIP = (".mp4", ".mov", ".webm")
_SKIP = (".json", ".lock", ".ready", ".txt", ".md")
# Настоящий клип из базы кадров весит мегабайты; всё мельче — обрезок.
_CLIP_MIN = 50 * 1024
# ПОИСКОВЫЕ источники: только эти кадры облако реально ищет на матрице, и
# только их оно вправе приносить. Список короткий и закрытый; всё, чего в
# нём нет, считается нашей работой.
ПОИСК = {"press_photo", "web_search", "pexels_photo", "pexels_video",
         "pexels", "stock", "stock_video", "TODO", "", "none"}
ПАПКА_ОБЛАКА = "_iz_oblaka"


def _brightness():
    """Готовый измеритель яркости из cloud/fetch_report.py (своего не пишем).

    Ищем ДВУМЯ путями: рядом с этим файлом и по постоянному адресу скилла.
    Если измерителя нет, заглушку от настоящего кадра не отличить — и тогда
    мы НЕ выбрасываем ничего (приехавшее уходит в сторону, а не в мусор), но
    говорим об этом вслух: молчаливое «проверка не выполнилась» — это ровно
    класс «успех значит ничего не сделано».
    """
    tries = [os.path.normpath(os.path.join(
                 os.path.dirname(os.path.abspath(__file__)), "..", "cloud",
                 "fetch_report.py")),
             os.path.expanduser(
                 "~/.claude/skills/news-video/cloud/fetch_report.py")]
    for p in tries:
        if not os.path.exists(p):
            continue
        try:
            spec = importlib.util.spec_from_file_location("_fr_cards", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod._brightness
        except Exception:
            continue
    print("  ВНИМАНИЕ: измеритель яркости (cloud/fetch_report.py) не найден —"
          " заглушки опознать нечем, приехавшее просто уведу в сторону")
    return lambda _f: None


def _scenes(proj):
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
    return best


def protected(proj, work=""):
    """id сцены -> источник, для всех сцен, кадр которых облако НЕ искало."""
    sc = _scenes(proj) or (_scenes(work) if work else [])
    out = {}
    for s in sc:
        try:
            i = int(s.get("id"))
        except (TypeError, ValueError):
            continue
        src = str(s.get("source") or "").strip()
        # ПОМЕТКА ПОДГОТОВЛЕННОГО НА МЕСТЕ КАДРА СИЛЬНЕЕ ИСТОЧНИКА: вложения
        # телеграма живут минуты, вкладка качает их сразу и срезает чужой
        # знак, а в облаке к тому времени лежал бы необрезанный кадр.
        ready = bool(s.get("local_ready")) or os.path.exists(
            os.path.join(proj, "images", "scene_%03d.ready" % i))
        if src in ПОИСК:
            if not ready:
                continue
            out[i] = (src or "поиск") + " + local_ready"
        else:
            out[i] = src or "источник не указан"
    return out


def card_ids(proj):
    """id сцен, кадр которых мы РИСУЕМ сами (`card:*`). Нужен `podmena.py`
    для отдельного счёта: постер есть, а клипа нет — потеря готовой работы."""
    out = []
    for s in _scenes(proj):
        if not str(s.get("source") or "").startswith("card"):
            continue
        try:
            out.append(int(s.get("id")))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


def _slot(d, i):
    """Файлы сцены в папке кадров, служебные не считаем."""
    if not d or not os.path.isdir(d):
        return []
    return sorted(f for f in glob.glob(os.path.join(d, "scene_%03d.*" % i))
                  if not f.lower().endswith(_SKIP))


def _kind(p):
    e = os.path.splitext(p)[1].lower()
    return "видео" if e in _CLIP else ("кадр" if e in _IMG else "файл")


def _stub(path, bright):
    """Заглушка «нет кадра»: ловится ЯРКОСТЬЮ, а не весом. Точный вес не
    ловит — бывает и 33 999, и 34 002, и 36 864 (ширина номера сцены в
    подписи меняет размер), и у каждой свой md5. Порог 20 КБ, стоявший в
    `get.sh`, пропускал заглушку 33 КБ как настоящий кадр."""
    if not path.lower().endswith(_IMG):
        return False
    try:
        if os.path.getsize(path) > STUB_MAX:
            return False
    except OSError:
        return False
    b = bright(path)
    return b is not None and b < DARK


def _odno_i_to_zhe(a, b):
    """Байт в байт один и тот же файл (размер, потом md5)."""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
    except OSError:
        return False
    import hashlib
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return (hashlib.md5(fa.read()).digest()
                    == hashlib.md5(fb.read()).digest())
    except OSError:
        return False


def _real(path, bright):
    """Файл, который имеет смысл беречь: клип приличного веса или не-заглушка."""
    try:
        sz = os.path.getsize(path)
    except OSError:
        return False
    if path.lower().endswith(_CLIP):
        return sz >= _CLIP_MIN
    return sz > 1024 and not _stub(path, bright)


def snapshot(proj, out):
    ids = protected(proj)
    if not ids:
        return 0
    bright = _brightness()
    os.makedirs(out, exist_ok=True)
    n = 0
    for i in sorted(ids):
        for p in _slot(os.path.join(proj, "images"), i):
            if not _real(p, bright):
                continue            # заглушку беречь незачем
            shutil.copy2(p, os.path.join(out, os.path.basename(p)))
            n += 1
    if n:
        print("  готовые кадры защищённых сцен отложены на время забора: %d шт"
              % n)
    return 0


def _was_drawn(proj, work, i):
    """Карточка УЖЕ была отрисована: рядом лежит её постер или резервный клип.
    Только постер-картинка, не `*.sfx.json`: тот пишется вместе с заданием,
    а не с готовым кадром. Заказ в `cards/queue/` признаком не считается —
    он есть и у карточки, которую ещё не рисовали (живой случай 09.11,
    сцена 93: задание в очереди, постера нет, потери нет)."""
    for r in [proj] + ([work] if work else []):
        for ext in (".jpg", ".jpeg", ".png"):
            if os.path.exists(os.path.join(r, "cards",
                                           "scene_%03d%s" % (i, ext))):
                return True
        for ext in _CLIP:
            if os.path.exists(os.path.join(
                    r, "cards", "clips_backup", "scene_%03d%s" % (i, ext))):
                return True
    return False


def restore(proj, src, work=""):
    ids = protected(proj, work)
    if not ids:
        return 0
    bright = _brightness()
    imgs = os.path.join(proj, "images")
    os.makedirs(imgs, exist_ok=True)
    back, dropped, parked, have, lost = 0, [], [], 0, []

    for i in sorted(ids):
        istoch = ids[i]
        # 1. что у нас было: сначала снимок перед чисткой, потом рабочая
        #    папка, потом резерв клипов карточек
        mine = ""
        for d in [src,
                  os.path.join(work, "images") if work else "",
                  os.path.join(proj, "cards", "clips_backup"),
                  os.path.join(work, "cards", "clips_backup") if work else ""]:
            cands = [p for p in _slot(d, i) if _real(p, bright)]
            # видео сильнее картинки: именно его и затирали заглушкой
            cands.sort(key=lambda p: (0 if p.lower().endswith(_CLIP) else 1,
                                      -os.path.getsize(p)))
            if cands:
                mine = cands[0]
                break
        # 2. что уже лежит в заборе по этой сцене
        theirs = _slot(imgs, i)
        if not mine:
            # беречь нечего: что приехало, то и остаётся (пустую сцену
            # посчитает FETCH-отчёт)
            if any(_real(p, bright) for p in theirs):
                have += 1
            elif _was_drawn(proj, work, i):
                lost.append(i)
            continue
        mine_name = os.path.basename(mine)
        # 3. разбираем привезённое: заглушку выбрасываем, настоящее уводим
        #    в сторону — но НИКОГДА не трогаем сам источник возврата
        for t in theirs:
            try:
                if os.path.samefile(t, mine):
                    continue
            except OSError:
                pass
            if _stub(t, bright):
                try:
                    os.remove(t)
                    dropped.append((i, istoch, os.path.basename(t)))
                except OSError:
                    pass
                continue
            if os.path.basename(t) == mine_name and _kind(t) == _kind(mine):
                # ТО ЖЕ ИМЯ И ТОТ ЖЕ РОД — но файл может быть ДРУГИМ. Молча
                # перезаписывать нельзя: у `direct_url` облако качает вложение
                # само, и наш файл — это, например, обрезанная версия. Если
                # байт в байт одно и то же, молчим; если разное — уводим
                # приехавшее в сторону и говорим, чтобы решала вкладка.
                if _odno_i_to_zhe(t, mine):
                    continue
            # настоящий кадр из облака по НЕпоисковой сцене: не выбрасываем,
            # но и не даём ему заменить нашу работу
            od = os.path.join(imgs, ПАПКА_ОБЛАКА)
            os.makedirs(od, exist_ok=True)
            try:
                shutil.move(t, os.path.join(od, os.path.basename(t)))
                parked.append((i, istoch, os.path.basename(t), mine_name))
            except OSError:
                pass
        # 4. возвращаем своё на место
        dst = os.path.join(imgs, mine_name)
        try:
            same = os.path.exists(dst) and os.path.samefile(mine, dst)
        except OSError:
            same = False
        if not same:
            shutil.copy2(mine, dst)
            back += 1
        have += 1

    for i, istoch, name in dropped:
        print("  !! по сцене %d приехала ЗАГЛУШКА (%s), у неё источник «%s» — "
              "пропущено, твой файл на месте" % (i, name, istoch))
    for i, istoch, name, mine_name in parked:
        print("  !! по сцене %d облако привезло СВОЙ %s (%s), а у неё источник "
              "«%s» и уже лежит %s — не затираю."
              % (i, _kind(name), name, istoch, mine_name))
        print("     приехавшее не выброшено: images/%s/%s — реши сама, что "
              "оставить" % (ПАПКА_ОБЛАКА, name))
    if back or dropped or parked:
        print("  защищённых сцен %d, своё на месте у %d%s"
              % (len(ids), have, ", возвращено %d" % back if back else ""))
    if lost:
        print("  !! КЛИПОВ НЕТ У ОТРИСОВАННЫХ КАРТОЧЕК: сцены %s"
              % ", ".join(str(x) for x in lost))
        print("     Постер в `cards/` есть, клипа нет — повтори `cards_cloud`,")
        print("     клипы возьмутся из кэша прогона за полминуты.")
    return 0


def spisok(proj):
    ids = protected(proj)
    print("защищено сцен: %d (их кадр облако не искало)" % len(ids))
    for i in sorted(ids):
        files = [os.path.basename(p) for p in _slot(os.path.join(proj, "images"), i)]
        print("  сцена %3d  источник %-22s %s"
              % (i, ids[i], ", ".join(files) or "файла нет"))
    return 0


def main(argv):
    def _opt(name):
        if name in argv:
            k = argv.index(name)
            return argv[k + 1] if k + 1 < len(argv) else ""
        return ""

    work = _opt("--work")
    pos, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--work",):
            i += 2
            continue
        if not a.startswith("--"):
            pos.append(a)
        i += 1

    if "--snapshot" in argv:
        return snapshot(pos[0], pos[1]) if len(pos) > 1 else 0
    if "--restore" in argv:
        return restore(pos[0], pos[1], work) if len(pos) > 1 else 0
    if "--spisok" in argv:
        return spisok(pos[0]) if pos else 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
