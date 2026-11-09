# -*- coding: utf-8 -*-
"""ЗАДАНИЕ НА КАРТОЧКУ — В ОЧЕРЕДЬ, А НЕ В РЕНДЕР НА МАШИНЕ ПОЛЬЗОВАТЕЛЯ.

Прямое слово пользователя 2026-10-23: «при сборке, неважно, дашборда или
чего-то там, ни в коем случае не использовать ресурсы компьютера; всё, что
можно сделать на GitHub, отсылать в GitHub; только крайние случаи, и то
оповещать мне».

Карточки арсенала (цитата-лоскут и карточки разбора) рисовались ЛОКАЛЬНО:
замер 22.10 — 50,9 с на карточку длиной 7,4 с, то есть 4-6 минут счёта на
машине за ролик. Облачный путь был написан в тот же день
(`fullcycle/cards_cloud.py` + workflow `cards-render`), но боевые обёртки на
него не перевели, а сам workflow лежал в одном репозитории из восьми.

Этот модуль — общая часть для `quote_card.py` и `style_card.py`: проверки
остаются в них (они разные), а запись задания и правка сцены — здесь, в одном
месте и в том же формате, который читает `cards_cloud.py`.
"""
import fcntl
import glob as _glob
import json
import os
import shutil
import subprocess
import time

QUEUE = os.path.join("cards", "queue")
# СВОЙ УГОЛ ДЛЯ СНИМКОВ КАРТОЧЕК (09.11, улов вкладки `usuario-2c`).
# `cards/photo/` переживает уборку папки забора, `images/` — нет.
PHOTO = os.path.join("cards", "photo")
JOURNAL = os.path.join("cards", "cards.json")
LOCK = os.path.join("cards", ".scenes.lock")
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUD_CMD = os.path.join(SKILL, "fullcycle", "cards_cloud.py")
VA_CMD = os.path.join(SKILL, "cloud", "va.sh")
NOTIFY = os.path.join(SKILL, "cloud", "notify.sh")


def local_allowed():
    """Локальный счёт разрешён ТОЛЬКО явным VIDEORYAD_LOCAL_OK=1."""
    return os.environ.get("VIDEORYAD_LOCAL_OK") == "1"


def notify_local(what):
    """Крайний случай — считаем на машине: пользователь просил оповещать."""
    try:
        subprocess.run(["bash", NOTIFY, "Считаю на ПК",
                        f"крайний случай: {what}"], timeout=20,
                       capture_output=True)
    except Exception:
        pass            # оповещение не должно валить работу


def check_photo(path):
    """ФОТО КАРТОЧКИ НЕЛЬЗЯ КЛАСТЬ В `images/` ПОД СВОИМ ИМЕНЕМ (09.11).

    Живой случай (вкладка `usuario-2c`, ролик `planeta-ukraina-forma-1011`,
    сцены 70 и 100): снимки для карточек легли в `images/card070.jpg` и
    `images/card100.jpg` — так велела подсказка самого `cards_cloud`
    («положи файл в images/»). Чистка папки забора снесла оба: в `images/`
    живут кадры СЦЕН, всё постороннее оттуда убирается. Карточки уехали в
    ролик с пустым местом под фото — у сплита чёрная левая половина, у досье
    тёмный прямоугольник, — и ни одна проверка этого не увидела: клип на
    месте, длительность сходится. Поймал пользователь глазами на дашборде:
    цитата Трампа есть, самого Трампа нет.

    Поэтому: кадр СВОЕЙ сцены (`images/scene_NNN.*`) брать можно и нужно — он
    тут же копируется в `cards/photo/`, — а посторонний файл в `images/`
    запрещён, потому что он там не жилец.
    """
    if not path:
        return
    ап = os.path.abspath(path)
    части = ап.replace("\\", "/").split("/")
    if "images" not in части:
        return
    имя = os.path.basename(ап)
    if имя.startswith("scene_") and имя[6:9].isdigit():
        return
    raise SystemExit(
        "!! ФОТО КАРТОЧКИ ЛЕЖИТ В images/ ПОД СВОИМ ИМЕНЕМ: %s\n"
        "   В `images/` живут кадры СЦЕН; посторонние файлы оттуда убирает\n"
        "   чистка папки забора, и карточка уедет в ролик с ПУСТЫМ местом\n"
        "   под фото — молча, прогон отчитается успехом (живой случай 09.11,\n"
        "   сцены 70 и 100 на `planeta-ukraina-forma-1011`).\n"
        "   Положи снимок в `cards/photo/` и укажи его оттуда:\n"
        "     mkdir -p cards/photo && mv %s cards/photo/\n"
        "     … --photo cards/photo/%s\n"
        "   Кадр СВОЕЙ сцены (`images/scene_NNN.jpg`) указывать можно — он\n"
        "   копируется в `cards/photo/` сам." % (path, path, имя))


def keep_photo(sid, path):
    """СНИМОК КАРТОЧКИ ЗАБИРАЕМ СЕБЕ, задание ссылается на КОПИЮ (09.11).

    Та же история, что и у `check_photo`, но лечение с другого конца: что бы
    вкладка ни указала ключом `--photo`, копия ложится в `cards/photo/` и
    дальше живёт своей жизнью. Исходник можно переместить, заменить кругом
    правок или снести уборкой — задание это уже не достанет.

    Имя копии — `card_NNN.<ext>`: уникально на сцену (в облако все файлы
    едут в одну папку по basename) и не сталкивается с кадрами донора,
    которые `unikalizaciya.py` кладёт туда же под именами `scene_NNN`/`kadr_`.
    """
    if not path:
        return path
    if not os.path.isfile(path):
        raise SystemExit("!! нет файла снимка: %s" % path)
    os.makedirs(PHOTO, exist_ok=True)
    ext = os.path.splitext(path)[1].lower() or ".jpg"
    цель = os.path.join(PHOTO, "card_%03d%s" % (int(sid), ext))
    if os.path.abspath(path) == os.path.abspath(цель):
        return цель
    # прежняя копия могла быть с другим расширением — убираем, иначе в
    # облако уедут оба файла и раннер возьмёт не тот
    for старый in _glob.glob(os.path.join(PHOTO, "card_%03d.*" % int(sid))):
        if os.path.abspath(старый) != os.path.abspath(цель):
            try:
                os.remove(старый)
            except OSError:
                pass
    shutil.copy2(path, цель)
    print("  снимок карточки забран себе: %s → %s (чистка папки забора его "
          "больше не достанет)" % (path, цель))
    return цель


# ───────────────────────────────────────────────────────────────────────────
# СЦЕНА СТАЛА РИСОВАННОЙ — ЕЁ СЛОИ ПЕРЕЕЗЖАЮТ В ТОМ ЖЕ ПРОХОДЕ (09.11)
#
# Живой случай вкладки `usuario-e6` на ролике «Орешник»: она переразметила
# сетку карточек (прежняя давала зазоры по 1-2 сцены и инструмент отбивал
# каждую вторую постановку), сдвинула семнадцать карточек на новые номера —
# и ВОСЕМЬ НАДПИСЕЙ С ОДНОЙ ВСПЛЫВАШКОЙ остались висеть на сценах, которые
# стали рисованными. Поймал `selfcheck`, но только перед дашбордом: круг
# правок уже потрачен. Её же вывод, дословно: «дешевле было бы правило:
# сдвинул карточку — сразу перенеси её слои, это одна строка в том же
# проходе».
#
# Поэтому дверь карточки сама снимает со сцены надпись, всплывашку и переход
# и кладёт их на соседнюю ПОДХОДЯЩУЮ сцену, вслух называя, что куда уехало.
# Некуда — отказ: молча потерять надпись хуже, чем встать (часть их —
# обязательные элементы, `obyazatelno.py`).
# `selfcheck` при этом не ослаблен и остаётся страховкой.
РАДИУС_ПРИЮТА = 5      # как далеко от сцены ищем приют для слоя
ЗАЗОР_ВСПЛЫВАШЕК = 2   # две всплывашки подряд читаются как мельтешение


def _всплывашка(запись):
    """Есть ли в записи overlays.json ФОТО-всплывашка (а не надпись)."""
    return bool(isinstance(запись, dict)
                and (запись.get("photo") or запись.get("query")
                     or запись.get("source")))


def _надпись(запись):
    return bool(isinstance(запись, dict) and (запись.get("text")
                                              or запись.get("words")))


def перенести_слои(scenes_path, sid, вид=""):
    """Снять со сцены `sid` надпись, всплывашку и переход и отдать соседу.

    Зовётся ДО того, как сцене поставлен источник `card:*`. Возвращает список
    напечатанных строк (пустой — переносить было нечего).
    """
    sid = int(sid)
    строки = []
    try:
        данные = json.load(open(scenes_path, encoding="utf-8"))
    except (OSError, ValueError):
        return строки
    сцены = данные["scenes"] if isinstance(данные, dict) else данные
    по_id = {}
    for s in сцены:
        try:
            по_id[int(s.get("id", -1))] = s
        except (TypeError, ValueError):
            pass
    номера = sorted(по_id)
    рисованные = {i for i, s in по_id.items()
                  if str(s.get("source", "")).startswith("card:")}
    рисованные.add(sid)        # наша сцена ею сейчас и станет

    ovp = "overlays.json"
    ov = {}
    if os.path.isfile(ovp):
        try:
            ov = json.load(open(ovp, encoding="utf-8"))
        except (OSError, ValueError):
            ov = {}
    запись = ov.get(str(sid)) if isinstance(ov, dict) else None
    есть_fx = bool(str(по_id.get(sid, {}).get("fx", "")).strip())
    if not isinstance(запись, dict) and not есть_fx:
        return строки

    def кандидаты():
        """Соседи по возрастанию расстояния: 34 → 33, 35, 32, 36, …"""
        for d in range(1, РАДИУС_ПРИЮТА + 1):
            for i in (sid - d, sid + d):
                if i in по_id and i not in рисованные:
                    yield i

    # Сцены, куда мы уже что-то переселили в ЭТОМ проходе: класть надпись и
    # всплывашку на одну сцену нельзя — его образец надписей (06.11) прямо
    # говорит «ни одной на сцене с фото-всплывашкой».
    занятые = set()

    def свободна(i, свой_род):
        if i in занятые:
            return False
        есть = ov.get(str(i))
        return not (свой_род(есть) if свой_род else есть)

    def приют_надписи(строго=True):
        # строгий заход: сцена вообще без слоёв; мягкий: лишь бы не надпись
        for i in кандидаты():
            if свободна(i, None if строго else _надпись):
                return i
        return None

    def приют_всплывашки(строго=True):
        for i in кандидаты():
            if not свободна(i, None if строго else _всплывашка):
                continue
            # ЗАЗОР СЧИТАЕМ БЕЗ СВОЕЙ ЖЕ ЗАПИСИ: она со сцены уезжает, и
            # считать её помехой — значит не найти приют вообще (поймано
            # сразу на проверке: надпись переехала, всплывашка «некуда»).
            if строго and any(_всплывашка(ov.get(str(j)))
                              for j in range(i - ЗАЗОР_ВСПЛЫВАШЕК + 1,
                                             i + ЗАЗОР_ВСПЛЫВАШЕК)
                              if j not in (i, sid)):
                continue
            return i
        return None

    def приют_fx():
        for i in кандидаты():
            # первая сцена переход не носит (правило двери `fx_put.py`)
            if i == номера[0] or str(по_id[i].get("fx", "")).strip():
                continue
            return i
        return None


    def положить(куда, что):
        цель = ov.setdefault(str(куда), {})
        if not isinstance(цель, dict):
            цель = {}
        цель.update(что)
        ov[str(куда)] = цель

    отказ = []
    if isinstance(запись, dict):
        if _надпись(запись):
            куда = приют_надписи(True) or приют_надписи(False)
            if куда is None:
                отказ.append("надпись «%s»"
                             % str((запись.get("text") or {}).get("words")
                                   or запись.get("words") or "")[:40])
            else:
                часть = {k: запись.pop(k) for k in ("text", "words")
                         if k in запись}
                положить(куда, часть)
                занятые.add(куда)
                строки.append("надпись перенесена на сцену %d" % куда)
        if _всплывашка(запись):
            куда = приют_всплывашки(True)
            тесно = False
            if куда is None:
                куда, тесно = приют_всплывашки(False), True
            if куда is None:
                отказ.append("всплывашка «%s»"
                             % str(запись.get("photo") or запись.get("query")
                                   or "")[:40])
            else:
                часть = {k: запись.pop(k) for k in list(запись)}
                положить(куда, часть)
                занятые.add(куда)
                строки.append("всплывашка перенесена на сцену %d%s"
                              % (куда, " (рядом есть другая — зазор тесный, "
                                       "посмотри глазами)" if тесно else ""))
        if not запись:
            ov.pop(str(sid), None)
        else:
            ov[str(sid)] = запись

    if отказ:
        raise SystemExit(
            "!! СЛОИ СЦЕНЫ %d ПЕРЕНОСИТЬ НЕКУДА: %s.\n"
            "   Сцена становится рисованной (card:%s), а на `card:*` не "
            "кладём ни надпись, ни всплывашку, ни переход (правило 06.11) — "
            "значит слой пропадёт молча.\n"
            "   Соседи в %d сценах либо тоже рисованные, либо уже со своим "
            "слоем. Поставь карточку на другую сцену ИЛИ сними слой руками "
            "и скажи координатору, что он выпал."
            % (sid, ", ".join(отказ), вид or "…", РАДИУС_ПРИЮТА))

    перенос_fx = None
    if есть_fx:
        куда = приют_fx()
        if куда is None:
            raise SystemExit(
                "!! ПЕРЕХОД СО СЦЕНЫ %d ПЕРЕНОСИТЬ НЕКУДА (fx «%s»).\n"
                "   На рисованный кадр эффекты не ложатся, а молча выбросить "
                "переход нельзя: засвет A73 — обязательный элемент.\n"
                "   Возьми другую сцену под карточку или перевесь переход "
                "сам (`fx_put.py`)."
                % (sid, str(по_id[sid].get("fx"))))
        перенос_fx = (куда, str(по_id[sid].get("fx")))

    # ЗАПИСЬ — ПОД ТЕМ ЖЕ ЗАМКОМ, ЧТО И ПРАВКА СЦЕНЫ. Соседние вкладки и
    # фоновые проходы пишут те же два файла; без замка правка откатывалась
    # молча (разбор 22.10, тот же механизм, что в `queue()`).
    os.makedirs("cards", exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        if isinstance(запись, dict) or строки:
            tmp = ovp + ".tmp"
            json.dump(ov, open(tmp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            os.replace(tmp, ovp)
        if перенос_fx:
            куда, kind = перенос_fx
            свежие = json.load(open(scenes_path, encoding="utf-8"))
            сп = свежие["scenes"] if isinstance(свежие, dict) else свежие
            for s in сп:
                try:
                    i = int(s.get("id", -1))
                except (TypeError, ValueError):
                    continue
                if i == sid:
                    s.pop("fx", None)
                elif i == куда:
                    s["fx"] = kind
            tmp = scenes_path + ".tmp"
            json.dump(свежие, open(tmp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            os.replace(tmp, scenes_path)
            строки.append("переход «%s» перенесён на сцену %d" % (kind, куда))

    if строки:
        print("сцена %d стала рисованной: %s" % (sid, ", ".join(строки)))
    return строки


def queue(scenes_path, sid, view, dur, watermark, channel, kwargs,
          anim=2.6, tail_zoom=0.045, card=None):
    """Положить задание в cards/queue/ и поставить сцене источник card:<вид>.

    Сцену правим ПОД ЗАМКОМ и с перечитыванием файла: соседние вкладки и
    фоновые проходы пишут тот же scenes.json, и правка молча откатывалась
    (разбор 22.10). Возвращает путь задания.
    """
    os.makedirs(QUEUE, exist_ok=True)
    # СЛОИ СЦЕНЫ ПЕРЕЕЗЖАЮТ ПЕРВЫМИ (09.11): сцена вот-вот станет рисованной,
    # а надпись и всплывашка на `card:*` запрещены. Делаем это ДО записи
    # задания, чтобы отказ «переносить некуда» не оставил полработы.
    перенести_слои(scenes_path, sid, view)
    # СНИМОК — В СВОЙ УГОЛ, ДО ЗАПИСИ ЗАДАНИЯ (09.11). Общая дверь трёх
    # инструментов из четырёх (`quote_card`, `style_card`, `element_put`);
    # четвёртый, `card_put`, зовёт те же две функции у себя.
    kwargs = dict(kwargs or {})
    if kwargs.get("photo"):
        check_photo(kwargs["photo"])
        kwargs["photo"] = keep_photo(sid, kwargs["photo"])
    job = {"scene": int(sid), "view": view, "dur": round(float(dur), 2),
           "anim": anim, "tail_zoom": tail_zoom,
           "watermark": watermark, "channel": channel,
           "kwargs": {k: v for k, v in (kwargs or {}).items()
                      if v not in ("", None, [], ())}}
    job["kwargs"]["watermark"] = watermark
    jpath = os.path.join(QUEUE, f"scene_{int(sid):03d}.json")
    json.dump(job, open(jpath, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        fresh = json.load(open(scenes_path, encoding="utf-8"))
        fscenes = fresh["scenes"] if isinstance(fresh, dict) else fresh
        tgt = next((x for x in fscenes if int(x.get("id", -1)) == int(sid)), None)
        if tgt is None:
            raise SystemExit(f"сцена {sid} исчезла из {scenes_path}")
        tgt["source"] = f"card:{view}"
        tgt["source_query"] = (f"карточка «{view}» — кадр рисуется в облаке, "
                               "фетч за сценой не идёт")
        if card:
            tgt["card"] = card
        tmp = scenes_path + ".tmp"
        json.dump(fresh, open(tmp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        os.replace(tmp, scenes_path)

        journal = json.load(open(JOURNAL, encoding="utf-8")) \
            if os.path.isfile(JOURNAL) else {}
        journal[str(int(sid))] = dict(card or {}, view=view, duration=round(float(dur), 2),
                                      queued=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(journal, open(JOURNAL, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    return jpath


def report(jpath, sid, view, scenes_path):
    print(f"задание записано: {jpath} (на машине не нарисовано НИЧЕГО)")
    print(f"сцене {sid} поставлен источник card:{view} — фетч за ней не пойдёт, "
          "в видео-лид не считается, эффекты на карточку не лягут")
    print("дальше, когда все карточки ролика поставлены:")
    # ЧЕРЕЗ `va.sh` И ТОЛЬКО ЧЕРЕЗ НЕЁ (09.11): с этого дня `cards_cloud.py`
    # без `VIDEORYAD_ACCOUNT` отказывается работать — цель он больше не
    # угадывает. Подсказку вкладка копирует целиком, поэтому и показываем
    # ровно ту команду, которая поедет.
    print(f"  bash {VA_CMD} <твоя цель> python3 {CLOUD_CMD} {scenes_path}")
    print("  (один облачный прогон на все карточки, клипы разложит сам)")
