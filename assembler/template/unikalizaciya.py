#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ВТОРОЙ РОЛИК НА ТЕХ ЖЕ КАДРАХ — БЕЗ ПОИСКА (07.11.2026).

    python3 unikalizaciya.py <проект-оригинала> <проект-рерайта> [--seed 7]

ЗАЧЕМ. Каналы-клоны берут одну тему, и поиск по второму тексту всё равно
принесёт те же самые кадры — только потратив на это всё время фетча и весь
трафик. Его прямое слово 07.11: «не бегать и не занимать время и токены
другими изображениями, просто что-то уникализировать, да и всё».

ЧТО ДЕЛАЕМ. Берём готовые кадры первого ролика, раскладываем под сцены
второго и меняем их ТЕХНИЧЕСКИ:
  · зеркало по горизонтали — но только там, где в кадре нет текста
    (вывеска, титр, флаг с надписью в отражении читаются как брак, поэтому
    перед зеркалом кадр проверяется распознаванием);
  · другая крупность — лёгкий срез с одной из сторон меняет композицию;
  · другой порядок внутри группы взаимозаменяемых сцен.

ЧЕГО НЕ ДЕЛАЕМ. Не двигаем кадр далеко от его сцены: он подбирался под
смысл конкретной реплики, и уехав на три сцены вперёд, он перестанет
соответствовать тексту. Перестановка — только внутри группы сцен с
близким визуальным заданием.

Эффекты, переходы и карточки сюда не входят: их ставит `fx_put.py --auto`,
он сам знает канал и сам даёт второму каналу другой набор.
"""
import argparse
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys

STOP = set("и в во не на с со а но что как для от до по за из у о об к "
           "это этот эта эти тот та те над под при про без через между".split())


def load_scenes(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["scenes"] if isinstance(d, dict) else d


def scenes_path(project):
    cands = [os.path.join(project, n) for n in os.listdir(project)
             if n.endswith(".scenes.json")]
    if not cands:
        sys.exit("нет .scenes.json в %s" % project)
    return max(cands, key=os.path.getsize)


def bag(scene):
    """Значимые слова сцены: по ним ищем, какой кадр ей подходит."""
    s = " ".join(str(scene.get(k) or "") for k in
                 ("visual_prompt", "source_query", "text"))
    return {w for w in re.findall(r"[А-Яа-яЁёA-Za-z]{4,}", s.lower())
            if w not in STOP}


# Распознавание стоит не в системе, а разложенным вручную: на этой машине
# нет apt и sudo (см. fetch_assets_news.py). Звать просто «tesseract» нельзя —
# его нет в PATH, вызов падает FileNotFoundError, функция честно отвечает
# «текст есть», и зеркало не применяется НИКОГДА. Ровно это и случилось при
# первой проверке 07.11: 12 кадров из 12 «с текстом».
_TESS = os.path.expanduser("~/tools/tesseract/usr/bin/tesseract")
_TESS_LIB = os.path.expanduser("~/tools/tesseract/usr/lib/x86_64-linux-gnu")
_TESS_DATA = os.path.expanduser("~/tools/tesseract/usr/share/tesseract-ocr/5/tessdata")


def _tess_env():
    env = os.environ.copy()
    if os.path.isdir(_TESS_LIB):
        env["LD_LIBRARY_PATH"] = _TESS_LIB + ":" + env.get("LD_LIBRARY_PATH", "")
    if os.path.isdir(_TESS_DATA):
        env["TESSDATA_PREFIX"] = _TESS_DATA
    return env


def has_text(path):
    """Есть ли в кадре читаемый текст — зеркалить такой нельзя."""
    if not path.lower().endswith((".jpg", ".jpeg", ".png")):
        return True          # видео не проверяем, зеркалим осторожно: считаем «есть»
    # Читаем не просто текст, а таблицу с УВЕРЕННОСТЬЮ: на обычной
    # фотографии распознавание всегда выдаёт мусорные «слова» из шума
    # (проверено 07.11 — 12 кадров из 12 ложно объявлялись текстовыми, и
    # зеркало не применялось никогда). Уверенность отсекает шум.
    try:
        binary = _TESS if os.path.exists(_TESS) else "tesseract"
        out = subprocess.run([binary, path, "-", "-l", "rus+eng",
                              "--psm", "11", "tsv"],
                             capture_output=True, text=True, timeout=60,
                             env=_tess_env()).stdout
    except (OSError, subprocess.SubprocessError):
        return True          # нет распознавания — считаем, что текст есть
    good = 0
    for line in out.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        word = cols[11].strip()
        if conf >= 70 and len(re.findall(r"[A-Za-zА-Яа-яЁё]", word)) >= 4:
            good += 1
    return good >= 2


def transform(src, dst, mirror, crop_pct):
    """Зеркало и срез — одним проходом ffmpeg, и для фото, и для видео."""
    filters = []
    if crop_pct:
        k = 1.0 - crop_pct / 100.0
        filters.append("crop=iw*%.4f:ih*%.4f:(iw-iw*%.4f)*%s:(ih-ih*%.4f)*%s"
                       % (k, k, k, "0" if crop_pct % 2 else "1",
                          k, "1" if crop_pct % 2 else "0"))
    if mirror:
        filters.append("hflip")
    if not filters:
        shutil.copy2(src, dst)
        return "копия"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", ",".join(filters)]
    if dst.lower().endswith(".mp4"):
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
                "-threads", "2", "-c:a", "copy"]
    else:
        cmd += ["-q:v", "2"]
    cmd.append(dst)
    r = subprocess.run(["nice", "-n", "19"] + cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        shutil.copy2(src, dst)
        return "копия (ffmpeg не справился)"
    return ("зеркало" if mirror else "") + (" + срез %d%%" % crop_pct if crop_pct else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source_project", help="проект первого ролика (с images/)")
    ap.add_argument("target_project", help="проект второго ролика (сцены рерайта)")
    ap.add_argument("--seed", type=int, default=0, help="зерно случайности")
    ap.add_argument("--no-mirror", action="store_true", help="не зеркалить вовсе")
    ap.add_argument("--wrap", type=int, default=35,
                    help="сколько процентов кадров донора ОБЕРНУТЬ в наш "
                         "элемент вместо прямой постановки (по умолчанию 35)")
    ap.add_argument("--share", type=int, default=80,
                    help="сколько процентов сцен закрывать кадрами донора "
                         "(по умолчанию 80, остальное — своё)")
    args = ap.parse_args()
    rnd = random.Random(args.seed or None)

    src_imgs = os.path.join(args.source_project, "images")
    man_path = os.path.join(src_imgs, "manifest.json")
    if not os.path.exists(man_path):
        sys.exit("у первого ролика нет images/manifest.json — кадры ещё не найдены")
    man = {int(m["id"]): m for m in json.load(open(man_path, encoding="utf-8"))
           if m.get("status") == "ok" and m.get("file")}

    src_scenes = {int(s["id"]): s for s in load_scenes(scenes_path(args.source_project))}
    tgt_path = scenes_path(args.target_project)
    tgt_scenes = load_scenes(tgt_path)

    dst_imgs = os.path.join(args.target_project, "images")
    os.makedirs(dst_imgs, exist_ok=True)

    # мешки слов кадров-доноров
    donors = []
    _skipped_cards = []
    for sid, m in man.items():
        sc = src_scenes.get(sid)
        if sc is None:
            continue
        # РИСОВАННЫЙ КАДР ДОНОРА В ПУЛ НЕ БЕРЁМ ВООБЩЕ (БЛОКЕР 07.11, улов
        # вкладки `usuario-2c`, 25 кадров в трёх роликах). `images/` донора
        # содержит не только найденные фотографии, но и ОТРИСОВАННЫЕ
        # карточки — плакаты, цитаты, диаграммы. Уникализатор брал их как
        # обычные кадры, и на канал ПЛАНЕТА уезжал готовый плакат канала
        # «5 МИНУТ» вместе с его вотермаркой — тот же самый кадр, что в
        # ролике-близнеце. То есть на этих сценах уникализация не
        # состоялась в принципе, да ещё и чужой знак в эфире.
        # Карточка принадлежит своему каналу и своему ролику: у неё свой
        # watermark, своя гамма, свой текст. Второй канал рисует СВОИ.
        if str(sc.get("source", "")).startswith("card:"):
            _skipped_cards.append(sid)
            continue
        donors.append((sid, bag(sc), m))
    if _skipped_cards:
        print("  рисованных кадров донора пропущено: %d (сцены %s) — "
              "карточки принадлежат своему каналу, второй рисует свои"
              % (len(_skipped_cards), ", ".join(map(str, sorted(_skipped_cards)[:12]))))

    # ── ПОДБОР ДОНОРОВ: ГЛОБАЛЬНО, С УЧЁТОМ ЗАНЯТОСТИ ──────────────────
    # ЖАДНО «ПО ОДНОЙ СЦЕНЕ» НЕЛЬЗЯ (07.11, улов вкладки `usuario-2c`).
    # Первая версия шла по сценам подряд и каждой давала лучшего донора, не
    # помня, что он уже отдан: из 82 кадров донора использовался 61, двадцать
    # один не тронут вовсе, четырнадцать поставлены по два-три раза, а восемь
    # сцен остались ВООБЩЕ без кадра. Плюс дубль файла внутри ролика — на нём
    # встаёт `selfcheck` (внутри сборки файл ровно один раз).
    # Поэтому считаем ВСЕ пары «сцена-донор», сортируем по качеству совпадения
    # и раздаём сверху вниз: занятый донор выбывает, занятая сцена тоже.
    targets = [sc for sc in tgt_scenes
               if not str(sc.get("source", "")).startswith("card:")]
    for sc in tgt_scenes:
        if str(sc.get("source", "")).startswith("card:"):
            pass

    pairs = []
    for sc in targets:
        tid = int(sc["id"])
        b = bag(sc)
        for sid, db, m in donors:
            inter = len(b & db)
            score = inter / max(1, len(b | db))
            # кадр соседней по счёту сцены ближе по смыслу, чем далёкий
            score -= 0.002 * abs(sid - tid)
            score += 0.0001 * rnd.random()
            pairs.append((score, tid, sid, m))
    pairs.sort(key=lambda x: -x[0])

    # ДОНОР ЗАКРЫВАЕТ НЕ БОЛЬШЕ 80% СЦЕН (07.11, его слово по дашборду
    # 8802): «если мы взяли 100% кадров, поменяли канал и поменяли их
    # местами — фигня какая-то. Нужно хотя бы процентов 20 добавлять
    # других. Или на место них делать свои эффекты, цитаты».
    # Иначе второй ролик — перекрашенная копия первого: те же кадры в том
    # же порядке, только зеркальные. Оставшаяся пятая часть закрывается
    # СВОИМ: кадром своей медиатеки или своим элементом — в `card_put.py`
    # двадцать два вида, а в деле сегодня девять.
    _limit = max(1, int(len(targets) * max(10, min(100, args.share)) / 100.0))
    assigned = {}          # сцена -> (донор, запись манифеста)
    busy_donors = set()
    for score, tid, sid, m in pairs:
        if len(assigned) >= _limit:
            break
        if tid in assigned or sid in busy_donors:
            continue
        assigned[tid] = (sid, m)
        busy_donors.add(sid)

    # ДОНОРЫ КОНЧИЛИСЬ — ТОЛЬКО ТОГДА ПОВТОР, И НЕ БЛИЖЕ 90 СЕКУНД.
    # Это правило «c» боевого конвейера: один и тот же кадр дважды допустим
    # лишь разнесённым по времени, рядом стоящие повторы — брак.
    def _start(tid):
        for sc in targets:
            if int(sc["id"]) == tid:
                return float(sc.get("start_sec") or 0)
        return 0.0

    for sc in targets:
        tid = int(sc["id"])
        if tid in assigned or len(assigned) >= _limit:
            continue
        b = bag(sc)
        best, best_score = None, -1e9
        for sid, db, m in donors:
            far = all(abs(_start(tid) - _start(t)) > 90
                      for t, (s2, _m2) in assigned.items() if s2 == sid)
            if not far:
                continue
            score = len(b & db) / max(1, len(b | db)) - 0.002 * abs(sid - tid)
            if score > best_score:
                best, best_score = (sid, m), score
        if best:
            assigned[tid] = best

    # ── ПЕРЕНОС ФАЙЛОВ ────────────────────────────────────────────────
    new_man, report = [], []
    for sc in tgt_scenes:
        tid = int(sc["id"])
        if str(sc.get("source", "")).startswith("card:"):
            report.append("сцена %d — рисованный кадр, донор не нужен" % tid)
            continue
        if tid not in assigned:
            report.append("сцена %d — СВОЁ: кадр медиатеки своего канала или "
                          "свой элемент (donor не ставим по правилу 80%%)" % tid)
            continue
        sid, m = assigned[tid]
        # ФАЙЛ ИЩЕМ ПО ШАБЛОНУ, А НЕ ПО ИМЕНИ ИЗ МАНИФЕСТА (07.11, тот же
        # улов): в манифесте стояло `scene_076.jpg`, а на диске лежал
        # `scene_076.mp4` — кадр молча терялся с сообщением «файл донора
        # пропал». Манифест и диск расходятся по расширению всегда, когда
        # сцену переделали из фото в видео.
        src_file = os.path.join(src_imgs, m["file"])
        if not os.path.exists(src_file):
            alt = sorted(glob.glob(os.path.join(src_imgs,
                                                "scene_%03d.*" % sid)))
            alt = [a for a in alt if ".ovthumb." not in a and ".text." not in a]
            if alt:
                src_file = alt[0]
            else:
                report.append("сцена %d — файл донора %d не найден" % (tid, sid))
                continue
        ext = os.path.splitext(src_file)[1]
        name = "scene_%03d%s" % (tid, ext)
        dst_file = os.path.join(dst_imgs, name)

        mirror = (not args.no_mirror) and rnd.random() < 0.6 and not has_text(src_file)
        crop = rnd.choice([0, 3, 4, 6])
        how = transform(src_file, dst_file, mirror, crop)
        new_man.append({"id": tid, "file": name, "source": m.get("source", "reuse"),
                        "status": "ok", "reused_from": sid})
        report.append("сцена %d ← кадр сцены %d, %s" % (tid, sid, how or "как есть"))

    json.dump(new_man, open(os.path.join(dst_imgs, "manifest.json"), "w",
                            encoding="utf-8"), ensure_ascii=False, indent=2)
    for line in report:
        print("  %s" % line)
    _free = len(donors) - len({v[0] for v in assigned.values()})
    print("перенесено кадров: %d из %d сцен" % (len(new_man), len(tgt_scenes)))
    print("доноров: %d, использовано %d, свободных осталось %d"
          % (len(donors), len({v[0] for v in assigned.values()}), _free))
    # ── КАДР ДОНОРА УХОДИТ В НАШ ЭЛЕМЕНТ, А НЕ НА ВЕСЬ ЭКРАН ──────────
    # Его слово 07.11, после сдачи шести роликов: «визуальный ряд получился
    # очень близким, один в один. Можно эти картинки брать, но не вставлять
    # как есть. На „5 МИНУТ“ картинка была прямо на экран, а на ПЛАНЕТУ эта
    # же картинка уходит в наш элемент конструктора — где картинка слева,
    # справа надписи. Вот это совершенно другой визуал, хотя исходник тот
    # же. А ставить один к одному, пускай даже с разными эффектами, — это
    # совсем не то».
    # Зеркало и срез меняют кадр технически, но композиция остаётся той же,
    # и два ролика читаются как один. Элемент меняет САМ КАДР: снимок
    # становится частью композиции с текстом, рамкой и своей гаммой канала.
    # Поэтому часть перенесённых кадров помечается «в элемент»: файл
    # откладывается отдельно, а в отчёт идёт готовая команда.
    _wrap_n = int(len(new_man) * max(0, min(80, args.wrap)) / 100.0)
    _wrap_dir = os.path.join(args.target_project, "cards", "photo")
    _wrapped = []
    if _wrap_n:
        os.makedirs(_wrap_dir, exist_ok=True)
        # берём те, что РОВНО подходят под окно: фотографии, не видео
        _cand = [m for m in new_man if not m["file"].lower().endswith(".mp4")]
        rnd.shuffle(_cand)
        _views = ["photo", "split", "dof", "wall", "film_frame", "vyrezka"]
        for i, m in enumerate(_cand[:_wrap_n]):
            src_p = os.path.join(dst_imgs, m["file"])
            dst_p = os.path.join(_wrap_dir, m["file"])
            try:
                shutil.move(src_p, dst_p)
            except OSError:
                continue
            m["wrap"] = _views[i % len(_views)]
            _wrapped.append((m["id"], m["wrap"], dst_p))
        new_man = [m for m in new_man if "wrap" not in m]

    # ЧИСЛО КАДРОВ, РОЖДЁННЫХ КЛОНИРОВАНИЕМ, ПИШЕМ В SCENES.JSON (08.11).
    # Иначе двери (`card_put`, `element_put`) считают их перебором над нормой,
    # и вкладка ставит каждый через `--force`, глуша заодно проверку зазора.
    # `obyazatelno.норма`/`зазор` читают этот ключ и прибавляют его к
    # обязательным — ролик-клон живёт по своей норме, а не по норме оригинала.
    if _wrapped:
        try:
            _d = json.load(open(tgt_path, encoding="utf-8"))
            if isinstance(_d, dict):
                _d["clone_wrapped"] = len(_wrapped)
                json.dump(_d, open(tgt_path, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
                print("в %s записано clone_wrapped=%d — норма рисованных "
                      "кадров поднята на столько же"
                      % (os.path.basename(tgt_path), len(_wrapped)))
        except Exception as _e:
            print("  !! не смог записать clone_wrapped: %s" % _e)

    _own = len(targets) - len(new_man) - len(_wrapped)
    print("своих сцен оставлено: %d из %d (%d%%) — закрывай их кадром своей "
          "медиатеки или СВОИМ элементом" % (_own, len(targets),
                                             round(100 * _own / max(1, len(targets)))))
    if _wrapped:
        print("")
        print("В ЭЛЕМЕНТ (кадр донора НЕ на весь экран, а внутри композиции): "
              "%d шт." % len(_wrapped))
        print("Файлы отложены в cards/photo/. Поставь каждый своей командой,")
        print("текст возьми из реплики этой сцены:")
        # КОМАНДЫ ПЕЧАТАЮТСЯ ПОД ФАКТИЧЕСКИЕ ИНТЕРФЕЙСЫ (08.11, улов вкладки
        # `usuario-cd`). Раньше три подсказки из шести не работали ни в каком
        # виде: `style_card` не знает вида `split` (у него bullets, forces,
        # photo, timeline), у `element_put` вид идёт ПОЗИЦИОННО, а не ключом
        # `--view`, а `film_frame` и `vyrezka` живут вообще в другой двери —
        # `fullcycle/card_put.py`. Вкладка после такой печати гадает по
        # справкам, то есть подсказка стоила круга вместо того, чтобы его
        # сэкономить. Каждый вид теперь печатает СВОЮ дверь.
        _S = "~/.claude/skills/news-video"
        for sid, view, path in _wrapped:
            rel = os.path.relpath(path, args.target_project)
            if view == "photo":
                cmd = ('python3 %s/template/style_card.py <scenes> %d photo '
                       '--photo %s --item "..." --item "..."' % (_S, sid, rel))
            elif view == "split":
                cmd = ('python3 %s/template/quote_card.py <scenes> %d '
                       '--photo %s --text "..." --author "Фамилия"'
                       % (_S, sid, rel))
            elif view in ("dof", "wall"):
                cmd = ('python3 %s/template/element_put.py <scenes> %d %s '
                       '--photo %s' % (_S, sid, view, rel))
            elif view == "vyrezka":
                cmd = ('python3 %s/fullcycle/card_put.py <scenes> %d vyrezka '
                       '--photo %s --author "Фамилия"' % (_S, sid, rel))
            else:
                cmd = ('python3 %s/fullcycle/card_put.py <scenes> %d %s '
                       '--photo %s' % (_S, sid, view, rel))
            print("  сцена %-3d %-11s %s" % (sid, view, cmd))
    print("виды элементов, которые у нас есть и почти не идут в дело: "
          "quote, doc, duel, strike, paper_typed, paper_hand, slope, line, "
          "pie, map_regions, map_dist, vyrezka, vyrezka_kontur")
    print("поиск не запускался — фетч этому ролику не нужен")


if __name__ == "__main__":
    # НЕНУЛЕВОЙ КОД ВОЗВРАТА НА ЛЮБОМ СБОЕ (БЛОКЕР 07.11, улов вкладки
    # `usuario-2c`). Инструмент упал на `NameError` и всё равно отчитался
    # `exited with code 0` — то есть обёртка, проверяющая код возврата,
    # отправила бы в сборку ролик с одним кадром из пятидесяти семи.
    # Это тот самый класс «успех может значить ничего не сделано»: без
    # честного кода возврата инструмент нельзя ставить в конвейер вообще.
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print("СБОЙ УНИКАЛИЗАТОРА: %s — кадры НЕ перенесены" % exc)
        sys.exit(1)
