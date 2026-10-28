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

ГЕЙТ КРУГОВ (2026-10-21). Ведёт журнал `.refetch_rounds.json` в папке ролика
и отбивает два самых дорогих сценария (замер по 20.10 — см. комментарий у
round_gate): переформулировку запроса на уже заменённой сцене и третий круг
правок. Отказ происходит ДО любых изменений: запросы не переписаны, кадры на
месте. Настоять — `--force`. Сводка по кругам: `refetch.py --rounds`
(печатает круги, доборы и долю повторных замен — для замера по фазам).
Добор пустых сцен после облака круг НЕ расходует: там нечего заменять.
"""
import glob
import re
import json
import os
import subprocess
import sys
import time

SKIP_EXT = (".json", ".text.png", ".lock")


def arg(name, default=None):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def wipe(d, sid):
    """Снятый кадр не удаляем, а УВОДИМ В `.trash/` папки ролика.

    2026-10-17, предложение рабочей вкладки, принято: образцы брака терялись
    именно здесь. Кадр с кнопкой PLAY и подписью агентства попадался
    шестой-седьмой раз, фильтра на него нет, а настроить фильтр не на чем —
    `os.remove` стирал файл за секунду до фетча замены. Теперь он лежит в
    `.trash/` до конца работы над роликом: диагностика есть, а из фетча,
    дедупа и `ship.sh` папка исключена (имя с точки — скрытая, в облако не
    едет, сироты по ней не считаются).
    """
    gone = []
    trash = os.path.join(d, ".trash")
    for f in glob.glob(os.path.join(d, "scene_%03d.*" % sid)):
        if f.endswith(SKIP_EXT) or ".ovthumb." in f:
            continue
        bn = os.path.basename(f)
        try:
            os.makedirs(trash, exist_ok=True)
            dst = os.path.join(trash, "%s.%s" % (time.strftime("%H%M%S"), bn))
            os.replace(f, dst)
        except OSError:
            os.remove(f)          # не вышло — ведём себя как раньше
        gone.append(bn)
    return gone


def restore_missing(d, ids):
    """Замена не нашлась — ВЕРНУТЬ старый кадр из `.trash`, а не оставить дыру.

    2026-10-17, поймано дважды за один ролик: `wipe` сносит кадр ДО фетча, и
    если фетч ничего не принёс, сцена остаётся совсем без картинки — в выводе
    при этом только «снёс scene_021.mp4», никакой ошибки. Вкладка узнавала об
    этом на сборке и делала бэкапы руками. Теперь старый кадр лежит в
    `.trash` (правка того же дня), поэтому дыру можно закрыть автоматически:
    кадр возвращается на место, а в лог идёт честная строка — заменить НЕ
    удалось, стоит прежний.
    """
    trash = os.path.join(d, ".trash")
    if not os.path.isdir(trash):
        return
    for sid in ids:
        have = [f for f in glob.glob(os.path.join(d, "scene_%03d.*" % sid))
                if not f.endswith(SKIP_EXT) and ".ovthumb." not in f]
        if have:
            continue
        back = sorted(glob.glob(os.path.join(trash, "*.scene_%03d.*" % sid)))
        if not back:
            print("  !! сцена %d осталась БЕЗ кадра, вернуть нечего" % sid)
            continue
        src = back[-1]
        dst = os.path.join(d, os.path.basename(src).split(".", 1)[1])
        try:
            os.replace(src, dst)
            print("  ВЕРНУЛ прежний кадр сцены %d (замена не нашлась): %s"
                  % (sid, os.path.basename(dst)))
        except OSError as e:
            print("  !! сцена %d без кадра, вернуть не вышло: %s" % (sid, e))


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


# ЛЮБОЙ ДОСРОЧНЫЙ ОТБОЙ ПЕЧАТАЕТ СЛОВО «ОШИБКА:» (28.10, улов вкладки 2 —
# стоило ей 25 минут тишины). Мониторы вкладок ждут в логе «ИТОГ» или
# traceback. Отбой `--force` без причины печатал «СТОП: …» и выходил мгновенно
# — монитор этого слова не знал и ждал до таймаута, а мгновенный отказ выглядел
# как долгая работа. Само требование причины правильное; плохо было только то,
# что отказ НЕМОЙ для того, кто его ждёт. Правило: добавляешь новый ранний
# выход — начинай строку с «ОШИБКА:» (или «ИТОГ:»), иначе он станет тихим.


# МГНОВЕННАЯ ЗАМЕНА ИЗ ЗАПАСА — КРУГ ПЕРЕСТАЁТ БЫТЬ КРУГОМ (28.10, решение
# пользователя «берём пять кандидатов»). Фетч теперь складывает проигравших
# кандидатов в `images/cands/scene_NNN__k_WxH.jpg`. Если кадр забракован
# ГЛАЗАМИ (а это 28-48% сцен по замерам 28.10, против 3-4% машинного брака),
# менять его походом в облако незачем: берём следующего из запаса — секунды
# вместо трёх минут и нового прогона.
#     python3 refetch.py --scenes <json> --next 12,34,47
# Использованный кандидат удаляется, прежний кадр уходит в бан на 2 дня
# (иначе вернётся через поиск), запрос в scenes.json НЕ меняется — мы меняем
# кадр, а не смысл сцены. Запас кончился — сцена называется числом, и по ней
# идёт обычный круг с переписанным запросом.
def replace_from_stash(scenes_path, ids, assets="images"):
    here_ = os.path.dirname(os.path.abspath(__file__))
    cands = os.path.join(assets, "cands")
    done, empty = [], []
    for sid in ids:
        pool = sorted(glob.glob(os.path.join(cands, "scene_%03d__*" % sid)))
        if not pool:
            empty.append(sid)
            continue
        # лучший из запаса: по площади из имени файла (…__k_WxH.jpg)
        def _area(f):
            m = re.search(r"__\d+_(\d+)x(\d+)", os.path.basename(f))
            return int(m.group(1)) * int(m.group(2)) if m else 0
        pick = sorted(pool, key=_area, reverse=True)[0]
        old = [f for f in glob.glob(os.path.join(assets, "scene_%03d.*" % sid))
               if not f.endswith(SKIP_EXT) and ".ovthumb." not in f]
        for f in old:
            h = _md5(f)
            if h:
                subprocess.run(["python3", os.path.join(here_, "ban_file.py"),
                                "--md5", h, "--days", "2",
                                "замена из запаса на сцене %d" % sid])
            try:
                os.remove(f)
            except OSError:
                pass
        dst = os.path.join(assets, "scene_%03d.jpg" % sid)
        try:
            os.replace(pick, dst)
            done.append(sid)
            print("  сцена %d: взят кадр из запаса (%s), осталось в запасе %d"
                  % (sid, os.path.basename(pick), len(pool) - 1))
        except OSError as e:
            print("  сцена %d: не удалось взять из запаса (%s)" % (sid, e))
            empty.append(sid)
    print("\nИТОГ ПО ДИСКУ: заменено из запаса %d из %d%s"
          % (len(done), len(ids),
             ("; запаса нет у сцен: %s" % ", ".join(map(str, empty))) if empty else ""))
    if empty:
        print("По ним нужен обычный круг с ПЕРЕПИСАННЫМ запросом: "
              "кадр из того же поиска уже исчерпан.")
    return 0 if done else 1


def count_replaced(assets, before, ids):
    """(заменено, осталось прежним, без файла) — ПО ФАКТУ НА ДИСКЕ.

    ПРОВАЛ ФЕТЧА ≠ КРУГ ВПУСТУЮ (28.10, улов вкладки 2 на
    `5min-kiev-obrechen-2810`). Круг на 34 сценах: две замены не нашлись, фетч
    вернул код 1, и итог печатал «результат рефетча НЕДЕЙСТВИТЕЛЕН» — по этой
    строке вкладка обязана переделывать весь круг, то есть выбросить 32
    состоявшиеся замены и ещё три минуты. Вкладка не поверила и проверила
    `stat`: 32 кадра обновлены, два остались от первого фетча. Это тот же
    класс, что «успех ≠ сделанная работа», только наизнанку — и лечится так
    же: итог считаем по ДИСКУ, а не по коду возврата.
    """
    replaced, kept, missing = [], [], []
    for sid in ids:
        files = [f for f in glob.glob(os.path.join(assets, "scene_%03d.*" % sid))
                 if not f.endswith(SKIP_EXT) and ".ovthumb." not in f]
        if not files:
            missing.append(sid)
            continue
        old = before.get(sid)
        if old and _md5(files[0]) == old:
            kept.append(sid)
        else:
            replaced.append(sid)
    return replaced, kept, missing


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


# ============================================================================
# ГЕЙТ КРУГОВ ПРАВОК (2026-10-21, по замеру двух роликов 20.10)
# ============================================================================
# Замер по журналам сессий: на planeta-kapitulyaciya-2110 было 7 вызовов
# --fix, на 5min-isterika-2110 — 13, при правиле «максимум два круга».
# Главное, что показал замер: ЦЕНА КРУГА ПОЧТИ НЕ ЗАВИСИТ ОТ ЧИСЛА КАДРОВ.
# 8 кадров в одном вызове — 2,5 мин до следующего шага; 1 кадр — 3,3-3,9 мин.
# Платим за круг (перечитать лист, сформулировать, дождаться, проверить), а
# не за фетч. Отсюда вывод: сокращать надо ЧИСЛО кругов, а не время фетча.
#
# Вторая половина потерь — ПОВТОРНЫЕ замены одной и той же сцены: 6 из 24
# (25%) на ПЛАНЕТЕ и 19 из 42 (45%) на 5 МИНУТ. Сцены 31 и 32 правились по
# ЧЕТЫРЕ раза, 7/21/48/55/61/64/71 — по три. Причина механическая: refetch
# был БЕЗ ПАМЯТИ, каждый вызов начинался с чистого листа, и четвёртая правка
# сцены выглядела как первая. Запрос при этом переписывался словами, хотя в
# скилле прямо сказано менять ОБЪЕКТ или ТИП кадра.
#
# Текстом это правило не работает (проверено, см. память про «класс брака →
# мина в тот же час»), поэтому оно здесь, в коде:
#   • журнал кругов на ролик (`.refetch_rounds.json`, рядом с проектом);
#   • повтор сцены → печатаем ВСЕ прошлые запросы по ней;
#   • новый запрос похож на прошлый (пересечение значимых слов ≥ 0.45) →
#     ОТКАЗ, пока не сменишь объект или не настоишь через --force;
#   • третий круг и дальше → ОТКАЗ без --force (бюджет два круга).
# Отказ происходит ДО apply_fix: запросы в scenes.json не переписываются,
# кадры не удаляются, терять нечего.
ROUNDS = ".refetch_rounds.json"
SIM_LIMIT = 0.45      # пересечение слов, выше которого это «та же фраза»
ROUND_BUDGET = 2      # кругов на ролик без --force

_STOP = {
    "реальное", "фото", "фотография", "фотографии", "снимок", "кадр",
    "крупным", "планом", "крупный", "план", "общий", "вид", "сверху",
    "closeup", "close", "detail", "macro", "texture", "aerial", "shot",
    "people", "nobody", "empty", "the", "and", "for", "with", "without",
    "его", "это", "там", "как", "или", "над", "под", "при", "около",
}


def _tokens(q):
    """Значимые слова запроса: без служебных и без коротких."""
    import re
    out = set()
    for t in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", (q or "").lower()):
        if len(t) > 2 and t not in _STOP:
            out.add(t[:6] if len(t) > 6 else t)   # грубая нормализация окончаний
    return out


def _similar(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


_MANIFEST_CACHE = {}


def _manifest_status(kind, sid):
    """Статус кадра по манифесту облака, '' если манифеста нет."""
    if kind not in _MANIFEST_CACHE:
        data = {}
        try:
            for m in json.load(open(os.path.join(kind, "manifest.json"),
                                   encoding="utf-8")):
                if isinstance(m, dict) and m.get("id") is not None:
                    data[int(m["id"])] = str(m.get("status", "")).lower()
        except (OSError, ValueError, TypeError, KeyError):
            data = {}
        _MANIFEST_CACHE[kind] = data
    try:
        return _MANIFEST_CACHE[kind].get(int(sid), "")
    except (TypeError, ValueError):
        return ""


def _has_asset(kind, sid):
    """Есть ли у сцены НАСТОЯЩИЙ кадр на диске.

    ЗАГЛУШКА НЕ СЧИТАЕТСЯ КАДРОМ (2026-10-21, поймано на первом же ролике).
    Облако кладёт «нет кадра» физическим файлом, поэтому наивная проверка
    существования считала бы добор пустых сцен ПРАВКОЙ и сжигала круг из
    бюджета впустую. Признак заглушки тот же, что у verify_assets: почти
    однотонный тёмный кадр.
    """
    # МАНИФЕСТ ЧЕСТНЕЕ ГЛАЗА (24.10, улов `usuario-dd`). Заглушка бывает НЕ
    # тёмной и НЕ типового размера: на `5min-voennye-2510` сцена 47 пришла
    # файлом 34 КБ, который не ловился ни по размеру, ни по яркости, — её
    # нашли только по плотности в `photo_quality.py`. А в манифесте облака у
    # неё честно стоял `status: placeholder`. Цена промаха высокая: такая
    # сцена считается «кадр есть», добор превращается в ПРАВКУ и съедает круг
    # из бюджета — на том ролике бюджет кончился до начала настоящего аудита.
    if _manifest_status(kind, sid) in ("placeholder", "failed", "empty", "stub"):
        return False
    real = []
    for f in glob.glob(os.path.join(kind, "scene_%03d.*" % int(sid))):
        if f.endswith(SKIP_EXT) or ".ovthumb." in f:
            continue
        if os.path.getsize(f) in STUB_SIZES or _looks_like_stub(f):
            continue
        real.append(f)
    return bool(real)


def _is_fill(pend):
    """ДОБОР пустых сцен (облако не нашло) против ПРАВКИ готового кадра.

    На planeta-kapitulyaciya-2110 первым вызовом --fix был именно добор
    8 сцен, которые матрица не закрыла, — это не круг правок, и съедать им
    бюджет нельзя: иначе на настоящий аудит остаётся один круг вместо двух.
    Признак прямой: у сцены НЕТ файла, значит заменять нечего.
    """
    have = miss = 0
    for _p, fx, is_ov in pend:
        kind = "overlays" if is_ov else "images"
        for sid in fx:
            if _has_asset(kind, sid):
                have += 1
            else:
                miss += 1
    return miss > 0 and have == 0


def _load_rounds():
    try:
        return json.load(open(ROUNDS, encoding="utf-8"))
    except (OSError, ValueError):
        return {"rounds": [], "tried": {}}


def force_reason():
    """`--force` без ПРИЧИНЫ словами больше не принимается (2026-10-21).

    Повод измерен в тот же день: соседняя вкладка прошла через --force дважды
    и сделала круги №3 и №4 по ОДНОМУ кадру на одну и ту же сцену с разницей в
    минуту — шесть минут за два кадра, при том что повторные замены в её же
    журнале попадали в брак в 25% случаев. Запрещать --force нельзя (жёсткое
    нарушение чинится всегда, сколько бы кругов ни потребовалось), но он
    должен быть ОСОЗНАННЫМ и ВИДИМЫМ: причина пишется в журнал, и по ней потом
    видно, на что реально уходят лишние круги.

    Возврат: None (форса нет) | строка-причина | False (форс без причины).
    """
    if "--force" not in sys.argv:
        return None
    i = sys.argv.index("--force")
    if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
        return sys.argv[i + 1].strip() or False
    return False


def yellow_cards():
    """Сколько жёлтых карточек уже стоит — потолок пользователя 2-3 на ролик."""
    try:
        return len(json.load(open("needs_upload.json", encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return 0


def round_gate(pend, force):
    """pend: список (путь, {id: значение}, is_overlay). Возврат: 0 / 1."""
    jr = _load_rounds()
    fill = _is_fill(pend)
    done = [r for r in jr.get("rounds", []) if not r.get("fill")]
    rnd = len(done) + (0 if fill else 1)
    tried = jr.get("tried", {})
    repeats, resays = [], []
    for _path, fx, is_ov in pend:
        kind = "overlays" if is_ov else "images"
        for sid, val in fx.items():
            q = val if isinstance(val, str) else val[1]
            prev = tried.get("%s:%s" % (kind, sid), [])
            if not prev:
                continue
            repeats.append((kind, sid, len(prev) + 1, prev, q))
            for p in prev:
                if _similar(p.get("query", ""), q) >= SIM_LIMIT:
                    resays.append((kind, sid, p.get("query", ""), q,
                                   _similar(p.get("query", ""), q)))
                    break
    if fill:
        print("\n--- ДОБОР пустых сцен (в бюджет кругов не идёт) ---")
    else:
        print("\n--- круг правок №%d (бюджет %d) ---" % (rnd, ROUND_BUDGET))
    if jr.get("rounds"):
        was = ", ".join("%s: %d кадр(ов)"
                        % ("добор" if r.get("fill") else "№%d" % r["n"],
                           len(r["ids"]))
                        for r in jr["rounds"])
        print("  прошлые вызовы — %s" % was)
    n_now = sum(len(fx) for _p, fx, _o in pend)
    print("  в этом круге кадров: %d" % n_now)
    if repeats:
        print("\n  ПОВТОРНАЯ правка тех же сцен (прошлая замена оказалась брак):")
        for kind, sid, n, prev, q in repeats:
            print("    %s сцена %s — правка №%d" % (kind, sid, n))
            for p in prev:
                print("        круг %d пробовал: %s" % (p.get("round", 0),
                                                        p.get("query", "")))
            print("        теперь просишь:  %s" % q)
    bad = False
    # ОТКАЗ ПО ОДНОЙ СЦЕНЕ НЕ РОНЯЕТ ВЕСЬ ВЫЗОВ (25.10, улов `usuario-6f`).
    # Было: одна переформулировка среди девяти правок отбивала ВСЕ девять, и
    # вкладка пересобирала команду целиком — а остальные восемь честно меняли
    # объект. Теперь виновные сцены просто ИСКЛЮЧАЮТСЯ из правок (их запросы
    # не переписываются, кадры не трогаются), а чистые чинятся в этом же круге.
    # Бюджет кругов — другое дело: там отказ по-прежнему общий, потому что
    # круг стоит одинаково независимо от числа кадров в нём.
    dropped = set()
    if resays and not force:
        for kind, sid, _o, _n, _s in resays:
            dropped.add("%s:%s" % (kind, sid))
        print("\nПЕРЕФОРМУЛИРОВКА — эти сцены из круга ИСКЛЮЧЕНЫ (остальные чиню):")
        for kind, sid, old, new, s in resays:
            print("  %s сцена %s — совпадение слов %.0f%%" % (kind, sid, s * 100))
            print("     было:  %s" % old)
            print("     стало: %s" % new)
        print("\nИсточник отдаёт на этот смысл один и тот же кадр — замер "
              "20.10: так ушло 25-45% всех замен и по 3 минуты на каждую.")
        print("Меняй не слова, а ОДНО ИЗ ТРЁХ:")
        print("  • объект съёмки (лицо → место, где это решают; предмет → "
              "помещение, где он стоит);")
        print("  • тип кадра (портрет → фасад здания → деталь → общий план);")
        print("  • источник (pexels_video → press_photo по-русски, и наоборот).")
        print("Настаиваешь на этой формулировке — добавь --force.")
        if len(dropped) == sum(len(fx) for _p, fx, _o in pend):
            bad = True
            print("\nВ круге не осталось ни одной чистой правки — вызов отменён.")
    if not fill and rnd > ROUND_BUDGET and not force:
        bad = True
        print("\nОШИБКА: СТОП — это круг №%d, а бюджет — %d." % (rnd, ROUND_BUDGET))
        print("Замер 20.10: 7 и 13 кругов вместо двух дали 22 и 37 минут "
              "правок. Круг стоит ~3 минуты независимо от числа кадров в нём, "
              "поэтому дешевле собрать ВСЕ находки в один список.")
        _nc = yellow_cards()
        print("ЖЁСТКОЕ нарушение (водяной знак, чужая страна, дети, документы, "
              "забаненный кадр) чини ВСЕГДА: --force \"причина словами\".")
        print("ПОГРАНИЧНОЕ после второго круга — жёлтой карточкой, пользователь "
              "решит сам за секунду. Сейчас карточек: %d (его потолок 2-3; что "
              "сверх — чинить самому)." % _nc)
        if n_now <= 2:
            print("И отдельно: в этом круге всего %d кадр(а) — круг стоит ~3 "
                  "минуты независимо от объёма, а третий заход на ту же сцену "
                  "попадает в брак в четверти случаев. Почти наверняка дешевле "
                  "карточка." % n_now)
    if bad:
        print("\nНичего не тронуто: запросы в scenes.json не переписаны, "
              "кадры на месте.")
        return 1
    if force and (resays or rnd > ROUND_BUDGET):
        print("  --force: иду дальше, круг и повторы записаны в журнал.")
    if dropped:
        # выкидываем виновные id из самих правок — дальше по коду их просто нет
        for _path, fx, is_ov in pend:
            kind = "overlays" if is_ov else "images"
            for sid in [k for k in fx if "%s:%s" % (kind, k) in dropped]:
                fx.pop(sid)
        print("  исключено сцен: %d, чиню остальные: %d"
              % (len(dropped), sum(len(fx) for _p, fx, _o in pend)))
    return 0


def round_record(pend, fill=None, why=None):
    """Записать круг в журнал — ПОСЛЕ того как все проверки пройдены.

    `fill` ОБЯЗАН приходить снаружи, посчитанный ДО wipe() (2026-10-21,
    поймано на первом же ролике). Пересчёт здесь давал всегда True: к моменту
    записи кадры уже уехали в `.trash`, сцены выглядели пустыми, и круг правок
    на 18 кадров записался «добором». Бюджет не уменьшался — гейт считал
    правильно, а помнил неправильно.
    """
    jr = _load_rounds()
    if fill is None:
        fill = _is_fill(pend)
    n_fix = len([r for r in jr.get("rounds", []) if not r.get("fill")])
    ids_all, tried = [], jr.setdefault("tried", {})
    for _path, fx, is_ov in pend:
        kind = "overlays" if is_ov else "images"
        for sid, val in fx.items():
            q = val if isinstance(val, str) else val[1]
            src = "press_photo" if isinstance(val, str) else val[0]
            key = "%s:%s" % (kind, sid)
            tried.setdefault(key, []).append(
                {"round": 0 if fill else n_fix + 1, "source": src,
                 "query": q, "fill": fill})
            ids_all.append(key)
    _rec = {"n": 0 if fill else n_fix + 1, "fill": fill,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "ids": ids_all}
    if why:
        _rec["force"] = why
    jr["rounds"].append(_rec)
    try:
        json.dump(jr, open(ROUNDS, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except OSError:
        pass


def rounds_report():
    """`--rounds` — сводка по кругам этого ролика (для замера по фазам)."""
    jr = _load_rounds()
    if not jr.get("rounds"):
        print("кругов правок пока не было (%s нет)" % ROUNDS)
        return 0
    n_fix = len([r for r in jr["rounds"] if not r.get("fill")])
    n_fill = len(jr["rounds"]) - n_fix
    print("кругов правок: %d (плюс доборов пустых сцен: %d)" % (n_fix, n_fill))
    for r in jr["rounds"]:
        print("  %-6s %s  кадров: %-3d  %s%s"
              % ("добор" if r.get("fill") else "круг %d" % r["n"],
                 r.get("ts", "?"), len(r["ids"]),
                 ", ".join(r["ids"][:14]),
                 ("   [--force: %s]" % r["force"]) if r.get("force") else ""))
    rep = {k: v for k, v in jr.get("tried", {}).items() if len(v) > 1}
    total = sum(len(v) for v in jr.get("tried", {}).values())
    if rep:
        extra = sum(len(v) - 1 for v in rep.values())
        print("\nповторных замен: %d из %d (%.0f%%)"
              % (extra, total, 100.0 * extra / total if total else 0))
        for k, v in sorted(rep.items(), key=lambda x: -len(x[1])):
            print("  %s — %d раз(а):" % (k, len(v)))
            for p in v:
                print("      круг %d: %s" % (p.get("round", 0), p.get("query", "")))
    else:
        print("повторных замен нет")
    return 0


def _from_library(assets, sid):
    """Кадр сцены пришёл из медиатеки пользователя, а не из веба?

    Нужно, чтобы `--ban` не хоронил НАВСЕГДА заготовку, которую пользователь
    положил сам: отказ на ОДНОЙ сцене не значит, что файл плох всегда.
    Живой случай 23.10 — пустая карта `КАРТЫ/ЕВРОПА/Blank Europe Map.jpg`
    забракована на сцене 34 и вечным баном закрылась для всех роликов.

    Источник берём из честного журнала `images/.sources*.json` (пишется при
    каждом удачном скачивании с 22.10), потом из манифеста.
    """
    for jf in sorted(glob.glob(os.path.join(assets, ".sources*.json"))):
        try:
            d = json.load(open(jf, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        src = d.get(str(sid))
        if src:
            return "library" in str(src)
    try:
        man = json.load(open(os.path.join(assets, "manifest.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return False
    for rec in (man if isinstance(man, list) else []):
        if isinstance(rec, dict) and int(rec.get("id", -1)) == int(sid):
            return "library" in str(rec.get("source", ""))
    return False


def sync_manifest(kind, ids):
    """ПРИВЕСТИ МАНИФЕСТ К ДИСКУ ПОСЛЕ ФЕТЧА (24.10, улов `usuario-c9`).

    Рефетч клал новый кадр на диск, а `images/manifest.json` оставался со
    старым `status: placeholder`. Дальше `contact_sheet.py` честно выжигал
    этот ярлык в подпись плитки, внешний агент читал ЯРЛЫК, а не картинку, и
    браковал нормальные кадры: на `5min-tramp-ustupki-2510` так пришли три
    фантомные находки из восемнадцати, две замены вернулись тем же файлом.
    Чиним в корне: после успешного фетча запись в манифесте приводится к
    тому, что реально лежит на диске.
    """
    path = os.path.join(kind, "manifest.json")
    try:
        man = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(man, list):
        return
    fixed = 0
    for rec in man:
        if not isinstance(rec, dict):
            continue
        try:
            sid = int(rec.get("id", -1))
        except (TypeError, ValueError):
            continue
        if sid not in set(int(i) for i in ids):
            continue
        _MANIFEST_CACHE.pop(kind, None)          # чтобы _has_asset не врал
        if _has_asset_on_disk(kind, sid):
            if str(rec.get("status", "")).lower() != "ok":
                rec["status"] = "ok"
                fixed += 1
            got = sorted(f for f in glob.glob(
                os.path.join(kind, "scene_%03d.*" % sid))
                if not f.endswith(SKIP_EXT) and ".ovthumb." not in f)
            if got:
                rec["file"] = os.path.basename(got[0])
    if fixed:
        try:
            json.dump(man, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("  манифест приведён к диску: %d сцен сняли отметку "
                  "«нет кадра»" % fixed)
        except OSError as e:
            print("  !! манифест не переписать: %s" % e)
    _MANIFEST_CACHE.pop(kind, None)


def _has_asset_on_disk(kind, sid):
    """Как _has_asset, но БЕЗ оглядки на манифест — иначе круг в рассуждении."""
    for f in glob.glob(os.path.join(kind, "scene_%03d.*" % int(sid))):
        if f.endswith(SKIP_EXT) or ".ovthumb." in f:
            continue
        if os.path.getsize(f) in STUB_SIZES or _looks_like_stub(f):
            continue
        return True
    return False


def main():
    # --next <ids> — мгновенная замена из запаса кандидатов (28.10)
    if "--next" in sys.argv:
        _i = sys.argv.index("--next")
        _ids = []
        if _i + 1 < len(sys.argv):
            _ids = [int(x) for x in sys.argv[_i + 1].replace(" ", "").split(",")
                    if x.strip().isdigit()]
        if not _ids:
            print("ОШИБКА: --next нужен список сцен, например --next 12,34",
                  file=sys.stderr)
            return 2
        _sc = ""
        if "--scenes" in sys.argv:
            _j = sys.argv.index("--scenes")
            _sc = sys.argv[_j + 1] if _j + 1 < len(sys.argv) else ""
        _assets = "overlays" if "--fix-overlays" in sys.argv else "images"
        return replace_from_stash(_sc, _ids, _assets)

    if "--snapshot" in sys.argv:
        return snapshot(arg("--snapshot"))
    if "--verify" in sys.argv:
        return verify(arg("--verify"))
    if "--rounds" in sys.argv:
        return rounds_report()
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
    jobs, pend = [], []
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
            print("ОШИБКА: СТОП — для сцен значение должно быть парой [source, query] "
                  "или словарём {\"source\": ..., \"source_query\": ...}.")
            for k, v in _bad.items():
                print(f"  id {k}: {v!r}")
            print("Пример: --fix-scenes '{\"24\": [\"press_photo\", \"...\"]}'."
                  "\nДля всплывашек (--fix-overlays) значение — строка, источник там всегда press_photo.")
            return 1
        pend.append((scenes, _fx, False))
    if overlays and fx_o:
        _fo = json.loads(fx_o)
        _bado = {k: v for k, v in _fo.items() if not (isinstance(v, str) and v.strip())}
        if _bado:
            print("ОШИБКА: СТОП — для всплывашек значение должно быть СТРОКОЙ-запросом.")
            for k, v in _bado.items():
                print(f"  id {k}: {v!r}")
            return 1
        pend.append((overlays, _fo, True))

    # ГЕЙТ КРУГОВ — строго ДО apply_fix: отказ не должен оставлять за собой
    # переписанные запросы и снесённые кадры (на этом уже обжигались с линтом).
    _fill_now = _is_fill(pend)     # СЧИТАЕМ ДО wipe(), иначе всегда «добор»
    _why = force_reason()
    if _why is False:
        print("ОШИБКА: СТОП — `--force` требует ПРИЧИНУ словами, она идёт в журнал.")
        print('  Пример: --force "забаненный кадр в сборке, selfcheck не пустит"')
        print("  Без причины не видно, на что уходят лишние круги — а это "
              "главная статья времени на ролике.")
        return 2
    if round_gate(pend, bool(_why)):
        return 1
    for _p, _fx2, _ov in pend:
        jobs.append(apply_fix(_p, _fx2, _ov))

    here = os.path.dirname(os.path.abspath(__file__))
    lint = os.path.join(here, "query_lint.py")
    # ЛИНТОВАТЬ НЕЧЕГО — НЕ ЛИНТУЕМ (26.10, улов `usuario-e8`): при
    # `--fix-overlays` без `--fix-scenes` список файлов выходил пустым,
    # `query_lint` без аргументов печатал СПРАВКУ и возвращал ненулевой код,
    # а refetch читал это как «замена содержит мину» — причина не названа,
    # фетч не шёл, вкладка теряла время и лезла в обход.
    _lint_files = [j[0] for j in jobs if j and j[0] and os.path.exists(j[0])]
    if os.path.exists(lint) and _lint_files:
        print("\n--- линт новых запросов ---")
        rc = subprocess.run(["python3", lint] + _lint_files).returncode
        if rc != 0 and not _why:
            print("\nОШИБКА: замена содержит мину — перепиши её от объекта "
                  "(или --force, если уверен). Фетч НЕ запускался, "
                  "СТАРЫЕ КАДРЫ НА МЕСТЕ (запросы в scenes.json уже "
                  "переписаны — поправь их и позови снова).")
            for sub, _, _, _ in jobs:
                if os.path.exists(sub):
                    os.remove(sub)
            return 1

    # --- КЛЮЧИ ПРОВЕРЯЕМ ДО ФЕТЧА (2026-10-18, улов usuario-42) ---
    # В папке ЗАБОРА (`<ролик>-cloud`) нет `.env`: ship.sh его не отправляет
    # (ключи живут в GitHub Secrets), get.sh не восстанавливал. Фетч при этом
    # падает на `FileNotFoundError: '.env'`, но код возврата здесь не
    # проверялся — и рефетч честно докладывал «ВЕРНУЛ прежний кадр сцены N
    # (замена не нашлась)». Читается как «объект в принципе не находится»,
    # хотя дело в ключах: вкладка дважды переписала формулировку впустую.
    if not os.path.exists(".env"):
        print("\nОШИБКА: ОСТАНОВ — в этой папке нет `.env`, ключи поиска не заданы, "
              "фетч упадёт, а рефетч доложит «замена не нашлась».")
        print("Лечение: cp ~/projects/<ролик>/.env .   (в папке ЗАБОРА .env "
              "не бывает — ship.sh его не отправляет, ключи в GitHub Secrets)")
        return 1

    # --ban: СНЯТЫЙ КАДР — В БАН, А НЕ ПРОСТО ИЗ СЦЕНЫ (2026-10-17).
    # Живой случай: архивное фото АЗС с ценами 2015 года забраковали на
    # сцене 45, сцену заменили — и на следующем рефетче тот же файл пришёл
    # на сцену 41. Замена сцены не выводит файл из выдачи, он переезжает.
    # Флаг для случаев, когда кадр плох САМ ПО СЕБЕ (водяной знак, архив,
    # чужая страна, датировка), а не «не подошёл по смыслу».
    _ban = "--ban" in sys.argv
    # БЕЗ `--ban` ПОИСК МОЖЕТ ВЕРНУТЬ ТОТ ЖЕ САМЫЙ ФАЙЛ (23.10, улов
    # `usuario-fa`). Живой случай: замена всплывашки «здание Верховной Рады»
    # вернула ровно тот кадр, который снимали, — и узналось это уже ПОСЛЕ
    # фетча, то есть ценой круга правок. Предупреждаем ДО, пока отменить
    # дёшево: снятый кадр остаётся в выдаче, если его не исключить.
    # БЕЗ `--ban` ПРЕЖНИЙ КАДР ТЕПЕРЬ БАНИТСЯ АВТОМАТИЧЕСКИ НА 2 ДНЯ
    # (28.10, улов вкладки 1 — третий случай этого класса за день).
    # Прежняя подсказка учила НЕВЕРНО: «меняешь объект — всё в порядке,
    # продолжай». Живой замер показал обратное — четыре сцены (47, 56, 67, 68)
    # приехали теми же файлами С ТОЧНОСТЬЮ ДО ПИКСЕЛЯ при ПЕРЕПИСАННЫХ по
    # объекту запросах, и на сцене 47 из-за этого до последнего стояла русская
    # схема ПДД «Г. Рубцовск». Поймала вкладка руками, сверкой размеров с
    # прошлым замером `photo_quality`; штатная проверка `report_same_file`
    # ловит это только ПОСЛЕ фетча, то есть ценой круга.
    # Поэтому: снятый кадр исключается из выдачи ВСЕГДА. Без `--ban` — на два
    # дня (заготовка не хоронится навсегда), с `--ban` — как раньше: веб-кадру
    # вечно, библиотечному на два дня.
    if not _ban:
        _n = sum(len(ids) for _, _, ids, _ in jobs)
        print(f"\nБЕЗ `--ban`: {_n} снятых кадров исключаются из выдачи на 2 "
              "ДНЯ автоматически — иначе источник вернёт тот же файл даже на "
              "переписанный по объекту запрос (замер 28.10: 4 сцены из 4).",
              flush=True)
        print("  Кадр плох САМ ПО СЕБЕ (клеймо, чужая страна, архив, рендер) "
              "— ставь `--ban`, тогда веб-кадр уйдёт навсегда.", flush=True)
    for _, assets, ids, _ in jobs:   # удаляем только теперь, линт прошёл
        for sid in ids:
            _md5s = []
            # СОБИРАЕМ ВСЕГДА, А НЕ ТОЛЬКО ПРИ `--ban`: без исключения из
            # выдачи поиск возвращает тот же файл (см. разбор выше).
            for f in glob.glob(os.path.join(assets, "scene_%03d.*" % sid)):
                if not f.endswith(SKIP_EXT) and ".ovthumb." not in f:
                    h = _md5(f)
                    if h:
                        _md5s.append(h)
            for f in wipe(assets, sid):
                print("  снёс %s" % f)
            # БИБЛИОТЕЧНЫЙ ФАЙЛ — БАН ВРЕМЕННЫЙ (2026-10-23). Отказ на одной
            # сцене не значит, что заготовка плоха всегда; вечный бан по md5
            # закрывает её для всех будущих роликов. Веб-кадру — как раньше.
            _lib = _from_library(assets, sid)
            for h in _md5s:
                _why_ban = ("рефетч --ban: кадр забракован на сцене %d" % sid
                            if _ban else
                            "рефетч: кадр заменён на сцене %d — временный бан, "
                            "чтобы поиск не вернул его снова" % sid)
                cmd = ["python3", os.path.join(here, "ban_file.py"), "--md5", h,
                       _why_ban]
                if _lib or not _ban:
                    cmd += ["--days", "2"]
                subprocess.run(cmd)
            if _md5s and not _ban:
                print("  прежний кадр исключён из выдачи на 2 дня (без "
                      "`--ban`) — иначе вернётся тот же файл.")
            if _lib and _md5s:
                print("  кадр ИЗ МЕДИАТЕКИ — бан временный, на 2 дня, чтобы "
                      "заготовка не выпала навсегда.")
                print("  Плох всегда? Забань руками: python3 ban_file.py "
                      "<путь> \"<причина>\"")

    round_record(pend, _fill_now, _why)   # круг засчитан, причина форса — в журнал

    failed_runs = []
    for sub, assets, ids, before in jobs:
        print("\n--- рефетч %s: %s ---" % (assets, ids))
        rc = subprocess.run(["python3", os.path.join(here, "fetch_parallel.py"),
                             sub, assets, ".env", "5"]).returncode
        if rc != 0:
            # НЕ путать «не нашлось» с «фетч не работал» (см. разбор выше)
            # 23.10: код 1 теперь означает ещё и «часть сцен осталась без
            # ФАЙЛА» (fetch_parallel считает итог по диску, а не по манифесту),
            # поэтому формулировка больше не утверждает, что фетч не работал.
            print("  ФЕТЧ ВЕРНУЛ КОД %d — часть сцен осталась без кадра. Смотри "
                  "строки «НЕТ ФАЙЛА У ... СЦЕН» и «ВОРКЕР УПАЛ» выше: там "
                  "названы конкретные сцены. Строки «ВЕРНУЛ прежний кадр» "
                  "означают откат, а НЕ то, что объект не находится." % rc)
            failed_runs.append((assets, rc))
        restore_missing(assets, ids)
        report_same_file(assets, before)
        sync_manifest(assets, ids)
    prune_needs_upload(only_ids=[sid for _, _, ids, _ in jobs for sid in ids])
    for sub, _, _, _ in jobs:
        if os.path.exists(sub):
            os.remove(sub)
    if failed_runs:
        # ИТОГ СЧИТАЕМ ПО ДИСКУ, А НЕ ПО КОДУ ВОЗВРАТА (28.10, см.
        # `count_replaced`): «фетч вернул 1» значит «часть сцен без кадра», а
        # не «ничего не сделано». Круг объявляется недействительным ТОЛЬКО
        # если не заменилась ни одна сцена.
        rep, kept, miss = [], [], []
        for _sub, _assets, _ids, _before in jobs:
            r, k, m = count_replaced(_assets, _before, _ids)
            rep += r; kept += k; miss += m
        total = len(rep) + len(kept) + len(miss)
        print("\nИТОГ ПО ДИСКУ: заменено %d из %d · осталось прежним %s · без "
              "файла %s" % (len(rep), total,
                            sorted(kept) or "нет", sorted(miss) or "нет"))
        if rep:
            print("КРУГ ЗАСЧИТАН, ПЕРЕДЕЛЫВАТЬ НЕ НАДО: %d замен состоялись и "
                  "лежат на диске. Фетч возвращал код по незакрытым сценам "
                  "(%s) — их веди в следующий круг СО СМЕНОЙ ОБЪЕКТА съёмки, "
                  "а не формулировки."
                  % (len(rep), ", ".join("%s код %d" % fr for fr in failed_runs)))
            return 0
        print("ИТОГ: не заменилась НИ ОДНА сцена — результат рефетча "
              "недействителен (%s)."
              % ", ".join("%s (код %d)" % fr for fr in failed_runs))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
