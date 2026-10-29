#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""НОЧНОЙ СБОР БАЗЫ КАДРОВ. Работает на раннере GitHub (публичная цель —
минуты не тратятся), машина пользователя не участвует (его прямое слово 23.10).

    base_harvest.py <plan.json> <out_dir> <.env> [--shard k/n]
                    [--want 25] [--tries 40] [--deadline 1500]

Почему это ОТДЕЛЬНЫЙ скрипт, а не боевой фетч: фетч устроен как «одна сцена —
один файл» (победитель + до четырёх отложенных кандидатов), и выжать из него
25 кадров на ОДИН запрос можно только псевдо-сценами, которые по второму
кругу перебирают ту же выдачу и упираются в дедуп. Здесь задача обратная:
один запрос — много кадров. Поэтому берём ту же выдачу один раз и спускаемся
по ней вглубь.

ГЕЙТЫ НЕ ИЗОБРЕТАЮТСЯ: всё до единого импортируется из боевых файлов
(`fetch_assets_news.py`, `photo_quality.py`). Если правило изменится там —
оно меняется и здесь, расхождения быть не может.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.abspath(os.path.join(HERE, "..", "template"))
sys.path.insert(0, TPL)

import fetch_assets_news as F          # noqa: E402  боевые гейты и загрузчик
import photo_quality as PQ             # noqa: E402  плотность деталей
import search_options as SO            # noqa: E402  выдача поисковиков

# ── НОРМЫ (те же числа, что в боевом конвейере) ────────────────────────────
MIN_W = int(os.environ.get("MIN_IMG_W", "1600"))
MIN_H = int(os.environ.get("MIN_IMG_H", "900"))
MIN_DETAIL = float(os.environ.get("MIN_DETAIL", "0.08"))
MAX_WORDS = int(os.environ.get("MAX_OCR_WORDS", "8"))

_BAD_EXT = (".svg", ".pdf", ".tif", ".tiff", ".djvu", ".gif")


def _say(*a):
    print(*a, flush=True)


def candidates(q, q_en):
    """Выдача четырёх источников ОДНИМ заходом, в порядке полезности для
    русских бытовых запросов: Яндекс понимает их как есть, DDG даёт западную
    фактуру по переводу, Openverse и Wikimedia — лицензионно чистое и крупное.
    Сток не зовём вовсе: запрещён пользователем 28.10."""
    out, seen = [], set()
    for name, fn in (
        # ОЧЕНЬ КРУПНЫЕ ПЕРВЫМИ (замер 28.10): порог ширины 1600 отбил 127
        # кадров из 186 скачанных — две трети работы впустую. Фильтр
        # "exlarge" даёт 15 новых адресов из 20 по сравнению с "large",
        # и это именно те версии, что проходят порог.
        ("yandex·очень крупные", lambda: SO.yandex_images(q, n=30, isize="exlarge")),
        ("yandex",    lambda: SO.yandex_images(q, n=30)),
        ("ddg",       lambda: SO.ddg_images(q_en, n=25)),
        ("openverse", lambda: SO.openverse(q_en, n=15)),
        ("wikimedia", lambda: SO.wikimedia(q_en, n=10)),
    ):
        try:
            got = fn() or []
        except Exception as e:
            _say("    %s: не ответил (%s)" % (name, e))
            continue
        n_new = 0
        for c in got:
            u = (c.get("full") or c.get("thumb") or "").strip()
            if not u or u in seen:
                continue
            if u.split("?")[0].lower().endswith(_BAD_EXT):
                continue
            # домен стокового агентства отбиваем ДО скачивания (единственная
            # защита от клейма, которое OCR не читает — см. _STOCK_DOMAINS)
            if F._is_stock_domain(u):
                continue
            seen.add(u)
            out.append((name, u))
            n_new += 1
        _say("    %s: %d кандидатов" % (name, n_new))
    return out


def gates(path):
    """ТА ЖЕ приёмка, что у боевого фетча, но с НАЗВАННОЙ причиной отказа —
    иначе отчёт прогона не отличает «источник пуст» от «всё отбито гейтом»,
    а это разные болезни с разным лечением."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        return None, "не открылся"
    if w < MIN_W or h < MIN_H:
        return None, "мелкий %dx%d" % (w, h)
    try:
        if F.file_md5(path) in F.load_banned_md5():
            return None, "в бан-листе"
    except OSError:
        pass
    words, blob = F._ocr_words(path)
    if any(m in blob for m in F._STOCK_WATERMARKS):
        return None, "клеймо стока"
    if F._looks_like_document(blob):
        return None, "бланк/документ"
    if words > MAX_WORDS:
        return None, "надписи (%d слов)" % words
    d = PQ.detail_ratio(path)
    if d and d < MIN_DETAIL:
        return None, "плотность %.3f" % d
    return (w, h, d), ""


def sheet(frames, out_jpg, title):
    """Контактный лист объекта: 12 плиток 4x3, номер выжжен на жёлтом.
    Однородный лист (один объект) — чтобы Codex сравнивал сравнимое, а не
    гадал, к какой теме относится плитка."""
    from PIL import Image, ImageDraw, ImageFont
    TW, TH, COLS = 320, 214, 4
    rows = (len(frames) + COLS - 1) // COLS
    W, H = COLS * TW, rows * TH + 34
    sh = Image.new("RGB", (W, H), (24, 24, 26))
    dr = ImageDraw.Draw(sh)
    try:
        fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 21)
    except Exception:
        fnt = big = ImageFont.load_default()
    dr.text((8, 8), title[:92], font=big, fill=(255, 214, 10))
    for i, p in enumerate(frames):
        x, y = (i % COLS) * TW, 34 + (i // COLS) * TH
        try:
            with Image.open(p) as im:
                im.thumbnail((TW - 6, TH - 6))
                sh.paste(im, (x + 3, y + 3))
        except Exception:
            dr.rectangle([x + 3, y + 3, x + TW - 3, y + TH - 3], fill=(60, 30, 30))
        # НОМЕР ПЛИТКИ ВЫЖИГАЕМ (правило дашборда): позицию в сетке можно
        # пересчитать неверно, а подписанный номер — нет
        dr.rectangle([x + 3, y + 3, x + 41, y + 27], fill=(255, 214, 10))
        dr.text((x + 10, y + 5), "%02d" % (i + 1), font=fnt, fill=(0, 0, 0))
    sh.save(out_jpg, "JPEG", quality=84)
    return out_jpg


def harvest_one(item, out_dir, want, tries, deadline):
    layer, q = item["layer"], item["q"]
    safe = item["dir"]
    dst = os.path.join(out_dir, "frames", layer, safe)
    os.makedirs(dst, exist_ok=True)
    _say("\n── %s / %s" % (layer, q))
    try:
        q_en = SO.translate_to_en(q) if any(ord(c) > 127 for c in q) else q
    except Exception:
        q_en = q
    if q_en != q:
        _say("    перевод для западных источников: %s" % q_en)

    cands = candidates(q, q_en)
    _say("    всего кандидатов: %d" % len(cands))
    # то, что уже лежит в базе у этого объекта, качать заново незачем
    kept, seen_md5, rej = [], set(item.get("known_md5") or []), {}
    if seen_md5:
        _say("    в базе уже есть %d кадров — их md5 отбиваю сразу" % len(seen_md5))
    tried = 0
    for src, u in cands:
        if len(kept) >= want or tried >= tries:
            break
        if deadline and time.time() > deadline:
            _say("    [дедлайн] останавливаюсь, что набрано — то и отдаю")
            break
        tmp = os.path.join(dst, ".cand.jpg")
        if not F._download_as_jpeg(u, tmp):
            rej["не скачался"] = rej.get("не скачался", 0) + 1
            continue
        tried += 1
        try:
            h5 = F.file_md5(tmp)
        except OSError:
            h5 = None
        if h5 and h5 in seen_md5:
            os.remove(tmp)
            rej["дубль"] = rej.get("дубль", 0) + 1
            continue
        ok, why = gates(tmp)
        if not ok:
            os.remove(tmp)
            rej[why] = rej.get(why, 0) + 1
            continue
        w, h, d = ok
        if h5:
            seen_md5.add(h5)
        name = "%02d_%dx%d.jpg" % (len(kept) + 1, w, h)
        os.replace(tmp, os.path.join(dst, name))
        kept.append(os.path.join(dst, name))
        _say("    + %s  %s  плотность %.2f  (%s)" % (name, u[:58], d, src))

    sheets = []
    if kept:
        os.makedirs(os.path.join(out_dir, "sheets"), exist_ok=True)
        for part in range(0, len(kept), 12):
            chunk = kept[part:part + 12]
            nm = "%s__%s%s.jpg" % (layer, safe, "" if part == 0 else "_%d" % (part // 12 + 1))
            sheets.append(sheet(chunk, os.path.join(out_dir, "sheets", nm),
                                "%s · %s" % (layer, q)))
            # КАРТА «ПЛИТКА → ФАЙЛ» РЯДОМ С ЛИСТОМ. Без неё приёмке пришлось бы
            # вычислять соответствие по порядку имён — то есть делать ровно то
            # допущение, на котором уже горели («номер плитки пересчитали
            # неверно»). Здесь порядок известен точно, он и записывается.
            json.dump({"sheet": nm, "layer": layer, "dir": safe, "q": q,
                       "tiles": [os.path.relpath(c, out_dir) for c in chunk]},
                      open(os.path.join(out_dir, "sheets", nm[:-4] + ".map.json"),
                           "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    _say("    ИТОГ: прошло %d из %d скачанных, отказы: %s"
         % (len(kept), tried, ", ".join("%s×%d" % (k, v) for k, v in sorted(rej.items())) or "нет"))
    return {"layer": layer, "q": q, "dir": safe, "need_video": item.get("need_video", False),
            "candidates": len(cands), "downloaded": tried, "kept": len(kept),
            "files": [os.path.relpath(p, out_dir) for p in kept],
            "sheets": [os.path.relpath(p, out_dir) for p in sheets],
            "rejects": rej}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("out_dir")
    ap.add_argument("env", nargs="?", default="")
    ap.add_argument("--shard", default="1/1", help="k/n — чья часть плана")
    ap.add_argument("--want", type=int, default=25)
    ap.add_argument("--tries", type=int, default=70)
    ap.add_argument("--deadline", type=float, default=0.0,
                    help="секунд на весь шард; 0 — без дедлайна")
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    items = plan["items"] if isinstance(plan, dict) else plan
    try:
        k, n = (int(x) for x in a.shard.split("/"))
    except ValueError:
        _say("ОШИБКА: --shard ждёт вид k/n, получил %r" % a.shard)
        raise SystemExit(2)
    mine = [it for i, it in enumerate(items) if i % n == (k - 1) % n]
    os.makedirs(a.out_dir, exist_ok=True)
    _say("шард %d/%d: объектов %d из %d (норма %d кадров, потолок попыток %d)"
         % (k, n, len(mine), len(items), a.want, a.tries))
    if a.env and os.path.exists(a.env):
        F.load_env(a.env)

    # OCR — обязательное условие, а не украшение: без tesseract гейт клейм
    # молча пропускает ВСЁ (улов 24.10 «успех может значить ничего не сделано»)
    tess = F._TESS_BIN if os.path.exists(F._TESS_BIN) else "tesseract"
    alive = F._ocr_alive(tess)
    _say("OCR (tesseract): %s" % ("работает" if alive else "НЕ РАБОТАЕТ — клейма не отсеются"))
    if not alive:
        _say("::warning::OCR мёртв, гейт клейм и надписей бесполезен")

    t0 = time.time()
    dl = (t0 + a.deadline) if a.deadline else 0.0
    rep = []
    for it in mine:
        if dl and time.time() > dl:
            _say("[дедлайн] шард остановлен, необработанных объектов: %d"
                 % (len(mine) - len(rep)))
            break
        try:
            rep.append(harvest_one(it, a.out_dir, a.want, a.tries, dl))
        except Exception as e:
            _say("ОШИБКА на объекте %r: %s" % (it.get("q"), e))
            rep.append({"layer": it.get("layer"), "q": it.get("q"), "dir": it.get("dir"),
                        "kept": 0, "error": str(e)})
    out = {"shard": a.shard, "seconds": round(time.time() - t0, 1),
           "ocr": bool(alive), "objects": rep,
           "kept_total": sum(r.get("kept", 0) for r in rep)}
    json.dump(out, open(os.path.join(a.out_dir, "report.shard%d.json" % k), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    _say("\n=== ШАРД %d/%d: кадров %d, объектов %d, %.0f с ==="
         % (k, n, out["kept_total"], len(rep), out["seconds"]))
    # пустой шард валим честно: «success» на нуле кадров уже стоил нам дня
    if rep and out["kept_total"] == 0:
        _say("::error::ни одного кадра не прошло гейты — смотри причины отказов выше")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
