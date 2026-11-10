#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ТЕМА СТАРТУЕТ ЦЕЛИКОМ И СРАЗУ — ВСЁ ПАРАЛЛЕЛЬНО (08.11.2026).

Его слово, сказанное трижды за день: «разумеется, рерайт начинать сразу по
тексту, не дожидаясь готового ролика. Зачем нам готовый ролик? У нас же всё
было готово, текст есть, SRT есть» и следом: «делать сразу и превьюшки, и
описания, и варианты заголовков, и варианты надписей на превью. Всё это можно
делать сразу же, немедленно».

ПОЧЕМУ РАНЬШЕ БЫЛО НЕ ТАК. Мы держали правило «внешний агент на машине ОДИН,
два задания разом не идут» — оно пришло из наблюдения 07.11 и 08.11 НЕ
подтвердилось: три задания, запущенные одновременно, вернули три своих ответа
за десять секунд. Похоже, прежний случай объяснялся не агентом, а обёрткой:
ответ кладётся рядом с брифом, и два задания по ОДНОМУ файлу затирали друг
друга. Теперь одинаковый бриф идёт по очереди, разные — параллельно
(`CODEX_PARALLEL`, по умолчанию три).

ЧТО ЗАПУСКАЕТ ЭТОТ ИНСТРУМЕНТ, получив папку темы и ключ георадара:
  1. задание на РЕРАЙТ второго канала и сам рерайт у агента;
  2. УПАКОВКУ: описание, десять заголовков, десять надписей, паттерн;
  3. ПЯТЬ ПРЕВЬЮ.
Всё тремя параллельными процессами, не дожидаясь ни раскадровки, ни фетча, ни
готового ролика первого канала. Раскадровку в это же время ведёт вкладка
канала — она четвёртая параллельная ветка.

    python3 tema_start.py "<папка темы>" --key ARM_… --channel-2 "ПЛАНЕТА"
    python3 tema_start.py "<папка темы>" --key ARM_… --only upakovka,prevyu

Печатает, что запущено и куда писать логи. Ничего не ждёт: процессы живут
сами, результат проверяется файлами в папке темы.
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ЛОГИ = "/tmp/videoryad-tema"


def канал_из_пути(path):
    части = os.path.abspath(path).replace("\\", "/").upper().split("/")
    for ч in части:
        for имя in ("5 МИНУТ", "ПЛАНЕТА", "ОЛЬКА НОВОСТИ", "ОЛЬКА",
                    "ДИПЛОМАТИЯ СИЛЫ", "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО"):
            if ч == имя or ч.startswith(имя + " "):
                return имя
    return ""


def запустить(имя, argv, лог):
    """Пускаем в фоне и возвращаем pid. Ничего не ждём."""
    os.makedirs(ЛОГИ, exist_ok=True)
    f = open(лог, "w")
    p = subprocess.Popen(argv, stdout=f, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    print("  ✓ %-10s pid %-7d лог: %s" % (имя, p.pid, лог))
    return p.pid


def main():
    ap = argparse.ArgumentParser(description="запустить тему целиком и параллельно")
    ap.add_argument("folder")
    ap.add_argument("--key", required=True, help="ключ георадара (ARM_… / PROD_…)")
    ap.add_argument("--channel-2", default="ПЛАНЕТА", dest="ch2",
                    help="канал, на который делается вторая статья")
    ap.add_argument("--only", default="", help="через запятую: rewrite,upakovka,prevyu")
    a = ap.parse_args()

    if not os.path.isdir(a.folder):
        sys.exit("нет папки: %s" % a.folder)
    ch1 = канал_из_пути(a.folder)
    тексты = [f for f in os.listdir(a.folder)
              if f.lower().endswith(".txt")
              and not any(s in f.upper() for s in
                          ("ЗАДАНИЕ", "УПАКОВКА", "ОТВЕТ", "ГЕОРАДАР", "РЕРАЙТ"))]
    if not тексты:
        sys.exit("в папке нет текста озвучки — запускать нечего")

    провал = False
    шаги = [s.strip() for s in (a.only or "rewrite,upakovka,prevyu").split(",") if s.strip()]
    метка = time.strftime("%H%M%S")
    база = os.path.basename(os.path.abspath(a.folder))[:28]
    os.makedirs(ЛОГИ, exist_ok=True)

    print("ТЕМА: %s" % база)
    print("  канал-источник: %s → второй канал: %s" % (ch1 or "не определён", a.ch2))
    print("  текст: %s" % тексты[0])
    print("ЗАПУСКАЮ ПАРАЛЛЕЛЬНО (ничего не жду):")

    if "rewrite" in шаги:
        # бриф пишется синхронно (секунды), агент — в фоне
        subprocess.run([sys.executable, os.path.join(HERE, "rewrite_brief.py"),
                        a.folder, "--key", a.key, "--channel", a.ch2],
                       check=False)
        задание = os.path.join(a.folder, "ЗАДАНИЕ-РЕРАЙТ.txt")
        if os.path.isfile(задание):
            запустить("рерайт", ["bash", os.path.join(HERE, "codex_ask.sh"), задание],
                      os.path.join(ЛОГИ, "rewrite-%s-%s.log" % (база, метка)))
        else:
            # МОЛЧАЛИВОГО ПРОВАЛА БОЛЬШЕ НЕТ (правка 10.11): раньше здесь
            # печаталась строка в лог фазы и код возврата оставался НУЛЕВЫМ —
            # вкладка рапортовала «вторая статья запущена в фоне», а статьи не
            # было. Теперь шаг признаётся провалившимся, и `faza.sh` говорит
            # «[СМОТРИ] вторая статья не запустилась» прямо в переписку.
            print("  !! ЗАДАНИЯ НА РЕРАЙТ НЕТ — вторая статья НЕ заказана, "
                  "см. вывод rewrite_brief.py выше")
            провал = True

    if "upakovka" in шаги:
        запустить("упаковка", [sys.executable, os.path.join(HERE, "upakovka.py"), a.folder],
                  os.path.join(ЛОГИ, "upakovka-%s-%s.log" % (база, метка)))

    if "prevyu" in шаги:
        запустить("превью", [sys.executable, os.path.join(HERE, "prevyu.py"), a.folder],
                  os.path.join(ЛОГИ, "prevyu-%s-%s.log" % (база, метка)))

    print("")
    if провал:
        print("")
        print("!! ОДНА ИЗ ВЕТОК НЕ ЗАПУСТИЛАСЬ — см. строки с «!!» выше.")
    print("Раскадровку первого канала вкладка ведёт ПАРАЛЛЕЛЬНО этим трём —")
    print("ждать их не нужно, они живут в своих процессах.")
    print("Проверка результата по файлам в папке темы:")
    print("  ЗАДАНИЕ-РЕРАЙТ.ОТВЕТ.txt · УПАКОВКА.json · превью-варианты/ПРЕВЬЮ-*.png")
    return 3 if провал else 0


if __name__ == "__main__":
    sys.exit(main())
