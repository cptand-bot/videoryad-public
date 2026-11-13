# -*- coding: utf-8 -*-
"""БАН ПО ПЕРЦЕПТИВНОМУ ХЕШУ — чтобы забаненный КАДР не возвращался другим
файлом (2026-11-13, его главная претензия дня, сказана дважды и зло).

Дословно: «то, что я забанил, оно никуда не банится, оно всё равно опять
достаётся и всё равно ложится… они всё равно лезут и лезут».

ПОЧЕМУ БАН НЕ ДЕРЖАЛ. Механизм был один — MD5 ФАЙЛА
(`~/projects/media-library/.banned_md5.json`, 3302 записи, живой, в облако
уезжает). А поиск отдаёт ТОТ ЖЕ снимок другим файлом: пережатым, другого
размера, с другого сайта, иногда с иной обрезкой. MD5 у него ДРУГОЙ, и бан
его не видит в упор. То есть банился не ОБРАЗ, а один конкретный файл —
поэтому «я забанил, а оно лезет» повторялось каждый день (независимо
подтверждено: `usuario-8e` — архивное письмо, бан 11.11, прилетело снова;
`usuario-03` — митинг STANDS WITH TRUMP три раза подряд на любой запрос
про Трампа).

ЧТО ТЕПЕРЬ. Рядом с md5-листом лежит `.banned_phash.json` — dHash 8x8
(64 бита, градиент по горизонтали). Два файла считаются ОДНИМ кадром, если
расстояние Хэмминга между хешами ≤ 6. Пережатая, уменьшенная и слегка
обрезанная копия даёт расстояние 0-4, то есть ловится; другой снимок того
же человека даёт 20+, то есть не ловится.

ЗАЩИТА ОТ ЛОЖНОГО СРАБАТЫВАНИЯ — ГЛАВНОЕ ЗДЕСЬ. У ровного кадра (чёрная
заглушка облака, размытая подложка, однотонное поле) хеш почти пустой или
почти полный, и такой «отпечаток» совпадает с любым другим ровным кадром.
Один забаненный тёмный кадр забанил бы ПОЛОВИНУ базы. Поэтому кадр с
плоским хешем (< 8 или > 56 единиц) и кадр с ничтожным разбросом яркости
(stddev < 6 по 32x32) отпечатка не получают вовсе: для них в силе прежний
md5, и ни записи, ни сверки по phash не происходит.

Путь переопределяется `VIDEORYAD_BANNED_PHASH_FILE` — так лист доезжает до
облачного раннера, у которого медиатеки нет (так же, как `VIDEORYAD_BANNED_FILE`
для md5). Порог — `VIDEORYAD_PHASH_DIST` (по умолчанию 6).
"""
import json
import os
import subprocess
import tempfile
import time

_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")

# ТРИ МАСШТАБА ВМЕСТО ОДНОГО — ИНАЧЕ ИНАЯ ОБРЕЗКА УХОДИТ ОТ БАНА (замер
# 13.11): пережатая копия даёт расстояние 0, а копия, у которой срезано по
# 6% с каждого края, — 13, то есть мимо порога 6. Поэтому и при бане, и при
# сверке считаем отпечаток ТРИЖДЫ: по всему кадру, по центральным 88% и по
# центральным 76%. Обрезанная копия своим полным кадром совпадает с нашим
# «центральные 88%» — и ловится на том же пороге 6, без его задирания
# (порог 13 начал бы путать разные снимки: у двух разных кадров замер дал 26,
# запас до 13 слишком мал).
SCALES = (1.0, 0.88, 0.76)

# ПУТЬ СЧИТАЕТСЯ ПРИ КАЖДОМ ОБРАЩЕНИИ, А НЕ ПРИ ИМПОРТЕ (2026-11-13). Лист
# phash лежит РЯДОМ с md5-листом, куда бы тот ни был переопределён, а
# переопределяют его В СЕРЕДИНЕ работы: `cloud_pipeline._ban_env()` ставит
# `VIDEORYAD_BANNED_FILE` уже после импорта модулей. Снимок на импорте дал бы
# путь к несуществующей медиатеке раннера — и бан по отпечатку молча не
# работал бы в облаке, ровно как это было с md5-листом до 2026-10-16.
def log_path():
    env = os.environ.get("VIDEORYAD_BANNED_PHASH_FILE")
    if env:
        return env
    md5log = os.environ.get("VIDEORYAD_BANNED_FILE") or os.path.expanduser(
        "~/projects/media-library/.banned_md5.json")
    if md5log.endswith(".banned_md5.json"):
        return md5log[: -len(".banned_md5.json")] + ".banned_phash.json"
    return os.path.join(os.path.dirname(md5log) or ".", ".banned_phash.json")


class _PathStr(str):
    """Строка-путь, которая всегда отдаёт АКТУАЛЬНЫЙ путь: старый код печатает
    `BANNED_PHASH_LOG` как строку, а внутри модуля зовётся `log_path()`."""
    def __str__(self):
        return log_path()

    def __repr__(self):
        return repr(log_path())


BANNED_PHASH_LOG = _PathStr(log_path())

try:
    PHASH_DIST = int(os.environ.get("VIDEORYAD_PHASH_DIST") or 6)
except ValueError:
    PHASH_DIST = 6

_CACHE = {"mtime": None, "set": set()}
_FILE_CACHE = {}


# ───────────────────────── отпечаток кадра ─────────────────────────
def _gray_array(path):
    """Серая матрица кадра. Для видео берём ОДИН кадр с середины файла —
    счёт ничтожный (одна распаковка), но без этого забаненный клип
    возвращается пережатым так же, как фото."""
    from PIL import Image
    import numpy as np

    if path.lower().endswith(_VIDEO_EXT):
        tmp = os.path.join(tempfile.gettempdir(),
                           "phash_%d_%d.png" % (os.getpid(), int(time.time() * 1000) % 100000))
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", "1", "-i", path,
                 "-frames:v", "1", "-vf", "scale=256:-1", "-y", tmp],
                check=True, timeout=25,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with Image.open(tmp) as im:
                return np.asarray(im.convert("L"), dtype=float)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    with Image.open(path) as im:
        return np.asarray(im.convert("L"), dtype=float)


def _dhash_image(im):
    """dHash одного изображения PIL. "" — кадру отпечаток давать НЕЛЬЗЯ."""
    import numpy as np
    from PIL import Image

    flat = np.asarray(im.resize((32, 32), Image.LANCZOS), dtype=float)
    if float(flat.std()) < 6.0:            # ровная заливка — только md5
        return ""
    small = np.asarray(im.resize((9, 8), Image.LANCZOS), dtype=float)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    ones = int(bits.sum())
    if ones < 8 or ones > 56:              # почти пустой/почти полный — плоско
        return ""
    val = 0
    for b in bits:
        val = (val << 1) | int(b)
    return "%016x" % val


def dhash_set(path):
    """Отпечатки кадра на трёх масштабах: весь кадр и два центральных среза.

    Пустой список — нечитаемый файл или кадр с ровной заливкой (такой хеш
    совпал бы с любым другим ровным кадром и забанил бы пол-базы; для них в
    силе прежний md5).
    """
    key = None
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_mtime, st.st_size)
        if key in _FILE_CACHE:
            return _FILE_CACHE[key]
    except OSError:
        return []
    out = []
    try:
        from PIL import Image

        arr = _gray_array(path)
        if arr is None or arr.size == 0:
            return []
        im = Image.fromarray(arr.astype("uint8"))
        w, h = im.size
        for sc in SCALES:
            if sc >= 0.999:
                cut = im
            else:
                dx, dy = int(w * (1 - sc) / 2), int(h * (1 - sc) / 2)
                if w - 2 * dx < 16 or h - 2 * dy < 16:
                    continue
                cut = im.crop((dx, dy, w - dx, h - dy))
            ph = _dhash_image(cut)
            if ph and ph not in out:
                out.append(ph)
    except Exception:
        return []
    if key:
        _FILE_CACHE[key] = out
    return out


def dhash_hex(path):
    """Главный отпечаток кадра (весь кадр) — 16 шестнадцатеричных цифр."""
    s = dhash_set(path)
    return s[0] if s else ""


def hamming(a, b):
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except (TypeError, ValueError):
        return 64


# ───────────────────────── лист и сверка ─────────────────────────
def load_banned_phash(this_project=""):
    """Активные отпечатки. Срок и «чужой временный бан» считаются ровно так
    же, как в `load_banned_md5`, — иначе временный бан рефетча выбивал бы
    кадр у соседней вкладки (правка 06.11 по md5, здесь повторена)."""
    path = log_path()
    if not os.path.exists(path):
        return set()
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return set()
    if not this_project:
        this_project = os.environ.get("VIDEORYAD_PROJECT") or \
            os.path.basename(os.path.abspath("."))
    ck = (mt, this_project, path)
    if _CACHE["mtime"] == ck:
        return _CACHE["set"]
    try:
        with open(path, encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        return set()
    today = time.strftime("%Y-%m-%d")
    out = set()
    for ph, e in log.items():
        if not isinstance(e, dict):
            e = {}
        if e.get("until") and e["until"] < today:
            continue
        own = str(e.get("project") or "")
        if own and e.get("until") and this_project and own != this_project:
            continue
        if ph:
            out.add(ph)
    _CACHE["mtime"] = ck
    _CACHE["set"] = out
    return out


def phash_banned(path, banned=None, this_project="", dist=None):
    """Этот ФАЙЛ — забаненный КАДР? Возвращает (да/нет, похожий_хеш, расстояние).

    Отличие от md5: ловит пережатую, уменьшенную и слегка обрезанную копию
    того же снимка, пришедшую с другого сайта.
    """
    mine = dhash_set(path)
    if not mine:
        return False, "", 64
    if banned is None:
        banned = load_banned_phash(this_project)
    if not banned:
        return False, "", 64
    lim = PHASH_DIST if dist is None else dist
    best, bd = "", 64
    for ph in mine:
        for b in banned:
            d = hamming(ph, b)
            if d < bd:
                best, bd = b, d
                if bd == 0:
                    return True, best, 0
    return (bd <= lim), best, bd


def ban_phash(path, md5="", reason="", until="", project=""):
    """Записать отпечаток кадра в лист. Зовётся из `ban_file.py` и дашборда
    ВМЕСТЕ с баном по md5 — md5 остаётся как точная метка файла."""
    hashes = dhash_set(path)
    if not hashes:
        return ""
    ph = hashes[0]
    path_log = log_path()
    log = {}
    if os.path.exists(path_log):
        try:
            with open(path_log, encoding="utf-8") as f:
                log = json.load(f)
        except (OSError, ValueError):
            log = {}
    e = {"md5": md5, "path": os.path.basename(path) if path else "",
         "reason": reason, "added": time.strftime("%Y-%m-%d")}
    if until:
        e["until"] = until
    if project:
        e["project"] = project
    for i, hh in enumerate(hashes):
        ee = dict(e)
        if i:
            ee["base"] = ph       # срез центра того же кадра, не отдельный бан
        log[hh] = ee
    os.makedirs(os.path.dirname(path_log) or ".", exist_ok=True)
    tmp = "%s.%d.tmp" % (path_log, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path_log)
    _CACHE["mtime"] = None
    return ph


def anonymized(src=None):
    """Обезличенная копия для облака: только хеш, срок и проект — без путей,
    причин и имён файлов (`ship.sh` везёт её в очередь раннера)."""
    src = src or log_path()
    try:
        with open(src, encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for ph, e in log.items():
        if not isinstance(e, dict):
            e = {}
        keep = {}
        if e.get("until"):
            keep["until"] = e["until"]
        if e.get("project"):
            keep["project"] = e["project"]
        out[ph] = keep
    return out


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print("лист: %s\nзаписей: %d\nпорог Хэмминга: %d"
              % (log_path(), len(load_banned_phash()), PHASH_DIST))
        raise SystemExit(0)
    ban = load_banned_phash()
    for p in args:
        ph = dhash_hex(p)
        hit, near, d = phash_banned(p, ban)
        print("%s\n  отпечаток: %s\n  забанен: %s (ближайший %s, расстояние %d)"
              % (p, ph or "НЕТ (ровный кадр — только md5)",
                 "ДА" if hit else "нет", near or "—", d))
