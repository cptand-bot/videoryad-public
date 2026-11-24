#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОПЫТ ИЗ ГЕОРАДАРА — ДОПОЛНИТЕЛЬНЫЙ БЛОК ДЛЯ УПАКОВКИ (24.11.2026).

ЗАЧЕМ. В таблице GeoRadar (GEO2_ARCHIVE_TEST) ChatGPT завёл 23.11 четыре
новых листа — GEO2_VideoLearning, GEO2_LearningPatterns, GEO2_PackageExamples,
GEO2_ClaudeInstructions — под постоянно пополняемую базу РЕАЛЬНЫХ результатов
собственных роликов (просмотры, CTR, заголовок, подтверждённая надпись).
Раньше `upakovka.py` эту базу не читал вовсе. Этот модуль — только чтение,
только добавочный блок к уже существующему промпту; ни один из старых
источников (`bank.txt`, `vybor.jsonl`, архивы, `svyazka.py`, `statistika.py`,
`avtorskoe.py`) не трогается и не заменяется.

ИСТОЧНИК — ТОЛЬКО ЛОКАЛЬНАЯ КОПИЯ НА D:. Скрипт запускается субпроцессом,
у него нет доступа к Google Sheets API/MCP — тот есть только у сессии Claude
Code. Поэтому берём ту же локальную копию `/mnt/d/_ГЕОРАДАР-КОПИЯ/*.xlsx`,
которую уже читают `geo_links.py` и другие инструменты видеоряда. Это и
обеспечивает работу «при следующих запусках Claude Code» без зависимости от
памяти текущего чата — файл лежит на диске независимо от сессии.

ПРОВЕРЕНО 24.11.2026: ежедневное обновление этой копии НЕ автоматизировано
кроном (в `crontab -l` нет задачи на неё) — её кладёт вручную вкладка,
работающая в моменте. Поэтому возраст копии всегда печатается в блоке
открыто, без утверждения «обновляется каждый день».

ЕСЛИ КОПИИ НЕТ / ОНА ПУСТАЯ / БИТАЯ — `блок()` возвращает "" или короткую
фразу-заглушку и НИКОГДА не бросает исключение: `upakovka.py` должен
продолжать работать точно как до этого модуля.
"""
import glob
import os
import time

GEO_DIR = os.environ.get("VIDEORYAD_GEO_DIR", "/mnt/d/_ГЕОРАДАР-КОПИЯ")

# Соответствие «папка канала» → как канал может быть обозначен в источнике
# georadar (пока там встречается только "Planet YouTube Studio").
АЛИАСЫ = {
    "ПЛАНЕТА": ("планета", "planet"),
    "5 МИНУТ": ("5 минут", "5 min", "5min"),
    "ОЛЬКА": ("олька",),
    "ОЛЬКА НОВОСТИ": ("олька",),
    "ДИПЛОМАТИЯ СИЛЫ": ("дипломати",),
    "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО": ("дипломати",),
}


def _свежая_копия():
    """Самый свежий .xlsx в папке копии георадара, или None."""
    try:
        files = glob.glob(os.path.join(GEO_DIR, "*.xlsx"))
    except OSError:
        return None
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _строки(ws):
    """Строки листа как список словарей по заголовку первой строки.
    Пустой/битый лист — пустой список, без исключения наружу."""
    try:
        it = ws.iter_rows(values_only=True)
        header = next(it)
    except StopIteration:
        return []
    if not header:
        return []
    header = [str(h or "").strip() for h in header]
    out = []
    for row in it:
        if not any(c is not None and str(c).strip() for c in row):
            continue
        out.append({header[i]: row[i] for i in range(len(header))
                    if i < len(row)})
    return out


def _похож_канал(источник, канал):
    if not канал:
        return True
    алиасы = АЛИАСЫ.get(канал.upper(), ())
    src = (str(источник or "")).lower()
    return any(a in src for a in алиасы) if алиасы else True


def блок(канал="", тема="", n=8):
    """Готовый текстовый блок для PROMPT.format(geo_opyt=...).
    Никогда не бросает исключение — любая проблема даёт короткую заглушку."""
    try:
        return _собрать(канал, тема, n)
    except Exception as e:
        return "(георадар: не удалось прочитать копию — %s)" % e


def _собрать(канал, тема, n):
    path = _свежая_копия()
    if not path:
        return ("(георадар: локальная копия не найдена в %s — работаем без "
                 "неё, как раньше)" % GEO_DIR)

    возраст_ч = (time.time() - os.path.getmtime(path)) / 3600.0
    снимок = time.strftime("%d.%m %H:%M", time.localtime(os.path.getmtime(path)))

    try:
        import openpyxl
    except ImportError:
        return "(георадар: модуль openpyxl недоступен — работаем без него)"

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        return "(георадар: копия %s не открылась — %s)" % (
            os.path.basename(path), e)

    куски = ["СНИМОК ГЕОРАДАРА: %s, %.1f ч назад (копия на D:, "
             "обновление НЕ по расписанию — вручную, когда вкладка положит "
             "свежую). ВЕСЬ ЭТОТ БЛОК — ТОЛЬКО ДЛЯ БЛОКА 2 (ЗАГОЛОВКИ И "
             "НАДПИСИ НА ПРЕВЬЮ). Для БЛОКА 1 (ОПИСАНИЕ) эти примеры, "
             "просмотры и формулировки НЕ использовать ни в каком виде —"
             " описание пишется только по тексту статьи."
             % (снимок, возраст_ч)]

    # ── GEO2_VideoLearning: реальные результаты по video_id ──────────
    видео_всего = 0
    if "GEO2_VideoLearning" in wb.sheetnames:
        строки = _строки(wb["GEO2_VideoLearning"])
        примеры = []
        for r in строки:
            views = r.get("views_total")
            ctr = r.get("ctr_percent")
            if not views and not ctr:
                continue                      # не реальный результат — пропуск
            if not _похож_канал(r.get("channel"), канал):
                continue
            видео_всего += 1
            надп = r.get("thumbnail_text") or "(надпись не подтверждена)"
            примеры.append(
                "video_id %s | канал %s | просмотры %s | CTR %s | "
                "заголовок «%s» | надпись: %s | статус: %s"
                % (r.get("video_id") or "?", r.get("channel") or "?",
                   views or "?", ctr or "?",
                   (r.get("title_full") or "")[:140], надп,
                   r.get("analysis_status") or "гипотеза"))
        if примеры:
            куски.append(
                "РЕАЛЬНЫЕ РЕЗУЛЬТАТЫ (GEO2_VideoLearning, не доказанная "
                "закономерность — просмотры причину не доказывают):\n· "
                + "\n· ".join(примеры[-n:]))

    # ── GEO2_PackageExamples: примеры готовых комплектов ─────────────
    if "GEO2_PackageExamples" in wb.sheetnames:
        строки = _строки(wb["GEO2_PackageExamples"])
        примеры = []
        for r in строки:
            views = r.get("views_total")
            if not views:
                continue
            if not _похож_канал(r.get("source"), канал):
                continue
            видео_всего += 1
            надп = r.get("thumbnail_text") or "(надпись не подтверждена)"
            примеры.append(
                "«%s» | просмотры %s | CTR %s | надпись: %s | %s"
                % ((r.get("title") or "")[:140], views,
                   r.get("ctr_percent") or "?", надп,
                   r.get("why_relevant") or ""))
        if примеры:
            куски.append(
                "ПРИМЕРЫ КОМПЛЕКТОВ (GEO2_PackageExamples, по CTR и "
                "просмотрам — наблюдение, не правило):\n· "
                + "\n· ".join(примеры[-n:]))

    # ── GEO2_LearningPatterns: закономерности, если накоплены ────────
    if "GEO2_LearningPatterns" in wb.sheetnames:
        строки = _строки(wb["GEO2_LearningPatterns"])
        паттерны = []
        for r in строки:
            if not r.get("pattern_name"):
                continue
            паттерны.append(
                "%s (%s, уверенность: %s): %s — %s"
                % (r.get("pattern_name"), r.get("type") or "?",
                   r.get("confidence") or "гипотеза",
                   r.get("performance_observation") or "",
                   r.get("usage_guidance") or ""))
        if паттерны:
            куски.append("ЗАКОНОМЕРНОСТИ (GEO2_LearningPatterns):\n· "
                         + "\n· ".join(паттерны[-n:]))

    # ── GEO2_ClaudeInstructions: живые правила из таблицы ────────────
    if "GEO2_ClaudeInstructions" in wb.sheetnames:
        строки = _строки(wb["GEO2_ClaudeInstructions"])
        правила = [r.get("instruction") for r in строки
                  if r.get("instruction")
                  and str(r.get("priority") or "").upper() in
                  ("CRITICAL", "HIGH")]
        if правила:
            куски.append("ПРАВИЛА ИЗ ГЕОРАДАРА (GEO2_ClaudeInstructions):\n· "
                         + "\n· ".join(правила))

    if видео_всего == 0:
        куски.append("(подтверждённых результатов с просмотрами/CTR "
                     "по этому каналу пока нет — база только завелась)")

    return "\n\n".join(куски)


if __name__ == "__main__":
    import sys
    канал = sys.argv[1] if len(sys.argv) > 1 else ""
    print(блок(канал))
