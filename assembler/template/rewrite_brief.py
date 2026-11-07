#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЗАДАНИЕ НА РЕРАЙТ ТЕМЫ ПОД ВТОРОЙ КАНАЛ (07.11.2026).

    python3 rewrite_brief.py <папка темы> --key PROD_… --channel "ПЛАНЕТА" \
            [--out <куда положить задание>]

ЗАЧЕМ. Пользователь ведёт каналы-клоны: та же тема, та же подача, другой
канал. Ценность текста не в фактах — факты везде одни, — а в АВТОРСКИХ
МЫСЛЯХ, юморе и иронии, которые он надиктовывает в ChatGPT и которые
георадар хранит отдельно. Рерайт обязан пережить эти мысли и при этом не
совпадать с оригиналом словами.

ОТКУДА БЕРЁМ ПРАВИЛА — НЕ ПРИДУМЫВАЕМ СВОИХ. В георадаре уже лежит всё:
  · `EditorialRules`   — 45 правил редактуры с приоритетами CRITICAL/HIGH,
    среди них «Защита авторских мыслей», «Затирание остроты»,
    «Уникальность между каналами» и «Фильтр TTS и CTA»;
  · `AuthorNotes`      — его собственные формулировки и гипотезы;
  · `AuthorReasoning`  — рассуждения: что он увидел, какую связь провёл,
    какой выбор сделал и почему;
  · `Productions`      — заголовок, канал, угол подачи, сюжетная линия.

В ГЕОРАДАР НИЧЕГО НЕ ПИШЕМ (его прямой запрет): читаем и кладём задание
рядом с текстом темы.
"""
import argparse
import glob
import os
import re
import sys


def read_text(path):
    """Прочитать текст В ЛЮБОЙ ИЗ НАШИХ КОДИРОВОК.

    МИНА, ПОЙМАННАЯ 07.11.2026 ДО ПЕРВОГО БОЕВОГО ПРОГОНА: все тексты
    озвучки пользователя лежат в Windows-1251 (их пишет его цепочка в
    ChatGPT, кодировка прямо указана в записи георадара). Чтение как
    utf-8 с errors="replace" НЕ ПАДАЕТ — оно молча превращает весь русский
    текст в символы замены. Проверка при этом бодро печатает «текст 13333
    знака, цифр нет», а в сервис озвучки уехал бы мусор.
    Поэтому кодировка подбирается, а не предполагается.
    """
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", "replace")


GEO_DIR = os.environ.get("GEORADAR_DIR", "/mnt/d/_ГЕОРАДАР-КОПИЯ")


def latest_geo():
    files = sorted(glob.glob(os.path.join(GEO_DIR, "*.xlsx")),
                   key=os.path.getmtime, reverse=True)
    if not files:
        sys.exit("нет копии георадара в %s — положи свежий xlsx" % GEO_DIR)
    return files[0]


def sheet_rows(wb, name):
    """Лист как список словарей. Пустые строки отбрасываются."""
    if name not in wb.sheetnames:
        return []
    ws = wb[name]
    rows = ws.iter_rows(values_only=True)
    try:
        hdr = [str(h) if h is not None else "" for h in next(rows)]
    except StopIteration:
        return []
    out = []
    for r in rows:
        if not any(v not in (None, "") for v in r):
            continue
        out.append({hdr[i]: r[i] for i in range(min(len(hdr), len(r)))})
    return out


def txt(v):
    return "" if v is None else str(v).strip()


def find_text(folder):
    """Текст озвучки темы — самый большой содержательный .txt."""
    skip = ("ЗАДАНИЕ", "БРИФ", "ОТВЕТ", "ПРОМПТ", "РЕРАЙТ", "ДОСЬЕ", "АУДИТ")
    cands = [os.path.join(folder, n) for n in os.listdir(folder)
             if n.lower().endswith(".txt")
             and not any(s in n.upper() for s in skip)]
    if not cands:
        sys.exit("в папке нет текста темы: %s" % folder)
    return max(cands, key=os.path.getsize)


def pick_author_material(wb, prod):
    """Авторские мысли, относящиеся к теме.

    Связь ищется по сюжетной линии и сущностям, а не по названию: рабочее
    имя темы в георадаре своё (правило всего сборщика). Если прямой связи
    нет — отдаём записи близкой даты и ЧЕСТНО помечаем это, чтобы писатель
    не принял чужую мысль за авторскую по этой теме.
    """
    storyline = txt(prod.get("main_storyline_id"))
    key = txt(prod.get("production_id"))
    notes, reasoning, weak = [], [], False

    for n in sheet_rows(wb, "AuthorNotes"):
        hay = " ".join(txt(n.get(k)) for k in
                       ("storylines_detected", "entities_detected", "notes",
                        "archive_record_key"))
        if storyline and storyline in hay:
            notes.append(n)
    for r in sheet_rows(wb, "AuthorReasoning"):
        hay = " ".join(txt(r.get(k)) for k in
                       ("related_geo2_ids", "article_or_topic", "notes"))
        if (storyline and storyline in hay) or (key and key in hay):
            reasoning.append(r)

    if not notes and not reasoning:
        weak = True
        day = txt(prod.get("created_at"))[:10]
        for n in sheet_rows(wb, "AuthorNotes"):
            if day and txt(n.get("authored_at"))[:10] == day:
                notes.append(n)
        for r in sheet_rows(wb, "AuthorReasoning"):
            if day and txt(r.get("captured_at"))[:10] == day:
                reasoning.append(r)
    return notes, reasoning, weak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="папка темы оригинала")
    ap.add_argument("--key", required=True, help="production_id в георадаре")
    ap.add_argument("--channel", required=True, help="канал-получатель рерайта")
    ap.add_argument("--out", help="куда положить задание (по умолчанию в папку темы)")
    ap.add_argument("--audit", metavar="РЕРАЙТ.txt",
                    help="собрать задание не писателю, а АУДИТОРУ: проверить "
                         "готовый рерайт по форме листа RetentionAudits")
    args = ap.parse_args()

    try:
        import openpyxl
    except ImportError:
        sys.exit("нет openpyxl")

    src = find_text(args.folder)
    text = read_text(src).strip()

    path = latest_geo()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    # Ключ бывает трёх видов, и живут они на РАЗНЫХ листах (правило скилла):
    #   PROD_… — запись в `Productions`;
    #   ARM_…  — авторский master в `AuthorReasoning`;
    #   AN_…   — заметка в `AuthorNotes`.
    # Искать только в Productions нельзя: 07.11 два ключа дня из трёх были
    # ARM_, и инструмент честно отвечал «записи нет» на живой записи.
    prods = [p for p in sheet_rows(wb, "Productions")
             if txt(p.get("production_id")) == args.key]
    if prods:
        prod = prods[0]
    else:
        prod = None
        for r in sheet_rows(wb, "AuthorReasoning"):
            if txt(r.get("reasoning_id")) == args.key:
                prod = {"production_id": args.key,
                        "title": txt(r.get("article_or_topic")),
                        "channel": "", "created_at": txt(r.get("captured_at")),
                        "main_storyline_id": txt(r.get("related_geo2_ids")),
                        "angle": txt(r.get("editorial_choice"))}
                break
        if prod is None:
            for n in sheet_rows(wb, "AuthorNotes"):
                if txt(n.get("author_note_id")) == args.key:
                    prod = {"production_id": args.key,
                            "title": txt(n.get("machine_interpretation"))[:120],
                            "channel": "", "created_at": txt(n.get("authored_at")),
                            "main_storyline_id": txt(n.get("storylines_detected")),
                            "angle": ""}
                    break
    if prod is None:
        sys.exit("записи %s в георадаре нет (копия %s). Работать дальше можно, "
                 "но без авторских мыслей — скажи об этом вслух."
                 % (args.key, os.path.basename(path)))

    # Сам master-ключ — это и есть авторская мысль верхнего уровня; при
    # поиске по сюжетной линии он не всегда попадает в выборку, поэтому
    # добавляем его явно.
    # Сам master плюс те записи, на которые он ССЫЛАЕТСЯ. У каждой темы
    # 07.11 master сборки видео (…_VIDEO_ASSEMBLY_…) отдельно, а смысловой
    # master статьи (…_AUDIT_MASTER_…) — отдельной записью, и именно там
    # лежит авторская гипотеза. Без перехода по `related_geo2_ids` рерайт
    # получил бы правила медиа вместо мыслей автора.
    _self = []
    _want = {args.key}
    if args.key.startswith("ARM_"):
        rows = sheet_rows(wb, "AuthorReasoning")
        for r in rows:
            if txt(r.get("reasoning_id")) == args.key:
                _self.append(r)
                for part in re.split(r"[;,\s]+", txt(r.get("related_geo2_ids"))):
                    if part.startswith("ARM_"):
                        _want.add(part)
        for r in rows:
            if txt(r.get("reasoning_id")) in _want and r not in _self:
                _self.append(r)

    rules = [r for r in sheet_rows(wb, "EditorialRules")
             if txt(r.get("priority")).upper() in ("CRITICAL", "HIGH")
             and txt(r.get("status")).lower() not in ("off", "disabled", "archived")]
    notes, reasoning, weak = pick_author_material(wb, prod)
    for r in _self:
        if r not in reasoning:
            reasoning.insert(0, r)
            weak = False

    # ── режим аудитора ────────────────────────────────────────────────
    # Аудитор ВСЕГДА другой агент, не тот, что писал: писатель свой текст
    # одобряет всегда. Форма вердикта взята из георадара как есть (лист
    # `RetentionAudits`: шесть осей, список проблем, решение), чтобы
    # отчёт ложился в его привычный вид.
    if args.audit:
        new = read_text(args.audit)
        out = args.out or os.path.join(args.folder, "ЗАДАНИЕ-АУДИТ.txt")
        A = []
        A.append("ЗАДАНИЕ: ПРОВЕРИТЬ РЕРАЙТ")
        A.append("=" * 70)
        A.append("Запись георадара: %s — «%s»" % (args.key, txt(prod.get("title"))))
        A.append("Канал рерайта: %s" % args.channel)
        A.append("")
        A.append("ЧТО ПРОВЕРИТЬ — ШЕСТЬ ОСЕЙ (форма листа RetentionAudits)")
        A.append("-" * 70)
        A.append("1. author_intent — на месте ли АВТОРСКИЕ МЫСЛИ (список ниже).")
        A.append("   Выпавшая мысль — это CRITICAL, а не замечание.")
        A.append("2. sharpness — не затёрта ли острота: оговорки вида «нет")
        A.append("   доказательств», «официально не подтверждено», смягчённые")
        A.append("   формулировки там, где оригинал говорил прямо.")
        A.append("3. uniqueness — не пересказ ли это оригинала теми же словами.")
        A.append("4. retention — держит ли текст внимание: начало, повороты.")
        A.append("5. cta — два призыва подписаться, на своих местах.")
        A.append("6. tts — числа прописью, тире отсутствуют, нет латиницы,")
        A.append("   которую голос прочтёт по буквам.")
        A.append("")
        A.append("ЮМОР И ИРОНИЯ — ОТДЕЛЬНО. Это главная ценность текста.")
        A.append("Если шутка оригинала исчезла или стала пресной — назови её.")
        A.append("")
        A.append("АВТОРСКИЕ МЫСЛИ, КОТОРЫЕ ОБЯЗАНЫ БЫТЬ В ТЕКСТЕ")
        A.append("-" * 70)
        if not notes and not reasoning:
            A.append("(в георадаре по этой записи их нет)")
        for n in notes[:12]:
            t = txt(n.get("original_text"))
            if t:
                A.append("· %s" % t[:400])
        for r in reasoning[:12]:
            a = txt(r.get("author_original")) or txt(r.get("author_hypothesis"))
            if a:
                A.append("· %s" % a[:400])
        A.append("")
        A.append("ФОРМАТ ОТВЕТА — строго такой, без лишних слов:")
        A.append("-" * 70)
        A.append("ОЦЕНКИ: retention=N author_intent=N uniqueness=N sharpness=N "
                 "cta=N tts=N   (N от одного до пяти)")
        A.append("ПРОБЛЕМЫ: по одной в строке, формат")
        A.append("  [CRITICAL|HIGH|MEDIUM] место в тексте :: БЫЛО → СТАЛО")
        A.append("  (правило георадара: только закрытые точечные команды —")
        A.append("   точная цитата и готовая замена, без общих советов)")
        A.append("РЕШЕНИЕ: принять | принять с правками | переписать заново")
        A.append("")
        A.append("ОРИГИНАЛ")
        A.append("-" * 70)
        A.append(text)
        A.append("")
        A.append("РЕРАЙТ НА ПРОВЕРКУ")
        A.append("-" * 70)
        A.append(new)
        open(out, "w", encoding="utf-8").write("\n".join(A))
        print("задание аудитору: %s" % out)
        print("авторских мыслей на контроле: %d" % (len(notes) + len(reasoning)))
        return

    out = args.out or os.path.join(args.folder, "ЗАДАНИЕ-РЕРАЙТ.txt")
    L = []
    L.append("ЗАДАНИЕ: ПЕРЕПИСАТЬ ТЕКСТ ПОД ДРУГОЙ КАНАЛ")
    L.append("=" * 70)
    L.append("Канал-получатель: %s" % args.channel)
    L.append("Запись георадара: %s — «%s»" % (args.key, txt(prod.get("title"))))
    if txt(prod.get("angle")):
        L.append("Угол подачи: %s" % txt(prod.get("angle")))
    L.append("")
    L.append("ЧТО ТРЕБУЕТСЯ")
    L.append("-" * 70)
    L.append("Тот же сюжет, та же подача, ДРУГИЕ СЛОВА. Это канал-клон:")
    L.append("новых углов, новых фактов и новых выводов НЕ добавлять.")
    # Длину требовать ДИАПАЗОНОМ В ЗНАКАХ, а не словом «столько же»: два
    # рерайта из двух 07.11 пришли на 14% и 23% длиннее оригинала, и оба
    # пришлось гонять на сокращение отдельным заходом.
    # ДЛИННЕЕ ОРИГИНАЛА — ЗАПРЕЩЕНО (07.11, его слово по сданному рерайту:
    # «очень нудноватый и растянут, очень много. Не надо его растягивать на
    # такую пропорцию. Он должен быть в пределах пяти-десяти процентов.
    # Даже если будет примерно совпадать — фиг с ним. Это нудота, я убью
    # канал тем самым»).
    # Три рерайта из трёх приходили на 14-23% длиннее и после круга
    # сокращения садились на 109-110% — то есть на верхней границе. Нудность
    # берётся именно оттуда: писатель добавляет подводки и повторы, чтобы
    # добрать объём. Поэтому цель теперь НЕ «столько же», а «не длиннее».
    # КОРИДОР 95-105%, ЕГО ЧИСЛА (07.11, уточнение в тот же день):
    # «не-не, 95 ставь. 95 нижний порог. И 105. 95 и 105. Вот так вот».
    L.append("ДЛИНА: от %d до %d знаков (у оригинала %d). Это коридор "
             "95-105%%, выход за него в любую сторону — брак."
             % (int(len(text) * 0.95), int(len(text) * 1.05), len(text)))
    L.append("Короче оригинала — хорошо. Длиннее — брак: зритель уходит от")
    L.append("растянутого текста, а подводки и повторы ради объёма делают")
    L.append("его нудным. Не добирай длину — добирай смысл.")
    L.append("Посчитай знаки готового текста перед ответом.")
    L.append("Числа писать ПРОПИСЬЮ с нужным падежом — текст идёт в озвучку,")
    L.append("цифрами сервис склоняет неверно.")
    L.append("Тире в тексте озвучки не ставить (правило фильтра TTS).")
    # ЮМОРА И САРКАЗМА — БОЛЬШЕ, ЧЕМ В ОРИГИНАЛЕ (07.11, его прямое слово:
    # «чтобы модель больше юмора туда вкладывала, больше юмора, чтобы она
    # была ещё более юмористичной. И саркастичный юмор, и сарказм»).
    # До этого в задании стояло «юмор обязан остаться» — то есть планка на
    # сохранение. Аудитор при этом трижды за день ловил обратное: рерайт
    # сглаживал шутки и менял хлёсткое слово на пресное. Планку поднимаем:
    # не сохранить, а ДОБАВИТЬ.
    L.append("")
    L.append("ЮМОР И САРКАЗМ — ГЛАВНОЕ ТРЕБОВАНИЕ К ЭТОМУ ТЕКСТУ")
    L.append("-" * 70)
    L.append("Юмор оригинала не просто сохранить — его должно стать БОЛЬШЕ.")
    L.append("Это канал с характером, а не сводка новостей: зритель остаётся")
    L.append("ради интонации, а не ради фактов, которые он уже слышал.")
    L.append("")
    L.append("Что работает:")
    L.append("· САРКАЗМ по поводу происходящего — сухая издёвка, а не")
    L.append("  клоунада: «ещё немного, и возле него поставят чиновника,")
    L.append("  который будет мягко придерживать его за локоть»;")
    L.append("· БЫТОВОЕ СРАВНЕНИЕ там, где politics: встреча глав государств")
    L.append("  как семейный скандал, санкции как счёт в ресторане;")
    L.append("· НЕОЖИДАННЫЙ ПОВОРОТ В КОНЦЕ АБЗАЦА — фраза, которой зритель")
    L.append("  не ждал после предыдущей;")
    L.append("· ПРЯМОЕ ОБРАЩЕНИЕ на «вы» и просторечие, где оно к месту.")
    L.append("")
    L.append("Чего делать НЕЛЬЗЯ: смягчать оценки, уводить резкое в")
    L.append("безличное («ситуация складывается» вместо «они доигрались»),")
    L.append("заменять хлёсткое слово нейтральным. Это главный брак рерайта:")
    L.append("текст становится гладким и мёртвым.")
    L.append("")
    L.append("Шутки оригинала — нижняя планка, а не образец. Своих добавь.")
    L.append("")
    L.append("АВТОРСКИЕ МЫСЛИ — ОБЯЗАНЫ ПЕРЕЖИТЬ ПЕРЕПИСЫВАНИЕ")
    L.append("-" * 70)
    if weak:
        L.append("(ВНИМАНИЕ: прямой связи с этой записью не нашлось, ниже —")
        L.append(" заметки той же даты. Бери только то, что реально о теме.)")
    if not notes and not reasoning:
        L.append("Авторских записей по теме в георадаре нет.")
    for n in notes[:12]:
        t = txt(n.get("original_text"))
        if t:
            L.append("· [%s] %s" % (txt(n.get("note_type")) or "note", t[:400]))
    for r in reasoning[:12]:
        a = txt(r.get("author_original")) or txt(r.get("author_hypothesis"))
        if a:
            L.append("· [мысль] %s" % a[:400])
        if txt(r.get("editorial_choice")):
            L.append("    выбор редакции: %s" % txt(r.get("editorial_choice"))[:250])
    L.append("")
    L.append("ПРАВИЛА РЕДАКТУРЫ ИЗ ГЕОРАДАРА (лист EditorialRules)")
    L.append("-" * 70)
    for r in rules:
        L.append("· [%s] %s" % (txt(r.get("priority")), txt(r.get("rule_name"))))
        if txt(r.get("required_check")):
            L.append("    проверка: %s" % txt(r.get("required_check"))[:300])
        if txt(r.get("action")):
            L.append("    действие: %s" % txt(r.get("action"))[:300])
    L.append("")
    L.append("ОРИГИНАЛЬНЫЙ ТЕКСТ")
    L.append("-" * 70)
    L.append(text)
    L.append("")
    L.append("ФОРМАТ ОТВЕТА: только готовый текст, без пояснений и заголовков")
    L.append("служебных блоков. На диск ничего не писать.")

    open(out, "w", encoding="utf-8").write("\n".join(L))
    print("задание: %s" % out)
    print("правил: %d · авторских заметок: %d · рассуждений: %d%s"
          % (len(rules), len(notes), len(reasoning),
             "  (связь по дате, слабая)" if weak else ""))
    print("оригинал: %d знаков" % len(text))


if __name__ == "__main__":
    main()
