# -*- coding: utf-8 -*-
"""ПРИЁМКА РАСКАДРОВКИ, СДЕЛАННОЙ ДРУГИМ АГЕНТОМ (Codex).

Схема с 2026-10-23: Codex расписывает ролик на сцены и придумывает запросы
(самая думающая и дорогая по токенам часть), а сборку ведёт вкладка здесь.
Он ничего не запускает и о наших проверках не знает — значит его файл надо
принять строго, до того как за него заплачено поиском.

    python3 accept_scenes.py "/mnt/d/СБОРЩИК/ГОТОВО/<имя>.scenes.json" \\
        --srt <путь к .srt> [--out 5min.scenes.json]

Что проверяется:
  * структура: есть scenes, у каждой id/text/start_sec/duration_sec/source;
  * ТАЙМИНГ: сцены идут подряд без разрывов и нахлёстов, конец совпадает с
    озвучкой (это главное — на нём рассыпается весь монтаж);
  * источники из разрешённого списка;
  * нормы: доля стока, плотность карточек, расстояние между ними;
  * язык запроса: press_photo/web_search — по-русски, pexels — латиницей.

Чинит само только то, что чинится однозначно (накопленный дрейф start_sec).
Всё остальное — называет и выходит с кодом 1.
"""
import argparse
import json
import os
import re
import sys

OK_SOURCES = {"press_photo", "web_search", "pexels_photo", "pexels_video",
              "local_library", "direct_url"}
CARD_PREFIX = "card:"


def srt_end(path):
    """Последний таймкод SRT в секундах."""
    try:
        txt = open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return 0.0
    last = 0.0
    for m in re.finditer(r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*"
                         r"(\d\d):(\d\d):(\d\d)[,.](\d{1,3})", txt):
        h, mi, s, ms = map(int, m.group(5, 6, 7, 8))
        last = max(last, h * 3600 + mi * 60 + s + ms / 1000.0)
    return last


def main():
    ap = argparse.ArgumentParser(description="принять раскадровку от Codex")
    ap.add_argument("src")
    ap.add_argument("--srt", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--fix", action="store_true", help="починить дрейф start_sec")
    ap.add_argument("--channel", default="5 МИНУТ",
                    help="канал в шапку готового файла (ПЛАНЕТА / 5 МИНУТ / …)")
    ap.add_argument("--per-scene", type=float, default=0.0,
                    help="секунд на сцену для нормы (по умолчанию 11.5; "
                         "13.2 — замер «ужать на 13%% разбросом», 28.10)")
    a = ap.parse_args()

    try:
        data = json.load(open(a.src, encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"ОШИБКА: не прочитать {a.src}: {e}")
    scenes = data.get("scenes") if isinstance(data, dict) else data
    if not scenes:
        sys.exit("ОШИБКА: в файле нет сцен")

    bad, warn = [], []
    # --- поля ---
    for i, sc in enumerate(scenes, 1):
        for f in ("id", "text", "start_sec", "duration_sec", "source"):
            if f not in sc:
                bad.append(f"сцена #{i}: нет поля {f}")
        src = str(sc.get("source", ""))
        if src and not src.startswith(CARD_PREFIX) and src not in OK_SOURCES:
            bad.append(f"сцена {sc.get('id')}: неизвестный источник «{src}»")
        if not src.startswith(CARD_PREFIX) and not str(sc.get("source_query", "")).strip():
            bad.append(f"сцена {sc.get('id')}: пустой source_query")
        d = float(sc.get("duration_sec") or 0)
        if d < 3:
            bad.append(f"сцена {sc.get('id')}: длительность {d:.1f} с — короче трёх секунд")
        elif d > 15:
            warn.append(f"сцена {sc.get('id')}: длительность {d:.1f} с — длиннее пятнадцати")

    # --- тайминг: непрерывность ---
    drift = []
    t = 0.0
    for sc in scenes:
        st = float(sc.get("start_sec") or 0)
        if abs(st - t) > 0.05:
            drift.append((sc.get("id"), st, t))
        t = (st if not a.fix else t) + float(sc.get("duration_sec") or 0)
    if drift and not a.fix:
        bad.append(f"ТАЙМИНГ РАЗЪЕХАЛСЯ у {len(drift)} сцен "
                   f"(первая — сцена {drift[0][0]}: стоит {drift[0][1]:.2f}, "
                   f"должно быть {drift[0][2]:.2f}). Перезапусти с --fix")

    total = sum(float(s.get("duration_sec") or 0) for s in scenes)
    if a.srt:
        end = srt_end(a.srt)
        if end and abs(total - end) > 1.5:
            bad.append(f"ДЛИТЕЛЬНОСТЬ НЕ СХОДИТСЯ: сцены дают {total:.1f} с, "
                       f"озвучка {end:.1f} с (разница {abs(total-end):.1f} с)")

    # --- нормы ---
    n = len(scenes)
    stock = sum(1 for s in scenes if str(s.get("source", "")).startswith("pexels"))
    cards = [i for i, s in enumerate(scenes)
             if str(s.get("source", "")).startswith(CARD_PREFIX)]
    if n:
        pct = 100.0 * stock / n
        if pct > 25:
            warn.append(f"стока {pct:.0f}% — коридор 10-20%")
        elif pct < 5:
            warn.append(f"стока {pct:.0f}% — маловато, начало ролика будет статичным")
    # ЧИСЛО СЦЕН — ФОРМУЛОЙ (24.10, прямое слово пользователя «это дофига, 101»).
    # сцен = длительность ÷ 11,5 (медиана по сданным роликам), допуск ±10%.
    if total > 60:
        # ШАГ СЦЕНЫ — КЛЮЧОМ, А НЕ КОНСТАНТОЙ (28.10, по прямому слову
        # пользователя: «ужимать надо разбросом»). 11,5 с остаётся значением по
        # умолчанию — это медиана по сданным роликам, и без ключа поведение
        # прежнее, идущие ролики правка не задевает. При `--per-scene 13.2`
        # норма падает на 13%, а длительности внутри ролика расходятся: 8-10 с
        # под клипы (видео-лид от этого выигрывает), 14-16 с под фото со
        # всплывашкой в середине, 11-12 с на именные сцены.
        want = total / (a.per_scene or 11.5)
        # ВЕРХНЯЯ ГРАНИЦА ПРИ ЗАДАННОМ ШАГЕ ШИРЕ (28.10, замер «Круговая
        # оборона»): норма 48 с допуском 43-52, а минимально достижимый
        # результат — 53, потому что сцены длиннее 16 с правило запрещает и их
        # приходится резать. Получалась ложная тревога ровно там, где правка
        # обязательна. При явном `--per-scene` верх считаем +20%.
        _hi = 1.2 if a.per_scene else 1.1
        if n > want * _hi:
            warn.append("сцен %d при норме %d (%.0f-%.0f) — нарезано мелко, "
                        "медиана %.1f с; каждая лишняя сцена это лишний запрос "
                        "и лишняя плитка на проверку"
                        % (n, round(want), want * 0.9, want * _hi, total / n))
        elif n < want * 0.9:
            warn.append("сцен %d при норме %d (%.0f-%.0f) — кадры будут «застывать»"
                        % (n, round(want), want * 0.9, want * _hi))
    # ВИД КАРТОЧКИ СВЕРЯЕМ С РЕЕСТРОМ ДВЕРИ (2026-10-27, улов `usuario-54` на
    # `5min-granica1997`). Приёмка проверяла только ПРЕФИКС `card:` — поэтому
    # выдуманный агентом `card:bullets` прошёл с кодом 0. Дефект был бы поздним
    # и немым: за `card:*` фетч не идёт, такой вид `card_put.py` не примет,
    # карточку никто не нарисует — в сборке просто пустые сцены. Список берём
    # из самого `card_put.py`, чтобы он не разъезжался с дверью: добавят вид
    # туда — приёмка узнает о нём сама.
    _known = set()
    try:
        _cp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "fullcycle", "card_put.py")
        _txt = open(_cp, encoding="utf-8").read()
        _blk = re.search(r"VIEWS = \{(.*?)\n\}", _txt, re.S)
        if _blk:
            _known = set(re.findall(r'"([a-z_]+)":', _blk.group(1)))
    except Exception:
        _known = set()
    for i in cards:
        _view = str(scenes[i].get("source", ""))[len(CARD_PREFIX):].strip()
        if not _view:
            bad.append("сцена %s: источник «card:» без вида — карточку нечем "
                       "рисовать" % scenes[i].get("id"))
        elif _known and _view not in _known:
            bad.append("сцена %s: вида карточки «%s» НЕ СУЩЕСТВУЕТ — "
                       "`card_put.py` знает только: %s. За `card:*` фетч не "
                       "идёт, значит сцена осталась бы пустой молча"
                       % (scenes[i].get("id"), _view,
                          ", ".join(sorted(_known))))

    norm = max(1, round(n / 15))
    if len(cards) > norm + 1:
        warn.append(f"карточек {len(cards)} при норме {norm} (+1 допуск)")
    for x, y in zip(cards, cards[1:]):
        if y - x < 8:
            warn.append(f"карточки на сценах {scenes[x]['id']} и {scenes[y]['id']} "
                        f"ближе восьми сцен друг к другу")

    # --- ШАБЛОННОСТЬ: уникальность по СМЫСЛУ, а не по приписке (23.10) ---
    # Живой случай: агент получил замечание «запросы повторяются» и приписал к
    # одному шаблону номер сцены — «переговоры …, 2025, сцена 41 — общий план»,
    # «…, сцена 42 — …». Формально 96 уникальных, по сути три. Плюс «сцена 41»
    # внутри поискового запроса — мусор, который поиску мешает.
    junk = re.compile(r"\s*,?\s*сцена\s*\d+\s*[—–-]?.*$|\s*[—–-]\s*(документальн|полевой|общий план).*$",
                      re.I)
    cores = {}
    for sc in scenes:
        if str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q = str(sc.get("source_query", ""))
        if re.search(r"сцена\s*\d+", q, re.I):
            bad.append(f"сцена {sc.get('id')}: в запросе служебная пометка «сцена N» — "
                       f"это мусор для поиска, убери")
        core = junk.sub("", q).strip().lower()
        core = " ".join(core.split()[:6])          # смысловое ядро запроса
        cores.setdefault(core, []).append(sc.get("id"))
    many = {k: v for k, v in cores.items() if len(v) > 3 and k}
    if many:
        worst = max(many.items(), key=lambda kv: len(kv[1]))
        bad.append(f"ЗАПРОСЫ ШАБЛОННЫЕ: {len(many)} формулировок повторяются более трёх раз. "
                   f"Худшая — «{worst[0][:50]}…» на {len(worst[1])} сценах "
                   f"({', '.join(map(str, worst[1][:6]))}…). Нужен СВОЙ предмет в каждой сцене")

    # ГОЛОВНАЯ ГРУППА СЛОВ — ВОТ ЧТО РЕШАЕТ (23.10, улов `usuario-dd`).
    # Прежняя проверка считала ядро по шести словам и ругалась лишь при более
    # чем трёх повторах — и пропустила подмену: агент взял пул из ~34 фраз и
    # прокрутил его ДВАЖДЫ, меняя только хвост-обстоятельство («…, утренний
    # свет» / «…, рядом с наблюдательной машиной»). Формально 95 уникальных
    # строк, на деле 25 пар одинаковых запросов. Поисковик ранжирует по первым
    # словам, хвост игнорирует (правило h), так что на фетче это дало бы
    # ~26 дублей по md5 и круг правок на ровном месте.
    heads = {}
    for sc in scenes:
        if str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q = junk.sub("", str(sc.get("source_query", ""))).strip().lower()
        h = " ".join(q.split()[:3])
        if h:
            heads.setdefault(h, []).append(sc.get("id"))
    pairs = {k: v for k, v in heads.items() if len(v) > 1}
    if pairs:
        # ИМЯ ЗДЕСЬ НЕ `total` (27.10, улов `usuario-31`): этим именем выше, на
        # строке ~96, посчитана ОБЩАЯ ДЛИТЕЛЬНОСТЬ ролика, и печать итога берёт
        # его же — переиспользование превращало «812,2 с» в «2.0 с», то есть
        # принятый файл выглядел пустым. Сама проверка длительности была живой,
        # врала только печать: ровно класс «успех ≠ сделанная работа».
        n_heads = sum(len(v) for v in pairs.values())
        worst = max(pairs.items(), key=lambda kv: len(kv[1]))
        msg = (f"ОДИНАКОВОЕ НАЧАЛО ЗАПРОСА у {n_heads} сцен в {len(pairs)} группах "
               f"(худшая — «{worst[0]}…» на сценах {', '.join(map(str, worst[1][:8]))}). "
               f"Поиск ранжирует по ПЕРВЫМ словам, хвост-обстоятельство он игнорирует — "
               f"эти сцены получат один и тот же кадр")
        (bad if total > len(scenes) * 0.15 else warn).append(msg)

    # --- ОДИН ОБЪЕКТ, РАЗМНОЖЕННЫЙ ФОРМУЛИРОВКАМИ (25.10, улов `usuario-6f`) ---
    # Новый класс брака раскадровки внешнего агента: уникальность ТЕКСТА запросов
    # соблюдена идеально (64 из 64 уникальны, проверка выше молчит), а по существу
    # один и тот же объект заказан восемь раз разными определениями — «трибуна»,
    # «полукруг», «депутатские ряды», «пленарные места», «вид из зала», «фасад».
    # На живом ролике так вышло 35 сцен из 69 на ПЯТИ объектах. Дефект приезжает
    # дважды: зритель видит один зал восемь раз (правило f), и половина запросов
    # возвращает один файл по md5 (правило h) — то есть ещё и круг правок.
    # Считаем по КОРНЮ существительного, а не по формулировке.
    # служебные слова наших же правил (год/месяц по правилу i, «реальное фото»
    # по шаблону запроса) объектом не являются
    _STOP = {"реальн", "фотогр", "крупны", "общий", "кадр", "съёмка", "съемка",
             "украин", "россий", "москва", "видео", "плане", "вид",
             "январ", "феврал", "марта", "апрел", "май", "июня", "июля",
             "август", "сентяб", "октябр", "ноябр", "декабр",
             # РОДОВЫЕ СЛОВА КОМПОНОВКИ — НЕ ОБЪЕКТ (28.10, улов вкладки
             # «Стубб»): у неё валились `перед…`, `фасад…`, `здани…`,
             # `площад…`, `общий…`, `минист…`. «Фасад министерства обороны
             # Польши» и «фасад министерства финансов Германии» — РАЗНЫЕ
             # объекты, а проверка видела один: она группирует по
             # шестисимвольным основам ВСЕХ значимых слов. Из-за этого приёмка
             # валила круг за кругом на законной раскадровке.
             "фасад", "здани", "площад", "перед", "интерь", "помещ",
             "улица", "улице", "входа", "входе", "минист", "ведомс",
             "комнат", "корпус", "террит", "снаруж", "внутри",
             # АНГЛИЙСКИЕ СЛУЖЕБНЫЕ СЛОВА СТОКА (28.10, замер «Круговая
             # оборона»): основа `closeu…` склеила ПЯТЬ разных предметов —
             # шины фуры, разметку, ковш экскаватора, бетон, колесо вагона.
             # Причём `closeup` предписывает добавлять САМ `query_lint` как
             # лечение мины «дорожная сцена без страны»: один инструмент
             # советовал то, что другой считал повтором объекта.
             "closeu", "close-", "macro", "detail", "shot", "footag",
             "angle", "aerial", "slow m", "timela", "handhe", "tracki"}
    # ИМЯ СОБСТВЕННОЕ РАЗЛИЧАЕТ ОБЪЕКТЫ (28.10, тот же улов). Если у сцен с
    # одной основой РАЗНЫЕ имена собственные (страна, город, ведомство,
    # фамилия), это разные объекты, а не повтор одного. Поэтому внутри группы
    # считаем сцены по НАБОРУ имён: ругаемся только если один и тот же набор
    # встречается больше трёх раз.
    roots = {}
    for sc in scenes:
        if str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q_raw = str(sc.get("source_query", ""))
        names = frozenset(w.lower()[:6] for w in re.findall(r"\b[А-ЯЁA-Z][а-яёa-z]{3,}", q_raw))
        seen = set()
        for w in re.findall(r"[а-яёa-z]{5,}", q_raw.lower()):
            r = w[:6]
            if r in _STOP or r in seen:
                continue
            seen.add(r)
            roots.setdefault(r, []).append((sc.get("id"), names))
    _by_root = {}
    for r, items in roots.items():
        from collections import Counter
        cnt = Counter(n for _, n in items)
        worst_names, worst_n = cnt.most_common(1)[0]
        if worst_n > 3:
            _by_root[r] = [sid for sid, n in items if n == worst_names]
    roots = _by_root
    heavy = sorted((v for v in roots.values() if len(v) > 3), key=len, reverse=True)
    if heavy:
        named = sorted(((r, v) for r, v in roots.items() if len(v) > 3),
                       key=lambda kv: len(kv[1]), reverse=True)
        head = "; ".join("«%s…» — %d сцен (%s)" % (r, len(v), ", ".join(map(str, v[:8])))
                         for r, v in named[:5])
        warn.append("ОДИН ОБЪЕКТ НА МНОГИХ СЦЕНАХ, разными словами: " + head +
                    " — норма не больше трёх сцен на объект. Уникальность текста "
                    "запросов тут не спасает: зритель увидит один и тот же кадр, "
                    "а часть запросов вернёт один файл по md5")

    # --- КАРТОЧКА: цитата, а не обрывок ---
    for sc in scenes:
        if not str(sc.get("source", "")).startswith(CARD_PREFIX):
            continue
        q = str(sc.get("source_query", "")).strip()
        if not q:
            continue
        first = q.split()[0] if q.split() else ""
        if first and first[:1].islower():
            warn.append(f"сцена {sc.get('id')}: текст карточки начинается с середины фразы "
                        f"(«{q[:40]}…») — нужна цитата целиком")

    # --- язык запроса ---
    cyr = re.compile(r"[а-яёА-ЯЁ]")
    for s in scenes:
        src, q = str(s.get("source", "")), str(s.get("source_query", ""))
        if src in ("press_photo", "web_search") and q and not cyr.search(q):
            warn.append(f"сцена {s.get('id')}: запрос не по-русски — «{q[:60]}»")
        if src.startswith("pexels") and cyr.search(q):
            bad.append(f"сцена {s.get('id')}: pexels ищет только латиницей — «{q[:60]}»")

    print(f"сцен: {n}, общая длительность {total:.1f} с")
    print(f"источники: press/web {sum(1 for s in scenes if s.get('source') in ('press_photo','web_search'))}, "
          f"сток {stock}, карточек {len(cards)}")
    for w in warn:
        print("  ВНИМАНИЕ:", w)
    for b in bad:
        print("  ОШИБКА:", b, file=sys.stderr)

    if a.fix:
        t = 0.0
        for sc in scenes:
            sc["start_sec"] = round(t, 2)
            t += float(sc.get("duration_sec") or 0)
        print("  тайминг пересчитан подряд от нуля")
        neg = [s.get("id") for s in scenes if float(s.get("duration_sec") or 0) <= 0]
        if neg:
            bad.append("после пересчёта остались неположительные длительности у сцен "
                       + ", ".join(map(str, neg))
                       + " — это не дрейф, а выдуманные числа: переделка")

    # `--fix` ЧИНИТ ТОЛЬКО ТАЙМИНГ И НЕ СНИМАЕТ ОСТАЛЬНЫЕ ОШИБКИ (24.10).
    # Живой случай на `planeta-evak-2510`: без `--fix` приёмка честно отказывала
    # («ПРИНИМАТЬ НЕЛЬЗЯ», код 1), а с `--fix` печатала «принято → …» и код 0,
    # хотя в файле оставались отрицательная длительность −86,6 с у последней
    # сцены и два шаблона запросов. Вкладка, доверившая `--fix`, уехала бы в
    # фетч с мусором и ничего не заметила. Дыра была ровно в том месте, которое
    # приёмка и должна закрывать.
    if bad:
        print("\nПРИНИМАТЬ НЕЛЬЗЯ — исправь перечисленное или попроси переделать."
              + ("\n(`--fix` чинит только дрейф start_sec; перечисленное выше он "
                 "не лечит — это переделка на его стороне.)" if a.fix else ""),
              file=sys.stderr)
        return 1
    if a.out:
        if isinstance(data, dict):
            data["channel"] = a.channel
            data["scenes"] = scenes
        else:
            data = {"channel": a.channel, "scenes": scenes}
        json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\nпринято → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
