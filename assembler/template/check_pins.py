#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_pins.py — сверка ПИНОВ (явных путей к файлам медиатеки) с бан-листом
и кулдауном ДО фетча.

Зачем: пин — это явный путь к файлу в `source_query` сцены, выбранный глазами
по контактному листу. Если этот файл забанен, попал в окно последних
COOLDOWN_VIDEOS роликов или уже стоит в этой сборке, `fetch_local_library`
молча переключается на round-robin по папке — вкладка уверена, что в сцене
стоит выбранный кадр, а стоит случайный.

Родился 2026-10-17 из улова на `planeta-svergnut-1810`: три пина в
ПОЛИТИКА/ЗЕЛЕНСКИЙ и ПОЛИТИКА/«УКРАИНА ВСУ и Азов» оказались забанены, и
поймать это удалось только сверкой md5 руками — сэкономило круг правок. Сам
фетчер с того же дня печатает `ПИН ОТКЛОНЁН (причина)`, но это видно уже
ПОСЛЕ фетча, а здесь — до.

Использование (из папки проекта):
    python3 .../check_pins.py scenes.json [overlays_fetch.scenes.json ...]
    python3 .../check_pins.py --strict scenes.json     # exit 1 при проблеме

Exit 0 — все пины чистые (или пинов нет), exit 1 — есть проблемные (при
--strict; без него всегда 0, чтобы не рвать пайплайн).
"""
import re
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# переиспользуем ТУ ЖЕ логику, что и фетчер, чтобы она не разъехалась
from fetch_assets_news import (  # noqa: E402
    COOLDOWN_VIDEOS, USAGE_LOG, BANNED_LOG, file_md5, load_banned_md5,
)


def load_env(path=".env"):
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def cooldown_md5(this_project):
    """md5 файлов, использованных в последних COOLDOWN_VIDEOS ДРУГИХ роликах.
    Журнал устроен как {md5: [{project, date, file}, ...]} — списка роликов
    в нём нет, он выводится агрегацией (гоча 2026-10-17)."""
    if not os.path.exists(USAGE_LOG):
        return set(), []
    with open(USAGE_LOG, encoding="utf-8") as f:
        log = json.load(f)
    proj_dates = {}
    for entries in log.values():
        for e in entries:
            if e["project"] == this_project:
                continue
            proj_dates[e["project"]] = max(proj_dates.get(e["project"], ""), e.get("date", ""))
    recent = sorted(proj_dates.items(), key=lambda kv: kv[1], reverse=True)[:COOLDOWN_VIDEOS]
    recent_names = {p for p, _ in recent}
    blocked = {md5 for md5, entries in log.items()
               if any(e["project"] in recent_names for e in entries)}
    return blocked, recent


def _lib_alt(lib):
    """Соседняя библиотека: `media-library` ↔ `media-library-2`.

    ОТКАТ ПОВТОРЯЕТ ФЕТЧЕР (`fetch_assets_news.py`, откат от 29.10), и это не
    удобство, а условие правильного приговора: фетч ищет тег в библиотеке
    канала, а не найдя — в соседней, ДЛЯ ЛЮБОГО тега, не только `БАЗА/`.
    Проверка без отката объявляла живые папки выдуманными (03.11, улов
    `usuario-0d`: на 5 МИНУТ отбились разом ПОЛИТИКА/ЕВРОПА, ЕВРОПА-армия,
    ЕС-форумы-Украина, НАТО, ПОЛЬША, УКРАИНА, ФРАНЦИЯ — 14 сцен из 75, в
    которых лежало от 10 до 141 файла). Цена ошибки обратная заявленной:
    сообщение гнало переписать живые библиотечные сцены в ПОИСКОВЫЕ, а доля
    поиска — главный множитель брака.
    """
    b = os.path.basename(os.path.normpath(lib))
    if b.endswith("-2"):
        return os.path.join(os.path.dirname(os.path.normpath(lib)), b[:-2])
    if b == "media-library":
        return os.path.normpath(lib) + "-2"
    return ""


def _lib_has(lib, rel):
    """Есть ли тег в библиотеке канала ИЛИ в соседней — как у фетчера.

    Возвращает путь, по которому нашлось (или пустую строку).
    """
    for base in (lib, _lib_alt(lib)):
        if not base:
            continue
        p = os.path.join(base, rel)
        if os.path.isdir(p) or os.path.isfile(p):
            return p
    return ""


def main():
    argv = [a for a in sys.argv[1:] if a != "--strict"]
    strict = "--strict" in sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    env = load_env()
    lib = os.path.expanduser(env.get("MEDIA_LIBRARY_DIR", "~/projects/media-library"))
    if not os.path.isabs(lib):
        lib = os.path.expanduser(os.path.join("~/projects", lib))
    project = os.path.basename(os.path.abspath("."))
    banned = load_banned_md5()
    cooled, recent = cooldown_md5(project)

    pins, bad, seen, missing = [], [], {}, []
    folders = {}
    for path in argv:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for sc in (data.get("scenes") if isinstance(data, dict) else data):
            q = sc.get("source_query") or ""
            if sc.get("source") != "local_library" or not q:
                continue
            qq = q.strip()
            direct = _lib_has(lib, qq)
            if direct and os.path.isfile(direct):
                pins.append((path, sc.get("id"), qq, direct,
                             float(sc.get("duration_sec") or 0)))
                continue
            # «папка:keyword» (кусок индексированного видео) — это папка
            folder = qq.split(":", 1)[0] if ":" in qq else qq
            _f = _lib_has(lib, folder)
            if _f and os.path.isdir(_f):
                # ПАПКА — round-robin, НО ОНА МОЖЕТ БЫТЬ ИСЧЕРПАНА КУЛДАУНОМ
                # (03.11, улов `usuario-79`). Живой случай:
                # `БАЗА/ВЕДОМСТВА/МИНОБОРОНЫ-РОССИИ` — ровно два файла, оба
                # съедены вчерашними роликами, и фетч отбил сцену «все файлы
                # использованы в последних 3 видео». Ни каталог («в каталог
                # ПРОХОДИТ»), ни пины («все пины чистые») этого не показывали:
                # сцена приезжала FAILED уже на фетче, то есть круг правок
                # терялся на том, что видно заранее одной проверкой.
                folders.setdefault(folder, (_f, []))[1].append(sc.get("id"))
                continue
            # НИ ФАЙЛА, НИ ПАПКИ — БИТЫЙ ПИН (2026-10-18, улов usuario-b7).
            # Раньше такой путь попадал в ветку «папка, не наше дело» и
            # check_pins печатал «все пины чистые». Фетч при этом молча уходит
            # в веб-водопад, ставит кадр с отметкой ok, а в manifest.json
            # остаётся source: local_library / status: cached — то есть манифест
            # ВРЁТ, будто пин сработал, и подмену нечем заметить даже потом.
            # Живой случай: всплывашка 17 на planeta-usloviya-1910, пин
            # «ПОЛИТИКА/КАРТЫ/РОССИЯ/Blank Map of Russia With Borders of
            # Subjects.jpg» — в медиатеке файл называется иначе.
            missing.append((path, sc.get("id"), qq))

    print(f"проект: {project}   медиатека: {lib}")
    print(f"бан-лист: {BANNED_LOG} ({len(banned)} активных md5)")
    print("кулдаун: " + (", ".join(f"{p} ({d})" for p, d in recent) or "журнала нет"))
    print(f"пинов найдено: {len(pins)}")
    # --- СВОБОДНЫХ ФАЙЛОВ В ПАПКЕ (кулдаун и бан) -------------------------
    # Считаем ТОЛЬКО у небольших папок: у папки на 40 файлов исчерпание
    # практически невозможно, а md5 каждого файла стоит чтения с диска.
    _EXH_MAX = 12
    _EXT = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm", ".mkv")
    for folder, (fpath, sids) in sorted(folders.items()):
        try:
            files = [f for f in os.listdir(fpath) if f.lower().endswith(_EXT)]
        except OSError:
            continue
        if not files:
            # ПУСТАЯ ПАПКА-ЗАГОТОВКА (03.11, улов `usuario-15`): в базе лежат
            # каталоги, созданные заранее под ночной сбор. Путь существует,
            # поэтому «выдуманным» он не считается, а кадра в нём нет — фетч
            # отдаст FAILED, и это видно здесь за секунды.
            bad.append((", ".join(map(str, sids)), folder,
                        "ПАПКА ПУСТАЯ (ноль кадров) — это заготовка под "
                        "ночной сбор, а не материал. Фетч отдаст сцену "
                        "FAILED: возьми другую папку или поисковый запрос"))
            continue
        if len(files) > _EXH_MAX:
            continue
        _is_map = "/КАРТЫ/" in ("/" + folder.replace("\\", "/"))
        free = 0
        for f in files:
            try:
                h = file_md5(os.path.join(fpath, f))
            except OSError:
                continue
            if h in banned:
                continue
            if h in cooled and not _is_map:
                continue
            free += 1
        if not free:
            bad.append((", ".join(map(str, sids)), folder,
                        "ПАПКА ИСЧЕРПАНА: все %d файл(ов) в бане или кулдауне "
                        "(последние %d ролика) — фетч отдаст сцену FAILED, "
                        "это видно ЗАРАНЕЕ. Возьми другую папку или сними бан"
                        % (len(files), COOLDOWN_VIDEOS)))
        # ВЕРТИКАЛИ И КВАДРАТЫ — ПРЕДУПРЕЖДАЕМ ДО ФЕТЧА (04.11, улов
        # `usuario-31`: холодильник приехал с широкими размытыми полями, и
        # увиделось это только в ГОТОВОМ файле). Размер берём ИЗ ИМЕНИ
        # файла — ночной сбор его туда пишет, картинки открывать не надо.
        _nar = _kn = 0
        for f in files:
            m = re.search(r"(\d{3,5})x(\d{3,5})", f)
            if not m:
                continue
            w, h = int(m.group(1)), int(m.group(2))
            if not w or not h:
                continue
            _kn += 1
            if w / float(h) < 1.40:
                _nar += 1
        if _kn and _nar / float(_kn) > 0.5:
            print("  ВНИМАНИЕ: в папке «%s» вертикалей и квадратов %d из %d "
                  "— в рамку 16:9 они не ложатся, кадр пойдёт по центру с "
                  "размытой заливкой полей. Выбери файл поимённо листом."
                  % (folder, _nar, _kn))
        if False:
            pass
        elif free < len(sids):
            print("  ВНИМАНИЕ: папка «%s» стоит на %d сценах (%s), а свободных "
                  "от кулдауна файлов в ней %d из %d — часть сцен уйдёт в "
                  "поиск или повторит кадр"
                  % (folder, len(sids), ", ".join(map(str, sids)),
                     free, len(files)))

    for src, sid, q in missing:
        bad.append((sid, q, "НЕТ ТАКОГО ФАЙЛА И НЕТ ТАКОЙ ПАПКИ в медиатеке — "
                            "фетч молча уйдёт в веб-водопад, а манифест оставит "
                            "source: local_library (ложь)"))
    for src, sid, q, direct, dur in pins:
        try:
            h = file_md5(direct)
        except OSError as exc:
            bad.append((sid, q, f"не читается: {exc}"))
            continue
        # ВИДЕОПИН КОРОЧЕ СЦЕНЫ — ВИДИМАЯ ПЕТЛЯ (23.10, улов `usuario-fa`).
        # Живой случай: пин «ПОЛИТИКА/ПУТИН/Нарезки - Путин2.mp4» 12,8 с встал
        # на сцену 14,9 с. `selfcheck` такое ловит, но ПРЕДУПРЕЖДЕНИЕМ и уже
        # ПОСЛЕ фетча — то есть после того, как за кадр заплачено. Здесь это
        # стоит один ffprobe и видно ДО отправки.
        if dur > 0 and direct.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".m4v")):
            try:
                _r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", direct],
                    capture_output=True, text=True, timeout=30)
                _have = float((_r.stdout or "0").strip() or 0)
            except (OSError, ValueError, subprocess.SubprocessError):
                _have = 0.0
            if _have and _have + 0.15 < dur:
                bad.append((sid, q, f"видео {_have:.1f} с КОРОЧЕ сцены {dur:.1f} с "
                                    f"(не хватает {dur - _have:.1f} с) — в кадре будет "
                                    "видимая петля; возьми другой файл или укороти сцену"))
                continue

        why = None
        _is_map = "/КАРТЫ/" in ("/" + q.replace("\\", "/"))
        if h in banned:
            why = "ЗАБАНЕН"
        elif _is_map:
            pass          # карты вне кулдауна (2026-10-17), см. fetch_local_library
        elif h in cooled:
            why = f"КУЛДАУН (был в последних {COOLDOWN_VIDEOS} роликах)"
        elif h in seen:
            why = f"ДУБЛЬ: тот же файл уже пин в сцене {seen[h]}"
        if why:
            # ПОСЛЕДСТВИЕ НАЗЫВАЕМ ВСЛУХ (03.11, улов `usuario-b5`). «ЗАБАНЕН»
            # читалось как «сцена не поедет», а фетч её ОТРАБОТАЕТ: пин
            # отклоняется и берётся round-robin по той же папке, то есть в
            # кадре окажется СЛУЧАЙНЫЙ файл, а строка фетча «ПИН ОТКЛОНЁН»
            # легко проскакивает в длинном логе. Пин точного имени файла —
            # не обещание, а просьба.
            bad.append((sid, q, f"{why} [md5 {h[:8]}] — фетч НЕ встанет, он "
                                f"возьмёт round-robin по папке "
                                f"«{os.path.dirname(q) or q}»: в кадре будет "
                                f"СЛУЧАЙНЫЙ файл. Выбери другой файл или "
                                f"снимай бан"))
        else:
            seen[h] = sid
    if bad:
        print(f"\nПРОБЛЕМНЫХ ПИНОВ: {len(bad)} — фетч подменит их случайным "
              f"файлом из той же папки, молча менять выбранный кадр нельзя:")
        for sid, q, why in bad:
            print(f"  сцена {sid}: {q}\n      → {why}")
        print("\nЛечение: выбрать другой файл из папки (или снять бан через "
              "ban_file.py, если бан ошибочный) ДО запуска фетча.")
    else:
        print("\nвсе пины чистые")
    return 1 if (bad and strict) else 0


if __name__ == "__main__":
    sys.exit(main())
