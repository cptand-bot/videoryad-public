#!/usr/bin/env python3
"""Pre-build review page for the video montage.

Two modes:

  python3 review.py [scenes.json] [images_dir] [out.html]
      Snapshot: one self-contained review.html (thumbnails embedded as
      data URIs). Hand it to the user as a file. Re-run after any swap.

  python3 review.py --live [scenes.json] [images_dir] [port]
      Live: renders every scene card immediately (text + timing + the
      *planned* source badge) and starts a small web server. Thumbnails
      and real source badges fill in as `fetch_assets_news.py` downloads
      each asset — the user reviews and marks scenes while the fetch is
      still running, no page reload. Serves the project dir; the user
      opens http://localhost:<port>/review.html . Ctrl-C / kill to stop.

Source badge on each thumbnail (top-right), colour-coded:
  📁 БИБЛИОТЕКА · ФОТО   синий    (local_library still)
  📁 БИБЛИОТЕКА · ВИДЕО  розовый  (local_library clip)
  🌐 ПРЕСС-ФОТО          зелёный  (press_photo / wikimedia — real photo off the web)
  🎞 СТОК · ФОТО/ВИДЕО   оранжевый(pexels_*)
  🎨 ГЕНЕРАЦИЯ           жёлтый   (generate — script-to-video only)
"""
import base64
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

from PIL import Image

# Sibling pipeline scripts (search_options.py, build_overlays.py, ...) are
# invoked by absolute path relative to THIS file, never bare/relative to the
# server's cwd. A project dir pulled from the cloud (~/projects/<name>-cloud/)
# holds only data, not scripts — a bare "search_options.py" subprocess call
# there fails silently (caught by a broad except, returns empty results) and
# looks to the user like "search stopped working" (2026-09-22). Resolving
# against __file__ means the search/build routes work from ANY project
# directory, cloud-pulled or local, with zero setup.
HERE = os.path.dirname(os.path.abspath(__file__))

def _script(name):
    return os.path.join(HERE, name)

TW, TH = 480, 270

# Scenes Claude could not source from free material and needs the user to
# upload a photo for. Written by Claude as needs_upload.json in the project
# dir: {"22": "современное фото Белого дома", ...}. The live server drops an
# id from this file the moment a photo is uploaded for that scene.
NEEDS_FILE = "needs_upload.json"


def load_needs():
    try:
        with open(NEEDS_FILE, encoding="utf-8") as f:
            return {str(k): v for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def drop_need(sid):
    n = load_needs()
    if n.pop(str(sid), None) is not None:
        try:
            with open(NEEDS_FILE, "w", encoding="utf-8") as f:
                json.dump(n, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


def save_need(sid, reason):
    n = load_needs()
    n[str(sid)] = reason
    try:
        with open(NEEDS_FILE, "w", encoding="utf-8") as f:
            json.dump(n, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# --- corner-pop-up overlays (build_overlays.py reads this) ---------------
# overlays.json in the project dir:
#   {"12": {"photo": "overlays/scene_012.jpg", "sound": "whoosh", "at": 3.0}}
# Only VIDEO scenes get a pop-up (photo-on-photo looks flat). The dashboard
# shows the "＋ всплывашка" control only on cards whose resolved asset is
# video; the panel writes here, the build runs build_overlays.py.
OVERLAY_FILE = "overlays.json"
SFX_DIR = "sfx"
SFX_LABELS = {"whoosh": "вжух", "zatvor": "затвор камеры", "pop": "поп"}


def load_overlays():
    try:
        with open(OVERLAY_FILE, encoding="utf-8") as f:
            return {str(k): v for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


_OVERLAY_LOCK = OVERLAY_FILE + ".lock"


def _atomic_write_json(path, data):
    # Пишем во временный файл + os.replace — иначе два одновременных запроса
    # (два процесса review.py на одном порту после неудачного kill, или два
    # потока одного процесса) могут перемежать свои write() и убить JSON
    # целиком (user, 2026-09-15, дважды на разных проектах: "всплывашка не
    # показывается... не ложится на картинку" — load_overlays() тихо
    # проглатывал ValueError и отдавал {} как будто всплывашек вообще нет).
    # flock — простая защита от гонки на файле ЦЕЛИКОМ.
    lock_path = path + ".lock"
    with open(lock_path, "w") as lock_f:
        try:
            import fcntl
            fcntl.flock(lock_f, fcntl.LOCK_EX)
        except ImportError:
            pass
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


import contextlib  # noqa: E402


@contextlib.contextmanager
def _overlays_txn():
    # Read-modify-write of overlays.json used to happen as two separate
    # calls (load_overlays() ... later ... _atomic_write_json(...)) with NO
    # lock held across the gap — only the final write was locked. Two
    # ThreadingTCPServer request threads editing DIFFERENT scene ids at
    # nearly the same moment would each read the same pre-edit snapshot,
    # then whichever wrote last silently discarded the other's change
    # (classic lost-update race). This is what caused entries to come back
    # missing fields, or entirely reduced to just `{"approved": true}`
    # (2026-09-22, "мерцу хана" build — id 8's photo/sound/at/shape/style/
    # scale all vanished, only the field the LATEST write happened to touch
    # survived). Fix: hold ONE flock across the whole read-modify-write, so
    # a second thread's transaction can't start reading until the first's
    # write has landed. Every route that touches OVERLAY_FILE must go
    # through this contextmanager — never call load_overlays() +
    # _atomic_write_json() as two separate steps again.
    lock_path = OVERLAY_FILE + ".lock"
    lock_f = open(lock_path, "w")
    try:
        try:
            import fcntl
            fcntl.flock(lock_f, fcntl.LOCK_EX)
        except ImportError:
            pass
        ov = load_overlays()
        # Бэкап ПЕРЕД записью (2026-10-11). Инцидент того дня: сессия приняла
        # живые клики пользователя за порчу файла, перезаписала overlays.json
        # целиком и затёрла 16 утверждений плюс воскресила 11 снятых
        # всплывашек; спасла только копия, сделанная случайно. История у
        # файла отсутствует, восстанавливать нечем — поэтому держим
        # последние 20 версий рядом. Стоит доли секунды, файл крошечный.
        try:
            if os.path.exists(OVERLAY_FILE):
                import time as _t
                bdir = os.path.join(os.path.dirname(OVERLAY_FILE) or ".", ".overlays_bak")
                os.makedirs(bdir, exist_ok=True)
                shutil.copyfile(
                    OVERLAY_FILE,
                    os.path.join(bdir, "overlays.%s.json" % _t.strftime("%H%M%S", _t.localtime())),
                )
                old = sorted(glob.glob(os.path.join(bdir, "overlays.*.json")))
                for p in old[:-20]:
                    os.remove(p)
        except Exception:
            pass  # бэкап никогда не должен ломать саму запись
        yield ov
        tmp = OVERLAY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ov, f, ensure_ascii=False, indent=2)
        os.replace(tmp, OVERLAY_FILE)
    finally:
        lock_f.close()


def save_overlay(sid, patch, create=False):
    with _overlays_txn() as ov:
        is_new = str(sid) not in ov
        cur = ov.get(str(sid), {})
        if create and is_new:
            cur.setdefault("sound", "whoosh")
            cur.setdefault("at", 2.0)
            cur.setdefault("photo", "")   # created; awaiting a photo
        cur.update({k: v for k, v in patch.items() if v is not None})
        ov[str(sid)] = cur
        result = cur
    return result


def drop_overlay(sid):
    with _overlays_txn() as ov:
        entry = ov.pop(str(sid), None)
    if entry is not None:
        # also remove the photo file itself — leaving it on disk makes it look
        # like a forgotten/orphaned overlay to ship.sh's on-disk recovery scan,
        # which silently re-adds it at ship time and undoes this exact removal
        # (user, 2026-09-16, furious: caught mid-build, after the dashboard was
        # already approved and sent — that must never happen again, all fixes
        # belong BEFORE ship, never after).
        photo = entry.get("photo") if isinstance(entry, dict) else None
        if photo:
            p = os.path.join(os.path.dirname(OVERLAY_FILE), photo)
            try:
                os.remove(p)
            except OSError:
                pass


# --- running headline ticker ("бегущая строка") — FULLY SEPARATE FEATURE --
# (user, 2026-10-03: хочет верхнюю бегущую строку с заголовками на части
# сцен, но ТОЛЬКО как изолированный модуль — если эта фича сломается, она
# не должна утянуть за собой остальной дашборд/сборку, и её должно быть
# можно выключить одним движением).
# Живёт в СВОЁМ файле ticker.json, со своим lock-ом — никогда не читается и
# не пишется через load_overlays/_overlays_txn/save_overlay. Если
# ticker.json в папке проекта не существует — load_ticker() просто вернёт
# {} и ни одна карточка на дашборде не покажет ни одной панели тикера:
# фича по умолчанию выключена для КАЖДОГО проекта, пока её явно не включили
# (python3 build_ticker.py propose ...). Рендер в финальное видео —
# отдельный скрипт build_ticker.py, запускается ПОСЛЕ get.sh на готовом
# финальном файле и пишет НОВЫЙ файл, не трогая оригинал — так что "мне не
# понравилось" = просто не брать этот новый файл, оригинал всегда цел.
TICKER_FILE = "ticker.json"


def load_ticker():
    try:
        with open(TICKER_FILE, encoding="utf-8") as f:
            return {str(k): v for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def _ticker_txn():
    lock_path = TICKER_FILE + ".lock"
    lock_f = open(lock_path, "w")
    try:
        try:
            import fcntl
            fcntl.flock(lock_f, fcntl.LOCK_EX)
        except ImportError:
            pass
        tk = load_ticker()
        yield tk
        tmp = TICKER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tk, f, ensure_ascii=False, indent=2)
        os.replace(tmp, TICKER_FILE)
    finally:
        lock_f.close()


def save_ticker(sid, patch):
    with _ticker_txn() as tk:
        cur = tk.get(str(sid), {})
        cur.update({k: v for k, v in patch.items() if v is not None})
        tk[str(sid)] = cur
        result = cur
    return result


def drop_ticker(sid):
    with _ticker_txn() as tk:
        tk.pop(str(sid), None)


_POS2STYLE = {"left": "left", "right": "right", "center": "up-center"}

def _ovcell_cur(spec, anchor="bottom"):
    """Клетка схемы 3×3 для ФОТО-всплывашки: горизонталь из style,
    вертикаль из anchor записи (или общего ключа ролика).
    Кнопочная схема вместо выпадающих списков — прямая просьба пользователя
    17.10: «тык нажал — центр, тык нажал — слева… а не списки, в которых я
    должен ковыряться». Такая же сетка уже была у всплывашки-СЛОВА."""
    h = _ovpos_cur(spec)                      # left | center | right
    v = str((spec or {}).get("anchor") or anchor).lower()
    if v not in ("top", "middle", "bottom"):
        v = "bottom"
    return {"top": "t", "middle": "m", "bottom": "b"}[v] + \
           {"left": "l", "center": "c", "right": "r"}[h]


def _ovpos_cur(spec):
    st = (spec or {}).get("style", "") or ""
    if "left" in st:
        return "left"
    if "right" in st:
        return "right"
    return "center"

def overlay_geom(sid, spec, photo_path=None, anchor="bottom"):
    """Where the pop-up will sit in the 1920x1080 frame — mirrors
    build_overlays.py's seeded layout EXACTLY (draw order matters, so the RNG
    stays in step). Height-driven, 1/3..1/2 of the frame; box hugs the photo's
    aspect. Returns fractions of the frame + the entry style."""
    import random as _r
    W, H = 1920, 1080
    spec = spec or {}
    HMIN, HMAX = H // 3, H // 2
    HBY = {"s": (HMIN, HMIN + 55), "m": (HMIN + 70, HMAX - 45), "l": (HMAX - 45, HMAX)}
    PICK = ["s", "s", "m", "m", "m", "l", "l", "l"]
    STY = ["right", "right", "left", "left", "up-center", "up-right", "up-left"]
    rnd = _r.Random(sid)
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
    if ar < 1.0:                                    # вертикальное фото -> всегда в половину кадра по высоте
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
    dw, dh = bw + 18, bh + 18                       # white + dark borders
    if shape == "circle":
        dw = dh = bh                                # круг: без прямоугольных рамок
    if "left" in style:
        x = margin
    elif "right" in style:
        x = W - dw - margin
    else:
        x = (W - dw) // 2
    _a = str(anchor).lower()
    y = margin if _a == "top" else ((H - dh) // 2 if _a == "middle" else H - dh - margin)
    _v = "сверху" if _a == "top" else ("по середине" if _a == "middle" else "снизу")
    ru = {"left": f"{_v} слева", "right": f"{_v} справа", "up-center": f"{_v} по центру",
          "up-right": f"{_v} справа", "up-left": f"{_v} слева"}
    pos = "left" if "left" in style else ("right" if "right" in style else "center")
    return {"xf": round(x / W, 4), "yf": round(y / H, 4),
            "wf": round(dw / W, 4), "hf": round(dh / H, 4),
            "style": style, "style_ru": ru.get(style, style), "size": cls,
            "shape": shape, "scale": round(msc, 2), "pos": pos}


def overlay_text_geom(tspec, png_path=None):
    """Прямоугольник текст-всплывашки в кадре 1920x1080 — зеркалит
    build_overlays._apply_text_overlay (сетка 9, без seeded-раскладки)."""
    W, H = 1920, 1080
    tspec = tspec or {}
    try:
        msc = max(0.4, min(2.4, float(tspec.get("scale", 1.0))))
    except (TypeError, ValueError):
        msc = 1.0
    pos = str(tspec.get("pos", "bc")).lower()
    yk = pos[0] if pos[:1] in ("t", "m", "b") else "b"
    xk = pos[1] if len(pos) > 1 and pos[1] in "lcr" else "c"
    ar = 6.0
    if png_path and os.path.exists(png_path):
        try:
            from PIL import Image
            with Image.open(png_path) as _im:
                ar = _im.width / _im.height if _im.height else 6.0
        except Exception:
            pass
    th = max(60, min(int(H / 6 * msc), int(H * 0.5)))
    tw = min(int(th * ar), int(W * 0.92))
    mg = 60
    x = {"l": mg, "c": (W - tw) // 2, "r": W - tw - mg}[xk]
    y = {"t": mg, "m": (H - th) // 2, "b": H - th - mg}[yk]
    ru_y = {"t": "верх", "m": "центр", "b": "низ"}[yk]
    ru_x = {"l": "слева", "c": "по центру", "r": "справа"}[xk]
    return {"xf": round(x / W, 4), "yf": round(y / H, 4),
            "wf": round(tw / W, 4), "hf": round(th / H, 4),
            "pos": pos, "pos_ru": f"{ru_y} {ru_x}",
            "words": tspec.get("words") or tspec.get("text") or "",
            "color": tspec.get("color", "white")}


def sfx_list():
    out = []
    for p in sorted(glob.glob(os.path.join(SFX_DIR, "*"))):
        stem, ext = os.path.splitext(os.path.basename(p))
        if ext.lower() in (".mp3", ".wav", ".m4a", ".ogg"):
            out.append({"name": stem, "label": SFX_LABELS.get(stem, stem)})
    return out


def build_scene_preview(sid, images_dir, scenes_path):
    """Собрать РЕАЛЬНЫЙ кусок одной сцены как в финале: Ken Burns / нормализация
    видео → всплывашка (фото + текст) → звук всплывашки. Кладёт в
    <images>/.rev/preview_NNN.mp4, возвращает URL. ~10-30 с на кадр."""
    import shutil
    scenes = json.load(open(scenes_path, encoding="utf-8"))["scenes"]
    sc = next((s for s in scenes if int(s["id"]) == int(sid)), None)
    if not sc:
        return None
    rev = os.path.join(images_dir, ".rev")
    os.makedirs(rev, exist_ok=True)
    tmp = os.path.join(rev, f".pv{sid}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    sub = os.path.join(tmp, "sc.json")
    json.dump({"scenes": [sc]}, open(sub, "w", encoding="utf-8"), ensure_ascii=False)
    ff = os.environ.get("FFMPEG_BIN", "ffmpeg")

    # 1. кадр -> клип (Ken Burns для фото, нормализация для видео)
    subprocess.run(["python3", _script("build_clips_1080.py"), sub, images_dir, tmp, ff],
                   capture_output=True, text=True)
    clip = os.path.join(tmp, f"clip_{int(sid):03d}.mp4")
    if not os.path.exists(clip):
        shutil.rmtree(tmp, ignore_errors=True)
        return None

    final = clip
    ov = load_overlays()
    ent = ov.get(str(sid))
    has_txt = isinstance(ent, dict) and isinstance(ent.get("text"), dict) \
        and str(ent["text"].get("words") or ent["text"].get("text") or "").strip()
    has_photo = isinstance(ent, dict) and ent.get("photo") and os.path.exists(ent["photo"])
    if ent and (has_photo or has_txt):
        ovj = os.path.join(tmp, "ov.json")
        json.dump({"anchor": ov.get("anchor", "bottom"), str(sid): ent},
                  open(ovj, "w", encoding="utf-8"), ensure_ascii=False)
        # 2. всплывашка(и) поверх клипа  (перезаписывает clip_NNN.mp4)
        subprocess.run(["python3", _script("build_overlays.py"), "overlay", sub,
                        images_dir, tmp, ovj, ff], capture_output=True, text=True)
        # 3. звук всплывашки
        sfxout = os.path.join(tmp, "sfx.mp4")
        subprocess.run(["python3", _script("build_overlays.py"), "sfx", sub, ovj,
                        SFX_DIR, clip, sfxout, "1.0", ff],
                       capture_output=True, text=True)
        final = sfxout if os.path.exists(sfxout) else clip

    # Бегущая строка в превью — отдельный, необязательный шаг (build_ticker.py
    # bake_one), ТОЛЬКО если для этой сцены есть утверждённая запись в
    # ticker.json. Любая ошибка здесь тихо гасится — превью без строки лучше,
    # чем сломанное превью (user, 2026-10-03: "нажал на превью, но ничего не
    # применилось" — до этого строка вообще не попадала ни в один предпросмотр,
    # только в финальный пост-обработанный файл, непонятно, как она выглядит).
    try:
        tk = load_ticker().get(str(sid))
        if tk and tk.get("approved") and str(tk.get("text", "")).strip():
            tkout = os.path.join(tmp, "tk.mp4")
            rtk = subprocess.run(["python3", _script("build_ticker.py"), "one",
                                  final, tk["text"], tkout], capture_output=True, text=True)
            if rtk.returncode == 0 and os.path.exists(tkout):
                final = tkout
    except Exception:
        pass

    dst = os.path.join(rev, f"preview_{int(sid):03d}.mp4")
    try:
        shutil.copy(final, dst)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    shutil.rmtree(tmp, ignore_errors=True)
    # не копить: держим ~20 последних превью
    old = sorted(glob.glob(os.path.join(rev, "preview_*.mp4")), key=os.path.getmtime)
    for f in old[:-20]:
        try:
            os.remove(f)
        except OSError:
            pass
    return f"{images_dir}/.rev/preview_{int(sid):03d}.mp4"


# --- текстовая всплывашка: рендер слова в прозрачный PNG ----------------
_TEXT_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]
TEXT_COLORS = {"white": (255, 255, 255), "yellow": (255, 232, 0), "red": (255, 34, 28)}


def render_text_png(text, tcolor, out_path):
    """Слово капсом, жирный, чёрная обводка, прозрачный фон. Рисуем крупно —
    build_overlays масштабирует под кадр. Возвращает True при успехе."""
    from PIL import Image, ImageDraw, ImageFont
    txt = " ".join((text or "").split()).upper()
    if not txt:
        return False
    fill = TEXT_COLORS.get(str(tcolor).lower(), TEXT_COLORS["white"]) + (255,)
    fs = 220
    font = None
    for fp in _TEXT_FONTS:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, fs)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()
    sw = max(4, int(fs * 0.11))
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    bb = d0.textbbox((0, 0), txt, font=font, stroke_width=sw)
    pad = sw + 14
    w = bb[2] - bb[0] + pad * 2
    h = bb[3] - bb[1] + pad * 2
    img = Image.new("RGBA", (max(w, 8), max(h, 8)), (0, 0, 0, 0))
    ImageDraw.Draw(img).text(
        (pad - bb[0], pad - bb[1]), txt, font=font, fill=fill,
        stroke_width=sw, stroke_fill=(0, 0, 0, 255))
    try:
        img.save(out_path)
        return True
    except OSError:
        return False


VID_EXT = (".mp4", ".mov", ".webm", ".mkv")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

BADGES = {
    # source, is_video -> (label, css-class)
    ("local_library", False): ("📁 БИБЛИОТЕКА · ФОТО", "b-libph"),
    ("local_library", True): ("📁 БИБЛИОТЕКА · ВИДЕО", "b-libvid"),
    ("press_photo", False): ("🌐 ПРЕСС-ФОТО", "b-press"),
    ("wikimedia", False): ("🌐 ПРЕСС-ФОТО", "b-press"),
    ("pexels_photo", False): ("🎞 СТОК · ФОТО", "b-stock"),
    ("pexels_video", True): ("🎞 СТОК · ВИДЕО", "b-stock"),
    ("generate", False): ("🎨 ГЕНЕРАЦИЯ", "b-gen"),
}


def badge_for(source, is_video):
    return BADGES.get((source, is_video)) or BADGES.get((source, False)) or (f"{source}", "b-other")


def resolved_asset(images_dir, sid):
    hits = []
    for p in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*")):
        if p.endswith(".json") or p.endswith(".revframe.jpg"):
            continue
        try:
            if os.path.getsize(p) > 0:
                hits.append(p)
        except OSError:
            continue          # transient temp file vanished mid-glob
    return sorted(hits)[0] if hits else None


# --- «Уникализировать» — набор мелких обратимых правок кадра ------------
# Одна панель на карточке: зеркало / цвет / поворот 1-3° / зум-обрез.
# Состояние на сцену копится в images/.uniq.json, применяется ЦЕЛИКОМ от
# нетронутого исходника (images/.uniq_orig/) одной ffmpeg-цепочкой — клики
# не «пережаривают» кадр, любой можно снять. Чёрные углы от поворота
# закрываются размытой подложкой той же картинки (как blur-fill вертикалок).
_UNIQ_DEFAULT = {"flip": False, "color": False, "bw": False, "rot": 0, "zoom": 1.0}


def _uniq_path(images_dir):
    return os.path.join(images_dir, ".uniq.json")


def _uniq_load(images_dir):
    try:
        return json.load(open(_uniq_path(images_dir)))
    except Exception:
        return {}


def _uniq_save(images_dir, data):
    p = _uniq_path(images_dir)
    tmp = p + ".tmp"
    json.dump(data, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _uniq_forget(images_dir, sid):
    """Забыть обработку сцены: состояние + сохранённый исходник. Нужно, когда
    файл ЗАМЕНИЛИ (другое фото всплывашки, новый поиск) — иначе «сброс» вернёт
    кадр от ПРЕДЫДУЩЕЙ картинки, а подсветка кнопок соврёт (2026-10-17)."""
    data = _uniq_load(images_dir)
    if data.pop(str(sid), None) is not None:
        _uniq_save(images_dir, data)
    for p in glob.glob(os.path.join(images_dir, ".uniq_orig", f"scene_{sid:03d}.*")):
        try:
            os.remove(p)
        except OSError:
            pass


def _uniq_state(images_dir, sid):
    st = dict(_UNIQ_DEFAULT)
    st.update(_uniq_load(images_dir).get(str(sid), {}))
    return st


def _uniq_is_default(st):
    return (not st.get("flip") and not st.get("color") and not st.get("bw")
            and int(st.get("rot", 0)) == 0 and float(st.get("zoom", 1.0)) <= 1.001)


def _uniq_summary(st):
    bits = []
    if st.get("flip"):
        bits.append("🔄")
    if st.get("color"):
        bits.append("🎨")
    if st.get("bw"):
        bits.append("⬜")
    if int(st.get("rot", 0)):
        bits.append(f"{int(st['rot'])}°")
    if float(st.get("zoom", 1.0)) > 1.001:
        bits.append(f"{float(st['zoom']):.1f}×")
    return " ".join(bits)


def _uniq_ffmpeg(orig, dst, st, is_video):
    """Собрать и применить всю цепочку уникализации от `orig` к `dst`."""
    pre = []
    if st.get("flip"):
        pre.append("hflip")
    if st.get("color"):
        pre.append("eq=contrast=1.12:saturation=1.16:brightness=0.03")
    if st.get("bw"):
        pre.append("hue=s=0")
    z = float(st.get("zoom", 1.0))
    if z > 1.001:
        pre.append(f"crop=iw/{z:.4f}:ih/{z:.4f}")
    rot = int(st.get("rot", 0))
    pre_s = (",".join(pre) + ",") if pre else ""

    if rot <= 0:
        vf = (pre_s.rstrip(",") or "null")
        # explicit video map — with any -map given, ffmpeg drops auto stream
        # selection, so -vf alone + "-map 0:a?" would ship an audio-only file
        args = ["-vf", vf, "-map", "0:v:0"]
    else:
        rad = rot * 0.01745329
        cov = 1.0 + rot * 0.032        # надуть резкий слой, чтобы после
        #                                поворота он крыл кадр (углы — подложка)
        # [a] размытая подложка (та же картинка, зум+поворот, срезаем чёрные
        #     углы, блюрим); [b] резкий слой, надутый и повёрнутый, выводится
        #     в исходном размере — видно только центр, углы кадра = подложка.
        fc = (f"[0:v]{pre_s}format=rgba,split=2[a][b];"
              f"[a]scale=iw*1.5:ih*1.5,rotate={rad:.6f}:c=black,"
              f"crop=iw/1.5:ih/1.5,boxblur=22:2[bg];"
              f"[b]scale=iw*{cov:.3f}:ih*{cov:.3f},"
              f"rotate={rad:.6f}:ow=iw/{cov:.3f}:oh=ih/{cov:.3f}:c=black@0[fg];"
              f"[bg][fg]overlay=0:0,format=yuv420p,setsar=1[out]")
        args = ["-filter_complex", fc, "-map", "[out]"]

    cmd = ["ffmpeg", "-y", "-i", orig] + args
    if is_video:
        cmd += ["-map", "0:a?", "-c:a", "copy"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", dst]
    else:
        cmd += ["-q:v", "2", dst]
    return subprocess.run(cmd, capture_output=True)


def overlay_preview_path(photo):
    # An overlay's "photo" can legitimately be a video file (pexels_video
    # source) — build_overlays.py already knows to grab a still frame from
    # it for the FINAL baked video. The dashboard's own <img> preview never
    # got that same treatment: it served the raw .mp4/.mov straight as an
    # <img src>, which every browser renders as a broken/blank (sometimes
    # see-through) image icon (user, 2026-09-22: "битые картинки, прозрачный
    # фон"). Cache one representative JPEG frame next to the video and hand
    # THAT to <img> instead — never the video path itself.
    if not photo or not str(photo).lower().endswith(VID_EXT):
        return photo
    if not os.path.exists(photo):
        return photo
    cached = photo + ".ovthumb.jpg"
    if not os.path.exists(cached) or os.path.getmtime(cached) < os.path.getmtime(photo):
        b = make_thumb_bytes(photo)
        if not b:
            return photo
        with open(cached, "wb") as f:
            f.write(b)
    return cached


def make_thumb_bytes(asset_path):
    """480x270 cover-cropped JPEG bytes for a still or a video's ~1s frame."""
    frame_src = asset_path
    tmp = None
    if asset_path.lower().endswith(VID_EXT):
        tmp = asset_path + ".revframe.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "1", "-i", asset_path, "-vframes", "1",
             "-vf", f"scale={TW}:{TH}:force_original_aspect_ratio=increase,crop={TW}:{TH}",
             tmp], capture_output=True)
        frame_src = tmp
    try:
        im = Image.open(frame_src).convert("RGB")
    except OSError:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
        return None
    r = max(TW / im.width, TH / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)))
    l, t = (im.width - TW) // 2, (im.height - TH) // 2
    im = im.crop((l, t, l + TW, t + TH))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=74)
    if tmp and os.path.exists(tmp):
        os.remove(tmp)
    return buf.getvalue()


def fmt(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def load_scenes(scenes_path):
    return json.load(open(scenes_path, encoding="utf-8"))["scenes"]


# ---------------------------------------------------------------- отказы ----
# Журнал «почему пользователь это убрал» (2026-10-16). Бан по md5 блокирует
# ровно тот файл и не мешает прийти следующему с тем же дефектом; здесь отказ
# привязан к ЗАПРОСУ и к ПРИЧИНЕ. Подробности — rejections.py.
#
# Расшифровка голосового комментария идёт В ФОНЕ: короткая фраза занимает у
# whisper около девяти секунд, и столько ждать после каждого снятия нельзя.
# Поэтому карточка закрывается мгновенно, а запись дописывается, когда текст
# готов. Если расшифровка не удалась — запись всё равно пишется, без текста:
# сам факт отказа и его причина ценнее комментария.

def _scene_meta(sid, scenes, images_dir, kind):
    """Запрос, источник и md5 того, что сняли, — чтобы отказ был привязан к
    запросу, а не к одному файлу."""
    meta = {"query": "", "source": "", "md5": "", "file": "", "base_query": ""}
    for s in scenes:
        if s.get("id") == sid:
            meta["base_query"] = s.get("source_query") or ""
            meta["query"] = meta["base_query"]
            meta["source"] = s.get("source") or ""
            break
    # Для ВСПЛЫВАШКИ запрос лежит не в scenes.json, а в overlays_fetch —
    # иначе в журнал попадает запрос базы, и запись выглядит так, будто
    # сняли базовый кадр (поймано на первых трёх живых записях 2026-10-16:
    # пользователь снимал всплывашки Вэнса, аэропорта и Госдепа, а в журнале
    # стояли запросы их баз). Базовый запрос при этом тоже сохраняем: пара
    # «база + всплывашка» и есть то, что он оценивает, когда говорит
    # «что оно иллюстрирует».
    if kind in ("overlay", "text"):
        for cand in (glob.glob("*overlays_fetch*.json")
                     + glob.glob("*overlay*fetch*.scenes.json")):
            try:
                ovq = json.load(open(cand, encoding="utf-8"))["scenes"]
            except (OSError, ValueError, KeyError):
                continue
            for o in ovq:
                if o.get("id") == sid:
                    meta["query"] = o.get("source_query") or meta["query"]
                    meta["source"] = o.get("source") or meta["source"]
                    break
            break
    sub = "overlays" if kind in ("overlay", "text") else images_dir
    for p in glob.glob(os.path.join(sub, f"scene_{sid:03d}.*")):
        if p.endswith((".json", ".revframe.jpg", ".ovthumb.jpg")):
            continue
        meta["file"] = p
        try:
            import hashlib
            with open(p, "rb") as fh:
                meta["md5"] = hashlib.md5(fh.read()).hexdigest()
        except OSError:
            pass
        break
    return meta


def _channel_of(project):
    """Канал ролика — для журнала отказов. Берём из `.source_dir`, который
    ship.sh кладёт в кэш: там путь вида D:\\YouTube\\НОВОСТИ\\<канал>\\…
    Фоллбэк — префикс имени проекта. Раньше канал брался из JSON браузера,
    которого тот не шлёт, и поле было пустым во ВСЕХ записях (поймано
    2026-10-16 на 17 живых записях)."""
    try:
        sd = os.path.expanduser(f"~/.cache/videoryad/{project}.source_dir")
        if os.path.exists(sd):
            parts = open(sd, encoding="utf-8").read().replace("\\", "/").split("/")
            for i, p in enumerate(parts):
                if p.upper().startswith("НОВОСТИ") and i + 1 < len(parts):
                    return parts[i + 1]
    except OSError:
        pass
    pref = project.split("-", 1)[0].lower()
    return {"planeta": "ПЛАНЕТА", "5min": "5 МИНУТ", "ds": "ДИПЛОМАТИЯ СИЛЫ",
            "olka": "ОЛЬКА", "perevod": "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО"}.get(pref, "")


def _log_reject_async(spec, sid, scenes, images_dir, project):
    """Пишет отказ в журнал; если приложено аудио — сперва расшифровывает."""
    def work():
        note = str(spec.get("note", "") or "").strip()
        audio_b64 = spec.get("audio") or ""
        if audio_b64:
            tmp = None
            try:
                raw = base64.b64decode(audio_b64)
                fd, tmp = tempfile.mkstemp(suffix=".webm")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(raw)
                from voice_note import transcribe
                spoken = transcribe(tmp)
                if spoken:
                    note = (note + " " + spoken).strip() if note else spoken
            except Exception:
                pass
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        kind = str(spec.get("kind", "scene"))
        meta = _scene_meta(sid, scenes, images_dir, kind)
        try:
            from rejections import log_rejection
            log_rejection(scene=sid, kind=kind,
                          action=str(spec.get("action", "clear")),
                          reason=str(spec.get("reason", "other")),
                          note=note, project=project,
                          channel=_channel_of(project), **meta)
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


def planned_is_video(scene):
    q = scene.get("source_query", "")
    return scene.get("source") == "pexels_video" or q.lower().endswith(VID_EXT)


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------
CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0e0f12;color:#e7e7ea;font:14px/1.5 -apple-system,Segoe UI,Roboto,system-ui,sans-serif}
header{position:sticky;top:0;z-index:10;background:#15161ae0;backdrop-filter:blur(8px);
  border-bottom:1px solid #2a2c33;padding:11px 20px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header h1{font-size:15px;margin:0;font-weight:600}
header .sub{color:#9a9aa2;font-size:13px}
header .spacer{flex:1}
#prog{height:4px;background:#2a2c33;border-radius:3px;width:160px;overflow:hidden}
#prog>i{display:block;height:100%;background:#3a86ff;width:0;transition:width .3s}
button{background:#2b2d36;color:#e7e7ea;border:1px solid #3a3d48;border-radius:7px;padding:7px 13px;font:inherit;cursor:pointer}
button:hover{background:#343742}
#count{font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;padding:20px;max-width:1640px;margin:0 auto}
.card{margin:0;background:#17181d;border:1px solid #262830;border-radius:12px;overflow:hidden;cursor:pointer;transition:border-color .12s}
.card:hover{border-color:#3a3d48}
.card.marked{border-color:#e04a3a;box-shadow:0 0 0 2px #e04a3a55}
.thumb{position:relative;aspect-ratio:16/9;background:#0b0b0d}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb.pending img{opacity:.12}
.thumb .wait{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#6b6b73;font-size:12px}
.thumb.ready .wait,.thumb.failed .wait{display:none}
.thumb.failed{background:#2a1414}
.thumb.failed::after{content:"нет кадра";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#e04a3a;font-weight:700}
.num{position:absolute;left:8px;top:8px;background:#000b;padding:2px 8px;border-radius:6px;font-weight:700;font-size:13px}
.ovmark{position:absolute;box-sizing:border-box;border:2px solid #46d39a;border-radius:3px;
  overflow:hidden;pointer-events:none;z-index:4;box-shadow:0 2px 8px #000a}
.ovmark img{width:100%;height:100%;object-fit:cover;display:block}
.ovmark::after{content:"";position:absolute;inset:0;border:2px solid rgba(255,255,255,.5);border-radius:1px}
.ovmark.solid{border-color:#7dffc8;box-shadow:0 0 0 2px rgba(125,255,200,.5),0 3px 12px #000c}
.ovpos{color:#8ef0c8;font-weight:400;font-size:11px}
.badge{position:absolute;right:8px;top:8px;padding:3px 8px;border-radius:6px;font-size:11px;font-weight:700;
  letter-spacing:.02em;color:#fff;text-shadow:0 1px 2px #0008;opacity:.55}
.thumb.ready .badge{opacity:1}
.b-libph{background:#2563eb}                       /* библиотека фото — синий */
.b-libvid{background:#ec4899}                      /* библиотека видео — розовый */
.b-press{background:#16a34a}                       /* пресс-фото из интернета — зелёный */
.b-gen{background:#eab308;color:#1a1400;text-shadow:none}  /* генерация ИИ — жёлтый */
.b-stock{background:#ea580c}                       /* сток — оранжевый */
.b-other{background:#4b5563}
.card.needup{border-color:#f59e0b;box-shadow:0 0 0 2px #f59e0b66}
.needb{position:absolute;left:0;right:0;bottom:0;background:#f59e0be6;color:#1a1400;
  font-weight:800;font-size:12px;text-align:center;padding:5px 6px;letter-spacing:.02em;
  animation:needpulse 1.4s ease-in-out infinite}
@keyframes needpulse{0%,100%{opacity:1}50%{opacity:.62}}
.needr{margin:4px 0 0;font-size:12px;color:#f59e0b;font-weight:700}
#needjump{background:#f59e0b;color:#1a1400;border-color:#f59e0b;font-weight:700}
figcaption{padding:10px 13px 13px}
.meta{color:#8b8b93;font-size:12px;letter-spacing:.02em}
.srcq{color:#7f8ea3;font-size:12px;margin:3px 0 7px;word-break:break-all}
.txt{margin:0;font-size:13.5px;color:#d7d7db}
.acts{display:flex;gap:7px;margin-top:10px;flex-wrap:wrap}
.acts button{padding:6px 10px;font-size:12px;border-radius:6px}
.acts button.on{background:#e04a3a;border-color:#e04a3a;color:#fff}
.up{display:inline-block;padding:6px 10px;font-size:12px;border-radius:6px;background:#1d3a5f;
  border:1px solid #2b5c96;color:#cfe4ff;cursor:pointer;user-select:none}
.up:hover{background:#244a78}
.up input{display:none}
.keepimg{background:#1f5133;border:1px solid #2f7a4c;color:#c9f5da;cursor:pointer}
.banimg{background:#5c1f22;border:1px solid #8c2f34;color:#f7cdd0;cursor:pointer}
.mirbtn{background:#243b5e;border:1px solid #3a5a8c;color:#cfe0ff;cursor:pointer}
.zoomwrap{display:inline-flex;align-items:center;gap:3px;background:#20261c;border:1px solid #55703a;
  border-radius:7px;padding:3px 6px;color:#dbefc6}
.zoomwrap i{font-style:normal;font-size:11px;color:#9fbf88;min-width:0}
.zoombtn{background:#334028;border:1px solid #55703a;color:#dbefc6;cursor:pointer;
  border-radius:5px;padding:2px 7px;font-size:12px}
.zoombtn:hover{background:#3f5233}
.zoombtn:disabled{opacity:.5;cursor:default}
.uniqwrap{display:inline-flex;flex-wrap:wrap;align-items:center;gap:3px;background:#241d2e;
  border:1px solid #6a4d8c;border-radius:7px;padding:3px 6px;color:#e6d6f5}
.uniqwrap i{font-style:normal;font-size:11px;color:#c3a6e0;min-width:0}
.uqgrp{display:inline-flex;align-items:center;gap:2px}
.uqbtn{background:#3a2d4d;border:1px solid #6a4d8c;color:#eaddf7;cursor:pointer;
  border-radius:5px;padding:2px 7px;font-size:12px}
.uqbtn:hover{background:#493a5f}
.uqbtn.on{background:#7b4dd6;border-color:#a583e8;color:#fff}
.uqbtn:disabled{opacity:.5;cursor:default}
.keepimg:hover{background:#276641}
.note{display:none;width:100%;margin-top:9px;background:#0e0f12;color:#e7e7ea;border:1px solid #3a3d48;
  border-radius:7px;padding:7px;font:inherit;resize:vertical;min-height:44px}
.card.marked .note{display:block}
.ovb{position:absolute;left:8px;bottom:8px;background:#0b3d2eee;color:#8ef0c8;
  padding:3px 8px;border-radius:6px;font-size:11px;font-weight:700}
.ovwrap{margin-top:9px;border:1px solid #8a7300;border-radius:8px;background:#221c00;padding:9px}
.ovwrap.ok{border-color:#1f6b4f;background:#0e1a15}
.ovhead{font-size:11.5px;color:#ffe27a;font-weight:700;margin-bottom:7px}
.ovwrap.ok .ovhead{display:none}
.ovprev{width:180px;border-radius:6px;border:1px solid #3a3d48;align-self:flex-start}
.txtwrap{margin-top:9px;border:1px solid #6a4d8c;border-radius:8px;background:#1e1830;padding:9px}
.txtwrap.ok{border-color:#1f6b4f;background:#0e1a15}
.txtwrap .ovhead{color:#d8c2f5}
.txtwrap.ok .ovhead{display:none}
.tkwrap{margin-top:9px;border:1px solid #2a5d8c;border-radius:8px;background:#0f1f2e;padding:9px}
.tkwrap.ok{border-color:#1f6b4f;background:#0e1a15}
.tkwrap .ovhead{color:#9fd2ff}
.tkwrap.ok .ovhead{display:none}
.ovtxtin{width:100%;box-sizing:border-box;text-transform:uppercase;font-weight:800;
  letter-spacing:.5px;background:#0e0f12;color:#fff;border:1px solid #3a3d48;border-radius:5px;padding:6px}
.ovcolrow{display:flex;gap:5px}
.ovcolrow button{flex:1;cursor:pointer;border-radius:5px;padding:4px 2px;font-weight:800;
  font-size:11px;border:2px solid #555;color:#111}
.ovcolrow button.on{border-color:#fff;box-shadow:0 0 0 2px #7b4dd6}
.ovcol-white{background:#fff}.ovcol-yellow{background:#ffe800}
.ovcol-red{background:#ff2620;color:#fff}
.ovshapes{display:flex;gap:4px}
.ovshapes button{width:30px;height:26px;padding:0;background:#2a2f3a;border:1px solid #444a58;
  border-radius:5px;color:#c9cedb;font-size:15px;cursor:pointer;line-height:1}
.ovshapes button.on{background:#7b4dd6;border-color:#a583e8;color:#fff}
.ovgrid{display:grid;grid-template-columns:repeat(3,26px);gap:3px}
.ovgrid button{width:26px;height:26px;padding:0;background:#2a2f3a;border:1px solid #444a58;
  color:#9aa2b4;border-radius:4px;font-size:13px;line-height:1}
.ovgrid button.on{background:#7b4dd6;border-color:#a583e8;color:#fff}
.txtmark{position:absolute;box-sizing:border-box;border:2px dashed #ffcf5a;border-radius:3px;
  display:flex;align-items:center;justify-content:center;overflow:hidden;pointer-events:none;z-index:5}
.txtmark img{max-width:100%;max-height:100%;object-fit:contain}
.pvbtn{background:#2d1f4d;border:1px solid #6a4d8c;color:#e6d6f5;cursor:pointer}
.pvbtn:hover{background:#3c2a63}
.pvbox{position:absolute;inset:0;background:#000;z-index:8}
.pvbox video{width:100%;height:100%;object-fit:contain;background:#000}
.pvclose{position:absolute;top:6px;right:6px;background:#000b;color:#fff;border:1px solid #777;
  border-radius:6px;padding:3px 10px;cursor:pointer;z-index:9;font-size:13px}
.ovpanel{padding:0;display:flex;flex-direction:column;gap:7px}
.ovpanel[hidden]{display:none}
.ovbtns{display:flex;gap:8px;margin-top:2px}
.ovok{flex:1;padding:7px 10px;font-size:12.5px;font-weight:700;border-radius:6px;
  background:#1f6b4f;border:1px solid #2f8f6a;color:#dffff0;cursor:pointer}
.ovok:hover{background:#268160}
.ovdone{font-size:12px;color:#8ef0c8;font-weight:600}
.rjgood{background:transparent;border:1px solid #3a5a48;color:#7fd6aa;border-radius:5px;
        padding:1px 6px;margin-left:6px;cursor:pointer;font-size:12px;opacity:.55}
.rjgood:hover{opacity:1;border-color:#6fbf94;background:#1e3328}
.ovedit{margin-left:8px;padding:3px 8px;font-size:11px;border-radius:5px;
  background:#0e0f12;border:1px solid #3a3d48;color:#a9c9bd;cursor:pointer}
.ovrow{display:flex;align-items:center;gap:8px;font-size:12px;color:#a9c9bd}
.ovrow select,.ovrow input{background:#0e0f12;color:#e7e7ea;border:1px solid #3a3d48;
  border-radius:6px;padding:5px 7px;font:inherit}
.ovrow input[type=number]{width:80px}
.ovfind{flex-wrap:wrap}
.ovfind input[type=text]{flex:1;min-width:160px}
.ovfind button{background:#1d3a5f;border:1px solid #2b5c96;color:#cfe4ff;border-radius:6px;
  padding:5px 10px;font:inherit;font-size:12px;cursor:pointer}
.ovfind button.mic{padding:5px 8px;background:#2a2c33;border-color:#3a3d48;
  touch-action:none;user-select:none;-webkit-user-select:none}
.ovfind button.mic:active{background:#5a1e1e;border-color:#8a2b2b}
.imgfind{margin-top:8px}
.imgfind input[type=text]{background:#0e0f12;color:#e7e7ea;border:1px solid #3a3d48;
  border-radius:6px;padding:5px 7px;font:inherit}
.opts{width:100%;display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.opts[hidden]{display:none}
.optnote{width:100%;font-size:11px;color:#9aa4b2;margin-bottom:2px}
.opt{position:relative;width:88px;height:56px;border-radius:5px;overflow:hidden;cursor:pointer;
  border:2px solid transparent;background:#0b0b0d;flex:0 0 auto}
.opt img{width:100%;height:100%;object-fit:cover;display:block}
.opt:hover{border-color:#5a7fb0}
.opt.picked{border-color:#46d39a;box-shadow:0 0 0 2px rgba(70,211,154,.4)}
.opt .vtag{position:absolute;left:3px;bottom:2px;font-size:10px;background:#000a;padding:0 3px;border-radius:3px}
.opt.noimg{background:#1a1c22;display:flex;align-items:center;justify-content:center}
.opt.noimg .q{color:#6b6b73;font-size:18px;font-weight:700}
#ovadd,button[id^=ovadd]{background:#123; border-color:#2b5c96; color:#9fd0ff}
.ovup{display:inline-block;padding:6px 10px;font-size:12px;border-radius:6px;background:#1d3a5f;
  border:1px solid #2b5c96;color:#cfe4ff;cursor:pointer;user-select:none;align-self:flex-start}
.ovup input{display:none}
.ovfile{font-size:11px;color:#8a94a2}
.ovclear{align-self:flex-start;padding:5px 9px;font-size:11px;border-radius:6px;
  background:#3a1a1a;border:1px solid #6b2b2b;color:#f0b8b8;cursor:pointer}
.ovmsg{font-size:11px;color:#8ef0c8}
dialog{background:#17181d;color:#e7e7ea;border:1px solid #3a3d48;border-radius:12px;padding:18px;max-width:560px;width:90%}
dialog textarea{width:100%;min-height:180px;background:#0e0f12;color:#e7e7ea;border:1px solid #3a3d48;border-radius:7px;padding:9px;font:inherit}
dialog .row{display:flex;gap:9px;justify-content:flex-end;margin-top:11px}
"""


def card_html(s, t, live, images_dir, needs=None, overlays=None, sfx=None, tickers=None):
    sid = s["id"]
    d = s["duration_sec"]
    overlays = overlays or {}
    sfx = sfx if sfx is not None else sfx_list()
    ov_cur = overlays.get(str(sid), {})
    # ВЕРТИКАЛЬ ВСПЛЫВАШКИ — ПОСЦЕННО (2026-10-17, прямая просьба пользователя:
    # «если бы она стояла вверху в центре, это было бы как раз хорошо… я бы мог
    # её менять»). Раньше верх/низ задавался ОДНИМ ключом anchor на весь ролик
    # (top для всех каналов кроме ПЛАНЕТЫ) и на дашборде его не было вообще —
    # менялась только горизонталь. Теперь запись сцены перебивает общий ключ.
    _ov_anchor = str(ov_cur.get("anchor") or overlays.get("anchor", "bottom")).lower()
    is_vid = planned_is_video(s)
    label, cls = badge_for(s.get("source", ""), is_vid)
    q = s.get("source_query", "")
    srcq = q.split("/")[-1] if "." in q.split("/")[-1] else q
    needs = needs or {}
    need_reason = needs.get(str(sid), "")
    need_hidden = "" if need_reason else " hidden"
    need_badge = f'<span class="needb" id="need{sid}"{need_hidden}>⚠️ НУЖНО ТВОЁ ФОТО</span>'
    need_row = (f'<p class="needr" id="needr{sid}"{need_hidden}>'
               f'⬆️ загрузи: {need_reason or ""}</p>')

    if live:
        thumb_inner = (f'<img id="i{sid}" alt="">'
                       f'<span class="wait">ждём кадр…</span>'
                       f'<span class="num">{sid:02d}</span>'
                       f'<span class="badge {cls}" id="b{sid}">{label}</span>'
                       f'{need_badge}')
        thumb_cls = "thumb pending"
    else:
        uri = None
        ap = resolved_asset(images_dir, sid)
        if ap:
            b = make_thumb_bytes(ap)
            if b:
                import base64
                uri = "data:image/jpeg;base64," + base64.b64encode(b).decode()
                is_vid = ap.lower().endswith(VID_EXT)
                label, cls = badge_for(s.get("source", ""), is_vid)
        img = f'<img src="{uri}" alt="">' if uri else '<span class="wait">нет кадра</span>'
        thumb_inner = (f'{img}<span class="num">{sid:02d}</span>'
                       f'<span class="badge {cls}">{label}</span>'
                       f'{need_badge}')
        thumb_cls = "thumb ready" if uri else "thumb failed"

    upload_btn = (f'<label class="up" id="up{sid}">⬆️ Загрузить своё'
                  f'<input type="file" accept="image/*,video/*" '
                  f'onchange="upload({sid},this)"></label>') if live else ""
    # «меня устраивает этот временный кадр» — снять жёлтую пометку, не искать
    # дальше (user 2026-09-06). Только на жёлтых карточках, где кадр уже есть.
    _has_img = bool(resolved_asset(images_dir, sid))
    keep_btn = (f'<button class="keepimg" id="keep{sid}" onclick="keepImg({sid})">'
                f'✓ Оставить это фото</button>' if (live and need_reason and _has_img) else "")
    # «примелькалось, задолбало» (user, 2026-09-22) — бан по md5, независимо
    # от обычного 3-видео кулдауна. Убирает кадр с карточки СРАЗУ (текущая
    # сборка тоже не должна его показывать) и метит needs_upload, чтобы
    # карточка не выглядела «готовой» без замены.
    # 2026-09-23: бан теперь может быть ВРЕМЕННЫМ (banAsset спрашивает число
    # дней, пусто = навсегда) — "не совсем убивать... через 10 дней только
    # его использовать".
    ban_btn = (f'<button class="banimg" id="ban{sid}" onclick="banAsset({sid})" '
               f'title="убрать этот файл из подбора — навсегда или на N дней">'
               f'🚫 Не использовать</button>' if (live and _has_img) else "")
    # (зеркало и зум-обрез теперь живут внутри панели «Уникализировать» ниже —
    # отдельные кнопки убраны, чтобы не дублировать 🔄. Роуты mirror/zoomimg
    # в сервере оставлены для совместимости, UI их больше не вызывает.)
    mirror_btn = ""
    zoom_btn = ""
    # «Уникализировать» — зеркало / цвет / поворот 1-3° (углы = размытая
    # подложка) / зум-обрез. Всё копится в .uniq.json и применяется ЦЕЛИКОМ от
    # нетронутого исходника — клики не пережаривают кадр, любой снимается
    # повторным нажатием (user 2026-09-08).
    if live and _has_img:
        _ust = _uniq_state(images_dir, sid)
        _on = lambda c: " on" if c else ""
        uniq_block = (
            f'<span class="uniqwrap" id="uw{sid}">✨'
            f'<button class="uqbtn{_on(_ust["flip"])}" data-k="flip" '
            f'onclick="uniqTog({sid},\'flip\')" title="зеркало">🔄</button>'
            f'<button class="uqbtn{_on(_ust["color"])}" data-k="color" '
            f'onclick="uniqTog({sid},\'color\')" title="контраст+цвет">🎨</button>'
            f'<button class="uqbtn{_on(_ust["bw"])}" data-k="bw" '
            f'onclick="uniqTog({sid},\'bw\')" title="чёрно-белое">⬜</button>'
            f'<span class="uqgrp" data-k="rot">⟳'
            + "".join(f'<button class="uqbtn{_on(int(_ust["rot"])==r)}" '
                      f'onclick="uniqSet({sid},\'rot\',{r})">{r}°</button>'
                      for r in (1, 2, 3))
            + f'</span>'
            f'<span class="uqgrp" data-k="zoom">✂️'
            + "".join(f'<button class="uqbtn{_on(abs(float(_ust["zoom"])-z)<0.01)}" '
                      f'onclick="uniqSet({sid},\'zoom\',{z})">{z}×</button>'
                      for z in (1.1, 1.2, 1.3))
            + f'</span>'
            f'<button class="uqbtn" onclick="uniqReset({sid})" title="снять всё">сброс</button>'
            f'<i id="um{sid}">{_uniq_summary(_ust)}</i></span>')
    else:
        uniq_block = ""
    # "add a pop-up here" — user can attach an overlay to ANY scene, not only
    # the ones Claude proposed (user request 2026-09-02).
    preview_btn = (f'<button class="pvbtn" id="pvbtn{sid}" onclick="previewScene({sid},event)" '
                   f'title="собрать и посмотреть этот кусок как в финале">▶ превью</button>'
                   ) if live else ""
    _tw0 = ov_cur.get("text") if isinstance(ov_cur.get("text"), dict) else {}
    _txt_on0 = bool(str(_tw0.get("words") or _tw0.get("text") or "").strip())
    _photo_on0 = bool(ov_cur.get("photo")) or (bool(ov_cur) and not _txt_on0)
    ov_add_btn = (f'<button id="ovadd{sid}" onclick="ovAdd({sid},{d:.1f})"'
                  f'{"" if (live and not _photo_on0) else " hidden"}>➕ всплывашка</button>'
                  f'<button id="txtadd{sid}" onclick="txtAdd({sid})"'
                  f'{"" if (live and not _txt_on0) else " hidden"}>➕ текст</button>'
                  ) if live else ""
    # type keywords -> fetch a new frame for this scene from the internet, now.
    img_search = (f'<div class="ovrow ovfind imgfind">'
                  f'<input type="text" id="imgq{sid}" placeholder="найти кадр в интернете — ключевые слова" '
                  f'onfocus="if(/^[⚠🔴]/.test(this.value))this.value=\'\'" '
                  f'onkeydown="if(event.key===\'Enter\')imgOpts({sid})">'
                  f'<button type="button" onclick="imgOpts({sid})">🔎 найти</button>'
                  f'<button type="button" class="mic" data-mic="imgq{sid}" title="держи и говори" '
                  f'onpointerdown="micStart(event,\'imgq{sid}\',\'imgmsg{sid}\',()=>imgOpts({sid}))" '
                  f'onpointerup="micStop()" onpointercancel="micStop()">🎤</button>'
                  f'<span class="ovfile" id="imgmsg{sid}"></span>'
                  f'<div class="opts" id="opts_img{sid}" hidden></div></div>') if live else ""

    # --- corner pop-up ("всплывашка") ---------------------------------
    # Claude proposes; the user only approves. The whole control is hidden
    # unless this scene has a proposal in overlays.json (the poll keeps it
    # in sync). No "add on every video scene" button — the user asked not
    # to see that ("зашил слишком много").
    _tw = ov_cur.get("text") if isinstance(ov_cur.get("text"), dict) else {}
    _twords = _tw.get("words") or _tw.get("text") or ""
    _text_active = bool(str(_twords).strip())
    # фото-панель активна: есть фото, ЛИБО есть заготовка сцены без текста
    _photo_active = bool(ov_cur.get("photo")) or (bool(ov_cur) and not _text_active)
    has_ov = _photo_active or _text_active
    ov_badge = (f'<span class="ovb" id="ovb{sid}"{"" if has_ov else " hidden"}>🖼 всплывашка</span>')
    if live:
        opts = "".join(f'<option value="{x["name"]}"'
                       f'{" selected" if x["name"] == ov_cur.get("sound") else ""}>{x["label"]}</option>'
                       for x in sfx)
        at_val = ov_cur.get("at", 0.4)   # появляется сразу после старта сцены, держится до конца
        ph = ov_cur.get("photo", "")
        _uov = _uniq_state("overlays", sid)
        ph_prev = overlay_preview_path(ph) if ph and os.path.exists(ph) else ph
        prev = (f'<img class="ovprev" id="ovprev{sid}" src="{ph_prev}?v={int(os.path.getmtime(ph))}" alt="">'
                if ph and os.path.exists(ph) else f'<img class="ovprev" id="ovprev{sid}" alt="" hidden>')
        _tcol = _tw.get("color", "yellow")
        _tpos = _tw.get("pos", "bc")
        _topts = "".join(f'<option value="{x["name"]}"'
                         f'{" selected" if x["name"] == _tw.get("sound","pop") else ""}>{x["label"]}</option>'
                         for x in sfx)
        # утверждено ли уже — держим ровно так, как оставил юзер, не сбрасывая
        # при каждом ре-рендере дашборда (user, 2026-09-15, злился: «утвердил —
        # значит утвердил, не заставляй делать это по десять раз»)
        _ov_approved = bool(ov_cur.get("approved")) and _photo_active
        ov_ui = (
            f'<div class="ovwrap{" ok" if _ov_approved else ""}" id="ovwrap{sid}"'
            f'{"" if _photo_active else " hidden"}>'
            f'<div class="ovhead">🖼 ВСПЛЫВАШКА — фото уголком поверх кадра. '
            f'Держится почти всю сцену. Жми «утвердить».</div>'
            f'<div class="ovpanel" id="ovp{sid}"{" hidden" if _ov_approved else ""}>'
            f'{prev}'
            f'<div class="ovrow"><label class="ovup" id="ovphoto{sid}">⬆️ загрузить фото'
            f'<input type="file" accept="image/*" onchange="ovPhoto({sid},this)"></label>'
            f'<button type="button" class="mirbtn" id="mirov{sid}" onclick="mirrorOv({sid})">🔄 отзеркалить</button></div>'
            # ТОТ ЖЕ НАБОР, ЧТО У ОСНОВНОГО КАДРА (user, 2026-10-17: «для
            # превьюшек тоже эти кнопки — отзеркалить, масштаб, угол разворота,
            # чёрно-белое, контрастность… чтобы функционал был такой же»).
            # Роут uniq теперь умеет работать по папке overlays/ (параметр t=ov),
            # состояние живёт в overlays/.uniq.json, исходник — в .uniq_orig/.
            + (f'<div class="ovrow"><span>обработка</span>'
               f'<span class="uniqwrap" id="uwov{sid}">'
               f'<button class="uqbtn{" on" if _uov["flip"] else ""}" data-k="flip" '
               f'onclick="uniqTog({sid},\'flip\',\'ov\')" title="зеркало">🔄</button>'
               f'<button class="uqbtn{" on" if _uov["color"] else ""}" data-k="color" '
               f'onclick="uniqTog({sid},\'color\',\'ov\')" title="контраст+цвет">🎨</button>'
               f'<button class="uqbtn{" on" if _uov["bw"] else ""}" data-k="bw" '
               f'onclick="uniqTog({sid},\'bw\',\'ov\')" title="чёрно-белое">⬜</button>'
               f'<span class="uqgrp" data-k="rot">⟳'
               + "".join(f'<button class="uqbtn{" on" if int(_uov["rot"])==r else ""}" '
                         f'onclick="uniqSet({sid},\'rot\',{r},\'ov\')">{r}°</button>'
                         for r in (1, 2, 3))
               + f'</span>'
               f'<span class="uqgrp" data-k="zoom">✂️'
               + "".join(f'<button class="uqbtn{" on" if abs(float(_uov["zoom"])-z)<0.01 else ""}" '
                         f'onclick="uniqSet({sid},\'zoom\',{z},\'ov\')">{z}×</button>'
                         for z in (1.1, 1.2, 1.3))
               + f'</span>'
               f'<button class="uqbtn" onclick="uniqReset({sid},\'ov\')" title="снять всё">сброс</button>'
               f'<i id="umov{sid}">{_uniq_summary(_uov)}</i></span></div>') if (live and ph) else ''
            f'<div class="ovrow ovfind">'
            f'<input type="text" id="ovq{sid}" placeholder="или найди в интернете — что именно, словами" '
            f'onfocus="if(/^[⚠🔴]/.test(this.value))this.value=\'\'" '
            f'onkeydown="if(event.key===\'Enter\')ovOpts({sid})">'
            f'<button type="button" onclick="ovOpts({sid})">🔎 найти</button>'
            f'<button type="button" class="mic" data-mic="ovq{sid}" title="держи и говори" '
            f'onpointerdown="micStart(event,\'ovq{sid}\',\'ovfile{sid}\',()=>ovOpts({sid}))" '
            f'onpointerup="micStop()" onpointercancel="micStop()">🎤</button></div>'
            f'<div class="opts" id="opts_ov{sid}" hidden></div>'
            f'<span class="ovfile" id="ovfile{sid}">{os.path.basename(ph) or "— фото не выбрано —"}</span>'
            f'<div class="ovrow"><span>звук</span>'
            f'<select id="ovsnd{sid}" onchange="ovSave({sid})">{opts}</select></div>'
            f'<div class="ovrow"><span>форма</span>'
            f'<input type="hidden" id="ovshape{sid}" value="{ov_cur.get("shape","rect")}">'
            f'<div class="ovshapes" id="ovsh{sid}">'
            + "".join(f'<button type="button" class="{"on" if ov_cur.get("shape","rect")==v else ""}" '
                      f'onclick="ovShape({sid},\'{v}\')" title="{lbl}">{sym}</button>'
                      for v, lbl, sym in (("rect", "прямоугольник", "▭"),
                                          ("rounded", "скруглённые углы", "▢"),
                                          ("square", "квадрат", "◼"),
                                          ("circle", "круг", "●")))
            + f'</div></div>'
            f'<div class="ovrow"><span>место</span><div class="ovgrid" id="ovpgrid{sid}">'
            + "".join(f'<button type="button" class="{"on" if _ovcell_cur(ov_cur, _ov_anchor)==c else ""}" '
                      f'onclick="ovPhotoPos({sid},\'{c}\')" title="{c}">{sym}</button>'
                      for c, sym in (("tl", "↖"), ("tc", "↑"), ("tr", "↗"),
                                     ("ml", "←"), ("mc", "•"), ("mr", "→"),
                                     ("bl", "↙"), ("bc", "↓"), ("br", "↘")))
            + f'</div></div>'
            f'<div class="ovrow"><span>масштаб</span>'
            f'<input type="number" id="ovscale{sid}" min="0.4" max="2.4" step="0.1" '
            f'value="{ov_cur.get("scale",1.0)}" onchange="ovSave({sid})"> ×</div>'
            f'<div class="ovrow"><span>появл., сек</span>'
            f'<input type="number" id="ovat{sid}" min="0" max="{d:.1f}" step="0.2" '
            f'value="{at_val}" onchange="ovSave({sid})" '
            f'title="через сколько секунд после старта сцены всплывашка въезжает; держится до конца сцены"></div>'
            f'<div class="ovbtns">'
            f'<button class="ovok" id="ovok{sid}" onclick="ovApprove({sid})">✓ Утвердить</button>'
            f'<button class="ovclear" onclick="ovClear({sid})">✕ Убрать</button>'
            f'</div>'
            f'<span class="ovmsg" id="ovmsg{sid}"></span>'
            f'</div>'
            f'<div class="ovdone" id="ovdone{sid}"{"" if _ov_approved else " hidden"}>✓ всплывашка утверждена '
            f'<span class="ovpos" id="ovpos{sid}"></span> '
            f'<button class="ovedit" onclick="ovEdit({sid})">изменить</button>'
            f'<button class="rjgood" onclick="rjAsk({sid},&quot;overlay&quot;,&quot;keep&quot;)" title="сказать, чем кадр хорош — по желанию">💬</button></div>'
            f'</div>'
        )
        # --- ОТДЕЛЬНАЯ панель: ТЕКСТ поверх кадра (своя кнопка «➕ текст») ---
        _txt_approved = bool(_tw.get("approved")) and _text_active
        txt_ui = (
            f'<div class="txtwrap{" ok" if _txt_approved else ""}" id="txtwrap{sid}"'
            f'{"" if _text_active else " hidden"}>'
            f'<div class="ovhead">🅰 ТЕКСТ поверх кадра — впиши слово, выбери цвет и место. '
            f'Своя всплывашка, работает вместе с фото.</div>'
            f'<div class="ovpanel"{" hidden" if _txt_approved else ""}>'
            f'<input class="ovtxtin" id="ovtxt{sid}" placeholder="СЛОВО: БЕГИТЕ, КАРАУЛ…" '
            f'value="{_twords}" oninput="this.value=this.value.toUpperCase()" '
            f'onkeydown="if(event.key===\'Enter\')ovTextSave({sid})" onchange="ovTextSave({sid})">'
            f'<div class="ovcolrow" id="ovcol{sid}">'
            + "".join(f'<button class="ovcol-{c}{" on" if _tcol==c else ""}" '
                      f'onclick="ovTextColor({sid},\'{c}\')">{lbl}</button>'
                      for c, lbl in (("white", "БЕЛЫЙ"), ("yellow", "ЖЁЛТЫЙ"), ("red", "КРАСНЫЙ")))
            + f'</div>'
            f'<div class="ovrow"><span>место</span><div class="ovgrid" id="ovgrid{sid}">'
            + "".join(f'<button class="{"on" if _tpos==p else ""}" '
                      f'onclick="ovTextPos({sid},\'{p}\')" title="{p}">{sym}</button>'
                      for p, sym in (("tl", "↖"), ("tc", "↑"), ("tr", "↗"),
                                     ("ml", "←"), ("mc", "•"), ("mr", "→"),
                                     ("bl", "↙"), ("bc", "↓"), ("br", "↘")))
            + f'</div></div>'
            f'<div class="ovrow"><span>звук</span>'
            f'<select id="ovtsnd{sid}" onchange="ovTextSave({sid})">{_topts}</select></div>'
            f'<div class="ovrow"><span>масштаб</span>'
            f'<input type="number" id="ovtscale{sid}" min="0.4" max="2.4" step="0.1" '
            f'value="{_tw.get("scale",1.0)}" onchange="ovTextSave({sid})"> ×</div>'
            f'<div class="ovrow"><span>появл., сек</span>'
            f'<input type="number" id="ovtat{sid}" min="0" max="{d:.1f}" step="0.2" '
            f'value="{_tw.get("at",2.0)}" onchange="ovTextSave({sid})"></div>'
            f'<div class="ovbtns">'
            f'<button class="ovok" id="txtok{sid}" onclick="txtApprove({sid})">✓ Утвердить</button>'
            f'<button class="ovclear" onclick="ovTextClear({sid})">✕ Убрать</button>'
            f'</div>'
            f'<span class="ovmsg" id="txtmsg{sid}"></span>'
            f'</div>'
            f'<div class="ovdone" id="txtdone{sid}"{"" if _txt_approved else " hidden"}>✓ текст утверждён '
            f'<button class="rjgood" onclick="rjAsk({sid},&quot;text&quot;,&quot;keep&quot;)" title="сказать, чем хорош — по желанию">💬</button> '
            f'<button class="ovedit" onclick="txtEdit({sid})">изменить</button></div>'
            f'</div>'
        )
    else:
        ov_ui = txt_ui = ""

    # --- бегущая строка (ticker) — отдельная, необязательная панель -------
    # Полностью изолирована: читает только tickers (из ticker.json), ничего
    # общего с overlays.json. Если для этой сцены нет записи в ticker.json
    # (обычный случай, когда фича вообще не включена на этом проекте) —
    # панель не рендерится, карточка выглядит ровно как раньше. Любая
    # ошибка внутри — тихо гасится, остальная карточка не страдает.
    tk_ui = ""
    try:
        tickers = tickers or {}
        tk_cur = tickers.get(str(sid), {})
        tk_text = str(tk_cur.get("text", "")).strip()
        tk_active = bool(tk_cur)
        if live and tk_active:
            tk_approved = bool(tk_cur.get("approved"))
            tk_ui = (
                f'<div class="tkwrap{" ok" if tk_approved else ""}" id="tkwrap{sid}">'
                f'<div class="ovhead">📰 БЕГУЩАЯ СТРОКА — короткий заголовок вверху кадра '
                f'(отдельно от всплывашек, может не входить в финал — смотря что решишь).</div>'
                f'<div class="ovpanel" id="tkp{sid}"{" hidden" if tk_approved else ""}>'
                f'<input class="ovtxtin" id="tktxt{sid}" placeholder="короткий заголовок…" '
                f'value="{tk_text}" oninput="this.value=this.value.toUpperCase()" '
                f'onkeydown="if(event.key===\'Enter\')tkSave({sid})" onchange="tkSave({sid})">'
                f'<div class="ovbtns">'
                f'<button class="ovok" id="tkok{sid}" onclick="tkApprove({sid})">✓ Утвердить</button>'
                f'<button class="ovclear" onclick="tkClear({sid})">✕ Убрать</button>'
                f'</div>'
                f'<span class="ovmsg" id="tkmsg{sid}"></span>'
                f'</div>'
                f'<div class="ovdone" id="tkdone{sid}"{"" if tk_approved else " hidden"}>✓ строка утверждена '
                f'<button class="ovedit" onclick="tkEdit({sid})">изменить</button></div>'
                f'</div>'
            )
    except Exception:
        tk_ui = ""

    card_cls = "card needup" if need_reason else "card"
    return f"""<figure class="{card_cls}" data-id="{sid}">
  <div class="{thumb_cls}" id="t{sid}">{thumb_inner}{ov_badge}<div class="ovmark" id="ovmark{sid}" hidden><img id="ovmarkimg{sid}" alt=""></div><div class="txtmark" id="txtmark{sid}" hidden><img id="txtmarkimg{sid}" alt=""></div><div class="pvbox" id="pvbox{sid}" hidden></div></div>
  <figcaption>
    <div class="meta">СЦЕНА {sid:02d} · {fmt(t)}–{fmt(t + d)} · {d:.1f}с</div>
    <div class="srcq">{srcq}</div>
    {need_row}
    <p class="txt">{s['text']}</p>
    <div class="acts">
      {keep_btn}
      {mirror_btn}
      {zoom_btn}
      {uniq_block}
      {preview_btn}
      {upload_btn}
      {ban_btn}
      {ov_add_btn}
    </div>
    {img_search}
    {ov_ui}
    {txt_ui}
    {tk_ui}
    <textarea class="note" id="n{sid}" placeholder="что поставить в этой сцене — опиши словами"
      oninput="save()"></textarea>
  </figcaption>
</figure>"""


def build_page(scenes, project, live, images_dir):
    total = sum(s["duration_sec"] for s in scenes)
    needs = load_needs()
    overlays = load_overlays()
    tickers = load_ticker()
    sfx = sfx_list()
    cards, t = [], 0.0
    for s in scenes:
        sid, d = s["id"], s["duration_sec"]
        try:
            cards.append(card_html(s, t, live, images_dir, needs, overlays, sfx, tickers))
        except Exception as e:
            # DASHBOARD INTERFACE CONTRACT (user, 2026-09-16, hard rule): a
            # card must NEVER render without its button row, no matter what
            # broke — a bad asset, a stale overlays.json path, anything. If
            # the full card_html build throws for any reason, fall back to
            # a minimal card that still carries the complete standard
            # control set, so "missing buttons" cannot happen even in a
            # case nobody anticipated. Fix the real cause separately — this
            # is a safety net, not a substitute for that.
            up = (f'<label class="up" id="up{sid}">⬆️ Загрузить своё'
                  f'<input type="file" accept="image/*,video/*" '
                  f'onchange="upload({sid},this)"></label>') if live else ""
            pv = (f'<button class="pvbtn" id="pvbtn{sid}" onclick="previewScene({sid},event)" '
                  f'title="собрать и посмотреть этот кусок как в финале">▶ превью</button>'
                  ) if live else ""
            ovadd = (f'<button id="ovadd{sid}" onclick="ovAdd({sid},{d:.1f})">➕ всплывашка</button>'
                     f'<button id="txtadd{sid}" onclick="txtAdd({sid})">➕ текст</button>') if live else ""
            search = (f'<div class="ovrow ovfind imgfind">'
                      f'<input type="text" id="imgq{sid}" placeholder="найти кадр в интернете — ключевые слова" '
                      f'onkeydown="if(event.key===\'Enter\')imgOpts({sid})">'
                      f'<button type="button" onclick="imgOpts({sid})">🔎 найти</button>'
                      f'<div class="opts" id="opts_img{sid}" hidden></div></div>') if live else ""
            cards.append(f"""<figure class="card cardbroken" data-id="{sid}">
  <div class="thumb failed" id="t{sid}"><span class="wait">⚠️ ошибка рендера карточки: {str(e)[:120]}</span>
  <span class="num">{sid:02d}</span></div>
  <figcaption>
    <div class="meta">СЦЕНА {sid:02d} · {fmt(t)}–{fmt(t + d)} · {d:.1f}с</div>
    <p class="txt">{s.get('text','')}</p>
    <div class="acts">{pv}{up}{ovadd}</div>
    {search}
    <textarea class="note" id="n{sid}" placeholder="что поставить в этой сцене"></textarea>
  </figcaption>
</figure>""")
        t += s["duration_sec"]
    need_n = len(needs)

    poll = ""
    if live:
        poll = """
// Всплывашки, которые пользователь только что убрал ✕ на этой вкладке — не
// давать poll() снова их открыть, если его собственный /state запрос успел
// улететь ДО клика и прилетает обратно ПОСЛЕ него с устаревшим ov.photo
// (сеть не гарантирует порядок ответов). Раньше это требовало второго клика
// «Убрать», потому что первый убирал панель, а опоздавший poll тут же её
// возвращал (user, 2026-09-22, "два раза приходится нажимать"). Снимаем
// пометку, как только сам poll подтвердит, что сервер уже не отдаёт photo.
const _justCleared = new Set();
async function poll(){
  try{
    const r = await fetch('state?_='+Date.now());
    const j = await r.json();
    let done = 0;
    const need = j.needs || {};
    j.scenes.forEach(sc => {
      const t = document.getElementById('t'+sc.id);
      if(!t) return;
      if(sc.status === 'failed'){ t.className = 'thumb failed'; }
      else if(sc.thumb){
        done++;
        const img = document.getElementById('i'+sc.id);
        const url = sc.thumb + '?v=' + sc.v;
        if(img.getAttribute('src') !== url){ img.src = url; }
        t.className = 'thumb ready';
        const b = document.getElementById('b'+sc.id);
        if(b && sc.badge){ b.textContent = sc.badge_label; b.className = 'badge ' + sc.badge; }
      }
      // needs-your-photo flag (server drops the id the moment you upload one)
      const nb = document.getElementById('need'+sc.id);
      const nr = document.getElementById('needr'+sc.id);
      const card = t.closest('.card');
      const reason = need[String(sc.id)];
      if(nb){ nb.hidden = !reason; }
      if(nr){ nr.hidden = !reason; if(reason) nr.textContent = '⬆️ загрузи: ' + reason; }
      if(card){ card.classList.toggle('needup', !!reason); }
      // всплывашка: поллинг ТОЛЬКО открывает панель (когда появились данные),
      // НИКОГДА не прячет — прячет только пользователь кнопкой ✕ (user 2026-09-08).
      const ov = (j.overlays || {})[String(sc.id)];
      const tOn = !!(ov && ov.text && (ov.text.words || ov.text.text));
      const pOn = !!(ov && (ov.photo || !tOn));
      if(!pOn) _justCleared.delete(sc.id);   // сервер догнал — снимаем пометку
      const ow = document.getElementById('ovwrap'+sc.id);
      if(ow && ow.hidden && pOn && !_justCleared.has(sc.id)){ ow.hidden = false; }
      const owOpen = ow && !ow.hidden;
      const ab = document.getElementById('ovadd'+sc.id);
      if(ab){ ab.hidden = pOn || owOpen; }
      const tw = document.getElementById('txtwrap'+sc.id);
      if(tw && tw.hidden && tOn){ tw.hidden = false; }
      const twOpen = tw && !tw.hidden;
      const tb = document.getElementById('txtadd'+sc.id);
      if(tb){ tb.hidden = tOn || twOpen; }
      const ovb = document.getElementById('ovb'+sc.id);
      if(ovb) ovb.hidden = !ov && !twOpen;
      const pv = document.getElementById('ovprev'+sc.id);
      if(pv && ov && ov.photo){
        const u = (ov._photo_prev || ov.photo) + '?t=' + (ov._v || 0);
        if(pv.getAttribute('src') !== u){ pv.src = u; pv.hidden = false; }
      }
      // мини-превью самой всплывашки — там, где она выедет в кадре
      const mk = document.getElementById('ovmark'+sc.id);
      if(mk){
        const P = ov && ov.photo && ov.pos ? ov.pos : null;
        mk.hidden = !P;
        if(P){
          mk.style.left = (P.xf*100)+'%'; mk.style.top = (P.yf*100)+'%';
          mk.style.width = (P.wf*100)+'%'; mk.style.height = (P.hf*100)+'%';
          mk.style.borderRadius = (P.shape === 'circle') ? '50%'
            : (P.shape === 'rounded') ? '14%' : '3px';
          mk.classList.toggle('solid', !!(ow && ow.classList.contains('ok')));
          const mi = document.getElementById('ovmarkimg'+sc.id);
          const u = (ov._photo_prev || ov.photo) + '?t=' + (ov._v || 0);
          if(mi && mi.getAttribute('src') !== u) mi.src = u;
        }
      }
      // мини-превью текст-всплывашки
      const tmk = document.getElementById('txtmark'+sc.id);
      if(tmk){
        const T = ov && ov._tpos && ov._tpng ? ov._tpos : null;
        tmk.hidden = !T;
        if(T){
          tmk.style.left=(T.xf*100)+'%'; tmk.style.top=(T.yf*100)+'%';
          tmk.style.width=(T.wf*100)+'%'; tmk.style.height=(T.hf*100)+'%';
          const tmi=document.getElementById('txtmarkimg'+sc.id);
          const tu=ov._tpng+'?t='+(ov._tv||0);
          if(tmi && tmi.getAttribute('src')!==tu) tmi.src=tu;
        }
      }
      const posEl = document.getElementById('ovpos'+sc.id);
      if(posEl && ov && ov.pos){
        const SH = {circle:'круг', rounded:'скруглённый', square:'квадрат', rect:''};
        const s = ov.pos.scale && ov.pos.scale !== 1 ? (', ×' + ov.pos.scale) : '';
        posEl.textContent = '· ' + ov.pos.size.toUpperCase() + s
          + (SH[ov.pos.shape] ? ', ' + SH[ov.pos.shape] : '')
          + ', выезжает ' + ov.pos.style_ru;
      }
    });
    const bar = document.getElementById('progi');
    bar.style.width = (100*done/j.scenes.length) + '%';
    document.getElementById('pgtxt').textContent = done + ' / ' + j.scenes.length + ' кадров';
    if(j.fetch_done && done + j.failed >= j.scenes.length){
      document.getElementById('pgtxt').textContent = '✓ все кадры на месте' + (j.failed? ' ('+j.failed+' без кадра)':'');
    }
    const nk = Object.keys(need);
    const nj = document.getElementById('needjump');
    if(nj){
      nj.hidden = nk.length === 0;
      nj.textContent = '⚠️ нужно твоё фото: ' + nk.length;
      nj.dataset.first = nk.length ? Math.min.apply(null, nk.map(Number)) : '';
    }
  }catch(e){}
  setTimeout(poll, 2500);
}
poll();
"""
    progress = ('<div id="prog"><i id="progi"></i></div>'
                '<span class="sub" id="pgtxt">загрузка…</span>') if live else ""

    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Предпросмотр — {project}</title>
<style>{CSS}</style></head><body>
<header>
  <h1>Предпросмотр видеоряда{' · LIVE' if live else ''}</h1>
  <span class="sub">{project} · {len(scenes)} сцен · {fmt(total)}</span>
  {progress}
  <span class="spacer"></span>
  <span class="sub">На каждой карточке: <b>✏️ Изменить кадр</b> — впиши что поставить ·
    <b>🔍 Искать в интернете</b> — впиши что найти. Потом →</span>
  <span class="sub">отмечено: <span id="count">0</span></span>
  <button id="needjump" onclick="jumpNeed()"{'' if need_n else ' hidden'} data-first="{min(int(k) for k in needs) if needs else ''}">⚠️ нужно твоё фото: {need_n}</button>
  <button onclick="showList()">📋 Показать правки для чата</button>
  <button onclick="clearAll()">Сбросить</button>
</header>
<div class="grid">
{''.join(cards)}
</div>
<dialog id="dlg">
  <div style="margin-bottom:8px">Вставь это в чат:</div>
  <textarea id="listout" readonly></textarea>
  <div class="row"><button id="copybtn" onclick="copyList()">Копировать</button>
  <button onclick="document.getElementById('dlg').close()">Закрыть</button></div>
</dialog>
<script>
const KEY = "review-{project}";
let state = {{}};
try {{ state = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch(e) {{}}
const WEB = "искать в интернете: ";
function render(){{
  let n = 0;
  document.querySelectorAll(".card").forEach(c => {{
    const id = c.dataset.id, v = state[id], on = !!v;
    c.classList.toggle("marked", on);
    const ta = c.querySelector(".note");
    if(on){{
      n++;
      if(typeof v === "string" && ta.value !== v) ta.value = v;
    }} else if(ta.value){{ ta.value = ""; }}
    const isWeb = typeof v === "string" && v.toLowerCase().startsWith(WEB);
    const chg = document.getElementById("chg"+id), web = document.getElementById("web"+id);
    if(chg) chg.classList.toggle("on", on && !isWeb);
    if(web) web.classList.toggle("on", isWeb);
  }});
  document.getElementById("count").textContent = n;
}}
function save(){{
  document.querySelectorAll(".card").forEach(c => {{
    const id = c.dataset.id;
    if(!state[id]) return;               // only activated cards keep a note
    const val = document.getElementById("n"+id).value;
    state[id] = val.trim() ? val : true;
  }});
  saveOnly(); render();
}}
function saveOnly(){{ try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch(e) {{}} }}
function mark(id){{ if(state[id]) delete state[id]; else state[id] = true; render(); saveOnly(); }}
function clearAll(){{ state = {{}}; try{{ localStorage.removeItem(KEY); }}catch(e){{}} render(); }}
function showList(){{
  save();
  const rows = Object.keys(state).map(Number).sort((a,b)=>a-b).map(id => {{
    const v = state[id];
    return "сцена " + id + (typeof v === "string" && v.trim() ? " — " + v.trim() : "");
  }});
  document.getElementById("listout").value = rows.length ? rows.join("\\n") : "(ничего не отмечено)";
  document.getElementById("dlg").showModal();
}}
function jumpNeed(){{
  const b = document.getElementById("needjump");
  let id = b && b.dataset.first;
  if(!id){{ const c = document.querySelector(".card.needup"); if(c) id = c.dataset.id; }}
  const card = id && document.querySelector('.card[data-id="'+id+'"]');
  if(card) card.scrollIntoView({{behavior:"smooth", block:"center"}});
}}
async function copyList(){{
  const t = document.getElementById("listout");
  const txt = t.value;
  const btn = document.getElementById("copybtn");
  let ok = false;
  try {{ await navigator.clipboard.writeText(txt); ok = true; }} catch(e) {{}}
  if(!ok){{
    t.removeAttribute("readonly"); t.focus(); t.select(); t.setSelectionRange(0, 999999);
    try {{ ok = document.execCommand("copy"); }} catch(e) {{}}
    t.setAttribute("readonly", "");
  }}
  if(btn){{
    btn.textContent = ok ? "Скопировано ✓" : "Выдели вручную и Ctrl+C";
    setTimeout(() => {{ btn.textContent = "Копировать"; }}, 2200);
  }}
}}
async function keepImg(id){{
  const b = document.getElementById("keep"+id); if(b) b.textContent = "…";
  try{{
    const r = await fetch("keepimg?id="+id, {{method:"POST"}});
    if(r.ok){{
      const card = document.querySelector('.card[data-id="'+id+'"]');
      if(card) card.classList.remove("needup");
      const nb = document.getElementById("need"+id); if(nb) nb.hidden = true;
      const nr = document.getElementById("needr"+id); if(nr) nr.hidden = true;
      if(b) b.remove();
    }} else if(b) b.textContent = "✓ Оставить это фото";
  }}catch(e){{ if(b) b.textContent = "✓ Оставить это фото"; }}
}}
async function banAsset(id){{
  const daysStr = prompt("Убрать на сколько дней? (пусто = навсегда)", "10");
  if(daysStr === null) return;   // отмена
  const days = daysStr.trim() === "" ? null : parseInt(daysStr.trim(), 10);
  const ans = await rjAsk(id, "scene", "ban");
  const why = (ans.note || RJ_LABEL[ans.reason] || "").trim();
  const b = document.getElementById("ban"+id); if(b) b.textContent = "…";
  const origLabel = "🚫 Не использовать";
  try{{
    const r = await fetch("ban_asset?id="+id, {{method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body: JSON.stringify({{reason: why, days: days}})}});
    if(r.ok){{
      const t = document.getElementById("t"+id);
      if(t){{ t.className = "thumb failed"; }}
      const img = document.getElementById("i"+id); if(img) img.removeAttribute("src");
      const card = document.querySelector('.card[data-id="'+id+'"]');
      if(card) card.classList.add("needup");
      const nb = document.getElementById("need"+id); if(nb) nb.hidden = false;
      const nr = document.getElementById("needr"+id);
      const untilMsg = days ? ("файл в бане на " + days + " дн., нужна замена")
                             : "файл забанен навсегда, нужна замена";
      if(nr){{ nr.hidden = false; nr.textContent = "⬆️ загрузи: " + untilMsg; }}
      if(b) b.remove();
    }} else if(b) b.textContent = origLabel;
  }}catch(e){{ if(b) b.textContent = origLabel; }}
}}
async function mirrorImg(id){{
  const b = document.getElementById("mir"+id); const o = b ? b.textContent : "";
  if(b){{ b.textContent = "…"; b.disabled = true; }}
  try{{
    const r = await fetch("mirror?id="+id, {{method:"POST"}});
    if(b) b.textContent = r.ok ? "🔄 отзеркалено ✓" : "✗";
    if(r.ok){{
      const im = document.getElementById("i"+id);
      if(im && im.src) im.src = im.src.split("?")[0] + "?t=" + Date.now();
    }}
  }}catch(e){{ if(b) b.textContent = "✗"; }}
  if(b) setTimeout(()=>{{ b.textContent = o || "🔄 Отзеркалить"; b.disabled = false; }}, 1800);
}}
async function zoomImg(id, f){{
  const tag = document.getElementById("zm"+id);
  const wrap = document.getElementById("zw"+id);
  if(wrap) wrap.querySelectorAll("button").forEach(x=>x.disabled=true);
  if(tag) tag.textContent = " …";
  try{{
    const r = await fetch("zoomimg?id="+id+"&f="+f, {{method:"POST"}});
    if(tag) tag.textContent = r.ok ? (f<=1.001 ? " оригинал ✓" : " "+f+"× ✓") : " ✗";
    if(r.ok){{
      const im = document.getElementById("i"+id);
      if(im && im.src) im.src = im.src.split("?")[0] + "?t=" + Date.now();
    }}
  }}catch(e){{ if(tag) tag.textContent = " ✗"; }}
  if(wrap) wrap.querySelectorAll("button").forEach(x=>x.disabled=false);
}}
async function uniqApply(id, params, t){{
  // t === "ov" — та же обработка, но для фото всплывашки (папка overlays/)
  const sfx = (t === "ov") ? "ov" : "";
  const wrap = document.getElementById("uw"+sfx+id);
  const tag = document.getElementById("um"+sfx+id);
  if(wrap) wrap.querySelectorAll("button").forEach(x=>x.disabled=true);
  const prev = tag ? tag.textContent : "";
  if(tag) tag.textContent = " …";
  try{{
    const r = await fetch("uniq?id="+id+((t==="ov")?"&t=ov":"")+"&"+params, {{method:"POST"}});
    const j = r.ok ? await r.json() : null;
    if(j){{
      if(tag) tag.textContent = j.summary || "";
      if(t === "ov"){{                       // перерисовать превьюшку всплывашки
        const pv = document.getElementById("ovprev"+id);
        if(pv && pv.src) pv.src = pv.src.split("?")[0] + "?v=" + Date.now();
      }}
      // подсветить активные кнопки по факту серверного состояния
      if(wrap){{
        wrap.querySelectorAll('button[data-k]').forEach(b=>{{
          const k=b.dataset.k; b.classList.toggle("on", !!j.state[k]);
        }});
        wrap.querySelectorAll('.uqgrp[data-k]').forEach(g=>{{
          const k=g.dataset.k;
          g.querySelectorAll('button').forEach(b=>{{
            const v=parseFloat(b.textContent);
            b.classList.toggle("on", Math.abs((j.state[k]||(k==='zoom'?1:0))-v)<0.01 && v>0.001 && (k!=='zoom'||v>1.001));
          }});
        }});
      }}
      const im = document.getElementById("i"+id);
      if(im && im.src) im.src = im.src.split("?")[0] + "?t=" + Date.now();
    }} else if(tag) tag.textContent = prev + " ✗";
  }}catch(e){{ if(tag) tag.textContent = prev + " ✗"; }}
  if(wrap) wrap.querySelectorAll("button").forEach(x=>x.disabled=false);
}}
function uniqTog(id, key, t){{ uniqApply(id, "toggle="+key, t); }}
function uniqSet(id, key, val, t){{ uniqApply(id, key+"="+val, t); }}
function uniqReset(id, t){{ uniqApply(id, "reset=1", t); }}
// ФОРМА ВСПЛЫВАШКИ КНОПКАМИ (user, 17.10: «не хочу этими списками морочиться»)
function ovShape(id, v){{
  const inp = document.getElementById("ovshape"+id);
  if(inp) inp.value = v;
  document.querySelectorAll("#ovsh"+id+" button").forEach(b=>
    b.classList.toggle("on", b.getAttribute("onclick").indexOf("'"+v+"'")>0));
  ovSave(id);
}}
async function previewScene(id, ev){{
  if(ev) ev.stopPropagation();
  const b=document.getElementById("pvbtn"+id);
  if(b){{ b.textContent="⏳ собираю… (может занять до минуты)"; b.disabled=true; }}
  try{{
    const r=await fetch("preview?id="+id,{{method:"POST"}});
    const txt=await r.text();
    let j=null; try{{ j=JSON.parse(txt); }}catch(e){{}}
    if(r.ok && j && j.url){{
      const box=document.getElementById("pvbox"+id);
      box.hidden=false;
      box.onclick=(e)=>e.stopPropagation();
      box.innerHTML='<video src="'+j.url+'?t='+Date.now()+'" controls autoplay playsinline></video>'
        +'<button class="pvclose" onclick="pvClose('+id+',event)">✕ закрыть</button>';
      if(b) b.textContent="▶ пересобрать превью";
    }} else {{
      if(b) b.textContent="✗ "+(txt||"не собралось").slice(0,40);
      console.warn("preview fail", r.status, txt);
    }}
  }}catch(e){{ if(b) b.textContent="✗ ошибка сети"; }}
  if(b) b.disabled=false;
}}
function pvClose(id, ev){{ if(ev) ev.stopPropagation();
  const box=document.getElementById("pvbox"+id);
  if(box){{ box.hidden=true; box.innerHTML=""; }}
  const b=document.getElementById("pvbtn"+id); if(b) b.textContent="▶ превью";
}}
async function mirrorOv(id){{
  const b = document.getElementById("mirov"+id); const o = b ? b.textContent : "";
  if(b){{ b.textContent = "…"; b.disabled = true; }}
  try{{
    const r = await fetch("mirror_ov?id="+id, {{method:"POST"}});
    if(b) b.textContent = r.ok ? "🔄 ✓" : "✗";
    if(r.ok){{
      const pv = document.getElementById("ovprev"+id);
      if(pv && pv.src) pv.src = pv.src.split("?")[0] + "?t=" + Date.now();
    }}
  }}catch(e){{ if(b) b.textContent = "✗"; }}
  if(b) setTimeout(()=>{{ b.textContent = o || "🔄 отзеркалить"; b.disabled = false; }}, 1500);
}}
async function upload(id, inp){{
  const f = inp.files[0]; if(!f) return;
  const lbl = document.getElementById("up"+id); const orig = lbl.textContent;
  lbl.textContent = "… загрузка";
  try{{
    const r = await fetch("upload?id="+id, {{method:"POST",
      headers:{{"X-Filename": encodeURIComponent(f.name)}}, body: f}});
    lbl.textContent = r.ok ? "✓ загружено" : "✗ не вышло";
  }}catch(e){{ lbl.textContent = "✗ не вышло"; }}
  setTimeout(()=>{{ lbl.textContent = orig; inp.value = ""; }}, 2600);
}}
async function ovSave(id){{
  const snd = document.getElementById("ovsnd"+id).value;
  const at  = parseFloat(document.getElementById("ovat"+id).value || "0");
  const shEl = document.getElementById("ovshape"+id);
  const shape = shEl ? shEl.value : "rect";
  const scEl = document.getElementById("ovscale"+id);
  const scale = scEl ? parseFloat(scEl.value || "1") : 1;
  const m = document.getElementById("ovmsg"+id); m.textContent = "…";
  try{{
    const r = await fetch("overlay?id="+id, {{method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body: JSON.stringify({{sound: snd, at: at, shape: shape, scale: scale}})}});
    m.textContent = r.ok ? "сохранено ✓" : "ошибка";
  }}catch(e){{ m.textContent = "ошибка"; }}
  setTimeout(()=>{{ m.textContent = ""; }}, 1800);
}}
function _ovTcolor(id){{
  const b = document.querySelector("#ovcol"+id+" button.on");
  if(!b) return "white";
  if(b.classList.contains("ovcol-yellow")) return "yellow";
  if(b.classList.contains("ovcol-red")) return "red";
  return "white";
}}
function txtAdd(id){{
  const w=document.getElementById("txtwrap"+id); if(w){{ w.hidden=false; w.dataset.touched="1"; }}
  const b=document.getElementById("txtadd"+id); if(b) b.hidden=true;
  const inp=document.getElementById("ovtxt"+id); if(inp) inp.focus();
}}
async function ovTextSave(id, approvedVal){{
  const txt = (document.getElementById("ovtxt"+id).value||"").trim();
  if(!txt) return;
  const pb = document.querySelector("#ovgrid"+id+" button.on");
  const body = {{
    words: txt, color: _ovTcolor(id),
    pos: pb ? pb.getAttribute("title") : "bc",
    sound: (document.getElementById("ovtsnd"+id)||{{}}).value || "pop",
    at: parseFloat((document.getElementById("ovtat"+id)||{{}}).value || "2"),
    scale: parseFloat((document.getElementById("ovtscale"+id)||{{}}).value || "1")
  }};
  if(approvedVal !== undefined) body.approved = approvedVal;
  const m=document.getElementById("txtmsg"+id); if(m) m.textContent="…";
  try{{
    const r=await fetch("overlay_text?id="+id,{{method:"POST",
      headers:{{"Content-Type":"application/json"}},body:JSON.stringify(body)}});
    if(m) m.textContent = r.ok ? "сохранено ✓" : "ошибка";
    if(r.ok){{
      const mk=document.getElementById("txtmark"+id), mi=document.getElementById("txtmarkimg"+id);
      if(mk) mk.hidden=false;
      if(mi) mi.src="overlays/scene_"+String(id).padStart(3,"0")+".text.png?t="+Date.now();
    }}
  }}catch(e){{ if(m) m.textContent="ошибка"; }}
  setTimeout(()=>{{ const mm=document.getElementById("txtmsg"+id); if(mm) mm.textContent=""; }},1600);
}}
function ovTextColor(id,c){{
  document.querySelectorAll("#ovcol"+id+" button").forEach(b=>
    b.classList.toggle("on", b.classList.contains("ovcol-"+c)));
  ovTextSave(id);
}}
async function ovPhotoPos(id,c){{
  // КЛЕТКА СХЕМЫ: первая буква — верх/середина/низ, вторая — лево/центр/право.
  // Одно нажатие = и горизонталь, и вертикаль, без списков (user, 17.10).
  document.querySelectorAll("#ovpgrid"+id+" button").forEach(b=>
    b.classList.toggle("on", b.getAttribute("title")===c));
  const V = {{t:"top", m:"middle", b:"bottom"}}[c[0]];
  const H = {{l:"left", c:"center", r:"right"}}[c[1]];
  const m = document.getElementById("ovmsg"+id); if(m) m.textContent = "…";
  try{{
    const r = await fetch("overlay?id="+id, {{method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body: JSON.stringify({{pos: H, anchor: V}})}});
    if(m) m.textContent = r.ok ? "сохранено ✓" : "ошибка";
  }}catch(e){{ if(m) m.textContent = "ошибка"; }}
  setTimeout(()=>{{ if(m) m.textContent = ""; }}, 1800);
}}
function ovTextPos(id,p){{
  document.querySelectorAll("#ovgrid"+id+" button").forEach(b=>
    b.classList.toggle("on", b.getAttribute("title")===p));
  ovTextSave(id);
}}
function txtApprove(id){{
  const w=document.getElementById("txtwrap"+id); if(!w) return;
  const inp=document.getElementById("ovtxt"+id);
  if(!(inp && inp.value.trim())){{ return; }}
  ovTextSave(id, true);
  w.classList.add("ok");
  const p=w.querySelector(".ovpanel"); if(p) p.hidden=true;
  const dn=document.getElementById("txtdone"+id); if(dn) dn.hidden=false;
}}
function txtEdit(id){{
  const w=document.getElementById("txtwrap"+id); if(!w) return;
  ovTextSave(id, false);
  w.classList.remove("ok");
  const p=w.querySelector(".ovpanel"); if(p) p.hidden=false;
  const dn=document.getElementById("txtdone"+id); if(dn) dn.hidden=true;
}}
async function ovTextClear(id){{
  try{{ await fetch("overlay_text?id="+id,{{method:"POST",
    headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{clear:1}})}}); }}catch(e){{}}
  const inp=document.getElementById("ovtxt"+id); if(inp) inp.value="";
  const w=document.getElementById("txtwrap"+id);
  if(w){{ w.hidden=true; w.classList.remove("ok"); delete w.dataset.touched;
    const p=w.querySelector(".ovpanel"); if(p) p.hidden=false;
    const dn=document.getElementById("txtdone"+id); if(dn) dn.hidden=true; }}
  const b=document.getElementById("txtadd"+id); if(b) b.hidden=false;
  const mk=document.getElementById("txtmark"+id); if(mk) mk.hidden=true;
  rjAsk(id, "text", "clear");
}}
// --- бегущая строка (ticker) — отдельная панель, свой роут /ticker -----
async function tkSave(id, approvedVal){{
  const inp = document.getElementById("tktxt"+id); if(!inp) return;
  const txt = (inp.value||"").trim();
  const body = {{text: txt}};
  if(approvedVal !== undefined) body.approved = approvedVal;
  const m = document.getElementById("tkmsg"+id); if(m) m.textContent = "…";
  try{{
    const r = await fetch("ticker?id="+id, {{method:"POST",
      headers:{{"Content-Type":"application/json"}}, body: JSON.stringify(body)}});
    if(m) m.textContent = r.ok ? "сохранено ✓" : "ошибка";
  }}catch(e){{ if(m) m.textContent = "ошибка"; }}
  setTimeout(()=>{{ const mm=document.getElementById("tkmsg"+id); if(mm) mm.textContent=""; }},1600);
}}
function tkApprove(id){{
  const inp = document.getElementById("tktxt"+id);
  if(!(inp && inp.value.trim())) return;
  tkSave(id, true);
  const w=document.getElementById("tkwrap"+id); if(w) w.classList.add("ok");
  const p=document.getElementById("tkp"+id); if(p) p.hidden=true;
  const dn=document.getElementById("tkdone"+id); if(dn) dn.hidden=false;
}}
function tkEdit(id){{
  tkSave(id, false);
  const w=document.getElementById("tkwrap"+id); if(w) w.classList.remove("ok");
  const p=document.getElementById("tkp"+id); if(p) p.hidden=false;
  const dn=document.getElementById("tkdone"+id); if(dn) dn.hidden=true;
}}
async function tkClear(id){{
  try{{ await fetch("ticker?id="+id,{{method:"POST",
    headers:{{"Content-Type":"application/json"}}, body: JSON.stringify({{clear:1}})}}); }}catch(e){{}}
  const w=document.getElementById("tkwrap"+id); if(w) w.remove();
}}
async function ovPhoto(id, inp){{
  const f = inp.files[0]; if(!f) return;
  const fn = document.getElementById("ovfile"+id); fn.textContent = "… загрузка";
  try{{
    const r = await fetch("overlay_photo?id="+id, {{method:"POST",
      headers:{{"X-Filename": encodeURIComponent(f.name)}}, body: f}});
    fn.textContent = r.ok ? f.name : "✗ не вышло";
    if(r.ok){{
      const pv = document.getElementById("ovprev"+id);
      pv.src = URL.createObjectURL(f); pv.hidden = false;
    }}
  }}catch(e){{ fn.textContent = "✗ не вышло"; }}
  inp.value = "";
}}
function ovApprove(id){{
  const pv = document.getElementById("ovprev"+id);
  if(!pv || pv.hidden || !pv.getAttribute("src")){{
    const m = document.getElementById("ovmsg"+id);
    if(m){{ m.textContent = "сначала фото — загрузи или найди"; setTimeout(()=>{{m.textContent="";}},2600); }}
    return;
  }}
  ovSave(id);
  fetch("overlay?id="+id, {{method:"POST", headers:{{"Content-Type":"application/json"}},
    body: JSON.stringify({{approved:true}})}});
  document.getElementById("ovp"+id).hidden = true;
  document.getElementById("ovdone"+id).hidden = false;
  document.getElementById("ovwrap"+id).classList.add("ok");
  const mk = document.getElementById("ovmark"+id); if(mk) mk.classList.add("solid");
}}
async function ovAdd(id, dur){{
  const r = await fetch("overlay?id="+id, {{method:"POST",
    headers:{{"Content-Type":"application/json"}},
    body: JSON.stringify({{create:1, at: Math.round(dur/2*10)/10}})}});
  if(r.ok){{
    const w = document.getElementById("ovwrap"+id);
    w.dataset.touched = ""; w.hidden = false;
    document.getElementById("ovp"+id).hidden = false;
    document.getElementById("ovdone"+id).hidden = true;
    const b = document.getElementById("ovadd"+id); if(b) b.hidden = true;
  }}
}}
// search -> show a grid of candidates -> click one to use it
async function _opts(id, q, gridId, msgId, target){{
  q = (q || "").trim(); if(!q || /^[⚠🔴]/.test(q)) return;
  const grid = document.getElementById(gridId);
  const msg = msgId ? document.getElementById(msgId) : null;
  const say = t => {{ if(msg) msg.textContent = t; }};
  grid.hidden = false; grid.innerHTML = '<span class="optnote">… ищу варианты</span>'; say("");
  try{{
    const r = await fetch("search_opts?id="+id, {{method:"POST",
      headers:{{"Content-Type":"application/json"}}, body: JSON.stringify({{q:q}})}});
    const j = await r.json().catch(()=>({{opts:[]}}));
    const opts = j.opts || [];
    if(!opts.length){{ grid.innerHTML = '<span class="optnote">ничего не нашлось — переформулируй</span>'; return; }}
    grid.innerHTML = '<span class="optnote">выбери кадр — ' + opts.length +
      (j.q_en ? ' · искал по-английски: «' + j.q_en + '»' : '') + '</span>';
    opts.forEach(o => {{
      const d = document.createElement("div");
      d.className = "opt" + (o.kind === "video" ? " vid" : "");
      d.title = o.src + " · " + o.w + "×" + o.h + (o.kind === "video" ? " · видео" : "");
      const im = document.createElement("img");
      im.loading = "lazy"; im.alt = "";
      im.onerror = () => {{
        if(im.src !== o.full && o.full && o.full !== o.thumb){{ im.src = o.full; }}   // try full-res
        else {{ d.classList.add("noimg"); im.remove(); d.insertAdjacentHTML("afterbegin", "<span class=q>?</span>"); }}
      }};
      im.src = o.thumb || o.full;
      d.appendChild(im);
      if(o.kind === "video") d.insertAdjacentHTML("beforeend", '<span class="vtag">▶</span>');
      d.onclick = () => pickOpt(id, o, gridId, msgId, target, d);
      grid.appendChild(d);
    }});
  }}catch(e){{ grid.innerHTML = '<span class="optnote">ошибка поиска</span>'; }}
}}
async function pickOpt(id, o, gridId, msgId, target, el){{
  const grid = document.getElementById(gridId);
  const msg = msgId ? document.getElementById(msgId) : null;
  grid.querySelectorAll(".opt").forEach(x => x.classList.remove("picked"));
  if(el) el.classList.add("picked");
  if(msg) msg.textContent = "… ставлю выбранный кадр";
  try{{
    const r = await fetch("pick_opt?id="+id, {{method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body: JSON.stringify({{full:o.full, kind:o.kind, target:target}})}});
    const j = await r.json().catch(()=>({{}}));
    if(r.ok && j.ok){{
      if(msg) msg.textContent = "✓ поставлено";
      setTimeout(() => {{ grid.hidden = true; grid.innerHTML = ""; }}, 900);
      if(target === "overlay"){{
        const pv = document.getElementById("ovprev"+id);
        if(pv){{ pv.src = o.thumb; pv.hidden = false; }}
      }}
    }} else {{ if(msg) msg.textContent = "✗ " + (j.reason || "не скачалось, выбери другой"); if(el) el.classList.remove("picked"); }}
  }}catch(e){{ if(msg) msg.textContent = "✗ ошибка"; }}
}}
function imgOpts(id){{ _opts(id, document.getElementById("imgq"+id).value, "opts_img"+id, "imgmsg"+id, "scene"); }}
function ovOpts(id){{ _opts(id, document.getElementById("ovq"+id).value, "opts_ov"+id, "ovfile"+id, "overlay"); }}
// push-to-talk: держишь кнопку и говоришь -> текст в поле вживую; отпустил ->
// стоп, текст применён, поиск сам. Статус и ошибки пишутся ПРЯМО В ПОЛЕ.
let _mic = null, _micRec = null, _micChunks = [], _micWantStop = false;
function micSrBad(){{ try{{ return localStorage.getItem("mic_sr_bad") === "1"; }}catch(e){{ return false; }} }}
function micMarkSrBad(){{ try{{ localStorage.setItem("mic_sr_bad", "1"); }}catch(e){{}} }}

/* ЗАПАСНОЙ ПУТЬ ДИКТОВКИ — запись в файл + локальный whisper на сервере
   (маршрут /voice). Зачем: браузерное распознавание (Web Speech API) живёт
   только в Chrome/Edge, требует интернета и регулярно отвечает ошибкой
   "network" — пользователь при этом видел «нужен Chrome» и оставался вообще
   без диктовки. Поймано дважды за 2026-10-16: в панели «почему убрал» откат
   в тот же день сделали, а в ПОИСКЕ ПО КАРТОЧКЕ его не было, и пользователь
   получил ту же стену второй раз. Здесь работает любой браузер и без сети,
   платой — несколько секунд ожидания после отпускания кнопки. */
function micFileStart(inpId, msgId, findFn){{
  const inp = document.getElementById(inpId);
  const btn = document.querySelector('[data-mic="'+inpId+'"]');
  const msg = msgId ? document.getElementById(msgId) : null;
  const show = (t) => {{ if(inp) inp.value = t; if(msg) msg.textContent = t; }};
  _micWantStop = false;
  if(!navigator.mediaDevices || !window.MediaRecorder){{ show("⚠ микрофон недоступен — напиши текстом"); return; }}
  navigator.mediaDevices.getUserMedia({{audio:true}}).then(function(stream){{
    const rec = new MediaRecorder(stream);
    _micRec = rec; _micChunks = [];
    rec.ondataavailable = function(e){{ if(e.data.size) _micChunks.push(e.data); }};
    rec.onstop = function(){{
      stream.getTracks().forEach(function(t){{ t.stop(); }});
      _micRec = null;
      if(btn) btn.textContent = "🎤";
      show("… расшифровываю на этой машине");
      const blob = new Blob(_micChunks, {{type:"audio/webm"}});
      const fr = new FileReader();
      fr.onloadend = async function(){{
        const b64 = String(fr.result).split(",")[1] || "";
        try{{
          const r = await fetch("voice", {{method:"POST",
            headers:{{"Content-Type":"application/json"}},
            body: JSON.stringify({{audio:b64}})}});
          const j = await r.json();
          const txt = (j.text || "").trim();
          if(txt){{
            if(inp) inp.value = txt;
            if(msg) msg.textContent = "ищу: " + txt;
            if(findFn) findFn();
          }} else show("не разобрал — скажи ещё раз или напиши");
        }}catch(e){{ show("расшифровка не ответила — напиши текстом"); }}
      }};
      fr.readAsDataURL(blob);
    }};
    rec.start();
    if(btn) btn.textContent = "🔴";
    show("🔴 говори, потом отпусти кнопку");
    if(_micWantStop){{ try{{ rec.stop(); }}catch(e){{}} }}   // отпустили раньше, чем включился микрофон
  }}).catch(function(){{ show("⚠ микрофон недоступен — напиши текстом"); }});
}}

function micStart(ev, inpId, msgId, findFn){{
  if(ev){{ try{{ ev.preventDefault(); ev.target.setPointerCapture(ev.pointerId); }}catch(e){{}} }}
  const inp = document.getElementById(inpId);
  const btn = document.querySelector('[data-mic="'+inpId+'"]');
  const msg = msgId ? document.getElementById(msgId) : null;
  const show = (t) => {{ if(inp) inp.value = t; if(msg) msg.textContent = t; }};
  const side = (t) => {{ if(msg) msg.textContent = t; }};
  if(_mic){{ try{{ _mic.abort(); }}catch(e){{}} _mic = null; }}
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(location.protocol === "file:"){{ show("⚠ открой http://localhost:8090/review.html — не файл"); return; }}
  /* Браузерное распознавание нет смысла даже пробовать, если оно здесь
     отсутствует, уже падало, или страница открыта по IP (там Web Speech
     запрещён как небезопасный контекст) — сразу локальный путь. */
  if(!SR || micSrBad() || !window.isSecureContext){{ micFileStart(inpId, msgId, findFn); return; }}
  let rec;
  try {{ rec = new SR(); }} catch(e) {{ micFileStart(inpId, msgId, findFn); return; }}
  rec.lang = "ru-RU"; rec.interimResults = true; rec.continuous = false;
  rec._final = ""; rec._done = false; rec._started = false; rec._stopWanted = false;
  const finish = () => {{
    if(rec._done) return; rec._done = true;
    if(btn) btn.textContent = "🎤";
    if(_mic === rec) _mic = null;
    const v = (inp && inp.value || "").trim();
    if(v && !v.startsWith("⚠") && !v.startsWith("🔴")){{ side("ищу: " + v); if(findFn) findFn(); }}
    else if(inp && inp.value.startsWith("🔴")) inp.value = "";
  }};
  rec.onstart = () => {{ rec._started = true; if(btn) btn.textContent = "🔴";
                         if(inp && !inp.value) inp.value = "🔴 говорите…"; side("🔴 говорите…");
                         if(rec._stopWanted) {{ try{{ rec.stop(); }}catch(e){{}} }} }};
  rec.onresult = (e) => {{
    let interim = "";
    for(let i = e.resultIndex; i < e.results.length; i++){{
      const tr = e.results[i][0].transcript;
      if(e.results[i].isFinal) rec._final += tr; else interim += tr;
    }}
    if(inp) inp.value = (rec._final + interim).replace(/\\s+/g, " ").trim();
  }};
  rec.onerror = (e) => {{
    rec._done = true; if(_mic === rec) _mic = null;
    if(btn) btn.textContent = "🎤";
    /* Сервис распознавания недоступен (нет сети, Edge без службы, запрет в
       браузере) — НЕ показываем стену «нужен Chrome», а запоминаем это и
       переходим на локальный whisper прямо в этой же попытке. */
    if(e.error === "network" || e.error === "service-not-allowed" || e.error === "language-not-supported"){{
      micMarkSrBad();
      micFileStart(inpId, msgId, findFn);
      return;
    }}
    const M = {{"not-allowed":"⚠ разреши микрофон: значок 🔒/📷 слева в адресной строке",
               "no-speech":"⚠ не расслышал, держи кнопку и говори громче",
               "aborted":"", "audio-capture":"⚠ микрофон не найден"}};
    const t = M[e.error]; if(t) show(t); else if(e.error !== "aborted") show("⚠ " + e.error);
  }};
  rec.onend = finish;
  _mic = rec;
  try {{ rec.start(); side("подключаю микрофон…"); }}
  catch(e) {{ micFileStart(inpId, msgId, findFn); return; }}
  // сторож: распознавание так и не стартовало — уходим на локальный путь
  setTimeout(() => {{
    if(_mic === rec && !rec._started && !rec._done){{
      rec._done = true; _mic = null;
      micMarkSrBad();
      micFileStart(inpId, msgId, findFn);
    }}
  }}, 2500);
}}
function micStop(){{
  if(_micRec){{ _micWantStop = true; try{{ _micRec.stop(); }}catch(e){{}} return; }}
  if(!_mic){{ _micWantStop = true; return; }}
  if(!_mic._started){{ _mic._stopWanted = true; return; }}   // stop once it starts
  try{{ _mic.stop(); }}catch(e){{}}
}}
async function ovFind(id){{
  const q = (document.getElementById("ovq"+id).value || "").trim();
  if(!q) return;
  const fn = document.getElementById("ovfile"+id); fn.textContent = "… ищу в интернете";
  try{{
    const r = await fetch("overlay_search?id="+id, {{method:"POST",
      headers:{{"Content-Type":"application/json"}}, body: JSON.stringify({{q:q}})}});
    const j = await r.json().catch(()=>({{}}));
    if(r.ok && j.photo){{
      fn.textContent = "✓ нашёл: " + q;
      const pv = document.getElementById("ovprev"+id);
      pv.src = j.photo + "?t=" + Date.now(); pv.hidden = false;
    }} else {{ fn.textContent = "✗ не нашёл — переформулируй или загрузи файл"; }}
  }}catch(e){{ fn.textContent = "✗ ошибка поиска"; }}
}}
function ovEdit(id){{
  fetch("overlay?id="+id, {{method:"POST", headers:{{"Content-Type":"application/json"}},
    body: JSON.stringify({{approved:false}})}});
  document.getElementById("ovp"+id).hidden = false;
  document.getElementById("ovdone"+id).hidden = true;
  document.getElementById("ovwrap"+id).classList.remove("ok");
  const mk = document.getElementById("ovmark"+id); if(mk) mk.classList.remove("solid");
}}
async function ovClear(id){{
  _justCleared.add(id);
  await fetch("overlay?id="+id+"&clear=1", {{method:"POST"}});
  const w = document.getElementById("ovwrap"+id);
  w.dataset.touched = ""; w.hidden = true;
  const b = document.getElementById("ovb"+id); if(b) b.hidden = true;
  const done = document.getElementById("ovdone"+id); if(done) done.hidden = true;
  const p = document.getElementById("ovp"+id); if(p) p.hidden = false;
  w.classList.remove("ok");
  const mk = document.getElementById("ovmark"+id); if(mk){{ mk.hidden = true; mk.classList.remove("solid"); }}
  const add = document.getElementById("ovadd"+id); if(add) add.hidden = false;
  rjAsk(id, "overlay", "clear");
}}
render();
{poll}
/* ---- «Почему убрал» (2026-10-16) ----
   Модальное окно, как у бана: посередине, фон затемнён, закрыть крестиком
   или кликом мимо НЕЛЬЗЯ — только кнопкой. Два выхода: причина (клик по
   кнопке, можно с голосом) или крупная кнопка ИГНОР, когда некогда. Игнор
   тоже пишет запись, просто без причины: сам факт снятия с запросом полезен.
   Предыдущая версия с всплывашкой в углу убрана — пользователь нажал на неё
   и ничего не открылось (в rjPanel остались переменные от старой сигнатуры,
   ReferenceError обрывал показ). */
let _rjCtx = null, _rjRec = null, _rjChunks = [], _rjAudio = "";
const RJ_REASONS = [
  ["watermark","водяной знак / логотип"],
  ["not_real","не реальное фото (AI, графика)"],
  ["wrong_country","чужая страна / объект"],
  ["wrong_person","не тот человек / устарело"],
  ["archive","архив вместо современности"],
  ["people","люди в кадре / дети"],
  ["stale","примелькалось"],
  ["offtopic","не по теме сцены"],
  ["document","документ или текст"],
  ["other","другое"]
];
const RJ_LABEL = {{watermark:"водяной знак/логотип", not_real:"не реальное фото",
  wrong_country:"чужая страна", wrong_person:"не тот человек",
  archive:"архив вместо современности", people:"люди в кадре",
  stale:"примелькалось", offtopic:"не по теме сцены",
  document:"документ/текст в кадре", other:""}};
const RJ_KIND = {{overlay:"всплывашку", text:"текст", scene:"сцену"}};
/* Для ОСТАВЛЕННОГО — свой короткий список: это не причины отказа, а то,
   чем кадр хорош. Пользователь просил 2026-10-16: «расширило бы картину не
   просто по запретам, но и по допуску». Окно для keep НЕ всплывает само —
   только по кнопке 💬 на утверждённой карточке. */
const RJ_GOOD = [
  ["fits","точно по этой сцене"],
  ["adds","добавляет то, чего нет в базе"],
  ["readable","хорошо видно / читается"],
  ["rare","редкий удачный кадр"],
  ["good_other","просто хорошо"]
];

function rjCommit(ctx, reason, note){{
  fetch("reject?id=" + ctx.id, {{method:"POST",
    headers:{{"Content-Type":"application/json"}},
    body: JSON.stringify({{kind:ctx.kind, action:ctx.action,
      reason: reason || "", note: note || "", audio: _rjAudio || ""}})
  }}).catch(function(){{}});
}}

function rjAsk(id, kind, action){{
  return new Promise(function(resolve){{
    _rjCtx = {{id:id, kind:kind, action:action, resolve:resolve}};
    _rjAudio = ""; _rjChunks = [];
    const box = document.getElementById("rjbtns");
    box.innerHTML = "";
    const list = (action === "keep") ? RJ_GOOD : RJ_REASONS;
    list.forEach(function(r){{
      const b = document.createElement("button");
      b.className = "rjb"; b.textContent = r[1];
      b.onclick = function(){{ rjSend(r[0]); }};
      box.appendChild(b);
    }});
    document.getElementById("rjnote").value = "";
    document.getElementById("rjstat").textContent = "";
    document.getElementById("rjmic").textContent = "🎤 надиктовать причину";
    document.getElementById("rjttl").textContent =
      (action === "keep" ? "Оставил " : (action === "ban" ? "Забанил " : "Снял ")) +
      (RJ_KIND[kind] || kind) + " " + id +
      (action === "keep" ? " — чем хорош?" : " — почему?");
    document.getElementById("rjw").hidden = false;
  }});
}}

/* Диктовка в реальном времени. Основной путь — распознавание самого
   браузера (Web Speech API): слова появляются в поле ПОКА ГОВОРИШЬ, ждать
   нечего. Оно работает в Chrome/Edge на localhost и требует сети — голос
   при этом уходит на сервера Google. Если API нет или оно отвалилось,
   автоматически включается запасной путь: запись в файл и локальный
   whisper (приватно, но ~8 секунд ожидания — пользователь, 2026-10-16:
   «я что, на каждую всплывашку буду 8 секунд тратить?»). */
let _rjSR = null, _rjFinal = "";

function rjMic(){{
  /* Если браузерное распознавание один раз уже отказало — больше не пытаемся.
     Иначе каждая диктовка начинается с неудачной попытки, пользователь теряет
     первые слова и видит мигающие сообщения. Запомнили — идём сразу локально.
     (Edge, 2026-10-16: сервис распознавания недоступен, а API объявлен.) */
  try{{ if(localStorage.getItem("rjsr_bad") === "1") return rjMicFile(); }}catch(e){{}}
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR) return rjMicFile();        /* нет API — пишем файл и шлём whisper */
  const btn = document.getElementById("rjmic");
  const st = document.getElementById("rjstat");
  const note = document.getElementById("rjnote");
  if(_rjSR){{ _rjSR.stop(); return; }}
  _rjFinal = note.value.trim();
  const r = new SR();
  r.lang = "ru-RU";
  r.continuous = true;
  r.interimResults = true;           /* ключ: промежуточные слова сразу */
  r.onresult = function(e){{
    let interim = "";
    for(let i = e.resultIndex; i < e.results.length; i++){{
      const t = e.results[i][0].transcript;
      if(e.results[i].isFinal) _rjFinal = (_rjFinal + " " + t).trim();
      else interim += t;
    }}
    note.value = (_rjFinal + " " + interim).trim();
    note.scrollTop = note.scrollHeight;
  }};
  r.onerror = function(ev){{
    _rjSR = null;
    btn.textContent = "🎤 надиктовать причину";
    /* ТОЛЬКО not-allowed означает, что микрофон запретил сам пользователь.
       Всё остальное — отказ СЕРВИСА распознавания (нет сети, сервис не
       отвечает, в Edge это приходит как service-not-allowed), и тогда надо
       молча уходить на локальный whisper, а не упрекать человека настройками
       браузера. Поймано живьём 2026-10-16: пользователь в Edge увидел
       «нужен Chrome и интернет» и остался без диктовки вообще. */
    if(ev.error === "not-allowed"){{
      st.textContent = "микрофон запрещён в браузере — разреши доступ и повтори";
      return;
    }}
    try{{ localStorage.setItem("rjsr_bad", "1"); }}catch(e){{}}
    st.textContent = "распознавание браузера недоступно — пишу локально…";
    rjMicFile();
  }};
  r.onend = function(){{
    _rjSR = null;
    btn.textContent = "🎤 надиктовать ещё";
    if(st.textContent === "говори — текст идёт в поле") st.textContent = "можно поправить и жать причину";
  }};
  try{{
    r.start();
  }}catch(e){{
    /* бывает, что API объявлен, но стартовать не даёт — не теряем диктовку */
    _rjSR = null;
    try{{ localStorage.setItem("rjsr_bad", "1"); }}catch(e2){{}}
    st.textContent = "распознавание браузера не стартовало — пишу локально…";
    return rjMicFile();
  }}
  _rjSR = r;
  btn.textContent = "⏹ стоп";
  st.textContent = "говори — текст идёт в поле";
}}

/* Запасной путь: запись в файл + локальный whisper. Медленно, зато офлайн
   и в любом браузере. */
async function rjMicFile(){{
  const btn = document.getElementById("rjmic");
  const st = document.getElementById("rjstat");
  if(_rjRec && _rjRec.state === "recording"){{ _rjRec.stop(); return; }}
  try{{
    const stream = await navigator.mediaDevices.getUserMedia({{audio:true}});
    _rjRec = new MediaRecorder(stream);
    _rjChunks = [];
    _rjRec.ondataavailable = function(e){{ if(e.data.size) _rjChunks.push(e.data); }};
    _rjRec.onstop = function(){{
      stream.getTracks().forEach(function(t){{ t.stop(); }});
      const blob = new Blob(_rjChunks, {{type:"audio/webm"}});
      const fr = new FileReader();
      fr.onloadend = async function(){{
        const b64 = String(fr.result).split(",")[1] || "";
        _rjAudio = "";
        btn.textContent = "🎤 надиктовать ещё";
        st.textContent = "расшифровываю локально…";
        const note = document.getElementById("rjnote");
        try{{
          const r = await fetch("voice", {{method:"POST",
            headers:{{"Content-Type":"application/json"}},
            body: JSON.stringify({{audio:b64}})}});
          const j = await r.json();
          const txt = (j.text || "").trim();
          if(txt){{
            note.value = note.value.trim() ? (note.value.trim() + " " + txt) : txt;
            st.textContent = "можно поправить и жать причину";
            note.focus();
            note.setSelectionRange(note.value.length, note.value.length);
          }} else st.textContent = "не разобрал — скажи ещё раз или напиши";
        }}catch(e){{
          _rjAudio = b64;
          st.textContent = "расшифровать не вышло, пошлю голос как есть";
        }}
      }};
      fr.readAsDataURL(blob);
    }};
    _rjRec.start();
    btn.textContent = "⏹ стоп";
    st.textContent = "пишу… расшифрую после остановки";
  }}catch(e){{ st.textContent = "микрофон недоступен — напиши текстом"; }}
}}

/* Единственные два выхода из окна: причина или ИГНОР. Оба пишут запись. */
function rjSend(reason){{
  const ctx = _rjCtx; if(!ctx) return;
  if(_rjSR){{ try{{ _rjSR.stop(); }}catch(e){{}} _rjSR = null; }}
  if(_rjRec && _rjRec.state === "recording"){{
    /* не теряем надиктованное: дожидаемся stop, он положит _rjAudio */
    const rec = _rjRec;
    rec.addEventListener("stop", function(){{ setTimeout(function(){{ rjSend(reason); }}, 120); }}, {{once:true}});
    rec.stop();
    return;
  }}
  const note = document.getElementById("rjnote").value || "";
  document.getElementById("rjw").hidden = true;
  _rjCtx = null;
  rjCommit(ctx, reason, note);
  if(typeof ctx.resolve === "function"){{
    ctx.resolve({{reason: reason || "", note: note}});
  }}
}}
function rjIgnore(){{ rjSend(""); }}
</script>
</body>
<div id="rjw" hidden>
 <div id="rjbox">
  <div id="rjttl"></div>
  <div id="rjbtns"></div>
  <div class="rjrow">
   <button id="rjmic" onclick="rjMic()">🎤 надиктовать причину</button>
   <span id="rjstat"></span>
  </div>
  <textarea id="rjnote" rows="2" placeholder="или напиши причину…"></textarea>
  <div class="rjrow rjfoot">
   <button class="rjign" onclick="rjIgnore()">ИГНОР</button>
   <button class="rjok" onclick="rjSend('other')">готово</button>
  </div>
 </div>
</div>
<style>
#rjw{{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:9999;
     display:flex;align-items:center;justify-content:center}}
#rjw[hidden]{{display:none}}
#rjbox{{background:#1b1b1b;color:#eee;padding:20px 22px;border-radius:10px;
       width:min(580px,92vw);box-shadow:0 10px 50px rgba(0,0,0,.7)}}
#rjttl{{font-size:17px;font-weight:600;margin-bottom:13px}}
#rjbtns{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}}
.rjb{{background:#2e2e2e;color:#eee;border:1px solid #444;border-radius:6px;
     padding:8px 11px;cursor:pointer;font-size:13px}}
.rjb:hover{{background:#3a3a3a;border-color:#888}}
.rjrow{{display:flex;align-items:center;gap:10px;margin:8px 0}}
.rjfoot{{justify-content:space-between;margin-top:14px}}
#rjmic{{background:#8a2d2d;color:#fff;border:0;border-radius:6px;
       padding:9px 15px;cursor:pointer;font-size:14px}}
#rjmic:hover{{background:#a33636}}
#rjstat{{font-size:12px;color:#aaa}}
#rjnote{{width:100%;background:#111;color:#eee;border:1px solid #444;
        border-radius:6px;padding:8px;font-size:13px;box-sizing:border-box}}
.rjign{{background:#333;color:#bbb;border:1px solid #4a4a4a;border-radius:6px;
       padding:9px 22px;cursor:pointer;font-size:14px;letter-spacing:.5px}}
.rjign:hover{{background:#444;color:#fff}}
.rjok{{background:#2d6a3f;color:#fff;border:0;border-radius:6px;
      padding:9px 22px;cursor:pointer;font-size:14px}}
.rjok:hover{{background:#37804c}}
</style>
</html>"""


# --------------------------------------------------------------------------
def run_snapshot(scenes_path, images_dir, out_path):
    scenes = load_scenes(scenes_path)
    project = os.path.basename(os.getcwd())
    html = build_page(scenes, project, live=False, images_dir=images_dir)
    open(out_path, "w", encoding="utf-8").write(html)
    print(f"wrote {out_path}  ({len(html)//1024} KB, {len(scenes)} scenes)")


CT_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
          "image/gif": ".gif", "video/mp4": ".mp4", "video/quicktime": ".mov",
          "video/webm": ".webm"}


def run_live(scenes_path, images_dir, port):
    import http.server
    import socketserver
    import threading
    import time
    import urllib.parse

    scenes = load_scenes(scenes_path)
    project = os.path.basename(os.getcwd())
    thumbs_dir = os.path.join(images_dir, ".rev")

    # Греем whisper заранее, в фоне: иначе первая же диктовка ждёт лишние
    # 2-3 секунды на загрузку модели, и это ровно тот момент, когда
    # пользователь смотрит на пустое поле и думает, что сломалось.
    def _warm():
        try:
            from voice_note import _load
            _load()
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()
    os.makedirs(thumbs_dir, exist_ok=True)
    open("review.html", "w", encoding="utf-8").write(
        build_page(scenes, project, live=True, images_dir=images_dir))

    def state_json():
        man = {}
        mp = os.path.join(images_dir, "manifest.json")
        if os.path.exists(mp):
            try:
                man = {m["id"]: m for m in json.load(open(mp, encoding="utf-8"))}
            except (OSError, ValueError):
                pass
        out, failed = [], 0
        for s in scenes:
            sid = s["id"]
            ap = resolved_asset(images_dir, sid)
            m = man.get(sid, {})
            row = {"id": sid}
            if not ap and (m.get("status") == "FAILED" or sid in man):
                row["status"] = "failed"
                failed += 1
            elif ap:
                tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                if not os.path.exists(tp) or os.path.getmtime(tp) < os.path.getmtime(ap):
                    b = make_thumb_bytes(ap)
                    if b:
                        open(tp, "wb").write(b)
                is_vid = ap.lower().endswith(VID_EXT)
                row["is_video"] = is_vid
                if os.path.exists(tp):
                    label, cls = badge_for(s.get("source", ""), is_vid)
                    row.update(thumb=f"{images_dir}/.rev/{sid:03d}.jpg",
                               v=int(os.path.getmtime(tp)),
                               badge=cls, badge_label=label)
            out.append(row)
        # fetch considered done when every scene id is in the manifest
        fetch_done = len(man) >= len(scenes) and len(man) > 0
        ovs = load_overlays()
        _anchor = str(ovs.get("anchor", "bottom")).lower()
        for k, v in ovs.items():
            if not str(k).isdigit():
                continue
            p = v.get("photo", "")
            v["_v"] = int(os.path.getmtime(p)) if p and os.path.exists(p) else 0
            p_prev = overlay_preview_path(p) if p and os.path.exists(p) else p
            v["_photo_prev"] = p_prev
            try:
                # a real still (the video's own extracted frame, if photo is
                # a video) gives overlay_geom an actual aspect ratio to read
                # instead of silently falling back to the 1.4 default.
                v["pos"] = overlay_geom(int(k), v, p_prev if p_prev and os.path.exists(p_prev) else None,
                                            str(v.get("anchor") or _anchor).lower())
            except Exception:
                pass
            tb = v.get("text") if isinstance(v.get("text"), dict) else None
            if tb and str(tb.get("words") or tb.get("text") or "").strip():
                tpng = os.path.join("overlays", f"scene_{int(k):03d}.text.png")
                v["_tv"] = int(os.path.getmtime(tpng)) if os.path.exists(tpng) else 0
                v["_tpng"] = tpng if os.path.exists(tpng) else ""
                try:
                    v["_tpos"] = overlay_text_geom(tb, tpng if os.path.exists(tpng) else None)
                except Exception:
                    pass
        return json.dumps({"scenes": out, "failed": failed, "fetch_done": fetch_done,
                           "needs": load_needs(), "overlays": ovs})

    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            if path in ("/state", "state"):
                body = state_json().encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            # review.html is NOT a static snapshot from server start — every
            # GET regenerates it fresh from current overlays.json/needs.json/
            # manifest, so a plain page reload always shows the real current
            # state (approved overlays, uniq edits, needs_upload flags), never
            # rolls anything back to how it looked when the server launched.
            # See SKILL.md gotcha "review.html served stale after reload".
            if path in ("", "/review.html", "review.html"):
                body = build_page(scenes, project, live=True, images_dir=images_dir).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Headers", "X-Filename,Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST,GET,OPTIONS")
            self.end_headers()

        def _reply(self, code, body=b"ok"):
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            base = self.path.split("?", 1)
            route = base[0].rstrip("/").lstrip("/")
            qs = urllib.parse.parse_qs(base[1] if len(base) > 1 else "")
            try:
                sid = int(qs.get("id", ["0"])[0])
            except ValueError:
                sid = 0

            if route == "overlay":
                if not sid:
                    return self._reply(400, b"no")
                if qs.get("clear"):
                    drop_overlay(sid)
                    return self._reply(200)
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._reply(400, b"no")
                patch = {}
                if "sound" in spec:
                    patch["sound"] = str(spec["sound"])
                if "shape" in spec:
                    sh = str(spec["shape"]).lower()
                    patch["shape"] = sh if sh in ("rect", "rounded", "square", "circle") else "rect"
                if spec.get("pos") in _POS2STYLE:
                    patch["style"] = _POS2STYLE[spec["pos"]]
                if str(spec.get("anchor", "")).lower() in ("top", "middle", "bottom"):
                    patch["anchor"] = str(spec["anchor"]).lower()
                if "scale" in spec:
                    try:
                        patch["scale"] = max(0.4, min(2.4, round(float(spec["scale"]), 2)))
                    except (TypeError, ValueError):
                        pass
                if "at" in spec:
                    try:
                        patch["at"] = round(float(spec["at"]), 2)
                    except (TypeError, ValueError):
                        pass
                if "approved" in spec:
                    patch["approved"] = bool(spec["approved"])
                save_overlay(sid, patch, create=bool(spec.get("create")))
                return self._reply(200)

            if route == "overlay_text":
                # ОТДЕЛЬНАЯ всплывашка-СЛОВО, живёт в overlays.json как вложенный
                # объект spec["text"] = {words,color,pos,sound,at,scale}. Может
                # сосуществовать с фото-всплывашкой той же сцены. PNG для превью
                # дашборда — overlays/scene_NNN.text.png (сборщик рисует свой).
                if not sid:
                    return self._reply(400, b"no")
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._reply(400, b"no")
                png = os.path.join("overlays", f"scene_{sid:03d}.text.png")
                if spec.get("clear"):
                    with _overlays_txn() as ovs:
                        cur = ovs.get(str(sid), {})
                        cur.pop("text", None)
                        if os.path.exists(png):
                            try:
                                os.remove(png)
                            except OSError:
                                pass
                        # осталось ли что-то осмысленное (реальное фото)?
                        if cur.get("photo") and os.path.exists(cur["photo"]):
                            ovs[str(sid)] = cur
                        else:
                            ovs.pop(str(sid), None)
                    return self._reply(200, json.dumps({"ok": True}).encode())
                words = " ".join(str(spec.get("words") or spec.get("text") or "").split()).strip()
                if not words:
                    return self._reply(400, b"empty")
                color = str(spec.get("color") or spec.get("tcolor") or "white").lower()
                if color not in TEXT_COLORS:
                    color = "white"
                pos = str(spec.get("pos", "bc")).lower()
                if not (len(pos) == 2 and pos[0] in "tmb" and pos[1] in "lcr"):
                    pos = "bc"
                tblock = {"words": words, "color": color, "pos": pos}
                tblock["sound"] = str(spec.get("sound", "pop"))
                try:
                    tblock["at"] = round(float(spec.get("at", 2.0)), 2)
                except (TypeError, ValueError):
                    tblock["at"] = 2.0
                try:
                    tblock["scale"] = max(0.4, min(2.4, round(float(spec.get("scale", 1.0)), 2)))
                except (TypeError, ValueError):
                    tblock["scale"] = 1.0
                os.makedirs("overlays", exist_ok=True)
                render_text_png(words, color, png)     # для превью дашборда
                with _overlays_txn() as ovs:
                    cur = ovs.get(str(sid), {})
                    _prev_text = cur.get("text") if isinstance(cur.get("text"), dict) else {}
                    tblock["approved"] = bool(spec["approved"]) if "approved" in spec \
                        else bool(_prev_text.get("approved", False))
                    cur["text"] = tblock
                    cur.setdefault("photo", cur.get("photo", ""))
                    ovs[str(sid)] = cur
                return self._reply(200, json.dumps({"ok": True}).encode())

            if route == "ticker":
                # Бегущая строка — полностью отдельная фича от overlay/
                # overlay_text выше: свой файл (ticker.json), своя транзакция
                # (_ticker_txn), ничего общего с OVERLAY_FILE. Поломка здесь
                # не может тронуть всплывашки.
                if not sid:
                    return self._reply(400, b"no")
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._reply(400, b"no")
                if spec.get("clear"):
                    drop_ticker(sid)
                    return self._reply(200, json.dumps({"ok": True}).encode())
                patch = {}
                if "text" in spec:
                    patch["text"] = " ".join(str(spec["text"]).split()).strip()
                if "approved" in spec:
                    patch["approved"] = bool(spec["approved"])
                save_ticker(sid, patch)
                return self._reply(200, json.dumps({"ok": True}).encode())

            if route == "keepimg":
                # "меня устраивает этот временный кадр" — снять жёлтую пометку,
                # оставить как есть, ничего больше не искать (user 2026-09-06).
                if not sid:
                    return self._reply(400, b"no")
                drop_need(sid)
                return self._reply(200)

            if route == "ban_asset":
                # «примелькалось, задолбало» (user, 2026-09-22) — ban by md5,
                # separate from the normal 3-video cooldown. Removes the
                # file from THIS scene right away (so the current build
                # can't ship it either) and flags needs_upload so the card
                # doesn't look "done" without a replacement.
                # 2026-09-23: `days` makes this a TIMED ban instead of
                # permanent — None/0 from the dashboard prompt = permanent,
                # same as before.
                if not sid:
                    return self._reply(400, b"no")
                src = None
                for p in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*")):
                    if not p.endswith((".json", ".revframe.jpg")):
                        src = p
                        break
                if not src:
                    return self._reply(404, b"no")
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    spec = {}
                reason = str(spec.get("reason", "")).strip()
                days = spec.get("days")
                try:
                    days = int(days) if days else None
                except (TypeError, ValueError):
                    days = None
                cmd = ["python3", _script("ban_file.py"), src, reason]
                if days:
                    cmd += ["--days", str(days)]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if r.returncode != 0:
                    return self._reply(500, b"no")
                try:
                    os.remove(src)
                except OSError:
                    pass
                tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                if os.path.exists(tp):
                    os.remove(tp)
                need_msg = (f"файл в бане на {days} дн., нужна замена" if days
                            else "файл забанен навсегда, нужна замена")
                save_need(sid, reason or need_msg)
                return self._reply(200)

            if route == "voice":
                # Синхронная расшифровка: текст возвращается в поле окна,
                # чтобы пользователь поправил имена ДО отправки («Вэнс», а не
                # «венз» — живой случай 2026-10-16). Ждать тут нормально:
                # ждёт только тот, кто сам решил диктовать.
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    spec = {}
                text = ""
                tmp = None
                try:
                    raw = base64.b64decode(spec.get("audio") or "")
                    if raw:
                        fd, tmp = tempfile.mkstemp(suffix=".webm")
                        with os.fdopen(fd, "wb") as fh:
                            fh.write(raw)
                        from voice_note import transcribe
                        text = transcribe(tmp)
                except Exception:
                    text = ""
                finally:
                    if tmp and os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                body = json.dumps({"text": text}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if route == "reject":
                # «Почему убрал» — фиксируется ВСЕГДА, даже если пользователь
                # закрыл панель не выбрав причину (тогда reason=other): факт
                # отказа с запросом уже полезен. Отвечаем сразу, расшифровка
                # голоса и запись идут в фоне, карточка не ждёт.
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    spec = {}
                if sid:
                    _log_reject_async(spec, sid, scenes, images_dir, project)
                return self._reply(200)

            if route == "mirror":
                # отзеркалить основной кадр сцены по горизонтали, в самом файле
                # scene_NNN.* (фото или видео). Live-poll подхватит по mtime.
                if not sid:
                    return self._reply(400, b"no")
                src = None
                for p in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*")):
                    if not p.endswith((".json", ".revframe.jpg")):
                        src = p
                        break
                if not src:
                    return self._reply(404, b"no")
                ext = os.path.splitext(src)[1]
                tmp = src + ".flip" + ext
                is_v = src.lower().endswith(VID_EXT)
                cmd = ["ffmpeg", "-y", "-i", src, "-vf", "hflip"]
                cmd += (["-c:a", "copy", tmp] if is_v else [tmp])
                r = subprocess.run(cmd, capture_output=True)
                if r.returncode != 0 or not os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    return self._reply(500, b"no")
                os.replace(tmp, src)
                tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                if os.path.exists(tp):
                    os.remove(tp)
                return self._reply(200)

            if route == "zoomimg":
                # «масштаб кадра»: пользователь выбирает КРАТНОСТЬ (1.1 / 1.2 /
                # 1.3 / 1.5), кадр центрально обрезается на эту кратность и
                # тянется обратно к исходному размеру. НЕ накопительно —
                # каждый раз режем от нетронутого оригинала (лежит в
                # images/.zoom_orig/), поэтому 1.1 после 1.5 = именно 1.1, а
                # f=1.0 возвращает оригинал. Меняет пиксельную структуру —
                # заодно уводит от дедупа.
                if not sid:
                    return self._reply(400, b"no")
                try:
                    factor = float(qs.get("f", ["1.2"])[0])
                except ValueError:
                    factor = 1.2
                factor = max(1.0, min(3.0, factor))
                src = None
                for p in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*")):
                    if not p.endswith((".json", ".revframe.jpg")):
                        src = p
                        break
                if not src:
                    return self._reply(404, b"no")
                ext = os.path.splitext(src)[1]
                is_v = src.lower().endswith(VID_EXT)
                odir = os.path.join(images_dir, ".zoom_orig")
                os.makedirs(odir, exist_ok=True)
                orig = os.path.join(odir, f"scene_{sid:03d}{ext}")
                if not os.path.exists(orig):
                    shutil.copyfile(src, orig)          # первый зум — сохраняем оригинал
                if factor <= 1.001:                  # сброс к оригиналу
                    shutil.copyfile(orig, src)
                    tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                    if os.path.exists(tp):
                        os.remove(tp)
                    return self._reply(200)
                pr = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", orig],
                    capture_output=True, text=True)
                try:
                    w, h = (int(x) for x in pr.stdout.strip().split("x")[:2])
                except (ValueError, IndexError):
                    return self._reply(500, b"no")
                w -= w % 2
                h -= h % 2
                vf = f"crop=iw/{factor:.3f}:ih/{factor:.3f},scale={w}:{h}"
                tmp = src + ".zm" + ext
                cmd = ["ffmpeg", "-y", "-i", orig, "-vf", vf]
                cmd += (["-c:a", "copy", tmp] if is_v else ["-q:v", "2", tmp])
                r = subprocess.run(cmd, capture_output=True)
                if r.returncode != 0 or not os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    return self._reply(500, b"no")
                os.replace(tmp, src)
                tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                if os.path.exists(tp):
                    os.remove(tp)
                return self._reply(200)

            if route == "uniq":
                # «Уникализировать»: зеркало/цвет/поворот/зум-обрез. Состояние
                # копится в images/.uniq.json, применяется ЦЕЛИКОМ от нетронутого
                # исходника images/.uniq_orig/ одной ffmpeg-цепочкой. Углы после
                # поворота = размытая подложка той же картинки.
                if not sid:
                    return self._reply(400, b"no")
                # t=ov — та же механика, но по ФОТО ВСПЛЫВАШКИ (user, 2026-10-17:
                # «чтобы функционал был такой же, как и на основной картинке»).
                # Состояние и исходники лежат рядом с файлом: overlays/.uniq.json
                # и overlays/.uniq_orig/, то есть две обработки не мешают друг другу.
                _uqdir = "overlays" if (qs.get("t", [""])[0] == "ov") else images_dir
                src = None
                for p in glob.glob(os.path.join(_uqdir, f"scene_{sid:03d}.*")):
                    if not p.endswith((".json", ".revframe.jpg", ".ovthumb.jpg")):
                        src = p
                        break
                if not src:
                    return self._reply(404, b"no")
                ext = os.path.splitext(src)[1]
                is_v = src.lower().endswith(VID_EXT)
                odir = os.path.join(_uqdir, ".uniq_orig")
                os.makedirs(odir, exist_ok=True)
                orig = os.path.join(odir, f"scene_{sid:03d}{ext}")
                if not os.path.exists(orig):
                    shutil.copyfile(src, orig)      # первый клик — сохраняем исходник

                data = _uniq_load(_uqdir)
                st = dict(_UNIQ_DEFAULT)
                st.update(data.get(str(sid), {}))
                if qs.get("reset"):
                    st = dict(_UNIQ_DEFAULT)
                elif qs.get("toggle"):
                    k = qs["toggle"][0]
                    if k in ("flip", "color", "bw"):
                        st[k] = not st.get(k)
                else:
                    if "rot" in qs:
                        try:
                            v = int(float(qs["rot"][0]))
                        except ValueError:
                            v = 0
                        st["rot"] = 0 if int(st.get("rot", 0)) == v else max(0, min(3, v))
                    if "zoom" in qs:
                        try:
                            v = round(float(qs["zoom"][0]), 2)
                        except ValueError:
                            v = 1.0
                        st["zoom"] = 1.0 if abs(float(st.get("zoom", 1.0)) - v) < 0.01 else max(1.0, min(2.0, v))

                if _uniq_is_default(st):
                    shutil.copyfile(orig, src)
                else:
                    tmp = src + ".uq" + ext
                    r = _uniq_ffmpeg(orig, tmp, st, is_v)
                    if r.returncode != 0 or not os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                        return self._reply(500, (r.stderr or b"")[-400:] or b"ffmpeg failed")
                    os.replace(tmp, src)

                data[str(sid)] = st
                if _uniq_is_default(st):
                    data.pop(str(sid), None)
                _uniq_save(_uqdir, data)
                if _uqdir == "overlays":
                    # кэш превьюшки всплывашки — иначе дашборд покажет старую
                    for _c in glob.glob(os.path.join("overlays", f"scene_{sid:03d}.*.ovthumb.jpg")) \
                            + glob.glob(os.path.join("overlays", f"scene_{sid:03d}*.ovthumb.jpg")):
                        try:
                            os.remove(_c)
                        except OSError:
                            pass
                else:
                    tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                    if os.path.exists(tp):
                        os.remove(tp)
                body = json.dumps({"state": st, "summary": _uniq_summary(st)}).encode()
                return self._reply(200, body)

            if route == "preview":
                # собрать РЕАЛЬНЫЙ кусок этой сцены (Ken Burns + всплывашка +
                # текст + звук) и вернуть URL плеера. Долго (~10-30 с/кадр).
                if not sid:
                    return self._reply(400, b"no")
                try:
                    url = build_scene_preview(sid, images_dir, scenes_path)
                except Exception as e:
                    return self._reply(500, str(e).encode()[:300])
                if not url:
                    return self._reply(500, b"preview build failed")
                return self._reply(200, json.dumps({"ok": True, "url": url}).encode())

            if route == "mirror_ov":
                # отзеркалить фото всплывашки (overlays/scene_NNN.jpg).
                if not sid:
                    return self._reply(400, b"no")
                src = None
                for p in glob.glob(os.path.join("overlays", f"scene_{sid:03d}.*")):
                    if not p.endswith(".json"):
                        src = p
                        break
                if not src:
                    return self._reply(404, b"no")
                tmp = src + ".flip" + os.path.splitext(src)[1]
                r = subprocess.run(["ffmpeg", "-y", "-i", src, "-vf", "hflip", tmp],
                                   capture_output=True)
                if r.returncode != 0 or not os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    return self._reply(500, b"no")
                os.replace(tmp, src)
                return self._reply(200)

            if route == "overlay_photo":
                n = int(self.headers.get("Content-Length", 0) or 0)
                data = self.rfile.read(n) if n else b""
                fname = urllib.parse.unquote(self.headers.get("X-Filename", ""))
                ext = os.path.splitext(fname)[1].lower() or ".jpg"
                if not (sid and data):
                    return self._reply(400, b"no")
                os.makedirs("overlays", exist_ok=True)
                for old in glob.glob(os.path.join("overlays", f"scene_{sid:03d}.*")):
                    os.remove(old)
                path = os.path.join("overlays", f"scene_{sid:03d}{ext}")
                with open(path, "wb") as fh:
                    fh.write(data)
                _uniq_forget("overlays", sid)      # фото новое — обработка старого не его
                save_overlay(sid, {"photo": path})
                return self._reply(200)

            if route == "overlay_search":
                # user typed "find me X" for a pop-up -> run the real fetcher
                # for one throw-away scene straight into overlays/.
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._reply(400, b"no")
                qtext = str(spec.get("q", "")).strip()
                if not (sid and qtext):
                    return self._reply(400, b"no")
                os.makedirs("overlays", exist_ok=True)
                for old in glob.glob(os.path.join("overlays", f"scene_{sid:03d}.*")):
                    os.remove(old)
                found = None
                for src in ("press_photo", "pexels_photo"):
                    mini = {"scenes": [{"id": sid, "text": qtext, "duration_sec": 3,
                                        "visual_prompt": qtext, "source": src,
                                        "source_query": qtext}]}
                    tmpf = os.path.join("overlays", f"_search_{sid}.json")
                    with open(tmpf, "w", encoding="utf-8") as fh:
                        json.dump(mini, fh, ensure_ascii=False)
                    try:
                        subprocess.run(["python3", _script("fetch_assets_news.py"), tmpf,
                                        "overlays", ".env"],
                                       capture_output=True, timeout=120)
                    except Exception:
                        pass
                    try:
                        os.remove(tmpf)
                    except OSError:
                        pass
                    hits = [p for p in glob.glob(os.path.join("overlays", f"scene_{sid:03d}.*"))
                            if not p.endswith(".json") and os.path.getsize(p) > 0]
                    if hits:
                        found = hits[0]
                        break
                if found:
                    _uniq_forget("overlays", sid)      # фото заменили — старую обработку забыть
                    save_overlay(sid, {"photo": found})
                    body = json.dumps({"photo": found}).encode()
                else:
                    body = b'{"photo":null}'
                self.send_response(200 if found else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if route == "img_search":
                # user typed keywords for the MAIN scene frame -> fetch it now,
                # straight into images/. Same idea as overlay_search.
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._reply(400, b"no")
                qtext = str(spec.get("q", "")).strip()
                if not (sid and qtext):
                    return self._reply(400, b"no")
                stext = next((s["text"] for s in scenes if s["id"] == sid), qtext)
                got = None
                for src in ("press_photo", "pexels_photo", "pexels_video"):
                    mini = {"scenes": [{"id": sid, "text": stext, "duration_sec": 3,
                                        "visual_prompt": qtext, "source": src,
                                        "source_query": qtext}]}
                    tmpf = os.path.join(images_dir, f"_isearch_{sid}.json")
                    with open(tmpf, "w", encoding="utf-8") as fh:
                        json.dump(mini, fh, ensure_ascii=False)
                    for old in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*")):
                        if not old.endswith(".json"):
                            os.remove(old)
                    try:
                        subprocess.run(["python3", _script("fetch_assets_news.py"), tmpf,
                                        images_dir, ".env"],
                                       capture_output=True, timeout=150)
                    except Exception:
                        pass
                    try:
                        os.remove(tmpf)
                    except OSError:
                        pass
                    hits = [p for p in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*"))
                            if not p.endswith(".json") and os.path.getsize(p) > 0]
                    if hits:
                        got = hits[0]
                        break
                if got:
                    tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                    if os.path.exists(tp):
                        os.remove(tp)
                    drop_need(sid)
                    body = json.dumps({"ok": True, "file": os.path.basename(got)}).encode()
                else:
                    body = b'{"ok":false}'
                self.send_response(200 if got else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if route == "search_opts":
                # gather candidate images/clips for a query -> user picks one
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._reply(400, b"no")
                qtext = str(spec.get("q", "")).strip()
                if not qtext:
                    return self._reply(400, b"no")
                try:
                    r = subprocess.run(["python3", _script("search_options.py"), qtext, ".env"],
                                       capture_output=True, text=True, timeout=75)
                    body = (r.stdout or '{"opts":[]}').encode()
                except Exception:
                    body = b'{"opts":[]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if route == "pick_opt":
                # user clicked one candidate -> download it into place
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    spec = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._reply(400, b"no")
                furl = str(spec.get("full", "")).strip()
                kind = str(spec.get("kind", "photo"))
                target = str(spec.get("target", "scene"))
                if not (sid and furl.startswith("http")):
                    return self._reply(400, b"no")
                out_dir = "overlays" if target == "overlay" else images_dir
                os.makedirs(out_dir, exist_ok=True)
                ok = False
                reason = ""
                try:
                    import urllib.request as _u
                    req = _u.Request(furl, headers={"User-Agent": "Mozilla/5.0"})
                    data = _u.urlopen(req, timeout=60).read()
                    head = data[:64].lstrip()[:16]
                    if len(data) < 800:
                        reason = "файл пустой"
                    elif kind == "video":
                        dest_ext = ".mp4"
                    elif head[:3] == b"\xff\xd8\xff":
                        dest_ext = ".jpg"
                    elif head[:8] == b"\x89PNG\r\n\x1a\n" or head[:4] == b"RIFF" or head[:4] == b"GIF8" or head[:2] == b"BM":
                        # raster but not jpeg -> re-encode to jpg
                        try:
                            from PIL import Image
                            import io as _io
                            im = Image.open(_io.BytesIO(data)).convert("RGB")
                            buf = _io.BytesIO(); im.save(buf, "JPEG", quality=90)
                            data = buf.getvalue(); dest_ext = ".jpg"
                        except Exception:
                            reason = "картинку не удалось прочитать"
                    elif head[:1] == b"<" or head[:5] == b"<?xml":
                        reason = "это SVG/веб-страница, не фото — выбери другой вариант"
                    else:
                        reason = "неизвестный формат файла"
                    if not reason and kind != "video":
                        try:
                            from PIL import Image
                            import io as _io
                            im = Image.open(_io.BytesIO(data)); im.load()
                            if min(im.size) < 200:
                                reason = "картинка слишком маленькая"
                        except Exception:
                            reason = "картинку не удалось прочитать"
                    if not reason:
                        for old in glob.glob(os.path.join(out_dir, f"scene_{sid:03d}.*")):
                            if not old.endswith(".json"):
                                os.remove(old)
                        dest = os.path.join(out_dir, f"scene_{sid:03d}{dest_ext}")
                        with open(dest, "wb") as fh:
                            fh.write(data)
                        if target == "overlay":
                            _uniq_forget("overlays", sid)      # фото заменили — старую обработку забыть
                            save_overlay(sid, {"photo": dest})
                        else:
                            tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                            if os.path.exists(tp):
                                os.remove(tp)
                            drop_need(sid)
                        ok = True
                except Exception as e:
                    reason = reason or f"ошибка загрузки: {e}"
                body = json.dumps({"ok": ok, "reason": reason}).encode()
                self.send_response(200 if ok else 502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if route != "upload":
                self.send_response(404)
                self.end_headers()
                return
            n = int(self.headers.get("Content-Length", 0) or 0)
            data = self.rfile.read(n) if n else b""
            fname = urllib.parse.unquote(self.headers.get("X-Filename", ""))
            ext = os.path.splitext(fname)[1].lower()
            if ext not in CT_EXT.values():
                ext = CT_EXT.get((self.headers.get("Content-Type") or "").split(";")[0].strip(), "")
            ok = False
            if sid and ext and data:
                for old in glob.glob(os.path.join(images_dir, f"scene_{sid:03d}.*")):
                    if not old.endswith(".json"):
                        os.remove(old)
                tp = os.path.join(thumbs_dir, f"{sid:03d}.jpg")
                if os.path.exists(tp):
                    os.remove(tp)
                with open(os.path.join(images_dir, f"scene_{sid:03d}{ext}"), "wb") as fh:
                    fh.write(data)
                drop_need(sid)          # user supplied it — clear the ⚠️ flag
                ok = True
            self.send_response(200 if ok else 400)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok" if ok else b"no")

    socketserver.TCPServer.allow_reuse_address = True
    # Порт берём СВОБОДНЫЙ, а не слепо запрошенный: на машине работают
    # несколько вкладок сборщика сразу, и 2026-10-11 это дало реальный
    # инцидент — сервер одной вкладки умер, её порт занял чужой проект,
    # пользователь утверждал карточки на дашборде, который считал своим.
    # Падать с "Address already in use" в фоне тоже нельзя: вкладка этого
    # не замечает и продолжает давать ссылку на чужой сервер.
    srv = None
    for cand in range(port, port + 60):
        try:
            srv = socketserver.ThreadingTCPServer(("0.0.0.0", cand), H)
            break
        except OSError:
            continue
    if srv is None:
        raise SystemExit(f"не нашёл свободный порт в диапазоне {port}..{port + 59}")
    if srv.server_address[1] != port:
        print(f"  !! порт {port} занят другим процессом — поднялся на {srv.server_address[1]}", flush=True)
    port = srv.server_address[1]
    ip = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
    print(f"\n  LIVE-предпросмотр запущен. Открой в браузере Windows:", flush=True)
    print(f"    http://localhost:{port}/review.html", flush=True)
    # Печатаем имя проекта рядом со ссылкой: единственный надёжный способ
    # убедиться, что ссылка ведёт именно на этот ролик (ps/ss врут, когда от
    # умершего сервера остаётся живая оболочка процесса).
    print(f"    проект: {os.path.basename(os.path.abspath('.'))}", flush=True)
    if ip:
        print(f"    (если localhost не открывается:  http://{ip[0]}:{port}/review.html )", flush=True)
    print(f"\n  Кадры подгружаются по мере скачивания. Отмечай/пиши правки прямо сейчас.", flush=True)
    print(f"  Ctrl-C чтобы остановить сервер.\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


def main():
    args = sys.argv[1:]
    live = "--live" in args
    args = [a for a in args if a != "--live"]
    scenes_path = args[0] if len(args) > 0 else (sorted(glob.glob("*.scenes.json")) or ["scenes.json"])[0]
    images_dir = args[1] if len(args) > 1 else "images"
    if live:
        port = int(args[2]) if len(args) > 2 else 8747
        run_live(scenes_path, images_dir, port)
    else:
        out_path = args[2] if len(args) > 2 else "review.html"
        run_snapshot(scenes_path, images_dir, out_path)


if __name__ == "__main__":
    main()
