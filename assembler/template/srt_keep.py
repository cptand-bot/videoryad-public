#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""srt_keep.py — публичную ЗАГЛУШКУ субтитров из облака в забор не кладём.

Зачем (09.11, улов `usuario-2c`, ролик `planeta-ukraina-forma-1011`): `get.sh`
вернул в папку забора `.srt` на 34 байта вместо настоящего файла на 48 КБ.
Настоящий всё это время лежал в папке пользователя на `D:`, и вкладка взяла
его руками. Поймал подмену только `captions_from_srt.py` («реплик 1,
перекрыто 1,0 с») — без него ролик уехал бы с ОДНОЙ строкой субтитров на
девятнадцать минут, и увидели бы это в готовом файле.

Откуда заглушка. По закрытию 14.10 текст сценария и субтитры в ПУБЛИЧНЫЙ
репозиторий не уезжают: `ship.sh` подменяет каждый `*.srt` в очереди строкой
`1 / 00:00:00,000 --> 00:00:01,000 / -` — ровно 34 байта, одна реплика.
Настоящего файла в облаке нет и быть не должно, поэтому забор обязан брать
его локально, а не принимать то, что приехало.

Где ищем настоящий, по порядку: копии, снятые перед чисткой забора → рабочая
папка ролика → папка-источник пользователя из `.source_dir` (её пишет
`take_folder.py`). В папке пользователя смотрим ТОЛЬКО `*.srt` верхнего
уровня — правило «в его папке не трогать ничего, кроме SRT и озвучки».

Использование:
    python3 srt_keep.py <папка забора> [--keep <копии>] [--work <рабочая>]
                        [--cache-source-dir <файл с путём>]

Коды возврата:
    0 — всё хорошо (настоящий на месте или восстановлен)
    3 — в заборе ЗАГЛУШКА и восстановить нечем
"""
import glob
import os
import shutil
import sys

STUB_MAX = 2048          # настоящий .srt ролика — десятки килобайт
STUB_CUES = 2            # и сотни реплик; у заглушки одна


def cues(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().count("-->")
    except OSError:
        return 0


def is_stub(path):
    try:
        sz = os.path.getsize(path)
    except OSError:
        return False
    # оба признака разом: мелкий И почти без реплик. По одному размеру
    # браковать нельзя — короткий, но настоящий файл тоже бывает.
    return sz <= STUB_MAX and cues(path) <= STUB_CUES


def srts(d):
    if not d or not os.path.isdir(d):
        return []
    return sorted(glob.glob(os.path.join(d, "*.srt")))


def _source_dir(dest, cache_file):
    for p in (os.path.join(dest, ".source_dir"), cache_file):
        if p and os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    v = f.read().strip()
            except OSError:
                continue
            if v and os.path.isdir(v):
                return v
    return ""


def _dirs(dest, keep, work, cache_file):
    """Где искать настоящий файл, в порядке доверия."""
    out = []
    for label, d in (("копии, снятые перед чисткой забора", keep),
                     ("рабочая папка ролика", work),
                     ("папка темы пользователя",
                      _source_dir(dest, cache_file))):
        if not d or not os.path.isdir(d):
            continue
        if os.path.abspath(d) == os.path.abspath(dest):
            continue
        out.append((label, d))
    return out


def fix(dest, keep="", work="", cache_file=""):
    here = srts(dest)
    if not here:
        return 0                      # .srt в заборе нет вовсе — не наше дело
    real_here = [f for f in here if not is_stub(f)]
    stubs = [f for f in here if is_stub(f)]
    if not stubs:
        return 0                      # всё настоящее, вести себя как раньше
    where = _dirs(dest, keep, work, cache_file)

    # ПО ИМЕНИ, А НЕ «САМЫЙ БОЛЬШОЙ»: у ролика бывает несколько `.srt`
    # (ПЛАНЕТА, перевод, черновик — живой случай `psd-ritorika-0911`, три
    # заглушки в одной папке). Каждой заглушке ищем её ТЁЗКУ, иначе легко
    # положить субтитры другого канала.
    restored, unresolved = [], []
    for st in stubs:
        b = os.path.basename(st)
        src = ""
        for label, d in where:
            c = os.path.join(d, b)
            if os.path.isfile(c) and not is_stub(c):
                src, src_from = c, "%s (%s)" % (label, d)
                break
        if not src:
            unresolved.append(st)
            continue
        _ssize, _scues = os.path.getsize(st), cues(st)
        shutil.copy2(src, st)
        restored.append(st)
        print("  !! из облака приехала ЗАГЛУШКА субтитров (%s — %d байт, "
              "реплик %d)," % (b, _ssize, _scues))
        print("     настоящий .srt восстановлен из %s" % src_from)
        print("     %s — %d байт, реплик %d" % (b, os.path.getsize(st),
                                                cues(st)))

    # ни одной тёзки и настоящего в папке нет — берём самый большой настоящий
    # из тех же мест под ЕГО именем: лучше правильные субтитры под чужим
    # именем, чем одна строка на весь ролик
    if unresolved and not real_here and not restored:
        best, best_from, best_sz = "", "", 0
        for label, d in where:
            for f in srts(d):
                if is_stub(f):
                    continue
                sz = os.path.getsize(f)
                if sz > best_sz:
                    best, best_from, best_sz = f, "%s (%s)" % (label, d), sz
            if best:
                break
        if best:
            dst = os.path.join(dest, os.path.basename(best))
            shutil.copy2(best, dst)
            restored.append(dst)
            print("  !! в заборе была только ЗАГЛУШКА субтитров (%s, %d байт)"
                  % (os.path.basename(unresolved[0]),
                     os.path.getsize(unresolved[0])))
            print("     настоящий .srt восстановлен из %s" % best_from)
            print("     %s — %d байт, реплик %d (имя другое: тёзки заглушки "
                  "нигде не нашлось)" % (os.path.basename(dst), best_sz,
                                         cues(dst)))
            for f in list(unresolved):
                if os.path.abspath(f) != os.path.abspath(dst):
                    try:
                        os.remove(f)
                        unresolved.remove(f)
                        print("     заглушка %s выброшена"
                              % os.path.basename(f))
                    except OSError:
                        pass

    if real_here or restored:
        # остатки заглушек рядом с настоящим файлом убираем: иначе
        # `captions_from_srt.py` может взять именно её
        _good = (real_here + restored)[0]
        for f in unresolved:
            try:
                os.remove(f)
                print("  выброшена заглушка субтитров %s (настоящий %s на "
                      "месте)" % (os.path.basename(f),
                                  os.path.basename(_good)))
            except OSError:
                pass
        return 0

    print("")
    print("!! В ЗАБОРЕ ЗАГЛУШКА СУБТИТРОВ, А НАСТОЯЩЕГО .srt НЕТ НИГДЕ.")
    for f in unresolved:
        print("   приехало: %s — %d байт, реплик %d"
              % (os.path.basename(f), os.path.getsize(f), cues(f)))
    print("   Это НЕ потеря облака: настоящий .srt туда и не уезжает")
    print("   (закрытие 14.10 — текст и субтитры в публичный репозиторий")
    print("   не отправляются, в очередь кладётся заглушка 34 байта).")
    print("   Искал: %s" % (", ".join("%s: %s" % (l, d) for l, d in where)
                            or "негде — ни копий, ни рабочей папки, ни "
                               "`.source_dir`"))
    print("   ЧТО ДЕЛАТЬ: возьми `.srt` из папки темы на `D:` —")
    print("     python3 ~/.claude/skills/news-video/template/take_folder.py \\")
    print("       \"<папка темы на D:>\" %s" % dest)
    print("   Собирать на заглушке НЕЛЬЗЯ: субтитров будет одна строка на")
    print("   весь ролик, и видно это станет только в готовом файле.")
    return 3


def main(argv):
    opts = {"--keep": "", "--work": "", "--cache-source-dir": ""}
    pos, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in opts:
            opts[a] = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
            continue
        if not a.startswith("--"):
            pos.append(a)
        i += 1
    if not pos:
        print(__doc__)
        return 0
    if not os.path.isdir(pos[0]):
        print("нет папки: %s" % pos[0])
        return 0
    return fix(pos[0], opts["--keep"], opts["--work"],
               opts["--cache-source-dir"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
