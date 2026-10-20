#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кадр из ЛЮБОГО доступного видео — файла на диске или прямой ссылки.

Замена `grab_stream_frame.py`, который брал кадр из YouTube и мёртв с
23.08.2026: YouTube требует PoToken, и видеоданные не отдаются вообще —
проверено снова 19.10.2026, в списке форматов остались только звуковые
дорожки. Чинить это нужно отдельным провайдером токенов, и это не
быстрая правка.

Но сам приём — «взять кадр из ролика в нужную секунду» — нужен часто, и
источников кроме YouTube хватает:

  * видео, прикреплённое к посту в телеграм-канале источника
    (качается обычным curl, см. раздел про георадар);
  * видеофайл с официального сайта (kremlin.ru, whitehouse.gov,
    сайты ведомств);
  * любой .mp4 / .webm / .m3u8 по прямой ссылке;
  * видео, уже лежащее в медиатеке.

Использование:
    python3 grab_video_frame.py <файл-или-url> <время> <out.jpg> [ffmpeg]

    <время> — секунды, либо мм:сс, либо чч:мм:сс

Кадр берётся точно, с перекодированием одного кадра в JPEG качества 2.
Для .m3u8 и длинных файлов ffmpeg сам доматывает до нужной точки.

ПОМНИ ПРО ПРАВА И БРАК: кадр из чужого ролика может нести логотип
канала, подпись или субтитры, вжатые загрузившим. Перед тем как ставить
такой кадр в сборку, посмотри его глазами — это ровно тот случай, ради
которого существует бан по содержимому.
"""
import os
import subprocess
import sys


def parse_ts(v):
    parts = [float(x) for x in str(v).split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        raise SystemExit(1)
    src, ts, out = sys.argv[1], parse_ts(sys.argv[2]), sys.argv[3]
    ffmpeg = sys.argv[4] if len(sys.argv) > 4 else "ffmpeg"

    if "youtube.com" in src or "youtu.be" in src:
        print("YouTube не отдаёт видеоданные без PoToken (проверено 19.10.2026).")
        print("Возьми тот же материал из телеграм-поста источника, с сайта")
        print("ведомства или из медиатеки — и передай ссылку на сам файл.")
        raise SystemExit(2)

    cmd = ["nice", "-n", "19", ffmpeg, "-v", "error", "-y",
           "-ss", f"{ts:.3f}", "-i", src,
           "-frames:v", "1", "-q:v", "2", "-threads", "2", out]
    r = subprocess.run(cmd)
    if r.returncode != 0 or not os.path.exists(out):
        print("кадр взять не удалось — проверь ссылку и время")
        raise SystemExit(3)
    sz = os.path.getsize(out)
    print(f"кадр {ts:.2f} с -> {out} ({sz // 1024} КБ). Посмотри его глазами: "
          "логотип канала и чужие субтитры — это брак.")


if __name__ == "__main__":
    main()
