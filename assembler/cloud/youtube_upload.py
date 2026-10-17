#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Загрузка готового ролика на YouTube ЧЕРНОВИКОМ (приватным).

Зачем именно черновиком: пользователь (2026-10-16) — «мне как раз надо, чтобы
он висел не опубликованным, лежал черновиком, я потом к нему вернусь». Это
совпадает с ограничением самого YouTube: пока приложение не прошло проверку
Google, всё загруженное принудительно приватно. То есть ограничение нам не
мешает, и верификацию запрашивать не нужно.

Грузится ГОТОВЫЙ ролик полного цикла (озвучка + субтитры + инфографика +
всплывашки + эффекты), а не немой видеоряд: видеоряд пользователь монтирует
сам, выкладывать его некуда.

Написано на голом urllib без google-api-python-client: пакетов в системе нет,
ставить их ради трёх запросов незачем, а resumable-протокол — это два вызова.

НАСТРОЙКА (один раз, делает пользователь — нужен вход в его аккаунт):
  1. console.cloud.google.com → создать проект (любое имя).
  2. APIs & Services → Library → включить "YouTube Data API v3".
  3. APIs & Services → OAuth consent screen → External → заполнить название,
     свою почту; в Test users добавить почту того аккаунта, с которого ведётся
     канал (иначе вход вернёт "access_denied").
  4. Credentials → Create credentials → OAuth client ID → тип "Desktop app".
  5. Скопировать Client ID и Client secret и отдать их сюда:
       python3 youtube_upload.py auth <канал> <client_id> <client_secret>
     Скрипт напечатает ссылку: открыть в браузере, войти нужным аккаунтом,
     разрешить доступ. Дальше токен лежит локально и обновляется сам.

ЗАГРУЗКА:
  python3 youtube_upload.py send <канал> <файл.mp4> "Заголовок" [описание-файл]

Квота: 10 000 единиц в сутки, одна загрузка — 1600, то есть 6 роликов в день
на один проект Google Cloud. Больше — заводить второй проект.
"""
import http.server
import json
import os
import ssl
import sys
import threading
import urllib.parse
import urllib.request

CFG_DIR = os.path.expanduser("~/.config/videoryad-youtube")
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?uploadType=resumable&part=snippet,status")
CHUNK = 8 * 1024 * 1024          # 8 МБ за запрос — хватает и не держит память


def cfg_path(channel):
    return os.path.join(CFG_DIR, f"{channel}.json")


def load_cfg(channel):
    with open(cfg_path(channel), encoding="utf-8") as fh:
        return json.load(fh)


def save_cfg(channel, data):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(cfg_path(channel), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.chmod(cfg_path(channel), 0o600)       # токен — это доступ к каналу


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def do_auth(channel, client_id, client_secret):
    """Вход по loopback: поднимаем локальный сервер, Google возвращает код на
    него. Старый способ с ручным копированием кода (OOB) Google отключил."""
    code_box = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path).query
            code_box.update(urllib.parse.parse_qs(q))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in code_box
            self.wfile.write(("<h2>" + ("Готово, можно закрыть вкладку."
                             if ok else "Не получилось — см. терминал.") + "</h2>").encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    redirect = f"http://127.0.0.1:{port}"
    params = {"client_id": client_id, "redirect_uri": redirect, "response_type": "code",
              "scope": SCOPE, "access_type": "offline", "prompt": "consent"}
    print("\nОткрой эту ссылку в браузере и войди ТЕМ аккаунтом, где нужный канал:\n")
    print(AUTH_URL + "?" + urllib.parse.urlencode(params) + "\n")
    threading.Thread(target=srv.handle_request, daemon=True).start()
    import time
    for _ in range(600):                      # ждём до 10 минут
        if "code" in code_box:
            break
        time.sleep(1)
    if "code" not in code_box:
        print("код не пришёл — попробуй ещё раз"); return 1
    tok = _post(TOKEN_URL, {"code": code_box["code"][0], "client_id": client_id,
                            "client_secret": client_secret, "redirect_uri": redirect,
                            "grant_type": "authorization_code"})
    save_cfg(channel, {"client_id": client_id, "client_secret": client_secret,
                       "refresh_token": tok["refresh_token"]})
    print(f"готово: доступ к каналу «{channel}» сохранён в {cfg_path(channel)}")
    return 0


def access_token(channel):
    c = load_cfg(channel)
    tok = _post(TOKEN_URL, {"client_id": c["client_id"], "client_secret": c["client_secret"],
                            "refresh_token": c["refresh_token"], "grant_type": "refresh_token"})
    return tok["access_token"]


def send(channel, path, title, desc="", tags=None):
    token = access_token(channel)
    meta = {"snippet": {"title": title[:100], "description": desc[:4900],
                        "tags": tags or [], "categoryId": "25"},   # 25 = News & Politics
            "status": {"privacyStatus": "private",                 # ЧЕРНОВИК
                       "selfDeclaredMadeForKids": False}}
    size = os.path.getsize(path)
    req = urllib.request.Request(
        UPLOAD_URL, data=json.dumps(meta).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8",
                 "X-Upload-Content-Length": str(size),
                 "X-Upload-Content-Type": "video/*"})
    with urllib.request.urlopen(req, timeout=120) as r:
        session = r.headers["Location"]
    sent = 0
    with open(path, "rb") as fh:
        while sent < size:
            block = fh.read(CHUNK)
            end = sent + len(block) - 1
            put = urllib.request.Request(
                session, data=block, method="PUT",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Length": str(len(block)),
                         "Content-Range": f"bytes {sent}-{end}/{size}"})
            try:
                with urllib.request.urlopen(put, timeout=600) as r:
                    out = json.load(r)
                    print(f"\nзагружено: https://studio.youtube.com/video/{out['id']}/edit")
                    print("статус: ЧЕРНОВИК (приватное) — опубликуешь сам")
                    return 0
            except urllib.error.HTTPError as e:
                if e.code != 308:               # 308 = кусок принят, продолжаем
                    print("ошибка загрузки:", e.code, e.read()[:300].decode("utf-8", "replace"))
                    return 1
                rng = e.headers.get("Range")
                sent = int(rng.split("-")[1]) + 1 if rng else sent + len(block)
                print(f"\r  отправлено {sent/1048576:.0f} из {size/1048576:.0f} МБ", end="", flush=True)
    return 1


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 1
    cmd = sys.argv[1]
    if cmd == "auth" and len(sys.argv) == 5:
        return do_auth(sys.argv[2], sys.argv[3], sys.argv[4])
    if cmd == "send" and len(sys.argv) >= 5:
        desc = ""
        if len(sys.argv) > 5 and os.path.isfile(sys.argv[5]):
            desc = open(sys.argv[5], encoding="utf-8").read()
        return send(sys.argv[2], sys.argv[3], sys.argv[4], desc)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
