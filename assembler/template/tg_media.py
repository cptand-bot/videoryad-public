#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ВЛОЖЕНИЯ ТЕЛЕГРАМ-ПОСТА — ОДНОЙ КОМАНДОЙ, БЕЗ РУЧНОГО РАЗБОРА РАЗМЕТКИ.

    python3 tg_media.py <ссылка на пост> [ещё ссылки ...]
    python3 tg_media.py --json out.json <ссылки ...>   # машинно, для scenes.json

Печатает по каждому посту: что в нём лежит (фото/видео), ПОЛНЫЙ адрес файла,
размер кадра и длительность. Ничего не качает (кроме заголовков видео).

ЗАЧЕМ ОТДЕЛЬНЫЙ ИНСТРУМЕНТ. Вкладки разбирали разметку поста руками, каждая
по-своему, и за один день 26.10 это дало ТРИ разных способа потерять кадр:

1. **Адрес обрезается в консоли.** Токен `cdn4.telesco.pe/file/…mp4?token=`
   бывает длиной до 400 знаков, печать режет на 110. Скопированный глазами
   обрезок даёт `HTTP Error 404`, и это читается как «токен истёк» — мы
   трижды записывали это в скилл именно так. Здесь адрес НИКОГДА не идёт
   через глаза: `--json` кладёт его в файл, который читает фетч.
2. **Аватарка канала вместо кадра.** В блоке поста бывает второй адрес —
   `tgme_widget_message_user_photo`; берём только из `photo_wrap` и
   `video_thumb`.
3. **Чужой пост.** Грепать всю страницу нельзя: она отдаёт ленту канала.
   Режем строго от своего `data-post` до следующего.

И четвёртое, найденное в тот же день: у крупного видео телеграм НЕ публикует
mp4 в веб-превью вовсе — в разметке стоит `not_supported`, хотя длительность
рядом живая. Это видно ДО любой попытки скачивания, и круги на `?embed=1`
тратить незачем — инструмент так и пишет: «видео есть, файла нет».
"""
import json
import re
import subprocess
import sys
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64)"


def _get(url, referer=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               **({"Referer": referer} if referer else {})})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="ignore")


def _block(html, chan, mid):
    """Кусок разметки РОВНО этого поста: от своего якоря до следующего."""
    anchor = 'data-post="%s/%s"' % (chan, mid)
    i = html.find(anchor)
    if i < 0:
        return ""
    j = html.find("data-post=", i + len(anchor))
    return html[i:j if j > 0 else len(html)]


def _probe(url, referer):
    """Размер кадра и длительность — по заголовку файла, без скачивания."""
    try:
        out = subprocess.run(
            # БЕЗ `-user_agent` ОТВЕТ ПУСТОЙ (проверено 26.10): cdn отдаёт файл
            # только «браузеру», и ffprobe молча возвращает ничего — а это
            # читается как «видео битое». Нужны ОБА заголовка.
            ["ffprobe", "-v", "error", "-user_agent", UA,
             "-headers", "Referer: %s\r\n" % referer,
             "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", url],
            capture_output=True, text=True, timeout=90).stdout
        d = json.loads(out or "{}")
        st = (d.get("streams") or [{}])[0]
        return (st.get("width"), st.get("height"),
                round(float(d.get("format", {}).get("duration") or 0), 1))
    except Exception:
        return (None, None, None)


def post(url):
    m = re.search(r"t\.me/(?:s/)?([A-Za-z0-9_]+)/(\d+)", url)
    if not m:
        return {"url": url, "error": "не похоже на ссылку поста"}
    chan, mid = m.group(1), m.group(2)
    page = _get("https://t.me/s/%s/%s" % (chan, mid))
    blk = _block(page, chan, mid)
    if not blk:
        return {"url": url, "error": "пост не найден на странице канала"}

    res = {"url": url, "channel": chan, "id": mid, "photos": [], "videos": [],
           "notes": []}

    # фото: только носители кадра, аватарка канала отсекается классом
    for mm in re.finditer(r'class="[^"]*(photo_wrap|video_thumb)[^"]*"[^>]*'
                          r"background-image:url\('([^']+)'\)", blk):
        res["photos"].append(mm.group(2))
        # ПОСТЕР ВИДЕО — ТОЖЕ ГОТОВЫЙ КАДР (27.10, улов `usuario-31` на
        # `OstashkoNews/227315` и `227359`). Когда телеграм не публикует само
        # видео, его превью всё равно остаётся в разметке — и это кадр
        # СПИКЕРА со стороны источника, без клейма агрегатора. Раньше он молча
        # лежал в `photos` вперемешку с обычными фото, и вкладка должна была
        # сама догадаться, что непубликуемое видео всё-таки дало кадр. Теперь
        # постеры собраны отдельно и инструмент говорит об этом вслух.
        if mm.group(1) == "video_thumb":
            res.setdefault("video_posters", []).append(mm.group(2))

    # видео: настоящий файл лежит в src плеера
    for mm in re.finditer(r'<video[^>]+src="([^"]+)"', blk):
        res["videos"].append(mm.group(1).replace("&amp;", "&"))

    # ПРИЗНАК ВИДЕО — ТОЛЬКО ПЛЕЕР ИЛИ ДЛИТЕЛЬНОСТЬ, НЕ СЛОВО `not_supported`
    # (баг пойман в бою через час после выпуска инструмента, улов `usuario-d9`
    # на `ZeRada1/32772` и `nabludatels/67220`): это слово стоит в разметке
    # телеграма ВСЕГДА, в том числе на постах вообще без видео. Инструмент
    # честно печатал «видео есть, файла нет», вкладка верила и шла искать
    # несуществующий файл — та самая тихая поломка, против которой он писался.
    dur = re.search(r'message_video_duration[^>]*>([\d:]+)<', blk)
    has_player = ("tgme_widget_message_video_player" in blk
                  or "message_video_thumb" in blk)
    if not res["videos"] and (has_player or dur):
        res["notes"].append(
            "видео в посте ЕСТЬ (%s), а файла нет: телеграм не публикует "
            "крупное видео в веб-превью. Круги на ?embed=1 не тратить."
            % (dur.group(1) if dur else "длительность не указана"))
        if res.get("video_posters"):
            # ПОСТЕР ПРОМЕРЯЕМ, А НЕ ОБЕЩАЕМ (27.10, улов `usuario-31` на
            # `OstashkoNews`: постеры пришли 320x180, то есть ниже порога
            # фетчера 500x320 — он их просто отклонит, и три сцены пришлось
            # возвращать в поиск). Утром того же дня инструмент советовал их
            # как «готовый кадр» вслепую — вот и получилось обещание, которое
            # фетч не выполняет. Теперь вердикт считается по размеру.
            for u in res["video_posters"]:
                w, h, _d = _probe(u, "https://t.me/%s/%s" % (chan, mid))
                if not w:
                    res["notes"].append("постер видео есть, промерить не удалось — "
                                        "смотри размер сам, порог фетчера 500x320")
                elif w < 500 or h < 320:
                    res["notes"].append(
                        "постер видео %sx%s — МАЛ, фетчер отклонит (порог 500x320). "
                        "Сцену отдавай в поиск, кадра тут нет" % (w, h))
                elif w < 1600:
                    res["notes"].append(
                        "постер видео %sx%s — пройдёт фетч, но это ниже порога "
                        "качества кадра 1600 px: годен ВО ВСПЛЫВАШКУ, не на "
                        "полный кадр" % (w, h))
                else:
                    res["notes"].append(
                        "постер видео %sx%s — годен как кадр: это снимок спикера "
                        "от самого источника, без клейма агрегатора. Ставь "
                        "`direct_url`; видео-лидом он НЕ считается." % (w, h))

    for v in res["videos"]:
        w, h, d = _probe(v, "https://t.me/%s/%s" % (chan, mid))
        if not w:
            res["notes"].append("видео есть, промерить не удалось — качай и смотри ffprobe сам")
            continue
        if w >= 1280:
            verdict = "годно БАЗОЙ"
        elif w == h:
            verdict = ("КВАДРАТ — в 16:9 это апскейл, берём ВСТАВКОЙ, "
                       "а не фоном на всю сцену")
        else:
            verdict = "НИЖЕ 720p — годно только во всплывашку"
        res["notes"].append("видео %sx%s, %s с — %s" % (w, h, d, verdict))
    return res


def main():
    args = sys.argv[1:]
    out = ""
    if args and args[0] == "--json":
        out, args = args[1], args[2:]
    if not args:
        sys.exit(__doc__)
    all_res = [post(u) for u in args]
    for r in all_res:
        print("— %s" % r["url"])
        if r.get("error"):
            print("   ОШИБКА: %s" % r["error"]); continue
        for p in r["photos"]:
            print("   фото : %s" % p)
        for v in r["videos"]:
            print("   видео: %s" % (v[:60] + "…(%d знаков, полный адрес в --json)" % len(v)
                                    if len(v) > 60 else v))
        for n in r["notes"]:
            print("   %s" % n)
        if not (r["photos"] or r["videos"] or r["notes"]):
            print("   вложений нет")
    if out:
        json.dump(all_res, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\nадреса записаны целиком: %s" % out)
        print("в scenes.json ставить source=direct_url и адрес ОТТУДА, не из печати")


if __name__ == "__main__":
    main()
