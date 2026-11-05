#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЗАБРАТЬ ПАПКУ ПОЛЬЗОВАТЕЛЯ ЦЕЛИКОМ, ОДНИМ СКОПОМ — ПЕРВЫМ ШАГОМ.

    python3 take_folder.py "<папка пользователя на D:>" <папка проекта>

ПРЯМОЕ СЛОВО ПОЛЬЗОВАТЕЛЯ 04.11, после потерянного получаса:
«зашить во все скиллы, во все репозитарии, во всё, что можно, в память,
чтобы такого больше не повторялось: всё сразу забирать с собой, одним
скопом. И не делать сборку видео, пока не убедитесь, что всё вошло туда».

Повод: озвучка и SRT лежали в его папке с самого начала, вкладка взяла
только `.srt`, а `.mp3` остался там же — и готовый файл на 476 МБ приехал
НЕМЫМ. Правок после `ship.sh` не бывает, значит цена — полная пересборка.

ЧТО ДЕЛАЕТ: копирует из его папки ВСЁ, что может понадобиться сборке
(`.srt`, `.mp3`, `.wav`, `.m4a`, `.txt`, `.ass`, `.json`), приводит озвучку
к имени `narration.<ext>`, запоминает исходную папку в `.source_dir` — её
потом читает `ship.sh`, когда ищет голос, — и печатает, что именно взято.
Ничего не удаляет и не перезаписывает уже существующее без нужды.
"""
import argparse
import os
import shutil
import sys

TAKE = (".srt", ".mp3", ".wav", ".m4a", ".txt", ".ass", ".json")
VOICE = (".mp3", ".wav", ".m4a")



# МЕДИАТЕКА КАНАЛА — СТАВИТСЯ САМА (улов 05.11, `usuario-e4`).
# В `template/.env` строки `MEDIA_LIBRARY_DIR` НЕТ ВООБЩЕ, а умолчание во всех
# читателях — `media-library`. Значит вкладка канала 5 МИНУТ, честно
# скопировав шаблон, молча получала ЧУЖУЮ медиатеку: сцены `local_library`
# не находились, уезжали в поиск, и ошибка не кричала ничем. Важное
# поведение не должно висеть на необязательном ключе, поэтому строка теперь
# пишется ЗДЕСЬ — на обязательном первом шаге, где канал и так известен
# из ПУТИ к его папке.
# Раскладка каналов (память `feedback_media_library_channel_mapping`):
#   media-library   — ПЛАНЕТА, ОЛЬКА
#   media-library-2 — 5 МИНУТ, ДИПЛОМАТИЯ СИЛЫ, ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО
LIB2 = ("5 МИНУТ", "ДИПЛОМАТИЯ СИЛЫ", "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО",
        "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО ЯЗЫКА")
LIB1 = ("ПЛАНЕТА", "ОЛЬКА")


def channel_of(path):
    """Канал берётся из ПУТИ и только из пути — он главнее георадара и
    главнее того, что написано в листе `Productions` (живой случай 28.10)."""
    parts = [x.strip().upper() for x in os.path.abspath(path).replace("\\", "/").split("/")]
    for want in LIB2 + LIB1:
        if want in parts:
            return want
    return ""


def ensure_env(dst, channel):
    """Кладёт в папку проекта `.env` и ставит в нём медиатеку канала.
    Чужое значение НЕ переписывает молча — говорит вслух."""
    env = os.path.join(dst, ".env")
    tmpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env):
        if not os.path.exists(tmpl):
            print("!! нет шаблона %s — .env собери руками" % tmpl, file=sys.stderr)
            return
        shutil.copy2(tmpl, env)
        print(".env взят из шаблона скилла")
    if not channel:
        print("!! КАНАЛ ИЗ ПУТИ НЕ УЗНАН — медиатеку в .env поставь сама "
              "(MEDIA_LIBRARY_DIR=media-library | media-library-2)", file=sys.stderr)
        return
    want = "media-library-2" if channel in LIB2 else "media-library"
    # ПУТЬ ПИШЕМ АБСОЛЮТНЫЙ: голое имя папки нормализует `fetch_assets_news`
    # и `check_pins`, но читателей у ключа больше десятка, и ручаться за
    # каждого нечем. Абсолютный путь одинаково понимают все.
    want_path = os.path.expanduser("~/projects/" + want)
    lines = open(env, encoding="utf-8").read().splitlines()
    have = [i for i, ln in enumerate(lines) if ln.strip().startswith("MEDIA_LIBRARY_DIR=")]
    if have:
        cur = lines[have[0]].split("=", 1)[1].strip()
        if os.path.basename(cur.rstrip("/")) != want:
            print("!! в .env уже стоит MEDIA_LIBRARY_DIR=%s, а каналу %s нужна "
                  "%s — не трогаю, разберись руками" % (cur, channel, want),
                  file=sys.stderr)
        else:
            print("медиатека канала %s: %s (уже стояла)" % (channel, want))
        return
    lines.append("MEDIA_LIBRARY_DIR=%s" % want_path)
    t = env + ".tmp"
    with open(t, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(t, env)
    print("медиатека канала %s: %s (дописано в .env)" % (channel, want_path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="папка пользователя (та, где лежит SRT)")
    ap.add_argument("dst", help="папка проекта")
    ap.add_argument("--force", action="store_true",
                    help="перезаписать уже лежащие файлы")
    a = ap.parse_args()
    if not os.path.isdir(a.src):
        sys.exit("нет папки: %s" % a.src)
    os.makedirs(a.dst, exist_ok=True)

    took, skipped, voice = [], [], ""
    for name in sorted(os.listdir(a.src)):
        p = os.path.join(a.src, name)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in TAKE:
            continue
        # озвучку кладём под каноническим именем: его ищет ship.sh и облако
        if ext in VOICE and not name.lower().startswith("sfx"):
            out = os.path.join(a.dst, "narration" + ext)
            voice = name
        else:
            out = os.path.join(a.dst, name)
        if os.path.exists(out) and not a.force:
            skipped.append(name)
            continue
        shutil.copy2(p, out)
        took.append("%s → %s" % (name, os.path.basename(out)))

    with open(os.path.join(a.dst, ".source_dir"), "w", encoding="utf-8") as f:
        f.write(os.path.abspath(a.src) + "\n")

    print("забрано из %s:" % a.src)
    for t in took:
        print("  " + t)
    if skipped:
        print("уже лежало (не трогал, --force перезапишет): %s"
              % ", ".join(skipped))
    print("исходная папка запомнена в .source_dir")
    ensure_env(a.dst, channel_of(a.src))

    srt = [f for f in os.listdir(a.dst) if f.lower().endswith(".srt")]
    nar = [f for f in os.listdir(a.dst)
           if f.lower().startswith("narration") and
           os.path.splitext(f)[1].lower() in VOICE]
    print()
    print("SRT: %s" % (", ".join(srt) if srt else "НЕТ"))
    print("ОЗВУЧКА: %s" % (nar[0] if nar else "НЕТ"))
    if not srt or not nar:
        print()
        print("!! КОМПЛЕКТ НЕ ПОЛНЫЙ. Полную сборку начинать НЕЛЬЗЯ: "
              "«не делать сборку видео, пока не убедитесь, что всё вошло "
              "туда» (его слово 04.11).", file=sys.stderr)
        print("   Посмотри, что лежит в его папке, и забери руками:",
              file=sys.stderr)
        for n in sorted(os.listdir(a.src))[:30]:
            print("     " + n, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
