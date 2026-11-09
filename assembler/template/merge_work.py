#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_work.py — забор НЕ ОТКАТЫВАЕТ правки в рабочих файлах ролика.

Зачем (09.11, улов агента на `5min-porazhenie-1011`): `get.sh` вернул
`overlays.json` из облачной копии и затёр перенос всплывашки со сцены 65 на
66, сделанный МЕЖДУ кругами правок. Поймал это только `selfcheck`
(«одинаковый файл в scene_065 и scene_066»).

ПОЧЕМУ ЗАЩИТА 08.11 НЕ СРАБОТАЛА — она мерила не то. Код сравнивал
`stat -c%Y` нашей копии с `stat -c%Y` файла из релиза и возвращал наш,
только если он НОВЕЕ. Но `overlays.json` и `*.scenes.json` облако
ПЕРЕПИСЫВАЕТ в ходе прогона (`merge_shards` вписывает в сцены пути к
привезённым кадрам), и файл приезжает с отметкой времени ПРОГОНА. Замер по
трём заборам 08-09.11:

    ролик                 отправка    отметка overlays.json из облака
    planeta-rasplata-0911 15:05:00    15:11:56   (+6 м 56 с)
    ssha-evropa-0911      12:01:43    12:06:30   (+4 м 47 с)
    psd-ritorika-0911     20:42:10    20:47:49   (+5 м 39 с)

То есть ЛЮБАЯ правка, сделанная в эти пять-семь минут — ровно когда вкладка
и работает, пока идёт фетч, — имеет отметку МЕНЬШЕ облачной и проигрывает.
Тот же класс, что «порог 20 КБ против заглушки 33 КБ»: защита стояла,
но признак был чужой.

Чего стоит облачная копия в деле (промер `planeta-rasplata-0911`): ключей
локально 16, в облаке 14 — две всплывашки в облаке отсутствуют ВООБЩЕ;
из 14 общих записей отличаются 14, и отличия — это `approved` (решения
вкладки на дашборде), `anchor`, `shape` и `text` (его в публичном режиме
вычищают). Новых ключей облако не приносит НИ ОДНОГО. То есть облачная
версия этого файла строго беднее нашей, и «вернуть её» — всегда потеря.

ПРАВИЛО: наше побеждает, облачное может только ДОБАВИТЬ то, чего у нас нет.
  * ключ (всплывашка, сцена) есть у нас → остаётся наш;
  * ключа у нас нет, а в облаке есть → НЕ возвращаем (это снятая вкладкой
    всплывашка; её возврат и был бы молчаливым откатом), но говорим вслух
    и кладём облачный файл рядом;
  * поле внутри записи есть в облаке и нет у нас → добавляем (так приезжают
    пути к привезённым файлам);
  * поле есть у обоих и разное → наше, и это РАСХОЖДЕНИЕ, о нём строка;
  * исключение по содержимому, а не по времени: если поле — ПУТЬ, нашего
    файла на диске нет, а облачный есть, берём облачный (так лечится
    «всплывашка приехала .mp4 вместо .jpg»).

Чисто наши файлы (`tg*.json`, `links*.txt`, `fx.json`, `rejections.jsonl`,
`.library_usage.json`, `*.autofix.json`) облако не правит вовсе — для них
просто возвращаем наши. `needs_upload.json`, `progress.json` и `_cloud/*`
наоборот ОБЛАЧНЫЕ (их пишет `merge_shards`), их не трогаем.

Использование:
    python3 merge_work.py <папка забора> --keep <папка копий> [--work <папка>]

Код возврата всегда 0: это страховка, а не гейт.
"""
import glob
import json
import os
import shutil
import sys

ПУТИ = {"photo", "file", "video", "clip", "src", "image", "poster"}
# облако их пишет само — наши копии поверх кладать нельзя
ОБЛАЧНЫЕ = {"needs_upload.json", "progress.json", "manifest.json"}
# чисто наши, облако их не правит
НАШИ = ("tg.json", "tg_fresh.json", "tg_rejected.json", "tg_claims.json",
        "tg_source.json", "fx.json", "rejections.jsonl",
        ".library_usage.json", "links.txt")


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(p, data):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _zhiv(dest, v):
    """Путь из поля указывает на существующий файл?"""
    if not isinstance(v, str) or not v:
        return False
    return os.path.exists(os.path.join(dest, v)) or os.path.exists(v)


def _merge_rec(dest, loc, cld):
    """Одна запись: наше побеждает, облачное добавляет недостающее."""
    out = dict(loc)
    added, fixed, conf = [], [], []
    for f, cv in (cld or {}).items():
        if f not in loc:
            out[f] = cv
            added.append(f)
        elif loc[f] != cv:
            if f in ПУТИ and not _zhiv(dest, loc[f]) and _zhiv(dest, cv):
                out[f] = cv
                fixed.append(f)
            else:
                conf.append(f)
    return out, added, fixed, conf


def _merge_dict(dest, loc, cld):
    """overlays.json: плоский словарь, ключи — номера сцен и скаляры."""
    out = dict(loc)
    added_f, fixed_f, conf_k, only_cloud = 0, [], [], []
    for k, cv in (cld or {}).items():
        if k not in loc:
            only_cloud.append(k)
            continue
        if isinstance(loc[k], dict) and isinstance(cv, dict):
            rec, a, fx, cf = _merge_rec(dest, loc[k], cv)
            out[k] = rec
            added_f += len(a)
            fixed_f += [(k, f) for f in fx]
            if cf:
                conf_k.append((k, cf))
        elif loc[k] != cv:
            conf_k.append((k, ["значение"]))
    return out, added_f, fixed_f, conf_k, only_cloud


def _merge_scenes(dest, loc, cld):
    """*.scenes.json: {"scenes": [...]} плюс скаляры верхнего уровня."""
    out = dict(loc)
    ls = {int(s["id"]): s for s in (loc.get("scenes") or []) if "id" in s}
    cs = {int(s["id"]): s for s in ((cld or {}).get("scenes") or [])
          if "id" in s}
    added_f, fixed_f, conf_k = 0, [], []
    scenes = []
    for s in (loc.get("scenes") or []):
        try:
            i = int(s["id"])
        except (KeyError, TypeError, ValueError):
            scenes.append(s)
            continue
        if i in cs:
            rec, a, fx, cf = _merge_rec(dest, s, cs[i])
            scenes.append(rec)
            added_f += len(a)
            fixed_f += [(i, f) for f in fx]
            if cf:
                conf_k.append((i, cf))
        else:
            scenes.append(s)
    out["scenes"] = scenes
    only_cloud = sorted(set(cs) - set(ls))
    for k, cv in (cld or {}).items():
        if k != "scenes" and k not in out:
            out[k] = cv
            added_f += 1
    return out, added_f, fixed_f, conf_k, only_cloud


def _park(dest, name):
    src = os.path.join(dest, name)
    dst = os.path.join(dest, name + ".iz_oblaka")
    try:
        shutil.copy2(src, dst)
        return os.path.basename(dst)
    except OSError:
        return ""


def one(dest, keep, name, scenes_mode):
    loc = _load(os.path.join(keep, name))
    cld_path = os.path.join(dest, name)
    cld = _load(cld_path)
    if loc is None:
        return 0                     # нашей копии нет — брать нечего
    if cld is None:
        _save(cld_path, loc)
        print("  вернул %s (в релизе его нет или он битый)" % name)
        return 0
    parked = ""
    if scenes_mode:
        out, added, fixed, conf, only_cloud = _merge_scenes(dest, loc, cld)
    else:
        out, added, fixed, conf, only_cloud = _merge_dict(dest, loc, cld)
    if conf or only_cloud:
        parked = _park(dest, name)
    _save(cld_path, out)

    било = []
    if added:
        било.append("из облака добавлено полей: %d (так приезжают пути к "
                    "привезённым файлам)" % added)
    if fixed:
        било.append("мёртвых путей вылечено облачными: %d (%s)"
                    % (len(fixed), ", ".join("%s/%s" % (k, f)
                                             for k, f in fixed[:4])))
    if било:
        print("  %s: %s" % (name, "; ".join(било)))
    if conf:
        print("  !! %s: ТВОИ ПРАВКИ СОХРАНЕНЫ, облачные значения отброшены —"
              % name)
        for k, fl in conf[:8]:
            print("     запись %s: расхождение в %s" % (k, ", ".join(fl)))
        if len(conf) > 8:
            print("     … и ещё %d записей" % (len(conf) - 8))
    if only_cloud:
        print("  !! %s: в облачной копии есть записи, которых у тебя НЕТ: %s"
              % (name, ", ".join(str(x) for x in only_cloud[:10])))
        print("     Не возвращаю: обычно это снятое тобой между кругами, и"
              " возврат был бы молчаливым откатом.")
    if parked:
        print("     твой файл оставлен, облачный лежит рядом: %s — сверь сама"
              % parked)
    return 0


def main(argv):
    def opt(n):
        if n in argv:
            k = argv.index(n)
            return argv[k + 1] if k + 1 < len(argv) else ""
        return ""

    pos = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--keep", "--work"):
            i += 2
            continue
        if not a.startswith("--"):
            pos.append(a)
        i += 1
    if not pos:
        print(__doc__)
        return 0
    dest, keep, work = pos[0], opt("--keep"), opt("--work")
    if not os.path.isdir(dest):
        return 0
    if keep and os.path.isdir(keep):
        one(dest, keep, "overlays.json", False)
        for p in sorted(glob.glob(os.path.join(keep, "*.scenes.json"))):
            b = os.path.basename(p)
            if b.endswith("_fetch.scenes.json"):
                continue
            one(dest, keep, b, True)
        # ЧИСТО НАШИ ФАЙЛЫ: облако их не правит, а распаковка архива кладёт
        # поверх СВОЮ (отправленную) копию — то есть откатывает всё, что
        # вкладка сделала после ship. Возвращаем без разговоров.
        # `*_fetch.scenes.json` сюда же: это ЗАДАНИЕ на всплывашки, облако
        # его только читает (проверено грепом по `cloud/*.py`), а правит его
        # вкладка на дашборде — ровно между кругами.
        свои = list(НАШИ) + [os.path.basename(x) for x in
                             glob.glob(os.path.join(keep, "*_fetch.scenes.json"))]
        вернул = []
        for b in свои:
            s = os.path.join(keep, b)
            d = os.path.join(dest, b)
            if not os.path.isfile(s):
                continue
            try:
                if os.path.isfile(d) and os.path.getsize(s) == os.path.getsize(d) \
                        and open(s, "rb").read() == open(d, "rb").read():
                    continue
            except OSError:
                pass
            try:
                shutil.copy2(s, d)
                вернул.append(b)
            except OSError:
                pass
        if вернул:
            print("  вернул наши рабочие файлы (облако их не правит): %s"
                  % ", ".join(вернул))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
