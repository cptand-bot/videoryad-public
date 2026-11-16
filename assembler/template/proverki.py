# -*- coding: utf-8 -*-
"""КАКИЕ ПРОВЕРКИ ЛОВЯТ БРАК, А КАКИЕ ТОЛЬКО ТОРМОЗЯТ (16.11.2026).

ЗАЧЕМ. Его вопрос двух месяцев: «все улучшения идут в жопу и возвращается
на тот же круг, значит, что-то не так». Счёт по нашим же журналам: 357
правок, и почти каждая ДОБАВЛЯЕТ шаг — новую дверь, новое сито, новый
обязательный вид. Ни одна не убирает. Отсюда и рост времени сборки: каждое
сработавшее сито — круг правок, а каждое правило вкладка перечитывает
сотни раз за смену.

ЕГО РЕШЕНИЕ 16.11, вечер, после объяснения: **проверка, которая за неделю
не отбила ни одного брака, снимается.** Ловит — остаётся, не ловит — уходит.
Правило «новая проверка обязана снимать старую» он НЕ принял, и правильно:
под него пришлось бы выбрасывать нужные сита ради счёта.

КАК УСТРОЕНО. Проверки сами отмечаются здесь в момент срабатывания —
строкой в `base/proverki.tsv` (только дописывается):

    дата-время · класс · имя проверки · проект

Класс: `mine` — мина линта запросов, `gate` — гейт (приёмка, selfcheck),
`door` — отказ двери карточки. Полный список мин линта берётся из самого
`query_lint` (реестр `MINES`), поэтому про них видно и обратное — какая НЕ
сработала ни разу.

ОТЧЁТ:
    python3 template/proverki.py --dni 7          # кто ловил, кто молчал
    python3 template/proverki.py --dni 7 --snyat   # только кандидаты на снятие

ЧЕГО ЗДЕСЬ НЕТ. Числа срабатываний НЕ значат «проверка хорошая»: мина,
которая бьёт по каждому второму запросу, может быть просто грубой. Поэтому
отчёт печатает И самых частых — их стоит смотреть глазами, не снимать
автоматом. Решение о снятии принимает координатор, инструмент только
считает.
"""

import argparse
import datetime as _dt
import io
import os
import sys

СКИЛЛ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ЖУРНАЛ = os.path.join(СКИЛЛ, "base", "proverki.tsv")

КЛАССЫ = ("mine", "gate", "door")


def otmetit(klass, imya, proekt=""):
    """Отметить срабатывание проверки. Молча, без исключений наружу.

    Зовётся из боевого кода в момент отказа, поэтому не имеет права ни
    упасть, ни замедлить прогон: открыли, дописали строку, закрыли.
    """
    try:
        k = str(klass or "").strip().lower()
        n = " ".join(str(imya or "").split())[:160]
        if not n or k not in КЛАССЫ:
            return
        p = os.path.basename(str(proekt or "").rstrip("/"))[:80]
        os.makedirs(os.path.dirname(ЖУРНАЛ), exist_ok=True)
        with io.open(ЖУРНАЛ, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\t%s\n"
                    % (_dt.datetime.now().strftime("%Y-%m-%d %H:%M"), k, n, p))
    except Exception:
        pass


def _zapisi(dni):
    порог = _dt.datetime.now() - _dt.timedelta(days=max(1, int(dni)))
    out = []
    if not os.path.isfile(ЖУРНАЛ):
        return out
    with io.open(ЖУРНАЛ, encoding="utf-8") as f:
        for стр in f:
            части = стр.rstrip("\n").split("\t")
            if len(части) < 3:
                continue
            try:
                когда = _dt.datetime.strptime(части[0], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if когда >= порог:
                out.append((когда, части[1], части[2],
                            части[3] if len(части) > 3 else ""))
    return out


def _vse_miny():
    """Полный список мин линта — чтобы видеть МОЛЧАВШИЕ, а не только частые."""
    try:
        import importlib.util
        сп = importlib.util.spec_from_file_location(
            "query_lint", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "query_lint.py"))
        м = importlib.util.module_from_spec(сп)
        сп.loader.exec_module(м)
        слова = []
        for item in list(getattr(м, "MINES", [])):
            try:
                w = str(item[0]).strip()
            except (TypeError, IndexError):
                continue
            if w and w not in слова:
                слова.append(w)
        return слова
    except Exception:
        return []


def otchet(dni=7, tolko_snyat=False):
    зап = _zapisi(dni)
    счёт = {}
    for _, k, n, _p in зап:
        счёт[(k, n)] = счёт.get((k, n), 0) + 1

    print("ПРОВЕРКИ ЗА %d дн.: срабатываний %d, разных проверок %d"
          % (dni, len(зап), len(счёт)))
    if not зап and not os.path.isfile(ЖУРНАЛ):
        print("журнала ещё нет — он заполнится, как только проверки начнут "
              "срабатывать (пишут сами)")

    мины_все = _vse_miny()
    молчали = [w for w in мины_все if ("mine", w) not in счёт]
    if not tolko_snyat:
        часто = sorted(счёт.items(), key=lambda kv: -kv[1])[:15]
        if часто:
            print("\nЛОВИЛИ ЧАЩЕ ВСЕГО (смотреть глазами: частая мина бывает "
                  "просто грубой):")
            for (k, n), c in часто:
                print("  %-5s %-70s %d" % (k, n[:70], c))

    if мины_все:
        print("\nМОЛЧАЛИ %d мин из %d — КАНДИДАТЫ НА СНЯТИЕ (его правило "
              "16.11: не ловит — уходит):" % (len(молчали), len(мины_все)))
        for w in молчали[:60]:
            print("   · %s" % w)
        if len(молчали) > 60:
            print("   … и ещё %d" % (len(молчали) - 60))
        print("\nСнимать не автоматом: мина могла молчать потому, что агент "
              "уже знает правило (список мин уезжает ему в задание). Смотреть "
              "так: молчит НЕДЕЛЮ и в журнале правок нет свежего повода — "
              "снимать.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="что ловят наши проверки")
    ap.add_argument("--dni", type=int, default=7)
    ap.add_argument("--snyat", action="store_true",
                    help="только кандидаты на снятие")
    ap.add_argument("--otmetit", nargs=2, metavar=("КЛАСС", "ИМЯ"),
                    help="отметить срабатывание руками (для проб)")
    a = ap.parse_args()
    if a.otmetit:
        otmetit(a.otmetit[0], a.otmetit[1])
        print("отмечено")
        return 0
    return otchet(a.dni, a.snyat)


if __name__ == "__main__":
    sys.exit(main())
