#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МАТЕРИАЛ ДОСЬЕ ДОЛЖЕН БЫТЬ В РОЛИКЕ, А НЕ В ФАЙЛЕ `tg.json`.

    dossier_use.py <scenes.json> [overlays.json …] [--tg tg.json] [--strict]

Строжайшее правило пользователя (31.10, сказано трижды за десять минут):
«То, что отдаётся георадаром, по возможности ВСЁ вставлять, что можно. Всё
использовать. Фотографии, видео, которые там вставляются. Для чего они тогда
нужны, если их не вставлять? Искать какую-то срань?»

Поэтому порядок источников в ролике такой, и он не обсуждается:
  1. материал досье (вложения постов георадара) — СНАЧАЛА;
  2. медиатека и база кадров;
  3. поиск — ТОЛЬКО то, что не закрыли первые два.

Скрипт сверяет `tg.json` (выдачу `tg_media.py`) со сценарием и говорит, что из
присланного пользователем осталось лежать без дела. Неиспользованный материал
при живых сценах из ПОИСКА — отказ: значит ролик ищет то, что уже лежит рядом.

Ширина кадра поводом НЕ является: узкий кадр ставится в родном размере по
центру с размытой заливкой полей (правило 30.10). Карты из постов идут в сцены
первым делом — карта источника это информация, а не «кадр 800 px».

КАДР ДОСЬЕ ВНУТРИ РИСОВАННОГО КАДРА — ПОСТАВЛЕННЫЙ (09.11, улов вкладки
`usuario-2c` на ролике `planeta-ukraina-forma-1011`). Фото Умерова из вложений
стояло в газетной вырезке на сцене 11, но источник сцены стал `card:vyrezka`:
адрес вложения из сцены ушёл (у карточек он один на всех, `_CARD_QUERY`), путь
к фото уехал в поле `card`, а сам файл — в `cards/photo/` под своим именем.
Гейт объявил кадр «лежащим без дела при живых поисковых сценах» и ОТКАЗАЛ в
фетче. Вкладка обошла это записью в `tg_rejected.json` «использован внутри
карточки» — то есть ГОДНЫЙ кадр пошёл в брак, чего быть не должно.
Поэтому сверяем не только адреса и имена, но и СОДЕРЖИМОЕ: md5 файла досье
против md5 всего, что стоит в ролике, включая исходные фото рисованных кадров
(`cards/photo/`, `cards/replaced/`, медиатека — путь берётся из задания
карточки, а не из списка папок по памяти). Имя тут не помощник: кадр приезжает
под именем вложения, а в карточку копируется под своим.
"""
import ast
import glob
import hashlib
import json
import os
import re
import sys

SEARCH = ("press_photo", "web_search", "wikimedia",
          "pexels_photo", "pexels_video", "pexels")

# РАЗБОР ЗАДАНИЙ КАРТОЧЕК БЕРЁМ ГОТОВЫЙ, А НЕ ПИШЕМ ВТОРОЙ (09.11): путь к
# фото лежит в трёх местах (`cards/queue/`, `cards/cards.json`, поле `card`
# сцены) и у каждого вида свой ключ — `photo`, `hero_photo`, `shots`. Это
# ровно тот список, который забывают по памяти, поэтому зовём
# `povtor_kadrov.карточные_фото()`: он обходит задание целиком.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from povtor_kadrov import карточные_фото
except ImportError:
    карточные_фото = None


def _md5(path):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for кусок in iter(lambda: f.read(1 << 20), b""):
                h.update(кусок)
    except OSError:
        return None
    return h.hexdigest()


def в_ролике_по_md5(here):
    """md5 → где этот файл стоит в ролике, человеческими словами.

    Пережатая копия тем же md5 не будет — поэтому это ДОБАВКА к сверке по
    адресу и имени, а не замена: видео досье приезжает в сцену обрезанным и
    опознаётся по-прежнему по адресу.
    """
    где = {}
    def добавить(path, что):
        try:
            if not os.path.isfile(path) or os.path.getsize(path) < 1024:
                return
        except OSError:
            return
        m = _md5(path)
        if m:
            где.setdefault(m, []).append(что)

    for d, что in (("images", "кадром сцены"), ("overlays", "всплывашкой"),
                   ("insets", "врезкой")):
        for f in sorted(glob.glob(os.path.join(here, d, "*"))):
            добавить(f, "%s (%s)" % (что, os.path.basename(f)))
    if карточные_фото is None:
        print("!! фото ВНУТРИ рисованных кадров не проверены: рядом нет "
              "povtor_kadrov.py")
        return где
    for ap, места in sorted(карточные_фото(here).items()):
        for sid, элемент in места:
            добавить(ap, "внутри рисованного кадра «%s» на сцене %s (%s)"
                     % (элемент, sid, os.path.basename(ap)))
    return где


def местные_копии(here):
    """Имя файла → путь: где на диске лежит скачанное вложение."""
    out = []
    for d in ("dossier", "images", "overlays", "insets", "clips",
              os.path.join("cards", "photo"), os.path.join("cards", "replaced")):
        for f in sorted(glob.glob(os.path.join(here, d, "*"))):
            if os.path.isfile(f):
                out.append((os.path.basename(f).lower(), f))
    return out


def _подсказки(m):
    """Под какими именами мог лечь на диск файл этого вложения.

    Рабочая подсказка одна — `канал_номер` из адреса поста
    (`t.me/OstashkoNews/228033` → `OstashkoNews_228033`): так вкладки и
    называют скачанное. Адрес файла в телеграме — трёхсотзначный токен, под
    таким именем файлов не бывает, но короткий огрызок (`3843e6786f.mp4`)
    встречается, поэтому берём и его.
    """
    out = []
    ч = re.search(r"t\.me/(?:s/)?([^/]+)/(\d+)", str(m.get("post") or ""))
    if ч:
        база = ("%s_%s" % (ч.group(1), ч.group(2))).lower()
        i = m.get("i")
        if i is not None:
            буква = "f" if m.get("kind") == "фото" else "v"
            out += ["%s_%s%d" % (база, буква, i),
                    "%s_ph%d" % (база, i), "%s_%d" % (база, i)]
        # БЕЗ НОМЕРА — ТОЛЬКО КОГДА ВЛОЖЕНИЕ В ПОСТЕ ОДНО: иначе подсказка
        # указывает на пост, а не на файл, и соседнее вложение зачлось бы
        # вместо этого.
        if int(m.get("n") or 0) <= 1:
            out.append(база)
    стем = os.path.splitext(os.path.basename(
        str(m["url"]).split("?")[0]))[0].lower()
    if 6 < len(стем) <= 40:
        out.append(стем)
    return out


def _urls(rec, key):
    v = rec.get(key) or []
    if isinstance(v, str):
        try:
            v = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            v = [v] if v.startswith("http") else []
    return [str(u) for u in v if str(u).startswith("http")]


def _notes(rec):
    v = rec.get("notes") or []
    if isinstance(v, str):
        try:
            v = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            v = [v]
    return [str(x) for x in v]


def load_tg(path):
    d = json.load(open(path, encoding="utf-8"))
    recs = d if isinstance(d, list) else (d.get("items") or d.get("posts") or [])
    out = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        post = str(r.get("url") or "")
        # НОМЕР ВЛОЖЕНИЯ В ПОСТЕ И ИХ ЧИСЛО нужны сверке по содержимому: имя
        # скачанного файла — `<канал>_<номер поста>_f0.jpg`, и без номера
        # вложения постер видео зачёлся бы «поставленным» только потому, что
        # в ролик ушло ДРУГОЕ вложение того же поста (поймано 09.11 на
        # `planeta-ukraina-forma-1011`, запись OstashkoNews/227780).
        _ф = _urls(r, "photos")
        _в = _urls(r, "videos")
        # РАЗМЕР И ПРИЗНАК ПОСТЕРА ЕДУТ ВМЕСТЕ С ФАЙЛОМ (11.11). `tg_media`
        # меряет их сам (`media_size`, `poster_size`, `video_posters`), а
        # гейт этих полей не читал — и требовал употребить постер 320x180,
        # который фетчер отклоняет на входе. См. `неприменим()`.
        _разм = dict(r.get("media_size") or {})
        _разм.update(dict(r.get("poster_size") or {}))
        _пост = set(r.get("video_posters") or [])
        for i, u in enumerate(_ф):
            out.append({"url": u, "post": post, "kind": "фото",
                        "notes": _notes(r), "i": i, "n": len(_ф),
                        "size": _разм.get(u, ""), "poster": u in _пост})
        for i, u in enumerate(_в):
            out.append({"url": u, "post": post, "kind": "видео",
                        "notes": _notes(r), "i": i, "n": len(_в),
                        "size": _разм.get(u, ""), "poster": False})
    return out


# ПОРОГИ ФЕТЧЕРА (`fetch_assets_news.py`): базовая сцена 500x320, всплывашка
# 300x200. Ниже них файл физически не встанет никуда — требовать его
# употребления значит держать фетч закрытым навсегда.
ПОРОГ_СЦЕНЫ = (500, 320)
ПОРОГ_ВСПЛЫВАШКИ = (300, 200)


def _wh(размер):
    m = re.match(r"^\s*(\d+)\s*[xх*]\s*(\d+)", str(размер or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def неприменим(m):
    """Почему этот файл в ролик не встанет НИКАК. Иначе None.

    11.11, улов смены: гейт требовал употребить ПОСТЕР видеопоста 320x179 —
    при пороге сцены 800 px и пороге фетчера 500x320 его отклоняет сам
    фетчер, и вкладка вписывала постер в `tg_rejected.json` руками на каждом
    ролике (живой пример — `planeta-3-merc-poslali-1211`). Неприменимое — не
    забытое: оно не идёт ни в «лежит без дела», ни в отказ, но и не
    прячется — его печатают отдельной строкой.
    Само ВИДЕО такого поста остаётся обычным материалом: содержание несёт
    оно, а постер — лишь его обложка.
    """
    w, h = _wh(m.get("size"))
    if not w:
        return None                       # размер не промерен — не судим
    if w < ПОРОГ_ВСПЛЫВАШКИ[0] or h < ПОРОГ_ВСПЛЫВАШКИ[1]:
        return ("%dx%d — ниже порога всплывашки %dx%d, фетчер отклонит"
                % (w, h, *ПОРОГ_ВСПЛЫВАШКИ))
    if m.get("poster") and (w < ПОРОГ_СЦЕНЫ[0] or h < ПОРОГ_СЦЕНЫ[1]):
        return ("постер видео %dx%d — ниже порога сцены %dx%d; содержание "
                "несёт само видео поста" % (w, h, *ПОРОГ_СЦЕНЫ))
    return None


def used_strings(paths):
    """Всё, что сценарий и всплывашки уже упоминают, одной кучей."""
    blob = []
    stats = {"direct_url": 0, "search": 0, "library": 0, "card": 0, "total": 0}
    for p in paths:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("!! не прочитать %s: %s" % (p, e))
            continue
        scenes = d.get("scenes", d) if isinstance(d, dict) else d
        # СЛОВАРНЫЙ ФОРМАТ `overlays.json` ТОЖЕ РАЗБИРАЕМ (05.11, улов
        # `usuario-9e`, стоил четырёх попыток). Боевой `overlays.json` — это
        # НЕ список сцен, а отображение `{"<sid>": {"photo": …}}`. Здесь он
        # молча отбрасывался (`not isinstance(list)` → `continue`), и гейт
        # держал «материал досье лежит без дела», хотя файл стоял всплывашкой.
        # Вкладка обходила дублированием записи внутрь сцены.
        if isinstance(scenes, dict):
            _flat = []
            for _k, _v in scenes.items():
                if not isinstance(_v, dict):
                    continue
                _e = dict(_v)
                _e.setdefault("source", "overlay")
                _flat.append(_e)
                # вложенные кусочки записи (text/photo/video) несут свои пути
                for _sub in ("text", "photo", "video", "overlay"):
                    _x = _v.get(_sub)
                    if isinstance(_x, dict):
                        _flat.append(_x)
            scenes = _flat
        if not isinstance(scenes, list):
            continue
        for s in scenes:
            if not isinstance(s, dict):
                continue
            src = str(s.get("source") or "")
            q = str(s.get("source_query") or "")
            blob.append(q)
            for k in ("file", "url", "asset", "path"):
                if s.get(k):
                    blob.append(str(s[k]))
            # ПОЛЕ `card` ЦЕЛИКОМ (09.11): у рисованной сцены путь к фото
            # лежит там — `photo`, `hero_photo`, `shots`. Перечислять ключи
            # нельзя (у каждого вида свои), поэтому в сверку идёт весь кусок
            # как текст: если кадр лёг под именем вложения, этого уже хватит.
            if isinstance(s.get("card"), dict):
                try:
                    blob.append(json.dumps(s["card"], ensure_ascii=False))
                except (TypeError, ValueError):
                    pass
            # ВСПЛЫВАШКИ ВНУТРИ СЦЕНЫ ТОЖЕ СЧИТАЮТСЯ (04.11, улов `usuario-af`
            # на «Газе»). Докстрока обещала «сценарий И ВСПЛЫВАШКИ», а
            # сканировался только уровень сцены — и два файла досье,
            # поставленные всплывашками в `scenes[].overlays` (формат из
            # задания раскадровки), гейт объявил «лежат без дела» при обоих
            # ПОСТАВЛЕННЫХ. Вкладка обходила переносом в
            # `overlays_fetch.scenes.json`. Класс тот же, что «поле в JSON ≠
            # файл, на который оно ссылается»: проверка смотрела не туда, где
            # лежит ответ.
            ovs = s.get("overlays")
            if isinstance(ovs, dict):
                ovs = [ovs]
            if isinstance(ovs, (list, tuple)):
                for ov in ovs:
                    if isinstance(ov, str):
                        blob.append(ov)
                        continue
                    if not isinstance(ov, dict):
                        continue
                    for k in ("photo", "file", "url", "asset", "path", "src",
                              "image", "query", "source_query"):
                        if ov.get(k):
                            blob.append(str(ov[k]))
                    _t = ov.get("text")
                    if isinstance(_t, dict):
                        for k in ("photo", "file", "url", "asset", "path"):
                            if _t.get(k):
                                blob.append(str(_t[k]))
            # записи словарного `overlays.json` в СЧЁТ СЦЕН не идут: это
            # всплывашки, их адреса нужны только для сверки с досье
            if src == "overlay":
                continue
            stats["total"] += 1
            if src == "direct_url":
                stats["direct_url"] += 1
            elif src.startswith("card"):
                stats["card"] += 1
            elif src == "local_library":
                stats["library"] += 1
            elif src in SEARCH:
                stats["search"] += 1
    return "\n".join(blob), stats


def load_rejected(where):
    """ЖУРНАЛ ОТКЛОНЁННОГО МАТЕРИАЛА ДОСЬЕ (31.10, предложение `usuario-b2`).

    Гейт не отличал «посмотрел и отклонил по дефекту или по теме» от «не
    смотрел». Живой случай: запись `ARM` многотемная, и пять файлов из неё
    про ДРУГИЕ сюжеты той же записи (танкеры в США, гарантии для России) плюс
    кадр с логотипом телеканала — к ролику не относятся вовсе, а гейт висел
    красным. Красный гейт, который «всегда красный», перестают читать — это
    хуже отсутствия гейта. Поэтому отклонённое засчитывается РАЗОБРАННЫМ, но
    только с названной причиной, и причина печатается: молча спрятать файл
    нельзя.

    Файл рядом со сценарием: `tg_rejected.json` (или `tg_отказы.json`).
    Формат любой из двух: {"<url>": "причина"} или
    [{"url": "…", "why": "…"}, …].
    """
    out = {}
    for name in ("tg_rejected.json", "tg_отказы.json"):
        p = os.path.join(where, name)
        if not os.path.isfile(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("!! не прочитать %s: %s" % (name, e))
            continue
        if isinstance(d, dict):
            for k, v in d.items():
                out[str(k)] = str(v)
        elif isinstance(d, list):
            for r in d:
                if isinstance(r, dict) and r.get("url"):
                    out[str(r["url"])] = str(r.get("why") or r.get("reason") or "")
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    tgs = []
    if "--tg" in sys.argv:
        tg1 = sys.argv[sys.argv.index("--tg") + 1]
        args = [a for a in args if a != tg1]
        # Та же маска, что и для глоба ниже: снапшот дня, отказы и служебные
        # файлы `geo_links` выдачей `tg_media` не являются, даже если их
        # передали ключом (05.11).
        if any(w in os.path.basename(tg1).lower()
               for w in ("snapshot", "снапшот", "snap", "reject", "отказ",
                         "source", "map")):
            tgs = []
        else:
            tgs = [tg1]
    here = os.path.dirname(os.path.abspath(args[0])) or "."
    # ВРЕМЕННЫЙ ФАЙЛ КРУГА ПРАВОК — НЕ СЦЕНАРИЙ (2026-10-31, улов `usuario-2e`,
    # дефект моей же правки). `refetch.py` кладёт правленые сцены в
    # `.refetch_images.json` и зовёт линтер по НЕМУ. Гейт видел две-три
    # починяемые сцены вместо всего ролика, не находил в них кадров досье и
    # отбивал круг: «поставлено 0, лежит без дела 1» — при том что кадр стоял
    # сценой 51 основного сценария. То есть чем аккуратнее вкладка разобрала
    # досье, тем вернее у неё блокировался любой круг правок, а штатная
    # лазейка `--force` вкладке недоступна. Подменяем временный файл
    # настоящими сценариями той же папки.
    _tmp = [x for x in args
            if os.path.basename(x).startswith(".")
            or "refetch" in os.path.basename(x).lower()]
    if _tmp:
        _real = [c for c in sorted(glob.glob(os.path.join(here, "*.scenes.json")))
                 if not os.path.basename(c).startswith(".")
                 and "refetch" not in os.path.basename(c).lower()]
        if _real:
            args = _real + [x for x in args if x not in _tmp]
            print("круг правок: вместо временного файла (%s) сверяю с "
                  "полным сценарием — %s"
                  % (", ".join(os.path.basename(x) for x in _tmp),
                     ", ".join(os.path.basename(x) for x in _real)))
        else:
            print("круг правок: полного сценария рядом нет, гейт досье "
                  "пропускаю — по двум починяемым сценам судить нельзя.")
            return 0
    # ВСЕ ПРОГОНЫ tg_media, А НЕ ПЕРВЫЙ ФАЙЛ ПО АЛФАВИТУ (31.10, улов
    # `usuario-6a`): у вкладки было два прогона, `tg.json` и `tg2.json`, и
    # второй в счёт не шёл — то есть материал «не существовал» для гейта.
    for c in sorted(glob.glob(os.path.join(here, "tg*.json"))):
        b = os.path.basename(c).lower()
        if "reject" in b or "отказ" in b:
            continue
        # СНАПШОТ ДНЯ — НЕ МАТЕРИАЛ ЭТОГО РОЛИКА (05.11, улов `usuario-8f`).
        # `geo_links.py` сам пишет про него «это материал ВСЕХ тем дня, а не
        # твоей записи», но файл естественно называется `tg_snapshot.json` и
        # попадал под маску `tg*.json`: гейт требовал поставить в ролик
        # полсотни ЧУЖИХ файлов и отбивал фетч. Вкладка лечила переносом
        # файла из папки — то есть пряталась от собственного инструмента.
        if "snapshot" in b or "снапшот" in b:
            continue
        # сравнение по АБСОЛЮТНОМУ пути: `--tg tg.json` и находка глоба
        # `/путь/tg.json` — один файл, а строки разные (печаталось «tg.json,
        # tg.json», и файлы считались дважды)
        if any(os.path.abspath(c) == os.path.abspath(t) for t in tgs):
            continue
        tgs.append(c)
    # ВСПЛЫВАШКИ СЧИТАЮТСЯ ТОЖЕ (31.10, тот же улов). Гейт сам пишет «что не
    # лезет в сцену — идёт во всплывашку», а смотрел только базовые сцены:
    # вкладка поставила шесть файлов досье всплывашками и получила
    # «поставлено 0». Для ролика, закрывшего материал целиком всплывашками,
    # это валило бы фетч без причины.
    _have = {os.path.abspath(x) for x in args}
    for c in sorted(glob.glob(os.path.join(here, "*overlay*.json"))
                    + glob.glob(os.path.join(here, "overlays*.json"))):
        if os.path.abspath(c) not in _have and "snapshot" not in os.path.basename(c):
            args.append(c)
            _have.add(os.path.abspath(c))
    tg = tgs[0] if tgs else None
    if not tgs:
        print("ОШИБКА: не найден файл выдачи tg_media.py (tg*.json) рядом со "
              "сценарием.", file=sys.stderr)
        print("  Досье ОБЯЗАНО быть прогнано до раскадровки: соберите ВСЕ "
              "ссылки t.me со ВСЕХ листов xlsx (Archive, Debug, AuthorNotes, "
              "NewsInbox, Claims, Sources, Productions) и прогоните "
              "tg_media.py --json tg.json <ссылки…>.", file=sys.stderr)
        return 2

    media = []
    _seen_u = set()
    for t in tgs:
        for m in load_tg(t):
            if m["url"] in _seen_u:
                continue
            _seen_u.add(m["url"])
            media.append(m)
    print("выдачи tg_media: %s" % ", ".join(os.path.basename(t) for t in tgs))
    print("сверяю со: %s" % ", ".join(os.path.basename(x) for x in args))
    blob, st = used_strings(args)
    rej = load_rejected(os.path.dirname(os.path.abspath(args[0])) or ".")
    if not media:
        print("в %s медиа нет вовсе — вложений у постов не было, претензий "
              "нет" % os.path.basename(tg))
        return 0

    # КЛЮЧОМ ОТКАЗА ГОДИТСЯ И АДРЕС ПОСТА, И АДРЕС ФАЙЛА (01.11, улов
    # `usuario-59`). Подсказка ниже печатала `{"<url>": "причина"}`, и это
    # читается как адрес ПОСТА — вкладка так и записала, а сверка шла по
    # адресу ФАЙЛА, и гейт держал красный свет на разобранном материале.
    # Адрес поста закрывает все его вложения: смотрят и отклоняют обычно
    # пост целиком.
    def _why(m):
        return rej.get(m["url"]) or rej.get(m.get("post") or "")

    # УЧЁТ ТОЖЕ ПО ТРЁМ КЛЮЧАМ, А НЕ ПО ОДНОМУ (06.11, улов `usuario-a3`,
    # стоил вкладке круга). Для ОТКАЗОВ адрес поста уже годился с 01.11, а
    # для УЧЁТА — нет: сцена честно несла `t.me/<канал>/<номер>` (так велит и
    # бриф, и наша инструкция), а сверка искала только cdn-адрес ФАЙЛА — и
    # гейт печатал «поставлено 0, лежит без дела 11» при шести реально
    # поставленных вложениях. Плюс третий ключ: ИМЯ ФАЙЛА. Боевой
    # `overlays.json` адресов не несёт вовсе (только `photo`/`sound`/`at`),
    # поэтому всплывашка из досье не засчитывалась НИКОГДА; по имени файла
    # она опознаётся, если кадр лёг под своим именем.
    # СВЕРКА ПО СОДЕРЖИМОМУ (09.11, см. шапку): кадр, попавший ВНУТРЬ
    # рисованного кадра, по адресу и имени не находится — ни того, ни другого
    # в сцене уже нет. Индекс считается один раз на запуск.
    _в_ролике = в_ролике_по_md5(here)
    _копии = местные_копии(here)
    _md5_кэш = {}
    _внутри = {}

    _ВИДЕО = (".mp4", ".mov", ".webm", ".mkv", ".m4v")

    def _по_содержимому(m):
        for п in _подсказки(m):
            for bn, path in _копии:
                if п not in bn:
                    continue
                # фото не ищем среди видеофайлов и наоборот: у поста бывают и
                # то и другое, и совпадение по подсказке ещё не совпадение по
                # вложению
                if (bn.endswith(_ВИДЕО)) != (m.get("kind") == "видео"):
                    continue
                if path not in _md5_кэш:
                    _md5_кэш[path] = _md5(path)
                где = _в_ролике.get(_md5_кэш[path] or "")
                if где:
                    return где
        return None

    def _used(m):
        if m["url"] in blob:
            return True
        if (m.get("post") or "") and m["post"] in blob:
            return True
        _bn = os.path.basename(str(m["url"]).split("?")[0])
        if bool(_bn) and len(_bn) > 6 and _bn in blob:
            return True
        где = _по_содержимому(m)
        if где:
            _внутри[m["url"]] = где
            return True
        return False

    used = len([m for m in media if _used(m)])
    dropped = [m for m in media if not _used(m) and _why(m)]
    # НЕПРИМЕНИМОЕ ОТДЕЛЯЕТСЯ ДО СЧЁТА «ЛЕЖИТ БЕЗ ДЕЛА» (11.11): файл ниже
    # порога фетчера не «забыт», его физически некуда поставить.
    _мало = [m for m in media
             if not _used(m) and not _why(m) and неприменим(m)]
    _мало_u = {m["url"] for m in _мало}
    unused = [m for m in media if not _used(m) and not _why(m)
              and m["url"] not in _мало_u]
    print("=== МАТЕРИАЛ ДОСЬЕ ===")
    print("файлов во вложениях постов: %d (фото %d, видео %d)" % (
        len(media), sum(1 for m in media if m["kind"] == "фото"),
        sum(1 for m in media if m["kind"] == "видео")))
    print("поставлено в ролик: %d, разобрано и отклонено: %d, неприменимо по "
          "размеру: %d, лежит без дела: %d"
          % (used, len(dropped), len(_мало), len(unused)))
    for m in _мало[:20]:
        print("  неприменимо: %s из %s — %s"
              % (m["kind"], m["post"], неприменим(m)))
    for m in dropped[:40]:
        print("  отклонено: %s из %s — %s"
              % (m["kind"], m["post"], _why(m) or "без причины"))
    for m in media:
        if m["url"] in _внутри:
            print("  зачтено по содержимому файла (md5): %s из %s — стоит %s"
                  % (m["kind"], m["post"], "; ".join(_внутри[m["url"]][:2])))
    print("сцен: всего %d — досье %d, медиатека %d, поиск %d, рисованных %d"
          % (st["total"], st["direct_url"], st["library"], st["search"],
             st["card"]))

    if not unused:
        print("\nЧисто: весь материал досье в ролике.")
        return 0

    print("\nНЕ ИСПОЛЬЗОВАНО:")
    for m in unused[:40]:
        note = ("; ".join(m["notes"])[:90]) if m["notes"] else ""
        print("  %s из %s%s" % (m["kind"], m["post"], (" — " + note) if note else ""))
        print("      %s" % m["url"])
    if len(unused) > 40:
        print("  … и ещё %d" % (len(unused) - 40))

    print("\n  Если файл СМОТРЕЛИ и он не подходит (чужая тема той же записи "
          "ARM, клеймо по центру, вшитые субтитры) — впиши его в "
          "tg_rejected.json рядом со сценарием: {\"<url>\": \"причина\"}. "
          "Ключом годится И адрес ПОСТА (t.me/…, закроет все его вложения), "
          "И адрес ФАЙЛА (cdn…, строка выше) — что удобнее. "
          "Он зачтётся разобранным, а причина останется видна.")
    if st["search"]:
        print("\nОТКАЗ: %d сцен закрыты ПОИСКОМ, пока %d файлов досье лежат "
              "без дела." % (st["search"], len(unused)))
        print("  Порядок источников: досье → медиатека и база → поиск, и"
              " только им.")
        print("  Ширина НЕ повод оставить кадр в стороне: узкий кадр ставится в"
              " родном размере по центру с размытой заливкой полей.")
        print("  КАРТЫ из постов ставятся в сцены первым делом — карта"
              " источника это информация, а не «кадр 800 px».")
        print("  Что физически не лезет в сцену — идёт во всплывашку (порог"
              " 800).")
        return 1
    print("\nСцен из поиска нет — остаток досье это не брак, но посмотри, не "
          "просится ли он во всплывашки.")
    return 1 if "--strict" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())
