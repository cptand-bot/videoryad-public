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


def _release(args, project):
    """Отпустить ссылки, закреплённые ЗА ЭТИМ роликом (03.11).

    Повод живой: хоп-обход `geo_links` по ключу соседнего ролика притащил 7
    ссылок ЧУЖОЙ темы (ракета FP-7, боеголовки КНДР, Зеленский про НПЗ, два
    поста про Patriot) и закрепил их за ним же. Вкладка их законно не взяла —
    но журнал закрепления уже считал их занятыми, и РОДНОЙ ролик этой темы
    получал «ЧУЖОЕ, НЕ БЕРУ» на свой собственный материал. Руками журнал
    править нельзя: он один на всю машину и его пишут четыре вкладки.

    Отпускается ТОЛЬКО своё: запись, закреплённая за другим проектом, не
    трогается (иначе один ролик уводил бы кадры у другого).
    """
    urls = []
    for a in args:
        if os.path.isfile(a):
            urls += [l.strip() for l in open(a, encoding="utf-8") if l.strip()]
        elif a.startswith("http"):
            urls.append(a.strip())
    if not urls:
        print("--release: нечего отпускать. Дай ссылки списком или файлом "
              "(например links.txt).", file=sys.stderr)
        return 2
    cl = claims_load()
    freed, foreign, absent = [], [], []
    for u in urls:
        v = cl.get(u)
        if not v:
            absent.append(u)
        elif v.get("проект") != project:
            foreign.append((u, v.get("проект")))
        else:
            cl.pop(u)
            freed.append(u)
    if freed:
        claims_save(cl)
    print("отпущено: %d (проект %s)" % (len(freed), project))
    for u in freed:
        print("  " + u)
    if foreign:
        print("НЕ ТРОГАЛ, это чужое закрепление: %d" % len(foreign))
        for u, pr in foreign[:10]:
            print("  %s → %s" % (u, pr))
    if absent:
        print("в журнале не было: %d" % len(absent))
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    # --release идёт БЕЗ таблицы и ключа: отпустить ссылки, которые этот ролик
    # взял и не использовал, чтобы их получил ролик своей темы.
    if "--release" in sys.argv:
        _pr = os.path.basename(os.path.abspath(os.getcwd()))
        if "--project" in sys.argv:
            _pr = sys.argv[sys.argv.index("--project") + 1]
        return _release(args, _pr)
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
    # НА КАКОМ ШАГЕ ПРИШЛА ССЫЛКА (05.11, улов `usuario-ca`). По ключу
    # EUENLARGE_255 обход дал 24 ссылки, по теме ролика — 7: запись соседней
    # темы перечислена в связях, и дальние шаги тянут её посты. Выбросить
    # дальние нельзя (04.11 было ровно наоборот: запись называет СВОИ
    # источники, и их отбивали как чужие), а вот СКАЗАТЬ, какие ближние и
    # какие дальние, дёшево — разбор вкладки начинается с ближних.
    hop_of = {}
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
                if u not in links:
                    hop_of[u] = hop
                links.setdefault(u, sheet)
        print("шаг %d: строк по связям %d, идентификаторов было %d, "
              "добавилось %d, ссылок %d"
              % (hop + 1, n_rows, len(ids), len(grew), len(links)))
        # КЛЮЧА В ТАБЛИЦЕ НЕТ — ЭТО ДРУГОЕ, ЧЕМ «ПОСТЫ НЕ ПОДВЯЗАНЫ» (01.11,
        # улов `usuario-49`). Оба случая давали «ссылок 0» и читались
        # одинаково, а лечатся по-разному: подвязки нет — работай по словам и
        # дате; ключа нет вовсе — названный ключ НЕ СУЩЕСТВУЕТ, и запись надо
        # искать по сущностям, иначе ролик уедет вообще без досье. Живой
        # случай: редакция назвала `ARM_20261101_ENERGY_NPZ_AUDIT_MASTER_133`,
        # которого в таблице нет ни разу (номера дня доходили до 130).
        if hop == 0 and n_rows == 0:
            print("\n!! КЛЮЧ «%s» НЕ ВСТРЕТИЛСЯ В ТАБЛИЦЕ НИ РАЗУ — это не "
                  "«посты не подвязаны», это НЕСУЩЕСТВУЮЩИЙ КЛЮЧ." % key,
                  file=sys.stderr)
            print("   Проверь номер у редакции и найди запись по СУЩНОСТЯМ "
                  "(дата, фамилии, объекты) разбором xlsx — ключи бывают "
                  "PROD_, ARM_, AN_…_CONTEXT, HOOK_, и номер соседней записи "
                  "того же дня обычно рядом.", file=sys.stderr)
            # НОМЕРА ИДУТ ВПЕРЕДИ ТАБЛИЦЫ, А У ТЕМЫ МОЖЕТ НЕ БЫТЬ ЗАПИСИ
            # ВОВСЕ (01.11, уловы `usuario-49` и `usuario-a5` — два мёртвых
            # ключа из двух на ПЛАНЕТЕ). Серия дня доходила до _130, а
            # названы были _133 и _135; у второй темы оформленной записи не
            # существовало, и единственным рабочим ключом оказался СНАПШОТ
            # СПИСКА постов на листе `GEO2_ListSnapshots` (вид
            # `GEO2-20261101-48-v1`). Поэтому порядок поиска такой.
            print("   Если записи нет и по сущностям: ищи СНАПШОТ СПИСКА на "
                  "листе GEO2_ListSnapshots (вид GEO2-ГГГГММДД-NN-v1) — у "
                  "свежей темы Production-записи может не быть вовсе, а "
                  "посты уже лежат в Archive/NewsInbox/SelectionObservations.",
                  file=sys.stderr)
        if not grew:
            break
        ids |= grew

    # ТРЕТИЙ ПУТЬ: СНАПШОТ СПИСКА (01.11, разбор по прямому вопросу
    # пользователя «почему кадры КНДР из георадара не вошли»).
    # У записи `PROD_20261101_GEOPOLITICAL_MIX_IRAN_KOREA_V1` цепочки нет
    # вовсе: `main_storyline_id` не встречается ни в `Storylines`, ни в
    # `Events`, ни в `Claims` — запись в статусе draft. Единственная связь с
    # постами идёт через лист `GEO2_ListSnapshots`: снапшоты вида
    # `GEO2-20261101-48-v1` содержат `record_key` постов (`-100…:560`), а уже
    # по этому ключу пост лежит в `Archive`/`NewsInbox`. Обход по графу таких
    # связей не видел, и материал (единственный пост про КНДР, 28.10, «Ким Чен
    # Ын приказал усилить подготовку армии», ЦТАК) в ролик не попадал.
    # Берём ТОЛЬКО снапшоты той же даты, что и запись, и помечаем отдельно —
    # это не «привязано к ключу», а «лежит в списке того же дня».
    snap = collections.OrderedDict()
    _d8 = re.search(r"(20\d{6})", key)
    if not links and _d8:
        _snap_keys = set()
        for sheet, line in rows:
            if "LISTSNAPSHOT" not in sheet.upper() and "SNAPSHOT" not in line.upper():
                continue
            if _d8.group(1) not in line:
                continue
            _snap_keys |= set(KEY_RE.findall(line))
        if _snap_keys:
            for sheet, line in rows:
                if not any(k in line for k in _snap_keys):
                    continue
                for u in TG_RE.findall(line):
                    if u not in links:
                        snap.setdefault(u, sheet)
            print("по СНАПШОТУ СПИСКА того же дня (%s) нашлось %d ссылок — "
                  "это посты, отобранные редакцией в этот день; ставь только "
                  "те, что по теме ролика" % (_d8.group(1), len(snap)))

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

    if links:
        _hp = "links_hops.txt"
        try:
            with open(_hp, "w", encoding="utf-8") as _f:
                for _u in sorted(links, key=lambda x: (hop_of.get(x, 9), x)):
                    _f.write("%d\t%s\n" % (hop_of.get(_u, 9), _u))
            _near = sum(1 for _u in links if hop_of.get(_u, 9) == 0)
            print("\nРАССТОЯНИЕ ДО ССЫЛКИ записано в %s: шаг 0 (строки самой "
                  "записи) — %d из %d. Разбор начинай с них: дальние шаги "
                  "тянут посты СОСЕДНИХ тем, перечисленных в связях."
                  % (_hp, _near, len(links)))
        except OSError:
            pass

    # ЗАКРЕПЛЕНИЕ: чужое не берём, своё помечаем.
    cl = claims_load()
    # СНАПШОТ В ОБЩУЮ КУЧУ НЕ ВЛИВАЕТСЯ (01.11, прямое слово пользователя,
    # через час после того как я это влил: «не притяни из другой темы, в эту
    # тему это должно касаться только этих источников»). Снапшот списка — это
    # материал ВСЕХ тем дня, и автоматическое слияние его с `links_topic`
    # давало ровно то перекрёстное раскидывание, которое запрещено 31.10.
    # Поэтому он лежит ОТДЕЛЬНЫМ файлом, в работу сам не идёт, и берётся из
    # него только то, что вкладка явно опознала как свою тему.
    if snap:
        _sp = "links_snapshot.txt"
        with open(_sp, "w", encoding="utf-8") as _f:
            for _u in snap:
                _f.write(_u + "\n")
        print("\n!! СНАПШОТ СПИСКА: %d ссылок → %s. ЭТО МАТЕРИАЛ ВСЕХ ТЕМ "
              "ДНЯ, а не твоей записи." % (len(snap), _sp), file=sys.stderr)
        print("   В работу он сам НЕ идёт. Бери оттуда ссылку ТОЛЬКО если "
              "пост дословно про твой сюжет; всё остальное — чужой ролик.",
              file=sys.stderr)
    # ССЫЛКА, НАЗВАННАЯ САМОЙ ЗАПИСЬЮ, ЧУЖИМ ЗАКРЕПЛЕНИЕМ НЕ ОТБИВАЕТСЯ
    # (04.11, улов `usuario-31`). Живой случай: запись 230 прямо перечисляет
    # пост источником №5, а он закреплён за вчерашним роликом другой темы —
    # и гейт объявлял своё чужим. Закрепление придумано против
    # ПЕРЕКРЁСТНОГО растаскивания материала по темам, а не против того,
    # чтобы запись пользовалась СВОИМИ источниками. Поэтому отбиваем только
    # найденное ПО ТЕМЕ (`topic`), а найденное ПО ИДЕНТИФИКАТОРАМ записи
    # (`links`) оставляем и честно говорим, что оно ещё у кого-то.
    taken = {u: cl[u] for u in list(topic)
             if u in cl and cl[u].get("проект") != project}
    for u in taken:
        topic.pop(u, None)
    shared = {u: cl[u] for u in list(links)
              if u in cl and cl[u].get("проект") != project}
    if shared:
        print("\nССЫЛКИ ЗАПИСИ, КОТОРЫЕ УЖЕ БРАЛ ДРУГОЙ РОЛИК — %d; БЕРУ, "
              "потому что их называет ТВОЯ запись:" % len(shared))
        for u, v in list(shared.items())[:10]:
            print("  %s → раньше %s (ключ %s)"
                  % (u, v.get("проект"), v.get("ключ")))
        print("  ОБЯЗАТЕЛЬНО сверь md5 скачанного с кадрами того ролика: "
              "совпавший кадр выбрось, иначе он уедет в два видео.")
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

    # ПОЛНЫЙ ОТБОЙ ПО ЗАКРЕПЛЕНИЮ — ОТДАЁМ ГОТОВЫЙ СПИСОК (03.11, улов
    # `usuario-37`). Ролик-V2 той же темы отбивается ЦЕЛИКОМ: все 10 ссылок
    # закреплены за вчерашней версией того же пакета, `links.txt` выходит
    # пустым, код 1 — и вкладка обязана собирать адреса ГЛАЗАМИ из печати, по
    # одному. Печать режется на 15 строках, то есть часть ссылок теряется
    # молча. Поэтому при полном отбое кладём их в файл и печатаем готовую
    # команду: решение «брать или не брать» остаётся за вкладкой, но собирать
    # руками больше нечего.
    # ОТБИТОЕ ВЫКЛАДЫВАЕМ ВСЕГДА, А НЕ ТОЛЬКО ПРИ ПОЛНОМ ОТБОЕ (04.11, улов
    # `usuario-eb` на «Калининграде»). Ветка 03.11 срабатывала лишь когда
    # своих ссылок НЕ осталось вовсе. Живой случай: 6 ссылок из 7 закреплены
    # за вчерашним роликом той же темы на ДРУГОМ канале, седьмая свободна, но
    # вложений у неё нет — то есть материала ноль, а файла со списком нет,
    # потому что формально «ссылка есть». Печать режется на 15 строках, и
    # остальное теряется молча. Теперь список лежит файлом при ЛЮБОМ отборе:
    # решение «вторая серия это или чужая тема» как и было за вкладкой.
    claimed_out = ""
    if taken:
        c_out = os.path.join(os.path.dirname(os.path.abspath(out)),
                             "links_claimed.txt")
        claimed_out = c_out
        with open(c_out, "w", encoding="utf-8") as f:
            for u in taken:
                f.write(u + "\n")
        _owners = sorted({(v.get("проект") or "?") for v in taken.values()})
        if links or topic:
            print("\nОТБИТО %d ИЗ %d, отбитые лежат целиком в %s"
                  % (len(taken), len(taken) + len(links) + len(topic), c_out))
        else:
            print("\nОТБИТО ВСЁ (%d ссылок), ОНИ ЛЕЖАТ ЦЕЛИКОМ В %s"
                  % (len(taken), c_out))
        print("   прежние владельцы: %s" % ", ".join(_owners))
        print("   Если твой ключ — ВТОРАЯ ВЕРСИЯ той же темы (пакет V2, "
              "второй канал), это ТВОЙ материал: прогоняй")
        print("     python3 tg_media.py --json tg.json $(cat %s)" % c_out)
        print("   и ОБЯЗАТЕЛЬНО сверяй md5 скачанного с кадрами прежнего "
              "ролика — совпавший кадр выбрасывай, иначе зритель увидит")
        print("   один и тот же кадр в двух роликах:")
        print("     md5sum <папка прежнего ролика>/assets/* | sort > /tmp/old.md5")
        print("   Если тема ЧУЖАЯ — ничего не бери, это материал другого ролика.")

    if not links and not topic and not taken:
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
    # КОД ВОЗВРАТА ЧЕСТНЫЙ, А НЕ «ПУСТ ЛИ links.txt» (03.11, улов `usuario-0d`).
    # Ветка полного отбоя по закреплению (добавлена в то же утро) кладёт все
    # ссылки в `links_claimed.txt` и печатает готовую команду — то есть
    # материал ЕСТЬ и работа продолжается, — а код оставался 1. Под `set -e`
    # это встаёт как отказ ровно там, где прогон успешен. Класс тот же, что
    # «успех джоба при пустой матрице»: код говорил не о том, что произошло.
    # 1 остаётся только когда НЕ НАЙДЕНО НИЧЕГО.
    if claimed_out and not (links or topic):
        print("код возврата 0: ссылки есть, они в %s (решение «брать или "
              "нет» за тобой)" % os.path.basename(claimed_out))
        return 0
    if not (links or topic):
        print("код возврата 1: не найдено НИ ОДНОЙ ссылки", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
