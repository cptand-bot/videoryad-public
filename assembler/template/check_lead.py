#!/usr/bin/env python3
"""Video-lead rule check (user, 2026-08-29):

  * scene 1 MUST be a video clip, not a still photo;
  * across the FIRST THIRD of the видеоряд (by runtime), video inserts must
    OUTNUMBER photo inserts;
  * after the first third the balance may relax.

Run in the pre-build audit. Reads the resolved assets in images/ if present,
otherwise falls back to the planned source_query extension.

Usage: python3 check_lead.py [scenes.json] [images_dir]
"""
import glob
import json
import os
import sys

VID = (".mp4", ".mov", ".webm", ".mkv")

sp = sys.argv[1] if len(sys.argv) > 1 else (sorted(glob.glob("*.scenes.json")) or ["scenes.json"])[0]
img = sys.argv[2] if len(sys.argv) > 2 else "images"
scenes = json.load(open(sp, encoding="utf-8"))["scenes"]


def _media_library_dir():
    # БЫЛ зашит на библиотеку-1 — на канале, который сидит на media-library-2
    # (5 МИНУТ/ДИПЛОМАТИЯ СИЛЫ/ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО), это тихо считало
    # ЛЮБУЮ local_library-сцену фото-сценой (искал папку не там, находил 0
    # файлов), ломая видео-лид даже когда реальные видео-клипы в сцене есть.
    # Поймано 2026-10-03 на ДИПЛОМАТИЯ СИЛЫ: check_lead дал fail 3 видео/14
    # фото, хотя 4 из "фото"-сцен были нормальные библиотечные видео.
    for envp in (".env",):
        if os.path.exists(envp):
            with open(envp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("MEDIA_LIBRARY_DIR="):
                        return os.path.expanduser(line.split("=", 1)[1].strip())
    return os.path.expanduser("~/projects/media-library")


LIB = _media_library_dir()
_ext = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")
_folder_is_video = {}


def _folder_video_ratio(rel):
    if rel not in _folder_is_video:
        d = os.path.join(LIB, rel)
        v = p = 0
        if os.path.isdir(d):
            for f in os.listdir(d):
                fl = f.lower()
                if fl.endswith((".mp4", ".mov")):
                    v += 1
                elif fl.endswith(_ext):
                    p += 1
        _folder_is_video[rel] = (v + p > 0 and v / (v + p) >= 0.6)
    return _folder_is_video[rel]


def is_video(s):
    # КАРТОЧКА АРСЕНАЛА — НЕ ВИДЕО-ВСТАВКА (2026-10-22). Она приезжает готовым
    # mp4 (так её берёт сборщик клипов), но норма видео-лида про ЖИВЫЕ кадры с
    # места события. Нарисованный нами лоскут бумаги закрывал бы норму
    # формально: «видео в первой трети есть» — а на экране статика.
    if str(s.get("source", "")).startswith("card"):
        return False
    hits = [p for p in glob.glob(os.path.join(img, f"scene_{s['id']:03d}.*"))
            if os.path.getsize(p) > 0 and not p.endswith(".json")]
    if hits:                                    # real asset on disk — authoritative
        return hits[0].lower().endswith(VID)
    q = s.get("source_query", "")
    if s.get("source") == "pexels_video" or ":" in q:   # :keyword = trimmed clip
        return True
    if q.lower().endswith(VID):
        return True
    if os.path.isfile(os.path.join(LIB, q)):     # explicit file path
        return q.lower().endswith(VID)
    if s.get("source") == "local_library" and q:  # bare folder — video-heavy?
        return _folder_video_ratio(q)
    return False


total = sum(s["duration_sec"] for s in scenes)
third = total / 3
t = 0.0
first, rest = [], []
for s in scenes:
    (first if t < third else rest).append((s["id"], is_video(s)))
    t += s["duration_sec"]

problems = []
note = None
if first and not first[0][1]:
    # БЫЛО hard problem (exit 1) — РАЗЖАЛОВАНО В ИНФО-СТРОКУ (user, 2026-10-08,
    # зло: "исключаем из правила первый кадр видео... топчетесь на одном месте
    # и какую-то ерунду явную подсовываете" — search-only канал не смог найти
    # реальное видео конкретного события, единственная альтернатива жёсткому
    # гейту была нерелевантный сток или AI-фабрикация). Видео для сцены 1
    # по-прежнему предпочтительно, когда есть осмысленный источник — но это
    # больше не блокер сборки.
    note = (f"сцена 1 — фото, а не видео (source_query -> "
            f"{scenes[0].get('source_query')}) — это больше не блокер "
            f"(правило отменено 2026-10-08), просто для сведения")

fv = sum(1 for _, v in first if v)
fp = len(first) - fv
need = len(first) // 2 + 1
if fv < need:
    problems.append(f"первая треть ({len(first)} сцен): видео {fv} / фото {fp} — "
                    f"видео должно ПРЕОБЛАДАТЬ. Нужно ≥{need} видео-вставок "
                    f"(перевести ещё {need - fv} фото-сцен на видео).")

photo_ids = [sid for sid, v in first if not v]

print(f"первая треть = {len(first)} сцен ({third:.0f}s из {total:.0f}s)")
print(f"  видео: {fv}   фото: {fp}")
if photo_ids:
    print(f"  фото-сцены в первой трети: {photo_ids}")
rv = sum(1 for _, v in rest if v)
print(f"остальные {len(rest)} сцен: видео {rv} / фото {len(rest)-rv} (баланс свободный)")
print()
if note:
    print("ИНФО (не блокер):", note)
if problems:
    # Формулировка смягчена 2026-10-16: раньше тут стояло «!! НАРУШЕНИЯ
    # ПРАВИЛА ЛИДА», и в выводе ship.sh это выглядело как упавшая проверка
    # посреди успешной отправки — вкладки тормозили и перечитывали вывод,
    # хотя по договорённости того же дня видео-лид НЕ блокирует ship
    # (блокируют только selfcheck и сверка сирот).
    print("~~ ВИДЕО-ЛИД НЕ ВЫПОЛНЕН (предупреждение, отправку НЕ блокирует):")
    for p in problems:
        print("   -", p)
    sys.exit(1)
print("OK — правило видео-лида соблюдено.")
