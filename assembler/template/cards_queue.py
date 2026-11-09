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


def queue(scenes_path, sid, view, dur, watermark, channel, kwargs,
          anim=2.6, tail_zoom=0.045, card=None):
    """Положить задание в cards/queue/ и поставить сцене источник card:<вид>.

    Сцену правим ПОД ЗАМКОМ и с перечитыванием файла: соседние вкладки и
    фоновые проходы пишут тот же scenes.json, и правка молча откатывалась
    (разбор 22.10). Возвращает путь задания.
    """
    os.makedirs(QUEUE, exist_ok=True)
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
