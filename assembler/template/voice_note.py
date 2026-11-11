#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Расшифровка голосового комментария к отказу (2026-10-16).

Пользователь жмёт микрофон на карточке дашборда и говорит, почему убирает
кадр. Браузер пишет webm/opus, сервер зовёт сюда, здесь ffmpeg приводит
к wav 16 кГц моно и faster-whisper расшифровывает по-русски.

Почему локально, а не Web Speech API браузера: тот работает только в Chrome,
требует интернета и отправляет голос в Google. Здесь всё остаётся на машине,
работает в любом браузере и не зависит от сети. `faster-whisper` уже стоял,
модель `small` уже скачана.

МОДЕЛЬ ЖИВЁТ В ОТДЕЛЬНОМ ПРОЦЕССЕ, А НЕ В ПАМЯТИ ДАШБОРДА (2026-11-09).
Замер: сам дашборд (страница, плитки, надписи, журнал) занимает 31 МБ, а
`WhisperModel("small", int8)` — ещё 594 МБ, и грузилась она В ПРОЦЕСС
СЕРВЕРА прямо на старте, фоновым потоком «погреть». Отсюда и брались
600-780 МБ на ролик: 97% этого веса — распознаватель, который молчит, пока
пользователь не нажмёт микрофон. При четырёх открытых дашбордах это 2,4 ГБ
на машине с 7,9 ГБ — она начинала терять вывод команд.
Теперь модель держит САЙДКАР: отдельный процесс, один на всю машину (его
находят по сокету в /tmp, поэтому четыре вкладки пользуются ОДНОЙ копией
модели, а не четырьмя), поднимается сам при первой диктовке и сам же
выходит через `VIDEORYAD_WHISPER_IDLE` секунд тишины, возвращая все 600 МБ
операционной системе. Дашборд остаётся на своих десятках мегабайт.

Цена вопроса замерена: загрузка модели 2,2 с, сама расшифровка 4-секундной
фразы 8-10 с. То есть первая диктовка после простоя дороже на 2,2 с (22% к
ожиданию), остальные — ровно как раньше. Если сайдкар не поднялся по любой
причине — расшифровка идёт в самом процессе, как до правки: функция не
теряется никогда, теряется только экономия.

Переключатели:
    VIDEORYAD_WHISPER_MODEL=base    размер модели (small — прежняя, втрое медленнее)
    VIDEORYAD_WHISPER_IDLE=86400    сколько секунд сайдкар ждёт работы
    VIDEORYAD_WHISPER_INPROC=1      грузить модель в свой процесс (как до правки)

Использование:
    python3 voice_note.py <audio-file>      # печатает расшифровку
    python3 voice_note.py --sidecar         # поднять сайдкар руками
    from voice_note import transcribe; transcribe(path)
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

# МОДЕЛЬ ПО УМОЛЧАНИЮ — `base`, А НЕ `small` (11.11.2026).
# Его слово три дня подряд: «с какого перепугу расшифровывается на моей
# машине? Почему не сразу? Почему долго?» Замер на одном и том же отрывке
# 4 с, нормальный приоритет, машина под восемью сессиями:
#     small  16,8 с · base  5,7 с · tiny  3,4 с
# Текст у `base` не хуже (`small`: «Если верить старое примете», `base`:
# «старые примете»), у `tiny` уже сыпется («старый приметет»). Поэтому
# `base`: втрое быстрее при том же качестве на коротких диктовках.
# Вернуть прежнюю: VIDEORYAD_WHISPER_MODEL=small
MODEL_SIZE = os.environ.get("VIDEORYAD_WHISPER_MODEL", "base")
_model = None

# Сколько сайдкар ждёт новой работы, прежде чем выйти и отдать память.
try:
    # СУТКИ, А НЕ ТРИ МИНУТЫ (11.11.2026): при 180 с сайдкар выходил между
    # диктовками, и КАЖДАЯ следующая снова грузила модель — это и было
    # «почему не сразу». Тёплым его держит `whisper_derzhi.sh` из cron.
    IDLE = float(os.environ.get("VIDEORYAD_WHISPER_IDLE", "86400"))
except ValueError:
    IDLE = 86400.0

# Сокет один на пользователя и на размер модели: четыре вкладки с открытыми
# дашбордами пользуются ОДНИМ сайдкаром, то есть одной копией модели.
_SOCK = os.path.join(tempfile.gettempdir(),
                     "videoryad-whisper-%d-%s.sock" % (os.getuid(), MODEL_SIZE))
_LOG = os.path.join(tempfile.gettempdir(),
                    "videoryad-whisper-%d.log" % os.getuid())

# Потолок ожидания ответа сайдкара. Расшифровка длинной фразы + загрузка
# модели — десятки секунд; 600 с с запасом, но не «навсегда»: зависший
# сайдкар не должен держать поток дашборда.
_WAIT = 600.0

# Подсказка модели: имена, которые в этих роликах звучат постоянно, а whisper
# по-русски их не знает и лепит похожее по звуку («Вэнс» → «венз», живой
# случай 2026-10-16). initial_prompt задаёт лексический контекст — модель
# начинает выбирать эти написания. Дополнять по мере появления новых фигур:
# стоит дёшево, а правка расшифровки руками стоит времени пользователя.
HINT = (
    "Вэнс, Трамп, Зеленский, Путин, Макрон, Мерц, Шольц, Ле Пен, Меланшон, "
    "Туск, Навроцкий, Си Цзиньпин, Мадуро, Рубио, Патель, Джорджеску, "
    "Вайдель, Орбан, Фицо, Стармер, Нетаньяху, Эрдоган, Лукашенко, Лавров, "
    "Медведев, Песков, Сикорский, Каллас, фон дер Ляйен, Гончаренко, "
    "НАТО, ЕС, ООН, ОБСЕ, МИД, Пентагон, Белый дом, Кремль, Брюссель, "
    "АдГ, Национальное объединение, Патриот, Ярс, Орешник, Шахед, "
    "всплывашка, видеоряд, сцена, кадр, сток, медиатека, дашборд"
)


def _log(msg):
    """Сайдкар пишет в файл, а не в никуда: молчащий распознаватель уже
    однажды стоил пользователю часа (2026-10-18)."""
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write("%s [%d] %s\n"
                     % (time.strftime("%H:%M:%S"), os.getpid(), msg))
    except OSError:
        pass


def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        # int8 на CPU — самый быстрый вариант без заметной потери качества
        # на коротких фразах; ролик этим не собирается, точность титров не нужна.
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def to_wav(src, dst=None):
    """webm/ogg/m4a -> wav 16k mono. Возвращает путь или None."""
    dst = dst or tempfile.mktemp(suffix=".wav")
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src,
         "-ac", "1", "-ar", "16000", dst],
        capture_output=True, text=True, timeout=60)
    return dst if r.returncode == 0 and os.path.exists(dst) else None


def _read_wav(path):
    """wav 16k mono -> float32 numpy в диапазоне [-1, 1].

    Своими руками, а не путём к файлу: встроенный в faster-whisper декодер
    зовёт `av.open(..., metadata_errors=...)`, а установленная здесь версия
    PyAV такого аргумента уже не принимает (TypeError, проверено 2026-10-16).
    Чинить версии пакетов нельзя — на том же faster-whisper стоит
    транскрипция озвучки в script-to-video. Массив модель принимает напрямую,
    и декодер не вызывается вообще.
    """
    import wave
    import numpy as np
    with wave.open(path, "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def _run_local(wav, language="ru"):
    """Расшифровка в ЭТОМ процессе — та же, что была до правки 09.11.
    Нужна сайдкару и остаётся запасным путём, если сайдкар не поднялся."""
    segments, _info = _load().transcribe(
        _read_wav(wav), language=language, vad_filter=True,
        initial_prompt=HINT,
        # beam_size=1 (greedy): замер 2026-10-16 на живой фразе — 7,7 с
        # против 9,5 с при дефолтных пяти лучах, текст побуквенно тот же.
        # Пользователь ждёт этот ответ, глядя в пустое поле, поэтому
        # каждая секунда тут дороже гипотетической точности. cpu_threads
        # не помогают вовсе (8 ядер против 4 — одно и то же время).
        beam_size=1,
        # фразы короткие и спонтанные; без этого whisper дорисовывает
        # «спасибо за просмотр» и прочие галлюцинации тишины
        condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments).strip()


# ----------------------------------------------------------- сайдкар ----
def _spawn_sidecar():
    """Поднять сайдкар и дождаться сокета. True — сокет готов."""
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--sidecar"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".")
    except Exception as exc:
        _log("сайдкар не запустился: %r" % (exc,))
        return False
    # Модель грузится ЛЕНИВО, уже после bind, поэтому сокет появляется
    # за доли секунды; 15 с — с запасом на холодный диск.
    for _ in range(150):
        if os.path.exists(_SOCK):
            return True
        time.sleep(0.1)
    _log("сайдкар не отдал сокет за 15 с")
    return False


def _ask_sidecar(wav, language="ru"):
    """Текст от сайдкара или None, если сайдкара нет и поднять не вышло."""
    for попытка in (0, 1):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(_WAIT)
        try:
            s.connect(_SOCK)
        except OSError:
            s.close()
            if попытка == 0 and _spawn_sidecar():
                continue
            return None
        try:
            s.sendall(json.dumps({"wav": os.path.abspath(wav),
                                  "language": language}).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            if not buf.strip():
                return None
            ans = json.loads(buf.decode("utf-8"))
            if ans.get("ok"):
                return ans.get("text", "") or ""
            _log("сайдкар вернул ошибку: %s" % ans.get("error"))
            return None
        except (OSError, ValueError) as exc:
            _log("разговор с сайдкаром сорвался: %r" % (exc,))
            return None
        finally:
            s.close()
    return None


def _sidecar():
    """Процесс-держатель модели. Слушает сокет, по простою выходит сам."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(_SOCK)
    except OSError:
        # Сокет на месте: либо кто-то уже слушает (тогда мы лишние), либо
        # он остался от убитого процесса (тогда забираем себе).
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(2)
            probe.connect(_SOCK)
            probe.close()
            return 0                      # живой сайдкар уже есть
        except OSError:
            pass
        try:
            os.unlink(_SOCK)
        except OSError:
            pass
        try:
            srv.bind(_SOCK)
        except OSError as exc:
            _log("не смог занять сокет: %r" % (exc,))
            return 1
    try:
        os.chmod(_SOCK, 0o600)
    except OSError:
        pass
    srv.listen(8)
    srv.settimeout(IDLE)
    _log("сайдкар поднят, модель %s, простой до выхода %.0f с"
         % (MODEL_SIZE, IDLE))
    сделано = 0
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                _log("простой %.0f с — выхожу, память возвращаю системе "
                     "(расшифровок за жизнь: %d)" % (IDLE, сделано))
                break
            except OSError as exc:
                _log("accept сорвался: %r" % (exc,))
                break
            conn.settimeout(_WAIT)
            try:
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                if not buf.strip():
                    continue
                req = json.loads(buf.decode("utf-8"))
                wav = req.get("wav") or ""
                if req.get("ping"):
                    ответ = {"ok": True, "text": ""}
                elif req.get("warm"):
                    _load()
                    ответ = {"ok": True, "text": ""}
                elif not os.path.exists(wav):
                    ответ = {"ok": False, "error": "нет файла %s" % wav}
                else:
                    t0 = time.time()
                    текст = _run_local(wav, req.get("language") or "ru")
                    сделано += 1
                    _log("расшифровка за %.1f с: %r" % (time.time() - t0,
                                                        текст[:80]))
                    ответ = {"ok": True, "text": текст}
            except Exception as exc:          # ни одна поломка не валит сайдкар
                _log("ОШИБКА на задании: %r" % (exc,))
                ответ = {"ok": False, "error": repr(exc)}
            try:
                conn.sendall(json.dumps(ответ, ensure_ascii=False).encode()
                             + b"\n")
            except OSError:
                pass
            finally:
                conn.close()
    finally:
        try:
            srv.close()
        except OSError:
            pass
        try:
            os.unlink(_SOCK)
        except OSError:
            pass
    return 0


def warm_sidecar():
    """Поднять сайдкар и попросить его загрузить модель заранее.

    Зовётся дашбордом только при VIDEORYAD_WHISPER_WARM=1: по умолчанию
    модель не грузится вовсе, пока пользователь не нажал микрофон.
    Память при этом уходит САЙДКАРУ, а не серверу дашборда.
    """
    try:
        if not os.path.exists(_SOCK) and not _spawn_sidecar():
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(_WAIT)
        try:
            s.connect(_SOCK)
            s.sendall(b'{"warm": true}\n')
            s.recv(4096)
        finally:
            s.close()
        return True
    except Exception:
        return False


def transcribe(path, language="ru"):
    """Текст расшифровки или "" — никогда не бросает: пустой комментарий
    не должен ронять отказ, пользователь уже нажал кнопку."""
    wav = None
    try:
        wav = to_wav(path)
        if not wav:
            return ""
        if os.environ.get("VIDEORYAD_WHISPER_INPROC") == "1":
            return _run_local(wav, language)
        текст = _ask_sidecar(wav, language)
        if текст is None:
            # Сайдкар не поднялся — расшифровываем здесь, как до правки
            # 09.11. Печатаем в лог сервера: функция цела, но 600 МБ
            # осели в дашборде, и это надо видеть.
            print("[voice] сайдкар не ответил — расшифровываю в процессе "
                  "дашборда (память не экономится), см. %s" % _LOG, flush=True)
            текст = _run_local(wav, language)
        return текст
    except Exception:
        return ""
    finally:
        if wav and os.path.exists(wav):
            try:
                os.remove(wav)
            except OSError:
                pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sidecar":
        raise SystemExit(_sidecar())
    if len(sys.argv) > 1 and sys.argv[1] == "--warm":
        raise SystemExit(0 if warm_sidecar() else 1)
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    print(transcribe(sys.argv[1]))
