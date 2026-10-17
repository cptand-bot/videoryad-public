#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refetch.py — переписать запросы и дорефетчить ТОЛЬКО указанные id.

Зачем отдельный скрипт: фикс-раунды раньше писались ad-hoc каждый билд, и
2026-10-12 (ds-lyudey-net-1310) такой одноразовый скрипт держал список
правок ЗАШИТЫМ В КОДЕ. Второй запуск — ради всплывашек — молча прогнал
заново и весь батч сцен из первого раунда: лишний час веб-поиска на
кадрах, которые уже были исправлены. Здесь зашитых списков нет вообще:
что передал, то и чинится.

Использование (правки — JSON, id → запрос):
    python3 refetch.py --scenes ds.scenes.json \\
        --fix '{"37":["pexels_video","european city street tram"],
                "58":["press_photo","здание администрации реальное фото"]}'

    python3 refetch.py --overlays overlays_fetch.scenes.json \\
        --fix '{"24":"электромонтёры ремонт линии Украина реальное фото"}'

Оба файла сразу — ТОЛЬКО раздельными флагами (у сцен и всплывашек разный
формат значения, и один id может существовать в обоих файлах):
    python3 refetch.py --scenes s.json --overlays o.json \\
        --fix-scenes '{"13":["pexels_video","..."]}' \\
        --fix-overlays '{"2":"..."}'

Для сцен значение — пара [source, query]; для всплывашек — просто строка
(источник у них всегда press_photo). Можно чинить и то и другое за один
вызов, передав оба файла с их --fix.

Что делает: переписывает запрос, УДАЛЯЕТ старый файл (иначе инкрементальный
фетчер увидит его и скажет «cached», ничего не скачав — отдельные грабли),
пишет подмножество только из этих id и зовёт на нём fetch_parallel.

Перед фетчем гоняет query_lint.py на новых запросах — мина в замене
означает, что следующий круг аудита найдёт то же самое, что и прошлый.
"""
import glob
import json
import os
import subprocess
import sys

SKIP_EXT = (".json", ".text.png", ".lock")


def arg(name, default=None):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def wipe(d, sid):
    gone = []
    for f in glob.glob(os.path.join(d, "scene_%03d.*" % sid)):
        if not f.endswith(SKIP_EXT) and ".ovthumb." not in f:
            os.remove(f)
            gone.append(os.path.basename(f))
    return gone


def _md5(path):
    import hashlib
    try:
        return hashlib.md5(open(path, "rb").read()).hexdigest()
    except OSError:
        return None


def apply_fix(path, fixes, is_overlay):
    data = json.load(open(path, encoding="utf-8"))
    ids = {int(k) for k in fixes}
    assets = "overlays" if is_overlay else "images"
    before = {}   # id -> md5 удаляемого файла, для сверки после рефетча
    for s in data["scenes"]:
        if s["id"] not in ids:
            continue
        v = fixes[str(s["id"])]
        if is_overlay:
            s["source_query"] = s["visual_prompt"] = v
        else:
            s["source"], s["source_query"], s["visual_prompt"] = v[0], v[1], v[1]
        for old in glob.glob(os.path.join(assets, "scene_%03d.*" % s["id"])):
            if not old.endswith(SKIP_EXT) and ".ovthumb." not in old:
                before[s["id"]] = _md5(old)
        # ФАЙЛЫ ЗДЕСЬ НЕ УДАЛЯЮТСЯ. Раньше удаление шло до линта, и при
        # отказе линта сцены оставались вообще без кадров (cross-session,
        # 2026-10-12: так пропало 29 сцен, заметили случайно). Удаление
        # перенесено в commit_wipe() — строго ПОСЛЕ успешного линта.
    json.dump(data, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    sub = {"scenes": [s for s in data["scenes"] if s["id"] in ids]}
    out = ".refetch_%s.json" % assets
    json.dump(sub, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    return out, assets, sorted(ids), before


def report_same_file(assets, before):
    """Сток умеет вернуть РОВНО ТОТ ЖЕ файл на переписанный запрос — в логе
    «ok», а дефект на месте (cross-session, 2026-10-12: флаги Норвегии и
    испанская надпись DETENIDO вернулись после рефетча)."""
    same = []
    for sid, old in before.items():
        if not old:
            continue
        for f in glob.glob(os.path.join(assets, "scene_%03d.*" % sid)):
            if not f.endswith(SKIP_EXT) and ".ovthumb." not in f:
                if _md5(f) == old:
                    same.append(sid)
    if same:
        print("\n!! ВЕРНУЛСЯ ТОТ ЖЕ ФАЙЛ (%s): %s" % (assets, same))
        print("   Меняй не формулировку, а сам объект съёмки — источник "
              "отдаёт на этот смысл один и тот же кадр.")
    return same


def prune_needs_upload(path="needs_upload.json", only_ids=None):
    """Облако пишет сюда ненайденные сцены; после локального добора записи
    остаются и дашборд рисует ложные жёлтые карточки при живых кадрах.

    ТОЛЬКО ПО ЧИНИМЫМ id (2026-10-17). Раньше снимались ВСЕ записи, у которых
    на диске есть файл, — и вместе с ними СОЗНАТЕЛЬНЫЕ жёлтые карточки вкладки
    («кадр есть, но слабый — пусть заменит пользователь»). Круг правок по
    двум другим сценам молча стирал их обе (5min-gerasimov-1810, сцены 37 и
    46). Инструкция «ставить жёлтые карточки после последнего рефетча» не
    спасает: пока круги идут, какой из них последний — неизвестно."""
    if not os.path.exists(path):
        return
    try:
        nu = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return
    _ids = {str(i) for i in (only_ids or [])}
    alive = [k for k in nu if (not _ids or str(k) in _ids)
             and [f for f in glob.glob("images/scene_%03d.*" % int(k))
                  if not f.endswith(SKIP_EXT)]]
    if alive:
        for k in alive:
            nu.pop(k, None)
        json.dump(nu, open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("  needs_upload: снял жёлтые карточки с %s (кадры на месте)"
              % ", ".join(sorted(alive, key=int)))


SNAP = ".overlays.snapshot.json"


def snapshot(path):
    """Снять слепок overlays.json ПЕРЕД отправкой в облако."""
    ov = json.load(open(path, encoding="utf-8"))
    state = {k: {"photo": bool(v.get("photo")), "text": bool(v.get("text")),
                 "sound": v.get("sound", ""), "approved": bool(v.get("approved"))}
             for k, v in ov.items() if k.isdigit()}
    json.dump(state, open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_text = sum(1 for v in state.values() if v["text"])
    print("слепок: %d всплывашек (%d с текстом) → %s"
          % (len(state), n_text, SNAP))
    return 0


# ЗАГЛУШКА «нет кадра» ЛОВИТСЯ ПО СОДЕРЖИМОМУ, А НЕ ПО ВЕСУ.
# Первая версия проверяла точный размер 36864 — и промахнулась на следующей
# же сборке (cross-session, 2026-10-12): там заглушки весили 33999, 34000,
# 34002, 34004, потому что ширина номера сцены в подписи меняет размер
# файла. По той же причине у каждой УНИКАЛЬНЫЙ md5, так что признак «один
# файл в 3+ сценах» тоже молчит. Надёжный признак — сама картинка: почти
# однотонный тёмный прямоугольник, т.е. низкий разброс яркости.
STUB_STDDEV = 12.0   # разброс яркости ниже этого
STUB_MEAN = 60.0     # и средняя яркость ниже этого = заглушка
STUB_SIZES = {36864}  # исторический вес, оставлен как дополнительный сигнал
SMALL = 12 * 1024


def _looks_like_stub(path):
    """Почти однотонный тёмный кадр = облачная заглушка «нет кадра»."""
    if not path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return False
    try:
        from PIL import Image, ImageStat
        st = ImageStat.Stat(Image.open(path).convert("L"))
        return st.stddev[0] < STUB_STDDEV and st.mean[0] < STUB_MEAN
    except Exception:
        return False


def verify_assets(dirs=("images", "overlays")):
    """Найти заглушки и подозрительно мелкие файлы."""
    import hashlib
    from collections import defaultdict
    stubs, small, by_md5 = [], [], defaultdict(list)
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in sorted(glob.glob(os.path.join(d, "scene_*"))):
            if f.endswith(SKIP_EXT) or ".ovthumb." in f:
                continue
            sz = os.path.getsize(f)
            if _looks_like_stub(f) or sz in STUB_SIZES:
                stubs.append((f, sz))
            elif sz < SMALL:
                small.append((f, sz))
            by_md5[hashlib.md5(open(f, "rb").read()).hexdigest()].append(f)
    # Одинаковый файл в 3+ сценах — почти всегда заглушка, а не совпадение.
    # Порог 3 (а не 2) выбран намеренно, дыры снизу нет — покрытие такое:
    #   1 сцена  → ловится размером (точным или <12 КБ);
    #   2 сцены  → падает в selfcheck как обычный дубль (_MAX_PER_BUILD=1),
    #              ещё до дашборда — дублировать эту проверку тут незачем;
    #   3+ сцен  → этот признак, он же страховка на случай, если облако
    #              однажды сменит вес заглушки.
    # Незакрыт только случай «одна заглушка нового веса >12 КБ в одной
    # сцене» — её видно глазами на контактном листе, она чёрная.
    repeats = {h: v for h, v in by_md5.items() if len(v) >= 3}
    bad = False
    if stubs:
        bad = True
        print("  ЗАГЛУШКИ «нет кадра» (точный размер): %s"
              % ", ".join(os.path.basename(f) for f, _ in stubs))
    if small:
        print("  подозрительно мелкие (<12 КБ): %s"
              % ", ".join("%s/%dб" % (os.path.basename(f), s) for f, s in small))
    for h, v in repeats.items():
        bad = True
        print("  один и тот же файл в %d сценах: %s"
              % (len(v), ", ".join(os.path.basename(x) for x in v)))
    if not bad and not small:
        print("  кадры: заглушек и повторов нет")
    return bad


def verify(path):
    """Сверить overlays.json со слепком. Облачный merge_shards умеет молча
    выбрасывать ключи целиком (а не оставлять их с пустым photo) — у
    параллельной вкладки так исчезли все 40 текстовых всплывашек разом.
    Поэтому сверяем по СПИСКУ id и по наличию полей, а не по факту ключа."""
    if not os.path.exists(SNAP):
        print("слепка нет (%s) — снять до отправки: refetch.py --snapshot %s"
              % (SNAP, path))
        return 2
    was = json.load(open(SNAP, encoding="utf-8"))
    ov = json.load(open(path, encoding="utf-8"))
    now = {k: v for k, v in ov.items() if k.isdigit()}
    lost = sorted(set(was) - set(now), key=int)
    lost_text = sorted([k for k in now if was.get(k, {}).get("text")
                        and not now[k].get("text")], key=int)
    lost_photo = sorted([k for k in now if was.get(k, {}).get("photo")
                         and not now[k].get("photo")], key=int)
    lost_sound = sorted([k for k in now if was.get(k, {}).get("sound")
                         and not now[k].get("sound")], key=int)
    for name, ids in (("ключ исчез целиком", lost), ("пропал текст", lost_text),
                      ("пропало фото", lost_photo), ("пропал звук", lost_sound)):
        if ids:
            print("  %s: %s" % (name, ", ".join(ids)))
    broken = bool(lost or lost_text or lost_photo or lost_sound)
    if broken:
        print("\nВосстанови из своей локальной копии — облако затирает "
              "overlays.json своей версией, а не мержит в твою.")
    else:
        print("overlays.json совпадает со слепком (%d всплывашек)" % len(now))
    print("\n--- кадры ---")
    if verify_assets():
        broken = True
    return 1 if broken else 0


def main():
    if "--snapshot" in sys.argv:
        return snapshot(arg("--snapshot"))
    if "--verify" in sys.argv:
        return verify(arg("--verify"))
    scenes, overlays = arg("--scenes"), arg("--overlays")
    # ОТДЕЛЬНЫЕ наборы правок на файл. Общий --fix на оба файла был
    # ошибкой дизайна (поймано живьём 2026-10-12): формат значений разный
    # (сцена = [source, query], всплывашка = строка), поэтому один набор
    # на два файла и падал, и успевал снести чужие файлы до падения —
    # id 2/49/60 существуют и там и там.
    fx_s, fx_o = arg("--fix-scenes"), arg("--fix-overlays")
    raw = arg("--fix")
    if raw and scenes and overlays:
        print("--fix нельзя с двумя файлами сразу: формат значений разный."
              "\nИспользуй --fix-scenes '{...}' и --fix-overlays '{...}'.")
        return 2
    if raw:  # один файл — старая короткая форма
        fx_s, fx_o = (raw, None) if scenes else (None, raw)
    if not (fx_s or fx_o) or not (scenes or overlays):
        print(__doc__)
        return 2
    jobs = []
    if scenes and fx_s:
        _fx = json.loads(fx_s)
        # ПРОВЕРКА ФОРМАТА, А НЕ МОЛЧАЛИВЫЙ ПРОВАЛ (2026-10-17). Для СЦЕН
        # значение обязано быть парой [source, query]. Если передать строку,
        # фетчер брал её ПЕРВЫЙ СИМВОЛ как источник — печатал
        # `ERROR: unknown source 'р'`, ставил сцене FAILED, но refetch
        # возвращал 0 и бодро писал «--- рефетч images: [24, 41] ---».
        # Круг правок выглядел успешным, а кадры не менялись; поймано только
        # сверкой файлов на диске (5min-gerasimov-1810).
        # СЛОВАРНАЯ ФОРМА ТОЖЕ ГОДИТСЯ (2026-10-17): вкладка естественно пишет
        # {"source": ..., "source_query": ...} — теми же именами, что в
        # scenes.json — и теряла на отбивке целый круг правок. Форма
        # однозначна, молчаливого провала с «первым символом» в ней нет,
        # поэтому приводим её к паре, а не отбиваем.
        def _as_pair(v):
            if isinstance(v, dict):
                src = v.get("source")
                qry = v.get("source_query", v.get("query"))
                if (isinstance(src, str) and src.strip()
                        and isinstance(qry, str) and qry.strip()):
                    return [src, qry]
                return None
            if (isinstance(v, (list, tuple)) and len(v) == 2
                    and all(isinstance(x, str) and x.strip() for x in v)):
                return list(v)
            return None
        _norm = {k: _as_pair(v) for k, v in _fx.items()}
        _bad = {k: _fx[k] for k, v in _norm.items() if v is None}
        if not _bad:
            _fx = _norm
        if _bad:
            print("СТОП: для сцен значение должно быть парой [source, query] "
                  "или словарём {\"source\": ..., \"source_query\": ...}.")
            for k, v in _bad.items():
                print(f"  id {k}: {v!r}")
            print("Пример: --fix-scenes '{\"24\": [\"press_photo\", \"...\"]}'."
                  "\nДля всплывашек (--fix-overlays) значение — строка, источник там всегда press_photo.")
            return 1
        jobs.append(apply_fix(scenes, _fx, False))
    if overlays and fx_o:
        _fo = json.loads(fx_o)
        _bado = {k: v for k, v in _fo.items() if not (isinstance(v, str) and v.strip())}
        if _bado:
            print("СТОП: для всплывашек значение должно быть СТРОКОЙ-запросом.")
            for k, v in _bado.items():
                print(f"  id {k}: {v!r}")
            return 1
        jobs.append(apply_fix(overlays, _fo, True))

    here = os.path.dirname(os.path.abspath(__file__))
    lint = os.path.join(here, "query_lint.py")
    if os.path.exists(lint):
        print("\n--- линт новых запросов ---")
        rc = subprocess.run(["python3", lint] + [j[0] for j in jobs]).returncode
        if rc != 0 and "--force" not in sys.argv:
            print("\nЗамена содержит мину — перепиши её от объекта "
                  "(или --force, если уверен). Фетч НЕ запускался, "
                  "СТАРЫЕ КАДРЫ НА МЕСТЕ (запросы в scenes.json уже "
                  "переписаны — поправь их и позови снова).")
            for sub, _, _, _ in jobs:
                if os.path.exists(sub):
                    os.remove(sub)
            return 1

    for _, assets, ids, _ in jobs:   # удаляем только теперь, линт прошёл
        for sid in ids:
            for f in wipe(assets, sid):
                print("  снёс %s" % f)
    for sub, assets, ids, before in jobs:
        print("\n--- рефетч %s: %s ---" % (assets, ids))
        subprocess.run(["python3", os.path.join(here, "fetch_parallel.py"),
                        sub, assets, ".env", "5"])
        report_same_file(assets, before)
    prune_needs_upload(only_ids=[sid for _, _, ids, _ in jobs for sid in ids])
    for sub, _, _, _ in jobs:
        if os.path.exists(sub):
            os.remove(sub)
    return 0


if __name__ == "__main__":
    sys.exit(main())
