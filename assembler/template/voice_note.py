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

Модель грузится один раз на процесс и живёт в памяти — первый вызов
медленнее (несколько секунд), дальше расшифровка короткой фразы занимает
примерно столько же, сколько сама фраза.

Использование:
    python3 voice_note.py <audio-file>      # печатает расшифровку
    from voice_note import transcribe; transcribe(path)
"""
import os
import subprocess
import tempfile

MODEL_SIZE = os.environ.get("VIDEORYAD_WHISPER_MODEL", "small")
_model = None

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


def transcribe(path, language="ru"):
    """Текст расшифровки или "" — никогда не бросает: пустой комментарий
    не должен ронять отказ, пользователь уже нажал кнопку."""
    wav = None
    try:
        wav = to_wav(path)
        if not wav:
            return ""
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
    except Exception:
        return ""
    finally:
        if wav and os.path.exists(wav):
            try:
                os.remove(wav)
            except OSError:
                pass


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    print(transcribe(sys.argv[1]))
