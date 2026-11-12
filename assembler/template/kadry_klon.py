#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""КАДРЫ КЛОНА БЕРУТСЯ У ДОНОРА, А НЕ ИЩУТСЯ ЗАНОВО (11.11.2026).

Его вопрос 11.11 по третьему варианту вчерашней темы: «Та тема, которая уже
собрана была вчера на двух каналах. Почему так долго собирать уже на том, что
уже есть?» Правило в SKILL.md стояло с 08.11 («кадры донора, scenes.json,
карточки берутся оттуда, заново ничего не ищется»), а инструмента под него не
было — вкладка шла полным циклом: раскадровка с нуля, 72 сцены в облачный
фетч, добор, круги правок. Два часа там, где у доноров лежат 154 готовых
кадра, которые он УЖЕ утвердил.

Что делает: сопоставляет сцены клона со сценами донора ПО ТЕКСТУ (та же
фактура — те же слова), и где похожесть выше порога, кладёт кадр донора в
`images/` клона, меняя источник сцены на `local_donor`. Фетч за такими
сценами уже не идёт.

ЧЕГО НЕ ДЕЛАЕТ: не берёт кадр, который забанен; не ставит один кадр дважды;
не трогает сцены-карточки (`card:*`) и готовые элементы; по умолчанию берёт
не больше 70% сцен — его курс 08.11 «клон отличается составом элементов, а
не только кадрами», полностью одинаковый видеоряд не нужен.

    python3 kadry_klon.py <scenes.json клона> [--donor <папка>] [--dolya 0.7]
    python3 kadry_klon.py <scenes.json клона> --spisok      # только показать
"""
import argparse
import difflib
import glob
import hashlib
import json
import os
import re
import shutil
import sys

# ЕГО СЛОВО 11.11: ТРЕТИЙ ЭКЗЕМПЛЯР СОБИРАЕТСЯ ПОЧТИ МГНОВЕННО.
# «У них есть два источника для дашборда — это Планета и 5 минут. И добить
# туда 10-15-20% нового — это вообще элементарно. И тут же отсылать на сборку
# без утверждения… Ну не 3,5 часа делать, дольше, чем с нуля».
# Поэтому берём у доноров ВСЁ, что подходит, оставляя новым поиском только
# 15% сцен: порог сходства низкий, а чего не хватило по смыслу — добиваем
# кадрами донора ПО ПОРЯДКУ (фактура та же, порядок повествования тот же).
ПОРОГ = 0.35          # похожесть запроса/текста; ниже — добиваем по порядку
ДОЛЯ = 0.85          # максимум сцен клона, закрываемых кадрами донора
ПРОЕКТЫ = os.path.expanduser("~/projects")
КАРТОЧКА = "card"


def норм(t):
    return re.sub(r"[^а-яёa-z0-9 ]", " ", (t or "").lower()).split()


def похожесть(a, b):
    sa, sb = норм(a), норм(b)
    if not sa or not sb:
        return 0.0
    return difflib.SequenceMatcher(None, " ".join(sa), " ".join(sb)).ratio()


def сцены(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    return d, (d.get("scenes", d) if isinstance(d, dict) else d)


def близнец(pdir):
    """Вторая папка того же ролика: рабочая <-> папка забора `<проект>-cloud`."""
    pdir = pdir.rstrip("/")
    return pdir[:-6] if pdir.endswith("-cloud") else pdir + "-cloud"


def рабочая_раскадровка(pdir):
    """САМАЯ СВЕЖАЯ раскадровка донора ИЗ ОБЕИХ ЕГО ПАПОК (12.11).

    Было: брали первый файл из одной папки. У донора их две — рабочая и
    папка забора `<проект>-cloud`, и источники в них РАСХОДЯТСЯ: карточки он
    ставит ПОСЛЕ отправки фетча, и в рабочем файле у сцены остаётся старый
    `web_search`, а в файле забора уже `card:film`. Фильтр `card:*` ниже
    смотрел в устаревший файл, пропускал сцену как обычную, а `файл_сцены()`
    отдавал из `images/` уже отрисованный КЛИП КАРТОЧКИ. Улов `usuario-16`
    12.11: 17 сцен из 49 приехали донорскими карточками — с ЕГО фразами
    поверх НАШЕГО переписанного текста и дублем вида. Берём свежайший по
    времени правки.
    """
    c = []
    for d in (pdir, близнец(pdir)):
        if not os.path.isdir(d):
            continue
        c += [p for p in glob.glob(os.path.join(d, "*.scenes.json"))
              if not os.path.basename(p).startswith(("codex", "lib_", "raw"))
              and not any(w in os.path.basename(p)
                          for w in ("overlays_fetch", "maps_fetch", "cards_fetch"))]
    if not c:
        return ""
    c.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
    return c[0]


def карточка_донора(pdir, sid):
    """Правда о сцене донора — ПО ФАЙЛАМ, а не по строке источника (12.11).

    Даже свежая раскадровка может отстать от дела: задание карточки лежит
    рядом, в `cards/queue/scene_NNN.json`, и оно появляется раньше, чем
    источник сцены перепишут. Сцена, у которой есть задание, — рисованная,
    донором она не бывает ни кадром, ни запросом.
    """
    try:
        имя = "scene_%03d.json" % int(sid)
    except (TypeError, ValueError):
        return False
    for d in (pdir, близнец(pdir)):
        if os.path.exists(os.path.join(d, "cards", "queue", имя)):
            return True
    return False


def тема_и_день(pdir):
    """Номер темы и день из `.source_dir` проекта."""
    try:
        with open(os.path.join(pdir, ".source_dir"), encoding="utf-8") as f:
            src = f.read().strip()
    except OSError:
        return "", "", ""
    ч = os.path.abspath(src).replace("\\", "/").split("/")
    if len(ч) < 4:
        return "", "", ""
    канал = ч[-4] if len(ч) >= 4 else ""
    день, тема = ч[-2], ч[-1]
    m = re.match(r"\s*(\d+)\s*-", тема)
    return канал, день, (m.group(1) if m else "")


def доноры(pdir):
    """Проекты той же темы и дня на «5 МИНУТ» и ПЛАНЕТЕ, с кадрами."""
    _, день, номер = тема_и_день(pdir)
    if not день:
        return []
    свои = os.path.abspath(pdir)
    найдено = []
    for d in sorted(glob.glob(os.path.join(ПРОЕКТЫ, "*"))):
        if not os.path.isdir(d) or os.path.abspath(d) == свои:
            continue
        к, дн, ном = тема_и_день(d)
        if дн != день or (номер and ном != номер):
            continue
        if к.upper().replace("Ё", "Е") not in ("5 МИНУТ", "ПЛАНЕТА"):
            continue
        if not glob.glob(os.path.join(d, "images", "scene_*")):
            continue
        найдено.append(d)
    # сначала тот, где кадров больше
    найдено.sort(key=lambda p: len(glob.glob(os.path.join(p, "images", "scene_*"))),
                 reverse=True)
    return найдено


def баны():
    p = os.path.join(ПРОЕКТЫ, "media-library", ".banned_md5.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def файл_сцены(images, sid):
    for f in sorted(glob.glob(os.path.join(images, "scene_%03d.*" % int(sid)))):
        b = os.path.basename(f)
        if any(w in b for w in (".ovthumb.", ".text.", ".revframe.",
                                ".wmcrop.", ".ocrcrop.", ".before_crop.")):
            continue
        return f
    return ""


def main():
    ap = argparse.ArgumentParser(description="кадры клона из донорской темы")
    ap.add_argument("scenes")
    ap.add_argument("--donor", action="append", default=[],
                    help="папка проекта-донора; без ключа ищутся сами")
    ap.add_argument("--dolya", type=float, default=ДОЛЯ,
                    help="какую долю сцен клона закрывать кадрами донора")
    ap.add_argument("--porog", type=float, default=ПОРОГ)
    ap.add_argument("--tolko-smysl", action="store_true", dest="tolko_smysl",
                    help="брать только смысловые совпадения, не добивать "
                         "кадрами донора по порядку")
    ap.add_argument("--spisok", action="store_true",
                    help="только показать, что взялось бы, ничего не трогая")
    a = ap.parse_args()

    if not os.path.isfile(a.scenes):
        sys.exit("нет файла: %s" % a.scenes)
    pdir = os.path.dirname(os.path.abspath(a.scenes)) or "."
    images = os.path.join(pdir, "images")
    os.makedirs(images, exist_ok=True)
    data, sc = сцены(a.scenes)
    if not sc:
        sys.exit("раскадровка пустая: %s" % a.scenes)

    дон = a.donor or доноры(pdir)
    if not дон:
        print("донорской темы того же дня не нашлось — ищем кадры как обычно")
        return 0
    print("доноры: %s" % ", ".join(os.path.basename(d) for d in дон))

    _ban = баны()
    пары = []
    занято = set()
    for d in дон:
        dp = рабочая_раскадровка(d)
        if not dp:
            continue
        _, dsc = сцены(dp)
        dimg = os.path.join(d, "images")
        for s in sc:
            sid = str(s.get("id"))
            if sid in занято:
                continue
            if str(s.get("source", "")).startswith(КАРТОЧКА):
                continue
            лучший, балл = None, 0.0
            for ds in dsc:
                if str(ds.get("source", "")).startswith(КАРТОЧКА):
                    continue
                if карточка_донора(d, ds.get("id")):
                    continue
                # СЧИТАЕМ И ПО ЗАПРОСУ, И ПО ТЕКСТУ, БЕРЁМ ЛУЧШЕЕ (11.11).
                # Текст у клона переписан заново (уникализация 60-80%), и по
                # нему совпадает мало — замер на живой теме дал 5 сцен из 72.
                # А ЗАПРОС описывает ОБЪЕКТ в кадре («Фридрих Мерц Берлин
                # 2026 официальный портрет»), и у клонов объекты те же: по
                # нему совпадение честное. Адреса файлов (`direct_url`) в
                # сравнение не идут — это не описание, а ссылка.
                r = похожесть(s.get("text"), ds.get("text"))
                q1, q2 = str(s.get("source_query", "")), str(ds.get("source_query", ""))
                if q1 and q2 and not q1.startswith("http") and not q2.startswith("http"):
                    r = max(r, похожесть(q1, q2))
                if r > балл:
                    лучший, балл = ds, r
            if not лучший or балл < a.porog:
                continue
            f = файл_сцены(dimg, лучший.get("id"))
            if not f:
                continue
            try:
                h = hashlib.md5(open(f, "rb").read()).hexdigest()
            except OSError:
                continue
            if h in _ban:
                continue
            пары.append((sid, s, f, балл, h, os.path.basename(d)))
            занято.add(sid)

    потолок = int(len(sc) * a.dolya)
    # ДОБИВАЕМ ПО ПОРЯДКУ (11.11). Смысловое совпадение закрывает примерно
    # половину сцен; остальное у донора всё равно про ту же тему, снятое в
    # том же порядке — берём его кадры подряд, пока не упрёмся в потолок.
    # Выключается ключом `--tolko-smysl`, если клон должен отличаться сильнее.
    if not a.tolko_smysl and len(пары) < потолок:
        свободные = [s for s in sc if str(s.get("id")) not in занято
                     and not str(s.get("source", "")).startswith(КАРТОЧКА)]
        запас = []
        for d in дон:
            dp = рабочая_раскадровка(d)
            if not dp:
                continue
            _, dsc = сцены(dp)
            dimg = os.path.join(d, "images")
            for ds in dsc:
                if str(ds.get("source", "")).startswith(КАРТОЧКА):
                    continue
                if карточка_донора(d, ds.get("id")):
                    continue
                f = файл_сцены(dimg, ds.get("id"))
                if not f:
                    continue
                try:
                    h = hashlib.md5(open(f, "rb").read()).hexdigest()
                except OSError:
                    continue
                if h in _ban:
                    continue
                запас.append((f, h, os.path.basename(d)))
        взятые_хэши = {x[4] for x in пары}
        запас = [x for x in запас if x[1] not in взятые_хэши]
        for s_, (f, h, dn) in zip(свободные, запас):
            if len(пары) >= потолок:
                break
            sid = str(s_.get("id"))
            пары.append((sid, s_, f, 0.0, h, dn))
            занято.add(sid)
            взятые_хэши.add(h)
    пары.sort(key=lambda x: x[3], reverse=True)
    пары = пары[:потолок]
    if not пары:
        print("похожих сцен у доноров нет — ищем кадры как обычно")
        return 0

    print("кадров донора подходит: %d из %d сцен (потолок %d, порог похожести "
          "%.2f)" % (len(пары), len(sc), потолок, a.porog))
    if a.spisok:
        for sid, _s, f, балл, _h, dn in sorted(пары, key=lambda x: int(x[0]))[:40]:
            print("  сцена %3s ← %s/%s (%.2f)" % (sid, dn, os.path.basename(f), балл))
        return 0

    # ЗАПАС НА ПОДМЕНУ: если кадр уже стоит в другой сцене, берём не «ничего»,
    # а СЛЕДУЮЩИЙ свободный кадр донора (11.11). Иначе дубль хэша просто
    # терял сцену: в замере `--spisok` подходило 61, а копировалось 35.
    _zapas = []
    for d in дон:
        dimg = os.path.join(d, "images")
        for f0 in sorted(glob.glob(os.path.join(dimg, "scene_*"))):
            b = os.path.basename(f0)
            if any(w in b for w in (".ovthumb.", ".text.", ".revframe.",
                                    ".wmcrop.", ".ocrcrop.", ".before_crop.")):
                continue
            try:
                h0 = hashlib.md5(open(f0, "rb").read()).hexdigest()
            except OSError:
                continue
            if h0 in _ban:
                continue
            _zapas.append((f0, h0, os.path.basename(d)))

    взято, хэши = 0, set()
    for sid, s, f, балл, h, dn in sorted(пары, key=lambda x: int(x[0])):
        if h in хэши:
            _замена = next(((f2, h2, d2) for f2, h2, d2 in _zapas
                            if h2 not in хэши), None)
            if not _замена:
                continue
            f, h, dn = _замена
        ext = os.path.splitext(f)[1]
        цель = os.path.join(images, "scene_%03d%s" % (int(sid), ext))
        if os.path.exists(цель):
            continue
        try:
            shutil.copy2(f, цель)
        except OSError as e:
            print("  сцена %s: не скопировалось (%s)" % (sid, e))
            continue
        хэши.add(h)
        s["source"] = "local_donor"
        s["source_query"] = "%s/%s" % (dn, os.path.basename(f))
        взято += 1

    if isinstance(data, dict):
        data["scenes"] = sc
    out = data if isinstance(data, dict) else sc
    tmp = a.scenes + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, a.scenes)
    print("взято кадров донора: %d — за этими сценами фетч уже не идёт" % взято)
    print("остальные %d сцен ищутся как обычно: клон должен отличаться "
          "составом, а не быть копией (его курс 08.11)" % (len(sc) - взято))
    return 0


if __name__ == "__main__":
    sys.exit(main())
