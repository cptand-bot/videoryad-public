#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parallel wrapper around fetch_assets_news.py.

The per-scene fetch is embarrassingly parallel (scene N's search doesn't
depend on scene M's), but the two rate-limit-prone providers — Yandex and
Wikimedia — ban the IP if hit too fast. So:

  * K worker processes run at once, each on a slice of the scenes;
  * fetch_assets_news._pace() (via FETCH_PACE_DIR) throttles Yandex/Wikimedia
    to one global call per N seconds no matter how many workers;
  * every OTHER provider (Openverse / Archive / Flickr / Pexels API / the
    image downloads) runs fully in parallel — and most scenes resolve there
    before ever reaching Yandex;
  * library folders are kept whole inside ONE worker so the folder
    round-robin / no-repeat logic stays correct;
  * a final serial pass repairs any cross-worker md5 collision (two workers
    grabbing the same web image for different scenes).

Usage:  python3 fetch_parallel.py <scenes.json> <images-dir> <.env> [K]
        K defaults to 5.  K=1 just calls the serial fetcher.

Everything the serial fetcher guarantees (no fabrication, OCR/watermark
reject, cooldown, video-lead-safe classification) is unchanged — this only
changes HOW MANY scenes are in flight at once.
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def lib_bucket(scene):
    """A key that must stay inside one worker: the library folder (so its
    round-robin isn't split across processes). Non-library scenes return
    None and get spread round-robin."""
    if scene.get("source") != "local_library":
        return None
    q = scene.get("source_query", "")
    q = q.split(":", 1)[0]                 # tag:keyword -> tag
    if "/" in q and os.path.splitext(q)[1]:  # explicit file -> its folder
        q = os.path.dirname(q)
    return q or "misc"


def partition(scenes, k):
    """k lists of scenes, balanced by count, library folders kept whole."""
    shards = [[] for _ in range(k)]
    load = [0] * k
    # library scenes grouped by folder, biggest groups first
    groups = {}
    loose = []
    for s in scenes:
        b = lib_bucket(s)
        (groups.setdefault(b, []) if b else loose).append(s)
    for grp in sorted(groups.values(), key=len, reverse=True):
        i = load.index(min(load))
        shards[i] += grp
        load[i] += len(grp)
    for s in loose:                        # spread the rest onto the lightest
        i = load.index(min(load))
        shards[i].append(s)
        load[i] += 1
    return [sh for sh in shards if sh]


def _local_only_gate(scenes_path, images_dir):
    """НА МАШИНЕ ПОЛЬЗОВАТЕЛЯ ФЕТЧИМ ТОЛЬКО МЕДИАТЕКУ (03.11, улов `usuario-79`).

    Прямое правило пользователя от 23.10: «при сборке... ни в коем случае не
    использовать ресурсы компьютера, всё, что можно сделать на GitHub, всё
    отсылать в GitHub». Медиатеки в облаке нет, поэтому библиотечные сцены
    добираются локально — и ТОЛЬКО они. Но в чек-листе рядом со словами
    «дофетчить библиотечные сцены локально» стояла команда на ПОЛНЫЙ
    `scenes.json`: вкладка запускала её буквально и гнала ВЕБ-ПОИСК на машине
    пользователя параллельно с облаком (живой случай — успело скачаться 14
    сцен, пока вкладка не сняла процесс). Вкладки обходили это, собирая файл
    только из `local_library` руками — в делах сданных роликов такие файлы
    лежат, то есть каждая доходила до обхода сама.

    Теперь это не договорённость, а поведение: веб-сцены отбрасываются, в
    работу идут только библиотечные. Снять — `VIDEORYAD_LOCAL_OK=1` (тот же
    ключ, что у локального рендера карточек) или `--web`.
    """
    data = json.load(open(scenes_path, encoding="utf-8"))
    scenes = data.get("scenes") or []
    lib = [s for s in scenes if s.get("source") == "local_library"]
    web = [s for s in scenes if s.get("source") != "local_library"]
    if not web:
        return scenes_path
    if os.environ.get("VIDEORYAD_LOCAL_OK") == "1" or "--web" in sys.argv:
        print("[parallel] ВНИМАНИЕ: веб-фетч %d сцен идёт НА МАШИНЕ "
              "ПОЛЬЗОВАТЕЛЯ (снято ключом) — это его ресурсы и его сеть."
              % len(web), flush=True)
        return scenes_path
    print("[parallel] локально фетчим ТОЛЬКО медиатеку: беру %d библиотечных "
          "сцен, отбрасываю %d веб-сцен (%s…)."
          % (len(lib), len(web),
             ", ".join(str(s.get("id")) for s in web[:8])), flush=True)
    print("[parallel] веб-сцены собирает ОБЛАКО (ship.sh). Нужен веб локально "
          "— VIDEORYAD_LOCAL_OK=1 или ключ --web, и скажи об этом "
          "пользователю.", flush=True)
    if not lib:
        print("[parallel] библиотечных сцен в файле нет — делать нечего.",
              flush=True)
        return ""
    # ДОБОР ТРОГАЕТ ТОЛЬКО ПУСТЫЕ СЦЕНЫ (03.11, улов `usuario-0d`). Библиотечная
    # ветка фетчера выбирает файл папки ЗАНОВО на каждом запуске, поэтому проход
    # по ПОЛНОМУ файлу ради нескольких пустых сцен молча менял кадры, уже
    # утверждённые глазами: у вкладки так сменились девять файлов, включая три
    # утверждённые час назад (сцены 3, 9, 16 — их в `--fix` не было вовсе).
    # Опаснее всего то, что утверждение и приговоры внешнего агента держатся
    # ровно на обратном: утверждённый кадр больше не меняется.
    # Поэтому: сцена с ЖИВЫМ кадром не трогается. Облачная заглушка кадром не
    # считается (её для этого и заменяют локально), забаненный файл тоже.
    # Снять — `--all` (переснять всё заново осознанно).
    if "--all" not in sys.argv:
        try:
            from fetch_assets_news import _looks_like_cloud_stub, \
                load_banned_md5, file_md5
            _ban = load_banned_md5()
        except Exception:
            _looks_like_cloud_stub = None
            _ban, file_md5 = set(), None
        _empty, _busy_ids = [], []
        for sc in lib:
            sid = sc.get("id")
            have = [f for f in glob.glob(
                os.path.join(images_dir, "scene_%03d.*" % (sid or 0)))
                if os.path.getsize(f) > 0
                and not f.endswith((".json", ".text.png", ".lock"))
                and ".ovthumb." not in f]
            _live = ""
            for f in have:
                if _looks_like_cloud_stub and _looks_like_cloud_stub(f):
                    continue
                if file_md5 and _ban and file_md5(f) in _ban:
                    continue
                _live = f
                break
            (_busy_ids if _live else _empty).append(sid)
        if _busy_ids:
            print("[parallel] у %d библиотечных сцен кадр УЖЕ СТОИТ — не "
                  "трогаю (%s). Раздача по кругу выбрала бы другой файл и "
                  "сменила утверждённый кадр."
                  % (len(_busy_ids), ", ".join(map(str, _busy_ids[:12]))),
                  flush=True)
            print("[parallel] переснять конкретные сцены — refetch.py; "
                  "переснять ВСЁ осознанно — ключ --all.", flush=True)
        if not _empty:
            print("[parallel] пустых библиотечных сцен нет — делать нечего.",
                  flush=True)
            return ""
        lib = [sc for sc in lib if sc.get("id") in set(_empty)]
    sub = {x: data[x] for x in data if x != "scenes"}
    sub["scenes"] = lib
    os.makedirs(images_dir, exist_ok=True)
    out = os.path.join(images_dir, ".local_only.scenes.json")
    json.dump(sub, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return out


def run(scenes_path, images_dir, env_path, k):
    scenes_path = _local_only_gate(scenes_path, images_dir)
    if not scenes_path:
        return 0
    data = json.load(open(scenes_path, encoding="utf-8"))
    scenes = data["scenes"]
    meta = {x: data[x] for x in data if x != "scenes"}

    if k <= 1 or len(scenes) <= 6:
        env = dict(os.environ)
        subprocess.run([sys.executable, os.path.join(HERE, "fetch_assets_news.py"),
                        scenes_path, images_dir, env_path], env=env, check=False)
        return

    sd = os.path.join(images_dir, ".shards")
    # ОБЩИЙ НА ВСЮ МАШИНУ, а не на проект (2026-10-12). Раньше замок лежал в
    # images/.pace самого проекта, то есть каждая вкладка притормаживала только
    # СЕБЯ. При четырёх параллельных вкладках к Яндексу уходило 4 запроса за
    # те же 2.5с — вчетверо выше задуманного, с ОДНОГО домашнего адреса. Это
    # прямой путь под бан, и чем больше роликов мы переводим на локальный
    # поиск (ради экономии минут GitHub), тем вернее мы в него упираемся.
    # Теперь все вкладки делят один замок: суммарный темп к Яндексу остаётся
    # 1 запрос / 2.5с независимо от числа вкладок. Каждая вкладка от этого
    # медленнее, но ни одна не попадает под блокировку.
    # Переопределить (например для изолированного теста) — FETCH_PACE_DIR.
    pace = os.environ.get("FETCH_PACE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "videoryad-pace")
    os.makedirs(pace, exist_ok=True)
    os.makedirs(sd, exist_ok=True)
    for f in glob.glob(os.path.join(pace, "*.lock")):
        # ГОЧА 2026-10-16: два fetch_parallel.py, запущенные одновременно (например
        # база в images/ и всплывашки в overlays/), делят ОДИН каталог пейсинга.
        # Второй падал здесь с FileNotFoundError ещё до начала работы — файл уже
        # снёс первый. Выглядело как «фетч отработал», а сцены оставались без
        # кадра, потому что старые файлы к тому моменту уже удалены вызывающим.
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    parts = partition(scenes, k)
    print(f"[parallel] {len(scenes)} сцен -> {len(parts)} потоков "
          f"({', '.join(str(len(p)) for p in parts)}), пейсинг Yandex/Wikimedia общий",
          flush=True)

    procs = []
    for i, part in enumerate(parts):
        sp = os.path.join(sd, f"shard{i}.scenes.json")
        json.dump({**meta, "scenes": part}, open(sp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        env = dict(os.environ)
        env["MANIFEST_NAME"] = f"manifest.shard{i}.json"
        env["FETCH_PACE_DIR"] = pace
        lg = open(os.path.join(images_dir, f".shard{i}.log"), "w")
        procs.append(subprocess.Popen(
            [sys.executable, os.path.join(HERE, "fetch_assets_news.py"),
             sp, images_dir, env_path], env=env, stdout=lg, stderr=subprocess.STDOUT))

    total = len(scenes)
    while any(p.poll() is None for p in procs):
        done = len(glob.glob(os.path.join(images_dir, "scene_*.*")))
        print(f"[parallel] {time.strftime('%H:%M:%S')} кадры ~{done}/{total}", flush=True)
        time.sleep(20)
    # ПАДЕНИЕ ВОРКЕРА — ГРОМКО (2026-10-22, улов `usuario-ec`; тот же класс
    # ловился 18.10 и вернулся). Коды возврата не проверялись вовсе: воркер
    # падал с трейсбеком в свой `.shardN.log`, манифеста шарда не появлялось, и
    # итоговая строка печатала «готово: 0/28 FAILED=[]» — пустой список провалов
    # при нулевом коде читается как «всё уже на месте». Живой случай: добор на
    # 28 сцен отработал за секунду и не скачал НИЧЕГО (NameError на `re`),
    # поймано только сверкой числа файлов глазами.
    _dead = []
    for i, p in enumerate(procs):
        rc = p.wait()
        if rc != 0:
            _dead.append((i, rc))
    for i, rc in _dead:
        lg = os.path.join(images_dir, f".shard{i}.log")
        print(f"[parallel] !! ВОРКЕР shard{i} УПАЛ, код {rc} — его сцены НЕ "
              f"фетчились. Хвост {lg}:", flush=True)
        try:
            with open(lg, encoding="utf-8", errors="replace") as f:
                tail = f.read().splitlines()[-15:]
            for ln in tail:
                print("        " + ln, flush=True)
        except OSError as e:
            print(f"        (лог не прочитать: {e})", flush=True)

    merge_manifests(images_dir, scenes)
    repaired = repair_collisions(scenes_path, images_dir, env_path)
    if repaired:
        merge_manifests(images_dir, scenes)

    m = json.load(open(os.path.join(images_dir, "manifest.json"), encoding="utf-8"))
    failed = sorted(x["id"] for x in m if x["status"] == "FAILED")
    print(f"[parallel] готово: {len(m)}/{total}  FAILED={failed}", flush=True)
    # СЦЕНЫ, ПО КОТОРЫМ НЕТ ЗАПИСИ ВОВСЕ — это не «не нашлось», а «не фетчили»
    _no_rec = sorted({s["id"] for s in scenes} - {x.get("id") for x in m})
    if _no_rec:
        print(f"[parallel] !! БЕЗ ЗАПИСИ В МАНИФЕСТЕ {len(_no_rec)} сцен: "
              f"{_no_rec} — их воркер не обработал (упал или не успел). "
              f"Запросы тут ни при чём, нужен добор именно этих сцен.",
              flush=True)
    # ИТОГ СЧИТАЕМ ПО ФАЙЛАМ НА ДИСКЕ, А НЕ ПО МАНИФЕСТУ (23.10, улов
    # `usuario-7b`). Сцена со статусом FAILED — это запись в манифесте, то есть
    # для прежней проверки она «обработана»: воркеры не падали, записи есть,
    # код возврата 0. Живой случай: фетч 17 всплывашек встал на 9 из 17, exit 0,
    # ни ошибки, ни списка провалов — читается как «всё на месте». Теперь
    # сверяем то единственное, что имеет значение, — ЕСТЬ ЛИ ФАЙЛ.
    _skip_ext = (".json", ".text.png", ".lock", ".log")
    _missing = []
    for sc in scenes:
        if str(sc.get("source", "")).startswith("card"):
            continue            # карточки рисуются у нас, файла в фетче и не ждём
        _sid = sc["id"]
        _have = [f for f in glob.glob(os.path.join(images_dir, "scene_%03d.*" % _sid))
                 if os.path.getsize(f) > 0 and not f.endswith(_skip_ext)]
        if not _have:
            _missing.append(_sid)
    if _missing:
        print(f"[parallel] !! НЕТ ФАЙЛА У {len(_missing)} СЦЕН из {total}: "
              f"{_missing}", flush=True)
        print("[parallel]    это итог ПО ДИСКУ, а не по манифесту: часть сцен "
              "осталась без кадра, хотя воркеры не падали. Нужен повторный "
              "проход именно по этим сценам.", flush=True)
    if _dead or _no_rec or _missing:
        print(f"[parallel] итог: НЕУСПЕХ — упавших воркеров {len(_dead)}, "
              f"сцен без записи {len(_no_rec)}, сцен без файла {len(_missing)}",
              flush=True)
        return 1
    print(f"[parallel] итог: все {total} сцен имеют файл на диске", flush=True)
    return 0


def merge_manifests(images_dir, scenes):
    order = {s["id"]: i for i, s in enumerate(scenes)}
    seen, rows = set(), []
    for mf in sorted(glob.glob(os.path.join(images_dir, "manifest.shard*.json"))):
        try:
            for row in json.load(open(mf, encoding="utf-8")):
                if row["id"] not in seen:
                    seen.add(row["id"])
                    rows.append(row)
        except Exception:
            pass
    rows.sort(key=lambda r: order.get(r["id"], 1 << 30))
    json.dump(rows, open(os.path.join(images_dir, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def repair_collisions(scenes_path, images_dir, env_path):
    """Two workers may have grabbed the same web image for different scenes
    (their _WEB_USED_MD5 sets aren't shared). Keep it on the lowest scene id,
    drop the copies, and re-fetch those scenes SERIALLY (the serial fetcher
    scans images/ for md5s already in use, so it won't repeat them)."""
    by_hash = {}
    for p in glob.glob(os.path.join(images_dir, "scene_*.*")):
        if os.path.splitext(p)[1].lower() not in (".jpg", ".jpeg", ".png", ".webp", ".mp4"):
            continue
        if ".text." in os.path.basename(p):   # review.py's own text-popup render cache, not an asset
            continue
        sid = int(os.path.basename(p).split("_")[1].split(".")[0])
        by_hash.setdefault(md5(p), []).append((sid, p))
    victims = []
    for sids in by_hash.values():
        if len(sids) > 1:
            for sid, p in sorted(sids)[1:]:
                os.remove(p)
                victims.append(sid)
    if not victims:
        return False
    print(f"[parallel] коллизии кадров у сцен {sorted(victims)} — перекачиваю серийно", flush=True)
    data = json.load(open(scenes_path, encoding="utf-8"))
    sub = {k: data[k] for k in data if k != "scenes"}
    sub["scenes"] = [s for s in data["scenes"] if s["id"] in set(victims)]
    rp = os.path.join(images_dir, ".shards", "repair.scenes.json")
    json.dump(sub, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    env = dict(os.environ)
    env["MANIFEST_NAME"] = "manifest.shardR.json"
    # НАМЕРЕННО НЕ трогаем FETCH_PACE_DIR: этот проход тоже ходит в Яндекс, и
    # ограничитель ему нужен. Раньше здесь стоял env.pop(...) — он имел смысл,
    # пока пустое значение делало _pace() пустышкой. После 2026-10-12 пустого
    # значения больше нет (по умолчанию общий замок ~/.cache/videoryad-pace),
    # поэтому та же строка значила бы ровно обратное задуманному. Убрана, чтобы
    # следующий читатель не «починил» её назад и не снял throttling.
    subprocess.run([sys.executable, os.path.join(HERE, "fetch_assets_news.py"),
                    rp, images_dir, env_path], env=env, check=False)
    return True


def _zamorozheno_stop(path_hint="."):
    """УТВЕРЖДЕНО — ЗНАЧИТ ЗАМОРОЖЕНО (Z-0019/Z-0020). Фетч — такая же
    правка состава, как замена кадра: после его «утверждаю» он не идёт.
    Вставлено 11.11 (`НА-РАСКАТКУ` п.14): у этого файла нет `main()`,
    поэтому проверка стоит в точке входа, а не декоратором.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from zamorozka import zamorozheno
        pdir = os.path.abspath(path_hint if os.path.isdir(path_hint)
                               else os.path.dirname(os.path.abspath(path_hint)) or ".")
        for _ in range(3):
            if os.path.exists(os.path.join(pdir, ".utverzhdeno.json")):
                break
            pdir = os.path.dirname(pdir)
        if zamorozheno(pdir):
            print("ФЕТЧ ЗАПРЕЩЁН: дашборд этого ролика утверждён. "
                  "Находку неси координатору — пересборку назначает пользователь.",
                  file=sys.stderr)
            raise SystemExit(3)
    except SystemExit:
        raise
    except Exception:
        pass            # нет модуля/метки — работаем как раньше


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: fetch_parallel.py <scenes.json> <images-dir> <.env> [K=5]")
        sys.exit(1)
    _zamorozheno_stop(sys.argv[1])
    K = int(sys.argv[4]) if len(sys.argv) > 4 else 5
    # код возврата ненулевой при упавшем воркере — `refetch.py` его УЖЕ
    # проверяет и печатает «ФЕТЧ УПАЛ», просто получать было нечего
    sys.exit(run(sys.argv[1], sys.argv[2], sys.argv[3], K) or 0)
