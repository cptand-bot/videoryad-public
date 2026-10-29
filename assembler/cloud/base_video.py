#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СБОР КЛИПОВ ДЛЯ БАЗЫ С ОФИЦИАЛЬНЫХ КАНАЛОВ ВЕДОМСТВ.

    base_video.py <plan.json> <out_dir> [--shard k/n] [--per-object 3]
                  [--clip 12] [--deadline 2100]

Решение пользователя 28.10: «я бы брал официальный YouTube-канал Белого дома,
Кремля, Министерства обороны России… у них ни водяных знаков нет». После
запрета стока движение в ролике взять больше неоткуда: вложения постов в
десяти замерах оказались переснятым ТВ-эфиром с чужими клеймами, а поисковые
картинки не двигаются.

Почему именно ВЕДОМСТВЕННЫЕ каналы: материал снят самим ведомством и выложен
им же, поэтому на нём нет клейма телеканала. Канал-перепечатка даёт ровно тот
же ТВ-рип, что и вложения, — такие в `base/channels.json` вносить нельзя.

Гейты у клипа свои (у фото их не бывает) и все проверяются ЗАПУСКОМ:
  - разрешение не ниже 1280x720 (ffprobe);
  - длительность клипа не меньше 10,15 с — короче сцена медиатеки не примет;
  - OCR по трём кадрам: клеймо агентства, плашка телеэфира, бегущая строка;
  - полоса вещателя по краям кадра (`_broadcast_banner` боевого фетча);
  - дедуп по md5.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.abspath(os.path.join(HERE, "..", "template"))
BASE = os.path.abspath(os.path.join(HERE, "..", "base"))
sys.path.insert(0, TPL)
import fetch_assets_news as F   # noqa: E402  те же гейты, что в бою

MIN_W, MIN_H = 1280, 720
MIN_CLIP = 10.15                # ниже этого сцена медиатеки клип не примет


def _say(*a):
    print(*a, flush=True)


def _run(cmd, timeout=600):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        _say("    команда не пошла: %s" % e)
        return None


def channels_path(plan_path):
    """Справочник каналов едет ВМЕСТЕ С ЗАДАНИЕМ. В облако синхронизируются
    только `template/` и `cloud/`, папки `base/` там нет вовсе — первый
    прогон 28.10 упал именно на этом: шесть машин честно отработали ноль
    клипов, а ошибка выглядела как «YouTube не пустил»."""
    near = os.path.join(os.path.dirname(os.path.abspath(plan_path)), "channels.json")
    if os.path.exists(near):
        return near
    local = os.path.join(BASE, "channels.json")
    if os.path.exists(local):
        return local
    raise SystemExit("ОШИБКА: нет channels.json ни рядом с заданием (%s), "
                     "ни в base/ — сбор клипов невозможен" % near)


_CH_CACHE = {}


def channels_for(layer, plan_path):
    cp = channels_path(plan_path)
    if cp not in _CH_CACHE:
        _CH_CACHE[cp] = json.load(open(cp, encoding="utf-8"))
    return [c for c in _CH_CACHE[cp]["каналы"] if layer in c.get("слои", [])]


def probe(path):
    r = _run(["ffprobe", "-v", "error", "-select_streams", "v:0",
              "-show_entries", "stream=width,height,duration",
              "-show_entries", "format=duration", "-of", "json", path], 120)
    if not r or r.returncode != 0:
        return 0, 0, 0.0
    try:
        d = json.loads(r.stdout)
        st = (d.get("streams") or [{}])[0]
        dur = float(st.get("duration") or d.get("format", {}).get("duration") or 0)
        return int(st.get("width") or 0), int(st.get("height") or 0), dur
    except Exception:
        return 0, 0, 0.0


def clip_is_clean(path, dur):
    """Три кадра клипа через тот же OCR, что судит фотографии. Один чистый
    кадр ничего не доказывает: плашка вещателя часто появляется на 2-3 секунде."""
    tmpdir = path + ".frames"
    os.makedirs(tmpdir, exist_ok=True)
    try:
        for i, t in enumerate((dur * 0.15, dur * 0.5, dur * 0.85)):
            fp = os.path.join(tmpdir, "f%d.jpg" % i)
            _run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "%.2f" % t,
                  "-i", path, "-frames:v", "1", "-q:v", "3", "-y", fp], 120)
            if not os.path.exists(fp):
                continue
            words, blob = F._ocr_words(fp)
            if any(m in blob for m in F._STOCK_WATERMARKS):
                return False, "клеймо стока/агентства"
            if words > 12:
                return False, "надписи в кадре (%d слов)" % words
            try:
                if F._broadcast_banner(fp):
                    return False, "полоса телеэфира"
            except Exception:
                pass
        return True, ""
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def pick_videos(channel, query, want):
    """Сначала поиск внутри канала, затем — свежие ролики канала. У разных
    ведомств работает по-разному: у Белого дома поиск, у Минобороны России
    свежая лента (там ролики и так по 34-42 с и тематически однородны)."""
    urls = []
    for kind, url in (("поиск", "https://www.youtube.com/%s/search?query=%s"
                       % (channel, re.sub(r"\s+", "+", query.strip()))),
                      ("свежие", "https://www.youtube.com/%s/videos" % channel)):
        r = _run(["yt-dlp", "--flat-playlist", "--playlist-end", str(want * 3),
                  "--print", "%(id)s\t%(duration)s\t%(title)s", url], 180)
        got = 0
        for line in ((r.stdout if r else "") or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 3 or not parts[0].strip():
                continue
            vid = parts[0].strip()
            try:
                dur = float(parts[1])
            except (ValueError, TypeError):
                dur = 0.0
            # слишком длинное качать незачем: брифинг на 55 минут даст тот же
            # кадр трибуны, что и трёхминутный, а весит в двадцать раз больше
            if dur and (dur < 12 or dur > 10800):
                continue
            if vid in [u[0] for u in urls]:
                continue
            urls.append((vid, dur, parts[2][:70], kind))
            got += 1
            if got >= want * 2:
                break
        if len(urls) >= want * 2:
            break
    return urls


def cut_clips(src, dst_dir, base_name, clip_len, want, seen_md5):
    """Режем ровные куски из середины — начало роликов ведомств почти всегда
    заставка с гербом, конец — титры."""
    w, h, dur = probe(src)
    if w < MIN_W or h < MIN_H:
        return [], "мелкое видео %dx%d" % (w, h)
    if dur < MIN_CLIP + 4:
        return [], "ролик короче клипа (%.1f с)" % dur
    out = []
    start = max(2.0, dur * 0.12)
    step = clip_len + 1.5
    n = 0
    while start + clip_len < dur * 0.95 and len(out) < want:
        n += 1
        dst = os.path.join(dst_dir, "%s_%02d.mp4" % (base_name, n))
        r = _run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "%.2f" % start,
                  "-i", src, "-t", "%.2f" % clip_len,
                  # звук не нужен: поверх ляжет озвучка, а файл легче вдвое
                  "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                  "-pix_fmt", "yuv420p", "-y", dst], 600)
        start += step
        if not r or not os.path.exists(dst) or os.path.getsize(dst) < 50000:
            continue
        cw, ch, cdur = probe(dst)
        if cdur < MIN_CLIP:
            os.remove(dst); continue
        try:
            h5 = F.file_md5(dst)
        except OSError:
            h5 = None
        if h5 and h5 in seen_md5:
            os.remove(dst); continue
        ok, why = clip_is_clean(dst, cdur)
        if not ok:
            os.remove(dst)
            _say("      кусок %d отбит: %s" % (n, why))
            continue
        if h5:
            seen_md5.add(h5)
        out.append(dst)
    return out, ""


def sweep_channel(item, out_dir, per_object, clip_len, deadline, per_video=3):
    """СВЕЖИЕ РОЛИКИ ОДНОГО КАНАЛА (решение пользователя 28.10): «если
    говорится про Зеленского — пускай он просто крутится». Объект здесь не
    ищется: берём последние записи официального канала и режем их. Привязка
    к событию и дате НЕ нужна — новее значит лучше, и кадр политика при этом
    всегда показывает его СЕЙЧАС, а не десять лет назад.

    Говорящая голова тут НЕ брак, а именно то, что нужно: это кадр персоны."""
    ch, folder = item["channel"], item["dir"]
    dst = os.path.join(out_dir, "frames", item["layer"], folder)
    os.makedirs(dst, exist_ok=True)
    _say("\n── %s → %s (свежие ролики канала)" % (ch, folder))
    seen_md5 = set(item.get("known_md5") or [])
    # роликов запрашиваем с запасом: часть отсеется по длине и по гейтам
    r = _run(["yt-dlp", "--flat-playlist", "--playlist-end",
              str(max(12, per_object * 2)),
              "--print", "%(id)s\t%(duration)s\t%(upload_date)s\t%(title)s",
              "https://www.youtube.com/%s/videos" % ch], 180)
    vids = []
    for line in ((r.stdout if r else "") or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[0].strip():
            continue
        try:
            dur = float(parts[1])
        except (ValueError, TypeError):
            dur = 0.0
        # ДЛИННЫЕ ЗАПИСИ БРАТЬ (28.10, его слово: «если там Путин совещание,
        # НАТО совещание — пускай будет, отрежешь кусочек»). Потолок 30 минут
        # отсекал ровно то, что нужно: ленты Кремля, НАТО и ООН состоят из
        # заседаний на час-два, из-за фильтра Путин дал ОДИН клип, НАТО один.
        # Кусок берём всё равно короткий, длина исходника роли не играет.
        if dur and (dur < 12 or dur > 10800):
            continue
        # ДАТА ВЫГРУЗКИ В ЛЕНТЕ КАНАЛА НЕ ОТДАЁТСЯ (проверено 28.10: приходит
        # "NA"), а на ней держится скользящее окно свежести. Берём дату
        # СБОРА: лента канала и так отсортирована от свежего к старому,
        # поэтому «собрано сегодня» и значит «самое новое, что есть».
        day = (parts[2] or "").strip()
        if not day or not day[:8].isdigit():
            day = time.strftime("%Y%m%d")
        vids.append((parts[0].strip(), dur, day[:8], parts[3][:60]))
    _say("    свежих роликов годной длины: %d" % len(vids))
    kept = []
    for vid, dur, day, title in vids:
        if len(kept) >= per_object or (deadline and time.time() > deadline):
            break
        if os.environ.get("BASE_VIDEO_COPY") == "1":
            # С ОДНОГО РОЛИКА — НЕ БОЛЬШЕ `per_video` КУСКОВ (28.10, его
            # замечание: «если там будет только 12, мы будем гонять одни и те
            # же клипы, это будет херня»). Набирать норму из одного часового
            # совещания бессмысленно: двенадцать кусков одной сцены зритель
            # прочтёт как один кадр, повторённый двенадцать раз.
            want_here = min(per_video, per_object - len(kept))
            got, why = grab_sections(vid, dur, dst, "%s_%s" % (day or "00000000", vid[:6]),
                                     clip_len, want_here, seen_md5)
            for g in got:
                _say("      + %s  ← %s · %s" % (os.path.basename(g), day, title[:40]))
            kept += got
            continue
        raw = os.path.join(dst, ".src.mp4")
        sec = "*%d-%d" % (int(max(3, dur * 0.08)), int(max(3, dur * 0.08)) + 90)
        rr = _run(["yt-dlp", "-q", "--no-warnings", "-f",
                   "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
                   "--download-sections", sec, "--force-keyframes-at-cuts",
                   "-o", raw, "--", vid], 600)
        if not os.path.exists(raw):
            _say("      %s: не скачалось (%s)" % (vid, ((rr.stderr or "")[:110] if rr else "нет ответа").replace("\n", " ")))
            continue
        # ИМЯ НЕСЁТ ДАТУ: папка персоны живёт скользящим окном, и свежее
        # вытесняет старое само, без правок боевого фетча
        got, why = cut_clips(raw, dst, "%s_%s" % (day or "00000000", vid[:6]),
                             clip_len, per_object - len(kept), seen_md5)
        os.remove(raw)
        if why:
            _say("      %s: %s" % (vid, why))
        for g in got:
            _say("      + %s  ← %s · %s" % (os.path.basename(g), day, title[:40]))
        kept += got
    _say("    ИТОГ: клипов %d" % len(kept))
    return {"layer": item["layer"], "q": item.get("q", ch), "dir": folder,
            "channel": ch, "kept": len(kept),
            "files": [os.path.relpath(p, out_dir) for p in kept]}


def grab_sections(vid, dur, dst_dir, base_name, clip_len, want, seen_md5):
    """КУСКИ КАЧАЕМ ГОТОВЫМИ, БЕЗ ПЕРЕКОДИРОВАНИЯ (локальный режим).

    Машину пользователя считать нельзя (его прямое слово 23.10), а YouTube
    отдаёт файлы только с домашнего адреса — на раннерах GitHub ответ один:
    «Sign in to confirm you're not a bot» (проверено 28.10, 12 джобов из 12).
    Выход: просим у YouTube сразу нужный отрезок и кладём его как есть.
    Процессор при этом не работает — идёт только скачивание."""
    out = []
    starts = []
    t = max(3.0, dur * 0.12)
    while t + clip_len < dur * 0.95 and len(starts) < want:
        starts.append(t)
        t += clip_len + 2.0
    for i, st in enumerate(starts, 1):
        dst = os.path.join(dst_dir, "%s_%02d.mp4" % (base_name, i))
        r = _run(["yt-dlp", "-q", "--no-warnings", "-f",
                  "bv*[height<=1080][ext=mp4]/b[height<=1080][ext=mp4]/b",
                  "--download-sections", "*%d-%d" % (int(st), int(st + clip_len + 1)),
                  "-o", dst, "--", vid], 300)
        if not os.path.exists(dst) or os.path.getsize(dst) < 50000:
            if r and r.stderr:
                _say("      кусок %d не скачался: %s" % (i, r.stderr[:100].replace("\n", " ")))
            continue
        w, h, cdur = probe(dst)
        if w < MIN_W or h < MIN_H:
            os.remove(dst); _say("      кусок %d: мелкий %dx%d" % (i, w, h)); continue
        if cdur < MIN_CLIP:
            os.remove(dst); _say("      кусок %d: короткий %.1f с" % (i, cdur)); continue
        try:
            h5 = F.file_md5(dst)
        except OSError:
            h5 = None
        if h5 and h5 in seen_md5:
            os.remove(dst); continue
        ok, why = clip_is_clean(dst, cdur)
        if not ok:
            os.remove(dst); _say("      кусок %d отбит: %s" % (i, why)); continue
        if h5:
            seen_md5.add(h5)
        out.append(dst)
    return out, ""


def harvest_one(item, out_dir, per_object, clip_len, deadline):
    layer, q = item["layer"], item["q"]
    safe = item["dir"]
    dst = os.path.join(out_dir, "frames", layer, safe)
    os.makedirs(dst, exist_ok=True)
    chans = channels_for(layer, item["_plan"])
    _say("\n── %s / %s" % (layer, q))
    if not chans:
        _say("    официального канала для этого слоя нет — пропускаю")
        return {"layer": layer, "q": q, "dir": safe, "kept": 0,
                "why": "нет канала для слоя"}
    seen_md5 = set(item.get("known_md5") or [])
    kept, tried_v = [], 0
    for ch in chans:
        if len(kept) >= per_object or (deadline and time.time() > deadline):
            break
        vids = pick_videos(ch["id"], q, per_object)
        _say("    %s: роликов-кандидатов %d" % (ch["id"], len(vids)))
        for vid, dur, title, kind in vids:
            if len(kept) >= per_object or (deadline and time.time() > deadline):
                break
            tried_v += 1
            raw = os.path.join(dst, ".src.mp4")
            # берём только кусок ролика: отрезок в начале середины. Скачивать
            # часовой брифинг целиком незачем ни по времени, ни по трафику.
            sec = "*%d-%d" % (int(max(3, dur * 0.1)), int(max(3, dur * 0.1)) + 90)
            r = _run(["yt-dlp", "-q", "--no-warnings", "-f",
                      "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b",
                      "--download-sections", sec, "--force-keyframes-at-cuts",
                      "-o", raw, "--", vid], 600)
            if not os.path.exists(raw):
                msg = ((r.stderr or "")[:120] if r else "нет ответа")
                _say("      %s: не скачалось (%s)" % (vid, msg.replace("\n", " ")))
                continue
            got, why = cut_clips(raw, dst, "v_%s" % vid[:6], clip_len,
                                 per_object - len(kept), seen_md5)
            os.remove(raw)
            if why:
                _say("      %s: %s" % (vid, why))
            for g in got:
                _say("      + %s  ← %s · %s" % (os.path.basename(g), ch["id"], title[:40]))
            kept += got
    _say("    ИТОГ: клипов %d (роликов пробовали %d)" % (len(kept), tried_v))
    return {"layer": layer, "q": q, "dir": safe, "kept": len(kept),
            "videos_tried": tried_v,
            "files": [os.path.relpath(p, out_dir) for p in kept]}


def sheet_for_clips(clips, out_jpg, title):
    """Лист клипов: по одному кадру из середины каждого, номер выжжен."""
    from PIL import Image, ImageDraw, ImageFont
    TW, TH, COLS = 320, 214, 4
    rows = max(1, (len(clips) + COLS - 1) // COLS)
    sh = Image.new("RGB", (COLS * TW, rows * TH + 34), (24, 24, 26))
    dr = ImageDraw.Draw(sh)
    try:
        fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 21)
    except Exception:
        fnt = big = ImageFont.load_default()
    dr.text((8, 8), ("ВИДЕО · " + title)[:92], font=big, fill=(120, 255, 170))
    for i, c in enumerate(clips):
        x, y = (i % COLS) * TW, 34 + (i // COLS) * TH
        tmp = c + ".thumb.jpg"
        _run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "5", "-i", c,
              "-frames:v", "1", "-q:v", "4", "-y", tmp], 120)
        try:
            with Image.open(tmp) as im:
                im.thumbnail((TW - 6, TH - 6))
                sh.paste(im, (x + 3, y + 3))
        except Exception:
            dr.rectangle([x + 3, y + 3, x + TW - 3, y + TH - 3], fill=(40, 60, 40))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        dr.rectangle([x + 3, y + 3, x + 41, y + 27], fill=(120, 255, 170))
        dr.text((x + 10, y + 5), "%02d" % (i + 1), font=fnt, fill=(0, 0, 0))
    sh.save(out_jpg, "JPEG", quality=84)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("out_dir")
    ap.add_argument("--shard", default="1/1")
    ap.add_argument("--per-object", type=int, default=15,
                    help="сколько клипов набрать в папку за заход")
    ap.add_argument("--per-video", type=int, default=3,
                    help="сколько кусков брать ИЗ ОДНОГО ролика: больше — и"
                         " папка превращается в нарезку одного совещания")
    ap.add_argument("--clip", type=float, default=12.0)
    ap.add_argument("--deadline", type=float, default=0.0)
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    allit = plan["items"] if isinstance(plan, dict) else plan
    for it in allit:
        it["_plan"] = a.plan
    items = [it for it in allit if it.get("need_video") or it.get("channel")]
    k, n = (int(x) for x in a.shard.split("/"))
    mine = [it for i, it in enumerate(items) if i % n == (k - 1) % n]
    os.makedirs(a.out_dir, exist_ok=True)
    _say("шард %d/%d: объектов с клипами %d из %d" % (k, n, len(mine), len(items)))

    if not shutil.which("yt-dlp"):
        _say("::error::yt-dlp не установлен — сбор клипов невозможен")
        raise SystemExit(1)
    if not shutil.which("ffmpeg"):
        _say("::error::ffmpeg не установлен")
        raise SystemExit(1)
    tess = F._TESS_BIN if os.path.exists(F._TESS_BIN) else "tesseract"
    alive = F._ocr_alive(tess)
    _say("OCR: %s" % ("работает" if alive else "НЕ РАБОТАЕТ — клейма не отсеются"))
    if not alive:
        _say("::error::без OCR клипы не проверить на клейма — останавливаюсь")
        raise SystemExit(1)

    t0 = time.time()
    dl = (t0 + a.deadline) if a.deadline else 0.0
    rep = []
    for it in mine:
        if dl and time.time() > dl:
            _say("[дедлайн] шард остановлен, необработанных: %d" % (len(mine) - len(rep)))
            break
        try:
            r = (sweep_channel(it, a.out_dir, a.per_object, a.clip, dl, a.per_video)
                 if it.get("channel")
                 else harvest_one(it, a.out_dir, a.per_object, a.clip, dl))
        except Exception as e:
            _say("ОШИБКА на объекте %r: %s" % (it.get("q"), e))
            r = {"layer": it.get("layer"), "q": it.get("q"), "dir": it.get("dir"),
                 "kept": 0, "error": str(e)}
        rep.append(r)
        clips = [os.path.join(a.out_dir, f) for f in r.get("files", [])]
        if clips:
            os.makedirs(os.path.join(a.out_dir, "sheets"), exist_ok=True)
            nm = "ВИДЕО__%s__%s.jpg" % (r["layer"], r["dir"])
            sheet_for_clips(clips, os.path.join(a.out_dir, "sheets", nm),
                            "%s · %s" % (r["layer"], r["q"]))
            json.dump({"sheet": nm, "layer": r["layer"], "dir": r["dir"], "q": r["q"],
                       "tiles": r["files"]},
                      open(os.path.join(a.out_dir, "sheets", nm[:-4] + ".map.json"),
                           "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out = {"shard": a.shard, "seconds": round(time.time() - t0, 1),
           "objects": rep, "kept_total": sum(r.get("kept", 0) for r in rep)}
    json.dump(out, open(os.path.join(a.out_dir, "report.video.shard%d.json" % k), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    _say("\n=== ШАРД %d/%d: клипов %d, объектов %d, %.0f с ==="
         % (k, n, out["kept_total"], len(rep), out["seconds"]))
    if rep and out["kept_total"] == 0:
        _say("::error::ни одного клипа — причина НАЗВАНА в строках выше по "
             "каждому ролику; не гадай, читай их")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
