#!/usr/bin/env python3
"""Режет общий .ass с субтитрами на по-сценные куски с местным отсчётом времени.

ЗАЧЕМ. Вжигать субтитры одним проходом по готовому ролику — это полное
перекодирование 14 минут (замер 2026-10-12: отключённый шаг stretch стоил
606 и 467 секунд на двухъядерных раннерах). А вжигать их в клипы, которые и
так кодируются на 12 машинах параллельно, стоит +2% к этому кодированию
(замер 2026-10-14: 20-секундный кусок — 12,52 с без субтитров против 12,75 с
с ними). То есть то же самое, но практически бесплатно.

Загвоздка одна: в общем .ass время абсолютное, от начала ролика, а каждый
клип — отдельный файл, который начинается с нуля. Поэтому для каждой сцены
собирается свой маленький .ass, где остались только попадающие в неё реплики,
а их время пересчитано от начала клипа.

ВЫКЛЮЧАТЕЛЬ. Этот скрипт и вжигание в build_clips_1080.py работают ТОЛЬКО
если в проекте лежит captions.ass. Нет файла — ничего не происходит вообще,
ни одного изменения в поведении. Генерируется он отдельной командой
(script-to-video/template/build_dynamics.py), то есть включить субтитры можно
только осознанно.

Использование:
    python3 captions_shard.py <scenes.json> <captions.ass> <out_dir>
"""
import json, os, re, sys

DIALOGUE = re.compile(r"^(Dialogue:\s*[^,]*,)([^,]+),([^,]+),(.*)$")


def _t2s(t):
    """ASS-время 0:00:03.48 -> секунды."""
    t = t.strip()
    h, m, rest = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def _s2t(x):
    if x < 0:
        x = 0.0
    h = int(x // 3600); x -= h * 3600
    m = int(x // 60);   x -= m * 60
    return f"{h}:{m:02d}:{x:05.2f}"


def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    scenes_path, ass_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    if not os.path.isfile(ass_path):
        print("captions_shard: нет .ass — субтитры выключены, ничего не делаю")
        return 0

    scenes = json.load(open(scenes_path, encoding="utf-8"))["scenes"]
    raw = open(ass_path, encoding="utf-8").read().splitlines()

    head, events = [], []
    in_events = False
    for ln in raw:
        if ln.strip().lower().startswith("[events]"):
            in_events = True
            head.append(ln)
            continue
        if in_events and ln.startswith("Dialogue:"):
            events.append(ln)
        else:
            head.append(ln)

    os.makedirs(out_dir, exist_ok=True)
    t = 0.0
    made = 0
    for sc in scenes:
        sid = int(sc["id"])
        dur = float(sc["duration_sec"])
        a, b = t, t + dur
        t = b
        lines = []
        for ln in events:
            m = DIALOGUE.match(ln)
            if not m:
                continue
            pre, st, en, tail = m.groups()
            s0, e0 = _t2s(st), _t2s(en)
            if e0 <= a or s0 >= b:          # реплика не попадает в эту сцену
                continue
            # обрезаем по границам сцены и переносим в местное время клипа
            lines.append(f"{pre}{_s2t(max(s0, a) - a)},{_s2t(min(e0, b) - a)},{tail}")
        if not lines:
            continue
        with open(os.path.join(out_dir, f"scene_{sid:03d}.ass"), "w", encoding="utf-8") as f:
            f.write("\n".join(head) + "\n" + "\n".join(lines) + "\n")
        made += 1
    print(f"captions_shard: кусков субтитров — {made} из {len(scenes)} сцен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
