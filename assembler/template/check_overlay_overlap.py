#!/usr/bin/env python3
"""Render each overlay scene's REAL 1920x1080 composite (base image cover-
cropped the way build_clips_1080.py frames it) with a red rectangle showing
exactly where the pop-up photo will sit (overlay_geom's own seeded math,
copied from review.py so it stays in lockstep). Tiles the results into
contact sheets under <project>/overlap_check/.

Why this exists: a pop-up's corner position is seeded per scene id and has
no idea where a face sits in the base photo — for a single person speaking
to camera (very common: podiums, interviews, press conferences) the face is
often dead-center-top or center, which is exactly where an `anchor: top`
channel's pop-ups land by default. Caught live (user, 2026-10-04, ОЛЬКА
"Алиев" build): 13 of 39 pop-ups landed squarely on the speaker's face.

Usage: python3 check_overlay_overlap.py [project_dir]
   (defaults to cwd)

Fix for a flagged scene: edit overlays.json directly, add/adjust that
scene's "style" (left/right/up-center/up-left/up-right) and/or "scale"
(0.4-2.4) to push the box into empty space, then re-run this script to
confirm before handing the dashboard over. No rebuild needed — this reads
overlays.json fresh every run.
"""
import glob
import json
import os

BADGE_H = 22          # поле под плиткой для номера сцены (2026-10-19)
import random
import subprocess
import sys

W, H = 1920, 1080


def overlay_geom(sid, spec, photo_path, anchor):
    HMIN, HMAX = H // 3, H // 2
    HBY = {"s": (HMIN, HMIN + 55), "m": (HMIN + 70, HMAX - 45), "l": (HMAX - 45, HMAX)}
    PICK = ["s", "s", "m", "m", "m", "l", "l", "l"]
    rnd = random.Random(sid)
    cls = spec.get("size") or rnd.choice(PICK)
    hlo, hhi = HBY.get(cls, HBY["m"])
    bh = rnd.randint(hlo, hhi)
    ar = 1.4
    if photo_path and os.path.exists(photo_path):
        try:
            from PIL import Image
            with Image.open(photo_path) as _im:
                ar = _im.width / _im.height
        except Exception:
            pass
    if ar < 1.0:
        bh = HMAX
        cls = "l"
    bw = int(bh * ar)
    bw = max(int(bh * 0.75), min(bw, int(W * 0.62)))
    margin = rnd.randint(40, 72)
    style = spec.get("style") or "up-center"
    shape = (spec.get("shape") or "rect").lower()
    if shape not in ("rect", "rounded", "square", "circle"):
        shape = "rect"
    if shape in ("square", "circle"):
        bw = bh
    try:
        msc = float(spec.get("scale", 1.0))
    except (TypeError, ValueError):
        msc = 1.0
    msc = max(0.4, min(2.4, msc))
    bh = max(120, min(int(bh * msc), int(H * 0.92)))
    bw = max(90, min(int(bw * msc), int(W * 0.92)))
    if shape in ("square", "circle"):
        bw = bh
    dw, dh = bw + 18, bh + 18
    if shape == "circle":
        dw = dh = bh
    if "left" in style:
        x = margin
    elif "right" in style:
        x = W - dw - margin
    else:
        x = (W - dw) // 2
    # «middle» поддержан наравне с top/bottom: его чтит `build_overlays.py`
    # ((H-h)/2), а здесь он падал в ветку «снизу» — рамка рисовалась не там,
    # где кадр её получит (03.11, вместе с правкой про anchor у записи).
    _a = str(anchor).lower()
    y = (margin if _a == "top"
         else ((H - dh) // 2 if _a == "middle" else H - dh - margin))
    return x, y, dw, dh


def base_frame(images_dir, sid):
    for ext in (".jpg", ".jpeg", ".png", ".mp4", ".mov"):
        p = os.path.join(images_dir, f"scene_{sid:03d}{ext}")
        if os.path.exists(p):
            if ext in (".mp4", ".mov"):
                out = f"/tmp/overlap_check_base_{sid:03d}.jpg"
                subprocess.run(["ffmpeg", "-y", "-ss", "1", "-i", p, "-frames:v", "1",
                                 "-update", "1", out], capture_output=True)
                return out
            return p
    return None


def cover_crop(im, w, h):
    iw, ih = im.size
    scale = max(w / iw, h / ih)
    nw, nh = int(iw * scale) + 1, int(ih * scale) + 1
    im2 = im.resize((nw, nh))
    x0 = (nw - w) // 2
    y0 = (nh - h) // 2
    return im2.crop((x0, y0, x0 + w, y0 + h))



# --- ТЕКСТОВЫЕ ВСПЛЫВАШКИ: ГЕОМЕТРИЯ ИЗ `build_overlays` (2026-10-18) ---
# До этого схема их НЕ МОДЕЛИРОВАЛА ВООБЩЕ и для текстовой записи рисовала
# рамку по геометрии ФОТО-всплывашки. При преобладании текста схема не молчит,
# а ЛЖЁТ: на ролике с 33 текстовыми из 39 проверяющий выдал 12 вердиктов о
# перекрытии лиц, которые физически не могли быть верными. Вкладка написала
# разовый рендер, им и вскрыла правду — встраиваем, чтобы не писать заново.
# Числа повторяют `_apply_text_overlay`: th = H/6 * scale (клампы 60 и H/2),
# tw = th * пропорция PNG (клампы W*0.92), поле 60, сетка 9 позиций,
# и `force_original_aspect_ratio=decrease` — то есть картинка ВПИСЫВАЕТСЯ в
# tw x th с сохранением пропорций, реальный размер меньше.
def text_geom(sid, spec, tmp_dir, proj=""):
    ts = spec.get("text") or {}
    words = str(ts.get("words") or "").strip()
    if not words:
        return None
    # НАДПИСЬ ИЗ-ПОД МАСКИ СЧИТАЕТСЯ НЕ ЗДЕСЬ, А ТАМ ЖЕ, ГДЕ ДАШБОРД И
    # СБОРКА (09.11). Лист перекрытий с этого дня — ТРЕТИЙ обязательный слой
    # осмотра кадров: по нему решают, не легла ли плашка на лицо или на окно
    # видеовставки. А он мерил маску формулой обычной надписи (`th = H/6`) и
    # рисовал её ОБЫЧНЫМ стилем «5 МИНУТ» — то есть показывал проверяющему не
    # ту картинку не на том месте. На живом ролике ПЛАНЕТЫ расхождение по
    # ширине доходило до 800 px: лист рисовал почти во весь кадр (1766) там,
    # где в видео ляжет 966. Ложное «чисто» на тесном кадре рождается именно
    # так. Поэтому тут ровно один механизм на три места: место и размер даёт
    # `review.overlay_text_geom`, картинку — `review.mask_text_png`, оба
    # зеркалят `build_overlays._apply_mask_overlay`. Ветвлений по каналу нет:
    # канал решает только цвет внутри рисовалки.
    png = os.path.join(tmp_dir, "ovl_%03d.png" % sid)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from review import mask_text_png, overlay_text_geom
        if str(ts.get("style") or "").lower().startswith("mask"):
            # маску рисует её собственная рисовалка — иначе на листе окажется
            # чужой формат (обычная плашка 5 МИНУТ вместо золотой маски)
            if not mask_text_png(ts, png, proj)[0]:
                return None
        else:
            from build_overlays import _render_text_png
            if not _render_text_png(words, ts.get("color", "white"), png,
                                    ts.get("font", "default")):
                return None
        # МЕСТО И РАЗМЕР — ОДНОЙ ФУНКЦИЕЙ НА ТРИ МЕСТА (09.11). Своего счёта
        # здесь не осталось НИ У ОДНОГО вида надписи: разбор `pos` тоже уходит
        # в `review._pos_ok`, который поднимает низ наверх ровно так, как это
        # делает сборка. Прежний разбор низ ПРИНИМАЛ — и на первом же ролике с
        # `pos: bc` лист нарисовал бы надпись внизу, тогда как в видео она
        # уезжает вверх: проверка перекрытий соврала бы в опасную сторону,
        # показав «чисто» там, где надпись ложится на лицо.
        g = overlay_text_geom(ts, png, sid)
    except Exception:
        return None
    return (int(round(g["xf"] * W)), int(round(g["yf"] * H)),
            int(round(g["wf"] * W)), int(round(g["hf"] * H)), png)


def main():
    from PIL import Image, ImageDraw

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

    # ИМЯ ПРОЕКТА НУЖНО НАДПИСИ ИЗ-ПОД МАСКИ: цвет приходит ПО КАНАЛУ, а
    # канал весь сборщик берёт ИЗ ПУТИ (09.11). Отдельного ключа не заводим.
    _projname = os.path.basename(os.path.abspath(proj))
    ov_path = os.path.join(proj, "overlays.json")
    images_dir = os.path.join(proj, "images")
    out_dir = os.path.join(proj, "overlap_check")

    import tempfile
    _tmp = tempfile.mkdtemp(prefix="ovlchk_")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ov = json.load(open(ov_path, encoding="utf-8"))
    # ANCHOR БЕРЁТСЯ У КАЖДОЙ ЗАПИСИ, А НЕ ТОЛЬКО ОБЩИЙ (03.11, улов
    # `usuario-1f`). `build_overlays.py` чтит `anchor` ОТДЕЛЬНОЙ всплывашки
    # (`sc_anchor = spec.get("anchor") or anchor`), а эта проверка читала
    # только глобальный ключ ролика и рисовала рамку на прежнем месте. То
    # есть вкладка правила `anchor` у всплывашки, садившейся на лицо,
    # пересобирала лист, видела рамку там же и считала правку нерабочей —
    # а на кадре она как раз СРАБОТАЛА. Проверка, которая врёт про результат
    # правки, хуже отсутствующей.
    # ДЕФОЛТ ЯКОРЯ — ПО КАНАЛУ, КАК В `build_overlays.py` (11.11,
    # `НА-РАСКАТКУ` п.11). Здесь стоял жёсткий `bottom`, а сборка для всех
    # каналов кроме ПЛАНЕТЫ ставит `top` — лист показывал посадку НЕ ТАМ,
    # где она будет, вкладка правила по листу, и `selfcheck` потом отбивал.
    # Канал берём как весь сборщик: из `scenes.json`, иначе из ПУТИ.
    _chan = ""
    for _sc in sorted(glob.glob(os.path.join(proj, "*.scenes.json"))) + \
               [os.path.join(proj, "scenes.json")]:
        try:
            _d = json.load(open(_sc, encoding="utf-8"))
            _chan = str(_d.get("channel", "") if isinstance(_d, dict) else "")
            if _chan:
                break
        except (OSError, ValueError):
            continue
    if not _chan:
        _up = os.path.abspath(proj).replace("\\", "/").split("/")
        for _i, _ч in enumerate(_up):
            if _ч.upper() == "НОВОСТИ" and _i + 1 < len(_up):
                _chan = _up[_i + 1]
                break
    _def_anchor = ("bottom"
                   if _chan.strip().upper().replace("Ё", "Е") == "ПЛАНЕТА"
                   or not _chan.strip() else "top")
    anchor = str(ov.get("anchor", _def_anchor)).lower()
    if "anchor" not in ov:
        print("якорь всплывашек по каналу «%s»: %s (ключа `anchor` в "
              "overlays.json нет)" % (_chan or "не определён", anchor))

    ids = sorted(int(k) for k in ov if k.isdigit())
    tiles = []
    for sid in ids:
        spec = ov[str(sid)]
        bp = base_frame(images_dir, sid)
        if not bp:
            continue
        base_im = Image.open(bp).convert("RGB")
        frame = cover_crop(base_im, W, H)
        draw = ImageDraw.Draw(frame)
        # ФОТО-всплывашка — красная рамка, как было
        if spec.get("photo"):
            _a = str(spec.get("anchor") or anchor).lower()
            if _a not in ("top", "middle", "bottom"):
                _a = anchor
            x, y, dw, dh = overlay_geom(sid, spec, spec.get("photo"), _a)
            draw.rectangle([x, y, x + dw, y + dh], outline=(255, 0, 0), width=8)
        # ТЕКСТОВАЯ — кладём НАСТОЯЩИЙ отрендеренный текст, а не рамку:
        # проверяющий должен видеть ровно то, что ляжет на кадр
        tg = text_geom(sid, spec, _tmp, _projname)
        if tg:
            tx, ty, tw_, th_, tpng = tg
            try:
                with Image.open(tpng) as _t:
                    _t = _t.convert("RGBA").resize((tw_, th_))
                    frame.paste(_t, (tx, ty), _t)
            except Exception:
                pass
            draw.rectangle([tx, ty, tx + tw_, ty + th_], outline=(0, 220, 255), width=5)
        if not spec.get("photo") and not tg:
            continue
        # НОМЕР СЦЕНЫ — ПОД КАДРОМ, А НЕ ПОВЕРХ НЕГО (2026-10-19).
        # Чёрная плашка в левом верхнем углу налезала на начало надписи, и та
        # читалась как обрезанная: два субагента независимо начали аудит с этой
        # ложной тревоги и потратили по кропу на её опровержение. Подпись
        # вынесена в поле высотой BADGE_H под плиткой — кадр больше ничем не
        # закрыт, а номер по-прежнему виден.
        _img = frame.resize((480, 270))
        thumb = Image.new("RGB", (480, 270 + BADGE_H), (0, 0, 0))
        thumb.paste(_img, (0, 0))
        d2 = ImageDraw.Draw(thumb)
        d2.text((4, 270 + 4), str(sid), fill=(255, 255, 0))
        tiles.append((sid, thumb))

    os.makedirs(out_dir, exist_ok=True)
    cols = 5
    n_sheets = (len(tiles) + 19) // 20
    for s in range(n_sheets):
        chunk = tiles[s * 20:(s + 1) * 20]
        rows = (len(chunk) + cols - 1) // cols
        sh = Image.new("RGB", (480 * cols, (270 + BADGE_H) * rows), (20, 20, 20))
        for i, (sid, th) in enumerate(chunk):
            r, c = divmod(i, cols)
            sh.paste(th, (c * 480, r * (270 + BADGE_H)))
        sh.save(os.path.join(out_dir, f"check_{s + 1}.jpg"), quality=85)
    import shutil as _sh
    _sh.rmtree(_tmp, ignore_errors=True)
    _own = sorted(int(k) for k in ov if k.isdigit()
                  and str((ov[k] or {}).get("anchor") or "").lower()
                  in ("top", "middle", "bottom"))
    print(f"tiles: {len(tiles)}  sheets: {n_sheets}  anchor: {anchor}"
          + (f"  (свой anchor у сцен: {_own})" if _own else "")
          + f"  ->  {out_dir}/")
    print("  красная рамка = фото-всплывашка, голубая = ТЕКСТОВАЯ "
          "(показан настоящий рендер, не схема; надпись из-под маски — "
          "своим видом и своим размером, как в видео)")
    # ПОРЯДОК ПРОБ — СНАЧАЛА СТОРОНА, ПОТОМ ЯКОРЬ (03.11, замер `usuario-1f`
    # на двух сценах одного ролика). `anchor: "top"` на кадре с людьми часто
    # не спасает, а ПЕРЕНОСИТ рамку с туловищ на ГОЛОВЫ: ряд делегатов стоит
    # высоко в кадре. Там решила СТОРОНА (`bottom` + `right` увёл рамку на
    # ковёр у ног), а на другой сцене, где над головами узорная стена,
    # помог именно `top`. Если пробовать якорь первым, кажется, что
    # свободного места в кадре нет вовсе.
    print("  села на лицо? пробуй ПО ПОРЯДКУ: 1) другая СТОРОНА (left/right) "
          "— на кадре с людьми свободен обычно низ у ног или бок; 2) потом "
          "`anchor` у ЭТОЙ записи (top/middle/bottom). Якорь первым часто "
          "переносит рамку с туловищ на ГОЛОВЫ.")


if __name__ == "__main__":
    main()
