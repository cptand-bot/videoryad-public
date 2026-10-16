#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Журнал отказов — почему пользователь снял или забанил кадр (2026-10-16).

Зачем. Бан пишется по md5, то есть блокирует РОВНО ТОТ файл и никак не мешает
прийти следующему с тем же дефектом (логотип НТВ ловился шесть раз на шести
разных файлах). А простое снятие карточки на дашборде до сих пор не
фиксировало вообще ничего, кроме `approved: false` — логика отказа жила в
голове у ассистента и умирала вместе с вкладкой.

Здесь отказ привязывается к ЗАПРОСУ и к ПРИЧИНЕ, а не к файлу. Накопленное
переживает вкладки и сессии, и из него растут правила.

Формат — `~/projects/media-library/rejections.jsonl`, одна строка на отказ:

    {"ts": "2026-10-16T10:12:33", "channel": "ПЛАНЕТА",
     "project": "planeta-pravye-1710", "scene": 37, "kind": "overlay",
     "action": "clear", "reason": "watermark",
     "note": "логотип НТВ в правом верхнем углу",
     "query": "Дональд Туск премьер-министр Польши реальное фото",
     "source": "press_photo", "md5": "...", "file": "overlays/scene_037.jpg"}

`note` — свободный текст, в том числе надиктованный голосом (см. voice_note.py).
Именно он самый ценный: коды причин огрубляют, а голосом пользователь
объясняет настоящую логику отказа.

jsonl, а не json: дописывается одной строкой из любого процесса, не ломается
от параллельной записи двух вкладок и не требует перечитывать весь файл.
"""
import json
import os
import datetime

LOG = os.path.expanduser("~/projects/media-library/rejections.jsonl")

# Коды причин выведены из 138 реальных банов и улова 2026-10-16, а не придуманы.
# Порядок = порядок кнопок на дашборде, самое частое сверху.
REASONS = [
    ("watermark",     "водяной знак / логотип канала"),
    ("not_real",      "не реальное фото (AI, рисунок, графика)"),
    ("wrong_country", "чужая страна / чужой объект"),
    ("wrong_person",  "не тот человек / устаревшая атрибуция"),
    ("archive",       "архив вместо современности"),
    ("people",        "люди в кадре / дети"),
    ("stale",         "примелькалось"),
    ("offtopic",      "не по теме сцены"),
    ("document",      "документ или текст в кадре"),
    ("other",         "другое"),
]
# Отдельно от "other": пользователь снял молча, не объясняя — ему было некогда.
# Это НЕ «другая причина», это отсутствие причины, и в сводках их нельзя
# смешивать. Факт снятия с запросом полезен и без объяснения.
UNSPECIFIED = "unspecified"

# Чем кадр ХОРОШ — для action="keep". Пользователь просил 2026-10-16:
# «расширило бы картину не просто по запретам, но и по допуску».
# Положительные примеры ценнее запретов тем, что показывают, КАК надо, а не
# только как не надо: по ним можно учить формулировку запроса, а не только
# фильтровать выдачу. Храним теми же полями, различаем по `action`.
GOOD = [
    ("fits",       "точно по этой сцене"),
    ("adds",       "добавляет то, чего нет в базе"),
    ("readable",   "хорошо видно / читается"),
    ("rare",       "редкий удачный кадр"),
    ("good_other", "просто хорошо"),
]
GOOD_CODES = {c for c, _ in GOOD}
REASON_CODES = {c for c, _ in REASONS}
REASON_LABEL = dict(REASONS)
REASON_LABEL[UNSPECIFIED] = "без причины (снято молча)"


def log_rejection(scene=None, kind="scene", action="clear", reason="other",
                  note="", query="", source="", md5="", file="",
                  project="", channel="", base_query="", log=LOG):
    """Дописать одну запись. Никогда не бросает — отказ пользователя важнее
    журнала, и сбой записи не должен ронять дашборд."""
    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "channel": channel or "",
        "project": project or os.path.basename(os.getcwd()),
        "scene": scene,
        "kind": kind,            # scene | overlay | text
        "action": action,        # clear | ban | replace
        "reason": (reason if reason in REASON_CODES or reason in GOOD_CODES
                   else (UNSPECIFIED if not (reason or "").strip() else "other")),
        "note": (note or "").strip(),
        "query": (query or "").strip(),
        # для всплывашки — запрос её БАЗОВОГО кадра: пользователь оценивает
        # пару целиком («что оно иллюстрирует»), и без базы запись немая
        "base_query": (base_query or "").strip(),
        "source": source or "",
        "md5": md5 or "",
        "file": file or "",
    }
    try:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return rec


def load_rejections(log=LOG, limit=None):
    """Все записи, новые в конце. Битые строки пропускаются молча."""
    if not os.path.exists(log):
        return []
    out = []
    with open(log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out[-limit:] if limit else out


def summarize(log=LOG, top=12):
    """Короткая сводка для подмешивания в контекст сборки: какие причины и
    какие запросы повторяются. Нужна компактность — это идёт в каждую сессию."""
    import collections
    recs = load_rejections(log)
    if not recs:
        return "журнал отказов пуст"
    keeps = [r for r in recs if r.get("action") == "keep"]
    recs = [r for r in recs if r.get("action") != "keep"]
    by_reason = collections.Counter(r.get("reason", "other") for r in recs)
    words = collections.Counter()
    for r in recs:
        q = (r.get("query") or "").lower()
        for w in q.split():
            if len(w) > 4:
                words[w] += 1
    lines = [f"отказов всего: {len(recs)}", "по причинам:"]
    for code, n in by_reason.most_common():
        lines.append(f"  {n:4d}  {REASON_LABEL.get(code, code)}")
    hot = [f"{w} ({n})" for w, n in words.most_common(top) if n > 1]
    if hot:
        lines.append("частые слова в забракованных запросах: " + ", ".join(hot))
    if keeps:
        gl = dict(GOOD)
        lines.append(f"\nОДОБРЕНО (что пользователю понравилось): {len(keeps)}")
        for code, n in collections.Counter(k.get("reason", "") for k in keeps).most_common():
            lines.append(f"  {n:4d}  {gl.get(code, code or '—')}")
        for k in keeps[-5:]:
            if k.get("note"):
                lines.append(f"    · {k['note'][:90]}")
                lines.append(f"      запрос: {(k.get('query') or '')[:80]}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--summary":
        print(summarize())
    else:
        print(__doc__)
        print("причины:")
        for c, l in REASONS:
            print(f"  {c:14} {l}")
