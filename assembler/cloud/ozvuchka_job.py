#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОЗВУЧКА В ОБЛАКЕ — ОБХОД БЛОКИРОВКИ ЕГО СЕТИ (08.11.2026).

Повод: вечером 08.11 с его машины перестали устанавливаться соединения с
адресами, на которые указывает `api.qw1voicegencore.pro` (188.114.96.5 и
188.114.97.5). Замер показал, что блокируются именно ЭТИ адреса: соседние
в том же диапазоне Cloudflare (…96.1, …97.1) открываются, GitHub и Discord
работают, а из облака GitHub сервис отвечает нормально. То есть сервис жив,
недоступна только дорога от него.

Его решение: «если увести озвучку в облако, текст уходит в GitHub, пускай
там будет, мне всё равно».

Скрипт работает НА РАННЕРЕ: читает текст, зовёт сервис его ключом из
секрета и кладёт рядом mp3 и srt. Логика взята из `template/ozvuchka.py`
дословно — один и тот же путь, чтобы результат не отличался ни на байт.

    python3 ozvuchka_job.py <текст.txt> <ИМЯ ШАБЛОНА> <куда класть>
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("VOICEGEN_API_URL", "https://api.qw1voicegencore.pro")
KEY = os.environ.get("VOICEGEN_API_KEY", "")


def _req(method, path, body=None, raw=False, timeout=180):
    url = path if path.startswith("http") else URL.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-Key", KEY)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            blob = r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit("сервис ответил %s на %s %s: %s"
                         % (e.code, method, path,
                            e.read()[:300].decode("utf-8", "replace")))
    return blob if raw else json.loads(blob.decode("utf-8"))


def читать(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", "replace")


def main():
    if len(sys.argv) < 4:
        sys.exit("ozvuchka_job.py <текст.txt> <шаблон> <папка результата>")
    текст_файл, шаблон, куда = sys.argv[1], sys.argv[2], sys.argv[3]
    if not KEY:
        sys.exit("нет VOICEGEN_API_KEY в окружении раннера (секрет репозитория)")

    текст = читать(текст_файл).strip()
    print("текст: %d знаков, шаблон: %s" % (len(текст), шаблон))

    tpls = {t["name"]: t["id"] for t in _req("GET", "/api/v1/client/templates")}
    if шаблон not in tpls:
        sys.exit("шаблона «%s» в сервисе нет. Есть: %s"
                 % (шаблон, ", ".join(sorted(tpls))))

    ans = _req("POST", "/api/v1/client/tasks",
               {"text": текст, "template_id": tpls[шаблон],
                "include_timestamps": True,
                "timestamps_granularity": "phrase", "auto_start": True})
    task = ans.get("task") or {}
    tid = task.get("task_id") or task.get("id")
    if not tid:
        sys.exit("сервис не вернул номер задачи: %s" % str(ans)[:300])
    print("задача: %s" % tid)

    # СМОТРИМ СОСТОЯНИЕ, А НЕ ФАКТ ОТВЕТА (урок 24.10: «успех» может значить
    # «ничего не сделано»).
    deadline, last, st = time.time() + 3600, "", {}
    while time.time() < deadline:
        st = _req("GET", "/api/v1/client/tasks/%s/state" % tid)
        status = (st.get("status") or "").lower()
        if status != last:
            print("  %s %s" % (status, st.get("status_message") or ""))
            last = status
        if status in ("completed", "done", "finished", "success"):
            break
        if status in ("failed", "error", "cancelled", "canceled"):
            sys.exit("озвучка не удалась: %s" % (st.get("error_message") or status))
        time.sleep(5)
    else:
        sys.exit("сервис не отдал результат за час")

    audio = _req("GET", st.get("result_download_url")
                 or "/api/v1/client/tasks/%s/download" % tid, raw=True)
    subs = _req("GET", st.get("timestamps_url")
                or "/downloads/tasks/%s/timestamps" % tid, raw=True)

    os.makedirs(куда, exist_ok=True)
    имя = os.path.splitext(os.path.basename(текст_файл))[0]
    mp3 = os.path.join(куда, имя + ".mp3")
    srt = os.path.join(куда, имя + ".srt")
    open(mp3, "wb").write(audio)
    open(srt, "w", encoding="utf-8").write(subs.decode("utf-8", "replace"))
    print("готово: %s (%.1f МБ) + %s" % (os.path.basename(mp3),
                                         len(audio) / 1048576.0,
                                         os.path.basename(srt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
