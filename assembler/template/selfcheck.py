#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Полная самопроверка сборки по SKILL.md ПЕРЕД тем как:
  - отдавать дашборд пользователю,
  - говорить «готово к собирай»,
  - запускать build_clips / assemble_final.

Обязательное правило (user, 2026-09-06, после 07.09-2: «делай самопроверку
каждого своего шага на полный цикл. Не делать ни одного действия лишнего
без самопроверки»). Косяк из задачи в задачу всплывает потому, что шаги
скилла пропускаются молча — этот скрипт их ловит.

Запуск:  python3 selfcheck.py <scenes.json> [images_dir]
Код возврата 0 = всё чисто. !=0 = есть НАРУШЕНИЯ, чинить до отдачи дашборда.
"""
import glob, hashlib, json, os, subprocess, sys

scenes_path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("*.scenes.json"))[0]
images = sys.argv[2] if len(sys.argv) > 2 else "images"
proj = os.path.dirname(os.path.abspath(scenes_path)) or "."
os.chdir(proj)

FAIL, WARN = [], []
d = json.load(open(scenes_path, encoding="utf-8"))
scenes = d["scenes"] if isinstance(d, dict) else d
meta = d.get("meta", {}) if isinstance(d, dict) else {}
ids = [s["id"] for s in scenes]
total = sum(s["duration_sec"] for s in scenes)

def asset(i):
    return [f for f in glob.glob(f"{images}/scene_{i:03d}.*") if not f.endswith(".json")]

needs = {}
if os.path.exists("needs_upload.json"):
    needs = json.load(open("needs_upload.json", encoding="utf-8"))

# 1. каждая сцена — либо файл, либо needs_upload
for i in ids:
    if not asset(i) and str(i) not in needs:
        FAIL.append(f"сцена {i}: нет ни картинки, ни записи в needs_upload.json")

# 2. format sniff — не-JPEG под .jpg (SKILL.md 2d)
for f in glob.glob(f"{images}/scene_*.jpg"):
    kind = subprocess.run(["file", "-b", f], capture_output=True, text=True).stdout
    if "JPEG" not in kind and "JFIF" not in kind:
        FAIL.append(f"{f}: не JPEG ({kind.strip()[:30]}) — build_clips подавится")

# 2b. oversized video source (user, 2026-09-16, furious — a whole 359s
# compilation reel got hand-pinned as a "single scene" clip and copied
# verbatim into images/, which build_clips_1080.py DOES trim correctly at
# build time (-t duration), but a source this large chokes/slows the live
# dashboard's thumbnail step and is a sign a long multi-shot compilation was
# used raw instead of being indexed (SKILL.md rule 3). Catch it before it
# ever reaches fetch/dashboard, not after.
for i, s in ((s["id"], s) for s in scenes):
    if s.get("source") != "local_library":
        continue  # pexels_video/press stock clips are legitimately longer than the cut; only a library exact-file pin risks being a whole compilation
    for f in asset(i):
        if not f.lower().endswith((".mp4", ".mov", ".webm")):
            continue
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", f], capture_output=True, text=True, timeout=10)
            src_dur = float(r.stdout.strip() or 0)
        except Exception:
            continue
        want = s["duration_sec"]
        if src_dur > max(30, want * 5):
            FAIL.append(f"{f}: источник {src_dur:.0f}с при нужных {want:.1f}с — похоже на "
                        f"целую нарезку/компиляцию, взятую как один клип (SKILL.md rule 3, "
                        f"index_library.py detect до использования, не голым файлом)")

# 3. дубли одного файла (no-repeat, SKILL.md rule 4/5)
h = {}
for f in glob.glob(f"{images}/scene_*.*") + glob.glob("overlays/scene_*.*"):
    if f.endswith((".json", ".text.png")):   # .text.png — рендер слова, дубли норм
        continue
    h.setdefault(hashlib.md5(open(f, "rb").read()).hexdigest(), []).append(os.path.basename(f))
for k, v in h.items():
    if len(v) > 1:
        FAIL.append(f"одинаковый файл в: {sorted(v)}")

# 4. overlays.json — ОБЯЗАН быть до дашборда, ~3/мин, anchor по каналу (SKILL.md 3b)
if not os.path.exists("overlays.json"):
    FAIL.append("overlays.json НЕТ — всплывашки не расставлены (SKILL.md 3b, обязательно ДО дашборда)")
else:
    ov = json.load(open("overlays.json", encoding="utf-8"))
    n_ov = len([k for k in ov if k != "anchor"])
    per_min = n_ov / (total / 60)
    # Плотность всплывашек — всегда ПРЕДУПРЕЖДЕНИЕ, не блокер: пользователь
    # удаляет лишние на дашборде (его правки = финал). ПЛАНЕТА целится в ~3/мин,
    # поиск-только идёт реже (прецедент «Чудовищные потери 2» ~1.3/мин).
    if per_min < 2.5:
        WARN.append(f"всплывашек {n_ov} ({per_min:.1f}/мин) — на ПЛАНЕТЕ ~3/мин; меньше — ок, если это твои правки")
    # у всех всплывашек пустой sound -> видеоряд выйдет без звука всплывашек
    # (feedback_overlays_sound_field_lost, 2026-09-08). Переприсвоить sound
    # (['whoosh','zatvor','pop'][i%3]) и локально прогнать build_overlays.py sfx.
    snd = [v.get("sound") or (v.get("text", {}).get("sound", "") if isinstance(v.get("text"), dict) else "")
           for k, v in ov.items() if k != "anchor"]
    if snd and not any(snd):
        FAIL.append("у ВСЕХ всплывашек sound='' — видеоряд соберётся БЕЗ звука "
                    "всплывашек. Переприсвоить sound в overlays.json.")
    ch = (meta.get("channel") or "").upper()
    want = "bottom" if "ПЛАНЕТА" in ch or "ПЛАНЕТА" == ch else "top"
    if ch and ov.get("anchor", "bottom") != want:
        FAIL.append(f"overlays anchor={ov.get('anchor','bottom')}, для канала {ch} нужен {want} (SKILL.md 3b)")
    for k, v in ov.items():
        if k == "anchor":
            continue
        ph = v.get("photo", "")
        tb = v.get("text") if isinstance(v.get("text"), dict) else None
        has_txt = bool(tb and str(tb.get("words") or tb.get("text") or "").strip())
        if not ph and has_txt:
            continue                       # чисто текст-всплывашка — фото не нужно
        if not os.path.exists(ph):
            FAIL.append(f"всплывашка {k}: файла нет ({ph})")
            continue
        oh = hashlib.md5(open(ph, "rb").read()).hexdigest()
        bf = asset(int(k))
        if bf and hashlib.md5(open(bf[0], "rb").read()).hexdigest() == oh:
            FAIL.append(f"всплывашка {k} = базовый кадр сцены (нельзя, SKILL.md 3b)")

    # 4b. всплывашка называет ТОГО ЖЕ человека/институт, что и базовый кадр —
    # не ловится md5 (два РАЗНЫХ файла одного и того же человека всё ещё
    # нарушение, user 2026-10-05/08: "Трамп всплывашка иллюстрирует Трампа",
    # "Сибига иллюстрирует Сибигу"). Сверяем имена собственные в запросах,
    # а не пиксели — работает даже когда это два разных фото одного лица.
    import re as _re
    def _names(text):
        # includes Ukrainian-only letters (і/ї/є/ґ) — without them a Cyrillic
        # word truncates mid-letter ("Київ"->"Ки", "Чернігівський"->"Черн")
        # and those stubs false-match across unrelated scenes (found live,
        # session 2026-10-08, peer session on an all-Ukrainian "5 МИНУТ" build).
        return set(_re.findall(r"[А-ЯЁІЇЄҐ][а-яёіїєґА-ЯЁІЇЄҐ]+", text or ""))
    _STOP = {"Украины", "Украина", "Украине", "Киев", "Киева", "Москва", "Москвы",
              "России", "Россия", "Верховная", "Рада", "Радой", "Радою", "НАТО",
              "МИД", "МЗС", "Кремль", "США", "ЕС", "Индии", "Индия",
              # Ukrainian/other-language forms of the same stop-words — without
              # these, a scene/overlay pair written in Ukrainian (or naming a
              # country other than RU/UA) false-flagged as a name collision
              # just because both mentioned "Україна"/"Ємен" (user_56 report,
              # cross-session, 2026-10-10). Add more language forms here as
              # they're caught, same spirit as the a3 cheat-sheet below.
              "Україна", "України", "Україні", "Україну", "Україною",
              "Київ", "Києва", "Києві", "Київу", "Москві", "Росія", "Росії",
              "Росію", "Росією", "ЗСУ", "Кремля", "Кремлі", "Ємен", "Ємену",
              "Йемен", "Йемену", "Йемена", "ЄС", "Індія", "Індії"}
    _by_id = {s["id"]: s for s in scenes}
    _ovq_path = None
    for _cand in glob.glob("*overlays_fetch*.json") + glob.glob("*overlay*fetch*.scenes.json"):
        _ovq_path = _cand
        break
    if _ovq_path and os.path.exists(_ovq_path):
        _ovq = {s["id"]: s.get("source_query", "") for s in json.load(open(_ovq_path, encoding="utf-8"))["scenes"]}
        for k, v in ov.items():
            if k == "anchor":
                continue
            sid = int(k)
            base_q = _by_id.get(sid, {}).get("source_query", "")
            ov_q = _ovq.get(sid, "")
            shared = (_names(base_q) - _STOP) & (_names(ov_q) - _STOP)
            if shared:
                FAIL.append(f"всплывашка {k}: тот же человек/объект ({', '.join(sorted(shared))}) "
                            f"что и базовый кадр — база: {base_q!r}, всплывашка: {ov_q!r}")

# 5. видео-лид (SKILL.md rule 7) — ПРЕДУПРЕЖДЕНИЕ, не блокер: пользователь
# может сознательно наменять фото в первой трети на дашборде (его правки =
# финал). Флагаем, чтобы он знал, но сборку не держим.
r = subprocess.run(["python3", "check_lead.py", scenes_path, images],
                   capture_output=True, text=True)
if r.returncode != 0:
    WARN.append("видео-лид не выполнен (см. ниже) — ок, если это твои правки на дашборде:\n     "
                + (r.stdout + r.stderr).strip().replace("\n", "\n     ")[:400])

# 6. сцена 1 = видео — БЫЛО hard FAIL, РАЗЖАЛОВАНО В WARN (user, 2026-10-08,
# зло: "исключаем из правила первый кадр видео... топчетесь на одном месте и
# какую-то ерунду явную подсовываете" — после того как search-only канал
# (5 МИНУТ) не смог найти реальное видео конкретного события ни с одной
# формулировкой запроса, и единственной альтернативой жёсткому гейту было
# либо нерелевантный сток, либо AI-фабрикация). Правило "видео лучше, если
# есть осмысленное" остаётся советом (см. ниже), но больше не блокер.
any_video = any(a and a[0].endswith((".mp4", ".mov")) for a in (asset(i) for i in ids))
a1 = asset(ids[0])
if a1 and not a1[0].endswith((".mp4", ".mov")):
    if any_video:
        WARN.append(f"сцена {ids[0]} не видео (было бы по старому правилу видео-лида, "
                    "но правило сцена-1=видео отменено 2026-10-08 — это не блокер)")
    else:
        WARN.append("во всём ролике нет ни одного видео — весь видеоряд из фото (Ken Burns). "
                    "Ок для канала на поиске-только; для ПЛАНЕТЫ так быть не должно.")

print("=" * 60)
print(f"САМОПРОВЕРКА: {scenes_path}  ({len(scenes)} сцен, {total:.0f}с, канал {meta.get('channel','?')})")
print("=" * 60)
if WARN:
    print("\n⚠ ПРЕДУПРЕЖДЕНИЯ:")
    for w in WARN:
        print("  -", w)
if FAIL:
    print(f"\n❌ НАРУШЕНИЙ: {len(FAIL)} — чинить ДО отдачи дашборда:")
    for x in FAIL:
        print("  -", x)
    sys.exit(1)
print("\n✅ всё чисто — дашборд можно отдавать")
