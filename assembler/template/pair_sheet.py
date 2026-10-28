#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pair_sheet.py — контактный лист ПАРАМИ: слева базовый кадр сцены, справа её
всплывашка. Рождён 2026-10-15: раздельные листы не дают увидеть дубль субъекта
(«Путин на картинке и выскакивает опять Путин»), а selfcheck сравнивает только
СЛОВА запросов и такой дубль пропускает.

    python3 pair_sheet.py <project_dir> [out_dir]
"""
import glob, json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

# ПОДПИСИ ПО-РУССКИ ТРЕБУЮТ TTF (2026-10-17): без font= PIL берёт свой
# битмап-шрифт без кириллицы, и «СЦЕНА 12 — слева КАДР…» рендерится
# квадратиками-тофу. Проверяющий субагент читал только цифры и сверял
# сцены вручную по scenes.json.
try:
    F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
except OSError:
    F = ImageFont.load_default()

def frame(path, box):
    if path.lower().endswith(".mp4"):
        tmp = path + ".pairtmp.jpg"
        subprocess.run(["ffmpeg","-v","error","-ss","1","-i",path,"-vframes","1",tmp,"-y"],check=False)
        path = tmp if os.path.exists(tmp) else None
        if not path: return None
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None
    finally:
        if path.endswith(".pairtmp.jpg"):
            try: os.remove(path)
            except OSError: pass
    im.thumbnail(box)
    return im

def main():
    proj = sys.argv[1] if len(sys.argv) > 1 else "."
    # ПРИНИМАЕМ И ПАПКУ, И `scenes.json` (28.10, улов вкладки «Круговая
    # оборона»: споткнулась подряд на обоих — соседние инструменты берут
    # scenes.json, а эти ждали ПАПКУ и падали `NotADirectoryError`).
    if proj and not os.path.isdir(proj):
        if proj.endswith(".json"):
            proj = os.path.dirname(os.path.abspath(proj)) or "."
        else:
            print("ОШИБКА: %r — не папка и не scenes.json" % proj, file=sys.stderr)
            sys.exit(2)

    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(proj, "pair_sheet")
    os.makedirs(out, exist_ok=True)
    ov = json.load(open(os.path.join(proj, "overlays.json"), encoding="utf-8"))
    # ТОЛЬКО СЦЕНЫ С ФОТО-ВСПЛЫВАШКОЙ (2026-10-18). Раньше пары строились по
    # ВСЕМ записям `overlays.json`, включая текстовые, у которых правой
    # половины не существует: на 6 фото и 29 текстовых вышло ВОСЕМЬ листов, и
    # оба проверяющих честно отчитались «18 из 20 пар пустые» — половина их
    # работы ушла в никуда. Лист предназначен для сверки пары «база ↔ фото
    # поверх неё», текстовые проверяются иначе (`check_overlay_overlap.py`
    # с 18.10 рисует их настоящим рендером).
    ids = sorted(int(k) for k in ov
                 if k.isdigit() and isinstance(ov[k], dict) and ov[k].get("photo"))
    _skipped = sum(1 for k in ov if k.isdigit() and isinstance(ov[k], dict)
                   and not ov[k].get("photo"))
    if _skipped:
        print("пропущено записей без фото (текстовые): %d" % _skipped)
    CW, CH, ROWS = 760, 300, 5          # пара в строке: 2 кадра по 380
    sheets, row, sheet_no = [], 0, 1
    img = Image.new("RGB", (CW, CH*ROWS), (12,12,12)); dr = ImageDraw.Draw(img)
    for sid in ids:
        b = [p for p in glob.glob(os.path.join(proj,"images","scene_%03d.*"%sid))
             if ".text." not in p and ".wmcrop." not in p]
        o = [p for p in glob.glob(os.path.join(proj,"overlays","scene_%03d.*"%sid))
             if ".text." not in p and ".wmcrop." not in p]
        y = row*CH
        dr.rectangle([0,y,CW,y+18], fill=(0,0,0))
        dr.text((6,y+4), "СЦЕНА %d — слева КАДР, справа ВСПЛЫВАШКА" % sid, font=F, fill=(255,230,0))
        for i,src in enumerate((b,o)):
            if src:
                im = frame(src[0], (370, CH-24))
                if im: img.paste(im, (i*380+4, y+20))
            else:
                dr.text((i*380+10, y+60), "нет файла", font=F, fill=(255,80,80))
        dr.line([(378,y+20),(378,y+CH-4)], fill=(90,90,90))
        row += 1
        if row == ROWS:
            p = os.path.join(out, "pair_%d.jpg" % sheet_no); img.save(p, quality=84)
            sheets.append(p); sheet_no += 1; row = 0
            img = Image.new("RGB", (CW, CH*ROWS), (12,12,12)); dr = ImageDraw.Draw(img)
    if row:
        p = os.path.join(out, "pair_%d.jpg" % sheet_no); img.save(p, quality=84); sheets.append(p)
    print("пар: %d  листов: %d  -> %s" % (len(ids), len(sheets), out))
    for p in sheets: print("  ", p)

if __name__ == "__main__":
    main()
