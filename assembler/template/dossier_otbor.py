#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОТБОР ВЛОЖЕНИЙ ДОСЬЕ — ДО ПОСТАНОВКИ В СЦЕНЫ, А НЕ ПОСЛЕ АУДИТА.

Улов 85 (14.11, вкладка `usuario-4b`, ключ 367): аудит листов забраковал
ОДИННАДЦАТЬ сцен из пятнадцати, и все одиннадцать — вложения досье:
скриншоты публикаций с чужими логотипами (NYT, Bloomberg, испанская и
немецкая пресса), плашки телеэфира, вшитые английские и русские субтитры.
Из досье уцелела ОДНА сцена. Круг правок на одиннадцать сцен плюс заход к
агенту — впустую.

Порядок работал против себя: правило 02.11 (обязательная проверка вложений
по ключу) и гейт `dossier_use` ЗАСТАВЛЯЮТ ставить эти кадры в сцены, а аудит
их потом выбрасывает. Разбор дешевле постановки: канал-ПЕРЕСКАЗЧИК своих
кадров не снимает вовсе — под текст про переговоры он кладёт скриншот
первоисточника, и это видно по АДРЕСУ ПОСТА, до любого скачивания.

    python3 template/dossier_otbor.py tg.json                # только разбор
    python3 template/dossier_otbor.py tg.json --pisat         # + tg_rejected.json

Отклонённое ложится в `tg_rejected.json` с причиной — тем самым файлом, что
`dossier_use` считает «разобрано и отклонено». Значит фетч не держится, круг
правок не тратится, а причина остаётся видна в проекте.

ЧТО ОТБИВАЕТСЯ ЗДЕСЬ (всё — по метаданным поста, без скачивания и OCR):
  * канал-пересказчик из списка `tg_media.RETELLERS`;
  * видео, которого телеграм не отдаёт (`not_supported`);
  * вертикальное видео (в горизонтальный кадр не ложится);
  * постер видео вместо фото ниже порога сцены;
  * фото ниже 800 px по длинной стороне (порог сцены с 05.11).
ЧТО ОТБИВАЕТСЯ ПОЗЖЕ, В ОБЛАКЕ (OCR на раннере, не на его машине):
  плашки телеэфира, логотипы изданий и плотный текст скриншота —
  `fetch_assets_news._accept_direct_photo`.
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ПОРОГ = 800          # px по длинной стороне, порог сцены для вложений (05.11)


def _retellers():
    """Список каналов-пересказчиков берём у `tg_media`, а не повторяем.

    Два списка в двух файлах расходятся — это тот же урок, что с видами
    эффектов: забытый во втором вид молча выбрасывается.
    """
    try:
        sys.path.insert(0, HERE)
        import tg_media
        return tuple(getattr(tg_media, "RETELLERS", ()) or ())
    except Exception:
        return ()


def _kanal(url):
    т = str(url or "").split("t.me/", 1)[-1]
    return т.split("/", 1)[0].strip().lower().lstrip("@")


def _pereskazchik(url, retellers):
    к = _kanal(url)
    return any(к.startswith(x) or x in к for x in retellers) if к else False


def _storona(размер):
    """Длинная сторона из строки «800x450» или пары."""
    try:
        if isinstance(размер, (list, tuple)) and len(размер) >= 2:
            return max(int(размер[0]), int(размер[1]))
        ш, в = str(размер).lower().split("x")[:2]
        return max(int(ш), int(в))
    except (ValueError, TypeError, IndexError):
        return 0


def _vertikal(размер):
    try:
        ш, в = str(размер).lower().split("x")[:2]
        return int(в) > int(ш)
    except (ValueError, TypeError, IndexError):
        return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    писать = "--pisat" in sys.argv
    if not args:
        sys.exit(__doc__)
    путь = args[0]
    if not os.path.isfile(путь):
        sys.exit("нет файла: %s" % путь)
    данные = json.load(io.open(путь, encoding="utf-8"))
    посты = данные if isinstance(данные, list) else данные.get("posts", [])
    retellers = _retellers()

    отклонено, годные = {}, []
    for p in посты:
        пост = p.get("url") or p.get("post") or ""
        пересказ = _pereskazchik(пост, retellers)
        размеры = p.get("poster_size") or {}
        постеры = set(p.get("video_posters") or [])
        for ф in (p.get("photos") or []):
            сторона = _storona(размеры.get(ф, ""))
            if пересказ:
                отклонено[ф] = ("канал-пересказчик %s: своих кадров не "
                                "снимает, под текст кладёт скриншот "
                                "первоисточника" % ("@" + _kanal(пост)))
            elif ф in постеры and сторона and сторона < ПОРОГ:
                отклонено[ф] = ("постер видео %s ниже порога сцены %d px"
                                % (размеры.get(ф, "?"), ПОРОГ))
            elif сторона and сторона < ПОРОГ:
                отклонено[ф] = ("фото %s ниже порога сцены %d px по длинной "
                                "стороне" % (размеры.get(ф, "?"), ПОРОГ))
            else:
                годные.append((пост, "фото", ф))
        for v in (p.get("videos") or []):
            адрес = v.get("url") if isinstance(v, dict) else v
            размер = (v.get("size") or v.get("resolution") or "") if isinstance(v, dict) else ""
            if пересказ:
                отклонено[адрес or пост] = (
                    "канал-пересказчик %s: видео у него — переснятый чужой "
                    "эфир с клеймом" % ("@" + _kanal(пост)))
            elif not адрес or адрес == "not_supported":
                отклонено[пост] = ("телеграм не отдаёт файл видео "
                                   "(`not_supported`) — круги на ?embed=1 не "
                                   "тратить")
            elif _vertikal(размер):
                отклонено[адрес] = ("вертикальное видео %s — в горизонтальный "
                                    "кадр не ложится" % размер)
            elif _storona(размер) and _storona(размер) < ПОРОГ:
                отклонено[адрес] = ("видео %s ниже порога сцены %d px"
                                    % (размер, ПОРОГ))
            else:
                годные.append((пост, "видео", адрес))

    print("ВЛОЖЕНИЙ РАЗОБРАНО: постов %d · годных к сцене %d · отклонено %d"
          % (len(посты), len(годные), len(отклонено)))
    for адрес, причина in list(отклонено.items())[:30]:
        print("  [ОТКЛОНЕНО] %s\n      %s" % (причина, str(адрес)[:110]))
    for пост, род, адрес in годные[:30]:
        print("  [ГОДНО] %-5s из %s" % (род, пост))

    if not писать:
        print("\nничего не записано (нужен ключ --pisat)")
        return 0
    if not отклонено:
        print("\nотклонять нечего — `tg_rejected.json` не трогаю")
        return 0
    # Пишем РЯДОМ СО СЦЕНАРИЕМ, в рабочую папку — именно оттуда файл читает
    # `dossier_use` (он смотрит `os.getcwd()`).
    цель = os.path.join(os.getcwd(), "tg_rejected.json")
    было = {}
    if os.path.exists(цель):
        try:
            было = json.load(io.open(цель, encoding="utf-8"))
        except ValueError:
            было = {}
    было.update({к: v for к, v in отклонено.items() if к not in было})
    json.dump(было, io.open(цель, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\nзаписано в %s: всего отклонённых %d" % (цель, len(было)))
    print("`dossier_use` зачтёт их разобранными — фетч на них не встанет, "
          "круг правок на постановку и аудит не тратится.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
