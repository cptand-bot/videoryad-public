#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""РЕЕСТР ЗАНЯТЫХ ТЕМ — ЧТОБЫ ДВЕ ВКЛАДКИ НЕ ВЕЛИ ОДНУ ТЕМУ.

    python3 zanyato.py --vzyat  --iz-puti "<папка темы на D:>" [--rabota досье]
    python3 zanyato.py --vzyat  --kanal ПЛАНЕТА --tema "3-Украина Поражение ЗАПАД"
                                [--den 10-11] [--kto имя] [--proekt путь] [--force]
    python3 zanyato.py --sdat   --iz-puti "<папка темы>" [--rabota видеоряд]
    python3 zanyato.py --spisok [--vse]

ПОВОД, дважды за 09.11:
  1) вложения досье ОДНОЙ темы параллельно разобрали ДВЕ вкладки — два
     осмотра субагентом, две скачки, результат сошёлся кадр в кадр; адреса
     вложений телеграма живут около часа, и второй заход мог прийти в пустоту;
  2) тему «3-Украина Поражение ЗАПАД» на ПЛАНЕТЕ вели одновременно вкладка и
     агент координатора — лишний заход раскадровки к внешнему агенту и лишняя
     ревизия медиатеки.
Оба раза виноват не исполнитель, а ОТСУТСТВИЕ ОТМЕТКИ «тема взята».

ЧТО ТАКОЕ ОДНА ЕДИНИЦА РАБОТЫ: канал + тема + день + вид работы. Один и тот
же текст на ДВУХ каналах — это КЛОН, он разрешён нарочно (правило 08.11), и
реестр ему не мешает: канал входит в ключ. А вот один канал + одна тема +
один вид работы у ДВУХ исполнителей — то самое столкновение.

ВИДЫ РАБОТЫ: `видеоряд` (по умолчанию), `досье`, `статья`, `упаковка`.
Разные виды по одной теме не конфликтуют: статью и видеоряд нарочно ведут
параллельно (правило «не ждать никого», 08.11).

ДЕЙСТВИЯ:
  --vzyat   отметиться. Тема уже у ДРУГОГО в работе → ОТКАЗ, код 2, строка
            «тему уже ведёт X с ЧЧ:ММ, проект такой-то». Своя же отметка
            повторно — не отказ. Сданное не мешает: берётся заново молча,
            с упоминанием, кто сдавал.
  --sdat    пометить сданным — занятость снимается, следующий `--vzyat`
            проходит.
  --spisok  что занято сейчас, с возрастом записей. Запись старше 12 часов в
            состоянии «в работе» показывается как «возможно брошено», но
            АВТОМАТИЧЕСКИ НЕ СНИМАЕТСЯ: снять её может только человек или
            осознанный `--force`.

ИМЯ ИСПОЛНИТЕЛЯ: переменная среды `VIDEORYAD_WHO`; её нет — имя папки проекта
плюс pid, чтобы отметка была хоть какая-то и столкновение всё равно было
видно.

НАДЁЖНОСТЬ: запись под замком (`flock` на соседнем `.lock`) и атомарная
(`os.replace`) — писать будут параллельно из нескольких процессов. Реестр
недоступен (нет прав, битый json) → ПРЕДУПРЕЖДЕНИЕ и работа продолжается:
эта отметка не должна становиться новой причиной простоя.
"""
import argparse
import json
import os
import re
import sys
import time

# ГДЕ ЛЕЖИТ РЕЕСТР. Рядом с `base/tg_claims.json` — там же, где остальные
# журналы сборщика, которые пишут все вкладки сразу. Каталог скилла один на
# машину, значит файл видят ВСЕ вкладки и все субагенты, а `flock` на нём
# работает честно (на `/mnt/d` через drvfs блокировки ненадёжны — именно
# поэтому реестр НЕ на D:, хотя копия георадара лежит там).
REESTR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "base", "zanyato.json"))
ZAMOK = REESTR + ".lock"

def _drugoy_reestr(path):
    """Подменить файл реестра — ТОЛЬКО для проверок инструмента.

    Нарочно сделано ключом `--reestr`, а не переменной среды: переменная
    тихо развела бы вкладки по разным реестрам, и столкновение, от которого
    всё это заведено, стало бы невидимым.
    """
    global REESTR, ZAMOK
    REESTR = os.path.abspath(path)
    ZAMOK = REESTR + ".lock"


RABOTY = ("видеоряд", "досье", "статья", "упаковка")
# Старше этого — «возможно брошено». Сутки сборщика короче, 12 часов хватает:
# ролик живёт 35-60 минут, смена — полдня.
BROSHENO_CHASOV = 12

KANALY = ("5 МИНУТ", "ПЛАНЕТА", "ОЛЬКА", "ДИПЛОМАТИЯ СИЛЫ",
          "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО", "ПЕРЕВОД С ДИПЛОМАТИЧЕСКОГО ЯЗЫКА",
          "МАТРИЦА ВЛАСТИ")


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip().upper()


def kluch(kanal, tema, den, rabota):
    """Одна единица работы: канал + тема + день + вид работы."""
    return "%s | %s | %s | %s" % (_norm(kanal), _norm(tema),
                                  _norm(den), _norm(rabota or "видеоряд"))


def iz_puti(path):
    """Канал, тему и день достаём ИЗ ПУТИ к папке темы.

    Канал берётся из пути и только из пути — он главнее георадара и главнее
    того, что написано в листе `Productions` (живой случай 28.10).
    Путь вида `.../НОВОСТИ/<КАНАЛ>/НОЯБРЬ/10-11/3-Украина Поражение ЗАПАД`:
    тема — последний каталог, день — предыдущий, если он похож на `ДД-ММ`.
    """
    p = os.path.abspath(str(path or "")).replace("\\", "/").rstrip("/")
    parts = [x for x in p.split("/") if x]
    kanal = ""
    for i, x in enumerate(parts):
        if _norm(x) in [_norm(k) for k in KANALY]:
            kanal = _norm(x)
            break
    tema, den = "", ""
    if parts:
        tema = parts[-1]
        # сама папка темы могла быть папкой проекта — тогда дня перед ней нет
        if len(parts) > 1 and re.fullmatch(r"\d{1,2}[-_.]\d{1,2}", parts[-2]):
            den = parts[-2].replace("_", "-").replace(".", "-")
        if re.fullmatch(r"\d{1,2}[-_.]\d{1,2}", tema):
            # дали путь до дня, без темы
            den, tema = tema.replace("_", "-").replace(".", "-"), ""
    return kanal, tema, den


def kto_ya(proekt=""):
    """Имя исполнителя: переменная среды, иначе папка проекта + pid."""
    who = (os.environ.get("VIDEORYAD_WHO") or "").strip()
    if who:
        return who
    baza = os.path.basename(os.path.abspath(proekt or os.getcwd()))
    return "%s/pid%d" % (baza, os.getpid())


class _Zamok(object):
    """flock на соседнем файле. Не вышло — работаем без замка, но говорим."""

    def __init__(self):
        self.f = None

    def __enter__(self):
        try:
            os.makedirs(os.path.dirname(REESTR), exist_ok=True)
            import fcntl
            self.f = open(ZAMOK, "a+")
            fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        except Exception as e:  # прав нет, нет fcntl, нет каталога
            print("  (реестр: замок не взят — %s; пишу без него)" % e,
                  file=sys.stderr)
            self.f = None
        return self

    def __exit__(self, *a):
        if self.f is not None:
            try:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.f.close()
            except Exception:
                pass
        return False


def load():
    """Читает реестр. Нет файла или битый json → пустой реестр и предупреждение.

    ОТКАЗ ЧИТАТЬ НЕ ДОЛЖЕН ЛОМАТЬ РАБОТУ: `take_folder.py` — боевая дверь,
    её зовут все вкладки первым шагом.
    """
    try:
        with open(REESTR, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("записи"), dict):
            return d, ""
        if isinstance(d, dict) and not d:
            return {"версия": 1, "записи": {}}, ""
        return ({"версия": 1, "записи": {}},
                "реестр %s не того вида — начинаю с пустого" % REESTR)
    except FileNotFoundError:
        return {"версия": 1, "записи": {}}, ""
    except (OSError, ValueError) as e:
        return {"версия": 1, "записи": {}}, "реестр не прочитан (%s)" % e


def save(d):
    """Атомарно: пишем рядом и `os.replace`. Не вышло — предупреждение."""
    try:
        os.makedirs(os.path.dirname(REESTR), exist_ok=True)
        t = REESTR + ".tmp%d" % os.getpid()
        with open(t, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(t, REESTR)
        return ""
    except OSError as e:
        return "реестр не записан (%s)" % e


def _vozrast(zap):
    try:
        return max(0.0, (time.time() - float(zap.get("ts") or 0)) / 3600.0)
    except (TypeError, ValueError):
        return 0.0


def _vozrast_slovami(h):
    if h < 1:
        return "%d мин" % int(h * 60)
    return "%.1f ч" % h


def kto_vel(kanal, tema, den, rabota, kto_isklyuchit=""):
    """Кто ведёт (или вёл) эту работу по этой теме. Для мягких предупреждений.

    Возвращает запись или None. Исключает своего исполнителя: предупреждать
    саму себя незачем.
    """
    d, _ = load()
    z = (d.get("записи") or {}).get(kluch(kanal, tema, den, rabota))
    if not z:
        return None
    if kto_isklyuchit and z.get("кто") == kto_isklyuchit:
        return None
    return z


def otmetitsya(kanal, tema, den, kto="", rabota="видеоряд", proekt="",
               force=False):
    """Отметиться на работу. Возвращает (можно_ли, строки_для_печати).

    Отказ ТОЛЬКО когда та же работа по той же теме у ДРУГОГО исполнителя в
    состоянии «в работе». Сданное не мешает. Своя отметка повторно — не отказ.
    """
    rabota = (rabota or "видеоряд").strip()
    kto = kto or kto_ya(proekt)
    k = kluch(kanal, tema, den, rabota)
    out = []
    with _Zamok():
        d, warn = load()
        if warn:
            out.append("!! " + warn)
        zap = (d.get("записи") or {}).get(k)
        if zap and zap.get("состояние") == "в работе" and zap.get("кто") != kto:
            h = _vozrast(zap)
            out.append("!! ТЕМУ УЖЕ ВЕДЁТ %s с %s (%s назад), работа «%s», "
                       "проект %s" % (zap.get("кто"), zap.get("время"),
                                      _vozrast_slovami(h), rabota,
                                      zap.get("проект") or "не назван"))
            if h >= BROSHENO_CHASOV:
                out.append("   запись старше %d ч — ВОЗМОЖНО БРОШЕНА; сама "
                           "она не снимается." % BROSHENO_CHASOV)
            if not force:
                out.append("   Если ты осознанно продолжаешь чужую работу — "
                           "повтори с --force. Иначе возьми другую тему и "
                           "скажи координатору о столкновении.")
                return False, out
            out.append("   --force: перенимаю работу у %s." % zap.get("кто"))
        if zap and zap.get("состояние") == "сдано":
            out.append("по этой теме работу «%s» уже сдавал %s (%s) — беру "
                       "заново." % (rabota, zap.get("кто"),
                                    zap.get("сдано") or zap.get("время")))
        if zap and zap.get("кто") == kto and zap.get("состояние") == "в работе":
            out.append("отметка уже твоя, с %s — ничего не меняю."
                       % zap.get("время"))
            return True, out
        novaya = {
            "канал": _norm(kanal) or "КАНАЛ НЕ УЗНАН",
            "тема": (tema or "").strip() or "ТЕМА НЕ УЗНАНА",
            "день": (den or "").strip(),
            "кто": kto,
            "работа": rabota,
            "время": time.strftime("%Y-%m-%d %H:%M"),
            "ts": int(time.time()),
            "состояние": "в работе",
            "проект": os.path.abspath(proekt) if proekt else os.getcwd(),
        }
        if zap:
            novaya["прежний"] = "%s (%s)" % (zap.get("кто"),
                                             zap.get("состояние"))
        d.setdefault("записи", {})[k] = novaya
        w = save(d)
        if w:
            out.append("!! " + w + " — отметка НЕ закреплена, скажи "
                       "координатору")
        else:
            out.append("тема отмечена за %s: %s | %s | %s | %s"
                       % (kto, novaya["канал"], novaya["тема"],
                          novaya["день"] or "день не указан", rabota))
    return True, out


def iz_proekta(proekt=""):
    """Канал, тему и день — по папке проекта: в ней лежит `.source_dir`.

    Папки проектов называются `5min-ritorika-0811`, имени канала в них нет
    (живой разбор 08.11). Зато `take_folder.py` первым шагом запоминает путь
    к его папке на D: — там и канал, и тема, и день.
    """
    p = os.path.abspath(proekt or os.getcwd())
    try:
        with open(os.path.join(p, ".source_dir"), encoding="utf-8") as f:
            src = f.read().strip()
        if src:
            return iz_puti(src)
    except OSError:
        pass
    return iz_puti(p)


def otmetitsya_myagko(kanal, tema, den, kto="", rabota="досье", proekt=""):
    """МЯГКАЯ отметка: занято другим — ПРЕДУПРЕДИТЬ, но не отказывать.

    Для `geo_links.py` и `tg_media.py`: разбор вложений второй вкладкой
    впустую — потеря времени, а не катастрофа, и останавливать за это разбор
    нельзя (адрес может быть нужен законно, второй серией той же темы).
    Зато сказать «это уже разобрано, вот где лежит» обязательно: адреса
    вложений телеграма живут около часа, и второй заход может прийти в
    пустоту, а результат всё равно сойдётся кадр в кадр (живой случай 09.11).

    Чужую отметку НЕ перебивает — она остаётся на первом разборщике.
    Возвращает (чужая_запись_или_None, строки_для_печати).
    """
    kto = kto or kto_ya(proekt)
    k = kluch(kanal, tema, den, rabota)
    out = []
    with _Zamok():
        d, warn = load()
        if warn:
            out.append("  (реестр: %s)" % warn)
        zap = (d.get("записи") or {}).get(k)
        if zap and zap.get("кто") != kto and zap.get("состояние") == "в работе":
            _pr = zap.get("проект") or ""
            out.append("!! ЭТУ РАБОТУ («%s») ПО ЭТОЙ ЖЕ ТЕМЕ УЖЕ ДЕЛАЛ %s в %s"
                       % (rabota, zap.get("кто"),
                          (zap.get("время") or "")[-5:] or "?"))
            if _pr:
                out.append("   его материал лежит в %s (и %s)"
                           % (_pr, os.path.join(_pr, "dossier")))
            out.append("   Второй раз адреса могут не открыться: ссылки на "
                       "вложения телеграма живут около часа, а результат "
                       "сойдётся кадр в кадр. Сначала посмотри его папку.")
            return zap, out
        if zap and zap.get("кто") == kto:
            return None, out
        novaya = {
            "канал": _norm(kanal) or "КАНАЛ НЕ УЗНАН",
            "тема": (tema or "").strip() or "ТЕМА НЕ УЗНАНА",
            "день": (den or "").strip(),
            "кто": kto,
            "работа": rabota,
            "время": time.strftime("%Y-%m-%d %H:%M"),
            "ts": int(time.time()),
            "состояние": "в работе",
            "проект": os.path.abspath(proekt) if proekt else os.getcwd(),
        }
        d.setdefault("записи", {})[k] = novaya
        save(d)
    return None, out


def sdat(kanal, tema, den, kto="", rabota="видеоряд", proekt=""):
    rabota = (rabota or "видеоряд").strip()
    kto = kto or kto_ya(proekt)
    k = kluch(kanal, tema, den, rabota)
    out = []
    with _Zamok():
        d, warn = load()
        if warn:
            out.append("!! " + warn)
        zap = (d.get("записи") or {}).get(k)
        if not zap:
            # сдать неотмеченное — нормальный случай (реестр заведён позже
            # темы): пишем сразу сданным, чтобы история не терялась
            zap = {"канал": _norm(kanal), "тема": (tema or "").strip(),
                   "день": (den or "").strip(), "кто": kto, "работа": rabota,
                   "время": time.strftime("%Y-%m-%d %H:%M"),
                   "проект": os.path.abspath(proekt) if proekt else os.getcwd()}
            out.append("отметки не было — пишу сразу сданной.")
        if zap.get("кто") != kto:
            out.append("отметку ставил %s, сдаю от имени %s."
                       % (zap.get("кто"), kto))
        zap["состояние"] = "сдано"
        zap["сдано"] = time.strftime("%Y-%m-%d %H:%M")
        zap["ts"] = int(time.time())
        if proekt:
            zap["проект"] = os.path.abspath(proekt)
        d.setdefault("записи", {})[k] = zap
        w = save(d)
        if w:
            out.append("!! " + w)
        else:
            out.append("сдано: %s | %s | %s | %s"
                       % (zap.get("канал"), zap.get("тема"),
                          zap.get("день") or "день не указан", rabota))
    return True, out


def spisok(vse=False):
    d, warn = load()
    out = []
    if warn:
        out.append("!! " + warn)
    zz = sorted((d.get("записи") or {}).values(),
                key=lambda z: (z.get("канал") or "", z.get("день") or "",
                               z.get("тема") or "", z.get("работа") or ""))
    v_rabote = [z for z in zz if z.get("состояние") == "в работе"]
    sdano = [z for z in zz if z.get("состояние") != "в работе"]
    out.append("РЕЕСТР: %s" % REESTR)
    out.append("в работе: %d, сдано: %d" % (len(v_rabote), len(sdano)))
    if v_rabote:
        out.append("")
        out.append("В РАБОТЕ (трогать нельзя):")
        for z in v_rabote:
            h = _vozrast(z)
            metka = "  возможно брошено" if h >= BROSHENO_CHASOV else ""
            out.append("  %-16s %-34s %-6s %-9s %s (%s)%s"
                       % (z.get("канал"), (z.get("тема") or "")[:34],
                          z.get("день") or "—", z.get("работа"),
                          z.get("кто"), _vozrast_slovami(h), metka))
            out.append("        %s" % (z.get("проект") or ""))
    if sdano and (vse or len(sdano) <= 40):
        out.append("")
        out.append("СДАНО (тему можно брать снова):")
        for z in sdano:
            out.append("  %-16s %-34s %-6s %-9s %s, сдано %s"
                       % (z.get("канал"), (z.get("тема") or "")[:34],
                          z.get("день") or "—", z.get("работа"),
                          z.get("кто"), z.get("сдано") or "?"))
    elif sdano:
        out.append("")
        out.append("сданных записей %d — показать целиком: --spisok --vse"
                   % len(sdano))
    return out


def main():
    ap = argparse.ArgumentParser(add_help=True,
                                 description="реестр занятых тем")
    ap.add_argument("--vzyat", action="store_true")
    ap.add_argument("--sdat", action="store_true")
    ap.add_argument("--spisok", action="store_true")
    ap.add_argument("--vse", action="store_true",
                    help="--spisok: показать и сданные целиком")
    ap.add_argument("--iz-puti", dest="iz_puti", default="",
                    help="папка темы на D: — канал, тема и день из пути")
    ap.add_argument("--iz-proekta", dest="iz_proekta", default="",
                    help="папка ПРОЕКТА — канал, тема и день из её "
                         "`.source_dir` (так зовёт ship.sh: пути к его папке "
                         "он не знает, а метка в проекте есть)")
    ap.add_argument("--kanal", default="")
    ap.add_argument("--tema", default="")
    ap.add_argument("--den", default="")
    ap.add_argument("--kto", default="")
    ap.add_argument("--rabota", default="видеоряд",
                    help="видеоряд | досье | статья | упаковка")
    ap.add_argument("--proekt", default="")
    ap.add_argument("--force", action="store_true",
                    help="--vzyat: осознанно перенять чужую работу")
    ap.add_argument("--reestr", default="",
                    help="другой файл реестра (только для проверок)")
    a = ap.parse_args()
    if a.reestr:
        _drugoy_reestr(a.reestr)

    if a.spisok or not (a.vzyat or a.sdat):
        for ln in spisok(a.vse):
            print(ln)
        return 0

    kanal, tema, den = a.kanal, a.tema, a.den
    if a.iz_proekta:
        k3, t3, d3 = iz_proekta(a.iz_proekta)
        kanal = kanal or k3
        tema = tema or t3
        den = den or d3
        if not a.proekt:
            a.proekt = a.iz_proekta
    if a.iz_puti:
        k2, t2, d2 = iz_puti(a.iz_puti)
        kanal = kanal or k2
        tema = tema or t2
        den = den or d2
    if not tema:
        print("не названа тема: дай --tema или --iz-puti <папка темы>",
              file=sys.stderr)
        return 2
    if not kanal:
        print("!! КАНАЛ ИЗ ПУТИ НЕ УЗНАН — ставь --kanal, иначе реестр не "
              "разведёт клоны по каналам", file=sys.stderr)
    if _norm(a.rabota) not in [_norm(x) for x in RABOTY]:
        print("  (вид работы «%s» не из списка %s — пишу как есть)"
              % (a.rabota, ", ".join(RABOTY)))

    if a.sdat:
        ok, out = sdat(kanal, tema, den, a.kto, a.rabota, a.proekt)
        for ln in out:
            print(ln)
        return 0

    ok, out = otmetitsya(kanal, tema, den, a.kto, a.rabota, a.proekt, a.force)
    for ln in out:
        print(ln, file=(sys.stdout if ok else sys.stderr))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
