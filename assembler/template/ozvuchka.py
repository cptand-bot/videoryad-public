#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОЗВУЧКА ТЕКСТОВ ДНЯ ЧЕРЕЗ СЕРВИС VoiceGen — ШАГ ПЕРЕД СБОРКОЙ (07.11.2026).

    python3 ozvuchka.py "<папка дня>"        # все темы дня подряд
    python3 ozvuchka.py "<папка темы>"       # одна тема
    python3 ozvuchka.py "<папка>" --check    # только проверка текста, без отправки
    python3 ozvuchka.py "<папка>" --voice "5 МИНУТ"   # шаблон вручную

ЗАЧЕМ: раньше пользователь сам гонял каждый текст через телеграм-бота и
клал `.mp3` и `.srt` рядом с `.txt`. Теперь это делает вкладка: получила
папку дня — озвучила все три темы, разложила файлы по папкам тем, и дальше
идёт обычный конвейер (`take_folder.py` → георадар → раскадровка → фетч).

ЧТО ВАЖНО И ПОЧЕМУ ИМЕННО ТАК:

* ШАБЛОН БЕРЁТСЯ ИЗ ПУТИ, как и канал везде в сборщике. Папка лежит в
  `…/5 МИНУТ/НОЯБРЬ/07-11/3-Космос война/` — значит шаблон «5 МИНУТ».
  Отдельно шаблон не спрашиваем (его прямое слово 07.11).

* ТЕКСТ ПРОВЕРЯЕТСЯ ДО ОТПРАВКИ. Переозвучка стоит дороже проверки:
  испорченный голос слышно только ушами и только после ролика. Главная
  мина — ЦИФРЫ: сервис читает их сам и склоняет неверно («две тысячи
  четыре году» вместо «две тысячи четвёртом году», память
  `feedback_tts_numbers_as_words`, его слово 05.10). Поэтому цифра в
  тексте — это стоп, а не предупреждение.

* РЕЗУЛЬТАТ ПРОВЕРЯЕТСЯ ЗАПУСКОМ, А НЕ НАЛИЧИЕМ ФАЙЛА (главный урок
  24.10: «успех» может значить «ничего не сделано»). Файл может прийти
  немым, обрезанным на середине текста или с пустым SRT — всё это
  ловится здесь, до того как ролик уедет в облако.

* РЕСУРСЫ МАШИНЫ НЕ ТРАТЯТСЯ: это сеть и ffprobe на пару секунд, счёта
  на ПК тут нет (его слово 23.10).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time


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


HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HERE, ".env")

# ──────────────────────────────────────────────────────────────────────
# КАНАЛ → ШАБЛОН В СЕРВИСЕ (скриншот бота «Мои шаблоны», 07.11.2026)
# Шаблон — это голос плюс его настройки, заведён пользователем заранее.
# ──────────────────────────────────────────────────────────────────────
TEMPLATES = {
    "ПЛАНЕТА": "ПЛАНЕТА",
    "5 МИНУТ": "5 МИНУТ",
    "ОЛЬКА": "ОЛЬКА NEWS",
    "ОЛЬКА НОВОСТИ": "ОЛЬКА NEWS",
    "ОЛЬГА ДАЙДЖЕСТ": "ОЛЬКА NEWS",
    "ДИПЛОМАТИЯ СИЛЫ": "ДОНОР1-ДИПЛОМАТИЯ СИЛЫ",
}
# «ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО» в списке шаблонов отсутствует — пользователь
# назовёт, каким его озвучивать; до тех пор инструмент честно встаёт.

# Служебные тексты, которые НЕ являются озвучкой: задания агенту, ответы,
# брифы. Их в сервис отправлять нельзя (это сотни килобайт инструкций).
SKIP_TXT = ("ЗАДАНИЕ", "БРИФ", "ОТВЕТ", "ПРОМПТ", "NOTES", "README",
            "ПРЕДЛОЖЕНИЯ", "ВИЗУАЛ", "ЗАМЕТКИ", "СОСТОЯНИЕ", "ИТОГ")


def load_env():
    """Ключ и адрес сервиса лежат в `template/.env` рядом с ключами стоков."""
    env = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in ("VOICEGEN_API_KEY", "VOICEGEN_API_URL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def channel_of(path):
    """Канал — из ПУТИ и только из пути (правило всего сборщика)."""
    parts = [p.strip().upper() for p in
             os.path.abspath(path).replace("\\", "/").split("/")]
    for part in parts:
        for name in TEMPLATES:
            if part == name or part.startswith(name + " "):
                return name
        if part.startswith("ПЕРЕВОД"):
            return "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО"
    return ""


def template_of(path):
    ch = channel_of(path)
    if not ch:
        return "", ""
    if ch not in TEMPLATES:
        return ch, ""
    return ch, TEMPLATES[ch]


def find_text(folder):
    """Текст озвучки в папке темы — единственный содержательный `.txt`."""
    found = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".txt"):
            continue
        up = name.upper()
        if any(up.startswith(s) or s in up for s in SKIP_TXT):
            continue
        found.append(os.path.join(folder, name))
    return found


# ──────────────────────────────────────────────────────────────────────
# ГЕЙТ ТЕКСТА — ДО ОТПРАВКИ
# ──────────────────────────────────────────────────────────────────────
def check_text(path):
    """Возвращает (ошибки, замечания). Ошибка = не отправляем."""
    text = read_text(path)
    errors, notes = [], []

    if len(text.strip()) < 200:
        errors.append("текст короче 200 знаков — похоже, это не озвучка")

    # ЦИФРЫ. Сервис произносит их сам и склоняет неверно.
    digits = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in re.finditer(r"\d[\d\s.,:/-]*", line):
            frag = m.group(0).strip(" .,:/-")
            if frag:
                digits.append((i, frag))
    if digits:
        show = "; ".join("стр.%d «%s»" % (i, f) for i, f in digits[:8])
        errors.append("ЦИФРЫ в тексте (%d шт.): %s%s — писать прописью с "
                      "падежом, иначе голос склоняет неверно"
                      % (len(digits), show, " …" if len(digits) > 8 else ""))

    # Латиница словами: читается по буквам или по-английски.
    lat = sorted(set(re.findall(r"\b[A-Za-z]{2,}\b", text)))
    if lat:
        notes.append("латиница: %s — проверить, как это прозвучит"
                     % ", ".join(lat[:10]))

    # «Ё» — ПОСЛЕДНИЙ РУБЕЖ ПЕРЕД СЕРВИСОМ (07.11). Текст без единой «ё»
    # на длине больше двух тысяч знаков — это не стиль автора, а потерянная
    # буква: в русском тексте такой длины «ё» встречается десятками. Сервис
    # прочтёт «все» вместо «всё» и «еще» вместо «ещё», и слышно это будет
    # только в готовом ролике. Живой случай: рерайт темы 1 ушёл в озвучку с
    # нулём «ё» при 61 в оригинале.
    _yo = text.count("ё") + text.count("Ё")
    if len(text) > 2000 and _yo == 0:
        errors.append("В ТЕКСТЕ НЕТ НИ ОДНОЙ «Ё» (%d знаков) — озвучка "
                      "прочтёт «все» вместо «всё». Вернуть букву." % len(text))
    elif len(text) > 2000 and _yo < len(text) / 1200:
        notes.append("«ё» всего %d на %d знаков — проверь, не потеряна ли"
                     % (_yo, len(text)))

    # Грубая оценка длительности: ~14 знаков в секунду русской речи.
    secs = len(text) / 14.0
    notes.append("текст %d знаков ≈ %d:%02d звучания"
                 % (len(text), int(secs // 60), int(secs % 60)))
    return errors, notes


# ──────────────────────────────────────────────────────────────────────
# ТРАНСПОРТ К СЕРВИСУ
# ──────────────────────────────────────────────────────────────────────
def _req(env, method, path, body=None, raw=False, timeout=180):
    """Один запрос к сервису. Ключ — заголовком X-API-Key (так описано в
    их OpenAPI: components.securitySchemes.APIKeyHeader)."""
    import urllib.request
    import urllib.error
    url = path if path.startswith("http") else env["VOICEGEN_API_URL"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-Key", env["VOICEGEN_API_KEY"])
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            blob = r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit("сервис ответил %s на %s %s: %s"
                         % (e.code, method, path, e.read()[:300].decode("utf-8", "replace")))
    return blob if raw else json.loads(blob.decode("utf-8"))


def templates_list(env):
    """Шаблоны, заведённые пользователем в боте: имя → id."""
    return {t["name"]: t["id"] for t in _req(env, "GET", "/api/v1/client/templates")}


def synth(text, template, env, timeout=3600):
    """Отдаёт (mp3-байты, srt-текст).

    Путь ровно тот же, что у пользователя в боте: задача на шаблоне, очередь
    сервиса, потом готовый файл. Субтитры просим сразу (`include_timestamps`),
    нарезка по фразам — так же, как стоит в его шаблонах
    (`_voicegen_timestamps_granularity: phrase`).
    """
    if not env.get("VOICEGEN_API_KEY"):
        raise SystemExit("нет VOICEGEN_API_KEY в template/.env")
    if not env.get("VOICEGEN_API_URL"):
        raise SystemExit("нет VOICEGEN_API_URL в template/.env")

    tpls = templates_list(env)
    if template not in tpls:
        raise SystemExit("шаблона «%s» в сервисе нет. Есть: %s"
                         % (template, ", ".join(sorted(tpls))))

    payload = {
        "text": text,
        "template_id": tpls[template],
        "include_timestamps": True,
        "timestamps_granularity": "phrase",
        "auto_start": True,
    }
    ans = _req(env, "POST", "/api/v1/client/tasks", payload)
    task = (ans.get("task") or {})
    task_id = task.get("task_id") or task.get("id")
    if not task_id:
        raise SystemExit("сервис не вернул номер задачи: %s" % str(ans)[:300])

    # Ждём и смотрим СОСТОЯНИЕ, а не факт ответа (урок 24.10: «успех» может
    # значить «ничего не сделано»).
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        st = _req(env, "GET", "/api/v1/client/tasks/%s/state" % task_id)
        status = (st.get("status") or "").lower()
        if status != last:
            print("      %s %s" % (status, st.get("status_message") or ""))
            last = status
        if status in ("completed", "done", "finished", "success"):
            break
        if status in ("failed", "error", "cancelled", "canceled"):
            raise SystemExit("озвучка не удалась: %s"
                             % (st.get("error_message") or status))
        time.sleep(5)
    else:
        raise SystemExit("сервис не отдал результат за %d с" % timeout)

    audio = _req(env, "GET",
                 st.get("result_download_url")
                 or "/api/v1/client/tasks/%s/download" % task_id, raw=True)
    subs = _req(env, "GET",
                st.get("timestamps_url")
                or "/downloads/tasks/%s/timestamps" % task_id, raw=True)
    return audio, subs.decode("utf-8", "replace")


# ──────────────────────────────────────────────────────────────────────
# ПРОВЕРКА РЕЗУЛЬТАТА — ЗАПУСКОМ, А НЕ НАЛИЧИЕМ ФАЙЛА
# ──────────────────────────────────────────────────────────────────────
def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def max_volume(path):
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path, "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", out)
    return float(m.group(1)) if m else -99.0


def srt_tail_seconds(srt_text):
    stamps = re.findall(r"(\d\d):(\d\d):(\d\d)[,.](\d\d\d)\s*-->", srt_text)
    if not stamps:
        return 0.0
    h, m, s, ms = stamps[-1]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def check_result(mp3, srt, text_path):
    """Ловит немой файл, обрыв на середине текста и пустой SRT."""
    problems = []
    dur = probe_duration(mp3)
    if dur < 1:
        problems.append("озвучка пустая (%.1f с)" % dur)
    vol = max_volume(mp3)
    if vol < -50:
        problems.append("файл немой (max_volume %.1f dB)" % vol)

    srt_text = read_text(srt) \
        if os.path.exists(srt) else ""
    blocks = len(re.findall(r"-->", srt_text))
    if blocks < 5:
        problems.append("в SRT всего %d строк" % blocks)
    tail = srt_tail_seconds(srt_text)
    if dur and tail and abs(tail - dur) > 5:
        problems.append("SRT обрывается на %.0f с при длине звука %.0f с — "
                        "текст озвучен не целиком" % (tail, dur))

    # Последние слова текста должны встретиться в хвосте субтитров.
    text = read_text(text_path)
    words = re.findall(r"[А-Яа-яЁё]{4,}", text)
    if words and srt_text:
        last = words[-1].lower()
        if last not in srt_text.lower()[-1500:]:
            problems.append("последнего слова текста («%s») нет в конце SRT" % last)
    return dur, problems


# ──────────────────────────────────────────────────────────────────────
def do_folder(folder, args, env):
    ch, tpl = template_of(folder)
    if args.voice:
        tpl = args.voice
    if not ch:
        print("  ✗ канал не читается из пути — %s" % folder)
        return False
    if not tpl:
        print("  ✗ для канала «%s» шаблон в сервисе не заведён — назови его "
              "или задай --voice" % ch)
        return False

    texts = find_text(folder)
    if not texts:
        print("  ✗ текста озвучки в папке нет")
        return False
    if len(texts) > 1:
        print("  ! текстов несколько, беру самый большой: %s"
              % ", ".join(os.path.basename(t) for t in texts))
    src = max(texts, key=lambda p: os.path.getsize(p))
    base = os.path.splitext(os.path.basename(src))[0]
    mp3 = os.path.join(folder, base + ".mp3")
    srt = os.path.join(folder, base + ".srt")

    print("  тема: %s" % os.path.basename(folder))
    print("  текст: %s" % os.path.basename(src))
    print("  шаблон: %s (канал %s)" % (tpl, ch))

    errors, notes = check_text(src)
    for n in notes:
        print("    · %s" % n)
    for e in errors:
        print("    ✗ %s" % e)
    if errors:
        return False
    if args.check:
        print("    ✓ текст к озвучке готов")
        return True

    if os.path.exists(mp3) and not args.force:
        print("    = озвучка уже лежит рядом, пропускаю (--force перезапишет)")
        return True

    text = read_text(src)
    t0 = time.time()
    audio, subs = synth(text, tpl, env)
    open(mp3, "wb").write(audio)
    open(srt, "w", encoding="utf-8").write(subs)

    dur, problems = check_result(mp3, srt, src)
    print("    звук %d:%02d, сделано за %d с" % (dur // 60, dur % 60, time.time() - t0))
    for p in problems:
        print("    ✗ %s" % p)
    if problems:
        return False
    print("    ✓ %s + .srt" % os.path.basename(mp3))
    return True


def find_targets(root, depth=5):
    """Все папки тем под корнем: есть текст озвучки, глубина до пяти уровней.

    ПЯТЬ, А НЕ ТРИ. Живой промах 07.11: сторож на корне `НОВОСТИ` молчал на
    только что положенной теме, потому что её путь
    `НОВОСТИ / 5 МИНУТ / НОЯБРЬ / 08-11 / 1-Тема` — это ЧЕТЫРЕ уровня, а
    предел стоял три. Ошибки при этом не было никакой: сторож исправно
    делал круги и честно не находил ничего. Запас берём с головой."""
    out = []
    if find_text(root):
        out.append(root)
    base = root.rstrip("/").count("/")
    for cur, dirs, _files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("thumbs", "images", "clips", "cards")]
        if cur.rstrip("/").count("/") - base > depth:
            dirs[:] = []
            continue
        if cur != root and find_text(cur):
            out.append(cur)
    return sorted(set(out))


def needs_voice(folder):
    """Тема ждёт озвучки: текст есть, а звука в папке нет НИКАКОГО.

    Сравнивать имена нельзя: бот отдаёт файл с заменой запятых и двоеточий
    на подчёркивание («ТРАМП, АБУ-ДАБИ.txt» → «ТРАМП_ АБУ-ДАБИ.mp3»), и
    точное совпадение имени дало бы «озвучки нет» на уже озвученной теме —
    а это повторная трата знаков пакета.

    И шаблон обязателен: без него это не тема канала, а чужая папка
    (код сборщика, отчёты смен, другой сборщик) — туда сторож не лезет."""
    if not find_text(folder):
        return False
    if not template_of(folder)[1]:
        return False
    for name in os.listdir(folder):
        if name.lower().endswith((".mp3", ".wav", ".m4a")):
            return False
    return True


def watch(root, args, env):
    """СТОРОЖ: озвучка отвязана от вкладок.

    Пользователь пишет тексты быстрее, чем вкладки сдают ролики (ролик это
    полчаса с лишним, текст — минуты). Поэтому озвучка не ждёт ничью вкладку:
    сторож сам обходит дерево, видит новую папку темы с текстом и без звука —
    и озвучивает. К моменту, когда вкладка освободится, её тема уже лежит
    готовой парой mp3+srt."""
    print("СТОРОЖ: %s, проверка каждые %d с. Ctrl+C — выход." % (root, args.every))
    seen = set()
    while True:
        try:
            fresh = [t for t in find_targets(root) if needs_voice(t) and t not in seen]
            # Старый архив не всплывает: сторож берёт только то, что положено
            # недавно. Иначе одна команда на корне канала переозвучила бы
            # месяц и сожгла пакет знаков.
            if args.max_age:
                edge = time.time() - args.max_age * 86400
                fresh = [t for t in fresh
                         if max(os.path.getmtime(x) for x in find_text(t)) > edge]
            fresh = fresh[:5]
            for t in fresh:
                print("\n[%s] новая тема" % time.strftime("%H:%M:%S"))
                if do_folder(t, args, env):
                    seen.add(t)
        except Exception as exc:  # сторож не должен падать насовсем
            print("[%s] сбой круга: %s" % (time.strftime("%H:%M:%S"), exc))
        time.sleep(args.every)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="папка дня или папка одной темы")
    ap.add_argument("--voice", help="шаблон вручную")
    ap.add_argument("--check", action="store_true", help="только проверка текста")
    ap.add_argument("--force", action="store_true", help="переозвучить поверх")
    ap.add_argument("--watch", action="store_true",
                    help="сторожить папку: озвучивать всё новое по мере появления")
    ap.add_argument("--max-age", type=int, default=3,
                    help="сторож берёт темы не старше стольких дней (0 — любые)")
    ap.add_argument("--every", type=int, default=60,
                    help="как часто смотреть папку в режиме --watch, секунд")
    args = ap.parse_args()
    env = load_env()

    root = os.path.abspath(args.folder)
    if not os.path.isdir(root):
        sys.exit("нет такой папки: %s" % root)

    if args.watch:
        watch(root, args, env)
        return

    targets = find_targets(root)
    print("ОЗВУЧКА: %d тем" % len(targets))
    ok = 0
    for t in targets:
        if do_folder(t, args, env):
            ok += 1
        print()
    print("готово: %d из %d" % (ok, len(targets)))
    sys.exit(0 if ok == len(targets) else 1)


if __name__ == "__main__":
    main()
