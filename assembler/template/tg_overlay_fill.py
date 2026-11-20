#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ФОТО ИЗ ПОСТА НИЖЕ ПОРОГА СЦЕНЫ — СТАВИМ ВСПЛЫВАШКОЙ, А НЕ ТЕРЯЕМ (17.11).

Его прямое слово: «мы же записывали, что ниже порога качества из вложений
это надо делать, значит тем качеством, которое есть. Только не на весь
экран, а таким маленьким окошком». Разбор того же дня: `tg_media.py`
правильно помечает такое фото «это всплывашка, не сцена» в `tg.json`, но
дальше ЭТУ пометку никто не превращает в реальную всплывашку — отметка
живёт одна, без следствия.

    python3 tg_overlay_fill.py <папка проекта>

Делает: берёт фото из `tg.json`, которые `dossier_use.неприменим()` не
отбраковывает вовсе, но и порога сцены (800 px) не достают — то есть ровно
категория «только всплывашкой». Для каждого ищет сцену того же ролика с
НАИБОЛЬШИМ словарным пересечением между текстом сцены и текстом поста (как
совпадение запроса у card_put, не дословное требование). Сцены, где уже
стоит карточка (`card:`) или уже есть файл в `overlays/`, пропускает — слоёв
на карточках не бывает, а занятую сцену не отбирает. Скачивает выбранный
файл в `overlays/scene_NNN.jpg`; саму запись в `overlays.json` НЕ пишет —
её при следующем вызове создаст сам `build_overlays.py build` (он уже умеет
подбирать звук/угол/вид по новому файлу в `overlays/`, второй раз это не
переизобретаем).
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dossier_use as du

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
СТОП = {"и", "в", "на", "с", "по", "у", "от", "к", "за", "из", "что", "это",
        "как", "а", "но", "не", "же", "уже", "ещё", "о", "об", "при", "для"}


def _норм(т):
    return [w for w in re.sub(r"[^а-яёa-z0-9 ]", " ",
            str(т or "").lower().replace("ё", "е")).split() if w not in СТОП]


def _только_всплывашкой(m):
    """True, если файл годен всплывашкой, но НЕ дотягивает до порога сцены
    (800 px по длинной стороне) — та самая категория из tg_media.py."""
    if du.неприменим(m):
        return False
    w, h = du._wh(m.get("size"))
    if not w:
        return False
    return max(w, h) < 800


def main():
    if len(sys.argv) < 2:
        print("usage: tg_overlay_fill.py <папка проекта>", file=sys.stderr)
        return 2
    project = sys.argv[1]
    import glob
    tg_files = [c for c in sorted(glob.glob(os.path.join(project, "tg*.json")))
                if not any(w in os.path.basename(c).lower() for w in
                           ("reject", "отказ", "snapshot", "снапшот", "source", "map"))]
    if not tg_files:
        print("tg*.json нет — вложений досье не было, делать нечего")
        return 0

    отказы = du.load_rejected(project)
    media = []
    видано = set()
    for t in tg_files:
        for m in du.load_tg(t):
            if m["url"] in видано:
                continue
            видано.add(m["url"])
            media.append(m)
    # 20.11, улов usuario-3f: файл всегда сохранялся под именем «.jpg»
    # (ниже), а кандидаты включали и `kind == "видео"` — видео утекало на
    # диск под именем картинки, нечитаемый мусор. Всплывашка — статичное
    # фото, видео-байты сюда класть незачем: берём только фото.
    кандидаты = [m for m in media
                 if not (отказы.get(m["url"]) or отказы.get(m.get("post") or ""))
                 and m.get("kind") == "фото"
                 and _только_всплывашкой(m)]
    if not кандидаты:
        print("годных под всплывашку (ниже порога сцены, выше порога "
              "фетчера) не нашлось — нечего ставить")
        return 0

    # тексты постов — url поста -> текст, как в codex_brief._dossier_block
    тексты = {}
    for t in tg_files:
        try:
            d = json.load(open(t, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in (d if isinstance(d, list) else d.get("items") or []):
            if isinstance(r, dict) and r.get("url"):
                тексты[str(r["url"])] = re.sub(r"\s+", " ",
                                               str(r.get("text") or "")).strip()

    scenes_path = None
    for f in os.listdir(project):
        if f.endswith(".scenes.json") and not f.startswith("codex"):
            scenes_path = os.path.join(project, f)
            break
    if not scenes_path:
        print("нет <проект>.scenes.json — не могу сопоставить сцены", file=sys.stderr)
        return 1
    data = json.load(open(scenes_path, encoding="utf-8"))
    scenes = data["scenes"] if isinstance(data, dict) else data

    overlays_dir = os.path.join(project, "overlays")
    os.makedirs(overlays_dir, exist_ok=True)
    занято = {int(re.match(r"scene_(\d+)", f).group(1))
              for f in os.listdir(overlays_dir)
              if re.match(r"scene_(\d+)\.(jpg|jpeg|png)$", f)}
    карточные = {int(s["id"]) for s in scenes
                 if str(s.get("source", "")).startswith("card:")}
    # УЖЕ ЕСТЬ ЗАПИСЬ В overlays.json — ДАЖЕ БЕЗ ФАЙЛА-ФОТО (17.11, поймано
    # на своём же первом тесте). Сцена с текстовой всплывашкой (N-текст)
    # «занятой» не считалась, файл клался рядом и повисал мёртвым грузом:
    # build_overlays.py не трогает записи, которые уже в overlays.json, и
    # photo-ключ к существующей text-записи не добавляет.
    ov_path = os.path.join(project, "overlays.json")
    if os.path.isfile(ov_path):
        try:
            ov = json.load(open(ov_path, encoding="utf-8"))
            занято |= {int(k) for k in ov if str(k).isdigit()}
        except (OSError, ValueError):
            pass

    поставлено = []
    for m in кандидаты:
        пост_текст = тексты.get(m.get("post") or "", "")
        слова_поста = set(_норм(пост_текст))
        if len(слова_поста) < 2:
            continue
        лучшая, лучший_счёт = None, 0
        for s in scenes:
            sid = int(s.get("id", -1))
            if sid in занято or sid in карточные:
                continue
            слова_сцены = set(_норм(s.get("text", "")))
            общие = слова_поста & слова_сцены
            if len(общие) > лучший_счёт:
                лучшая, лучший_счёт = sid, len(общие)
        if лучшая is None or лучший_счёт < 2:
            continue
        dst = os.path.join(overlays_dir, "scene_%03d.jpg" % лучшая)
        try:
            req = urllib.request.Request(m["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
            if len(raw) < 500:
                print("  сцена %d: ответ слишком маленький (%d байт), пропуск"
                      % (лучшая, len(raw)))
                continue
            with open(dst, "wb") as f:
                f.write(raw)
        except Exception as e:
            print("  сцена %d: не скачалось (%s)" % (лучшая, e))
            continue
        занято.add(лучшая)
        поставлено.append(лучшая)
        print("  сцена %d <- %s (общих слов с постом: %d)"
              % (лучшая, m["url"][:70], лучший_счёт))

    print("ИТОГО положено всплывашек: %d из %d кандидатов"
          % (len(поставлено), len(кандидаты)))
    if поставлено:
        print("дальше: python3 %s/build_overlays.py build %s — он сам "
              "допишет overlays.json" % (HERE, project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
