#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adopt_cloud.py — перенести кадры из папки ЗАБОРА в папку ролика.

Зачем отдельный инструмент (2026-10-22, улов `usuario-ad`, стоило разбора на
пустом месте): в `images/manifest.json` поле `file` — ГОЛОЕ ИМЯ файла
(«scene_001.mp4»), без каталога. Естественное
`os.path.join(<корень забора>, m["file"])` даёт несуществующий путь, все кадры
молча считаются отсутствующими и переносится НОЛЬ сцен — при том что в заборе
честные 88 файлов, а `FETCH-report.md` говорит «БЕЗ КАДРА: 0». Выглядит как
пустой забор, хотя забор полон.

Правильный путь — `<забор>/images/<basename>`, и то же самое для всплывашек
(`<забор>/overlays/`). Здесь это зашито, чтобы больше никто не складывал путь
руками.

    python3 adopt_cloud.py <папка забора> <папка ролика> [--dry-run] [--force]

По умолчанию НЕ перезаписывает существующие файлы в папке ролика (там могут
лежать кадры, которые вкладка уже правила руками) — для перезаписи `--force`.
Печатает построчный итог и в конце сверку: сколько сцен в сценарии, сколько
кадров перенесено, по скольким кадра нет вовсе.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import sys

_IMG = (".jpg", ".jpeg", ".png", ".webp")
_VID = (".mp4", ".mov", ".webm")


# Имена, под которыми в папке ролика лежит СЫРОЙ файл внешнего агента или
# черновик: по ним фетч никогда не шёл, и сверять с ними забор нельзя.
_RAW_HINTS = ("codex", "agent", "raw", "draft", "orig", "_in", "syr")


def _scenes_file(proj, quiet=False):
    """Эталонный scenes.json папки.

    2026-10-27, улов `usuario-2d`, стоило половины ролика при зелёном
    FETCH-report: выбор шёл глобом с сортировкой «больше сцен, короче имя», и
    рядом с принятым `<ролик>.scenes.json` лежал сырой `codex.scenes.json`
    агента — столько же сцен, имя короче, значит побеждал он. Сверка «кадр под
    переписанный запрос» шла с ПЕРВОНАЧАЛЬНЫМИ запросами агента, и перенос
    отклонял 51 сцену из 87 как «переписанный запрос». Отчёт фетча при этом
    честно говорил «БЕЗ КАДРА: 0» — класс «успех ≠ сделанная работа».

    Порядок теперь по ИМЕНИ, а не по размеру:
      1. `<имя папки ролика>.scenes.json` — принятый файл этого ролика;
      2. любой, кроме черновиков агента (`_RAW_HINTS`): больше сцен, свежее;
      3. если других нет вовсе — черновик, но с громкой строкой в выводе.
    """
    cs = [x for x in glob.glob(os.path.join(proj, "*.scenes.json"))
          if "overlays_fetch" not in os.path.basename(x)]
    if not cs:
        return ""

    def _stem(q):
        return os.path.basename(q)[:-len(".scenes.json")].lower()

    want = os.path.basename(os.path.abspath(proj)).lower()
    exact = [x for x in cs if _stem(x) == want]
    if exact:
        pick = exact[0]
    else:
        clean = [x for x in cs if not any(h in _stem(x) for h in _RAW_HINTS)]
        pool = clean or cs
        pool.sort(key=lambda q: (-len(_load(q).get("scenes", [])),
                                 -os.path.getmtime(q)))
        pick = pool[0]
        if not clean and not quiet:
            print("!! в папке только черновик агента (%s) — сверка пойдёт по нему; "
                  "принятый <ролик>.scenes.json не найден"
                  % os.path.basename(pick))
    if len(cs) > 1 and not quiet:
        others = [os.path.basename(x) for x in cs if x != pick]
        print("сценариев в папке %d, взят %s (прочие: %s)" % (
            len(cs), os.path.basename(pick), ", ".join(others)))
    return pick


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}



# --- ДВЕ ПРОВЕРКИ ПЕРЕД ПЕРЕНОСОМ (2026-10-23, улов `usuario-a7`) -----------
# Перенос сверялся ТОЛЬКО с манифестом облака и потому воскрешал кадры, которые
# вкладка забанила минуту назад: проход уходил ДО круга правок, возвращался со
# старыми кадрами, манифест честно показывал `status: ok`, и файлы ложились
# обратно в проект молча. Это не редкий случай, а штатный ход конвейера —
# отправил, пока считается провёл круг правок, забрал проход «из прошлой
# редакции»; чем больше проходов, тем вернее совпадение (у вкладки их было
# шесть). Фетчер обе проверки делает, но перенос идёт мимо него, это обычное
# копирование. Обе стоят миллисекунды.
def _banned_md5():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from fetch_assets_news import load_banned_md5
        return load_banned_md5()
    except Exception:
        return set()


def _file_md5(path):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _queries(path):
    """{id сцены: source_query} из scenes.json, чтобы поймать «кадр из прошлой
    редакции»: запрос переписан — значит кадр к нему уже не относится."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    try:
        data = _load(path)
    except Exception:
        return out
    for sc in (data.get("scenes") if isinstance(data, dict) else data) or []:
        try:
            out[int(sc.get("id", -1))] = str(sc.get("source_query", ""))
        except (TypeError, ValueError):
            pass
    return out


def _recs(d):
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    for k in ("items", "scenes", "manifest"):
        v = d.get(k)
        if isinstance(v, list):
            return [r for r in v if isinstance(r, dict)]
    return []


def adopt(src, dst, dry=False, force=False):
    if not os.path.isdir(src):
        print("!! нет папки забора: %s" % src)
        return 2
    os.makedirs(os.path.join(dst, "images"), exist_ok=True)

    total_moved = total_skipped = missing = rejected = 0
    holes = {}          # статус из манифеста → список имён
    clashes = []        # кадр уже есть в другом формате
    _banned = _banned_md5()
    _q_src = _queries(_scenes_file(src))
    _q_dst = _queries(_scenes_file(dst))
    if _banned:
        print("бан-лист: %d активных md5 — забаненное из забора не берём" % len(_banned))
    if _q_src and _q_dst:
        _diff = [k for k in _q_src if k in _q_dst and _q_src[k] != _q_dst[k]]
        if _diff:
            print("запросы переписаны после отправки у %d сцен: %s" % (
                len(_diff), ", ".join(map(str, sorted(_diff)[:10]))))
    for sub in ("images", "overlays"):
        moved = skipped = 0
        s_dir = os.path.join(src, sub)
        if not os.path.isdir(s_dir):
            continue
        d_dir = os.path.join(dst, sub)
        os.makedirs(d_dir, exist_ok=True)
        man = _recs(_load(os.path.join(s_dir, "manifest.json")))
        names = [os.path.basename(str(m.get("file") or "")) for m in man if m.get("file")]
        # СТАТУС ИЗ МАНИФЕСТА ЧИТАЛСЯ ТОЛЬКО ГЛАЗАМИ (2026-10-31, улов
        # `usuario-b2`). Перенос отклонял по бану и по переписанному запросу,
        # а поле `status` не смотрел вовсе — и ЗАГЛУШКИ ЕХАЛИ КАК ГОДНЫЕ
        # КАДРЫ. Живой счёт: в манифесте 40 ok, 32 placeholder, 5
        # card_pending; инструмент отчитался «перенесено 55, отклонено 13» и
        # в сверке написал «кадров на месте 73, без кадра 4». По факту 17 из
        # этих 73 — тёмно-красные заглушки «нет кадра» (1920x1080, 34 КБ,
        # яркость 28), и сверка их считала кадрами, то есть ПРЯТАЛА дыру.
        # Поймалось косвенно, по одинаковой плотности в `photo_quality.py`.
        # Правило «переносить только по манифесту» соблюдалось, манифест
        # честно писал статус — игнорировал его исполнитель.
        _st = {}
        for m in man:
            _f = os.path.basename(str(m.get("file") or ""))
            if _f:
                _st[_f] = str(m.get("status") or "ok")
        if not names:
            # манифеста нет или он пуст — берём, что лежит на диске
            names = [os.path.basename(p) for p in glob.glob(os.path.join(s_dir, "scene_*"))
                     if os.path.splitext(p)[1].lower() in _IMG + _VID]
        print("== %s: в манифесте/на диске %d файлов" % (sub, len(names)))
        for n in sorted(set(names)):
            sp = os.path.join(s_dir, n)          # <-- ВОТ ЭТОТ ПУТЬ, а не join(src, n)
            if not os.path.isfile(sp):
                print("   НЕТ в заборе: %s" % n)
                missing += 1
                continue
            _m = re.search(r"scene_(\d+)", n)
            _sid = int(_m.group(1)) if _m else -1
            if _banned and _file_md5(sp) in _banned:
                print("   ЗАБАНЕН, НЕ БЕРУ: %s (сцена %d) — кадр из прошлой "
                      "редакции, его забанили уже после отправки прохода" % (n, _sid))
                rejected += 1
                continue
            _qs, _qd = _q_src.get(_sid), _q_dst.get(_sid)
            if _qs is not None and _qd is not None and _qs != _qd:
                print("   ЗАПРОС ПЕРЕПИСАН, НЕ БЕРУ: %s (сцена %d)" % (n, _sid))
                print("      было: %s" % _qs[:90])
                print("      стало: %s" % _qd[:90])
                rejected += 1
                continue
            _s = _st.get(n, "ok")
            if _s != "ok":
                _why = {"placeholder": "ЗАГЛУШКА «нет кадра», а не кадр",
                        "card_pending": "рисованный кадр, его отрисует cards_cloud",
                        "library_pending": "сцена медиатеки — кадр берётся "
                                           "локально, в облаке её нет",
                        "not_supported": "формат не поддержан фетчером",
                        "banned": "забанен на стороне облака"}.get(
                            _s, "статус «%s» — не «ok»" % _s)
                print("   НЕ БЕРУ: %s (сцена %d) — %s" % (n, _sid, _why))
                holes.setdefault(_s, []).append(_sid)
                rejected += 1
                continue
            dp = os.path.join(d_dir, n)
            # ДВЕ СБОРКИ В ОДНОЙ ПАПКЕ (та же гоча, 31.10): у сцены уже лежал
            # свой `scene_NNN.mp4` из базы, а сверху ложился `scene_NNN.jpg`
            # из забора — сборщик брал ОДИН из двух, и какой именно, зависело
            # от порядка глоба. Кадр, который уже есть, не перекрываем ничем
            # другого формата: конфликт называется и решается вкладкой.
            _other = [q for q in glob.glob(os.path.join(d_dir, "scene_%03d.*" % _sid))
                      if _sid >= 0 and os.path.basename(q) != n
                      and os.path.splitext(q)[1].lower() in _IMG + _VID]
            if _other and not force:
                print("   НЕ КЛАДУ РЯДОМ: %s (сцена %d) — у сцены уже есть "
                      "%s. Двух кадров на одну сцену быть не должно: сборщик "
                      "возьмёт любой." % (n, _sid,
                                          ", ".join(os.path.basename(q) for q in _other)))
                clashes.append(_sid)
                rejected += 1
                continue
            if os.path.exists(dp) and not force:
                skipped += 1
                continue
            if not dry:
                shutil.copy2(sp, dp)
            moved += 1
        print("   перенесено %d, пропущено (уже есть) %d" % (moved, skipped))
        total_moved += moved
        total_skipped += skipped

    print("ИТОГО перенесено %d, пропущено %d%s" % (
        total_moved, total_skipped,
        (", ОТКЛОНЕНО %d (статус, бан, переписанный запрос или столкновение "
         "форматов)" % rejected) if rejected else ""))
    if holes.get("placeholder"):
        _ph = sorted(set(holes["placeholder"]))
        print("\n!! ЗАГЛУШКИ, НУЖЕН ДОБОР — %d сцен: %s" % (
            len(_ph), ", ".join(str(x) for x in _ph)))
        print("   Это кадры, которых фетч НЕ НАШЁЛ. Они не перенесены, и в "
              "сверке ниже честно числятся «без кадра».")
    for _s, _ids in sorted(holes.items()):
        if _s == "placeholder":
            continue
        print("!! статус «%s» — %d сцен: %s" % (
            _s, len(set(_ids)), ", ".join(str(x) for x in sorted(set(_ids)))))
    if clashes:
        print("!! У %d СЦЕН КАДР УЖЕ БЫЛ в другом формате: %s — из забора не "
              "брал, разберись какой нужен." % (
                  len(set(clashes)), ", ".join(str(x) for x in sorted(set(clashes)))))
    sf = _scenes_file(dst, quiet=True) or _scenes_file(src, quiet=True)
    if sf:
        scenes = _load(sf).get("scenes", [])
        have = set()
        for p in glob.glob(os.path.join(dst, "images", "scene_*")):
            if os.path.splitext(p)[1].lower() in _IMG + _VID:
                try:
                    have.add(int(os.path.basename(p).split("_")[1].split(".")[0]))
                except (IndexError, ValueError):
                    pass
        no = [s.get("id") for s in scenes if s.get("id") not in have
              and not str(s.get("source", "")).startswith("card")]
        print("\nсверка со сценарием %s: сцен %d, кадров на месте %d, без кадра %d"
              % (os.path.basename(sf), len(scenes), len(have), len(no)))
        if no:
            print("  без кадра: %s" % ", ".join(str(x) for x in no[:30]))
    if dry:
        print("\n--dry-run: ничего не скопировано")
    if missing:
        print("!! %d файлов из манифеста не нашлось в заборе" % missing)
    return 1 if missing else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(adopt(args[0], args[1],
                   dry="--dry-run" in sys.argv, force="--force" in sys.argv))
