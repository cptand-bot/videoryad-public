# -*- coding: utf-8 -*-
"""ПРОВЕРКА КЛЮЧЕЙ СТОКОВ — ПЕРВЫМ ДЕЛОМ, ДО ПОИСКА КАДРОВ.

Повод (11.11.2026): ключ Pexels оказался отозван, Openverse лежал, и вместо
того чтобы сразу сказать ему «дай новый ключ», вкладка час искала по
Викискладу. Теперь так: одна команда в начале ролика — и сразу видно, чем
можно работать, а чего просить.

    python3 kluchi.py [папка проекта]

Ключи живут в <папка проекта>/.env:
    PEXELS_API_KEY=...      pexels.com/api — фото и видео, лучшее качество
    PIXABAY_API_KEY=...     pixabay.com/api/docs — фото и видео, щедрый лимит

ЧТО ЗНАЧАТ ОТВЕТЫ:
  Pexels 403    — ключ отозван или аккаунт закрыт. Сам не починится, просить новый.
  Pixabay 403   — ЧАЩЕ ВСЕГО НЕ КЛЮЧ: Pixabay отбивает запросы без браузерного
                  User-Agent. Проверять только с заголовком (этот скрипт так и делает).
  Openverse 504 — у них лежит шлюз, бывает надолго; ждать бесполезно.
  Commons       — без ключа, но по быту даёт мимо (замер 11.11: годных ~40%),
                  годится для истории, портретов, гравюр, карт.
"""
import json, os, sys, urllib.request, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    " (KHTML, like Gecko) Chrome/125.0 Safari/537.36"}


OBSHIY = os.path.expanduser("~/.claude/skills/news-video/kluchi.env")


def _chitat(p):
    if not os.path.exists(p):
        return {}
    return dict(l.strip().split("=", 1) for l in open(p, encoding="utf-8")
                if "=" in l and not l.strip().startswith("#"))


def _env(d):
    """Ключ берётся из проекта, а если там пусто — из общего kluchi.env."""
    e = _chitat(OBSHIY)
    e.update({k: v for k, v in _chitat(os.path.join(d, ".env")).items() if v.strip()})
    return e


def _zapros(u, hdr=None, t=20):
    h = dict(UA)
    h.update(hdr or {})
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=t))


def pexels(key):
    if not key:
        return "нет ключа", "взять на pexels.com/api, минута"
    try:
        d = _zapros("https://api.pexels.com/videos/search?query=winter&per_page=1",
                    {"Authorization": key})
        return "ЖИВОЙ", "видео: %s" % d.get("total_results")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return "МЁРТВ (403)", "ключ отозван — просить новый на pexels.com/api"
        return "ошибка %s" % e.code, ""
    except Exception as e:
        return "ошибка", repr(e)[:60]


def pixabay(key):
    if not key:
        return "нет ключа", "взять на pixabay.com/api/docs, минута"
    u = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": key, "q": "winter", "per_page": 3})
    try:
        d = _zapros(u)
        return "ЖИВОЙ", "видео: %s" % d.get("totalHits")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return "403", "проверь User-Agent — без него Pixabay отбивает ЛЮБОЙ ключ"
        return "ошибка %s" % e.code, ""
    except Exception as e:
        return "ошибка", repr(e)[:60]


def openverse():
    try:
        d = _zapros("https://api.openverse.org/v1/images/?q=winter&page_size=1"
                    "&license_type=commercial")
        return "ЖИВОЙ", "фото: %s" % d.get("result_count")
    except Exception as e:
        return "лежит", repr(e)[:50]


def commons():
    try:
        d = _zapros("https://commons.wikimedia.org/w/api.php?action=query&format=json"
                    "&generator=categorymembers&gcmtitle=Category:Winter&gcmtype=file"
                    "&gcmlimit=3&prop=imageinfo&iiprop=url|size")
        n = len(((d.get("query") or {}).get("pages") or {}))
        return "ЖИВОЙ", "по категориям отдаёт %d" % n
    except Exception as e:
        return "лежит", repr(e)[:50]


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    e = _env(d)
    print("ключи из", os.path.join(d, ".env"))
    rows = [("Pexels  (фото+видео)", *pexels(e.get("PEXELS_API_KEY", "").strip())),
            ("Pixabay (фото+видео)", *pixabay(e.get("PIXABAY_API_KEY", "").strip())),
            ("Openverse (без ключа)", *openverse()),
            ("Commons   (без ключа)", *commons())]
    for nm, st, kom in rows:
        print("  %-22s %-14s %s" % (nm, st, kom))
    zhivyh = [r for r in rows if r[1] == "ЖИВОЙ" and "без ключа" not in r[0]]
    print()
    if zhivyh:
        print("СТОК ЕСТЬ: %s — можно искать видео." % ", ".join(r[0].split()[0] for r in zhivyh))
    else:
        print("СТОКА НЕТ. НЕ НАЧИНАТЬ ПОИСК ПО ВИКИСКЛАДУ — сначала СРАЗУ попросить ключ:")
        print("   pexels.com/api  или  pixabay.com/api/docs — минута, и работает видео.")
        sys.exit(2)
