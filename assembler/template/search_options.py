#!/usr/bin/env python3
"""Return a list of candidate images/clips for a query — for the review dashboard's
"pick one" picker. Does NOT download the full asset; just gathers thumbnail +
full-res URLs from the free sources so the user can choose.

Usage:  python3 search_options.py "<query>" <.env>   ->  JSON on stdout
        {"opts": [{"thumb": url, "full": url, "kind": "photo"|"video",
                   "w": int, "h": int, "src": "pexels"|"openverse"|"wikimedia"}]}
"""
import json
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) news-video-review"


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_env(path):
    env = {}
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except OSError:
        pass
    return env


def pexels_photos(q, key, n=12):
    out = []
    try:
        url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
            {"query": q, "per_page": n, "orientation": "landscape"})
        d = json.loads(_get(url, {"Authorization": key}))
        for p in d.get("photos", []):
            out.append({"thumb": p["src"]["medium"], "full": p["src"]["large2x"],
                        "kind": "photo", "w": p.get("width", 0), "h": p.get("height", 0),
                        "src": "pexels"})
    except Exception:
        pass
    return out


def pexels_videos(q, key, n=6):
    out = []
    try:
        url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
            {"query": q, "per_page": n, "orientation": "landscape", "size": "medium"})
        d = json.loads(_get(url, {"Authorization": key}))
        for v in d.get("videos", []):
            hd = [f for f in v.get("video_files", [])
                  if f.get("quality") == "hd" and f.get("width", 9999) <= 1920]
            hd.sort(key=lambda f: abs(f.get("width", 0) - 1280))
            if not hd:
                continue
            out.append({"thumb": v.get("image", ""), "full": hd[0]["link"],
                        "kind": "video", "w": hd[0].get("width", 0),
                        "h": hd[0].get("height", 0), "src": "pexels"})
    except Exception:
        pass
    return out


def openverse(q, n=12):
    out = []
    try:
        url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
            {"q": q, "page_size": n, "license_type": "all",
             "mature": "false"})
        d = json.loads(_get(url))
        for r in d.get("results", []):
            full = r.get("url") or r.get("thumbnail")
            th = r.get("thumbnail") or full
            if not full:
                continue
            out.append({"thumb": th, "full": full, "kind": "photo",
                        "w": r.get("width", 0), "h": r.get("height", 0),
                        "src": r.get("source", "openverse")})
    except Exception:
        pass
    return out


def wikimedia(q, n=6):
    out = []
    try:
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "search",
            "gsrnamespace": "6", "gsrsearch": q, "gsrlimit": n,
            "prop": "imageinfo", "iiprop": "url|size", "iiurlwidth": "1600"})
        d = json.loads(_get(url))
        for p in (d.get("query", {}).get("pages", {}) or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            u = ii.get("url")
            if not u:
                continue
            low = u.lower()
            # SVG/PDF/TIFF/DjVu can't be used as-is -> serve Wikimedia's rendered PNG
            if low.endswith((".svg", ".pdf", ".tif", ".tiff", ".djvu")):
                png = ii.get("thumburl")
                if not png:
                    continue
                full = png
            else:
                full = u
            out.append({"thumb": ii.get("thumburl", full), "full": full,
                        "kind": "photo", "w": ii.get("width", 0),
                        "h": ii.get("height", 0), "src": "wikimedia"})
    except Exception:
        pass
    return out


import re as _re


def translate_to_en(text):
    """RU (or anything) -> EN via Google's free gtx endpoint. Returns the input
    unchanged on failure or if it's already plain ASCII."""
    if not _re.search(r"[^\x00-\x7f]", text):
        return text
    try:
        url = ("https://translate.googleapis.com/translate_a/single?client=gtx"
               "&sl=auto&tl=en&dt=t&q=" + urllib.parse.quote(text))
        d = json.loads(_get(url, timeout=12))
        return "".join(seg[0] for seg in d[0] if seg and seg[0]).strip() or text
    except Exception:
        try:  # fallback: MyMemory
            url = ("https://api.mymemory.translated.net/get?langpair=ru|en&q="
                   + urllib.parse.quote(text))
            d = json.loads(_get(url, timeout=12))
            return (d.get("responseData", {}).get("translatedText") or text).strip()
        except Exception:
            return text


def ddg_images(q, n=14):
    """DuckDuckGo image search (aggregates Bing). No key. Two-step: grab the
    vqd token from the search page, then hit the i.js JSON endpoint."""
    out = []
    try:
        hdr = {"Referer": "https://duckduckgo.com/",
               "Accept": "application/json, text/javascript, */*; q=0.01"}
        page = _get("https://duckduckgo.com/?q=" + urllib.parse.quote(q) + "&iax=images&ia=images").decode("utf-8", "ignore")
        m = _re.search(r'vqd=["\']?([\d-]+)', page) or _re.search(r'vqd=([\d-]+)&', page)
        if not m:
            return out
        vqd = m.group(1)
        url = ("https://duckduckgo.com/i.js?l=us-en&o=json&q=" + urllib.parse.quote(q)
               + "&vqd=" + vqd + "&f=,,,,,&p=1")
        d = json.loads(_get(url, hdr))
        for r in d.get("results", []):
            if not r.get("image"):
                continue
            out.append({"thumb": r.get("thumbnail") or r["image"], "full": r["image"],
                        "kind": "photo", "w": r.get("width", 0), "h": r.get("height", 0),
                        "src": "web·" + (r.get("source") or "ddg")})
            if len(out) >= n:
                break
    except Exception:
        pass
    return out


def yandex_images(q, n=12):
    """Scrape Yandex Images results HTML. May hit a captcha from some IPs — then
    returns nothing and the other sources cover it."""
    out = []
    try:
        url = "https://yandex.com/images/search?text=" + urllib.parse.quote(q) + "&isize=large"
        html = _get(url, {"Accept-Language": "en,ru;q=0.9"}).decode("utf-8", "ignore")
        import html as _h
        # result tiles serialize their JSON with &quot; entities inside data-bem
        for m in _re.finditer(r'img_href&quot;:&quot;(https?://[^&]+)&quot;', html):
            full = _h.unescape(m.group(1))
            if full.startswith("http"):
                out.append({"thumb": full, "full": full, "kind": "photo",
                            "w": 0, "h": 0, "src": "yandex"})
            if len(out) >= n:
                break
        if not out:
            for m in _re.finditer(r'"img_href":"(https?:\\?/\\?/[^"]+?)"', html):
                full = m.group(1).replace("\\/", "/")
                out.append({"thumb": full, "full": full, "kind": "photo",
                            "w": 0, "h": 0, "src": "yandex"})
                if len(out) >= n:
                    break
    except Exception:
        pass
    return out


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"opts": []}))
        return
    q = sys.argv[1].strip()
    env = load_env(sys.argv[2])
    key = env.get("PEXELS_API_KEY", "")
    is_ru = bool(_re.search(r"[а-яА-ЯёЁ]", q))
    # n=30, not yandex_images' own default n=12 — with the default cap, "thin
    # Yandex coverage" was unreachable (12 < any sane threshold), so the
    # English fallback below fired on every single Russian query regardless
    # of how well Yandex actually covered it.
    y = yandex_images(q, n=30)                  # Yandex handles Russian natively
    opts = list(y)
    q_en = q
    # Rule g (SKILL.md): for a Russian/CIS-named subject, Russian search comes
    # first and English banks are a top-up, not a default — translating
    # "Калининград" to "Kaliningrad" and mixing in generic English-web/stock
    # hits is exactly the wrong-content risk rule g warns about (user,
    # 2026-10-02, annoyed: "искал по-английски: Kaliningrad — зачем?").
    # So: English-indexed banks only run when Yandex alone came up thin.
    if not (is_ru and len(y) >= 15):
        q_en = translate_to_en(q)                  # english for the english-indexed banks
        opts += wikimedia(q_en)                     # real people / places / maps first
        opts += ddg_images(q_en)                    # broad web (Bing-backed)
        if key:
            opts += pexels_photos(q_en, key)
            opts += pexels_videos(q_en, key)
        opts += openverse(q_en)
    # de-dupe by full url, keep order, cap; drop non-raster (SVG/PDF/TIFF) —
    # they save as a broken .jpg and never render a thumbnail
    _BAD = (".svg", ".pdf", ".tif", ".tiff", ".djvu")
    seen, uniq = set(), []
    for o in opts:
        f = o.get("full", "")
        if not f or f in seen:
            continue
        if f.split("?")[0].lower().endswith(_BAD):
            continue
        seen.add(f)
        uniq.append(o)
    out = {"opts": uniq[:40]}
    if q_en.lower() != q.lower():
        out["q_en"] = q_en
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
