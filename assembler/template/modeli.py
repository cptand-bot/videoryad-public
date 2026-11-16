# -*- coding: utf-8 -*-
"""НА КАКИХ МОДЕЛЯХ МЫ РАБОТАЕМ — ОДНОЙ СТРОКОЙ, ПО ФАКТУ (16.11.2026).

Его требование 16.11, дословно: «мне такая хрень не нужна, я должен 100%,
150% быть уверенным в том, что работают дешёвые модели. А не „я найду, если
увижу“… Жёстко зашить». То есть ответ «работает или нет» обязан давать КОД,
а не глаз координатора и не его подсчёты в аккаунте.

ЧТО СЧИТАЕТ. Транскрипты сессий (`~/.claude/projects/<проект>/*.jsonl`) несут
у каждого запроса модель и расход: `message.model`, `message.usage` с полями
`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`,
`output_tokens`. Инструмент складывает их по дням и моделям и печатает долю
ДОРОГОЙ модели в общем объёме.

ПОЧЕМУ СЧИТАЕМ ПОДАЧУ, А НЕ ОТВЕТЫ. Замер 14-16.11: подача контекста
568 / 508 / 143 млн токенов в день против 0,61 / 0,73 / 0,48 млн на ответы.
Девяносто девять процентов расхода — это повторная подача той же переписки,
поэтому доля модели считается по ПОДАЧЕ (вход + кэш), а выход печатается
отдельно, для полноты.

КАК ЧИТАТЬ ВЫВОД. «дорогих 100%» — всё идёт на Opus, перевод не работает.
«дорогих 15-25%» — на сильной модели остался координатор, остальное на
Sonnet и Haiku, то есть работает. Цифра «на ролик» сравнима день к дню:
при шести роликах в день было ~90 млн на ролик на Opus.

    python3 template/modeli.py              # за 3 дня
    python3 template/modeli.py --dni 7
    python3 template/modeli.py --kratko     # ровно одна строка (для смены)
"""

import argparse
import collections
import datetime as _dt
import glob
import json
import os
import sys

ПРОЕКТЫ = os.path.expanduser("~/.claude/projects")

# Цена подачи относительно Opus (кэш-чтение, прайс ноября 2026):
# Opus 1,5 $/М · Sonnet 0,3 $/М · Haiku 0,08 $/М. Нужна не точность счёта в
# деньгах, а ответ «дорогая модель или дешёвая».
ДОРОГИЕ = ("opus",)
ВЕС = (("opus", 1.0), ("sonnet", 0.2), ("haiku", 0.05))


def _вес(модель):
    м = str(модель or "").lower()
    for ключ, в in ВЕС:
        if ключ in м:
            return в
    return 1.0          # неизвестную модель считаем дорогой, чтобы не обмануться


def _дорогая(модель):
    м = str(модель or "").lower()
    return any(к in м for к in ДОРОГИЕ)


def собрать(dni=3):
    порог = (_dt.datetime.now() - _dt.timedelta(days=max(1, int(dni)))).strftime("%Y-%m-%d")
    по_дням = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for файл in glob.glob(os.path.join(ПРОЕКТЫ, "*", "*.jsonl")):
        try:
            with open(файл, encoding="utf-8") as fh:
                for стр in fh:
                    if '"usage"' not in стр:
                        continue
                    try:
                        z = json.loads(стр)
                    except Exception:
                        continue
                    m = z.get("message") or {}
                    u = m.get("usage") or {}
                    if not u:
                        continue
                    день = str(z.get("timestamp") or "")[:10]
                    if not день or день < порог:
                        continue
                    мод = str(m.get("model") or "?")
                    c = по_дням[день][мод]
                    c["подача"] += (int(u.get("input_tokens") or 0)
                                    + int(u.get("cache_creation_input_tokens") or 0)
                                    + int(u.get("cache_read_input_tokens") or 0))
                    c["выход"] += int(u.get("output_tokens") or 0)
                    c["запросов"] += 1
        except Exception:
            continue
    return по_дням


def _роликов(день):
    """Сколько роликов сдано в этот день — по реестру занятых тем."""
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "base", "zanyato.json")
        d = json.load(open(p, encoding="utf-8"))
        зап = d.get("записи") or d.get("zapisi") or []
        дд = _dt.datetime.strptime(день, "%Y-%m-%d").strftime("%d-%m")
        n = 0
        for z in зап:
            if str(z.get("статус") or "") in ("сдано", "сдан") and дд in str(z.get("день") or ""):
                n += 1
        return n
    except Exception:
        return 0


def печать(dni=3, kratko=False):
    по_дням = собрать(dni)
    if not по_дням:
        print("транскриптов за этот срок нет — считать нечего")
        return 1
    строки = []
    for день in sorted(по_дням):
        모 = по_дням[день]
        подача = sum(c["подача"] for c in 모.values())
        выход = sum(c["выход"] for c in 모.values())
        дорого = sum(c["подача"] for м, c in 모.items() if _дорогая(м))
        взвеш = sum(c["подача"] * _вес(м) for м, c in 모.items())
        доля = 100.0 * дорого / max(1, подача)
        экономия = 100.0 * (1 - взвеш / max(1, подача))
        строки.append((день, подача, выход, доля, экономия, 모))

    if kratko:
        день, подача, выход, доля, экономия, _ = строки[-1]
        рол = _роликов(день)
        print("МОДЕЛИ %s: дорогая модель %.0f%% подачи (%.0f М из %.0f М)%s — %s"
              % (день, доля, доля * подача / 100 / 1e6, подача / 1e6,
                 " · %.0f М на ролик" % (подача / 1e6 / рол) if рол else "",
                 "ДЕШЁВЫЕ РАБОТАЮТ" if доля <= 40 else
                 "ДЕШЁВЫЕ НЕ РАБОТАЮТ: почти всё на дорогой"))
        return 0

    print("РАСХОД ПО МОДЕЛЯМ (считается ПОДАЧА контекста: 99%% расхода — она)")
    for день, подача, выход, доля, экономия, 모 in строки:
        рол = _роликов(день)
        print("\n%s · подача %.0f М · выход %.2f М%s"
              % (день, подача / 1e6, выход / 1e6,
                 " · роликов сдано %d → %.0f М на ролик" % (рол, подача / 1e6 / рол)
                 if рол else ""))
        for м in sorted(모, key=lambda x: -모[x]["подача"]):
            c = 모[м]
            print("   %-28s %6.0f М подачи · %5.2f М выход · %5d запросов%s"
                  % (м.split("-2026")[0], c["подача"] / 1e6, c["выход"] / 1e6,
                     c["запросов"], "   ДОРОГАЯ" if _дорогая(м) else ""))
        print("   ИТОГ: дорогая модель — %.0f%% подачи; экономия от дешёвых %.0f%% → %s"
              % (доля, экономия,
                 "РАБОТАЕТ" if доля <= 40 else "НЕ РАБОТАЕТ: почти всё на дорогой"))
    print("\nМерка день к дню — «М подачи на один сданный ролик». На Opus было "
          "~90 М (568 М / 6 роликов, 14.11). Переведённые вкладки обязаны "
          "дать ~20 М.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="на каких моделях мы работаем")
    ap.add_argument("--dni", type=int, default=3)
    ap.add_argument("--kratko", action="store_true", help="одна строка")
    a = ap.parse_args()
    return печать(a.dni, a.kratko)


if __name__ == "__main__":
    sys.exit(main())
