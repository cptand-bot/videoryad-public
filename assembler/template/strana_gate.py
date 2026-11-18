# -*- coding: utf-8 -*-
"""ГЕЙТ «НЕ ТА СТРАНА / НЕ ТОТ ЧЕЛОВЕК ПОСЛЕ СМЕНЫ СТРАТЕГИИ» (18.11.2026).

Точный корень, найденный координатором по живому ролику `5min-2-kiev-
prigovoren-1911`: сцену 1 (запрос «Виталий Ким…») в 10:34 переключили с
библиотеки на «поиск по персоне» — а дальше сито «не та страна/не тот
человек» (оно РЕАЛЬНО работает: в том же ролике поймало сцены 2/42/55)
эту сцену больше ни разу не проверило. В эфир ушло фото российского
военного инспектирования техники вместо министра по делам ветеранов
Украины.

`refetch.py round_record()` сам помечает сцену, когда `--force` называет
смену стратегии словами «переключ»/«стратег»/«поиск по персоне»/«поиск по
имени» — запись ложится в `.strana_proverka.json`. Этот гейт требует явный
вердикт по каждой такой сцене, как `deti_gate.py`:

    python3 strana_gate.py check   <проект>        # 0 — чисто/нет записей, 1 — нужен вердикт
    python3 strana_gate.py spisok  <проект>        # что именно проверять
    python3 strana_gate.py verdikt <проект> --ok 1,2 --bad 5 --kto "та страна/тот человек"

Смотрящий (субагент `kadry` или внешний агент) сверяет кадр с ЗАПРОСОМ этой
сцены — тот ли человек, та ли страна — и называет номера сцен, которые
НЕ подтвердились (`--bad`); остальные из списка считаются подтверждёнными
автоматически при `--ok` или при `--vse-chisto`.

Обход — только `VIDEORYAD_NO_STRANA=1` и только по его прямому слову про
этот ролик.
"""
import argparse
import json
import os
import sys
import time

ОТМЕТКИ = ".strana_proverka.json"
ВЕРДИКТ = ".strana_verdict.json"


def _ч(путь):
    try:
        return json.load(open(путь, encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _вердикт():
    try:
        return json.load(open(ВЕРДИКТ, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sid_of(key):
    """«images:42» → 42."""
    try:
        return int(str(key).rsplit(":", 1)[-1])
    except ValueError:
        return None


def cmd_spisok(проект):
    os.chdir(проект)
    записи = _ч(ОТМЕТКИ)
    в = _вердикт()
    if not записи:
        print("записей нет — гейт чист по умолчанию")
        return 0
    непроверено = [r for r in записи if r.get("key") not in в]
    if not непроверено:
        print("все %d записей уже с вердиктом" % len(записи))
        return 0
    print("НУЖНА ПРОВЕРКА — сцена сменила стратегию поиска, сито её не "
          "видело (%d):" % len(непроверено))
    for r in непроверено:
        sid = _sid_of(r.get("key"))
        print("  сцена %s — %s" % (sid, r.get("why", "")[:120]))
    return 0


def cmd_verdikt(проект, a):
    os.chdir(проект)
    в = _вердикт()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if a.vse_chisto:
        for r in _ч(ОТМЕТКИ):
            в[r.get("key")] = {"ok": True, "ts": ts}
    for sid in (a.ok or "").split(","):
        sid = sid.strip()
        if not sid:
            continue
        for r in _ч(ОТМЕТКИ):
            if str(_sid_of(r.get("key"))) == sid:
                в[r.get("key")] = {"ok": True, "ts": ts}
    for sid in (a.bad or "").split(","):
        sid = sid.strip()
        if not sid:
            continue
        for r in _ч(ОТМЕТКИ):
            if str(_sid_of(r.get("key"))) == sid:
                в[r.get("key")] = {"ok": False, "kto": a.kto or "",
                                   "ts": ts}
    json.dump(в, open(ВЕРДИКТ, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    плохие = [k for k, v in в.items() if not v.get("ok")]
    if плохие:
        print("ЗАПИСАНО, но остались БРАКОВАННЫЕ (%d) — чинить перед "
              "дашбордом: %s" % (len(плохие), ", ".join(
                  str(_sid_of(k)) for k in плохие)))
        return 1
    print("вердикт записан, все чисто")
    return 0


def cmd_check(проект):
    if os.environ.get("VIDEORYAD_NO_STRANA") == "1":
        print("VIDEORYAD_NO_STRANA=1 — гейт пропущен по его слову")
        return 0
    os.chdir(проект)
    записи = _ч(ОТМЕТКИ)
    if not записи:
        return 0
    в = _вердикт()
    непроверено = [r for r in записи if r.get("key") not in в]
    if непроверено:
        print("ПРОВЕРКА СТРАНЫ/ПЕРСОНЫ НЕ ПРОЙДЕНА: %d сцен сменили "
              "стратегию поиска и ни разу не прошли сито «не та страна/не "
              "тот человек» (см. `strana_gate.py spisok`)." % len(непроверено),
              file=sys.stderr)
        return 1
    плохие = [k for k, v in в.items() if not v.get("ok")]
    if плохие:
        print("ПРОВЕРКА СТРАНЫ/ПЕРСОНЫ: %d сцен помечены браком и не "
              "починены: %s" % (len(плохие),
              ", ".join(str(_sid_of(k)) for k in плохие)), file=sys.stderr)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("spisok"); p1.add_argument("проект")
    p2 = sub.add_parser("check"); p2.add_argument("проект")
    p3 = sub.add_parser("verdikt")
    p3.add_argument("проект")
    p3.add_argument("--ok", default="")
    p3.add_argument("--bad", default="")
    p3.add_argument("--kto", default="")
    p3.add_argument("--vse-chisto", action="store_true", dest="vse_chisto")
    a = ap.parse_args()
    if a.cmd == "spisok":
        return cmd_spisok(a.проект)
    if a.cmd == "check":
        return cmd_check(a.проект)
    if a.cmd == "verdikt":
        return cmd_verdikt(a.проект, a)
    return 1


if __name__ == "__main__":
    sys.exit(main())
