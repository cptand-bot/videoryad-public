# -*- coding: utf-8 -*-
"""ГЕЙТ МОДЕЛИ: РОЛИК НЕ СОБИРАЕТСЯ НА ДОРОГОЙ МОДЕЛИ (16.11.2026).

Его требование 16.11, дословно: «мне такая хрень не нужна, я должен 100%,
150% быть уверенным в том, что работают дешёвые модели. А не „я найду, если
увижу“… Жёстко зашить». Прежняя правка завела дешёвых субагентов и записала
правило в четыре места — но правило, которое держится ТЕКСТОМ, обходят,
позвав инструмент напрямую (урок 11.11, повторился трижды за день). Поэтому
здесь гейт: фазы ролика и сдача ОТКАЗЫВАЮТ, если вкладка сидит на дорогой
модели.

КАК УЗНАЁМ МОДЕЛЬ. Переменной окружения с моделью нет, хуку её тоже не дают
(проверено по документации 16.11). Но каждая сессия пишет свой транскрипт
`~/.claude/projects/<проект>/<id>.jsonl`, и в каждой записи ответа стоит
`message.model`. Берём САМЫЙ СВЕЖИЙ транскрипт: та вкладка, которая прямо
сейчас позвала этот скрипт, писала в него секунды назад. Окно свежести —
`--okno` секунд (по умолчанию 300). Транскрипта нет или он старый — гейт
МОЛЧИТ и пропускает: глухая блокировка на пустом месте дороже, чем дорогая
модель (правило «умолчание должно быть рабочим»).

ЧТО СЧИТАЕТСЯ ДОРОГИМ: `opus`. Дешёвые — `sonnet`, `haiku`. Неизвестную
модель гейт считает ДЕШЁВОЙ: иначе завтрашняя новая модель встанет поперёк
конвейера.

КОМУ МОЖНО. Координатору — он не ведёт ролики, а раздаёт темы и правит код;
его шаги гейт не трогает, потому что `faza.sh` и `ship.sh` зовёт только
рабочая вкладка. Разовый обход — `VIDEORYAD_MODEL_OK=1`, и он печатается в
журнал проверок, то есть виден в отчёте.

    python3 template/model_gate.py            # код 1, если дорогая модель
    python3 template/model_gate.py --tiho     # без вывода, только код
"""

import argparse
import glob
import json
import os
import sys
import time

ДОРОГИЕ = ("opus",)
ПРОЕКТЫ = os.path.expanduser("~/.claude/projects")


def модель_сессии(okno=300):
    """(модель, путь) самой свежей сессии или (None, '')."""
    лучший, когда = "", 0.0
    for ф in glob.glob(os.path.join(ПРОЕКТЫ, "*", "*.jsonl")):
        try:
            t = os.path.getmtime(ф)
        except OSError:
            continue
        if t > когда:
            лучший, когда = ф, t
    if not лучший or (time.time() - когда) > okno:
        return None, ""
    # ищем последнюю запись с моделью — с конца файла, не читая его целиком
    try:
        with open(лучший, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            размер = fh.tell()
            хвост = b""
            шаг = 65536
            while размер > 0 and len(хвост) < 2_000_000:
                назад = min(шаг, размер)
                размер -= назад
                fh.seek(размер)
                хвост = fh.read(назад) + хвост
                for стр in reversed(хвост.split(b"\n")):
                    if b'"model"' not in стр:
                        continue
                    try:
                        z = json.loads(стр.decode("utf-8", "ignore"))
                    except Exception:
                        continue
                    м = ((z.get("message") or {}).get("model")
                         or z.get("model") or "")
                    if м and "synthetic" not in str(м):
                        return str(м), лучший
    except OSError:
        pass
    return None, лучший


def дорогая(модель):
    return any(к in str(модель or "").lower() for к in ДОРОГИЕ)


def проверить(okno=300, tiho=False, zachem="ролик"):
    if os.environ.get("VIDEORYAD_MODEL_OK") == "1":
        if not tiho:
            print("  гейт модели снят ключом VIDEORYAD_MODEL_OK=1 — отмечено "
                  "в журнале проверок")
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import proverki
            proverki.otmetit("gate", "ОБХОД гейта модели (VIDEORYAD_MODEL_OK)",
                             os.path.basename(os.getcwd()))
        except Exception:
            pass
        return 0
    м, путь = модель_сессии(okno)
    if not м:
        return 0            # не смогли определить — не мешаем работе
    if not дорогая(м):
        if not tiho:
            print("  модель вкладки: %s — дешёвая, работаем" % m_short(м))
        return 0
    if not tiho:
        print("ОТКАЗ: %s собирается на ДОРОГОЙ модели (%s).\n"
              "  Его требование 16.11: «я должен 100%%, 150%% быть уверенным "
              "в том, что работают дешёвые модели… жёстко зашить».\n"
              "  Переключи вкладку: /model sonnet — и повтори команду.\n"
              "  Сильная модель остаётся координатору и смысловым шагам "
              "(запросы, наполнение карточек), а фазы ролика и сдача идут на "
              "Sonnet.\n"
              "  Если это осознанное исключение — VIDEORYAD_MODEL_OK=1 перед "
              "командой; обход попадёт в отчёт `proverki.py`."
              % (zachem, m_short(м)), file=sys.stderr)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import proverki
        proverki.otmetit("gate", "гейт модели: вкладка на %s" % m_short(м),
                         os.path.basename(os.getcwd()))
    except Exception:
        pass
    return 1


def m_short(м):
    return str(м or "").split("-2026")[0]


def main():
    ap = argparse.ArgumentParser(description="гейт дорогой модели")
    ap.add_argument("--okno", type=int, default=300,
                    help="сколько секунд транскрипт считается свежим")
    ap.add_argument("--tiho", action="store_true")
    ap.add_argument("--zachem", default="ролик")
    a = ap.parse_args()
    return проверить(a.okno, a.tiho, a.zachem)


if __name__ == "__main__":
    sys.exit(main())
