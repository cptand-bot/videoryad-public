#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""БАТЧ-ДВЕРЬ КЛЮЧЕЙ КАРТОЧЕК — один вход на весь комплект.

Улов 93 и 93-А (14.11, вкладка `usuario-b2`, цена — ЧЕТЫРЕ захода к агенту
на один ролик). Путь был такой: `kartochki_srazu --naznachennye --stavit`
вывел ключи из текста для 7 карточек из 56, а остальные вкладка заказывала у
агента — и он раз за разом возвращал то, чего у вида нет:

  * плюральные имена вместо флагов: `--repliki`, `--pary`, `--tezisy`,
    `--soobshcheniya`, `--rows` (у `card_put` флаги одиночные: `--replika`,
    `--para`, `--tezis`, `--soobshchenie`, `--row`). Такой вызов argparse
    отбивает целиком — «unrecognized arguments», карточка не встаёт;
  * ЧУЖИЕ содержательные ключи: `--row` виду, у которого рядов не бывает;
  * ВЫДУМАННЫЕ пути: `--photo images/022.jpg`, `--shot images/043.jpg` —
    это кадры СЦЕН (их правило 12.11 внутрь карточки не пускает), и вдобавок
    таких файлов на диске нет.

Заходами это не лечится: вкладка трижды цитировала агенту его же подсказку, и
трижды получала те же ключи. Поэтому фильтрация переехала из обвязки вкладки
в КОД — одна дверь принимает список `{id, view, args}` как есть, сама
приводит имена к флагам двери, выбрасывает чужое и выдуманное, добирает
обязательное из текста той же сцены и ставит карточку.

    python3 template/kartochki_batch.py <ролик>.scenes.json --zadanie ответ.json
    python3 template/kartochki_batch.py <ролик>.scenes.json --zadanie - --stavit
    cat ответ.json | python3 … --zadanie - --stavit --otpravit

Без `--stavit` печатается только разбор (что встанет, что отброшено, чего не
хватает) — ничего не пишется. Формат задания терпимый, у агента он гуляет:

    [{"id": 22, "view": "lenta", "args": {"--text": "…",
                                          "--soobshchenie": ["…", "…"]}}]
    [{"sid": 22, "вид": "lenta", "ключи": "--text «…» --soobshchenie «…»"}]

Код возврата: 0 — отказов нет; 1 — часть сцен не встала (их список в отчёте).
"""
import argparse
import importlib.util as _ilu
import json
import os
import re
import shlex
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_PUT = os.path.join(SKILL, "fullcycle", "card_put.py")
CARDS_CLOUD = os.path.join(SKILL, "fullcycle", "cards_cloud.py")
SRAZU = os.path.join(SKILL, "template", "kartochki_srazu.py")

# Ключи-РАМКА: подпись, кикер, первоисточник, должность, автор. Они не
# принадлежат ни одному виду и у любого вида безвредны — их не трогаем.
РАМКА = {"text", "title", "source", "kick", "role", "author", "accent",
         "watermark", "anim", "tail_zoom", "force", "dry_run", "images"}

# Флаги, в которых стоит ПУТЬ К ФАЙЛУ, — их проверяем диском (улов 93-А).
ПУТЕВЫЕ = {"--photo", "--shot", "--a-photo", "--b-photo", "--photo-b"}


def _modul(path):
    sp = _ilu.spec_from_file_location("_m_" + os.path.basename(path), path)
    m = _ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _vidy():
    """Таблица видов `card_put`: вид → список обязательных ключей (dest)."""
    try:
        return dict(getattr(_modul(CARD_PUT), "VIEWS", {}) or {})
    except Exception:
        return {}


def _dver(вид):
    """Дверь вида — та же логика, что у `kartochki_srazu` (не дублируем)."""
    try:
        return _modul(SRAZU)._dver_vida(вид)
    except Exception:
        return CARD_PUT


def _vyzovy(текст):
    """Куски исходника двери: содержимое каждого `add_argument(...)`.

    Считаем скобки, а не ловим регуляркой до конца строки: в `card_put`
    два вызова стоят в одной строке (`--top-who`; `--top-text`), а другие
    растянуты на пять строк — регулярка склеивала их в один и теряла `dest`.
    """
    out = []
    for м in re.finditer(r"add_argument\(", текст):
        i, глубина = м.end(), 1
        while i < len(текст) and глубина:
            if текст[i] == "(":
                глубина += 1
            elif текст[i] == ")":
                глубина -= 1
            i += 1
        out.append(текст[м.end():i - 1])
    return out


def _flagi(дверь):
    """Что дверь принимает: {флаг}, {чужое имя → флаг}, {флаг → dest}, append.

    Читается из САМОГО исходника двери, а не из списка в этом файле: иначе
    новый ключ двери молча стал бы «чужим» и выбрасывался. Это тот же урок,
    что с видами эффектов — список в двух местах расходится.
    Плюс замечание `usuario-b2` 14.11: у части видов ключ «динамический»
    (`--repliki` у вида `repliki`) и в `--help` его нет вовсе — поэтому
    берём и dest-имена, они и есть то, чем зовёт агент.
    """
    флаги, алиасы, dest_po_flagu, многократные = set(), {}, {}, set()
    try:
        текст = open(дверь, encoding="utf-8").read()
    except OSError:
        return флаги, алиасы, dest_po_flagu, многократные
    for вызов in _vyzovy(текст):
        имена = re.findall(r'"(--[a-z0-9][a-z0-9-]*)"', вызов)
        if not имена:
            continue
        флаги.update(имена)
        м = re.search(r'dest="([a-z0-9_]+)"', вызов)
        dest = м.group(1) if м else имена[0][2:].replace("-", "_")
        for ф in имена:
            dest_po_flagu[ф] = dest
            if 'action="append"' in вызов:
                многократные.add(ф)
        # Агент зовёт ключ ИМЕНЕМ ПОЛЯ, а не флагом: `--repliki` вместо
        # `--replika`. Алиас строится сам из `dest=` — ровно те пять случаев,
        # на которых сгорели три захода 14.11.
        for вариант in ("--" + dest, "--" + dest.replace("_", "-")):
            if вариант not in флаги:
                алиасы.setdefault(вариант, имена[0])
    return флаги, алиасы, dest_po_flagu, многократные


def _klyuchi_iz_teksta(вид, текст):
    """Ключи, которые выводятся из текста сцены (`kartochki_srazu._klyuchi`).

    Нужно для «подставляет обязательные»: если агент забыл `--value` или
    `--na-polu`, добирать их из текста ЭТОЙ ЖЕ сцены законно — числа и
    фамилии при этом не выдумываются, они берутся из реплики.
    """
    try:
        m = _modul(SRAZU)
        фраза = m._fraza_pod_vid(вид, текст) or m._fraza(текст)
        return m._klyuchi(вид, фраза, текст) or []
    except Exception:
        return []


КАВЫЧКИ = "«»\u201c\u201d\u201e\u201f\"\u2018\u2019"


def _bez_kavychek(зн):
    """Снять кавычки агента: он пишет `--author «Сергей Рябков»`.

    `shlex` ёлочки за кавычки не считает — значение рвалось по пробелу, и
    гейт имени видел ««Сергей» вместо «Сергей Рябков» (поймано живьём
    14.11 на пробе батч-двери).
    """
    т = str(зн).strip()
    while т[:1] in КАВЫЧКИ:
        т = т[1:]
    while т[-1:] in КАВЫЧКИ:
        т = т[:-1]
    return т.strip()


def _tokeny(стр):
    """Разбор строки ключей с уважением к ёлочкам: «…» — один токен."""
    out, буфер, внутри = [], "", False
    for ч in стр:
        if ч == "\u00ab":
            внутри, буфер = True, буфер
            continue
        if ч == "\u00bb":
            внутри = False
            continue
        if ч.isspace() and not внутри:
            if буфер:
                out.append(буфер)
                буфер = ""
            continue
        буфер += ч
    if буфер:
        out.append(буфер)
    return out


def _podognat_frazu(вид, фраза, текст_сцены=""):
    """Фраза под ёмкость вида. Возвращает (фраза, правилась, беда).

    `card_put` отбивает «текст не влезает в вид: 5 строк при 2» — отказ
    законный, но заходом к агенту он не лечится: вид ёмкостью две строки
    физически не возьмёт абзац. Логика подгонки уже есть в
    `kartochki_srazu._fraza_pod_vid` (мерит ШРИФТОМ, а не знаками), здесь
    она применяется к тексту АГЕНТА, а не к выбранному нами.

    ОБРЫВОК МОЛЧА НЕ СТАВИМ (его слово 14.11, поймал трижды за час:
    «Ответ из Европы уже начинает»): если целой мысли не выходит ни из
    фразы агента, ни из текста сцены, вид отдаётся вкладке — это
    самоотвод, а не обрезка.
    """
    try:
        m = _modul(SRAZU)
    except Exception:
        return фраза, False, ""
    for источник in (фраза, текст_сцены):
        if not str(источник or "").strip():
            continue
        try:
            подогнанная = m._fraza_pod_vid(вид, источник)
        except Exception:
            return фраза, False, ""
        if подогнанная and подогнанная.strip():
            п = подогнанная.strip()
            if п == фраза.strip():
                return фраза, False, ""
            return п, True, ""
    return фраза, False, ("фраза не влезает в вид «%s», а целой мысли из "
                          "текста сцены не выходит — вид ставит вкладка "
                          "своей формулировкой" % вид)


def _pary_klyuchey(argv):
    """Разбор готовой командной строки в {флаг: [значения]}."""
    out, i = {}, 0
    while i < len(argv):
        т = argv[i]
        if not т.startswith("--"):
            i += 1
            continue
        if "=" in т:
            ф, зн = т.split("=", 1)
            out.setdefault(ф, []).append(_bez_kavychek(зн))
            i += 1
            continue
        зн = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else ""
        out.setdefault(т, []).append(_bez_kavychek(зн) if зн else зн)
        i += 2 if зн else 1
    return out


def _args_zapisi(запись):
    """Ключи записи в виде {флаг: [значения]} — формат у агента гуляет."""
    сыро = None
    for к in ("args", "klyuchi", "ключи", "keys", "cmd", "command", "команда"):
        if к in запись:
            сыро = запись[к]
            break
    if сыро is None:
        # Ключи разложены прямо в записи: {"id":…, "view":…, "--text":…}
        сыро = {к: v for к, v in запись.items() if str(к).startswith("--")}
    if isinstance(сыро, str):
        стр = сыро
        # В строке может стоять и сама команда — хвост после имени вида.
        стр = re.sub(r"^.*?card_put\.py\s+\S+\s+\d+\s+\S+\s*", "", стр)
        return _pary_klyuchey(_tokeny(стр))
    if isinstance(сыро, list):
        return _pary_klyuchey([str(x) for x in сыро])
    if isinstance(сыро, dict):
        out = {}
        for к, v in сыро.items():
            ф = str(к)
            if not ф.startswith("--"):
                ф = "--" + ф.strip("-").replace("_", "-")
            зн = v if isinstance(v, list) else [v]
            out[ф] = ["" if x is None else _bez_kavychek(x) for x in зн]
        return out
    return {}


def _zapisi(задание):
    """Список записей из ответа агента — хоть списком, хоть словарём."""
    if isinstance(задание, dict):
        for к in ("cards", "карточки", "scenes", "сцены", "items", "list"):
            if isinstance(задание.get(к), list):
                задание = задание[к]
                break
        else:
            задание = [задание]
    out = []
    for з in задание or []:
        if not isinstance(з, dict):
            continue
        ном = None
        for к in ("id", "sid", "scene", "сцена", "номер", "no", "n"):
            if з.get(к) not in (None, ""):
                try:
                    ном = int(str(з[к]).strip().lstrip("0") or "0")
                except ValueError:
                    ном = None
                break
        вид = ""
        for к in ("view", "vid", "вид", "kind", "card", "карточка"):
            if з.get(к):
                вид = str(з[к]).strip()
                break
        if вид.startswith("card:"):
            вид = вид[len("card:"):].strip()
        if ном and вид:
            out.append((ном, вид, _args_zapisi(з)))
    return out


def _tekst_sceny(scenes, ном):
    try:
        d = json.load(open(scenes, encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    сц = d.get("scenes", d) if isinstance(d, dict) else d
    for i, s in enumerate(сц, 1):
        н = s.get("id") or s.get("sid") or i
        try:
            н = int(str(н).lstrip("0") or "0")
        except ValueError:
            н = i
        if н == ном:
            return (s.get("text") or s.get("текст") or "").strip()
    return ""


def _proverit_put(флаг, значение, корень):
    """Путь на диске и ВНЕ `images/` — иначе это выдумка или кадр сцены.

    Формат `путь.jpg=подпись` у `--shot` сохраняем: проверяем только путь.
    """
    путь = значение.split("=", 1)[0].strip()
    if not путь:
        return None, "пустой путь"
    полн = путь if os.path.isabs(путь) else os.path.join(корень, путь)
    if not os.path.exists(полн):
        return None, "такого файла нет на диске: %s" % путь
    низ = os.path.basename(путь)
    в_images = (os.sep + "images" + os.sep) in os.path.abspath(полн) + os.sep
    if в_images or re.match(r"^scene_?\d{2,3}\.", низ):
        return None, ("это кадр СЦЕНЫ (%s) — правило 12.11 внутрь карточки "
                      "его не пускает" % низ)
    return значение, ""


def _sobrat(ном, вид, ключи, scenes, корень, виды):
    """Разбор одной записи: (argv, что отброшено, причина отказа, замечания)."""
    дверь = _dver(вид) or CARD_PUT
    флаги, алиасы, dest_po_flagu, многократные = _flagi(дверь)
    обязательные = list((виды.get(вид) or ([],))[0]) if вид in виды else []
    свои = set(обязательные)
    # Содержательные ключи ДРУГИХ видов — то, что агент подставляет чаще
    # всего. Рамка (подпись, кикер, источник) чужой не бывает.
    чужие = _soderzhatelnye(виды) - РАМКА - свои

    argv, отброшено, замечания, стоит = [], [], [], set()
    for флаг, значения in ключи.items():
        ф = флаг if флаг in флаги else алиасы.get(флаг, "")
        if not ф:
            отброшено.append("%s — у двери %s такого ключа нет"
                             % (флаг, os.path.basename(дверь)))
            continue
        dest = dest_po_flagu.get(ф, ф[2:].replace("-", "_"))
        if dest in чужие:
            отброшено.append("%s — ключ ЧУЖОГО вида (виду «%s» он не нужен)"
                             % (флаг, вид))
            continue
        взято = 0
        for зн in (значения if ф in многократные else значения[:1]):
            if ф in ПУТЕВЫЕ:
                годный, беда = _proverit_put(ф, str(зн), корень)
                if годный is None:
                    отброшено.append("%s %s — %s" % (ф, зн, беда))
                    continue
                зн = годный
            зн = str(зн)
            if dest == "text":
                зн, правилась, беда_текста = _podognat_frazu(
                    вид, зн, _tekst_sceny(scenes, ном))
                if беда_текста:
                    return argv, отброшено, беда_текста, замечания
                if правилась:
                    замечания.append("--text подогнан под ёмкость вида «%s» "
                                     "(иначе дверь отбила бы «не влезает»)" % вид)
            argv += [ф, зн]
            взято += 1
        if взято:
            стоит.add(dest)
        # ЛИСТ ИЗ ОДНОЙ СТРОКИ ИНСТРУМЕНТ СЧИТАЕТ ПУСТЫМ (замечание
        # `usuario-b2` 14.11, проверено на живом ролике): просить у агента
        # 3-6 строк, а не одну фразу. Это замечание, а не отказ.
        if dest == "text" and взято and len(str(значения[0])) < 90 \
                and not any("подогнан" in з for з in замечания):
            замечания.append("--text короче 90 знаков (%d) — лист выйдет "
                             "пустым, проси у агента 3-6 строк"
                             % len(str(значения[0])))

    # ── ДОБОР ОБЯЗАТЕЛЬНОГО ИЗ ТЕКСТА ТОЙ ЖЕ СЦЕНЫ ──
    нехватка = [к for к in обязательные if к not in стоит]
    if нехватка:
        текст = _tekst_sceny(scenes, ном)
        добор = _pary_klyuchey(_klyuchi_iz_teksta(вид, текст)) if текст else {}
        for ф, зн in добор.items():
            d = dest_po_flagu.get(ф, ф[2:].replace("-", "_"))
            if d not in нехватка:
                continue
            for v in (зн if ф in многократные else зн[:1]):
                argv += [ф, v]
            нехватка.remove(d)
            замечания.append("%s добран из текста сцены" % ф)
    if нехватка:
        return argv, отброшено, ("не хватает обязательного: %s — из текста "
                                 "сцены не выводится" % ", ".join(нехватка)), замечания
    return argv, отброшено, "", замечания


def _soderzhatelnye(виды):
    """Все содержательные ключи таблицы видов (dest-имена)."""
    out = set()
    for v in виды.values():
        треб = v[0] if v and isinstance(v[0], (list, tuple)) else []
        out.update(треб)
    return out


def _uzhe_stoit(корень, ном):
    """Задание уже в `cards/queue` — `card_put` его НЕ перезаписывает.

    Замечание `usuario-b2` 14.11: чтобы добавить фото к готовой карточке,
    ей пришлось править `cards/queue/scene_014.json` руками. Поэтому дверь
    не делает вид, что поставила: говорит прямо, что задание уже есть.
    """
    return os.path.isfile(os.path.join(корень, "cards", "queue",
                                       "scene_%03d.json" % ном))


def main():
    ap = argparse.ArgumentParser(
        description="батч-дверь: список карточек от агента → поставленные сцены")
    ap.add_argument("scenes")
    ap.add_argument("--zadanie", required=True,
                    help="файл с ответом агента (json) или «-» для stdin")
    ap.add_argument("--stavit", action="store_true",
                    help="поставить; без него только разбор")
    ap.add_argument("--otpravit", action="store_true",
                    help="после постановки отправить рисовку в облако")
    ap.add_argument("--force", action="store_true",
                    help="передать --force двери (плотность и повтор)")
    a = ap.parse_args()

    if not os.path.isfile(a.scenes):
        raise SystemExit("нет файла сцен: %s" % a.scenes)
    корень = os.path.dirname(os.path.abspath(a.scenes)) or "."
    сыро = sys.stdin.read() if a.zadanie == "-" else open(
        a.zadanie, encoding="utf-8").read()
    # Агент любит обернуть ответ в ```json — снимаем, это не ошибка задания.
    м = re.search(r"```(?:json)?\s*(.+?)```", сыро, re.S)
    if м:
        сыро = м.group(1)
    try:
        задание = json.loads(сыро)
    except ValueError as e:
        raise SystemExit("задание не читается как json: %s" % e)

    записи = _zapisi(задание)
    if not записи:
        raise SystemExit("в задании нет ни одной записи вида {id, view, args}")
    виды = _vidy()
    print("В ЗАДАНИИ КАРТОЧЕК: %d" % len(записи))

    план, самоотводы, уже = [], [], []
    for ном, вид, ключи in записи:
        if виды and вид not in виды and not _dver(вид):
            самоотводы.append((ном, вид, "такого вида нет ни у одной двери"))
            continue
        if _uzhe_stoit(корень, ном):
            уже.append((ном, вид))
            continue
        argv, отброшено, беда, замечания = _sobrat(
            ном, вид, ключи, a.scenes, корень, виды)
        for о in отброшено:
            print("  отброшено:  сцена %-3d %s" % (ном, о))
        for з in замечания:
            print("  замечание:  сцена %-3d %s" % (ном, з))
        if беда:
            самоотводы.append((ном, вид, беда))
            continue
        план.append((ном, вид, argv))

    if уже:
        print("\nзадание уже лежит в cards/queue (%d) — `card_put` его НЕ "
              "перезапишет:" % len(уже))
        print("  " + " · ".join("%d %s" % (н, в) for н, в in уже))
    print("\nготово к постановке: %d · самоотвод: %d"
          % (len(план), len(самоотводы)))
    for ном, вид, беда in самоотводы:
        print("  [САМООТВОД] сцена %-3d %-16s %s" % (ном, вид, беда))
    if not a.stavit:
        print("\nничего не поставлено (нужен ключ --stavit)")
        return 0

    поставлено, отказы = 0, []
    for ном, вид, argv in план:
        дверь = _dver(вид) or CARD_PUT
        кмд = [sys.executable, дверь, a.scenes, str(ном), вид] + argv
        if a.force:
            кмд.append("--force")
        r = subprocess.run(кмд, capture_output=True, text=True, cwd=корень)
        if r.returncode == 0:
            поставлено += 1
            print("  [ОК]    сцена %-3d → %s" % (ном, вид))
        else:
            хвост = [с for с in (r.stderr or r.stdout or "").splitlines() if с.strip()]
            отказы.append((ном, вид, хвост[0] if хвост else "код %d" % r.returncode))

    print("\nпоставлено карточек: %d из %d" % (поставлено, len(план)))
    for ном, вид, беда in отказы:
        print("  [ОТКАЗ] сцена %-3d %-16s %s" % (ном, вид, беда))
    if a.otpravit and поставлено:
        print("\nотправляю рисовку в облако:")
        subprocess.run([sys.executable, CARDS_CLOUD], cwd=корень)
    return 0 if not отказы and not самоотводы else 1


if __name__ == "__main__":
    sys.exit(main())
