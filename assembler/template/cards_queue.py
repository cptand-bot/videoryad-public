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
import sys
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
# НА НАШИХ ЭЛЕМЕНТАХ СЛОЁВ НЕ БЫВАЕТ — ОДИН ГЕЙТ И ОДНО ПОВЕДЕНИЕ (09.11)
#
# ЕГО ПРЯМОЕ СЛОВО, дважды за полчаса, второй раз с требованием «зашей в
# память и в скиллы, зашей жёстким правилом»:
#
#   «На наших элементах не должны быть ни надписей, ни всплывашек. Наши
#    элементы, которые мы делаем при помощи наших эффектов, точнее вот этих
#    карточек, которые в арсенале находятся. Там уже всё есть, там полный
#    цикл законченный всего, там не надо ничего больше иллюстрировать».
#
# Сцена с источником `card:<вид>` — ЛЮБОЙ рисованный кадр арсенала (карточка,
# цитата-лоскут, вырезка по контуру, стена улик, лента плёнки, слайдер,
# столбцы, досье, карта и остальные) — НЕ НЕСЁТ НИЧЕГО СВЕРХУ: ни
# фото-всплывашки, ни надписи (включая надпись из-под маски `mask_plate`), ни
# перехода `fx`, ни блика с пылинками.
#
# Блик/пылинки/зерно/виньетка на карточку не ложатся ПО ПОСТРОЕНИЮ: они
# живут в `fx.json` одним набором на ролик, а `build_clips_1080.py` держит
# `CARD_SIDS` и для таких сцен не добавляет ни фильтра, ни светового слоя.
# Поэтому здесь проверяется то, что ставится ПОШТУЧНО: записи
# `overlays.json`, поле `fx` сцены и видео-врезка `insets/scene_NNN.mp4`.
#
# ГРАНИЦА, КОТОРУЮ НЕЛЬЗЯ ПУТАТЬ (уточнение того же дня, 09.11).
#
# ЗАПРЕЩЕНО — НАЛОЖЕНИЯ ПОВЕРХ рисованного кадра:
#   * надпись и надпись из-под маски (`mask_plate`);
#   * фото-всплывашка;
#   * переход и эффект в поле `fx`;
#   * блик и пылинки;
#   * видео-врезка (ставится полем `fx: inset`, ловится вместе с ним);
#   * подпись-ЯРЛЫК внутри элемента, которая лишь называет то, что и так
#     видно: «Владимир Путин» на портрете Путина, заголовок «Дональд Трамп»
#     над его же фотографией. Это он и увидел на дашборде. КОДОМ НЕ ЛОВИТСЯ
#     (от законной подписи персоны в `vyrezka` её отличает только смысл) —
#     смотрит вкладка глазами на дашборде.
#
# РАЗРЕШЕНО И ТРОГАТЬ НЕЛЬЗЯ — текст, который и ЕСТЬ содержание элемента:
#   реплика в цитате-сплите (A35), числа и подписи к ним в `pie`, `bars`,
#   `slider`, `map`, `map_dist`, тезисы в `pull`, `wall`, `poster`,
#   `marker_serif`, `film_frame`, `photo`, строки в `dossier`. Без этого
#   текста элемент — пустая плашка, а половина обязательного набора как раз
#   такая. Его «там уже всё есть, полный цикл законченный» — ПРО них: они
#   закончены именно потому, что несут свой текст.
#
# Поэтому гейт смотрит ТОЛЬКО на наложения — записи `overlays.json` и поле
# `fx` по номеру рисованной сцены — и НИКОГДА на текст внутри задания
# карточки (`cards/queue/scene_NNN.json`). Иначе следующая вкладка снимет
# цитату из цитаты-сплита.
#
# Функции ниже — ЕДИНСТВЕННЫЙ источник правды для трёх мест: гейт дашборда
# (`selfcheck.py`), гейт полной сборки (`cloud/ship.sh` зовёт этот файл
# командой `--gate`) и сами инструменты постановки карточек. Разъехаться им
# нельзя: ровно на «инструментов два, правку получил один» 02.11 потерялась
# приёмка `card:timeline`.
ВИДЫ_МАСКИ = ("mask", "mask_plate")
РАДИУС_ПРИЮТА = 5      # как далеко от сцены ищем приют для слоя
ЗАЗОР_ВСПЛЫВАШЕК = 2   # две всплывашки подряд читаются как мельтешение
НА_СЦЕН_МАСКИ = 8.5    # норма надписей из-под маски (дубль из obyazatelno)
НА_СЦЕН_ФОТО = 7       # ориентир фото-всплывашек: одна на 6-7 сцен


def _всплывашка(запись):
    """Есть ли в записи overlays.json ФОТО-всплывашка (а не надпись)."""
    return bool(isinstance(запись, dict)
                and (запись.get("photo") or запись.get("query")
                     or запись.get("source")))


def _надпись(запись):
    return bool(isinstance(запись, dict) and (запись.get("text")
                                              or запись.get("words")))


def _маска(запись):
    """Надпись из-под маски (`style: mask` / `mask_plate`) — тоже НАДПИСЬ."""
    т = (запись or {}).get("text") if isinstance(запись, dict) else None
    if not isinstance(т, dict):
        return False
    return str(т.get("style", "")).strip().lower() in ВИДЫ_МАСКИ


def рисованная(сцена):
    return str((сцена or {}).get("source", "")).startswith("card:")


def _слои_сцены(сцена, запись, проект="."):
    """Что лежит ПОВЕРХ кадра этой сцены. Список имён, пустой — чисто."""
    виды = []
    if isinstance(запись, dict) and запись:
        if _надпись(запись):
            виды.append("надпись из-под маски" if _маска(запись) else "надпись")
        if _всплывашка(запись):
            виды.append("всплывашка")
        if not виды:
            виды.append("запись в overlays.json")
    kind = str((сцена or {}).get("fx", "")).strip().lower()
    if kind:
        виды.append("эффект/переход «%s»" % kind)
    # ВИДЕО-ВРЕЗКУ ОТДЕЛЬНО НЕ ЛОВИМ, И ЭТО НЕ НЕДОСМОТР: файл
    # `insets/scene_NNN.mp4` сам по себе не слой — `build_clips_1080.py`
    # берёт его ТОЛЬКО при `fx: inset`, а любое `fx` на карточке гейт уже
    # забраковал выше. Оставшийся от прежней разметки файл в кадр не попадает,
    # и валить из-за него сборку значило бы держать ролик на невидимке.
    return виды


def слои_на_карточках(scenes, ov=None, проект="."):
    """Нарушения правила. Список (sid, [виды слоёв]), по возрастанию сцены.

    `ov` — разобранный `overlays.json` (None: читаем из папки `проект`).
    """
    if ov is None:
        ov = {}
        try:
            with open(os.path.join(проект or ".", "overlays.json"),
                      encoding="utf-8") as fh:
                ov = json.load(fh) or {}
        except (OSError, ValueError):
            ov = {}
    if not isinstance(ov, dict):
        ov = {}
    наруш = []
    for s in (scenes or []):
        if not рисованная(s):
            continue
        try:
            sid = int(s.get("id", -1))
        except (TypeError, ValueError):
            continue
        виды = _слои_сцены(s, ov.get(str(sid)), проект)
        if виды:
            наруш.append((sid, виды))
    return sorted(наруш)


def отказ_слои(наруш):
    """Текст ЖЁСТКОГО отказа его словами. Пустой список — пустая строка."""
    if not наруш:
        return ""
    куски = "; ".join("%d (%s)" % (sid, ", ".join(в)) for sid, в in наруш)
    return (
        "НА НАШИХ ЭЛЕМЕНТАХ СЛОЁВ НЕ БЫВАЕТ, КАРТОЧКА — ЗАКОНЧЕННЫЙ КАДР. "
        "Сцены: %s.\n"
        "   Его прямое слово (09.11, дважды): «На наших элементах не должны "
        "быть ни надписей, ни всплывашек… там уже всё есть, там полный цикл "
        "законченный всего, там не надо ничего больше иллюстрировать».\n"
        "   На `card:*` не кладём НИЧЕГО: ни фото-всплывашку, ни надпись "
        "(включая надпись из-под маски), ни переход `fx`, ни блик с "
        "пылинками.\n"
        "   Лечение: сними запись этой сцены из `overlays.json` (руками или "
        "кнопкой «снять» на дашборде), поле `fx` — `fx_put.py <scenes.json> "
        "<сцена> --off`. "
        "Переносить на соседнюю сцену — только если иначе не выполняется "
        "норма (надписи из-под маски, фото-всплывашки, засвет A73); на "
        "другую рисованную сцену — НИКОГДА." % куски)


def обычных_сцен(scenes, кроме=None):
    """Сколько в ролике сцен БЕЗ рисованного кадра — знаменатель всех норм.

    09.11, его правило про чистые элементы: нормы надписей и всплывашек
    считаются только по обычным сценам. Иначе гейт запрещает слой на
    карточке, а норма его же требует — вкладка попадает в вилку и идёт
    третьим кругом правок. У роликов 09-10.11 карточек 15-17 из 67-71 сцены,
    то есть ЧЕТВЕРТЬ: норма 8 вместо 7 требовала надпись, которую некуда
    поставить.
    """
    кроме = set(int(x) for x in (кроме or []))
    n = 0
    for s in (scenes or []):
        try:
            sid = int(s.get("id", -1))
        except (TypeError, ValueError):
            sid = -1
        if sid in кроме or рисованная(s):
            continue
        n += 1
    return n


def _норма_fx(kind):
    """Сколько таких эффектов обязан нести ролик (0 — не обязателен)."""
    try:
        import obyazatelno as _ob
    except Exception:
        return 1 if str(kind).strip().lower() == "flash" else 0
    for el in getattr(_ob, "ОБЯЗАТЕЛЬНЫЕ", []):
        if str(el.get("fx", "")).strip().lower() == str(kind).strip().lower():
            return int(el.get("min") or 1)
    return 0


def перенести_слои(scenes_path, sid, вид=""):
    """Сцена стала рисованной: СНЯТЬ с неё слои, перенести — только по норме.

    ЕГО СЛОВО 09.11: «там не надо ничего больше иллюстрировать». Значит по
    умолчанию слой со сцены СНИМАЕТСЯ, а не переселяется: прежнее поведение
    (всегда переносить, некуда — стоп) плодило всплывашки и надписи там, где
    их никто не просил, и вставало на ровном месте.

    Переносим ТОЛЬКО когда без этого слоя просядет норма:
      * надписи из-под маски — одна на 8,5 обычных сцен (`obyazatelno`,
        элемент N-текст);
      * фото-всплывашки — одна на 7 обычных сцен;
      * эффект, который стоит в обязательном наборе (засвет A73).
    На другую РИСОВАННУЮ сцену не переносим никогда. Приюта нет — слой
    снимается, и об этом говорится громко: недостачу назовёт гейт
    (`selfcheck` / `obyazatelno`) числом, а не молчанием.

    Зовётся ДО того, как сцене поставлен источник `card:*`. Возвращает список
    напечатанных строк (пустой — трогать было нечего).
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
    рисованные = {i for i, s in по_id.items() if рисованная(s)}
    рисованные.add(sid)        # наша сцена ею сейчас и станет

    ovp = "overlays.json"
    ov = {}
    if os.path.isfile(ovp):
        try:
            ov = json.load(open(ovp, encoding="utf-8"))
        except (OSError, ValueError):
            ov = {}
    if not isinstance(ov, dict):
        ov = {}
    запись = ov.get(str(sid))
    если_словарь = isinstance(запись, dict)
    есть_fx = bool(str(по_id.get(sid, {}).get("fx", "")).strip())
    if not если_словарь and not есть_fx:
        return строки

    # ЗНАМЕНАТЕЛЬ НОРМ — ТОЛЬКО ОБЫЧНЫЕ СЦЕНЫ, наша уже не считается.
    обычных = max(1, обычных_сцен(сцены, кроме=[sid]))

    def слоёв_рода(род):
        """Сколько таких слоёв останется в ролике без нашей сцены."""
        n = 0
        for k, v in ov.items():
            if not str(k).isdigit() or int(k) == sid:
                continue
            if int(k) in рисованные:      # на карточке слоя быть не должно
                continue
            if род(v):
                n += 1
        return n

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
            # считать её помехой — значит не найти приют вообще.
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

    if если_словарь:
        if _надпись(запись):
            часть = {k: запись.pop(k) for k in ("text", "words") if k in запись}
            это_маска = str(((часть.get("text") or {}) if isinstance(
                часть.get("text"), dict) else {}).get("style", "")
            ).strip().lower() in ВИДЫ_МАСКИ
            норма = (max(1, int(round(обычных / float(НА_СЦЕН_МАСКИ))))
                     if это_маска else 0)
            осталось = слоёв_рода(_маска) if это_маска else 0
            имя = "надпись из-под маски" if это_маска else "надпись"
            if осталось >= норма:
                строки.append("%s СНЯТА (норма %d, в ролике остаётся %d)"
                              % (имя, норма, осталось))
            else:
                куда = приют_надписи(True) or приют_надписи(False)
                if куда is None:
                    строки.append(
                        "%s СНЯТА, перенести НЕКУДА (соседи в %d сценах либо "
                        "рисованные, либо со своим слоем) — норма %d, "
                        "остаётся %d, недостачу назовёт гейт"
                        % (имя, РАДИУС_ПРИЮТА, норма, осталось))
                else:
                    положить(куда, часть)
                    занятые.add(куда)
                    строки.append("%s перенесена на сцену %d (без неё норма "
                                  "%d не выполняется)" % (имя, куда, норма))
        if _всплывашка(запись):
            норма = обычных // int(НА_СЦЕН_ФОТО)
            осталось = слоёв_рода(_всплывашка)
            часть = {k: запись.pop(k) for k in list(запись)}
            if осталось >= норма:
                строки.append("всплывашка СНЯТА (ориентир %d, в ролике "
                              "остаётся %d)" % (норма, осталось))
            else:
                куда = приют_всплывашки(True)
                тесно = False
                if куда is None:
                    куда, тесно = приют_всплывашки(False), True
                if куда is None:
                    строки.append(
                        "всплывашка СНЯТА, перенести НЕКУДА — ориентир %d, "
                        "остаётся %d, недостачу назовёт гейт"
                        % (норма, осталось))
                else:
                    положить(куда, часть)
                    занятые.add(куда)
                    строки.append("всплывашка перенесена на сцену %d%s (без "
                                  "неё ориентир %d не выполняется)"
                                  % (куда, " (рядом есть другая — зазор "
                                           "тесный, посмотри глазами)"
                                     if тесно else "", норма))
        if not запись:
            ov.pop(str(sid), None)
        else:
            ov[str(sid)] = запись

    перенос_fx = None
    if есть_fx:
        kind = str(по_id[sid].get("fx", "")).strip()
        норма = _норма_fx(kind)
        осталось = sum(1 for i, s in по_id.items()
                       if i != sid and i not in рисованные
                       and str(s.get("fx", "")).strip().lower() == kind.lower())
        if осталось >= норма:
            перенос_fx = (None, kind)
            строки.append("эффект «%s» СНЯТ (норма %d, в ролике остаётся %d)"
                          % (kind, норма, осталось))
        else:
            куда = приют_fx()
            if куда is None:
                перенос_fx = (None, kind)
                строки.append(
                    "эффект «%s» СНЯТ, перенести НЕКУДА — он в обязательном "
                    "наборе (норма %d, остаётся %d), поставь его на обычную "
                    "сцену сам: fx_put.py --sid <сцена> --kind %s"
                    % (kind, норма, осталось, kind))
            else:
                перенос_fx = (куда, kind)
                строки.append("эффект «%s» перенесён на сцену %d (без него "
                              "норма %d не выполняется)" % (kind, куда, норма))

    # ЗАПИСЬ — ПОД ТЕМ ЖЕ ЗАМКОМ, ЧТО И ПРАВКА СЦЕНЫ. Соседние вкладки и
    # фоновые проходы пишут те же два файла; без замка правка откатывалась
    # молча (разбор 22.10, тот же механизм, что в `queue()`).
    os.makedirs("cards", exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        # ПУСТОЙ `overlays.json` НЕ СОЗДАЁМ (09.11). Карточки ставятся РАНЬШЕ
        # всплывашек, и файла в папке обычно ещё нет: запись пустого `{}`
        # сняла бы отказ «overlays.json НЕТ — всплывашки не расставлены» и
        # вкладка уехала бы на дашборд без слоя вообще.
        if если_словарь and (os.path.isfile(ovp) or ov):
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
                elif куда is not None and i == куда:
                    s["fx"] = kind
            tmp = scenes_path + ".tmp"
            json.dump(свежие, open(tmp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            os.replace(tmp, scenes_path)

    if строки:
        print("сцена %d стала рисованной, слоёв на ней не будет: %s"
              % (sid, "; ".join(строки)))
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


# ───────────────────────────────────────────────────────────────────────────
# ТОТ ЖЕ ОТКАЗ КОМАНДОЙ — ДЛЯ `cloud/ship.sh` (09.11)
#
# Дашборд держит `selfcheck.py`, он зовёт `слои_на_карточках` как функцию. У
# полной сборки гейт свой и на bash, а правок после `ship.sh` не бывает —
# поэтому там это отдельная команда, но правило и текст отказа те же, из
# этого файла. Два списка в двух местах разъезжаются при первой же правке.
#
#     python3 cards_queue.py --gate <scenes.json> [папка проекта]
#
# Код выхода 1 — слои на рисованных кадрах есть; 0 — чисто.
def _cli(argv):
    if not argv or argv[0] != "--gate":
        print(__doc__)
        print("гейт: python3 cards_queue.py --gate <scenes.json> [папка]")
        return 2
    if len(argv) < 2:
        print("нужен путь к scenes.json", file=sys.stderr)
        return 2
    путь = argv[1]
    проект = argv[2] if len(argv) > 2 else (os.path.dirname(
        os.path.abspath(путь)) or ".")
    try:
        данные = json.load(open(путь, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print("не прочитать %s (%s)" % (путь, e), file=sys.stderr)
        return 2
    сцены = данные["scenes"] if isinstance(данные, dict) else данные
    наруш = слои_на_карточках(сцены, None, проект)
    if not наруш:
        n = sum(1 for s in сцены if рисованная(s))
        print("✅ рисованные кадры чистые (%d карточек, слоёв ни на одной)" % n)
        return 0
    print("❌ " + отказ_слои(наруш))
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
