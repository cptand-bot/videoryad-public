#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МАШИННАЯ ПРОВЕРКА РЕРАЙТА — ДО ТОГО, КАК ЕГО УВИДИТ АУДИТОР (07.11.2026).

    python3 rewrite_lint.py <оригинал.txt> <рерайт.txt> [--brief ЗАДАНИЕ-РЕРАЙТ.txt]

Половина брака ловится без всякой модели и стоит ноль: совпадение с
оригиналом, цифры, тире, длина, призывы подписаться. Модель-аудитор нужна
только для того, что машина не умеет — пережили ли переписывание авторские
мысли, цел ли юмор. Поэтому порядок такой: сначала эта проверка, и только
прошедший текст идёт к аудитору.

Правила взяты из георадара (лист `EditorialRules`):
  · «Уникальность между каналами» — пословная сверка версий;
  · «Фильтр TTS и CTA» — тире запрещены, два призыва подписаться,
    проверка чисел и «ё»;
  · длина держится ±10%, иначе ролик уедет по хронометражу.
"""
import argparse
import re
import sys


def read_text(path):
    """Прочитать текст В ЛЮБОЙ ИЗ НАШИХ КОДИРОВОК.

    МИНА, ПОЙМАННАЯ 07.11.2026 ДО ПЕРВОГО БОЕВОГО ПРОГОНА: все тексты
    озвучки пользователя лежат в Windows-1251 (их пишет его цепочка в
    ChatGPT, кодировка прямо указана в записи георадара). Чтение как
    utf-8 с errors="replace" НЕ ПАДАЕТ — оно молча превращает весь русский
    текст в символы замены. Проверка при этом бодро печатает «текст 13333
    знака, цифр нет», а в сервис озвучки уехал бы мусор.
    Поэтому кодировка подбирается, а не предполагается.
    """
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", "replace")


SHINGLE = 5          # длина сцепки слов, по которой ищем совпадения
MAX_OVERLAP = 0.12   # доля сцепок оригинала, которую рерайту позволено повторить


def words(text):
    return re.findall(r"[А-Яа-яЁёA-Za-z0-9]+", text.lower())


def shingles(ws, n=SHINGLE):
    return {" ".join(ws[i:i + n]) for i in range(max(0, len(ws) - n + 1))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("original")
    ap.add_argument("rewrite")
    ap.add_argument("--brief", help="файл задания — из него берутся авторские мысли")
    ap.add_argument("--max-overlap", type=float, default=MAX_OVERLAP)
    args = ap.parse_args()

    orig = read_text(args.original)
    new = read_text(args.rewrite)

    errors, notes = [], []

    # 1. длина
    ratio = len(new) / max(1, len(orig))
    notes.append("длина: %d знаков против %d (%.0f%%)" % (len(new), len(orig), ratio * 100))
    if not 0.9 <= ratio <= 1.1:
        errors.append("длина вне допуска ±10%% — ролик уедет по хронометражу")

    # 2. совпадение с оригиналом (правило «Уникальность между каналами»)
    so, sn = shingles(words(orig)), shingles(words(new))
    common = so & sn
    overlap = len(common) / max(1, len(so))
    notes.append("совпадение с оригиналом: %.1f%% сцепок по %d слов"
                 % (overlap * 100, SHINGLE))
    if overlap > args.max_overlap:
        sample = sorted(common, key=len, reverse=True)[:5]
        errors.append("текст слишком близок к оригиналу (%.1f%% при пороге %.0f%%). "
                      "Повторяются, например: %s"
                      % (overlap * 100, args.max_overlap * 100,
                         "; ".join("«%s»" % s for s in sample)))

    # 3. цифры — озвучка склоняет их неверно
    digits = re.findall(r"\d+", new)
    if digits:
        errors.append("ЦИФРЫ в тексте (%d шт.: %s) — писать прописью с падежом"
                      % (len(digits), ", ".join(digits[:8])))

    # 4. тире — правило фильтра TTS из георадара
    dashes = len(re.findall(r"[—–]", new))
    if dashes:
        errors.append("тире в тексте (%d шт.) — правило фильтра TTS их запрещает" % dashes)

    # 5. призывы подписаться: по правилу их должно быть два
    cta = len(re.findall(r"подпиш", new, re.I))
    notes.append("призывов подписаться: %d" % cta)
    if cta < 2:
        errors.append("призывов подписаться меньше двух (правило CTA)")

    # 6. «ё» — георадар требует её проверять
    if "ё" not in new and "Ё" not in new:
        notes.append("«ё» в тексте не встречается ни разу — проверить осознанно")

    # 7. авторские мысли: грубая прикидка по редким словам из задания.
    #    Это НЕ замена аудитору, а ранний сигнал «мысль выпала целиком».
    if args.brief:
        brief = read_text(args.brief)
        block = brief.split("АВТОРСКИЕ МЫСЛИ")[-1].split("ПРАВИЛА РЕДАКТУРЫ")[0]
        thoughts = [l.strip("· ").strip() for l in block.splitlines()
                    if l.strip().startswith("·")]
        lost = []
        nw = set(words(new))
        for t in thoughts:
            key = [w for w in words(t) if len(w) > 6]
            if not key:
                continue
            hit = sum(1 for w in set(key) if w in nw) / len(set(key))
            if hit < 0.25:
                lost.append(t[:90])
        if lost:
            notes.append("возможно выпали мысли (проверит аудитор): %s"
                         % " | ".join(lost[:3]))

    for n in notes:
        print("  · %s" % n)
    for e in errors:
        print("  ✗ %s" % e)
    print("ПРОВЕРКА: %s" % ("НЕ ПРОЙДЕНА" if errors else "пройдена, можно к аудитору"))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
