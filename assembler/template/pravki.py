#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЖУРНАЛ ПРАВОК — что мы меняли в коде и зачем (12.11.2026).

Его слово 12.11: «нужно завести ещё отдельную вкладку… чтобы туда заносились
наши правки, наши действия, чтобы это был тоже ещё один журнал, с которым мы
могли бы сверяться. Чтобы ты в случае чего — ой, я не записал себе в скилл
или в память, — а я тебе скажу: туда иди, смотри там».

ПОЧЕМУ ОТДЕЛЬНЫЙ ЖУРНАЛ, А НЕ ПАМЯТЬ И НЕ SKILL.md
  Память и скилл хранят ПРАВИЛА («как надо»), а это журнал ДЕЙСТВИЙ («что
  сделали и когда»). Правило из памяти теряется при смене вкладки, а строка
  здесь не теряется никогда: файл дописывается, а не переписывается.

УСТРОЙСТВО
  · `base/pravki.tsv` — только ДОПИСЫВАЕТСЯ. Руками не править (правило
    реестра занятых: греп по значениям дважды сносил записи дня).
  · Раскатка пишется САМА: `cloud/sync_assembler.sh` зовёт
    `pravki.py raskatka <цель> --fayly …` после успешного пуша. Десять целей
    одной правки ложатся в ОДНУ строку: цель дописывается к уже открытой
    записи того же набора файлов за последние три часа.
  · На Google Drive лежит таблицей «ГЕОРАДАР — ЖУРНАЛ ПРАВОК (что меняли в
    коде, когда и зачем)», id `1hwuPNd5WCa26OGQuF4dSH8T18JEN1ZilJt-5A8wW4Qg`,
    рядом с базой статистики. Сам GEO2 НЕ ТРОГАЕМ: туда пишет редакция.
    Коннектор не умеет ни дописывать строки, ни менять содержимое
    (`update_file` правит только имя и место) — обновление ПЕРЕСОЗДАНИЕМ из
    `--csv`, старый файл в корзину, как у базы статистики. Значит id после
    каждого обновления НОВЫЙ: постоянная зацепка — НАЗВАНИЕ, а не id.

КОМАНДЫ
  pravki.py dobav --fayly "template/faza.sh" --chto "…" --povod "…"
  pravki.py raskatka cptand-pub --fayly "a.py,b.py"
  pravki.py spisok [--dni 3] [--kto имя]
  pravki.py nayti "музыка"
  pravki.py --csv [файл]            # выгрузка для таблицы
"""
import argparse
import csv
import datetime
import io
import os
import sys

СКИЛЛ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ЖУРНАЛ = os.path.join(СКИЛЛ, "base", "pravki.tsv")
ПОЛЯ = ["id", "дата", "время", "кто", "файлы", "что", "повод",
        "цели", "проверено", "заметка"]
ОКНО_ЧАСОВ = 3          # в пределах скольки часов раскатка считается той же


def _сейчас():
    return datetime.datetime.now()


def _читать():
    if not os.path.exists(ЖУРНАЛ):
        return []
    with io.open(ЖУРНАЛ, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f, delimiter="\t") if r.get("id")]


def _писать_всё(строки):
    """Перезапись ЦЕЛИКОМ нужна только для дописывания цели в открытую
    строку. Пишем через временный файл: обрыв на середине не должен
    оставить журнал обрезанным."""
    врем = ЖУРНАЛ + ".tmp"
    with io.open(врем, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ПОЛЯ, delimiter="\t",
                           extrasaction="ignore")
        w.writeheader()
        for r in строки:
            w.writerow(r)
    os.replace(врем, ЖУРНАЛ)


def _дописать(строка):
    есть = os.path.exists(ЖУРНАЛ)
    os.makedirs(os.path.dirname(ЖУРНАЛ), exist_ok=True)
    with io.open(ЖУРНАЛ, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ПОЛЯ, delimiter="\t",
                           extrasaction="ignore")
        if not есть:
            w.writeheader()
        w.writerow(строка)


def _кто(явно=""):
    return (явно or os.environ.get("VIDEORYAD_KTO")
            or os.environ.get("VIDEORYAD_TAB") or "вкладка")


def _новый_id(строки):
    n = 0
    for r in строки:
        try:
            n = max(n, int(str(r["id"]).lstrip("П-")))
        except ValueError:
            pass
    return "П-%04d" % (n + 1)


def _набор(s):
    return tuple(sorted(x.strip() for x in str(s).replace(";", ",").split(",")
                        if x.strip()))


def dobav(a):
    строки = _читать()
    т = _сейчас()
    строка = {
        "id": _новый_id(строки), "дата": т.strftime("%d.%m.%Y"),
        "время": т.strftime("%H:%M"), "кто": _кто(a.kto),
        "файлы": ", ".join(_набор(a.fayly)), "что": a.chto,
        "повод": a.povod, "цели": a.celi, "проверено": a.provereno,
        "заметка": a.zametka,
    }
    _дописать(строка)
    print("записано %s: %s — %s" % (строка["id"], строка["файлы"] or "—",
                                    строка["что"][:70]))
    return 0


def raskatka(a):
    """Цель дописывается к УЖЕ ОТКРЫТОЙ записи того же набора файлов.

    Иначе одна правка, уехавшая по десяти целям, дала бы десять одинаковых
    строк и журнал стал бы нечитаемым ровно в тот день, когда он нужен.
    """
    набор = _набор(a.fayly)
    if not набор:
        return 0
    строки = _читать()
    т = _сейчас()
    for r in reversed(строки):
        if _набор(r.get("файлы", "")) != набор:
            continue
        try:
            когда = datetime.datetime.strptime(
                r["дата"] + " " + r["время"], "%d.%m.%Y %H:%M")
        except ValueError:
            continue
        if (т - когда).total_seconds() > ОКНО_ЧАСОВ * 3600:
            break
        цели = [c for c in str(r.get("цели", "")).split(", ") if c]
        if a.cel in цели:
            return 0
        цели.append(a.cel)
        r["цели"] = ", ".join(цели)
        _писать_всё(строки)
        print("цель %s дописана к %s (целей %d)" % (a.cel, r["id"], len(цели)))
        return 0
    # открытой записи нет — правка ушла мимо журнала, заводим строку сами:
    # пусть будет неполная запись, чем ни одной.
    _дописать({
        "id": _новый_id(строки), "дата": т.strftime("%d.%m.%Y"),
        "время": т.strftime("%H:%M"), "кто": _кто(),
        "файлы": ", ".join(набор),
        "что": "раскатка без записи в журнале (описание не задано)",
        "повод": "", "цели": a.cel, "проверено": "", "заметка": "",
    })
    print("заведена строка по раскатке %s (описания не было)" % a.cel)
    return 0


def opisat(a):
    """Дописать описание к строке, которую завела САМА раскатка.

    Авто-строка («описание не задано») лучше пропущенной, но пустой она
    бесполезна: журнал читают, чтобы вспомнить ПОЧЕМУ.
    """
    строки = _читать()
    for r in строки:
        if r["id"].lower() != a.id.lower():
            continue
        if a.chto:
            r["что"] = a.chto
        if a.povod:
            r["повод"] = a.povod
        if a.provereno:
            r["проверено"] = a.provereno
        if a.zametka:
            r["заметка"] = a.zametka
        _писать_всё(строки)
        print("%s дополнена: %s" % (r["id"], r["что"][:70]))
        return 0
    print("записи %s в журнале нет" % a.id, file=sys.stderr)
    return 1


def spisok(a):
    строки = _читать()
    если_с = None
    if a.dni:
        если_с = _сейчас() - datetime.timedelta(days=a.dni)
    вышло = 0
    for r in строки:
        if a.kto and a.kto.lower() not in r.get("кто", "").lower():
            continue
        if если_с:
            try:
                когда = datetime.datetime.strptime(r["дата"], "%d.%m.%Y")
            except ValueError:
                когда = None
            if когда and когда.date() < если_с.date():
                continue
        print("%s  %s %s  %s\n    файлы: %s\n    что:   %s%s%s%s" % (
            r["id"], r["дата"], r["время"], r["кто"], r["файлы"] or "—",
            r["что"],
            "\n    повод: " + r["повод"] if r.get("повод") else "",
            "\n    цели:  " + r["цели"] if r.get("цели") else "",
            "\n    проверено: " + r["проверено"] if r.get("проверено") else ""))
        вышло += 1
    print("— записей: %d (всего в журнале %d)" % (вышло, len(строки)))
    return 0


def nayti(a):
    слово = a.slovo.lower()
    строки = _читать()
    нашлось = [r for r in строки
               if слово in "\t".join(str(v) for v in r.values()).lower()]
    for r in нашлось:
        print("%s  %s %s  %s · %s\n    %s" % (
            r["id"], r["дата"], r["время"], r["кто"], r["файлы"], r["что"]))
    print("— найдено: %d по слову «%s»" % (len(нашлось), a.slovo))
    return 0


def v_csv(путь):
    строки = _читать()
    путь = путь or os.path.join(СКИЛЛ, "base", "ПРАВКИ.csv")
    with io.open(путь, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ПОЛЯ, extrasaction="ignore")
        w.writeheader()
        for r in строки:
            w.writerow(r)
    print("выгружено %d строк: %s" % (len(строки), путь))
    print("дальше: обновить таблицу «ГЕОРАДАР — ЖУРНАЛ ПРАВОК» на Drive "
          "(id 1hwuPNd5WCa26OGQuF4dSH8T18JEN1ZilJt-5A8wW4Qg) — пересозданием "
          "файла из этого CSV, старый в корзину. GEO2 не трогаем.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="журнал правок кода")
    ap.add_argument("--csv", nargs="?", const="", default=None,
                    help="выгрузить журнал таблицей и выйти")
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("dobav", help="записать правку")
    d.add_argument("--fayly", default="", help="через запятую")
    d.add_argument("--chto", required=True, help="что изменено, одной фразой")
    d.add_argument("--povod", default="", help="почему: улов, его слово, замер")
    d.add_argument("--celi", default="", help="куда раскатано, если уже")
    d.add_argument("--provereno", default="", help="чем проверено (запуском!)")
    d.add_argument("--zametka", default="")
    d.add_argument("--kto", default="")

    r = sub.add_parser("raskatka", help="отметить цель раскатки (зовёт sync)")
    r.add_argument("cel")
    r.add_argument("--fayly", default="")

    o = sub.add_parser("opisat", help="дописать описание к авто-строке")
    o.add_argument("id")
    o.add_argument("--chto", default="")
    o.add_argument("--povod", default="")
    o.add_argument("--provereno", default="")
    o.add_argument("--zametka", default="")

    s = sub.add_parser("spisok", help="показать записи")
    s.add_argument("--dni", type=int, default=0)
    s.add_argument("--kto", default="")

    n = sub.add_parser("nayti", help="поиск по журналу")
    n.add_argument("slovo")

    a = ap.parse_args()
    if a.csv is not None:
        return v_csv(a.csv)
    if a.cmd == "dobav":
        return dobav(a)
    if a.cmd == "raskatka":
        return raskatka(a)
    if a.cmd == "opisat":
        return opisat(a)
    if a.cmd == "spisok":
        return spisok(a)
    if a.cmd == "nayti":
        return nayti(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
