# -*- coding: utf-8 -*-
"""ГЕЙТ «ДЕТИ И ДЕТСКИЕ ПЛОЩАДКИ» — НИ ОДИН ТАКОЙ КАДР НЕ ДОХОДИТ ДО ДАШБОРДА.

Повод (10.11, его слово по сданному ролику «ЗЕ готов в Антарктиде»):
«У нас есть строжайший запрет: ни дети, ни детские площадки в кадр не
попадают» и следом, когда вкладка стала объяснять, откуда взялся кадр:
«Да мне пофиг, где она была, в базе или не в базе, скачана, не скачана —
НЕ ДОЛЖНО БЫТЬ НА ДАШБОРДЕ. Она не должна туда попадать».

Почему мин в запросах не хватило. `query_lint` чистит ЗАПРОС («школ», «дет»,
«семь»), но кадр приходит не только из запроса: его даёт база кадров
(`local_library`), вложение телеграма, ручная подмена, карточка арсенала.
В тот раз папка базы называлась ДВОР-МНОГОЭТАЖЕК-КИЕВА, запрос был чистый,
а все одиннадцать файлов в папке оказались детскими площадками.
Поэтому гейт смотрит НЕ запрос, а САМ КАДР, и стоит перед дашбордом.

Три команды:

    python3 deti_gate.py listy  <проект>            # собрать листы на просмотр
    python3 deti_gate.py verdikt <проект> --bad 5,12 [--vse-chisto]
    python3 deti_gate.py check  <проект>            # гейт: 0 — чисто, 1 — нет

Кто смотрит листы: СУБАГЕНТ вкладки (дёшево, свой контекст, картинки в
основной поток не копятся) или внешний агент. На машине пользователя не
считается ничего, кроме склейки готовых миниатюр (~1 с на ролик).

Гейт зовут `selfcheck.py` (не отдаёт дашборд) и `cloud/ship.sh` (не собирает
ролик). Обход — только `VIDEORYAD_NO_DETI=1` и только по его прямому слову
про этот ролик.
"""
import argparse
import glob
import json
import os
import sys
import time

MARKER = "deti"
VERDICT = os.path.join(MARKER, "verdict.json")
LISTS = os.path.join(MARKER, "lists")
# Сколько миниатюр кладём на один лист: 24 хватает, чтобы площадка была видна
# глазом, и держит число картинок у смотрящего в рамках правила 23.10
# (потолок 25 изображений на субагента).
PER_SHEET = 24
COLS = 6
CELL_W, CELL_H = 320, 200


def _project_dir(p):
    return os.path.abspath(os.path.expanduser(p))


def _scenes_file(pdir):
    """Рабочий scenes.json проекта (не сырой файл агента `codex*.json`)."""
    cands = [f for f in glob.glob(os.path.join(pdir, "*.scenes.json"))
             if not os.path.basename(f).startswith(("codex", "lib_", "raw"))]
    if not cands:
        cands = glob.glob(os.path.join(pdir, "*.scenes.json"))
    return cands[0] if cands else None


def _scene_ids(pdir):
    sf = _scenes_file(pdir)
    if not sf:
        return []
    try:
        d = json.load(open(sf, encoding="utf-8"))
    except Exception:
        return []
    sc = d.get("scenes", d) if isinstance(d, dict) else d
    return [int(s["id"]) for s in sc if "id" in s]


def _frame_for(pdir, sid):
    """Картинка сцены для листа: сперва готовая миниатюра (её уже посчитали —
    облако или дашборд), потом сам кадр. Видео берём ТОЛЬКО если от него уже
    есть кадр-миниатюра: декодировать mp4 ради листа значит считать на его
    машине, а это запрещено (23.10)."""
    images = os.path.join(pdir, "images")
    for p in (os.path.join(images, ".rev", f"{sid:03d}.jpg"),
              os.path.join(pdir, "thumbs", f"{sid:03d}.jpg")):
        if os.path.exists(p):
            return p
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(images, f"scene_{sid:03d}{ext}")
        if os.path.exists(p):
            return p
    p = os.path.join(images, f"scene_{sid:03d}.mp4.revframe.jpg")
    if os.path.exists(p):
        return p
    # ВИДЕО-СЦЕНА БЕЗ ГОТОВОЙ МИНИАТЮРЫ. Площадка может быть и в клипе, так
    # что пропускать такие сцены нельзя — дыра в гейте. Снимаем ОДИН кадр
    # (0,1-0,3 с на сцену, десяток сцен на ролик) и кладём рядом, чтобы
    # второй раз не считать. Это единственный счёт этого инструмента на
    # машине пользователя; всё остальное берётся готовым.
    src = os.path.join(images, f"scene_{sid:03d}.mp4")
    if os.path.exists(src):
        import subprocess
        ff = os.environ.get("FFMPEG_BIN", "ffmpeg")
        try:
            subprocess.run([ff, "-nostdin", "-v", "error", "-ss", "1", "-i", src,
                            "-frames:v", "1", "-vf", "scale=400:-1", "-threads", "1",
                            "-y", p], capture_output=True, timeout=25)
        except Exception:
            return None
        if os.path.exists(p):
            return p
    return None


def cmd_listy(args):
    from PIL import Image, ImageDraw
    pdir = _project_dir(args.project)
    ids = _scene_ids(pdir)
    if not ids:
        print("deti_gate: не нашёл scenes.json — нечего проверять", file=sys.stderr)
        return 2
    out_dir = os.path.join(pdir, LISTS)
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.jpg")):
        os.remove(old)

    pairs = [(sid, _frame_for(pdir, sid)) for sid in ids]
    have = [(s, f) for s, f in pairs if f]
    missing = [s for s, f in pairs if not f]

    sheets = []
    for start in range(0, len(have), PER_SHEET):
        chunk = have[start:start + PER_SHEET]
        rows = (len(chunk) + COLS - 1) // COLS
        sheet = Image.new("RGB", (CELL_W * COLS, CELL_H * rows), (18, 18, 18))
        d = ImageDraw.Draw(sheet)
        for i, (sid, path) in enumerate(chunk):
            try:
                im = Image.open(path)
                im.thumbnail((CELL_W - 8, CELL_H - 26))
            except Exception:
                continue
            x = (i % COLS) * CELL_W + 4
            y = (i // COLS) * CELL_H + 22
            sheet.paste(im, (x, y))
            d.text((x, y - 18), f"сцена {sid}", fill=(255, 225, 70))
        name = os.path.join(out_dir, f"list_{len(sheets) + 1:02d}.jpg")
        sheet.save(name, quality=80)
        sheets.append(name)

    meta = {"ids": ids, "sheets": sheets, "missing": missing, "ts": time.time()}
    json.dump(meta, open(os.path.join(pdir, MARKER, "lists.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"листов: {len(sheets)} (сцен {len(have)} из {len(ids)})")
    for s in sheets:
        print("  " + s)
    if missing:
        print(f"без картинки пока: {len(missing)} сцен — {missing[:12]}")
    print("\nЧТО СПРОСИТЬ У СМОТРЯЩЕГО (субагент, не основной поток):")
    print("  «Назови номера сцен, где есть ребёнок, подросток, школьник ИЛИ")
    print("   детская площадка — в том числе ПУСТАЯ: горка, качели, песочница,")
    print("   школьный двор, детский сад. Даже мелко на заднем плане.»")
    print("Потом: python3 deti_gate.py verdikt <проект> --bad 5,12  (или --vse-chisto)")
    return 0


def cmd_verdikt(args):
    pdir = _project_dir(args.project)
    ids = _scene_ids(pdir)
    bad = []
    if args.bad:
        for part in str(args.bad).replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                bad.append(int(part))
    if not args.vse_chisto and not bad:
        print("deti_gate: назови --bad <номера> или подтверди --vse-chisto",
              file=sys.stderr)
        return 2
    os.makedirs(os.path.join(pdir, MARKER), exist_ok=True)
    v = {"checked": ids, "bad": sorted(set(bad)), "ts": time.time(),
         "kto": args.kto or "субагент вкладки"}
    json.dump(v, open(os.path.join(pdir, VERDICT), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if bad:
        print(f"записано: брак в сценах {v['bad']} — замени кадры и прогони листы заново")
    else:
        print(f"записано: чисто, просмотрено сцен {len(ids)}")
    return 0


# ГЕЙТ ДЕЙСТВУЕТ СО СЛЕДУЮЩЕГО РОЛИКА, А НЕ ЗАДНИМ ЧИСЛОМ (10.11, его прямое
# слово через полчаса после установки: «они ничего не должны переделывать,
# это просто на следующий ролик… вот сборка идёт — какая будет, такая пускай
# приезжает»). Проект, начатый ДО этой отметки, гейт пропускает с одной
# строкой предупреждения: ломать идущие сборки запрещено.
GATE_SINCE = 1794320000.0   # 2026-11-10 14:13 (момент установки)


def _started_before_gate(pdir):
    """Когда ролик НАЧАТ. По `scenes.json` судить нельзя: его переписывает
    каждый круг правок, и идущий со вчера ролик выглядел бы новым. Берём то,
    что кладётся один раз и не меняется, — озвучку и `.srt`; если их нет,
    саму папку."""
    stamps = []
    for pat in ("narration.*", "*.srt", "*.mp3"):
        for f in glob.glob(os.path.join(pdir, pat)):
            try:
                stamps.append(os.path.getmtime(f))
            except OSError:
                pass
    if not stamps:
        try:
            stamps.append(os.path.getmtime(pdir))
        except OSError:
            return False
    return min(stamps) < GATE_SINCE


def cmd_check(args):
    """ГЕЙТ. Код 0 — можно отдавать дашборд и собирать; 1 — нельзя."""
    pdir = _project_dir(args.project)
    if os.environ.get("VIDEORYAD_NO_DETI") == "1":
        print("deti_gate: ОБХОД VIDEORYAD_NO_DETI=1 — только по его прямому слову")
        return 0
    if _started_before_gate(pdir) and not os.path.exists(os.path.join(pdir, VERDICT)):
        print("ДЕТИ: ролик начат до установки гейта (10.11 14:20) — пропускаю, "
              "проверка обязательна начиная со СЛЕДУЮЩЕГО ролика")
        return 0
    ids = _scene_ids(pdir)
    vp = os.path.join(pdir, VERDICT)
    if not os.path.exists(vp):
        print("ДЕТИ: проверка не делалась вовсе.", file=sys.stderr)
        print("  python3 ~/.claude/skills/news-video/template/deti_gate.py listy "
              + pdir, file=sys.stderr)
        return 1
    try:
        v = json.load(open(vp, encoding="utf-8"))
    except Exception:
        print("ДЕТИ: вердикт нечитаем — прогони проверку заново", file=sys.stderr)
        return 1
    bad = [int(x) for x in v.get("bad", [])]
    if bad:
        print(f"ДЕТИ: в сценах {bad} ребёнок или детская площадка — заменить кадры",
              file=sys.stderr)
        return 1
    checked = set(int(x) for x in v.get("checked", []))
    new = [i for i in ids if i not in checked]
    if new:
        print(f"ДЕТИ: сцены {new[:12]} появились после проверки — прогони листы заново",
              file=sys.stderr)
        return 1
    print(f"ДЕТИ: чисто ({len(checked)} сцен просмотрено)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("listy", help="собрать контактные листы на просмотр")
    a.add_argument("project")
    a.set_defaults(func=cmd_listy)
    b = sub.add_parser("verdikt", help="записать вердикт смотрящего")
    b.add_argument("project")
    b.add_argument("--bad", help="номера сцен с детьми/площадками через запятую")
    b.add_argument("--vse-chisto", action="store_true", dest="vse_chisto")
    b.add_argument("--kto", help="кто смотрел")
    b.set_defaults(func=cmd_verdikt)
    c = sub.add_parser("check", help="гейт: 0 — чисто, 1 — нельзя отдавать")
    c.add_argument("project")
    c.set_defaults(func=cmd_check)
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
