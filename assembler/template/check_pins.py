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
import json
import os
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

    pins, bad, seen = [], [], {}
    for path in argv:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for sc in (data.get("scenes") if isinstance(data, dict) else data):
            q = sc.get("source_query") or ""
            if sc.get("source") != "local_library" or not q:
                continue
            direct = os.path.join(lib, q)
            if not os.path.isfile(direct):
                continue            # папка, не пин — не наше дело
            pins.append((path, sc.get("id"), q, direct))

    print(f"проект: {project}   медиатека: {lib}")
    print(f"бан-лист: {BANNED_LOG} ({len(banned)} активных md5)")
    print("кулдаун: " + (", ".join(f"{p} ({d})" for p, d in recent) or "журнала нет"))
    print(f"пинов найдено: {len(pins)}")
    for src, sid, q, direct in pins:
        try:
            h = file_md5(direct)
        except OSError as exc:
            bad.append((sid, q, f"не читается: {exc}"))
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
            bad.append((sid, q, f"{why} [md5 {h[:8]}]"))
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
