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
import json
import os
import subprocess
import time

QUEUE = os.path.join("cards", "queue")
JOURNAL = os.path.join("cards", "cards.json")
LOCK = os.path.join("cards", ".scenes.lock")
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUD_CMD = os.path.join(SKILL, "fullcycle", "cards_cloud.py")
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


def queue(scenes_path, sid, view, dur, watermark, channel, kwargs,
          anim=2.6, tail_zoom=0.045, card=None):
    """Положить задание в cards/queue/ и поставить сцене источник card:<вид>.

    Сцену правим ПОД ЗАМКОМ и с перечитыванием файла: соседние вкладки и
    фоновые проходы пишут тот же scenes.json, и правка молча откатывалась
    (разбор 22.10). Возвращает путь задания.
    """
    os.makedirs(QUEUE, exist_ok=True)
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
    print(f"  python3 {CLOUD_CMD} {scenes_path}")
    print("  (один облачный прогон на все карточки, клипы разложит сам)")
