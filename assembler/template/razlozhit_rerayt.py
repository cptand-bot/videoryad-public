#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Положить готовую вторую статью в ЗЕРКАЛЬНУЮ папку второго канала.

ЗАЧЕМ (блокер, 11.11, `НА-РАСКАТКУ` п.2). `tema_start.py` заказывает вторую
статью и кладёт ответ агента в папку ПЕРВОГО канала
(`ЗАДАНИЕ-РЕРАЙТ.ОТВЕТ.txt`). Шага «положить готовый текст в папку второго
канала» в коде НЕ БЫЛО — он был описан в ПОРЯДКЕ-ДНЯ как РУЧНОЙ, и вкладка
второго канала стояла, пока кто-то не разложит руками. Потерянный час на
каждой теме и блокер для схемы «один ключ на все каналы».

Ждём ответ (он пишется агентом в фоне), затем кладём его текстом в
зеркальную папку: тот же день, тот же номер темы, другой канал. Имя файла —
как принято у пользователя: «<основа> <канал нижним регистром>.txt».
Дальше текст подхватывает сторож озвучки, как любой другой.

    python3 razlozhit_rerayt.py "<папка темы 1-го канала>" --channel-2 ПЛАНЕТА [--wait 45]
"""
import argparse
import os
import re
import subprocess
import sys
import time

# Суффикс имени файла по каналу — ровно так пользователь называет тексты.
СУФФИКС = {
    "5 МИНУТ": "5 минут",
    "ПЛАНЕТА": "планета",
    "ДИПЛОМАТИЯ СИЛЫ": "дипломатия силы",
    "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО": "перевод",
    "ОЛЬКА": "олька",
}
СЛУЖЕБНЫЕ = ("ЗАДАНИЕ", "БРИФ", "ОТВЕТ", "УПАКОВКА", "ГЕОРАДАР", "РЕРАЙТ",
             "СОСТОЯНИЕ", "ДЛЯ-ВКЛАДКИ", "ССЫЛКИ", "ПРОМПТ", "ДОСЬЕ",
             "АУДИТ", "СТАТЬЯ", "СПИСОК")


def суффикс(канал):
    к = (канал or "").strip().upper()
    if к in СУФФИКС:
        return СУФФИКС[к]
    return к.split()[0].lower() if к else ""


def канал_из_пути(path):
    """Канал — это сегмент сразу после каталога НОВОСТИ (правило скилла)."""
    части = os.path.abspath(path).replace("\\", "/").split("/")
    for i, ч in enumerate(части):
        if ч.upper() == "НОВОСТИ" and i + 1 < len(части):
            return части[i + 1]
    return ""


def текст_темы(папка):
    """Самый большой содержательный .txt — как в `rewrite_brief.find_text`."""
    канд = [f for f in os.listdir(папка)
            if f.lower().endswith(".txt")
            and not any(s in f.upper() for s in СЛУЖЕБНЫЕ)]
    if not канд:
        return ""
    return max(канд, key=lambda f: os.path.getsize(os.path.join(папка, f)))


def основа(имя_файла, канал1):
    """«Лавров РЕЗКИЙ ОТКАЗ 5 минут.txt» -> «Лавров РЕЗКИЙ ОТКАЗ»."""
    стем = os.path.splitext(имя_файла)[0]
    с = суффикс(канал1)
    if с and стем.lower().endswith(с.lower()):
        стем = стем[: -len(с)]
    return стем.strip(" -–—")


def зеркальная_папка(папка1, канал1, канал2):
    """Тот же день, тот же номер темы, другой канал."""
    абс = os.path.abspath(папка1)
    части = абс.split(os.sep)
    try:
        i = [ч.upper() for ч in части].index("НОВОСТИ")
    except ValueError:
        return ""
    если_есть = list(части)
    если_есть[i + 1] = канал2
    прямой = os.sep.join(если_есть)
    if os.path.isdir(прямой):
        return прямой
    # Имя темы у второго канала может отличаться регистром или словом —
    # ищем по НОМЕРУ темы («1-», «2-»…) внутри того же дня.
    день = os.sep.join(если_есть[:-1])
    номер = re.match(r"\s*(\d+)\s*-", части[-1])
    if номер and os.path.isdir(день):
        for d in sorted(os.listdir(день)):
            if os.path.isdir(os.path.join(день, d)) and \
               re.match(r"\s*%s\s*-" % номер.group(1), d):
                return os.path.join(день, d)
    return прямой          # папки ещё нет — создадим её сами


def main():
    ap = argparse.ArgumentParser(
        description="разложить готовую вторую статью в папку второго канала")
    ap.add_argument("folder", help="папка темы ПЕРВОГО канала")
    ap.add_argument("--channel-2", dest="ch2", required=True,
                    help="канал, на который написана вторая статья")
    ap.add_argument("--wait", type=int, default=45,
                    help="сколько минут ждать ответ агента (по умолчанию 45)")
    ap.add_argument("--otvet", default="",
                    help="путь к готовому ответу, если он лежит не там")
    ap.add_argument("--bez-linta", dest="bez_linta", action="store_true",
                    help="разложить БЕЗ проверки rewrite_lint (только по его "
                         "прямому слову)")
    a = ap.parse_args()

    if not os.path.isdir(a.folder):
        sys.exit("нет папки: %s" % a.folder)
    канал1 = канал_из_пути(a.folder)
    ответ = a.otvet or os.path.join(a.folder, "ЗАДАНИЕ-РЕРАЙТ.ОТВЕТ.txt")

    # ЖДЁМ ОТВЕТ. Он пишется в фоне агентом; пустой или растущий файл
    # раскладывать нельзя — вкладка второго канала начнёт работать по огрызку.
    дедлайн = time.time() + a.wait * 60
    прошлый = -1
    while time.time() < дедлайн:
        if os.path.isfile(ответ):
            р = os.path.getsize(ответ)
            if р > 2000 and р == прошлый:
                break
            прошлый = р
        time.sleep(20)
    else:
        print("!! вторая статья не появилась за %d мин — %s" % (a.wait, ответ))
        return 3
    if not os.path.isfile(ответ) or os.path.getsize(ответ) <= 2000:
        print("!! ответ пустой или слишком короткий: %s" % ответ)
        return 3

    имя1 = текст_темы(a.folder)
    if not имя1:
        print("!! в папке первого канала нет текста — не от чего взять имя")
        return 3
    новое = "%s %s.txt" % (основа(имя1, канал1), суффикс(a.ch2))
    куда = зеркальная_папка(a.folder, канал1, a.ch2)
    if not куда:
        print("!! не удалось вычислить папку второго канала от %s" % a.folder)
        return 3
    os.makedirs(куда, exist_ok=True)
    цель = os.path.join(куда, новое)
    if os.path.isfile(цель) and os.path.getsize(цель) > 2000:
        print("текст второго канала уже лежит, не трогаю: %s" % цель)
        return 0
    # ЛИНТ — ГЕЙТ, А НЕ СОВЕТ (12.11, его слово: «вчера был проеб по ним, один
    # крючок оставался нетронутым»). Проверка крючка в `rewrite_lint.py`
    # появилась 11.11, но звали её РУКАМИ из ПОРЯДКА-ДНЯ — и текст с
    # непереписанным началом спокойно лёг в папку второго канала. Единственное
    # горлышко, через которое статья обязана пройти, — вот этот шаг: здесь и
    # держим. Осознанно мимо: --bez-linta (его прямое слово, не «так быстрее»).
    if not a.bez_linta:
        исходник = os.path.join(a.folder, имя1)
        задание = os.path.join(a.folder, "ЗАДАНИЕ-РЕРАЙТ.txt")
        кмд = [sys.executable,
               os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "rewrite_lint.py"), исходник, ответ]
        if os.path.isfile(задание):
            кмд += ["--brief", задание]
        п = subprocess.run(кмд, capture_output=True, text=True)
        print(п.stdout or "", end="")
        if п.returncode != 0:
            print(п.stderr or "", end="", file=sys.stderr)
            print("!! ВТОРАЯ СТАТЬЯ НЕ РАЗЛОЖЕНА: линт не пройден.", file=sys.stderr)
            print("   Перепиши названное (крючок — в первую очередь) и "
                  "повтори этот шаг.", file=sys.stderr)
            return 4

    with open(ответ, encoding="utf-8", errors="replace") as fh:
        тело = fh.read().strip() + "\n"
    with open(цель, "w", encoding="utf-8") as fh:
        fh.write(тело)
    print("вторая статья разложена: %s (%d знаков)" % (цель, len(тело)))
    print("дальше её берёт сторож озвучки — руками класть ничего не нужно.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
