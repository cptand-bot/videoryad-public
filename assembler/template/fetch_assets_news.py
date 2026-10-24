#!/usr/bin/env python3
"""
News-niche asset fetcher for the news-video pipeline.

Unlike script-to-video's fetch_assets.py (which defaults to AI-generating
~90% of scenes), this NEVER generates images of real people/events - a
generated "photo" of a real news event is a fabrication risk, not a stylistic
choice. Waterfall per scene's `source` field:

  wikimedia   -> Wikimedia Commons (real photos, often press-donated)
  press_photo -> DVIDS -> Openverse -> Flickr CC -> Internet Archive ->
                 Wikimedia -> web_search - in that order, first hit wins.
                 DVIDS (dvidshub.net) is the U.S. DoD's own public-domain
                 photo wire - only hits for US-military/DoD scenes, a miss
                 is one cheap API call, needs DVIDS_API_KEY in .env (free,
                 see SKILL.md). Openverse (api.openverse.org) is itself an
                 aggregator over many CC sources (Europeana, museum/gallery
                 collections, Flickr, Wikimedia and more) via one API, free,
                 no key required for light use.
  direct_url  -> готовый адрес медиа: вложение телеграм-поста из досье
                 георадара, файл на сайте источника. Качается как есть,
                 расширение по СОДЕРЖИМОМУ (телеграм отдаёт файлы без
                 расширения), сита те же — бан-md5, OCR/клейма для фото,
                 ffprobe для видео. Промах НЕ подменяется водопадом.
  pexels_photo / pexels_video -> Pexels stock - ONLY for generic, non-specific
                 cutaways (a city skyline, a courtroom, a stock market ticker,
                 weather) where showing a real person/place isn't the point.
                 Never classify a scene about a SPECIFIC real event/person as
                 pexels_* - see SKILL.md.

Usage:
  python3 fetch_assets_news.py <scenes.json> <images-dir> <.env>
"""
import glob
import json
import os
import re
import shutil
import sys
import time
import hashlib
import subprocess
import socket
import urllib.request
import urllib.parse
from collections import Counter

# md5 -> how many scenes in THIS build already use that exact file. A
# deliberate leitmotif may repeat up to twice (rule 5 / SKILL "establishing
# leitmotif"); the 3rd request for the same file is rerouted to a fresh one.
_USE_COUNT = Counter()
_WEB_USED_MD5 = set()   # md5 of every image web_search accepted this run (+ cross-video cooldown)
# md5 -> человеческое «где он уже стоит» (2026-10-22, улов `usuario-5a`).
# Без этого отказ по собственному дублю выглядел как «вернуть нечего»: вкладка
# попросила во всплывашку тот же кадр, что стоит базой сцены 3, и получила
# пустоту без причины — круг правок на ровном месте.
_WEB_USED_WHERE = {}
_DUP_SAID = set()        # о каком md5 уже сказали в этом прогоне
# Rule 5 (user, 2026-08-31): every library file appears in a видеоряд at most
# ONCE. No leitmotif exception — was 2, now 1. A folder that runs out of fresh
# files fails the scene loudly (EXHAUSTED) instead of recycling.
_MAX_PER_BUILD = 1

DEFAULT_UA = "news-video/0.1 (personal project)"

# ---------------------------------------------------------------------------
# Cross-process pacing for parallel fetch (fetch_parallel.py). When several
# worker processes run at once, the rate-limit-prone providers (Yandex,
# Wikimedia) must still be hit no faster than one call per N seconds GLOBALLY
# or they ban the IP. _pace() serialises + throttles via a lock dir; a single
# serial run leaves FETCH_PACE_DIR unset and every call is a no-op.
# ---------------------------------------------------------------------------
# ВКЛЮЧЁН ВСЕГДА, а не только в параллельном режиме (2026-10-12).
# Раньше значением по умолчанию была пустая строка, и _pace() становился
# пустышкой на ЛЮБОМ серийном запуске — то есть на всех мелких доправках по
# ходу аудита (их за сборку бывает несколько десятков) к Яндексу летели
# запросы вообще без интервала. Плюс каталог замка раньше жил внутри проекта,
# так что четыре вкладки тормозили только каждая себя и суммарно били по
# Яндексу вчетверо чаще задуманного — с одного домашнего адреса.
# Теперь по умолчанию один общий замок на всю машину: 1 запрос / 2.5 с к
# Яндексу суммарно, сколько бы вкладок и режимов ни работало одновременно.
_PACE_DIR = os.environ.get("FETCH_PACE_DIR") or os.path.join(
    os.path.expanduser("~"), ".cache", "videoryad-pace")
_PACE_MIN = {"yandex": 2.5, "wikimedia": 6.0, "ddg": 1.5, "openverse": 0.4,
             "internet_archive": 0.6, "flickr": 0.4}


def _pace(provider):
    """Block until at least _PACE_MIN[provider] seconds have passed since any
    worker last called this provider. No-op when FETCH_PACE_DIR is unset."""
    if not _PACE_DIR:
        return
    try:
        import fcntl
        os.makedirs(_PACE_DIR, exist_ok=True)
        lockf = os.path.join(_PACE_DIR, provider + ".lock")
        gap = _PACE_MIN.get(provider, 1.0)
        with open(lockf, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                last = float(fh.read().strip() or 0)
            except ValueError:
                last = 0.0
            wait = last + gap - time.time()
            if wait > 0:
                time.sleep(min(wait, gap))
            fh.seek(0)
            fh.truncate()
            fh.write(str(time.time()))
            fh.flush()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Source rules the user demanded 2026-08-29 (see SKILL.md "НЕРУШИМЫЕ ПРАВИЛА").
# ---------------------------------------------------------------------------

# Rule 2: no stock photos of people for political/diplomacy scenes. If a
# pexels_* query hits one of these, refuse it and fail the scene loudly so it
# gets reclassified to local_library or press_photo. Pexels stays allowed only
# for people-free objects/scenery.
PEXELS_BLOCK = [
    "negotiat", "diploma", "summit", "delegation", "minister", "president",
    "parliament", "congress", "council", "leader", "official", "signing",
    "handshake", "politician", "government", "spokes", "envoy", "ambassador",
    "переговор", "министр", "президент", "саммит", "чиновник", "депутат",
    "парламент", "делегац", "лидер", "подпис", "рукопожат",
]

# Rule 4 (user, 2026-08-31): a library shot used in ANY of the last
# COOLDOWN_VIDEOS videos is off-limits — 3 consecutive videos must be fully
# non-repeating; the 4th may reuse. Was 5. Strict: no silent fallthrough to a
# blocked file, the scene fails and you add material / rewrite it.
COOLDOWN_VIDEOS = 3
USAGE_LOG = os.path.expanduser("~/projects/media-library/.usage_log.json")

# Blacklist — separate from the rolling COOLDOWN_VIDEOS window above. The
# user (2026-09-22): "оно уже встречается сто тысяч раз... хочу пометку
# никогда больше не использовать" — a library shot (or a re-hosted web
# photo) that's just visually stale/overused, independent of the last-3-
# videos rule. Keyed by md5 so it works for any source type and survives
# renames. `ban_file.py` (this dir) and the dashboard's 🚫 button both write
# here; fetch_local_library and _accept() both read it.
#
# 2026-09-23: entries can now be TIMED, not just permanent — the user found
# a flat forever-ban too harsh for a shot that's merely overused right now
# ("не совсем убивать... через 10 дней только его использовать"). An entry
# with a "until" date (YYYY-MM-DD) expires on its own — load_banned_md5()
# stops returning it once today's date passes "until". No "until" key =
# permanent, same as before (backward compatible with old entries).
# 2026-10-15: путь переопределяется переменной VIDEORYAD_BANNED_FILE —
# так бан-лист доезжает до облачного раннера, у которого медиатеки нет.
# ship.sh кладёт обезличенную копию (только md5, без локальных путей) в
# queue/<name>/.banned_md5.json, fetch_shard.py выставляет переменную.
# Без переменной поведение прежнее — локальный файл медиатеки.
BANNED_LOG = os.environ.get("VIDEORYAD_BANNED_FILE") or os.path.expanduser(
    "~/projects/media-library/.banned_md5.json")


def load_banned_md5():
    if not os.path.exists(BANNED_LOG):
        return set()
    try:
        with open(BANNED_LOG, encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        return set()
    today = time.strftime("%Y-%m-%d")
    return {md5 for md5, e in log.items()
            if not e.get("until") or e["until"] >= today}


def ban_md5(md5, path="", reason="", days=None):
    """Blacklist a file by md5 — permanently (default) or for `days` days.
    `path` is just a human-readable breadcrumb (relative library path or
    source URL) — matching is always by md5, never by path, so a renamed/
    re-downloaded copy stays banned for as long as the entry is active."""
    log = {}
    if os.path.exists(BANNED_LOG):
        try:
            log = json.load(open(BANNED_LOG, encoding="utf-8"))
        except (OSError, ValueError):
            log = {}
    entry = {"path": path, "reason": reason, "date": time.strftime("%Y-%m-%d")}
    if days:
        entry["days"] = int(days)
        entry["until"] = time.strftime("%Y-%m-%d", time.localtime(time.time() + int(days) * 86400))
    log[md5] = entry
    os.makedirs(os.path.dirname(BANNED_LOG), exist_ok=True)
    tmp = BANNED_LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    os.replace(tmp, BANNED_LOG)


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_blocked_md5(this_project):
    """md5s of library files used in the last COOLDOWN_VIDEOS *other* projects,
    plus anything permanently banned (see BANNED_LOG above)."""
    if not os.path.exists(USAGE_LOG):
        return load_banned_md5(), {}
    with open(USAGE_LOG, encoding="utf-8") as f:
        log = json.load(f)
    # newest projects first, excluding the one we're building now
    proj_dates = {}
    for md5, entries in log.items():
        for e in entries:
            if e["project"] == this_project:
                continue
            proj_dates[e["project"]] = max(proj_dates.get(e["project"], ""), e.get("date", ""))
    recent = {p for p, _ in sorted(proj_dates.items(), key=lambda kv: kv[1], reverse=True)[:COOLDOWN_VIDEOS]}
    blocked = {md5 for md5, entries in log.items()
               if any(e["project"] in recent for e in entries)}
    blocked |= load_banned_md5()   # permanent + not-yet-expired timed bans, on top of the rolling window above
    return blocked, log


def record_usage(log, this_project, used_md5_to_relpath):
    today = time.strftime("%Y-%m-%d")
    for md5, relpath in used_md5_to_relpath.items():
        entries = log.setdefault(md5, [])
        if not any(e["project"] == this_project for e in entries):
            entries.append({"project": this_project, "date": today, "file": relpath})
    tmp = USAGE_LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    os.replace(tmp, USAGE_LOG)

# This machine has no apt/sudo, so tesseract was installed by hand-extracting
# .debs (apt-get download + dpkg-deb -x) into ~/tools/tesseract - see SKILL.md
# Gotchas. Falls back to a plain "tesseract" call (e.g. if run on a machine
# where it's properly installed via a package manager).
_TESS_BIN = os.path.expanduser("~/tools/tesseract/usr/bin/tesseract")
_TESS_LIB = os.path.expanduser("~/tools/tesseract/usr/lib/x86_64-linux-gnu")
_TESS_DATA = os.path.expanduser("~/tools/tesseract/usr/share/tesseract-ocr/5/tessdata")


def _tesseract_env():
    env = os.environ.copy()
    if os.path.isdir(_TESS_LIB):
        env["LD_LIBRARY_PATH"] = _TESS_LIB + ":" + env.get("LD_LIBRARY_PATH", "")
    if os.path.isdir(_TESS_DATA):
        env["TESSDATA_PREFIX"] = _TESS_DATA
    return env


# stock-agency watermark tokens - if OCR sees any of these ANYWHERE in the
# image (even a faint corner tile at low text density), it's a watermarked
# preview from a paid bank, not a clean reusable photo. This skill exists
# precisely to avoid watermarked/copyrighted previews (SKILL.md), and the
# heavy-text filter misses them because a single "alamy" tile is only 1 word.
# Hit live on ukraincy-begut-0709: alamy (scene 120), dreamstime (73, 78).
_STOCK_WATERMARKS = (
    # ОБРАБОТАНО АПСКЕЙЛЕРОМ (2026-10-23, улов `usuario-7b`): «Magnific» —
    # замощённая полупрозрачная надпись по ВСЕМУ полю, шаг примерно 1/6
    # ширины, мелким светлым шрифтом; OCR не взял. Признак вдвойне: и знак,
    # и кадр почти наверняка машинный — на русский запрос про Донбасс приехал
    # американский дом с газоном и соснами.
    "magnific",
    # каталожное фото интернет-магазина: надпись ДВАЖДЫ поперёк кадра, крупно,
    # по центру — OCR её не взял (23.10, улов `usuario-dd`, сцена 20).
    "палатки-армии", "палатки армии",
    # агентство URA.RU, подпись мелко в нижнем правом углу на реальном фото
    # (2026-10-23, тот же улов; парный проверяющий написал «по содержанию ок»
    # и про знак не сказал).
    "ura.ru", "ura ru",
    # фотобанки ОБОЕВ на русских запросах про панораму города (2026-10-18):
    # «телебашня на Александерплац Берлин реальное фото 2026» → плашка
    # «УЮТНАЯ СТЕНА» в углу; tesseract не поймал (0 подозрений на 82 файлах),
    # знак нашёл глаз на парном листе.
    "уютная стена", "уютнаястена",
    # телеграм-паблики Донбасса на русских запросах про восстановление/стройку
    # (2026-10-18): знак во весь кадр, дважды подряд, пул один, переформулировка
    # не помогает; tesseract не поймал ни одного — ловим по подписи.
    "kulemzin", "donetskmedia", "донецкmedia",
    "recommend.ru",   # отзывный сайт, логотип в правом нижнем углу (2026-10-16)
    "alamy", "dreamstime", "shutterstock", "getty", "gettyimages",
    "depositphotos", "123rf", "istock", "istockphoto", "adobestock",
    "bigstock", "canstockphoto", "vectorstock", "vecteezy", "stockphoto", "photostock",
    "lori.ru", "фотобанк", "легион-медиа",
    # non-stock sources that OCR-leaked into frames on 07.09-2 (photo-collector
    # sites, news-article screenshots, agency bugs). A single tile = reject.
    "pastvu", "violity", "fishki", "pngtree", "mycity", "akiro",
    # 2026-10-17: споттерская база на русском запросе про Typhoon
    "wings over europe",
    "bbc news", "kommersant", "коммерсант", "ria.ru", "риа новости",
    "sputnik", "1prime", "che line", "служба безпеки", "unian.",
    # ТЕЛЕВИЗИОННАЯ ГРАФИКА НА ПОДЛОЖКЕ ПОЗАДИ СПИКЕРА, А НЕ В УГЛУ
    # (2026-10-19, planeta-tir-surovikin-2010): логотип «Первый канал HD» на
    # экране позади Мерца и читаемая плашка эфира в зале Бундестага. Прежние
    # записи ловили только угловые «мухи» новостных сайтов.
    "первый канал", "россия 24", "россия-24", "russia today",
    # РЕКЛАМНЫЙ ПОСТЕР ТЕЛЕКАНАЛА НА АРХИВНЫЙ ЗАПРОС (2026-10-19): «падение
    # Берлинской стены 1989 архивная фотография» → постер History с золотым
    # логотипом в углу и анонсом эфира «Pawn Stars | Sunday 9:50 PM» поперёк
    # кадра. Архив был задуман, логотип канала — нет.
    "pawn stars", "history channel", "сериал на history",
    # ЗНАК КАНАЛА-ПЕРЕПУБЛИКАТОРА ПО ЦЕНТРУ КАДРА (2026-10-19): полупрозрачное
    # «ОСТАШКО! ВАЖНОЕ / TELEGRAM» поверх заголовка статьи FT — не в углу,
    # а посередине, поэтому проверка краёв его пропустила.
    "осташко", "осташко! важное",
    # МОСКОВСКИЕ ГОРОДСКИЕ ОБЪЕКТЫ — МАГНИТ НА ЗНАКИ МЕСТНЫХ АГЕНТСТВ
    # (2026-10-19): «здание посольства США в Москве» дважды подряд пришло со
    # знаком по центру. Лечится не формулировкой, а выбором ОБЩЕИЗВЕСТНОГО
    # объекта, который снимают все (Кремль с набережной прошёл сразу).
    "агентство городских новостей", "kremlin pool", "риа kremlin",
    # Visual China Group: знак «© 视觉中国» приехал на РУССКИЙ запрос про
    # Бундесвер (сам кадр — ч/б архив в пустыне). Иероглифы tesseract не
    # читает, поэтому главный рубеж — домен ниже; токен оставлен на случай
    # латинской подписи.
    "视觉中国", "visual china", "vcg.com",
    # 2026-10-12, cross-session (ds-8-mostov-1310): украинская городская и
    # транспортная тематика стабильно тянет водяные знаки местных пабликов
    # и фотоархивов. ВНИМАНИЕ: логотипы госслужб (ДСНС, Одеська ОВА и т.п.)
    # сюда НЕ добавлять — по правилу аудита это их собственная съёмка и
    # приемлемый случай, в отличие от чужой перепубликации.
    "уніан", "думская", "rasfokus", "расфокус", "nashtransport",
    "skyandmethod", "horevica", "my-sokol", "artemco",
    "сайт міста києва",
)


_STYLIZED_NAME = ("animate", "ai-gen", "ai_gen", "aigen", "ai-generated",
                  "motion-graphic", "lower-third", "эмблема", "заставка",
                  # AI video-gen tool exports — no "ai-gen" in the name, just a
                  # task/genid UUID pipeline signature (found 2026-09-14 in
                  # ПОЛИТИКА/NEWs and ПОЛИТИКА/SVO, slipping past the filter
                  # above and serving as "real" news b-roll via round-robin)
                  "_genid_", "grok-video", "task_01")
_STYLIZED_TAGS = {"ai-generated", "ai-gen", "stylised", "stylized",
                  "motion-graphics", "emblem-glow", "3d-render", "cgi"}


def _is_stylized(fname, tags):
    """True for motion-graphics / AI-composite library assets that must not
    stand in for a real news shot (NATO-emblem glow renders, missiles over
    EU-star rings, 'animate*.mp4'). Name heuristic + index tag check."""
    low = os.path.basename(fname).lower()
    if any(k in low for k in _STYLIZED_NAME):
        return True
    return bool(_STYLIZED_TAGS & {str(t).lower() for t in (tags or ())})


def _ocr_raw(image_path, tess_bin):
    """One tesseract pass over whatever image is at `image_path`. Same
    parsing as before, split out so it can run over a cropped/upscaled
    region too, not just the full frame."""
    try:
        res = subprocess.run(
            [tess_bin, image_path, "-", "-l", "eng+rus", "tsv"],
            capture_output=True, text=True, timeout=30, env=_tesseract_env(),
        )
    except Exception:
        return 0, ""
    real_words, tokens = 0, []
    for line in (res.stdout or "").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        word = cols[11].strip()
        if not word:
            continue
        tokens.append(word.lower())
        if conf > 60 and sum(c.isalnum() for c in word) >= 3:
            real_words += 1
    return real_words, " ".join(tokens)


def _corner_watermark_blob(image_path, tess_bin):
    """A stock-agency watermark tile (alamy/shutterstock/bigstock/...) sits
    in one corner (or a faint centre tile) at maybe 2-4% of the frame's
    area - OCR over the WHOLE image routinely can't resolve it (it hit live
    2026-09-16: 'alamy'/'shutterstock' are already in _STOCK_WATERMARKS, the
    watermark was rejected by no rule, tesseract just never read the tiny
    text at full-frame resolution). Crop each corner + the bottom strip
    (where most agencies put it), upscale 3x, OCR each separately - a tile
    that's illegible at 1920px wide becomes readable once it's the whole
    crop. Returns a lowercased text blob (empty string on any failure -
    never blocks the pipeline)."""
    try:
        from PIL import Image
    except Exception:
        return ""
    try:
        im = Image.open(image_path).convert("RGB")
    except Exception:
        return ""
    w, h = im.size
    if w < 40 or h < 40:
        return ""
    cw, ch = max(1, w // 5), max(1, h // 6)
    regions = [
        (0, h - ch, cw, h),                  # bottom-left
        (w - cw, h - ch, w, h),              # bottom-right
        (0, 0, cw, ch),                      # top-left
        (w - cw, 0, w, ch),                  # top-right
        (0, h - ch, w, h),                   # full bottom strip
    ]
    blob_parts = []
    # ПОТОЛОК НА УВЕЛИЧЕНИЕ (23.10, улов `usuario-fa`). Кроп увеличивался
    # ВТРОЕ безусловно, и на крупном кадре это давало чудовищный размер:
    # у 6467×4311 нижняя полоса 6467×718 превращалась в 19401×2154 — сорок
    # один мегапиксель. Процесс часами сидел в PIL, tesseract при этом даже
    # не запускался, и снаружи это выглядело как «OCR завис»: выход нулевой,
    # вывод пустой, процессов нет. Увеличиваем ровно настолько, насколько
    # нужно мелкому клейму, и не больше 3000 px по длинной стороне.
    _t0 = time.time()
    for box in regions:
        if time.time() - _t0 > 60:
            blob_parts.append("")      # дальше не идём: бюджет кадра вышел
            break
        try:
            crop = im.crop(box)
            _k = min(3.0, 3000.0 / max(crop.width, crop.height, 1))
            if _k > 1.01:
                crop = crop.resize((int(crop.width * _k), int(crop.height * _k)))
            tmp = image_path + f".wmcrop.jpg"
            crop.save(tmp, "JPEG", quality=90)
            _, blob = _ocr_raw(tmp, tess_bin)
            blob_parts.append(blob)
        except Exception:
            continue
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return " ".join(blob_parts)


def _ocr_words(image_path):
    """Run tesseract over the full frame AND each corner/bottom-strip crop
    (see _corner_watermark_blob); return (real_word_count, full_lowercased_
    text). real_word_count = high-confidence words (conf>60, >=3 alnum
    chars) on the FULL image only (a corner crop's upscale can manufacture
    false 'words' out of noise, so it must never feed the heavy-text-
    screenshot count - only the watermark-token blob). Returns (0, "") if
    tesseract is unavailable so a missing OCR tool never blocks the
    pipeline."""
    tess_bin = _TESS_BIN if os.path.exists(_TESS_BIN) else "tesseract"
    real_words, blob = _ocr_raw(image_path, tess_bin)
    corner_blob = _corner_watermark_blob(image_path, tess_bin)
    return real_words, (blob + " " + corner_blob).strip()


def has_heavy_text_overlay(image_path, word_threshold=8):
    """OCR pre-filter, not a substitute for actually looking at the image.
    A webpage screenshot or a graphic-design article header has dozens of
    real, high-confidence words; a real press photo's occasional background
    sign/logo does not. word_threshold=8 leaves comfortable margin either
    side (0 real words on a clean night skyline, 70+ on an actual
    article-screenshot). Returns False ("looks fine") if tesseract is
    missing rather than blocking the pipeline."""
    return _ocr_words(image_path)[0] > word_threshold


def has_stock_watermark(image_path):
    """True if OCR finds a paid-stock watermark token anywhere - even one
    faint corner tile (low word count, so has_heavy_text_overlay misses it).
    A substring match: 'alamy' catches the repeated 'alamy alamy alamy'
    tiling, 'gettyimages.com' etc."""
    blob = _ocr_words(image_path)[1]
    return any(w in blob for w in _STOCK_WATERMARKS)


def _accept(ok, out_path):
    """Call after any image fetch: rejects (deletes + returns False) a
    download that has heavy baked-in text (webpage screenshot / design
    header), a paid-stock watermark tile (alamy/dreamstime/getty/...), or
    a file the user has permanently banned by md5 (see BANNED_LOG) — a web
    photo that keeps winning the same search (e.g. the Reichstag/Bundesrat
    collision) can recur across unrelated queries just as a library file
    can via round-robin."""
    if not ok:
        return ok
    try:
        if file_md5(out_path) in load_banned_md5():
            os.remove(out_path)
            return False
    except OSError:
        pass
    words, blob = _ocr_words(out_path)
    bad = words > 8 or any(w in blob for w in _STOCK_WATERMARKS)
    if bad:
        try:
            os.remove(out_path)
        except OSError:
            pass
        return False
    return ok


# АДРЕС ИСТОЧНИКА ДЛЯ МАНИФЕСТА (2026-10-17, заявка вкладки-разработчика):
# в `images/manifest.json` стояло только «web_search / ok», и проверить,
# ОТКУДА приехало фото персоны, можно было лишь глазами. Теперь каждый
# успешный скачанный файл запоминает свой адрес, и он попадает в манифест —
# сверка становится проверяемой, а повторный брак с одного домена видно
# сразу, без OCR.
LAST_SRC_URL = {}


def _remember_src(out_path, url):
    try:
        LAST_SRC_URL[os.path.abspath(out_path)] = url
    except Exception:
        pass


def _download_as_jpeg(url, out_path, timeout=20):
    try:
        host = url.split("/")
        ref = host[0] + "//" + host[2] + "/" if len(host) > 2 else url
        blob = http_get(url, headers={"Referer": ref}, timeout=timeout)
    except Exception:
        return False
    if not blob or len(blob) < 6000:
        return False
    head = blob[:12]
    is_img = (head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n"
              or head[:6] in (b"GIF87a", b"GIF89a") or head[8:12] == b"WEBP")
    if not is_img:
        return False
    tmp = out_path + ".raw"
    with open(tmp, "wb") as f:
        f.write(blob)
    try:
        from PIL import Image
        im = Image.open(tmp); im.load()
        if im.width < 500 or im.height < 320:
            os.remove(tmp); return False
        im.convert("RGB").save(out_path, "JPEG", quality=90)
        os.remove(tmp)
        _remember_src(out_path, url)
        return True
    except Exception:
        try: os.remove(tmp)
        except OSError: pass
        return False


# Domain-level stock-agency block for web_search candidates (user, 2026-09-16,
# furious - a "dreamstime" watermark covered the ENTIRE frame in cursive
# rotated text, tiled repeatedly, plus a solid banner reading "dreamstime.com"
# - about as blatant as a watermark gets - and it still shipped, because
# tesseract simply cannot read that stylised/rotated logo font at all. No
# amount of upscaling a corner crop fixes an OCR engine failing to recognise
# the GLYPHS themselves. The reliable signal is the URL, not the pixels:
# every one of these agencies hosts its own preview images on its own domain,
# so reject by hostname BEFORE downloading - this can't be fooled by a font
# OCR can't parse. Keep _STOCK_WATERMARKS/_accept()'s OCR check too (defense
# in depth for a re-host on a different domain), but this domain check is
# now the primary defense for the agencies it covers.
_STOCK_DOMAINS = (
    # ШЕДЕВРУМ — AI-КАРТИНКА, ДОМЕН НАДЁЖНЕЕ ЛЮБОГО ГЛАЗА (2026-10-18).
    # `avatars.mds.yandex.net/get-shedevrum/...` приезжает на БЫТОВЫЕ
    # предметные запросы («пустое кресло за столом»), всегда квадрат
    # 1024x1024, и выглядит как обычное фото. Фабрикация запрещена жёстко,
    # поэтому режем по url, не дожидаясь аудита.
    "get-shedevrum", "/shedevrum",
    # КАТАЛОЖНЫЕ ТОВАРНЫЕ ФОТО МАГАЗИНОВ — стерильная съёмка на белом там,
    # где нужен кадр с события. Замер 2026-10-18: чем КОНКРЕТНЕЕ предмет в
    # запросе (микрофоны, кресло, шеврон, табличка делегации), тем выше шанс
    # поймать магазин вместо съёмки. Лечение не в формулировке, а в смене
    # объекта — помещение или сцена с людьми.
    "img.tehnomaks.ru", "/img/prod/", "i.etsystatic.com", "etsystatic.com",
    "satu.kz", "pinterest.", "pinimg.com",
    # замощённая по всему полю вотермарка крипто-канала, OCR не берёт
    "public.bnbstatic.com",
    "alamy.com", "dreamstime.com", "shutterstock.com", "gettyimages.",
    "istockphoto.com", "depositphotos.com", "123rf.com", "adobe.com/stock",
    "stock.adobe.com", "bigstockphoto.com", "canstockphoto.com",
    "vectorstock.com", "vecteezy.com", "stocksy.com", "pond5.com",
    "agefotostock.com", "photostock.", "lori.ru",
    # авиационные споттер-базы: водяной знак — стилизованный логотип,
    # OCR его не читает (ловилось 2026-10-13 и 2026-10-14) — только домен
    "airliners.net", "jetphotos.net", "jetphotos.com", "russianplanes.net",
    "planespotters.net", "abpic.co.uk", "airteamimages.com",
    # форумы/агрегаторы с вшитым знаком
    "yaplakal.com", "pixel-shot.com",
    # личные блоги-травелоги: подпись автора строкой по нижней кромке
    # («© Alexander Belenkiy | macos.livejournal.com»), OCR её не взял —
    # поймано глазами на planeta-tri-bukvy-1810, 2026-10-17
    "macos.livejournal.com", "macos.me", "livejournal.com/photo",
    # агентства, у которых знак вшит В КАДР (не в угол) и OCR его не берёт:
    # поймано глазами 2026-10-17 на planeta-svergnut-1810
    "interfax.com.ua",
    # знак через весь кадр, OCR не берёт (2026-10-17, тот же ролик):
    # каталог напольных покрытий приехал на «служебный коридор», сток-клипарт —
    # на «здание Казначейства США»
    "nash-parus.com.ua", "pngtree",
    # Visual China Group (视觉中国) — китайское фотоагентство, знак вшит в
    # кадр иероглифами, OCR их не берёт в принципе (словари rus+eng).
    # Поймано глазами 2026-10-19 на русском запросе про полигон Бундесвера.
    "vcg.com", "visualchina",
)


def _is_stock_domain(url):
    """Сверяем ХОСТ И ПУТЬ (расширено 2026-10-18).
    Раньше смотрели только netloc, и признак, живущий в пути, не срабатывал
    никогда: `avatars.mds.yandex.net/get-shedevrum/...` — AI-картинка
    Шедеврума на обычном яндексовом хосте, по хосту её не отличить. В списке
    уже лежали такие записи («adobe.com/stock», «livejournal.com/photo»),
    и они тоже не работали — поймано тестом, а не в бою."""
    try:
        u = urllib.parse.urlparse(url)
        hay = (u.netloc + u.path).lower()
    except Exception:
        return False
    return any(d in hay for d in _STOCK_DOMAINS)


def fetch_web_search(query, out_path, env=None):
    """Search-engine image fallback (user 2026-09-05: search-only channels —
    'сразу лезть в поиск'). Yandex first (Russian/Ukrainian names, hyper-local
    subjects — SKILL rule g), then DuckDuckGo (Bing-backed) on an English
    rendering. Ordinary web/news images, not CC — deliberate, for the user's
    own search-only channels. Caller's _accept() still runs the OCR reject."""
    try:
        import search_options as _so
    except Exception:
        return False
    cands = []
    try:
        _pace("yandex")
        cands += _so.yandex_images(query, n=12)
    except Exception: pass
    try:
        _pace("ddg")
        q_en = _so.translate_to_en(query) if any(ord(c) > 127 for c in query) else query
        cands += _so.ddg_images(q_en, n=14)
    except Exception: pass
    # --- РАЗМЕР УЧАСТВУЕТ В ОТБОРЕ (2026-10-18, улов usuario-18) ---
    # Было: брался ПЕРВЫЙ кандидат, который скачался и прошёл проверки. Размер
    # не смотрели вообще — ни порога, ни сортировки. Живой замер: 23 кадра из
    # 45 оказались уже 1600 px (в основном 1200-1300), на выводе 1920x1080 их
    # растягивает, и пользователь увидел это сразу: «много фотографий сратого
    # качества… Яндекс — бери хорошее». При этом КРУПНЫЕ версии в выдаче ЕСТЬ:
    # те же сцены дали 1199x674 → 2560x1060 и 1200x675 → 8256x5504, мы их
    # просто не выбирали (`isize=large` есть, но ширина/высота в выдаче
    # приходят нулями и в отбор не попадали).
    # Теперь: качаем кандидатов подряд, меряем, держим ЛУЧШЕГО, выходим рано
    # на действительно крупном. Порог — не жёсткий отказ: если крупнее ничего
    # нет, берём лучшее из найденного, иначе сцена осталась бы пустой.
    # Вертикальные НЕ отбрасываем (для портретов есть blur-fill), но при
    # равном размере горизонтальный выигрывает.
    _MIN_W = int(os.environ.get("MIN_IMG_W", "1600"))
    _MIN_H = int(os.environ.get("MIN_IMG_H", "900"))
    _EARLY_W = int(os.environ.get("IMG_EARLY_W", "2400"))
    _TRY_MAX = int(os.environ.get("IMG_TRY_MAX", "6"))

    def _measure(path):
        try:
            from PIL import Image as _I
            with _I.open(path) as im:
                return im.size
        except Exception:
            return (0, 0)

    _BAD = (".svg", ".pdf", ".tif", ".tiff", ".djvu")
    seen = set()
    best = None            # (score, w, h, tmp_path, md5)
    tried = 0
    tmp = out_path + ".cand"
    for c in cands:
        if tried >= _TRY_MAX:
            break
        u = c.get("full") or c.get("thumb") or ""
        if not u or u in seen: continue
        seen.add(u)
        if u.split("?")[0].lower().endswith(_BAD): continue
        if _is_stock_domain(u): continue   # reject by domain, before ever downloading
        if not _download_as_jpeg(u, tmp):
            continue
        tried += 1
        try:
            h5 = file_md5(tmp)
        except OSError:
            h5 = None
        if h5 and h5 in _WEB_USED_MD5:
            try: os.remove(tmp)
            except OSError: pass
            # ГРОМКО: причина отказа — СВОЙ ЖЕ кадр, а не «ничего не нашлось»
            # (2026-10-22). Печатаем один раз на запрос, чтобы не залить лог.
            _wh = _WEB_USED_WHERE.get(h5)
            if _wh and h5 not in _DUP_SAID:
                _DUP_SAID.add(h5)
                print(f"      дубль: этот кадр УЖЕ СТОИТ {_wh} "
                      f"[md5 {h5[:8]}] — одному файлу в ролике одна сцена. "
                      f"Нужен он же во всплывашке? Копируй файл руками. "
                      f"Нужен другой кадр? Перепиши запрос.")
            continue        # этот кадр уже стоит в другой сцене этой сборки
        w, h = _measure(tmp)
        # счёт: площадь, горизонтальный при равенстве выигрывает
        score = w * h * (1.0 if w >= h else 0.75)
        if best is None or score > best[0]:
            if best is not None:
                try: os.remove(best[3])
                except OSError: pass
            keep = tmp + ".best"
            try:
                os.replace(tmp, keep)
            except OSError:
                keep = tmp
            best = (score, w, h, keep, h5)
        else:
            try: os.remove(tmp)
            except OSError: pass
        if best and best[1] >= _EARLY_W and best[1] >= best[2]:
            break           # крупный горизонтальный — дальше не ищем
    if not best:
        return False
    score, w, h, keep, h5 = best
    try:
        os.replace(keep, out_path)
    except OSError:
        return False
    if h5:
        _WEB_USED_MD5.add(h5)
        _m = re.search(r"scene_(\d+)", os.path.basename(out_path or ""))
        _WEB_USED_WHERE.setdefault(
            h5, ("сценой %d этой сборки" % int(_m.group(1))) if _m
            else "в этой сборке")
    if w < _MIN_W or h < _MIN_H:
        print(f"  [web_search] лучшее, что нашлось: {w}x{h} — НИЖЕ порога "
              f"{_MIN_W}x{_MIN_H}, на 1920x1080 будет растянуто", flush=True)
        # ЗАПИСЫВАЕМ, А НЕ ТОЛЬКО ПЕЧАТАЕМ (23.10, улов `usuario-98`). Строка
        # выше уходит в лог шарда, а его никто не читает: в облаке двадцать
        # шардов, и вкладка узнавала о растянутом кадре только из
        # `photo_quality.py` ПОСЛЕ сборки. Живой случай: шесть кадров,
        # дофетченных взамен брака, сами оказались 1280-1500 — замена вышла не
        # лучше оригинала. Журнал едет вместе с кадрами и виден сразу.
        try:
            _lr = os.path.join(os.path.dirname(out_path or "."),
                               ".lowres." + os.environ.get("MANIFEST_NAME", "manifest.json"))
            _m2 = re.search(r"scene_(\d+)", os.path.basename(out_path or ""))
            if _m2:
                _d = {}
                if os.path.exists(_lr):
                    try:
                        _d = json.load(open(_lr, encoding="utf-8"))
                    except (OSError, ValueError):
                        _d = {}
                _d[str(int(_m2.group(1)))] = f"{w}x{h} при пороге {_MIN_W}x{_MIN_H}"
                json.dump(_d, open(_lr, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass
    else:
        print(f"  [web_search] взят кадр {w}x{h} (из {tried} кандидатов)", flush=True)
    return True


# --- НАСТОЯЩИЙ ИСТОЧНИК КАДРА, ОТДЕЛЬНО ОТ ЗАЯВЛЕННОГО (2026-10-18) ---
# `images/.sources.json` = {"<id сцены>": "<источник, который реально отдал файл>"}.
# Нужен затем, что инкрементальный проход видит готовый файл и не знает, откуда
# он взялся; без этого «cached» писал заявленный в сцене source и врал (разбор
# в ветке cached ниже). Пишется после каждого удачного скачивания, параллельным
# воркерам не мешает: файл свой на каждый images_dir, запись атомарная.
def _true_sources_path(images_dir):
    # Имя привязано к манифесту: в облаке 20 шардов пишут в ОДНУ папку и каждый
    # ведёт свой manifest.<N>.json (MANIFEST_NAME). Общий .sources.json они бы
    # перетирали друг другу (read-modify-write), поэтому у каждого свой файл.
    mn = os.environ.get("MANIFEST_NAME", "manifest.json")
    return os.path.join(images_dir, "." + mn.replace("manifest", "sources"))


def _load_true_sources(images_dir):
    """Склейка своего журнала и всех пошардовых — на кэш-проходе важно видеть,
    что нашли ОСТАЛЬНЫЕ шарды прошлого прогона, а не только свой."""
    data = {}
    try:
        for name in sorted(os.listdir(images_dir)):
            if not (name.startswith(".sources") and name.endswith(".json")):
                continue
            try:
                with open(os.path.join(images_dir, name), encoding="utf-8") as f:
                    part = json.load(f)
                if isinstance(part, dict):
                    data.update(part)
            except (OSError, ValueError):
                continue
    except OSError:
        return {}
    return data


def _load_own_true_sources(images_dir):
    try:
        with open(_true_sources_path(images_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_true_source(images_dir, sid, used_source):
    try:
        data = _load_own_true_sources(images_dir)   # свой шард, без чужих записей
        data[str(sid)] = used_source
        tmp = _true_sources_path(images_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _true_sources_path(images_dir))
    except OSError:
        pass          # журнал источников — удобство, пайплайн из-за него не рвём


def _press_waterfall(query, out_path, env):
    """The 'real photo' waterfall for `press_photo` / `wikimedia` scenes AND
    for a local_library tag folder that turned up empty. Order (user rule,
    2026-09-03): Openverse -> Flickr CC -> Internet Archive -> Wikimedia LAST.
    Wikimedia blocks and returns junk, and auto-disables after its first miss
    (see fetch_wikimedia) — it must never be the step everything waits on.
    Returns (ok, source_name)."""
    steps = [
        ("dvids", lambda: fetch_dvids(query, env.get("DVIDS_API_KEY", ""), out_path)),
        ("openverse", lambda: fetch_openverse(query, out_path)),
        ("flickr_cc", lambda: fetch_flickr_cc(query, env.get("FLICKR_API_KEY", ""), out_path)),
        ("internet_archive", lambda: fetch_internet_archive(query, out_path)),
        ("wikimedia", lambda: fetch_wikimedia(query, out_path)),
        ("web_search", lambda: fetch_web_search(query, out_path, env)),
    ]
    for name, fn in steps:
        if _past_deadline():
            print(f"  [дедлайн] бросаю водопад на шаге «{name}» — время шарда "
                  "вышло, сцена уйдёт в манифест как недобранная", flush=True)
            return False, "deadline"
        try:
            if _accept(fn(), out_path):
                return True, name
        except Exception:
            continue
    return False, "press_photo"


def _copy_from_library(src_path, out_base):
    """Копия файла медиатеки в проект, КАРТИНКА — всегда в .jpg (23.10).

    Баг, пойманный вкладкой `usuario-22` на `5min-evropa-stol-2310`: ветка
    `local_library` клала файл С ИСХОДНЫМ расширением, а `overlays.json` по
    соглашению ждёт `scene_NNN.jpg`. Пин карты из `КАРТЫ/ЧЕХИЯ` (там png)
    давал `overlays/scene_011.png`, статус `ok`, манифест тоже `.png` — и
    всплывашка просто не находилась на сборке, молча. Веб-ветка такого не
    знает: `_accept()` давно нормализует скачанное в JPEG.

    Прозрачность подкладываем БЕЛЫМ, а не чёрным: карты и схемы почти всегда
    на прозрачном фоне, и `convert("RGB")` залил бы их чёрным.
    """
    ext = os.path.splitext(src_path)[1].lower()
    if ext not in (".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".jpeg"):
        out_path = out_base + ext          # видео и уже готовый .jpg — как есть
        shutil.copyfile(src_path, out_path)
        return out_path
    out_path = out_base + ".jpg"
    try:
        from PIL import Image
        with Image.open(src_path) as im:
            if im.mode in ("RGBA", "LA", "P"):
                rgba = im.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
            else:
                flat = im.convert("RGB")
            flat.save(out_path, "JPEG", quality=92)
        return out_path
    except Exception as e:
        print(f"  [library] {os.path.basename(src_path)}: не пересохранить в "
              f"JPEG ({e}) — кладу как есть", flush=True)
        out_path = out_base + ext
        shutil.copyfile(src_path, out_path)
        return out_path


def fetch_local_library(tag_query, media_library_dir, out_base, usage_counts, ffmpeg="ffmpeg",
                        blocked_md5=None, used_md5=None, dur_hint=None, seq=0):
    """Pull from the user's own pre-vetted local folder instead of the web.
    SKILL.md makes this the FIRST source to try for news scenes about a
    recurring subject the user has hand-picked photos/clips for. `tag_query`
    is a relative path under media_library_dir ("ПОЛИТИКА/ПУТИН"), optionally
    "<tag>:<keyword>" to pull one indexed sub-clip out of a longer source
    video (see media-library/index_library.py). Rotates through whatever
    matches so the same file doesn't repeat across scenes. Returns the output
    path written, or None if the tag folder is missing/empty - caller then
    falls through to the press_photo waterfall.
    (Ported from script-to-video's fetch_assets.py - keep the two in sync if
    either is fixed.)"""
    # explicit single-file assignment: source_query is a path to one file in
    # the library. Hand-picked per scene during the audit so the exact frame
    # is chosen, not round-robin. Repetition across the video is still capped
    # by the manifest audit (rule 5).
    direct = os.path.join(media_library_dir, tag_query)
    if os.path.isfile(direct):
        try:
            h = file_md5(direct)
        except OSError:
            h = None
        # rules 4 & 5 apply to explicit picks too: reroute to a fresh file if
        # this exact file was used in the last COOLDOWN_VIDEOS videos, or is
        # already at the per-build cap (2 — leitmotifs allowed, no 3rd use).
        _blk = (blocked_md5 or set())
        # КАРТЫ ЖИВУТ ВНЕ КУЛДАУНА (2026-10-17). Кулдаун в 3 ролика придуман
        # против повторов ФУТАЖА: один и тот же кадр события в трёх роликах
        # подряд виден и раздражает. Контурная карта — не футаж, а справочный
        # объект: карта Украины везде одна и та же по смыслу, и «разнообразить»
        # её нечем. По многим регионам у нас вообще ОДИН файл, и кулдаун делал
        # карту недоступной почти всегда (живой случай: ролик дословно
        # перечисляет пять областей Украины, а карту областей поставить нечем).
        # Бан и лимит «один раз на ролик» для карт ОСТАЮТСЯ.
        _is_map = "/КАРТЫ/" in ("/" + tag_query.replace("\\", "/"))
        if _is_map and h:
            _blk = {x for x in _blk if x in load_banned_md5()}
        if h and (h in _blk or _USE_COUNT[h] >= _MAX_PER_BUILD):
            # ГРОМКО, а не молча (2026-10-17, улов рабочей вкладки на
            # planeta-svergnut-1810): раньше пин, попавший в бан/кулдаун/лимит,
            # тихо подменялся round-robin'ом по папке — вкладка была уверена,
            # что в сцене стоит выбранный глазами кадр, а стоял случайный.
            # Три забаненных пина за один ролик ловились только сверкой md5
            # руками. Теперь причина подмены видна в логе фетча.
            try:
                _why = ("забанен" if h in load_banned_md5()
                        else ("лимит на ролик" if _USE_COUNT[h] >= _MAX_PER_BUILD
                              else "кулдаун последних видео"))
            except Exception:
                _why = "бан/кулдаун/лимит"
            print(f"[{seq:03d}] ПИН ОТКЛОНЁН ({_why}): {tag_query} "
                  f"[md5 {h[:8]}] → беру round-robin по папке "
                  f"'{os.path.dirname(tag_query)}'. Если нужен именно кадр — "
                  f"выбери другой файл или снимай бан.")
            tag_query = os.path.dirname(tag_query)
        else:
            out_path = _copy_from_library(direct, out_base)
            if h:
                _USE_COUNT[h] += 1
            if used_md5 is not None and h:
                used_md5[out_path] = h
                _LIB_RELPATH[h] = os.path.relpath(direct, media_library_dir)
            return out_path

    if ":" in tag_query:
        tag, keyword = tag_query.split(":", 1)
        keyword = keyword.strip().lower()
    else:
        tag, keyword = tag_query, None

    tag_dir = os.path.join(media_library_dir, tag)
    if not os.path.isdir(tag_dir):
        return None

    if keyword:
        index_path = os.path.join(tag_dir, "index.json")
        index = {}
        if os.path.exists(index_path):
            with open(index_path, encoding="utf-8") as f:
                index = json.load(f)
        # never pull a stylised / horror / intro-sfx segment for a news scene —
        # the РОССИЯ folder also holds "#ПРЕДСКАЗАТЕЛЬ" esoteric clips whose
        # winter/forest shots carry blood-spatter and bat-silhouette effects.
        _SFX_TAGS = {"хоррор", "кровь", "брызги", "летучая", "мышь", "силуэт",
                     "интро", "транзишн", "спецэффект", "блёстки", "блестки"}
        matches = [
            (fname, seg) for fname, segs in index.items() for seg in segs
            if any(keyword in t.lower() for t in seg.get("tags", []))
            and not (_SFX_TAGS & {t.lower() for t in seg.get("tags", [])})
            and not _is_stylized(fname, seg.get("tags", []))
        ]
        if matches:
            key = f"{tag}:{keyword}"
            # rotate; prefer a segment not yet used this build, then one used
            # once, never a 3rd use (leitmotif cap = _MAX_PER_BUILD).
            n_m = len(matches)
            base = usage_counts.get(key, 0)
            idx = base % n_m
            for ceiling in (1, _MAX_PER_BUILD):
                hit = next((j for j in range(n_m)
                            if _USE_COUNT[(matches[(base + j) % n_m][0],
                                           round(matches[(base + j) % n_m][1]["start"], 2))] < ceiling),
                           None)
                if hit is not None:
                    idx = (base + hit) % n_m
                    break
            usage_counts[key] = base + 1
            fname, seg = matches[idx]
            _USE_COUNT[(fname, round(seg["start"], 2))] += 1
            use_n = _USE_COUNT[(fname, round(seg["start"], 2))]
            src_path = os.path.join(tag_dir, fname)
            out_path = out_base + ".mp4"
            # Cut a scene-length window from the DETECTED cut point (seg.start
            # = a real scene boundary = start of a clean shot). First use starts
            # exactly there; a reuse of the same segment shifts in by 2s steps
            # so two scenes pulling one segment yield two distinct clips
            # (md5-dedup wants zero repeats). Cutting the whole segment instead
            # gave byte-identical clips + drift into the wrong shot.
            # СЕГМЕНТ КОРОЧЕ СЦЕНЫ — ТЯНЕМ ДАЛЬШЕ, А НЕ ОТДАЁМ ОГРЫЗОК (24.10).
            # Было `want = min(dur_hint, seg_len)`: пин `ПОЛИТИКА/ПУТИН:журналисты`
            # на сцену 12,4 с отдавал клип 3,30 с, `…:совещание` на 13,0 с — 5,07 с,
            # и оба с бодрым `ok` в логе и в манифесте. Дальше `build_clips`
            # добивал это `-stream_loop -1`, и зритель видел одно движение
            # четырежды (улов `usuario-29`). Правило 3 в SKILL.md обещало ровно
            # обратное — «кусок ДЛИНОЙ СЦЕНЫ». Теперь так и есть: окно тянется до
            # следующего ОБНАРУЖЕННОГО реза (чужой кадр не захватываем) либо до
            # конца файла, и если всё равно не хватило — говорим об этом вслух.
            seg_len = max(0.5, seg["end"] - seg["start"])
            need = float(dur_hint or seg_len)
            hard_end = seg["end"]
            if need > seg_len + 0.05:
                _later = sorted(s["start"] for s in index.get(fname, [])
                                if s.get("start", 0) > seg["end"] + 0.05)
                if _later:
                    hard_end = _later[0]
                else:
                    try:
                        _pr = subprocess.run(
                            ["ffprobe", "-v", "error", "-show_entries",
                             "format=duration", "-of", "csv=p=0", src_path],
                            capture_output=True, text=True, timeout=20)
                        hard_end = max(hard_end, float(_pr.stdout.strip() or 0))
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass
            avail = max(0.5, hard_end - seg["start"])
            want = min(need, avail)
            if want < need - 0.3:
                print(f"[{seq:03d}] КОРОТКИЙ БИБЛИОТЕЧНЫЙ КУСОК: {fname} даёт "
                      f"{want:.2f} с на сцену {need:.2f} с — сборка зациклит его "
                      f"×{need / max(want, 0.01):.1f}. Пинь ТОЧНЫЙ файл подлиннее "
                      f"или смени сцену на поиск", flush=True)
            off = min(max(0.0, avail - want), (use_n - 1) * 2.0)
            cmd = [ffmpeg, "-y", "-ss", f"{seg['start'] + off:.2f}", "-i", src_path,
                   "-t", f"{want:.2f}", "-c:v", "libx264",
                   "-preset", "veryfast", "-crf", "20", "-an", out_path]
            subprocess.run(cmd, check=True, capture_output=True)
            return out_path

    exts = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")
    files = sorted(f for f in os.listdir(tag_dir) if f.lower().endswith(exts))
    # drop stylised / AI-composite clips ("animate*.mp4", emblem-glow renders):
    # a news scene needs a real photo/clip, not a motion-graphics render.
    # Hit live on ukraincy-begut-0709: round-robin over ПОЛИТИКА/НАТО and
    # ПОЛИТИКА/ЕВРОПА-армия kept serving "animate*.mp4" (NATO-emblem glow,
    # missiles-over-EU-stars) which look fabricated next to news narration.
    real = [f for f in files if not _is_stylized(f, ())]
    if real:
        files = real
    if not files:
        return None

    blocked_md5 = blocked_md5 or set()
    # rotate through the folder, but skip files used in the last N videos
    # (rule 4) and files already used earlier in THIS video (rule 5).
    n = len(files)
    start = usage_counts.get(tag, 0)
    chosen = None
    for step in range(n):
        cand = files[(start + step) % n]
        cand_path = os.path.join(tag_dir, cand)
        try:
            h = file_md5(cand_path)
        except OSError:
            continue
        if h in blocked_md5:
            continue
        if _USE_COUNT[h] >= _MAX_PER_BUILD:
            continue
        chosen, chosen_md5 = cand, h
        usage_counts[tag] = (start + step + 1)
        break

    if chosen is None:
        # every file in this folder is on cooldown / already used -> rule 4:
        # fail loudly, do NOT recycle an old shot.
        return "EXHAUSTED"

    src_path = os.path.join(tag_dir, chosen)
    out_path = _copy_from_library(src_path, out_base)
    _USE_COUNT[chosen_md5] += 1
    if used_md5 is not None:
        used_md5[out_path] = chosen_md5
        _LIB_RELPATH[chosen_md5] = os.path.relpath(src_path, media_library_dir)
    return out_path


# md5 -> library relpath, filled as files are picked, for the usage log
_LIB_RELPATH = {}


def load_env(env_path):
    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v
    return env


# ПОТОЛОК НА ЧТЕНИЕ ОТВЕТА — ПО ОБЩЕМУ ВРЕМЕНИ, А НЕ ПО БЕЗДЕЙСТВИЮ (23.10).
# Корень зависших шардов, найденный на `planeta-zapad-front-2410` (прогон
# 39923281250, cptand-pub): 15 шардов из 20 отработали за 76-139 с, пять
# висели до самого `timeout-minutes` — 28 минут. Причина НЕ в разбросе машин
# (все 20 стартовали в одну секунду) и не в том, что таймаут не применился:
# `timeout=N` у `urlopen` — это таймаут БЕЗДЕЙСТВИЯ сокета. Сервер, отдающий
# тело по чуть-чуть, его не нарушает ни разу, и `resp.read()` висит сколько
# угодно. Мягкий дедлайн шарда это не ловит: он проверяется МЕЖДУ сценами, а
# зависание происходит ВНУТРИ одной. Поэтому читаем кусками и обрываем по
# общему времени — тогда сцена честно падает в «не добыл», шард идёт дальше,
# а дедлайн снова начинает работать.
_READ_LIMIT_SEC = float(os.environ.get("FETCH_READ_LIMIT_SEC", "90") or 90)

# МЯГКИЙ ДЕДЛАЙН ВИДЕН НЕ ТОЛЬКО МЕЖДУ СЦЕНАМИ (23.10). Он проверялся ровно в
# одном месте — в цикле по сценам, — и потому ни разу не сработал на живых
# прогонах: время шард проводит ВНУТРИ сцены, в водопаде из шести источников.
# Итог дважды за день: шарды доживали до жёсткого таймаута и теряли ВСЁ, хотя
# должны были остановиться сами и записать манифест с пометкой «не успели».
# Теперь дедлайн лежит в модуле, и водопад сверяется с ним перед каждым шагом.
_DEADLINE_AT = 0.0


def _past_deadline():
    return bool(_DEADLINE_AT) and time.time() > _DEADLINE_AT
# Страховка для путей, где таймаут не передан явно: без неё такой сокет ждёт
# бесконечно (настройка процесса, на уже открытые соединения не влияет).
socket.setdefaulttimeout(60)


def _read_capped(resp, max_bytes=None, limit_sec=None, what="ответ"):
    limit = _READ_LIMIT_SEC if limit_sec is None else limit_sec
    t0 = time.time()
    parts, got = [], 0
    while True:
        if limit and time.time() - t0 > limit:
            # ПЕЧАТАЕМ ПРЯМО ЗДЕСЬ (23.10, запрос `usuario-21`). Раньше обрыв
            # только выбрасывал исключение, и выше по стеку оно превращалось в
            # обычное «не скачалось» — в логе шарда НИ ОДНОЙ строки про потолок.
            # Замер «сколько адресов упёрлось в потолок» было негде взять.
            print(f"  [потолок] обрываю чтение: {limit:.0f} с, получено "
                  f"{got // 1024} КБ — {what}", flush=True)
            raise TimeoutError(
                f"чтение дольше {limit:.0f} с, получено {got // 1024} КБ — обрываю ({what})")
        # read1, а НЕ read: read(N) ждёт, пока наберётся весь кусок, и на
        # медленной отдаче один такой вызов висит минутами — проверка времени
        # до него просто не доходит (поймано стендом 23.10: сервер слал по
        # 1 КБ в полсекунды, кусок 256 КБ читался бы 128 с). read1 отдаёт то,
        # что уже пришло, поэтому потолок проверяется часто.
        chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(16384)
        if not chunk:
            break
        parts.append(chunk)
        got += len(chunk)
        if max_bytes is not None and got > max_bytes:
            break
    # МЕДЛЕННОЕ, НО ЖИВОЕ СКАЧИВАНИЕ ТОЖЕ ВИДНО (23.10). Замер показал, что
    # шесть шардов из двадцати идут вчетверо дольше медианы, а потолок при этом
    # НЕ срабатывает ни разу: время уходит не на зависания, а на сумму
    # медленных живых загрузок. Без этой строки понять, на чём именно, нельзя.
    _spent = time.time() - t0
    if _spent > 10:
        print(f"  [медленно] {_spent:.0f} с, {got // 1024} КБ — {what}", flush=True)
    return b"".join(parts)


def http_get(url, headers=None, timeout=18):
    h = {"User-Agent": DEFAULT_UA}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _read_capped(resp, what=url[:80])


# --- Wikimedia is NEVER a blocking step (user, 2026-09-03, twice, angry) ---
# Commons rate-limits / blocks then returns junk anyway. Rule: ONE try, short
# timeout; the FIRST failure turns it OFF for the whole run. It also sits LAST
# in every waterfall — search-based / aggregator sources go first.
_WM_DEAD = [False]


def fetch_wikimedia(query, out_path):
    if _WM_DEAD[0]:
        return False
    _pace("wikimedia")
    search_url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrnamespace": 6, "gsrlimit": 5, "prop": "imageinfo",
            "iiprop": "url|size", "format": "json",
            # для КАРТ (ниже) нужен готовый растр из svg — Commons отдаёт его
            # в thumburl, если попросить ширину
            "iiurlwidth": 1600,
        }
    )
    try:
        data = json.loads(http_get(search_url, timeout=7))
    except Exception:
        _WM_DEAD[0] = True
        print("  [wikimedia отключён на весь прогон — не отвечает/блокирует]")
        return False
    pages = data.get("query", {}).get("pages", {})
    image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    # КАРТЫ — отдельный случай (2026-10-17). На Commons чистые контурные карты
    # почти все в SVG, а этот цикл SVG всегда отбрасывал — поэтому «карта» как
    # класс запроса не добывалась ВООБЩЕ (живой случай: «политическая карта
    # Украины с областями», FAILED на двух формулировках, всплывашка потеряна).
    # Для карт берём готовый растр из thumburl. Разрешаем это ТОЛЬКО когда
    # запрос прямо про карту: иначе через SVG полезут схемы, диаграммы, флаги и
    # логотипы, а инфографика и чужие логотипы запрещены правилом a1.
    _map_q = any(w in query.lower() for w in
                 ("карт", "map", "outline", "контурн", "очертани"))
    best = None
    for p in pages.values():
        for ii in p.get("imageinfo", []):
            url = ii.get("url", "")
            low = url.lower().split("?")[0]
            if low.endswith(".svg") and _map_q and ii.get("thumburl"):
                w, h = ii.get("thumbwidth", 0), ii.get("thumbheight", 0)
                if w * h > (best[1] if best else 0):
                    best = (ii["thumburl"], w * h)
                continue
            if not low.endswith(image_exts):
                continue  # Commons' File namespace also holds PDF/DjVu/SVG/audio - skip those
            w, h = ii.get("width", 0), ii.get("height", 0)
            if w * h > (best[1] if best else 0):
                best = (url, w * h)
    if not best:
        return False
    try:
        blob = http_get(best[0], timeout=15)
    except Exception:
        _WM_DEAD[0] = True
        return False
    with open(out_path, "wb") as f:
        f.write(blob)
    return True


def fetch_openverse(query, out_path):
    """Openverse (api.openverse.org) aggregates CC-licensed images from many
    sources in one search - Europeana, museum/gallery collections, Flickr,
    Wikimedia and more. Free, no API key required for light/personal use
    (an optional free key raises the rate limit - not needed here)."""
    search_url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "license_type": "commercial,modification", "page_size": 5}
    )
    data = json.loads(http_get(search_url))
    results = data.get("results", [])
    image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    for r in results:
        url = r.get("url", "")
        if not url.lower().split("?")[0].endswith(image_exts):
            continue
        try:
            img_bytes = http_get(url)
        except Exception:
            continue
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        return True
    return False


def fetch_internet_archive(query, out_path):
    search_url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
        {"q": f"{query} AND mediatype:image", "fl[]": "identifier", "rows": 5, "output": "json"}
    )
    data = json.loads(http_get(search_url))
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        return False
    image_exts = (".jpg", ".jpeg", ".png")
    for doc in docs:
        identifier = doc["identifier"]
        try:
            meta = json.loads(http_get(f"https://archive.org/metadata/{identifier}"))
        except Exception:
            continue
        candidates = [
            f for f in meta.get("files", [])
            if f.get("name", "").lower().endswith(image_exts) and f.get("source") != "metadata"
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda f: int(f.get("size", 0)), reverse=True)
        filename = candidates[0]["name"]
        try:
            img_bytes = http_get(f"https://archive.org/download/{identifier}/{urllib.parse.quote(filename)}")
        except Exception:
            continue
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        return True
    return False


def fetch_flickr_cc(query, api_key, out_path):
    """Flickr photos.search restricted to Creative Commons / public-domain
    licenses (license IDs: 1-10 = various CC, plus 9=CC0, 10=Public Domain
    Mark - excludes license 0 = All Rights Reserved). Free API key from
    https://www.flickr.com/services/apps/create/apply - no cost, no card."""
    if not api_key:
        return False
    search_url = "https://api.flickr.com/services/rest/?" + urllib.parse.urlencode(
        {
            "method": "flickr.photos.search", "api_key": api_key, "text": query,
            "license": "1,2,3,4,5,6,7,8,9,10", "sort": "relevance", "per_page": 5,
            "content_type": 1, "media": "photos", "extras": "url_c,url_o,url_l",
            "format": "json", "nojsoncallback": 1,
        }
    )
    data = json.loads(http_get(search_url))
    photos = data.get("photos", {}).get("photo", [])
    for p in photos:
        url = p.get("url_o") or p.get("url_l") or p.get("url_c")
        if not url:
            continue
        with open(out_path, "wb") as f:
            f.write(http_get(url))
        return True
    return False


def fetch_dvids(query, api_key, out_path):
    """DVIDS (Defense Visual Information Distribution Service, dvidshub.net) -
    the U.S. Department of Defense's own photo wire. Every asset is a U.S.
    government work -> public domain by default (17 U.S.C. 105), so unlike a
    press/stock photo there's no watermark to fight. Narrow scope: only ever
    returns something for a scene genuinely about the U.S. military / DoD /
    a U.S.-hosted event a DoD photographer covered (Pentagon briefing, a
    carrier strike group, NATO exercise with US troops, POTUS at a US-military
    venue). It will not have anything for Kremlin, Ukrainian, or most other
    countries' own events - still fine to try first, a miss costs one fast
    HTTP call. Free account + key: https://www.dvidshub.net/member/registration
    (key shows up in account settings after signup; user sets DVIDS_API_KEY
    in .env - see SKILL.md)."""
    if not api_key:
        return False
    search_url = "https://api.dvidshub.net/search?" + urllib.parse.urlencode(
        {"q": query, "type": "image", "max_results": 5, "api_key": api_key}
    )
    try:
        data = json.loads(http_get(search_url))
    except Exception:
        return False
    for r in data.get("results", []):
        asset_id = r.get("id")
        if not asset_id:
            continue
        try:
            asset_url = "https://api.dvidshub.net/asset?" + urllib.parse.urlencode(
                {"id": asset_id, "api_key": api_key}
            )
            meta = json.loads(http_get(asset_url))
            img_url = meta.get("results", {}).get("image")
            if not img_url:
                continue
            img_bytes = http_get(img_url)
        except Exception:
            continue
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        return True
    return False


def fetch_pexels_photo(query, api_key, out_path):
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": 3, "orientation": "landscape"}
    )
    data = json.loads(http_get(url, {"Authorization": api_key}))
    photos = data.get("photos", [])
    if not photos:
        return False
    with open(out_path, "wb") as f:
        f.write(http_get(photos[0]["src"]["large2x"]))
    return True


def fetch_pexels_video(query, api_key, out_path, target_width=1280):
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": 5, "orientation": "landscape", "size": "medium"}
    )
    data = json.loads(http_get(url, {"Authorization": api_key}))
    for v in data.get("videos", []):
        candidates = [f for f in v["video_files"] if f["quality"] == "hd" and f["width"] <= 1920]
        if not candidates:
            continue
        candidates.sort(key=lambda f: abs(f["width"] - target_width))
        with open(out_path, "wb") as f:
            f.write(http_get(candidates[0]["link"]))
        return True
    return False


# --- Pixabay: second free stock source, tried when Pexels has no key / is
# down (401 etc) or returns nothing - same "generic object only" scope as
# Pexels, never used for a specific real person/event (user, 2026-09-20,
# after the Pexels API key started 401'ing mid-session on several builds).
def fetch_pixabay_photo(query, api_key, out_path):
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode(
        {"key": api_key, "q": query, "image_type": "photo",
         "orientation": "horizontal", "safesearch": "true", "per_page": 3}
    )
    data = json.loads(http_get(url))
    hits = data.get("hits", [])
    if not hits:
        return False
    with open(out_path, "wb") as f:
        f.write(http_get(hits[0]["largeImageURL"]))
    return True


def fetch_pixabay_video(query, api_key, out_path, target_width=1280):
    url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": api_key, "q": query, "safesearch": "true", "per_page": 5}
    )
    data = json.loads(http_get(url))
    for v in data.get("hits", []):
        files = v.get("videos", {})
        candidates = [f for f in files.values() if f.get("url") and f.get("width")]
        if not candidates:
            continue
        candidates.sort(key=lambda f: abs(f["width"] - target_width))
        with open(out_path, "wb") as f:
            f.write(http_get(candidates[0]["url"]))
        return True
    return False


def fetch_stock_photo(query, env, out_path):
    """Pexels first, Pixabay as fallback - either one satisfies pexels_photo."""
    try:
        if not env.get("PEXELS_API_KEY"):
            print("  [pexels_photo] ключа PEXELS_API_KEY нет в .env")
        else:
            _raw = fetch_pexels_photo(query, env["PEXELS_API_KEY"], out_path)
            if not _raw:
                print("  [pexels_photo] ключ ответил, по запросу ничего подходящего — пробую pixabay")
            elif _accept(_raw, out_path):
                return True
            else:
                print("  [pexels_photo] кадр найден, но ОТКЛОНЁН (знак/текст/бан) — пробую pixabay")
    except Exception as e:
        print(f"  [pexels_photo error, trying pixabay] {e}")
    if env.get("PIXABAY_API_KEY"):
        try:
            return _accept(fetch_pixabay_photo(query, env["PIXABAY_API_KEY"], out_path), out_path)
        except Exception as e:
            print(f"  [pixabay_photo error] {e}")
    return False


def _accept_video(ok, out_path):
    """Video counterpart to _accept() — no OCR (can't tesseract a video
    cheaply), but a permanently-banned md5 must still be rejected here.
    Root-caused 2026-09-27: fetch_stock_video() never checked the ban list
    at all, so a banned pexels_video clip kept being re-downloaded and
    shipped straight into a dashboard the user had explicitly banned it
    from — the still-photo path (_accept()) already had this check, video
    never did."""
    if not ok:
        return ok
    try:
        if file_md5(out_path) in load_banned_md5():
            os.remove(out_path)
            return False
    except OSError:
        pass
    return ok


def fetch_stock_video(query, env, out_path):
    """Pexels first, Pixabay as fallback - either one satisfies pexels_video."""
    # ПОЧЕМУ ЗДЕСЬ ПЕЧАТЬ ПРИЧИНЫ (2026-10-18): молчаливый `return False`
    # заставил вкладку решить, что «Pexels локально мёртв, а в облаке живой»,
    # и увести сцену в press_photo по правилу про 403. Проверка ключа curl'ом
    # показала HTTP 200 и остаток 14414 из 25000 — то есть ключ был жив, а
    # сцена падала по другой причине (ничего не нашлось либо кадр отклонён
    # бан-листом/фильтром). Отличать эти три случая теперь обязана сама строка
    # лога, иначе каждый раз диагностируют не то.
    try:
        if not env.get("PEXELS_API_KEY"):
            print("  [pexels_video] ключа PEXELS_API_KEY нет в .env")
        else:
            _raw = fetch_pexels_video(query, env["PEXELS_API_KEY"], out_path)
            if not _raw:
                print("  [pexels_video] ключ ответил, по запросу ничего подходящего — пробую pixabay")
            elif _accept_video(_raw, out_path):
                return True
            else:
                print("  [pexels_video] клип найден, но ОТКЛОНЁН (бан-лист) — пробую pixabay")
    except Exception as e:
        print(f"  [pexels_video error, trying pixabay] {e}")
    if env.get("PIXABAY_API_KEY"):
        try:
            return _accept_video(fetch_pixabay_video(query, env["PIXABAY_API_KEY"], out_path), out_path)
        except Exception as e:
            print(f"  [pixabay_video error] {e}")
    return False


# ГОТОВЫЙ МЕДИА-АДРЕС — ИСТОЧНИК `direct_url` (2026-10-20, диспетчер `andrey-b8`)
#
# Зачем: досье георадара приносит ссылки на посты источников, и к постам
# ПРИКРЕПЛЕНЫ фото И ВИДЕО — это готовые кадры события, а не поисковая
# лотерея. До сих пор вкладка качала их руками `curl`, и такой кадр
# проходил МИМО всех сит: ни бан-листа, ни OCR, ни манифеста, ни адреса
# источника. Видео-лид при этом провален семь роликов подряд, и лечение
# пользователь назвал прямым словом — брать видео из постов источников,
# норму не трогать.
#
# Теперь это обычный источник сцены: в `source` ставится `direct_url`, в
# `source_query` — один адрес или несколько через пробел/`|` (пробуются по
# порядку, первый годный выигрывает). Расширение выбирается по СОДЕРЖИМОМУ,
# а не по ссылке: телеграм отдаёт файлы без расширения вовсе.
#
# Сита те же, что у остальных источников: бан-md5 (фото и видео), OCR на
# тяжёлый текст и стоковые клейма (фото), минимальный размер кадра, проверка
# ffprobe на декодируемость (видео). Адрес запоминается в манифесте.
_DIRECT_MAX_BYTES = 120 * 1024 * 1024   # телеграм-видео бывает крупным
_DIRECT_MIN_VIDEO = 150 * 1024          # меньше — почти наверняка заглушка/превью
_DIRECT_MIN_BASE_H = 700                # базовому кадру нужно ≥720p, см. SKILL.md
_DIRECT_LAST_WH = {}                    # путь -> (ширина, высота) последнего видео


def _direct_split(query):
    out = []
    for chunk in (query or "").replace("|", " ").replace(",", " ").split():
        c = chunk.strip().strip("<>\u00ab\u00bb\"'")
        if c.startswith(("http://", "https://")):
            out.append(c)
    return out


def _direct_download(url):
    """Качает адрес целиком в память с потолком. Возвращает (blob, ctype)."""
    host = url.split("/")
    ref = host[0] + "//" + host[2] + "/" if len(host) > 2 else url
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA,
                                               "Referer": ref})
    with urllib.request.urlopen(req, timeout=40) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        # вложения телеграма (cdn*.telesco.pe) — главный источник зависаний
        blob = _read_capped(resp, _DIRECT_MAX_BYTES + 1, what="direct_url " + url[:60])
    if len(blob) > _DIRECT_MAX_BYTES:
        raise ValueError(f"файл больше {_DIRECT_MAX_BYTES // (1024*1024)} МБ")
    return blob, ctype


def _direct_kind(blob, ctype):
    head = blob[:16]
    if (head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n"
            or head[:6] in (b"GIF87a", b"GIF89a") or head[8:12] == b"WEBP"):
        return "image"
    if head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3":
        return "video"
    if ctype.startswith("image/"):
        return "image"
    if ctype.startswith("video/"):
        return "video"
    return ""


def _direct_save_video(blob, out_base, ffmpeg="ffmpeg"):
    """Кладёт видео как .mp4. Matroska/WebM перепаковывает (контейнер .webm
    в конвейере нигде не ждут), mp4/mov оставляет как есть."""
    if len(blob) < _DIRECT_MIN_VIDEO:
        return ""
    out = out_base + ".mp4"
    if blob[4:8] == b"ftyp":
        with open(out, "wb") as f:
            f.write(blob)
    else:
        tmp = out_base + ".src"
        with open(tmp, "wb") as f:
            f.write(blob)
        okr = False
        for args in (["-c", "copy"], ["-c:v", "libx264", "-preset", "veryfast",
                                      "-crf", "22", "-c:a", "aac"]):
            try:
                subprocess.run([ffmpeg, "-y", "-v", "error", "-i", tmp]
                               + args + [out],
                               check=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=600)
                okr = os.path.isfile(out) and os.path.getsize(out) > _DIRECT_MIN_VIDEO
            except Exception:
                okr = False
            if okr:
                break
        try:
            os.remove(tmp)
        except OSError:
            pass
        if not okr:
            return ""
    # ffprobe — последнее сито: битый или обрезанный файл дальше не едет.
    # Попутно снимаем РАЗМЕР КАДРА: по описи `media_type` в георадаре его не
    # видно, а вложение бывает 640x352 (2026-10-20, улов `usuario-3f`) — такое
    # в базовую сцену означает апскейл втрое, то есть мыло во весь экран.
    try:
        pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height",
                             "-show_entries", "format=duration",
                             "-of", "default=nw=1:nk=1", out],
                            capture_output=True, text=True, timeout=60)
        vals = [x.strip() for x in (pr.stdout or "").splitlines() if x.strip()]
        if pr.returncode != 0 or len(vals) < 3:
            os.remove(out)
            return ""
        w, h, dur = int(float(vals[0])), int(float(vals[1])), float(vals[2])
        if dur < 0.5:
            os.remove(out)
            return ""
        _DIRECT_LAST_WH[os.path.abspath(out)] = (w, h)
    except Exception:
        try:
            os.remove(out)
        except OSError:
            pass
        return ""
    return out


def _direct_save_image(blob, out_base, for_overlay=False):
    # ПОРОГ РАЗМЕРА — ТОЛЬКО ДЛЯ БАЗОВОГО КАДРА (2026-10-22, улов `usuario-82`:
    # потеряно 2 годных вложения из досье). Телеграм отдаёт картинки 500-800 px
    # по длинной стороне, и для ВСПЛЫВАШКИ это норма: она занимает четверть
    # экрана. Порог 500x320 от 18.10 считался под кадр во весь экран. Это тот
    # же случай, что уже разобран с «тяжёлым текстом»: всплывашке свои мерки.
    lim_w, lim_h = (300, 200) if for_overlay else (500, 320)
    tmp = out_base + ".raw"
    with open(tmp, "wb") as f:
        f.write(blob)
    out = out_base + ".jpg"
    try:
        from PIL import Image
        im = Image.open(tmp); im.load()
        if im.width < lim_w or im.height < lim_h:
            os.remove(tmp)
            return ""
        im.convert("RGB").save(out, "JPEG", quality=90)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return ""
    try:
        os.remove(tmp)
    except OSError:
        pass
    return out


def _accept_direct_photo(path, allow_text):
    """Сито для фото, приехавшего по ГОТОВОМУ адресу из досье.

    Отличие от `_accept()` ровно одно и оно важное: для ВСПЛЫВАШКИ порог
    «тяжёлый текст» не применяется. Повод (2026-10-20, улов `usuario-40`):
    из трёх вложений доехало одно, а ДВА СКРИНШОТА ПУБЛИКАЦИЙ (Axios про
    встречу с сенаторами, Washington Post про задержку Patriot) сито
    зарезало — у них плотный текст во весь кадр. То есть главный годный
    актив телеграм-постов через `direct_url` не проходил в принципе.
    Порог на текст существует против СЛУЧАЙНОЙ веб-картинки (скриншот
    страницы вместо фото), а вложение из досье выбрано человеком и адрес
    вписан руками — там это сито лишнее.

    Что остаётся включённым всегда, и для всплывашки тоже: бан-лист по md5
    и стоковые клейма. От них послабления нет.

    Для БАЗОВОГО кадра порог сохранён: скриншот издания во весь экран сцены
    — это ровно то, что пользователь запретил («никаких документов и
    бумаг с текстом»), всплывашка же для цитаты издания и предназначена.
    """
    try:
        if file_md5(path) in load_banned_md5():
            os.remove(path)
            return False, "бан-лист"
    except OSError:
        pass
    words, blob = _ocr_words(path)
    if any(w in blob for w in _STOCK_WATERMARKS):
        try:
            os.remove(path)
        except OSError:
            pass
        return False, "стоковое клеймо"
    if not allow_text and words > 8:
        try:
            os.remove(path)
        except OSError:
            pass
        return False, ("тяжёлый текст — для БАЗОВОГО кадра не годится; "
                       "если это скриншот публикации, ставь его всплывашкой")
    return True, ""


# --- ДВЕ БЕДЫ ВЛОЖЕНИЙ, КОТОРЫХ НЕ ВИДНО ПО РАЗРЕШЕНИЮ (2026-10-22, улов
# `usuario-f1` на `ze-soglasen-2310`) ------------------------------------
# 1. ТЕЛЕГРАМ ОТДАЁТ ОДИН И ТОТ ЖЕ ФАЙЛ НА РАЗНЫЕ ПОСТЫ. Адреса разные, md5
#    один — в ролике получаются две сцены с одинаковым видео (сцены 1 и 17).
#    Ловится только сверкой md5 между сценами, глазами на контактном листе
#    видно уже поздно.
# 2. ПЯТЬ ИЗ ШЕСТИ ВЛОЖЕНИЙ ОКАЗАЛИСЬ ЭФИРОМ FOX NEWS с плашкой «FOX NEWS
#    ALERT» на весь низ и «LIVE» вверху. По правилу 19.10 эфирная плашка —
#    брак (газета можно, эфир нет). Промер разрешения её не видит: на
#    репост-пабликах такая плашка ровно такая же норма, как низкое качество.
#    Лечится кропом, поэтому печатаем ГОТОВУЮ команду, а не просто ругань.
_BROADCAST_TOKENS = ("live", "breaking", "alert", "news alert", "fox news",
                     "cnn", "msnbc", "sky news", "bbc news", "прямой эфир",
                     "срочно", "в эфире")
_DIRECT_CROP_HINT = ("crop=in_w*0.72:in_h*0.72:in_w*0.14:in_h*0.08"
                     ",scale=1920:-2")


def _broadcast_banner(path, ffmpeg="ffmpeg"):
    """Слова телевизионной плашки на кадре, или ''. Видео — по стоп-кадру."""
    probe = path
    tmp = ""
    if os.path.splitext(path)[1].lower() in (".mp4", ".mov", ".webm"):
        tmp = path + ".banner.jpg"
        try:
            subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", "1", "-i", path,
                            "-frames:v", "1", tmp],
                           check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60)
            probe = tmp
        except Exception:
            return ""
    try:
        _n, text = _ocr_words(probe)
    except Exception:
        text = ""
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    hits = [t for t in _BROADCAST_TOKENS if t in (text or "")]
    return ", ".join(sorted(set(hits)))


def fetch_direct_url(query, out_base, ffmpeg="ffmpeg", for_overlay=False):
    # `for_overlay` снимает ДВА ограничения базового кадра: порог «тяжёлый
    # текст» (скриншот публикации — законная всплывашка) и минимальное
    # разрешение (мелкое видео во всплывашке приемлемо, во весь экран нет).
    """Готовый адрес медиа (вложение телеграм-поста, файл на сайте источника).

    Возвращает путь к файлу или "" — НИКОГДА не подменяет кадр чем-то другим:
    промах здесь должен быть видно в логе, чтобы сцену переписали руками.
    """
    urls = _direct_split(query)
    if not urls:
        print("  [direct_url] в source_query нет http-адреса", flush=True)
        return ""
    for url in urls:
        try:
            blob, ctype = _direct_download(url)
        except Exception as e:
            print(f"  [direct_url] не скачалось ({e}): {url[:110]}", flush=True)
            continue
        kind = _direct_kind(blob, ctype)
        if not kind:
            print(f"  [direct_url] не фото и не видео (Content-Type '{ctype}', "
                  f"{len(blob)} Б): {url[:110]}", flush=True)
            continue
        if kind == "video":
            path = _direct_save_video(blob, out_base, ffmpeg)
            if not path:
                print(f"  [direct_url] видео не читается/слишком мелкое: {url[:110]}",
                      flush=True)
                continue
            _w, _h = _DIRECT_LAST_WH.get(os.path.abspath(path), (0, 0))
            if _w:
                print(f"  [direct_url] размер кадра {_w}x{_h}", flush=True)
            if not for_overlay and _h and _h < _DIRECT_MIN_BASE_H:
                os.remove(path)
                print(f"  [direct_url] видео {_w}x{_h} ОТКЛОНЕНО для БАЗОВОЙ сцены "
                      f"(нужно ≥720p, иначе апскейл во весь экран); во всплывашку "
                      f"такое годится: {url[:110]}", flush=True)
                continue
            if not _accept_video(True, path):
                print(f"  [direct_url] видео ОТКЛОНЕНО бан-листом: {url[:110]}",
                      flush=True)
                continue
        else:
            path = _direct_save_image(blob, out_base, for_overlay=for_overlay)
            if not path:
                print(f"  [direct_url] фото мелкое или битое "
                      f"(порог {'300x200 для всплывашки' if for_overlay else '500x320 для базовой сцены'}): "
                      f"{url[:110]}", flush=True)
                continue
            okp, why = _accept_direct_photo(path, for_overlay)
            if not okp:
                print(f"  [direct_url] фото ОТКЛОНЕНО ({why}): {url[:110]}",
                      flush=True)
                continue
        # ДУБЛЬ ПО СОДЕРЖИМОМУ: адреса разные, файл один и тот же
        try:
            _h5 = file_md5(path)
        except OSError:
            _h5 = ""
        if _h5 and _h5 in _WEB_USED_MD5:
            _wh = _WEB_USED_WHERE.get(_h5, "в этой сборке")
            os.remove(path)
            print(f"  [direct_url] ТОТ ЖЕ ФАЙЛ уже стоит {_wh} [md5 {_h5[:8]}] — "
                  f"телеграм отдаёт одно вложение на разные посты. Беру "
                  f"следующий адрес: {url[:110]}", flush=True)
            continue
        if _h5:
            _WEB_USED_MD5.add(_h5)
            _m = re.search(r"scene_(\d+)", os.path.basename(out_base or ""))
            _WEB_USED_WHERE.setdefault(
                _h5, ("сценой %d этой сборки" % int(_m.group(1))) if _m
                else "в этой сборке")
        # ПЛАШКА ЭФИРА: разрешение в порядке, а кадр всё равно брак
        _ban = _broadcast_banner(path, ffmpeg)
        if _ban:
            print(f"  [direct_url] ВНИМАНИЕ: на кадре плашка эфира ({_ban}) — "
                  f"по правилу 19.10 эфирный титр брак, газетный нет. Лечится "
                  f"кропом, кадр НЕ отклоняю:", flush=True)
            print(f"      ffmpeg -y -i {path} -vf \"{_DIRECT_CROP_HINT}\" "
                  f"-c:a copy {path}.crop.mp4 && mv {path}.crop.mp4 {path}",
                  flush=True)
        _remember_src(path, url)
        print(f"  [direct_url] {kind}: {os.path.basename(path)} <- {url[:110]}",
              flush=True)
        return path
    return ""


def main():
    if len(sys.argv) < 4:
        print("usage: fetch_assets_news.py <scenes.json> <output-images-dir> <.env>")
        sys.exit(1)
    scenes_path, images_dir, env_path = sys.argv[1:4]
    os.makedirs(images_dir, exist_ok=True)
    env = load_env(env_path)
    media_library_dir = env.get("MEDIA_LIBRARY_DIR", os.path.expanduser("~/projects/media-library"))
    # ПУТЬ МЕДИАТЕКИ НОРМАЛИЗУЕМ (2026-10-18). Все живые .env держат абсолютный
    # путь, но форма «MEDIA_LIBRARY_DIR=media-library-2» описана в заметках как
    # рабочая — а она бы ломала и пин (os.path.join с cwd = папка ролика), и
    # сверку пина ниже. Та же логика, что в check_pins.py, чтобы не разъехались.
    media_library_dir = os.path.expanduser(media_library_dir)
    if not os.path.isabs(media_library_dir):
        media_library_dir = os.path.expanduser(os.path.join("~/projects", media_library_dir))
    local_usage = {}

    this_project = os.path.basename(os.path.dirname(os.path.abspath(images_dir)))
    blocked_md5, usage_log = load_blocked_md5(this_project)
    _WEB_USED_MD5.update(blocked_md5)
    for _b in blocked_md5:
        _WEB_USED_WHERE.setdefault(_b, "в бане или кулдауне прошлых роликов")
    # also block any image already sitting in images_dir (a kept/cached scene) so
    # web_search on a re-fetch can't pick the same photo for a different scene
    for _p in glob.glob(os.path.join(images_dir, 'scene_*.*')):
        if os.path.splitext(_p)[1].lower() in ('.jpg', '.jpeg', '.png', '.webp'):
            try:
                _h = file_md5(_p)
                _WEB_USED_MD5.add(_h)
                _m = re.search(r"scene_(\d+)", os.path.basename(_p))
                _WEB_USED_WHERE[_h] = ("сценой %d этой сборки" % int(_m.group(1))
                                       if _m else "в этой сборке")
            except OSError: pass
    used_md5 = {}   # out_path -> md5, for this build
    print(f"project={this_project}  library shots on cooldown from last "
          f"{COOLDOWN_VIDEOS} videos: {len(blocked_md5)}")

    with open(scenes_path, encoding="utf-8") as f:
        data = json.load(f)

    # parallel workers (fetch_parallel.py) each write their own manifest shard
    # so they don't clobber one another; the wrapper merges them afterwards.
    manifest_name = os.environ.get("MANIFEST_NAME", "manifest.json")
    manifest_path = os.path.join(images_dir, manifest_name)

    # МАНИФЕСТ ДОПИСЫВАЕТСЯ, А НЕ ЗАТИРАЕТСЯ (2026-10-18, улов usuario-70).
    # Было: фетч по ПОДМНОЖЕСТВУ сцен (любой рефетч, дофетч трёх кадров)
    # переписывал `images/manifest.json` целиком и оставлял в нём только эти
    # id — после дофетча трёх сцен манифест стал из 3 записей вместо 75.
    # Ошибки при этом НЕТ, а `contact_sheet.py` читает именно его и молча
    # собирает почти пустой лист; вкладки пересобирали манифест руками по
    # четыре раза за ролик. Теперь прежние записи сохраняются, если их файл
    # ещё лежит на диске и сцены нет в текущем прогоне.
    # ВНИМАНИЕ: в main() переменной `scenes` НЕТ, сцены лежат в data["scenes"].
    # Утренняя версия этой правки обращалась к `scenes` и роняла ЛЮБОЙ фетч
    # NameError'ом (18.10, поймала рабочая вкладка). Коварство в том, что
    # fetch_parallel печатал «готово: 0/45 FAILED=[]» — пустой список FAILED
    # выглядит как успех, а падение видно только в .shardN.log.
    _scenes = data["scenes"] if isinstance(data, dict) else data
    _cur_ids = {s["id"] for s in _scenes}
    manifest = []
    try:
        with open(manifest_path, encoding="utf-8") as _mf:
            _old = json.load(_mf)
        if isinstance(_old, list):
            for _e in _old:
                if not isinstance(_e, dict) or _e.get("id") in _cur_ids:
                    continue
                _f = _e.get("file")
                if _f and os.path.exists(os.path.join(images_dir, _f)):
                    manifest.append(_e)
            if manifest:
                print(f"манифест: сохранил {len(manifest)} прежних записей "
                      f"(фетч идёт по {len(_cur_ids)} сценам)", flush=True)
    except (OSError, ValueError):
        pass
    # МЯГКИЙ ДЕДЛАЙН ШАРДА (2026-10-22, улов `usuario-ec` + разбор диспетчера).
    # Облачный джоб фетча режется `timeout-minutes`, и при этом ТЕРЯЕТСЯ ВЕСЬ
    # манифест шарда: сцены приезжают заглушками, а в отчёте их нет вовсе —
    # отличить «фетч не добыл» от «шард не успел» было нечем. Замер живьём
    # (olga-pub, прогон 39769452005): 6 шардов из 20 убиты ровно на 918 с =
    # 15 минут таймаута, самый долгий успешный — 652 с. Теперь шард сам
    # останавливается чуть раньше таймаута, ЗАПИСЫВАЕТ манифест и помечает
    # недоделанные сцены честной причиной. Ноль = без дедлайна (локальный фетч).
    _deadline = 0.0
    try:
        _dl = float(os.environ.get("FETCH_DEADLINE_SEC", "0") or 0)
        if _dl > 0:
            _deadline = time.time() + _dl
            globals()["_DEADLINE_AT"] = _deadline   # водопад смотрит сюда же
            print(f"дедлайн шарда: {_dl:.0f} с — что не успеем, попадёт в "
                  f"манифест как 'не успели до дедлайна'", flush=True)
    except ValueError:
        pass
    _skipped_by_deadline = []
    for scene in data["scenes"]:
        if _deadline and time.time() > _deadline:
            _skipped_by_deadline.append(scene["id"])
            continue
        sid = scene["id"]
        source = scene["source"]  # "local_library" | "wikimedia" | "press_photo" | "pexels_photo" | "pexels_video" | "direct_url"
        query = scene["source_query"]
        ext = "mp4" if source == "pexels_video" else "jpg"
        out_path = os.path.join(images_dir, f"scene_{sid:03d}.{ext}")

        # cache check by glob, not a fixed extension - local_library can land
        # a .jpg/.png/.mp4/.mov depending on what was in the folder
        # EXCLUDE .text.png / .json / lock files (user, 2026-10-08, furious —
        # review.py's live dashboard writes overlays/scene_NNN.text.png as its
        # OWN preview-thumbnail render cache for a text pop-up; when an overlay
        # photo fetch targeted the SAME overlays/ dir for the SAME scene id,
        # this glob matched that stray .text.png and treated the scene as
        # "already cached", silently skipping the real photo download and
        # reporting a false "ok" — scenes 1/2/4/5 on a "5 МИНУТ" build ended up
        # with NO overlay photo at all despite a clean-looking fetch log).
        # Mirrors the same exclusion selfcheck.py's dedup pass already uses.
        existing = [p for p in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*"))
                    if os.path.getsize(p) > 0 and not p.endswith((".json", ".text.png", ".lock"))]
        # ЗАБАНЕННЫЙ КАДР НЕ СЧИТАЕТСЯ КЭШЕМ (2026-10-15). Бан проверялся только
        # при СКАЧИВАНИИ (_accept/_accept_video), а уже лежащий файл принимался
        # как «cached» без единой проверки. Поэтому забаненный клип возвращался
        # из ролика в ролик: в слоте очереди оставался файл от прошлой сборки,
        # фетч видел его и ничего не качал — бан-лист при этом был доставлен и
        # исправен, просто его никто не спрашивал. Поймано живьём на
        # planeta-territorii-1610, пользователь: «Я его баню, баню, а оно опять».
        if existing:
            _ban = load_banned_md5()
            _kept = []
            for _p in existing:
                try:
                    if file_md5(_p) in _ban:
                        os.remove(_p)
                        print(f"[{sid:03d}] кэш забанен — удалил {os.path.basename(_p)}, качаю заново", flush=True)
                        continue
                except OSError:
                    pass
                _kept.append(_p)
            existing = _kept
        if existing:
            # МАНИФЕСТ НЕ ДОЛЖЕН ВРАТЬ ПРО ИСТОЧНИК (2026-10-18, улов usuario-b7).
            # Было: «cached» писал ЗАЯВЛЕННЫЙ в сцене `source`. На провалившемся
            # пине («ПОЛИТИКА/КАРТЫ/РОССИЯ/<опечатка>.jpg») фетч честно уходит в
            # веб-водопад и кладёт веб-картинку, но СЛЕДУЮЩИЙ инкрементальный
            # проход видел готовый файл и переписывал запись как
            # `source: local_library / status: cached` — манифест утверждал, что
            # пин сработал. А переносить кадры из облачного забора в проект
            # предписано ровно по манифесту, то есть ложь ехала дальше.
            # Теперь настоящий источник пишется в `.sources.json` при каждом
            # удачном скачивании и оттуда же читается на кэш-проходе.
            _true = _load_true_sources(images_dir).get(str(sid))
            if not _true and source == "local_library":
                _pin = os.path.join(media_library_dir, (query or "").strip())
                _folder = os.path.join(media_library_dir,
                                       (query or "").strip().split(":", 1)[0])
                if not os.path.isfile(_pin) and not os.path.isdir(_folder):
                    _true = "НЕ library (пин не существует)"
                    print(f"[{sid:03d}] ВНИМАНИЕ: пин '{query}' не существует — "
                          f"кадр в сцене НЕ из медиатеки, манифест помечен честно",
                          flush=True)
            manifest.append({"id": sid, "file": os.path.basename(existing[0]),
                             "source": _true or source, "status": "cached"})
            _mt = manifest_path + ".tmp"
            with open(_mt, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            os.replace(_mt, manifest_path)
            continue

        ok = False
        used_source = source
        fail_why = ""        # причина отказа едет в манифест (2026-10-22)
        try:
            if source == "local_library":
                local_out = fetch_local_library(
                    query, media_library_dir,
                    os.path.join(images_dir, f"scene_{sid:03d}"), local_usage,
                    blocked_md5=blocked_md5, used_md5=used_md5,
                    dur_hint=scene.get("duration_sec"), seq=sid,
                )
                if local_out == "EXHAUSTED":
                    fail_why = ("папка медиатеки исчерпана: все файлы в "
                                "кулдауне или уже в этом ролике")
                    print(f"[{sid:03d}] FAILED: папка '{query}' исчерпана — все файлы "
                          f"использованы в последних {COOLDOWN_VIDEOS} видео или уже в этом. "
                          f"Добери материал в папку или перепиши сцену.")
                    ok = False
                elif local_out:
                    ok, out_path = True, local_out
                else:
                    # tag folder missing/empty - fall through to the press
                    # waterfall (never generate), per SKILL.md
                    ok, used_source = _press_waterfall(query, out_path, env)
            elif source == "direct_url":
                # ГОТОВЫЙ АДРЕС (вложение телеграм-поста из досье георадара,
                # файл на сайте источника). Промах НЕ уводится в водопад:
                # адрес выбран руками по досье, и подмена случайным веб-фото
                # скрыла бы, что именно не доехало.
                # ВСПЛЫВАШКА ли это: в облаке сцена помечена `_dest`, локально
                # всплывашки фетчатся в свой каталог `overlays/`.
                _is_ov = (scene.get("_dest") == "overlays"
                          or os.path.basename(os.path.normpath(images_dir)) == "overlays")
                direct_out = fetch_direct_url(
                    query, os.path.join(images_dir, f"scene_{sid:03d}"),
                    for_overlay=_is_ov)
                if direct_out:
                    ok, out_path = True, direct_out
                else:
                    fail_why = ("ни один адрес из source_query не дал годного "
                                "кадра (сита: размер, клейма, тяжёлый текст)")
                    print(f"[{sid:03d}] FAILED: ни один адрес из source_query не "
                          f"дал годного кадра — перепиши сцену или дай другую ссылку")
                    ok = False
            elif source in ("wikimedia", "press_photo"):
                ok, used_source = _press_waterfall(query, out_path, env)
            elif source in ("pexels_photo", "pexels_video"):
                blob = (query + " " + scene.get("visual_prompt", "")).lower()
                hit = next((w for w in PEXELS_BLOCK if w in blob), None)
                if hit:
                    fail_why = f"pexels запрещён для политики (слово '{hit}')"
                    print(f"[{sid:03d}] FAILED: pexels запрещён для политики "
                          f"(слово '{hit}' в запросе). Переклассифицируй сцену в "
                          f"local_library или press_photo — сток со случайными "
                          f"людьми на политической сцене недопустим.")
                    ok = False
                elif source == "pexels_photo":
                    ok = fetch_stock_photo(query, env, out_path)
                else:
                    ok = fetch_stock_video(query, env, out_path)
            elif source.startswith("card"):
                # ШТАТНАЯ ДВЕРЬ ДЛЯ АРСЕНАЛА ВТОРОГО СБОРЩИКА (2026-10-22).
                # Источник вида «card:<вид>» означает: кадр рисуется У НАС
                # (template/quote_card.py и будущие соседи), в сеть за ним
                # ходить не надо и нечего. Файла нет — значит карточку просто
                # ещё не отрисовали; это не ошибка классификации, и сцену не
                # надо переклассифицировать в press_photo.
                print(f"[{sid:03d}] {source}: кадр рисуется локально, фетч пропущен"
                      + ("" if os.path.exists(out_path) else
                         " — ФАЙЛА НЕТ, карточка ещё не нарисована"))
                ok = os.path.exists(out_path)
            else:
                print(f"[{sid:03d}] ERROR: unknown source '{source}' - news-video never generates, "
                      f"fix the scene's source classification instead")
        except Exception as e:
            fail_why = "ошибка фетча: %s" % e
            print(f"[{sid:03d}] ERROR: {e}")
            ok = False

        print(f"[{sid:03d}] {used_source} -> {'ok' if ok else 'FAILED'}")
        _src = LAST_SRC_URL.get(os.path.abspath(out_path), "")
        if not _src and used_source == "local_library":
            _src = str(locals().get("local_out") or "")
        # ПРИЧИНА ОТКАЗА ТЕПЕРЬ ХРАНИТСЯ (2026-10-22, улов `usuario-5a`): поля
        # `reason` в схеме записи не существовало вовсе, поэтому FAILED молчал
        # ПО УСТРОЙСТВУ, а не из-за потерянного лога — вкладка не могла
        # отличить «фетч ходил и не добыл» от «сцену никто не фетчил, упал
        # шард», хотя лечатся они по-разному (запрос против добора).
        _rec = {"id": sid, "file": os.path.basename(out_path) if ok else None,
                "source": used_source, "status": "ok" if ok else "FAILED",
                "url": _src}
        if not ok:
            _rec["reason"] = fail_why or ("водопад press/web не дал годного "
                                          "кадра (сита: клейма, тяжёлый текст, "
                                          "размер, собственный дубль)")
        manifest.append(_rec)
        if ok:
            _save_true_source(images_dir, sid, used_source)
        # write manifest after EVERY scene so `review.py --live` can show
        # thumbnails as they arrive, not only once the whole fetch is done
        _mtmp = manifest_path + ".tmp"
        with open(_mtmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        os.replace(_mtmp, manifest_path)
        time.sleep(0.3)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # rule 4: record which library shots this video used, so the next builds
    # skip them for COOLDOWN_VIDEOS videos.
    used_relpaths = {md5: _LIB_RELPATH.get(md5, "?") for md5 in set(used_md5.values())}
    if used_relpaths:
        record_usage(usage_log, this_project, used_relpaths)
        print(f"usage log: recorded {len(used_relpaths)} library shots for '{this_project}'")

    if _skipped_by_deadline:
        _known = {m.get("id") for m in manifest}
        for _sid in _skipped_by_deadline:
            if _sid not in _known:
                manifest.append({"id": _sid, "file": None, "source": "?",
                                 "status": "FAILED", "url": "",
                                 "reason": "не успели до дедлайна шарда — "
                                           "запрос, скорее всего, в порядке, "
                                           "нужен добор этой сцены"})
        print("ДЕДЛАЙН ШАРДА: не дошли до %d сцен — %s. Запросы тут ни при чём, "
              "нужен добор." % (len(_skipped_by_deadline),
                                ", ".join(str(x) for x in _skipped_by_deadline)),
              flush=True)
        _mt = manifest_path + ".tmp"
        with open(_mt, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        os.replace(_mt, manifest_path)
    failed = [m for m in manifest if m["status"] == "FAILED"]
    print(f"\nDone. {len(manifest)-len(failed)}/{len(manifest)} ok.")
    if failed:
        print("Failed ids (no free source had anything - consider a more generic query, or a local photo you supply by hand):", [m["id"] for m in failed])


if __name__ == "__main__":
    main()
