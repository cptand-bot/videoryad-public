#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СВЯЗКА «ЗАГОЛОВОК + НАДПИСИ + ПРЕВЬЮ» И ЕЁ СУДЬБА (08.11.2026).

Его слово: «эти названия, которые я ввожу, и надписи, которые я применяю, это
же не значит, что они на сто процентов уверенно зайдут. Это значит, что вот
этот вариант я выбрал. Как они зайдут или не зайдут на тот или иной канал, мы
будем смотреть уже по статистике, через неделю или за три-четыре дня. Вот там
всё будет понятно: залетела эта связка или не залетела. Эту логику тоже надо
зафиксировать».

ОТСЮДА ДВА РАЗНЫХ ФАКТА, И ПУТАТЬ ИХ НЕЛЬЗЯ:
  1. ЧТО ОН ВЫБРАЛ — пишется само, дашбордом упаковки, в день сборки.
     Это его ВКУС, а не доказательство.
  2. КАК ЭТО ЗАШЛО — приходит через 3-7 дней из статистики канала.
     Только это и есть доказательство.

Поэтому обучение на журнале идёт по трём уровням:
  · ЗАЛЕТЕЛО      — связка с подтверждённой статистикой, главный ориентир;
  · НЕ ЗАШЛО      — тоже подтверждено, идёт в задание как «так не делать»;
  · ПОКА БЕЗ ЗАМЕРА — его выбор без статистики, слабый ориентир.

    python3 svyazka.py --список                 # что ждёт замера
    python3 svyazka.py --ждут                   # только созревшие (3+ дня)
    python3 svyazka.py --замер <id> --просмотры 42000 --вердикт залетело
    python3 svyazka.py --замер <id> --просмотры 4100 --ctr 3.1 --вердикт нет

Результаты ложатся в `upakovka_lib/svyazki.jsonl` и подхватываются
`upakovka.py` при следующей упаковке. Статистику вводит ОН или редакция:
у нас доступа к кабинету канала нет, и выдумывать числа запрещено.
"""

import argparse
import io
import json
import os
import sys
import time

ЗДЕСЬ = os.path.dirname(os.path.abspath(__file__))
ЖУРНАЛ = os.path.join(ЗДЕСЬ, "upakovka_lib", "vybor.jsonl")
СВЯЗКИ = os.path.join(ЗДЕСЬ, "upakovka_lib", "svyazki.jsonl")
ВЕРДИКТЫ = ("залетело", "средне", "нет")


def _читать(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def связки():
    """Собираем связки из журнала выбора: канал + тема = одна связка."""
    по_теме = {}
    for e in _читать(ЖУРНАЛ):
        ключ = "%s|%s" % (e.get("канал", ""), e.get("тема", ""))
        с = по_теме.setdefault(ключ, {
            "id": ключ, "канал": e.get("канал", ""), "тема": e.get("тема", ""),
            "дата": (e.get("когда") or "")[:10],
            "заголовок": "", "надписи": [], "превью": None})
        if e.get("событие") == "превью":
            с["превью"] = e.get("выбран_вариант")
            for поле in ("надпись_сверху", "надпись_снизу"):
                if e.get(поле):
                    с["надписи"].append(e[поле])
        elif str(e.get("событие") or "").startswith("свой_заголов"):
            с["заголовок"] = e.get("выбрано", "")
        elif e.get("событие") == "заголовки" and not с["заголовок"]:
            с["заголовок"] = "(скопировал из списка) " + (e.get("выбрано") or "")
    замеры, описания, файлы = {}, {}, {}
    пакеты = {}
    for z in _читать(СВЯЗКИ):
        for поле in ("суть", "актуальность", "подача", "паттерн",
                     "хронометраж", "день", "описание_ролика"):
            if z.get(поле):
                пакеты.setdefault(z["id"], {})[поле] = z[поле]
        if z.get("описание_превью"):
            описания[z["id"]] = z["описание_превью"]
        if z.get("вердикт") or z.get("просмотры"):
            замеры[z["id"]] = z
    for e in _читать(ЖУРНАЛ):
        if e.get("файл_превью"):
            файлы["%s|%s" % (e.get("канал", ""), e.get("тема", ""))] = e["файл_превью"]
    for к, с in по_теме.items():
        с["замер"] = замеры.get(к)
        с["описание_превью"] = описания.get(к, "")
        с.update(пакеты.get(к, {}))
        с["файл_превью"] = файлы.get(к, "")
    return list(по_теме.values())



def из_папки(folder):
    """Что можно взять из папки темы без вопросов: паттерн упаковки,
    хронометраж озвучки, канал и день публикации из пути."""
    из = {}
    if not folder or not os.path.isdir(folder):
        return из
    try:
        up = os.path.join(folder, "УПАКОВКА.json")
        if os.path.exists(up):
            d = json.load(io.open(up, encoding="utf-8"))
            из["паттерн"] = d.get("паттерн") or d.get("pattern") or ""
            из["описание_ролика"] = (d.get("описание") or "")[:400]
    except Exception:
        pass
    try:
        import subprocess
        mp3 = [f for f in os.listdir(folder) if f.lower().endswith(".mp3")]
        if mp3:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of", "csv=p=0",
                                os.path.join(folder, mp3[0])],
                               capture_output=True, text=True, timeout=20)
            сек = float((r.stdout or "0").strip() or 0)
            если = int(сек)
            из["хронометраж"] = "%d:%02d" % (если // 60, если % 60)
    except Exception:
        pass
    части = os.path.abspath(folder).replace("\\", "/").split("/")
    for ч in части:
        if len(ч) == 5 and ч[2] == "-" and ч.replace("-", "").isdigit():
            из["день"] = ч
    return из


def дней_прошло(дата):
    try:
        t = time.mktime(time.strptime(дата, "%Y-%m-%d"))
        return int((time.time() - t) // 86400)
    except (ValueError, TypeError):
        return 0


def main():
    ap = argparse.ArgumentParser(description="связка заголовок+надписи+превью и её статистика")
    ap.add_argument("--список", "--list", action="store_true", dest="show")
    ap.add_argument("--ждут", action="store_true", help="только созревшие без замера (3+ дня)")
    ap.add_argument("--замер", default="", dest="mark", help="id связки")
    ap.add_argument("--просмотры", type=int, default=0)
    ap.add_argument("--ctr", type=float, default=0.0)
    ap.add_argument("--вердикт", default="", choices=("",) + ВЕРДИКТЫ)
    ap.add_argument("--заметка", default="")
    # СТАТИСТИКА РАЗНАЯ ПО КАНАЛАМ (08.11, его слово: «на одном канале одна
    # аудитория, на другом другая; один канал ютуб рекомендует в одной хрени,
    # другой в другой; там больше мужиков, там больше из России, а там с
    # Украиной больше»). Поэтому замер хранит и состав аудитории, а обучение
    # идёт ПО КАНАЛУ, а не общим котлом.
    ap.add_argument("--аудитория", default="", dest="aud",
                    help="состав: «РФ 62%%, Украина 18%%, муж 71%%, 45+ 40%%»")
    ap.add_argument("--удержание", default="", dest="udr",
                    help="среднее удержание, если есть: «42%%» или «4:10»")
    ap.add_argument("--по-каналам", action="store_true", dest="by_ch",
                    help="сводка: что залетало на каждом канале")
    # ПОЛНЫЙ ПАКЕТ, А НЕ ТОЛЬКО КАРТИНКА (08.11, его слово: «привязывать это
    # всё вместе, связывать с темой ролика: превью, надписи на превью,
    # заголовок, сама тема, её актуальность, её подача, её востребованность —
    # в общем, полный пакет»). Тема, канал, паттерн и хронометраж тянутся
    # сами из папки темы; суть, актуальность и подачу вписываем словами.
    ap.add_argument("--суть", default="", dest="sut",
                    help="о чём ролик одной строкой")
    ap.add_argument("--актуальность", default="", dest="akt",
                    help="сегодняшнее событие / вчерашнее / старая тема / вечная")
    ap.add_argument("--подача", default="", dest="pod",
                    help="как подано: разбор, издёвка, предупреждение, счёт по фактам…")
    ap.add_argument("--папка", default="", dest="folder",
                    help="папка темы — из неё подтянутся паттерн и хронометраж")
    ap.add_argument("--описание", default="", dest="opis",
                    help="ЧТО НАРИСОВАНО на превью: кто в кадре, эмоция, план, "
                         "цвет, объекты. Пишется отдельной записью к связке")
    a = ap.parse_args()

    все = связки()

    if a.mark:
        цель = [с for с in все if с["id"] == a.mark]
        if not цель:
            print("связки с таким id нет. Есть:")
            for с in все:
                print("  %s" % с["id"])
            return 2
        пакет = {k: v for k, v in (("суть", a.sut), ("актуальность", a.akt),
                                   ("подача", a.pod)) if v}
        пакет.update(из_папки(a.folder))
        if пакет:
            пакет.update({"id": a.mark, "когда": time.strftime("%Y-%m-%d %H:%M:%S")})
            os.makedirs(os.path.dirname(СВЯЗКИ), exist_ok=True)
            with io.open(СВЯЗКИ, "a", encoding="utf-8") as f:
                f.write(json.dumps(пакет, ensure_ascii=False) + "\n")
            print("пакет темы записан: %s" % ", ".join(
                k for k in пакет if k not in ("id", "когда")))
            if not a.opis and not a.вердикт and not a.просмотры:
                return 0
        if a.opis:
            os.makedirs(os.path.dirname(СВЯЗКИ), exist_ok=True)
            with io.open(СВЯЗКИ, "a", encoding="utf-8") as f:
                f.write(json.dumps({"id": a.mark, "описание_превью": a.opis,
                                    "когда": time.strftime("%Y-%m-%d %H:%M:%S")},
                                   ensure_ascii=False) + "\n")
            print("описание превью записано: %s" % a.mark)
            if not a.вердикт and not a.просмотры:
                return 0
        if not a.вердикт and not a.просмотры:
            return print("нужен хотя бы --просмотры или --вердикт") or 2
        запись = {"id": a.mark, "когда": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "просмотры": a.просмотры or None, "ctr": a.ctr or None,
                  "аудитория": a.aud or None, "удержание": a.udr or None,
                  "вердикт": a.вердикт or ("залетело" if a.просмотры else ""),
                  "заметка": a.заметка}
        os.makedirs(os.path.dirname(СВЯЗКИ), exist_ok=True)
        with io.open(СВЯЗКИ, "a", encoding="utf-8") as f:
            f.write(json.dumps(запись, ensure_ascii=False) + "\n")
        print("записано: %s — %s%s" % (a.mark, запись["вердикт"],
                                       (", просмотров %d" % a.просмотры) if a.просмотры else ""))
        return 0

    if not все:
        print("связок пока нет: он ещё не выбирал заголовки и превью")
        return 0

    if a.by_ch:
        по_каналам = {}
        for с in все:
            по_каналам.setdefault(с["канал"] or "(без канала)", []).append(с)
        for канал, список in sorted(по_каналам.items()):
            замеренные = [x for x in список if x.get("замер")]
            залетели = [x for x in замеренные
                        if (x["замер"] or {}).get("вердикт") == "залетело"]
            print("=== %s: связок %d, с замером %d, залетело %d"
                  % (канал, len(список), len(замеренные), len(залетели)))
            for x in залетели:
                з = x["замер"] or {}
                print("   ✓ %s" % (x.get("заголовок") or x["тема"])[:90])
                print("     надписи: %s" % (" / ".join(x.get("надписи") or []) or "—"))
                if з.get("просмотры"):
                    print("     просмотров: %s%s" % (з["просмотры"],
                          (", аудитория: " + з["аудитория"]) if з.get("аудитория") else ""))
            if замеренные and not залетели:
                print("   (пока ни одна не залетела)")
        return 0

    for с in все:
        дней = дней_прошло(с["дата"])
        замер = с.get("замер")
        if a.ждут and (замер or дней < 3):
            continue
        статус = ("ЗАМЕР: %s%s" % (замер["вердикт"],
                                   (", %d просмотров" % замер["просмотры"])
                                   if замер.get("просмотры") else "")
                  if замер else ("ЖДЁТ ЗАМЕРА (%d дн.)" % дней if дней >= 3
                                 else "рано, %d дн." % дней))
        print("· %s" % с["id"])
        print("   заголовок: %s" % (с["заголовок"] or "—"))
        print("   надписи:   %s" % (" / ".join(с["надписи"]) or "—"))
        print("   превью:    %s   %s" % (с["превью"] or "—", статус))
        if с.get("описание_превью"):
            print("   на превью: %s" % с["описание_превью"][:160])
        пакет = " · ".join("%s: %s" % (k, с[k]) for k in
                           ("суть", "актуальность", "подача", "паттерн",
                            "хронометраж") if с.get(k))
        if пакет:
            print("   тема:      %s" % пакет[:200])
    if a.ждут:
        print("\nвписать результат: svyazka.py --замер \"<id>\" --просмотры N --вердикт залетело")
    return 0


if __name__ == "__main__":
    sys.exit(main())
