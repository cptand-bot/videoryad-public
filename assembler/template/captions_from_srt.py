#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""captions.ass из .srt ролика — ВЫКЛЮЧАТЕЛЬ СУБТИТРОВ НА ОДИН РОЛИК.

Субтитров в новостных роликах по умолчанию НЕТ (договорённость 14.10). Этот
скрипт кладёт в папку ролика `captions.ass`, и ровно по наличию файла облако
вжигает субтитры в клипы — не отдельным проходом, а внутри кодирования,
которое и так идёт на 12 машинах (замер 14.10: +2% к времени клипа).

    python3 captions_from_srt.py <ролик.srt> [--plate 06c7c7] [--text 0B1B1B]
                                 [--out captions.ass] [--size 56]

ЦВЕТ ПОДЛОЖКИ — ПРЯМОЕ СЛОВО ПОЛЬЗОВАТЕЛЯ 03.11: «субтитры например на
планету, вот с такой вот подложкой, не с чёрной, а вот такого цвета 06c7c7».
Поэтому плашка задаётся ключом и по умолчанию бирюзовая, а не чёрная.
Текст по умолчанию ТЁМНЫЙ: белый на бирюзовом даёт контраст ~2:1 и читается
плохо, тёмный — ~8:1. Нужен белый — `--text FFFFFF`.

В ASS цвет пишется как &HAABBGGRR (альфа, синий, зелёный, красный), то есть
байты RGB идут в обратном порядке — отсюда перестановка в `_ass_color`.
Группировка реплик повторяет `script-to-video/template/build_dynamics.py`:
фраза копится, пока не наберётся 2,6 с или 38 знаков.
"""
import argparse
import os
import re
import sys

HDR = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial,{size},{text},&H000000FF,{plate},{plate},1,0,0,0,100,100,0,0,3,{pad},0,2,80,80,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_color(hex6, alpha="00"):
    h = hex6.strip().lstrip("#").upper()
    if len(h) != 6 or any(c not in "0123456789ABCDEF" for c in h):
        sys.exit("цвет пишется шестью знаками, например 06c7c7")
    return "&H%s%s%s%s" % (alpha, h[4:6], h[2:4], h[0:2])


def _t(sec):
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return "%d:%02d:%02d.%02d" % (h, m, s, cs)


def cues(path):
    raw = open(path, encoding="utf-8-sig", errors="replace").read()
    out = []
    for m in re.finditer(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*"
                         r"(\d+):(\d+):(\d+)[,.](\d+)\s*\n(.*?)(?=\n\s*\n|\Z)",
                         raw, re.S):
        st = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
        en = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + int(m.group(8)) / 1000
        tx = " ".join(x.strip() for x in m.group(9).split("\n") if x.strip())
        tx = re.sub(r"<[^>]+>", "", tx).strip()
        if tx:
            out.append([st, en, tx])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt")
    ap.add_argument("--channel", default="", help="канал: подставит его палитру")
    ap.add_argument("--plate", default="", help="цвет подложки, 6 знаков")
    ap.add_argument("--text", default="", help="цвет текста, 6 знаков")
    ap.add_argument("--alpha", default="00", help="прозрачность подложки, 00 — плотная")
    ap.add_argument("--size", type=int, default=52)
    ap.add_argument("--pad", type=int, default=6, help="воздух вокруг текста в плашке")
    ap.add_argument("--margin", type=int, default=75, help="отступ снизу")
    ap.add_argument("--out", default="captions.ass")
    a = ap.parse_args()
    # ПАЛИТРА СУБТИТРОВ ПО КАНАЛУ (прямое слово пользователя 03.11): ПЛАНЕТА —
    # бирюзовая подложка #06c7c7, 5 МИНУТ — бордовая #5d0303. Текст подбирается
    # к подложке: на светлой бирюзовой тёмный (контраст ~8:1), на тёмной
    # бордовой белый. Белый на бирюзовой даёт ~2:1 и не читается.
    CHAN = {"ПЛАНЕТА": ("06c7c7", "0B1B1B"),
            "5 МИНУТ": ("5d0303", "FFFFFF"),
            "5МИНУТ": ("5d0303", "FFFFFF")}
    _ch = (a.channel or "").strip().upper().replace("Ё", "Е")
    _pl, _tx = CHAN.get(_ch, ("06c7c7", "0B1B1B"))
    if _ch and _ch not in CHAN:
        print("канал «%s» не в палитре — беру бирюзовую по умолчанию" % a.channel)
    a.plate = a.plate or _pl
    a.text = a.text or _tx
    if not os.path.isfile(a.srt):
        sys.exit("нет файла: %s" % a.srt)

    groups, cur = [], None
    for st, en, tx in cues(a.srt):
        if cur is None:
            cur = [st, en, tx]
        else:
            cur[1], cur[2] = en, (cur[2] + " " + tx).strip()
        # ДЛИНУ ДЕРЖИМ ПО ШИРИНЕ КАДРА, А НЕ ПО ВРЕМЕНИ (проверено кадром
        # 03.11): при 38 знаках и кегле 56 строка вылезала за оба края —
        # плашка шла от края до края, а слова обрезались. 30 знаков при
        # кегле 52 и переносе (WrapStyle 0) дают одну-две строки внутри кадра.
        if cur[1] - cur[0] >= 2.6 or len(cur[2]) >= 30:
            groups.append(cur)
            cur = None
    if cur:
        groups.append(cur)
    for i in range(1, len(groups)):          # внахлёст — не мигаем
        if groups[i][0] < groups[i - 1][1]:
            d = groups[i - 1][1] - groups[i][0]
            groups[i][0] += d
            groups[i][1] += d
    if not groups:
        sys.exit("в SRT не нашлось ни одной реплики")

    body = [HDR.format(size=a.size, pad=a.pad, mv=a.margin,
                       text=_ass_color(a.text), plate=_ass_color(a.plate, a.alpha))]
    for st, en, tx in groups:
        body.append("Dialogue: 0,%s,%s,Caption,,0,0,0,,%s"
                    % (_t(st), _t(en), tx.upper()))
    open(a.out, "w", encoding="utf-8").write("\n".join(body) + "\n")
    print("субтитры: %d строк → %s" % (len(groups), a.out))
    print("  подложка #%s, текст #%s, кегль %d, отступ снизу %d"
          % (a.plate.lstrip('#'), a.text.lstrip('#'), a.size, a.margin))
    print("  ВКЛЮЧЕНО: этот файл в папке ролика и есть выключатель — облако "
          "вожжёт субтитры в клипы (+2% к кодированию). Не нужны — удали его.")


if __name__ == "__main__":
    main()
