#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""naydi.py — НАЙТИ, А НЕ ВСПОМИНАТЬ (09.11.2026).

    python3 naydi.py "дашборд памят"            # по словам, все источники
    python3 naydi.py "расплата" --dni 3         # только за последние 3 суток
    python3 naydi.py "ПЛАН-ЭКОНОМИИ" --kratko   # по одной строке на попадание

Его слово 09.11, дословно: «сейчас мы час ебёмся с тем, чтобы вспомнить. А ты
его, оказывается, можешь найти». Повод: он голосом восстанавливал потерянный
разговор, пока ответ лежал в транскрипте вкладки и в папке на `D:`.

ПРАВИЛО: прежде чем спросить «а что мы решали?», ищем САМИ — этим скриптом.
Пользователь не хранилище.

Где ищет (в этом порядке):
  1. переписка всех вкладок — ~/.claude/projects/**/*.jsonl (слова ЕГО и мои);
  2. память — ~/.claude/projects/-home-andrey/memory/*.md;
  3. рабочие документы скилла — SKILL.md, CHANGELOG.md, БРИФ-КОРОТКО.md,
     ПЛАН-ЭКОНОМИИ.md, OPEN-ITEMS.md, references/*.md;
  4. его папка на диске — D:\\YouTube\\НОВОСТИ\\*.txt и НОВОСТИ-СОСТОЯНИЕ.txt;
  5. готовые файлы роликов — по имени (где лежит, сколько весит, когда сдан).

Печатает дату, источник и фрагмент. Ничего не меняет.
"""
import argparse, glob, json, os, re, sys, time, datetime

HOME = os.path.expanduser("~")
SKILL = os.path.join(HOME, ".claude", "skills", "news-video")
MEM = os.path.join(HOME, ".claude", "projects", "-home-andrey", "memory")
NEWS = "/mnt/d/YouTube/НОВОСТИ"


def rx(words):
    # все слова должны встретиться рядом (в пределах одного фрагмента),
    # регистр и падежные хвосты не важны: берём по 4-6 первых букв слова
    parts = []
    for w in words.split():
        stem = re.escape(w[:max(4, len(w) - 2)])
        parts.append(stem)
    return [re.compile(p, re.I) for p in parts]


def hits(text, pats):
    return all(p.search(text) for p in pats)


def frag(text, pats, width=260):
    m = pats[0].search(text)
    if not m:
        return text[:width]
    a = max(0, m.start() - width // 3)
    return ("…" if a else "") + text[a:a + width].replace("\n", " ")


def iter_transcripts(since):
    root = os.path.join(HOME, ".claude", "projects")
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")) + \
             glob.glob(os.path.join(root, "*", "*", "subagents", "*.jsonl")):
        if os.path.getmtime(f) < since:
            continue
        who = "агент" if "subagents" in f else os.path.basename(f)[:8]
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") not in ("user", "assistant"):
                continue
            ts = d.get("timestamp", "")[:16].replace("T", " ")
            m = (d.get("message") or {}).get("content")
            if isinstance(m, str):
                txts = [m]
            elif isinstance(m, list):
                txts = [c.get("text", "") for c in m
                        if isinstance(c, dict) and c.get("type") == "text"]
            else:
                continue
            for t in txts:
                if t and t.strip():
                    yield ts, ("ОН" if d["type"] == "user" else "я") + " · " + who, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words")
    ap.add_argument("--dni", type=int, default=7, help="глубина поиска в сутках (по умолчанию 7)")
    ap.add_argument("--kratko", action="store_true", help="по одной строке на попадание")
    ap.add_argument("--vsyo", action="store_true", help="не ограничивать число попаданий")
    a = ap.parse_args()
    pats = rx(a.words)
    since = time.time() - a.dni * 86400
    cap = 10 ** 6 if a.vsyo else 12

    print("ИЩУ «%s» за %d суток\n" % (a.words, a.dni))

    # 1. переписка
    seen, rows = set(), []
    for ts, who, t in iter_transcripts(since):
        if len(t) > 12000 or not hits(t, pats):
            continue
        key = frag(t, pats, 90)
        if key in seen:
            continue
        seen.add(key)
        rows.append((ts, who, frag(t, pats, 120 if a.kratko else 320)))
    rows.sort()
    print("── ПЕРЕПИСКА (%d) ──" % len(rows))
    for ts, who, t in rows[-cap:]:
        print("  %s · %-12s %s" % (ts, who, t))

    # 2-3. память и документы
    docs = (sorted(glob.glob(os.path.join(MEM, "*.md"))) +
            [os.path.join(SKILL, x) for x in
             ("SKILL.md", "CHANGELOG.md", "БРИФ-КОРОТКО.md", "BRIEF-TAB.md",
              "ПЛАН-ЭКОНОМИИ.md", "OPEN-ITEMS.md", "ПОРЯДОК-ДНЯ.md", "BUGS-LIVE.md")] +
            sorted(glob.glob(os.path.join(SKILL, "references", "*.md"))))
    print("\n── ПАМЯТЬ И ДОКУМЕНТЫ ──")
    n = 0
    for p in docs:
        if not os.path.exists(p):
            continue
        try:
            lines = open(p, encoding="utf-8", errors="replace").read().split("\n")
        except OSError:
            continue
        for i, ln in enumerate(lines, 1):
            ctx = " ".join(lines[max(0, i - 2):i + 1])
            if hits(ctx, pats) and pats[0].search(ln):
                print("  %s:%d  %s" % (os.path.relpath(p, HOME), i, ln.strip()[:200]))
                n += 1
                break
    if not n:
        print("  (ничего)")

    # 4. его папка
    print("\n── ЕГО ФАЙЛЫ НА ДИСКЕ ──")
    n = 0
    cands = glob.glob(os.path.join(NEWS, "*.txt")) + \
        glob.glob("/mnt/d/YouTube/НОВОСТИ-СОСТОЯНИЕ.txt") + \
        glob.glob(os.path.join(NEWS, "CLAUDE CODE", "*", "*.txt"))
    for p in cands:
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if hits(t, pats):
            print("  %s · %s" % (datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%d.%m %H:%M"),
                                 p.replace("/mnt/d", "D:")))
            print("      %s" % frag(t, pats, 220))
            n += 1
    if not n:
        print("  (ничего)")

    # 5. готовые ролики по имени
    print("\n── ГОТОВЫЕ ФАЙЛЫ РОЛИКОВ ──")
    n = 0
    pats_mp4 = glob.glob(os.path.join(NEWS, "*", "*", "*", "*", "*.mp4")) + \
              glob.glob(os.path.join(NEWS, "*", "*", "*", "*.mp4"))
    for p in sorted(set(pats_mp4)):
        if hits(os.path.basename(p), pats):
            st = os.stat(p)
            print("  %s · %d МБ · %s" % (datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d.%m %H:%M"),
                                         st.st_size // 2**20, p.replace("/mnt/d", "D:")))
            n += 1
    if not n:
        print("  (ничего)")


if __name__ == "__main__":
    main()
