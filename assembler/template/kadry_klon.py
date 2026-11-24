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
ПОРОГ = 0.5           # похожесть запроса/текста; ниже — добиваем по порядку.
# ПОДНЯТ С 0.35 (23.11, НА-РАСКАТКУ п.160, usuario-80): `норм()` не чистит
# стоп-слова, и SequenceMatcher.ratio() на двух РАЗНЫХ по теме предложениях
# из одного смыслового поля (финансы/кредиты, но разные страны и события)
# набирал 0.35-0.40 просто на общей грамматике и частых словах — сцена про
# Арахамию сматчилась с донором про Фицо/кредиты. Калибровка на синтетике:
# несвязанные-но-из-одной-темы ~0.39, настоящее совпадение ~0.70, совсем
# разное ~0.21 — 0.5 уверенно режет первый класс и держит второй.
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
        # ПАПКА ЗАБОРА ДОНОРОМ НЕ СЧИТАЕТСЯ (15.11, улов `usuario-b8`).
        # В `<проект>-cloud/images/` лежит ВСЁ, что привёз фетч, включая
        # кадры, которые донор потом забанил и заменил. Живой случай: кадр с
        # подростком у граффити-стены был забанен в рабочем проекте, но
        # остался в заборе — клон утащил оттуда устаревшую пару, и запрет на
        # детей чуть не доехал до сборки. Берём только рабочую папку донора.
        if os.path.basename(d.rstrip("/")).endswith("-cloud"):
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


_OV_EXT = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm")


def всплывашка_донора(d, donor_sid):
    """Файл донорской ВСПЛЫВАШКИ (не кадра) для её сцены, если есть (21.11).

    Те же правила, что у `build_overlays.py do_build` при сборе `overlays/`:
    служебный `.text.png` не считается.
    """
    try:
        имя = "scene_%03d" % int(donor_sid)
    except (TypeError, ValueError):
        return ""
    for f in sorted(glob.glob(os.path.join(d, "overlays", имя + ".*"))):
        b = os.path.basename(f)
        if b.endswith(".text.png") or not b.lower().endswith(_OV_EXT):
            continue
        if os.path.getsize(f) > 0:
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
    ap.add_argument("--bez-unikalizacii", action="store_true", dest="bez_unik",
                    help="не зеркалить и не менять крупность взятых кадров")
    ap.add_argument("--spisok", action="store_true",
                    help="только показать, что взялось бы, ничего не трогая")
    a = ap.parse_args()

    if not os.path.isfile(a.scenes):
        sys.exit("нет файла: %s" % a.scenes)
    pdir = os.path.dirname(os.path.abspath(a.scenes)) or "."
    images = os.path.join(pdir, "images")
    os.makedirs(images, exist_ok=True)
    overlays_dir = os.path.join(pdir, "overlays")
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
    _ов_взято = set()
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

            # ВСПЛЫВАШКА ДОНОРА — ТОТ ЖЕ ПРИНЦИП, ЧТО КАДР (21.11, П-0422).
            # `tg_overlay_fill.py`/`build_overlays.py` ищут совпадение со
            # СЛОВАРЁМ поста по тексту СЦЕНЫ, а текст клона переписан заново
            # — на нём находит в разы меньше (его замер 19.11: 13 vs 3, 27
            # vs 4, 8 vs 5 на трёх темах дня). Сцена донора здесь уже
            # смыслово подобрана (порог похожести выше `a.porog`) — если у
            # неё есть всплывашка и клон своей ещё не получил, переносим её
            # вместе с кадром, не дожидаясь отдельного словарного поиска.
            # Только для смысловых совпадений этого цикла, не для добивки
            # по порядку ниже — там сцены не связаны по содержанию.
            if not a.spisok and sid not in _ов_взято \
                    and not glob.glob(os.path.join(overlays_dir,
                                                    "scene_%03d.*" % int(sid))):
                of = всплывашка_донора(d, лучший.get("id"))
                if of:
                    try:
                        oh = hashlib.md5(open(of, "rb").read()).hexdigest()
                    except OSError:
                        oh = None
                    if oh and oh not in _ban:
                        os.makedirs(overlays_dir, exist_ok=True)
                        oext = os.path.splitext(of)[1]
                        цель_ов = os.path.join(
                            overlays_dir, "scene_%03d%s" % (int(sid), oext))
                        try:
                            shutil.copy2(of, цель_ов)
                            _ов_взято.add(sid)
                        except OSError:
                            pass

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
    if _ов_взято:
        print("всплывашек донора перенесено: %d" % len(_ов_взято))
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
        # КЛИПЫ КАРТОЧЕК ДОНОРА В ЗАПАС НЕ КЛАДЁМ (13.11, пункт 66 очереди,
        # улов `usuario-fc`: в клон прилетел клип чужой карточки `bars`).
        # В основном доборе выше карточки отсеяны по `source` и
        # `карточка_донора`, а этот список собирался СЛЕПЫМ `glob` по папке —
        # то есть те же самые файлы возвращались через чёрный ход. Наш
        # рисованный кадр чужому ролику не принадлежит: он сделан под ЕГО
        # текст, в клоне читается как цитата из соседнего ролика.
        _карточки_донора = set()
        _dp0 = рабочая_раскадровка(d)
        if _dp0:
            _, _dsc0 = сцены(_dp0)
            for _ds0 in _dsc0:
                try:
                    _sid0 = int(_ds0.get("id"))
                except (TypeError, ValueError):
                    continue
                if (str(_ds0.get("source", "")).startswith(КАРТОЧКА)
                        or карточка_донора(d, _ds0.get("id"))):
                    _карточки_донора.add("scene_%03d" % _sid0)
        for f0 in sorted(glob.glob(os.path.join(dimg, "scene_*"))):
            b = os.path.basename(f0)
            if b.split(".")[0] in _карточки_донора:
                continue
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
    # ВЗЯТЫЙ У ДОНОРА КАДР УНИКАЛИЗИРУЕТСЯ (15.11, его прямое слово: «можно
    # же на эту же тему закинуть на планету, только отзеркалить это же фото,
    # если там нет надписей, которые перевернутся. Положить на него какой-то
    # другой эффект»). Инструмент для этого есть с 07.11, но клон его не
    # звал — и один и тот же кадр уезжал в два ролика без единого отличия.
    # Зеркало ставится только там, где распознавание не нашло в кадре текста;
    # заодно меняется крупность. Отключить: --bez-unikalizacii.
    if взято and not a.bez_unik:
        _un = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "unikalizaciya.py")
        if os.path.exists(_un) and дон:
            import subprocess as _sp
            print("уникализирую кадры донора (зеркало без текста + крупность):")
            _r = _sp.run([sys.executable, _un, дон[0], pdir],
                         capture_output=True, text=True)
            _хвост = (_r.stdout or "").strip().splitlines()
            for _л in _хвост[-6:]:
                print("  %s" % _л)
            if _r.returncode != 0:
                print("  уникализация не прошла — кадры остались как у донора",
                      file=sys.stderr)

    # ГЕЙТ ДЕТЕЙ СРАЗУ ПОСЛЕ ПЕРЕНОСА (15.11, улов `usuario-27`, живой
    # случай: кадр с подростком у граффити-стены приехал из ролика донора в
    # клон как «уже проверенный» — у донора проверка ещё не гонялась).
    # Донорский кадр не является проверенным по умолчанию: гоняем здесь.
    if взято:
        _dg = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "deti_gate.py")
        if os.path.exists(_dg):
            import subprocess as _sp
            # БЫЛО (до 23.11): звали `deti_gate.py <scenes.json>` без
            # подкоманды (нужна listy/verdikt/centr/check) И с файлом сцен
            # вместо папки проекта — argparse падал кодом 2 на КАЖДОМ
            # переносе, а сообщение ниже читало любой ненулевой код как
            # «не чисто», хотя гейт вообще не запускался (Z-0034/п.156).
            # deti_gate — не синхронная проверка: listy собирает листы,
            # смотрящий (суб­агент/внешний агент) даёт verdikt, check потом
            # читает ЗАПИСАННЫЙ вердикт. Автоматический check тут был бы
            # пустышкой без verdikt — поэтому только листы и явная просьба.
            print("гейт детей по перенесённым кадрам — собираю контактные листы:")
            _r = _sp.run([sys.executable, _dg, "listy", pdir],
                         capture_output=True, text=True)
            for _л in (_r.stdout or "").strip().splitlines()[-6:]:
                print("  %s" % _л)
            if _r.returncode != 0:
                print("  !! deti_gate.py listy упал (код %d) — разбери "
                      "вручную: python3 deti_gate.py listy %s" % (_r.returncode, pdir),
                      file=sys.stderr)
            else:
                print("  листы готовы в %s/deti/ — требуется просмотр и "
                      "verdikt ПЕРЕД check, кадр донора проверенным "
                      "не считается, пока verdikt не записан" % pdir)

    print("взято кадров донора: %d — за этими сценами фетч уже не идёт" % взято)
    print("остальные %d сцен ищутся как обычно: клон должен отличаться "
          "составом, а не быть копией (его курс 08.11)" % (len(sc) - взято))
    return 0


if __name__ == "__main__":
    sys.exit(main())
