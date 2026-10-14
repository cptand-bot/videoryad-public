#!/usr/bin/env python3
"""Пост-сборочный шаг для каналов, которые берут кадры из медиатеки
(«ПЛАНЕТА»-тип, НЕ search-only каналы).

После доставки готового видеоряда — разложить файлы, что лежали в
`media-library/ПОЛИТИКА/1-NA SEGODNIA/` под эту сборку, по тематическим
папкам библиотеки и опустошить SEGODNIA. Разложить ВСЕ файлы, что были в
папке на момент сборки — вошёл файл в финальное видео или нет, неважно
(user, 2026-09-04: «попапкам разложить, даже если он не вошёл»).

Классификация:
  - Файл нашёлся (по md5) среди images/ или overlays/ проекта -> берём тему
    сцены, в которую он встал (bucket из visual_prompt "[bucket] текст…"),
    маппим на папку библиотеки.
  - Файл не нашёлся нигде (в сборку не попал) -> смотрим на сам файл
    (имя + первые кадры/картинку) и решаем по смыслу; если реально неясно —
    НЕ гадаем, оставляем в SEGODNIA и печатаем отдельным списком «уточни».

Длинные многосюжетные видео (не 5-15с кусок) — сначала `index_library.py
detect --single` + `tag 0 <ключевые_слова_темы>`, потом уже move — чтобы
в библиотеке лежал не голый файл, а индексированный.

Только move (никогда delete). Новая папка темы -> создаём, печатаем
уведомление, в тихую не создаём.

Запуск: python3 file_away_segodnia.py <project_dir> <scenes.json> [--dry-run]
  [--folder "2-NA SEGODNIA"] [--assign имя_файла.jpg=ПОЛИТИКА/ПАПКА ...]

--folder — если в этот день несколько роликов, у каждого своя staging-папка
(1-NA SEGODNIA, 2-NA SEGODNIA, ...); по умолчанию 1-NA SEGODNIA.

--assign — для файлов, что не вошли ни в одну сцену этой сборки (скрипт их
сам не смотрит, только по md5 сверяет с images/overlays): Claude открывает
файл (Read), решает по смыслу и передаёт сюда явно, вместо угадывания.
"""
import hashlib, json, os, re, shutil, subprocess, sys, glob

ML = os.environ.get("MEDIA_LIBRARY_DIR") or os.path.expanduser("~/projects/media-library")
# несколько роликов в один день -> несколько параллельных staging-папок
# (1-NA SEGODNIA, 2-NA SEGODNIA, ...) — какую разбирать, передаётся явно
# через --folder "2-NA SEGODNIA" (user, 2026-09-16); дефолт держит старое
# поведение для одиночного ролика в день.
SEGODNIA_NAME = "1-NA SEGODNIA"
if "--folder" in sys.argv:
    SEGODNIA_NAME = sys.argv[sys.argv.index("--folder") + 1]
SEGODNIA = os.path.join(ML, "ПОЛИТИКА", SEGODNIA_NAME)
INDEX_LIB = os.path.join(os.path.dirname(__file__), "..", "..", "script-to-video", "template", "index_library.py")
INDEX_LIB = os.path.normpath(INDEX_LIB) if os.path.exists(os.path.normpath(INDEX_LIB)) else \
    os.path.expanduser("~/.claude/skills/script-to-video/template/index_library.py")

# бакет классификатора -> папка библиотеки + ключевые слова для авто-тега
BUCKET_DEST = {
 "putin": ("ПОЛИТИКА/ПУТИН", ["putin"]),
 "kremlin_voice": ("ПОЛИТИКА/РОССИЯ", ["россия", "кремль"]),
 "budanov": ("ПОЛИТИКА/БУДАНОВ", ["буданов"]),
 "zelensky": ("ПОЛИТИКА/ЗЕЛЕНСКИЙ", ["zelensky"]),
 "usmed": ("ПОЛИТИКА/США-РФ", ["сша", "переговоры"]),
 "talks": ("ПОЛИТИКА/Украина-РФ-Переговоры", ["переговоры"]),
 "front": ("ПОЛИТИКА/SVO", ["фронт", "война"]),
 "map": ("ПОЛИТИКА/SVO", ["карта", "фронт"]),
 "cities": ("ПОЛИТИКА/УКРАИНА ВСУ и Азов", ["донбасс", "город"]),
 "logi": ("ПОЛИТИКА/УКРАИНА", ["логистика", "склад"]),
 "ports": ("ПОЛИТИКА/ODESSA-portiUKRAINI", ["одесса", "порт"]),
 "border": ("ПОЛИТИКА/УКРАИНА", ["граница"]),
 "npz": ("ПОЛИТИКА/НЕФТЬ", ["нпз", "нефть"]),
 "ruwar": ("ПОЛИТИКА/НЕФТЬ", ["нефть", "удар"]),
 "rustores": ("ПОЛИТИКА/РОССИЯ", ["склад", "россия"]),
 "drone": ("ПОЛИТИКА/ДРОНЫ", ["дрон"]),
 "pvo": ("ПОЛИТИКА/ПВО-укр", ["пво", "украина"]),
 "mobil": ("ПОЛИТИКА/Мобилизация-УКР", ["мобилизация", "украина"]),
 "mobil_ru": ("ПОЛИТИКА/MOBILIZACIYA", ["мобилизация", "россия"]),
 "mobil_ua": ("ПОЛИТИКА/Мобилизация-УКР", ["мобилизация", "украина"]),
 "energy": ("ПОЛИТИКА/УКРАИНА", ["энергетика"]),
 "food": ("ПОЛИТИКА/УКРАИНА", ["логистика"]),
 "people": ("ПОЛИТИКА/УКРАИНА", ["мирные", "разрушения"]),
 "money": ("ПОЛИТИКА/РОССИЯ", ["экономика"]),
 "usmed_alt": ("ПОЛИТИКА/ВИТКОФФ-КУШНЕР", ["witkoff", "kushner"]),
}

def md5(p):
    try:
        return hashlib.md5(open(p, "rb").read()).hexdigest()
    except OSError:
        return None

def bucket_of(scene):
    m = re.match(r"\[([a-z_]+)", scene.get("visual_prompt", "") or "")
    return m.group(1) if m else None

def is_long_video(path, ffprobe="ffprobe"):
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".mp4", ".mov", ".mkv", ".webm"):
        return False
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=15)
        dur = float(r.stdout.strip() or 0)
        return dur > 20 or os.path.getsize(path) > 15 * 1024 * 1024
    except Exception:
        return os.path.getsize(path) > 15 * 1024 * 1024

def dest_path(folder_rel, fname):
    d = os.path.join(ML, folder_rel)
    os.makedirs(d, exist_ok=True)
    base, ext = os.path.splitext(fname)
    p = os.path.join(d, fname)
    n = 1
    while os.path.exists(p):
        p = os.path.join(d, f"{base}_{n}{ext}")
        n += 1
    return p

def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    proj, scenes_path = sys.argv[1], sys.argv[2]
    dry = "--dry-run" in sys.argv
    assign = {}
    if "--assign" in sys.argv:
        i = sys.argv.index("--assign") + 1
        while i < len(sys.argv) and "=" in sys.argv[i]:
            fn, folder = sys.argv[i].split("=", 1)
            assign[fn] = folder
            i += 1

    if not os.path.isdir(SEGODNIA):
        print(f"папки {SEGODNIA_NAME} нет — нечего делать"); return
    files = [f for f in glob.glob(os.path.join(SEGODNIA, "*"))
             if os.path.isfile(f) and not f.endswith((".json",))]
    if not files:
        print(f"{SEGODNIA_NAME} пустая — нечего разбирать"); return

    scenes = json.load(open(os.path.join(proj, scenes_path), encoding="utf-8"))["scenes"]
    S = {s["id"]: s for s in scenes}

    # индекс md5 -> сцена, по images/ и overlays/ этого проекта
    used_by = {}
    for d in ("images", "overlays"):
        for p in glob.glob(os.path.join(proj, d, "scene_*.*")):
            m = re.search(r"scene_(\d+)", os.path.basename(p))
            if not m:
                continue
            h = md5(p)
            if h:
                used_by.setdefault(h, S.get(int(m.group(1))))

    filed, unclear = [], []
    for f in sorted(files):
        fname = os.path.basename(f)
        if fname in assign:
            folder_rel, tags = assign[fname], []
        else:
            h = md5(f)
            scene = used_by.get(h)
            bucket = bucket_of(scene) if scene else None
            dest = BUCKET_DEST.get(bucket) if bucket else None
            if not dest:
                unclear.append((f, scene["text"][:60] if scene else "(не вошёл ни в одну сцену этой сборки)"))
                continue
            folder_rel, tags = dest
        new_folder = not os.path.isdir(os.path.join(ML, folder_rel))
        if dry:
            filed.append((f, folder_rel, "DRY-RUN"))
            continue
        target = f
        if is_long_video(f):
            try:
                subprocess.run(["python3", INDEX_LIB, "detect", f, "--single"],
                               check=True, capture_output=True, text=True, timeout=120)
                subprocess.run(["python3", INDEX_LIB, "tag", f, "0"] + tags,
                               check=True, capture_output=True, text=True, timeout=30)
            except Exception as e:
                print(f"  [!] индексация не удалась для {os.path.basename(f)}: {e}")
        dst = dest_path(folder_rel, os.path.basename(f))
        shutil.move(f, dst)
        filed.append((f, folder_rel, "новая папка" if new_folder else ""))

    print(f"\nРазложено: {len(filed)}")
    for f, folder, note in filed:
        print(f"  {os.path.basename(f)} -> {folder}" + (f"  [{note}]" if note else ""))
    if unclear:
        print(f"\nНе понял, куда класть ({len(unclear)}) — оставлены в {SEGODNIA_NAME}, уточни:")
        for f, why in unclear:
            print(f"  {os.path.basename(f)} — {why}")
    if not dry:
        print(f"\n{SEGODNIA_NAME}: осталось файлов {len(glob.glob(os.path.join(SEGODNIA,'*')))}")

if __name__ == "__main__":
    main()
