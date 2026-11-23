# -*- coding: utf-8 -*-
"""УТВЕРЖДЕНО — ЗНАЧИТ ЗАМОРОЖЕНО. ПОСЛЕ ЭТОГО НИ ОДНОГО КАДРА.

Его слова 10.11, два подряд: «Если он утверждён, значит он утверждён» (Z-0019)
и «нарушение отдать управляющей вкладке, пускай пофиксит это, чтобы больше
никогда такого не повторялось. Это же было строгое правило, блин» (Z-0020).

Повод: вкладка получила «дашборд утверждаю», ПОСЛЕ этого нашла ситом слабый
кадр на сцене 50, заменила его и отправила пересборку. Находка была верной —
действие нет: утверждение пользователя относится к КОНКРЕТНОМУ составу
кадров, и любая правка после него делает сданное не тем, что он видел.
Правило держалось памятью вкладки и не удержалось, поэтому теперь — код.

Как работает:

    python3 zamorozka.py postavit <проект>     # запомнить утверждённый состав
    python3 zamorozka.py check    <проект>     # 0 — можно, 1 — правки запрещены
    python3 zamorozka.py snyat    <проект> --slovo-polzovatelya

`<проект>` — полный путь ИЛИ просто имя папки в `~/projects` (16.11, п.186):
имя проекта принимают остальные инструменты конвейера, и здесь оно теперь
тоже адрес. Папки с таким именем нет — ответ «ПРОЕКТ НЕ НАЙДЕН» и код 3, а
не «заморозки и не было»: эти два ответа путать нельзя.

`postavit` ставит `ship.sh` сам при ПЕРВОЙ полной сборке (не `--fetch-only`):
полная сборка идёт только после его «собирай», это и есть момент утверждения.
`check` сверяет md5 сценария, `overlays.json` и всех кадров. Совпало — пуск
разрешён (это пересборка того же самого); разошлось — отказ.

Снять заморозку может только пользователь: ключ `--slovo-polzovatelya`, и
вкладке его ставить нельзя. Находку после утверждения несут координатору,
пересборку назначает он.
"""
import argparse
import glob
import hashlib
import json
import os
import sys
import time

FAIL_FILE = ".utverzhdeno.json"


def _pdir(p):
    """Папка проекта по полному пути ИЛИ по одному имени проекта.

    ИМЯ ПРОЕКТА — ТОЖЕ АДРЕС (16.11, улов `usuario-7c`, `НА-РАСКАТКУ` п.186).
    Было: аргумент понимался только как путь, и на `zamorozka.py snyat
    planeta-3-svo-1711` инструмент отвечал «заморозки и не было» — то есть
    про НЕСУЩЕСТВУЮЩУЮ папку `./planeta-3-svo-1711`. Вкладка читала это как
    «заморозки нет», шла собирать и упиралась в отказ `ship.sh` (п.185).
    Остальные инструменты конвейера имя проекта принимают (`accept_scenes`,
    `check_pins`, `codex_brief`), поэтому и здесь так же: не нашлось по
    пути — ищем `~/projects/<имя>`, затем папку забора `~/projects/<имя>-cloud`.
    Ничего не нашлось — возвращаем как было, чтобы вызывающий сказал
    «проект не найден», а не «заморозки не было».
    """
    p = p or "."
    пути = [os.path.abspath(os.path.expanduser(p))]
    if not os.path.isdir(пути[0]) and not os.path.isabs(p) and os.sep not in p:
        пути.append(os.path.expanduser(os.path.join("~/projects", p)))
        пути.append(os.path.expanduser(os.path.join("~/projects", p + "-cloud")))
    for к in пути:
        if os.path.isdir(к):
            return os.path.abspath(к)
    return пути[0]


def _md5(path):
    h = hashlib.md5()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _scenes_file(pdir):
    cands = [f for f in glob.glob(os.path.join(pdir, "*.scenes.json"))
             if not os.path.basename(f).startswith(("codex", "lib_", "raw"))]
    if not cands:
        cands = glob.glob(os.path.join(pdir, "*.scenes.json"))
    return cands[0] if cands else None


def _snimok(pdir):
    """Состав ролика одним слепком: сценарий, всплывашки, все кадры."""
    s = {"scenes": "", "overlays": "", "kadry": {}}
    sf = _scenes_file(pdir)
    if sf:
        s["scenes"] = _md5(sf)
    ov = os.path.join(pdir, "overlays.json")
    if os.path.exists(ov):
        s["overlays"] = _md5(ov)
    for d in ("images", "overlays", "cards/photo"):
        dd = os.path.join(pdir, d)
        if not os.path.isdir(dd):
            continue
        for f in sorted(os.listdir(dd)):
            fp = os.path.join(dd, f)
            # `.text.png` — ДЕРИВАТИВ overlays.json, НЕ НОВЫЙ КОНТЕНТ (21.11,
            # улов `usuario-3e`). Надпись из-под маски перерисовывается заново
            # при каждой сборке с тем же текстом, но НОВЫМ отпечатком PNG —
            # рендер не детерминирован. Сам текст уже сверяется через md5
            # `overlays.json` выше; второй раз та же правка считалась как
            # «изменилось» без единой настоящей правки, гейт свежести не
            # стабилизировался НИКОГДА.
            if (not os.path.isfile(fp)
                    or f.endswith((".json", ".revframe.jpg", ".text.png"))):
                continue
            s["kadry"]["%s/%s" % (d, f)] = _md5(fp)
    return s


def _после_просмотра(pdir):
    """Кадры, чей mtime НОВЕЕ последнего реального открытия дашборда
    (`.posledniy_prosmotr`, пишет `review.py` на каждый GET страницы) —
    они легли в проект ПОСЛЕ того, как он в последний раз смотрел, и в
    слепок утверждения попадут непроверенными им глазами. Его вопрос
    18.11: «не мог ли он просочиться без моей проверки» — мог, если
    фоновый дозаказ кадра дописал файл в этом окне."""
    метка = os.path.join(pdir, ".posledniy_prosmotr")
    if not os.path.isfile(метка):
        return []
    try:
        t_просмотр = float(open(метка, encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return []
    подозрительно = []
    for d in ("images", "overlays", "cards/photo"):
        dd = os.path.join(pdir, d)
        if not os.path.isdir(dd):
            continue
        for f in sorted(os.listdir(dd)):
            fp = os.path.join(dd, f)
            # `.text.png` исключён по той же причине, что в `_snimok` выше —
            # недетерминированный рендер надписи, не новый контент.
            if (not os.path.isfile(fp)
                    or f.endswith((".json", ".revframe.jpg", ".text.png"))):
                continue
            try:
                if os.path.getmtime(fp) > t_просмотр:
                    подозрительно.append("%s/%s" % (d, f))
            except OSError:
                continue
    return подозрительно


def cmd_postavit(args):
    pdir = _pdir(args.project)
    p = os.path.join(pdir, FAIL_FILE)
    if os.path.exists(p) and not args.perezapisat:
        print("заморозка уже стоит — ничего не меняю")
        return 0
    # ДАШБОРД НИ РАЗУ НЕ ОТКРЫВАЛСЯ (23.11) — его прямое слово «я никакого
    # дашборда не утверждал». Живой случай: вкладка звала ship.sh напрямую
    # (ship.sh без --fetch-only сам зовёт postavit как «момент утверждения»),
    # минуя review.py — .posledniy_prosmotr никогда не писался, и старая
    # _после_просмотра() на отсутствующую метку отвечала «подозрительных
    # нет», то есть замораживала БЕЗ единого живого показа страницы.
    метка_просмотра = os.path.join(pdir, ".posledniy_prosmotr")
    if not os.path.isfile(метка_просмотра):
        print("!! ДАШБОРД НИ РАЗУ НЕ ОТКРЫВАЛСЯ — заморозка (и сборка) не "
              "ставится.", file=sys.stderr)
        print("   Подними review.py --live и дай ему открыть страницу, "
              "прежде чем собирать.", file=sys.stderr)
        print("   Обход только его прямым словом на этот ролик: "
              "VIDEORYAD_POSTAVIT_BEZ_PROVERKI=1", file=sys.stderr)
        if os.environ.get("VIDEORYAD_POSTAVIT_BEZ_PROVERKI") != "1":
            return 1
    data = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "snimok": _snimok(pdir)}
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("УТВЕРЖДЕНО И ЗАМОРОЖЕНО в %s: кадров %d. Дальше правки запрещены."
          % (data["ts"], len(data["snimok"]["kadry"])))
    _сомнительные = _после_просмотра(pdir)
    if _сомнительные:
        print("!! ВНИМАНИЕ: %d файлов изменились ПОСЛЕ последнего открытия "
              "дашборда — он мог утвердить состав, не увидев их таким, каким "
              "он лёг в заморозку:" % len(_сомнительные), file=sys.stderr)
        for f in _сомнительные[:20]:
            print("   %s" % f, file=sys.stderr)
        print("   Обнови дашборд (перезагрузи страницу) и получи его "
              "утверждение ЕЩЁ РАЗ, прежде чем собирать. Обход только его "
              "словом: VIDEORYAD_POSTAVIT_BEZ_PROVERKI=1.", file=sys.stderr)
        if os.environ.get("VIDEORYAD_POSTAVIT_BEZ_PROVERKI") != "1":
            return 1
    return 0


def cmd_check(args):
    """0 — работать можно; 1 — проект заморожен и состав изменён."""
    pdir = _pdir(args.project)
    # ПАПКИ НЕТ — ЭТО НЕ «ЗАМОРОЗКИ НЕТ» (16.11, п.186). Код не меняем:
    # решение о сборке принимает `ship.sh`, а здесь важно, чтобы вкладка не
    # прочла тишину как разрешение.
    if not os.path.isdir(pdir):
        print("zamorozka: ПРОЕКТ НЕ НАЙДЕН (%s) — проверка заморозки НЕ "
              "сделана, дай полный путь" % pdir, file=sys.stderr)
    p = os.path.join(pdir, FAIL_FILE)
    if os.environ.get("VIDEORYAD_RAZMOROZKA") == "1":
        print("zamorozka: ОБХОД VIDEORYAD_RAZMOROZKA=1 — только по слову пользователя")
        return 0
    if not os.path.exists(p):
        return 0
    try:
        was = json.load(open(p, encoding="utf-8"))["snimok"]
    except Exception:
        return 0
    now = _snimok(pdir)
    raznica = []
    if was.get("scenes") and was["scenes"] != now.get("scenes"):
        raznica.append("сценарий")
    if was.get("overlays") != now.get("overlays"):
        raznica.append("overlays.json")
    for k, v in was.get("kadry", {}).items():
        if now.get("kadry", {}).get(k) != v:
            raznica.append(k)
    for k in now.get("kadry", {}):
        if k not in was.get("kadry", {}):
            raznica.append("новый " + k)
    if not raznica:
        if args.tikho:
            return 0
        print("заморозка цела: состав тот же, что он утвердил — пересборка разрешена")
        return 0
    ts = ""
    try:
        ts = json.load(open(p, encoding="utf-8")).get("ts", "")
    except Exception:
        pass
    print("ДАШБОРД УТВЕРЖДЁН%s — ПРАВКИ ЗАПРЕЩЕНЫ." % (" в " + ts if ts else ""),
          file=sys.stderr)
    print("  Разошлось: " + " · ".join(raznica[:10])
          + (" и ещё %d" % (len(raznica) - 10) if len(raznica) > 10 else ""),
          file=sys.stderr)
    print("  Находку НЕ чини сам — неси координатору, пересборку назначает "
          "пользователь.", file=sys.stderr)
    print("  Вернуть как было: восстанови кадры из утверждённого состава.",
          file=sys.stderr)
    return 1


def cmd_snyat(args):
    pdir = _pdir(args.project)
    if not args.slovo:
        print("снять заморозку может только пользователь: "
              "--slovo-polzovatelya", file=sys.stderr)
        return 2
    # «ПАПКИ НЕТ» И «ЗАМОРОЗКИ НЕТ» — ДВА РАЗНЫХ ОТВЕТА (16.11, п.186).
    # Прежде оба случая отвечали «заморозки и не было», и опечатка в имени
    # проекта читалась как разрешение собирать.
    if not os.path.isdir(pdir):
        print("ПРОЕКТ НЕ НАЙДЕН: «%s»" % args.project, file=sys.stderr)
        print("  искал как путь, как ~/projects/%s и как ~/projects/%s-cloud."
              % (args.project, args.project), file=sys.stderr)
        print("  Дай полный путь к папке проекта. Про заморозку это НИЧЕГО "
              "не говорит — она может стоять.", file=sys.stderr)
        return 3
    p = os.path.join(pdir, FAIL_FILE)
    if os.path.exists(p):
        os.remove(p)
        print("заморозка снята по слову пользователя (%s)" % pdir)
    else:
        print("заморозки в %s и не было" % pdir)
    return 0


def zamorozheno(pdir, tikho=True):
    """Короткая дверь для ИНСТРУМЕНТОВ ПРАВКИ: True — трогать проект нельзя.

    Здесь намеренно НЕ та же логика, что в `ship.sh`. Сборке важно, разошёлся
    ли состав с утверждённым (пересборка того же самого разрешена), а
    инструменту правки — сам ФАКТ утверждения: иначе первый `ban_file` на
    замороженном проекте прошёл бы спокойно (состав-то ещё совпадает), кадр
    бы уехал, и упёрлись бы мы только на пуше, потеряв круг. Ровно это и
    случилось 10.11 (Z-0019).
    """
    try:
        if os.environ.get("VIDEORYAD_RAZMOROZKA") == "1":
            return False
        return os.path.exists(os.path.join(pdir, FAIL_FILE))
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("postavit")
    a.add_argument("project")
    a.add_argument("--perezapisat", action="store_true")
    a.set_defaults(func=cmd_postavit)
    b = sub.add_parser("check")
    b.add_argument("project")
    b.add_argument("--tikho", action="store_true")
    b.set_defaults(func=cmd_check)
    c = sub.add_parser("snyat")
    c.add_argument("project")
    c.add_argument("--slovo-polzovatelya", dest="slovo", action="store_true")
    c.set_defaults(func=cmd_snyat)
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
