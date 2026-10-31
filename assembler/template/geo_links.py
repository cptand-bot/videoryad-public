#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ССЫЛКИ ДОСЬЕ — ТОЛЬКО ТЕ, ЧТО ПРИВЯЗАНЫ К ЗАПИСИ ЭТОГО РОЛИКА.

    geo_links.py <geo.xlsx> <ключ записи> [--out links.txt] [--hops 5]
                 [--show]

Прямое слово пользователя 31.10, дважды: «Фото и видео из георадара должно
уходить НЕРАНДОМНО, по темам. А конкретно привязанным темам по записи ID в
георадаре… Каждая запись ID закрепляется за определённой темой, картинки
соответствуют ТОЛЬКО этой теме. И никакой другой. Никакие другие вкладки они
попадать не должны.»

Поэтому строки отбираются НЕ ПО СЛОВУ, а по идентификаторам записи. Поиск по
слову собирает чужое: на живой таблице «ослабленный критерий» дал 253 ссылки
против 35 привязанных, а по общим персоналиям — 960 (Зеленский 601 попадание,
Путин 542). Это материал ДРУГИХ роликов, и ставить его нельзя.

Как работает:
  1. находит строки, где встречается сам ключ;
  2. выбирает из них ИДЕНТИФИКАТОРЫ (`PROD_…`, `ARM_…`, `AN_…`, `HOOK_…`,
     `ANG_…`, `GEO2_…`) — это и есть связи записи;
  3. делает `--hops` шагов по этим связям по ВСЕМ листам;
  4. из найденных строк вытаскивает ссылки `t.me/<канал>/<номер>`.

Рядом с `links.txt` пишет `tg_source.json`: ключ, все использованные
идентификаторы, по каким листам и сколько ссылок — чтобы отбор можно было
проверить, а не поверить на слово.
"""
import collections
import json
import os
import re
import sys

# ЦЕПОЧКА СВЯЗЕЙ ТАБЛИЦЫ, ПРОЙДЕННАЯ ПО ЖИВЫМ ДАННЫМ 31.10:
#   Productions(production_id, main_storyline_id) → Storylines(STY_…)
#   → StorylineEvents(SLE_… → EVT_…) → Events(EVT_…)
#   → EventClaims(ECL_… → CLM_…) → Claims(CLM_…, record_key)
#   → Archive / NewsInbox(record_key → original_link), плюс ветка автора
#   AuthorReasoning / AuthorReasoningRelations / AnalysisLinks (ARM_, ARR_,
#   ANL_, ANG_, HOOK_, AUD_).
# Ссылка на пост лежит в `Archive`/`NewsInbox`, а связь с записью идёт через
# `record_key` вида `-1002814742406:2423` — без него цепочка обрывается на
# `Claims`, и первый прогон отдал НОЛЬ ссылок при восьми найденных
# идентификаторах.
ID_RE = re.compile(
    r"\b(?:PROD|GEO2|STY|SLE|EVT|ECL|CLM|ARM|ARR|ANL|ANG|HOOK|AUD|AN)"
    r"_[A-Za-z0-9][A-Za-z0-9_]{3,}\b")
# `record_key` — тоже идентификатор связи, но формы «чат:сообщение».
KEY_RE = re.compile(r"-?\d{10,}:\d+")
# УЗЛЫ-ХАБЫ В ОБХОД НЕ БЕРЁМ. `ENT_ZELENSKY` стоит в сотнях утверждений, а
# `SRC_TELEGRAM_<канал>` — во всех постах канала: пойдя по ним, обход
# вытащил бы ВЕСЬ архив (замер: 960 ссылок, Зеленский 601 попадание) — ровно
# то «хаотичное раскидывание по вкладкам», которое запрещено. Сущность и
# канал описывают МИР, а не тему записи.
HUBS = ("ENT_", "SRC_", "LOC_", "ORG_")
# ПО ЧЕМУ ИДТИ ДАЛЬШЕ ПЕРВОГО ШАГА — СТРОГО (31.10, замер на трёх живых
# ключах). Свободный обход по всем идентификаторам РАЗМЫВАЕТ ТЕМУ: граф
# авторских записей (`ARM_`, `ARR_`, `ANL_`, `AUD_`) связывает между собой ВСЕ
# записи дня, и два разных ролика — НПЗ и Абу-Даби — получили одни и те же 23
# ссылки. Это ровно то «хаотичное раскидывание по вкладкам», которое
# запрещено. Поэтому со второго шага идём ТОЛЬКО по предметной цепочке:
# сюжет → события → утверждения → ключ записи поста → `Archive`/`NewsInbox`.
# Авторские рассуждения дают материал только СВОИМИ строками (первый шаг):
# что автор привязал к записи руками, то и наше.
FOLLOW = ("GEO2_", "STY_", "SLE_", "EVT_", "ECL_", "CLM_", "ANG_", "HOOK_")
TG_RE = re.compile(r"https?://t\.me/[A-Za-z0-9_]+/\d+")


def rows_of(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        for r in ws.iter_rows(values_only=True):
            line = " | ".join(str(c) for c in r if c is not None)
            if line.strip():
                yield ws.title, line


CLAIMS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "base", "tg_claims.json")


def claims_load():
    """КТО УЖЕ ВЗЯЛ ЭТУ ССЫЛКУ (31.10, прямое слово пользователя).

    «Каждая запись ID в георадаре закрепляется за определённой темой, картинки
    соответствуют ТОЛЬКО этой теме. И никакой другой. Только эти картинки и
    только для этой темы. НИКАКИЕ ДРУГИЕ ВКЛАДКИ они попадать не должны.»

    Одной привязки по идентификаторам для этого мало: у части записей автор
    посты к ключу не подвязывал вовсе (замер 31.10: по цепочке ключа ноль
    ссылок там, где вкладка руками нашла 25 и 65). Поэтому закрепление
    держится ЖУРНАЛОМ: ссылка, взятая роликом, помечается его именем, и другой
    ролик её уже не получит — независимо от того, как она была найдена.
    """
    try:
        return json.load(open(os.path.normpath(CLAIMS), encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def claims_save(d):
    try:
        os.makedirs(os.path.dirname(os.path.normpath(CLAIMS)), exist_ok=True)
        json.dump(d, open(os.path.normpath(CLAIMS), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except OSError as e:
        print("!! журнал закрепления не записан: %s" % e, file=sys.stderr)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    xlsx, key = args[0], args[1].strip()
    out = "links.txt"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    hops = 5
    if "--hops" in sys.argv:
        hops = max(1, int(sys.argv[sys.argv.index("--hops") + 1]))
    project = os.path.basename(os.path.abspath(os.getcwd()))
    if "--project" in sys.argv:
        project = sys.argv[sys.argv.index("--project") + 1]
    words = []
    if "--words" in sys.argv:
        words = [w.strip().upper() for w in
                 re.split(r"[;,]", sys.argv[sys.argv.index("--words") + 1])
                 if w.strip()]
    dates = []
    if "--date" in sys.argv:
        dates = [d.strip() for d in
                 re.split(r"[;,]", sys.argv[sys.argv.index("--date") + 1])
                 if d.strip()]

    rows = list(rows_of(xlsx))
    print("строк в таблице: %d" % len(rows))

    ids = {key.upper()}
    sheets = collections.Counter()
    links = collections.OrderedDict()
    for hop in range(hops):
        grew = set()
        n_rows = 0
        for sheet, line in rows:
            up = line.upper()
            if not any(i in up for i in ids):
                continue
            n_rows += 1
            sheets[sheet] += 1
            for m in ID_RE.findall(line) + KEY_RE.findall(line):
                mu = m.upper()
                if mu in ids or mu.startswith(HUBS):
                    continue
                if hop == 0 or mu.startswith(FOLLOW) or KEY_RE.fullmatch(mu):
                    grew.add(mu)
            for u in TG_RE.findall(line):
                links.setdefault(u, sheet)
        print("шаг %d: строк по связям %d, идентификаторов было %d, "
              "добавилось %d, ссылок %d"
              % (hop + 1, n_rows, len(ids), len(grew), len(links)))
        if not grew:
            break
        ids |= grew

    # ВТОРОЙ ПРОХОД — ПО ТЕМЕ ЗАПИСИ, И ОН ПОМЕЧАЕТСЯ ОТДЕЛЬНО. Нужен там, где
    # автор посты к ключу не подвязал: по цепочке ключа ноль, а материал есть.
    # Такие ссылки годны ТОЛЬКО если тема совпадает, и закрепление за роликом
    # их всё равно разведёт по вкладкам.
    topic = collections.OrderedDict()
    if words or dates:
        for sheet, line in rows:
            up = line.upper()
            if words and not any(w in up for w in words):
                continue
            if dates and not any(d in line for d in dates):
                continue
            for u in TG_RE.findall(line):
                if u not in links:
                    topic.setdefault(u, sheet)
        print("по теме записи (слова/дата) нашлось ещё %d ссылок" % len(topic))

    # ЗАКРЕПЛЕНИЕ: чужое не берём, своё помечаем.
    cl = claims_load()
    taken = {u: cl[u] for u in list(links) + list(topic)
             if u in cl and cl[u].get("проект") != project}
    for u in taken:
        links.pop(u, None)
        topic.pop(u, None)
    if taken:
        print("\nЧУЖОЕ, НЕ БЕРУ — %d ссылок уже закреплены за другими "
              "роликами:" % len(taken))
        for u, v in list(taken.items())[:15]:
            print("  %s → %s (ключ %s)"
                  % (u, v.get("проект"), v.get("ключ")))
    for u in list(links) + list(topic):
        cl[u] = {"проект": project, "ключ": key,
                 "привязка": "по идентификаторам записи" if u in links
                             else "по теме записи"}
    claims_save(cl)

    if not links and not topic:
        print("\nССЫЛОК НЕТ. Либо ключ назван неверно, либо у записи нет "
              "привязанных постов. Проверь ключ по таблице (бывает PROD_, "
              "ARM_, AN_…_CONTEXT, HOOK_) и не подменяй его поиском по слову: "
              "чужие ссылки в ролик не идут.", file=sys.stderr)

    with open(out, "w", encoding="utf-8") as f:
        for u in links:
            f.write(u + "\n")
    if topic:
        t_out = os.path.join(os.path.dirname(os.path.abspath(out)),
                             "links_topic.txt")
        with open(t_out, "w", encoding="utf-8") as f:
            for u in topic:
                f.write(u + "\n")
        print("по теме записи: %d → %s (ставить только при совпадении темы, "
              "иначе в tg_rejected.json)" % (len(topic), t_out))
    meta = {"ключ": key, "проект": project,
            "идентификаторы": sorted(ids), "листы": dict(sheets),
            "ссылок по идентификаторам": len(links),
            "ссылок по теме": len(topic),
            "отдано другим роликам": {u: v.get("проект") for u, v in taken.items()},
            "файл": os.path.abspath(out)}
    side = os.path.join(os.path.dirname(os.path.abspath(out)), "tg_source.json")
    json.dump(meta, open(side, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("\nИТОГ: ссылок %d → %s (разбор отбора: %s)"
          % (len(links), out, os.path.basename(side)))
    print("идентификаторов записи: %d — %s"
          % (len(ids), ", ".join(sorted(ids)[:12])))
    print("по листам: %s" % ", ".join("%s %d" % kv for kv in sheets.most_common()))
    if "--show" in sys.argv:
        for u in links:
            print("  " + u)
    print("дальше: tg_media.py --json tg.json $(cat %s)" % out)
    return 0 if (links or topic) else 1


if __name__ == "__main__":
    sys.exit(main())
