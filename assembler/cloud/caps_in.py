#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caps_in.py — положить `captions.ass` в папку задания, не коммитя его.

Зачем (09.11, закрытие утечки). `captions.ass` — это ВЕСЬ текст сценария
дословно (241 строка на `5min-oreshnik-1011`). Пока он ехал в облако файлом
в `queue/<ролик>`, он оставался в истории ПУБЛИЧНОГО репозитория навсегда:
уборка очереди снимает файл с HEAD, но блоб достаётся по SHA старого
коммита. Вычистка текста из `scenes.json` при этом не значила ничего — тот
же текст лежал рядом в полном виде.

Приём взят у рабочего `ozvuchka.yml`: содержимое едет ВХОДОМ ЗАПУСКА
(`workflow_dispatch`), сжатое gzip и закодированное base64. Замер наших
файлов: сырой 28-45 КБ → после gzip+base64 10,6-16,6 КБ; предел входов
`workflow_dispatch` — 65 535 символов на все входы, то есть запас вчетверо.

Почему отдельным файлом, а не строкой в workflow: значение берётся из
ПЕРЕМЕННОЙ ОКРУЖЕНИЯ и ни разу не попадает ни в текст команды, ни в вывод.
Actions печатает текст шага в лог, а логи публичного репозитория открыты
всем — подставь полезную нагрузку прямо в команду, и утечка просто
переедет из истории git в логи. Здесь в stdout уходят только числа.

Использование (на раннере):
    CAPS=<gzip+base64> CAPS_FOR=<имя ролика> \
        python3 caps_in.py <папка задания> <имя ролика>

Коды возврата:
    0 — файл на месте (приехал входом, лежал в задании или нечего делать)
    1 — вход есть, но он битый: не распаковался либо в нём нет ни одной
        строки `Dialogue`. Это именно ОШИБКА, а не «субтитров нет»: иначе
        ролик уехал бы с одной строкой на весь хронометраж, и увидели бы
        это только в готовом файле.
"""
import base64
import binascii
import gzip
import os
import sys


def dialogues(path):
    """Сколько строк субтитров реально в файле. Проверяем РЕЗУЛЬТАТОМ, а не
    наличием файла: пустой или обрезанный `.ass` даёт ноль строк в видео."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return sum(1 for ln in f if ln.startswith("Dialogue"))
    except OSError:
        return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 0
    proj, name = argv[0], argv[1]
    dest = os.path.join(proj, "captions.ass")

    # 1. файл уже в задании — так работает вкладка со СТАРЫМ ship.sh. Этот
    #    путь намеренно оставлен рабочим: раскатка кода и обновление вкладок
    #    не одномоментны, и ломать идущие ролики нельзя.
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        print("субтитры: файл уже в задании (старый путь), строк %d"
              % dialogues(dest))
        return 0

    payload = os.environ.get("CAPS", "")
    if not payload:
        print("субтитры: входа caps нет — остаётся кэш прошлого прогона")
        return 0

    # 2. защита от ЧУЖОЙ полезной нагрузки: прогон мог быть запущен под один
    #    ролик, а очередь к этому моменту отдать другой (ночной cron берёт
    #    `ls -d queue/*/ | head -1`). Положить чужие субтитры хуже, чем не
    #    положить никаких.
    want = os.environ.get("CAPS_FOR", "")
    if want and want != name:
        print("субтитры: вход адресован ролику %r, собираю %r — НЕ применяю"
              % (want, name))
        return 0

    try:
        raw = gzip.decompress(base64.b64decode(payload, validate=True))
    except (binascii.Error, ValueError, OSError, EOFError) as e:
        print("субтитры: вход caps НЕ РАСПАКОВАЛСЯ (%s). Ждал gzip+base64."
              % type(e).__name__)
        return 1

    os.makedirs(proj, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(raw)
    n = dialogues(dest)
    if n < 1:
        os.remove(dest)
        print("субтитры: во входе caps нет ни одной строки Dialogue — "
              "файл не оставляю")
        return 1
    print("субтитры: приехали входом запуска, строк %d, байт %d"
          % (n, len(raw)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
