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
    return os.path.abspath(os.path.expanduser(p or "."))


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
            if not os.path.isfile(fp) or f.endswith((".json", ".revframe.jpg")):
                continue
            s["kadry"]["%s/%s" % (d, f)] = _md5(fp)
    return s


def cmd_postavit(args):
    pdir = _pdir(args.project)
    p = os.path.join(pdir, FAIL_FILE)
    if os.path.exists(p) and not args.perezapisat:
        print("заморозка уже стоит — ничего не меняю")
        return 0
    data = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "snimok": _snimok(pdir)}
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("УТВЕРЖДЕНО И ЗАМОРОЖЕНО в %s: кадров %d. Дальше правки запрещены."
          % (data["ts"], len(data["snimok"]["kadry"])))
    return 0


def cmd_check(args):
    """0 — работать можно; 1 — проект заморожен и состав изменён."""
    pdir = _pdir(args.project)
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
    p = os.path.join(pdir, FAIL_FILE)
    if os.path.exists(p):
        os.remove(p)
        print("заморозка снята по слову пользователя")
    else:
        print("заморозки и не было")
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
