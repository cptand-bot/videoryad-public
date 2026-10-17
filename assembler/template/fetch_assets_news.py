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
import shutil
import sys
import time
import hashlib
import subprocess
import urllib.request
import urllib.parse
from collections import Counter

# md5 -> how many scenes in THIS build already use that exact file. A
# deliberate leitmotif may repeat up to twice (rule 5 / SKILL "establishing
# leitmotif"); the 3rd request for the same file is rerouted to a fresh one.
_USE_COUNT = Counter()
_WEB_USED_MD5 = set()   # md5 of every image web_search accepted this run (+ cross-video cooldown)
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
    for box in regions:
        try:
            crop = im.crop(box)
            crop = crop.resize((crop.width * 3, crop.height * 3))
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
    # агентства, у которых знак вшит В КАДР (не в угол) и OCR его не берёт:
    # поймано глазами 2026-10-17 на planeta-svergnut-1810
    "interfax.com.ua",
    # знак через весь кадр, OCR не берёт (2026-10-17, тот же ролик):
    # каталог напольных покрытий приехал на «служебный коридор», сток-клипарт —
    # на «здание Казначейства США»
    "nash-parus.com.ua", "pngtree",
)


def _is_stock_domain(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(d in host for d in _STOCK_DOMAINS)


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
    _BAD = (".svg", ".pdf", ".tif", ".tiff", ".djvu")
    seen = set()
    for c in cands:
        u = c.get("full") or c.get("thumb") or ""
        if not u or u in seen: continue
        seen.add(u)
        if u.split("?")[0].lower().endswith(_BAD): continue
        if _is_stock_domain(u): continue   # reject by domain, before ever downloading
        if _download_as_jpeg(u, out_path):
            try:
                h = file_md5(out_path)
            except OSError:
                h = None
            if h and h in _WEB_USED_MD5:
                try: os.remove(out_path)
                except OSError: pass
                continue            # same image already used elsewhere this build — keep looking
            if h:
                _WEB_USED_MD5.add(h)
            return True
    return False


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
        try:
            if _accept(fn(), out_path):
                return True, name
        except Exception:
            continue
    return False, "press_photo"


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
            out_path = out_base + os.path.splitext(direct)[1].lower()
            shutil.copyfile(direct, out_path)
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
            seg_len = max(0.5, seg["end"] - seg["start"])
            want = min(dur_hint or seg_len, seg_len)
            off = min(max(0.0, seg_len - want), (use_n - 1) * 2.0)
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
    out_path = out_base + os.path.splitext(src_path)[1].lower()
    shutil.copyfile(src_path, out_path)
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


def http_get(url, headers=None, timeout=18):
    h = {"User-Agent": DEFAULT_UA}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


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
        if env.get("PEXELS_API_KEY") and _accept(fetch_pexels_photo(query, env["PEXELS_API_KEY"], out_path), out_path):
            return True
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
    try:
        if env.get("PEXELS_API_KEY") and _accept_video(fetch_pexels_video(query, env["PEXELS_API_KEY"], out_path), out_path):
            return True
    except Exception as e:
        print(f"  [pexels_video error, trying pixabay] {e}")
    if env.get("PIXABAY_API_KEY"):
        try:
            return _accept_video(fetch_pixabay_video(query, env["PIXABAY_API_KEY"], out_path), out_path)
        except Exception as e:
            print(f"  [pixabay_video error] {e}")
    return False


def main():
    if len(sys.argv) < 4:
        print("usage: fetch_assets_news.py <scenes.json> <output-images-dir> <.env>")
        sys.exit(1)
    scenes_path, images_dir, env_path = sys.argv[1:4]
    os.makedirs(images_dir, exist_ok=True)
    env = load_env(env_path)
    media_library_dir = env.get("MEDIA_LIBRARY_DIR", os.path.expanduser("~/projects/media-library"))
    local_usage = {}

    this_project = os.path.basename(os.path.dirname(os.path.abspath(images_dir)))
    blocked_md5, usage_log = load_blocked_md5(this_project)
    _WEB_USED_MD5.update(blocked_md5)
    # also block any image already sitting in images_dir (a kept/cached scene) so
    # web_search on a re-fetch can't pick the same photo for a different scene
    for _p in glob.glob(os.path.join(images_dir, 'scene_*.*')):
        if os.path.splitext(_p)[1].lower() in ('.jpg', '.jpeg', '.png', '.webp'):
            try: _WEB_USED_MD5.add(file_md5(_p))
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

    manifest = []
    for scene in data["scenes"]:
        sid = scene["id"]
        source = scene["source"]  # "local_library" | "wikimedia" | "press_photo" | "pexels_photo" | "pexels_video"
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
            manifest.append({"id": sid, "file": os.path.basename(existing[0]), "source": source, "status": "cached"})
            _mt = manifest_path + ".tmp"
            with open(_mt, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            os.replace(_mt, manifest_path)
            continue

        ok = False
        used_source = source
        try:
            if source == "local_library":
                local_out = fetch_local_library(
                    query, media_library_dir,
                    os.path.join(images_dir, f"scene_{sid:03d}"), local_usage,
                    blocked_md5=blocked_md5, used_md5=used_md5,
                    dur_hint=scene.get("duration_sec"), seq=sid,
                )
                if local_out == "EXHAUSTED":
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
            elif source in ("wikimedia", "press_photo"):
                ok, used_source = _press_waterfall(query, out_path, env)
            elif source in ("pexels_photo", "pexels_video"):
                blob = (query + " " + scene.get("visual_prompt", "")).lower()
                hit = next((w for w in PEXELS_BLOCK if w in blob), None)
                if hit:
                    print(f"[{sid:03d}] FAILED: pexels запрещён для политики "
                          f"(слово '{hit}' в запросе). Переклассифицируй сцену в "
                          f"local_library или press_photo — сток со случайными "
                          f"людьми на политической сцене недопустим.")
                    ok = False
                elif source == "pexels_photo":
                    ok = fetch_stock_photo(query, env, out_path)
                else:
                    ok = fetch_stock_video(query, env, out_path)
            else:
                print(f"[{sid:03d}] ERROR: unknown source '{source}' - news-video never generates, "
                      f"fix the scene's source classification instead")
        except Exception as e:
            print(f"[{sid:03d}] ERROR: {e}")
            ok = False

        print(f"[{sid:03d}] {used_source} -> {'ok' if ok else 'FAILED'}")
        manifest.append({"id": sid, "file": os.path.basename(out_path) if ok else None, "source": used_source, "status": "ok" if ok else "FAILED"})
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

    failed = [m for m in manifest if m["status"] == "FAILED"]
    print(f"\nDone. {len(manifest)-len(failed)}/{len(manifest)} ok.")
    if failed:
        print("Failed ids (no free source had anything - consider a more generic query, or a local photo you supply by hand):", [m["id"] for m in failed])


if __name__ == "__main__":
    main()
