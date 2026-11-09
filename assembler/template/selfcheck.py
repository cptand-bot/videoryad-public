#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Полная самопроверка сборки по SKILL.md ПЕРЕД тем как:
  - отдавать дашборд пользователю,
  - говорить «готово к собирай»,
  - запускать build_clips / assemble_final.

Обязательное правило (user, 2026-09-06, после 07.09-2: «делай самопроверку
каждого своего шага на полный цикл. Не делать ни одного действия лишнего
без самопроверки»). Косяк из задачи в задачу всплывает потому, что шаги
скилла пропускаются молча — этот скрипт их ловит.

Запуск:  python3 selfcheck.py <scenes.json> [images_dir]
Код возврата 0 = всё чисто. !=0 = есть НАРУШЕНИЯ, чинить до отдачи дашборда.
"""
import glob, hashlib, io, json, os, subprocess, sys

# ГОЛЫЙ ВЫЗОВ БРАЛ ФАЙЛ ВСПЛЫВАШЕК И СРАВНИВАЛ ЕГО САМ С СОБОЙ (2026-10-20,
# улов `usuario-40`). В папке ролика лежат ДВА `*.scenes.json`, и `sorted()`
# ставит `overlays_fetch.scenes.json` первым по алфавиту почти всегда. Итог:
# на все 24 всплывашки разом печаталось «запрос ТОТ ЖЕ, что у базового кадра»
# — выглядит как настоящая находка, сигнала ноль, и вкладка чуть не переписала
# весь слой всплывашек. Теперь файл всплывашек из автовыбора исключён (как это
# давно делает облачный `setup`), а если после отбора кандидатов не осталось —
# скрипт честно просит имя файла, а не берёт что попало.
def _pick_scenes():
    cands = [p for p in sorted(glob.glob("*.scenes.json"))
             if "overlays_fetch" not in os.path.basename(p)
             and "overlay" not in os.path.basename(p).split(".")[0]]
    if not cands:
        print("selfcheck: в папке нет основного *.scenes.json (только файл "
              "всплывашек?) — передай имя файла первым аргументом")
        sys.exit(2)
    if len(cands) > 1:
        print(f"selfcheck: основных файлов сцен несколько {cands} — беру "
              f"{cands[0]}; если нужен другой, передай его первым аргументом")
    return cands[0]


scenes_path = sys.argv[1] if len(sys.argv) > 1 else _pick_scenes()
images = sys.argv[2] if len(sys.argv) > 2 else "images"
proj = os.path.dirname(os.path.abspath(scenes_path)) or "."
os.chdir(proj)

FAIL, WARN = [], []
d = json.load(open(scenes_path, encoding="utf-8"))
scenes = d["scenes"] if isinstance(d, dict) else d
# Канал в шапке `<niche>.scenes.json` лежит ВЕРХНИМ УРОВНЕМ (`channel`), а не
# в блоке `meta` — проверено на всех живых проектах 2026-10-16. Раньше читался
# только `meta`, которого там нет ни у кого: печаталось «канал ?», и проверка
# `anchor` по каналу МОЛЧА не выполнялась ни разу за всё время. Читаем оба
# места, чтобы работало и со старыми файлами, где `meta` всё-таки есть.
meta = {} if not isinstance(d, dict) else {**d, **(d.get("meta") or {})}
ids = [s["id"] for s in scenes]
total = sum(s["duration_sec"] for s in scenes)

def asset(i):
    """Файлы кадра сцены. `.ready` — МЕТКА подготовленного вложения (06.11),
    а не кадр: вкладка кладёт её рядом по нашей же инструкции, и без этого
    исключения каждая такая сцена давала ложное «в images/ ДВА файла».
    Нулевой файл тоже не кадр."""
    out = []
    for f in glob.glob(f"{images}/scene_{i:03d}.*"):
        if f.endswith((".json", ".ready", ".lock")):
            continue
        try:
            if os.path.getsize(f) == 0:
                continue
        except OSError:
            continue
        out.append(f)
    return out

needs = {}
if os.path.exists("needs_upload.json"):
    needs = json.load(open("needs_upload.json", encoding="utf-8"))

# 1. каждая сцена — либо файл, либо needs_upload
for i in ids:
    if not asset(i) and str(i) not in needs:
        FAIL.append(f"сцена {i}: нет ни картинки, ни записи в needs_upload.json")

# 1b. ДВА ФАЙЛА НА ОДНУ СЦЕНУ — СБОРЩИК ВОЗЬМЁТ НЕ ТОТ (2026-10-27, улов
# `usuario-31` на `planeta-ultimatum-2810`, одиннадцать пар). Облако кладёт
# тёмную заглушку `scene_NNN.jpg` на сцены источников, которых оно не
# обслуживает (карточки, медиатека), а потом поверх ложится настоящий
# `scene_NNN.mp4` из локального добора — и в папке остаются ОБА. Сцена при
# этом «с кадром», проверки молчат, а в сборку уезжает тот файл, который
# первым попал в glob: на одиннадцати сценах это была бы чёрная заглушка.
# Отличить можно только счётом файлов, поэтому проверка здесь.
_TMP_SUF = (".wmcrop.jpg", ".ocrcrop.jpg", ".text.jpg", ".ovthumb.jpg")
for i in ids:
    _fs = [f for f in asset(i) if not f.endswith(_TMP_SUF)]
    if len(_fs) > 1:
        _sizes = ", ".join("%s (%d КБ)" % (os.path.basename(f),
                                           os.path.getsize(f) // 1024)
                           for f in sorted(_fs))
        # ГОТОВАЯ КОМАНДА С `mkdir -p` (08.11, улов `usuario-cd`): папку
        # `.placeholders/` уносит чистка забора, и перенос дубля молча не
        # срабатывал — снаружи это выглядело как «17 нарушений на ровном
        # месте». Теперь каталог создаётся в той же строке, а сама папка
        # внесена в список переживающих `get.sh`.
        FAIL.append("сцена %s: в images/ ДВА файла — %s. Сборщик возьмёт "
                    "первый по алфавиту, а не нужный. Убрать лишний "
                    "(тёмные заглушки облака на 30-40 КБ):\n"
                    "      mkdir -p .placeholders && mv images/<лишний> "
                    ".placeholders/" % (i, _sizes))

# 1b-бис. ТЁМНАЯ ЗАГЛУШКА ОБЛАКА НА МЕСТЕ ЖИВОГО КАДРА (04.11, улов
# `usuario-75`: чёрный кадр на 1:52 в СДАННОМ ролике). Проверка 1b ловит
# заглушку только когда рядом лежит второй файл; здесь кадр был ОДИН —
# заглушка приехала с `get.sh` и затёрла пин медиатеки, а механизм rebuild
# её законсервировал («сцена не менялась»). Ловим по ЯРКОСТИ, а не по
# точному размеру: он гуляет 30-40 КБ.
_ph = []
for i in ids:
    for f in asset(i):
        if f.endswith(_TMP_SUF) or not f.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        try:
            if os.path.getsize(f) > 60000:
                continue
            from PIL import Image, ImageStat
            with Image.open(f) as _im:
                _b = ImageStat.Stat(_im.convert("L")).mean[0]
        except Exception:
            continue
        if _b < 45:
            _ph.append("сцена %s: %s — %d КБ, средняя яркость %.0f из 255"
                       % (i, os.path.basename(f), os.path.getsize(f) // 1024, _b))
# КАРТОЧКА БЕЗ КЛИПА — ЭТО НЕ «ЗАГЛУШКА», А НЕНАРИСОВАННЫЙ ЭЛЕМЕНТ (06.11,
# улов `usuario-a3`). Виды режима `cli` (`bars`, `slider`) рисуются ТОЛЬКО
# клипом, превью у них не бывает; если задание упало в облаке, в `images/`
# остаётся прежняя заглушка — и проверка кричала «тёмная заглушка», уводя
# вкладку искать кадр вместо того, чтобы перерисовать карточку.
_card_no_clip = []
for _s in scenes:
    if not str(_s.get("source", "")).startswith("card"):
        continue
    _i = int(_s.get("id", 0))
    if not glob.glob(f"{images}/scene_{_i:03d}.mp4"):
        _card_no_clip.append(_i)
if _card_no_clip:
    _nums = ", ".join(map(str, _card_no_clip))
    FAIL.append("КАРТОЧКА НЕ НАРИСОВАНА (сцены %s): источник `card:*`, а клипа "
                "в images/ нет. Это НЕ брак кадра — задание не отрисовалось "
                "или не разложено. Прогони `bash ~/.claude/skills/news-video/"
                "cloud/va.sh <цель> python3 ~/.claude/skills/"
                "news-video/fullcycle/cards_cloud.py <ролик>.scenes.json` — "
                "уже готовые карточки заново не рисуются." % _nums)
    _ph = [x for x in _ph
           if not any(("сцена %d:" % i) in x for i in _card_no_clip)]

if _ph:
    FAIL.append("ТЁМНАЯ ЗАГЛУШКА ВМЕСТО КАДРА (" + "; ".join(_ph) +
                "). Это заглушка облака, а не фотография: в готовом ролике "
                "будет ЧЁРНЫЙ кадр. Верни кадр локально и пересобери — "
                "rebuild сам её не переклеит, он считает сцену неизменной.")

# 1c. ИСТОЧНИК СЦЕНЫ И ФАЙЛ НА ДИСКЕ РАСХОДЯТСЯ (2026-10-27, улов `usuario-31`
# на `planeta-ultimatum-2810`, сцена 20). После кода 1 на фетче запрос был
# переписан в `press_photo`, а в `images/` остался ПРЕЖНИЙ стоковый `.mp4` —
# файл валидный, сцена «с кадром», и ни одна проверка этого не видела: сверить
# можно только источник против расширения. Для `local_library`, `direct_url` и
# карточек проверка не делается: там законны и фото, и видео.
_PHOTO_SRC = ("press_photo", "web_search", "wikimedia", "pexels_photo")
for s_ in scenes:
    i = s_["id"]
    src = str(s_.get("source", ""))
    fs = [f for f in asset(i) if not f.endswith(_TMP_SUF)]
    if len(fs) != 1:
        continue          # ноль и дубли уже разобраны выше
    ext = os.path.splitext(fs[0])[1].lower()
    is_vid = ext in (".mp4", ".mov", ".webm")
    if src.startswith("pexels_video") and not is_vid:
        FAIL.append("сцена %s: источник %s, а на диске КАРТИНКА %s — фетч не "
                    "заменил файл; сцена покажет не то, что в запросе"
                    % (i, src, os.path.basename(fs[0])))
    elif src in _PHOTO_SRC and is_vid:
        FAIL.append("сцена %s: источник %s, а на диске ВИДЕО %s — остался "
                    "прежний стоковый клип, запрос переписан впустую"
                    % (i, src, os.path.basename(fs[0])))

# 2. format sniff — не-JPEG под .jpg (SKILL.md 2d)
# ВРЕМЕННЫЕ КРОПЫ OCR — НЕ ФАЙЛЫ РОЛИКА (24.10, улов `usuario-68`).
# `has_heavy_text_overlay` создаёт и тут же удаляет `scene_NNN.jpg.wmcrop.jpg`
# на каждом кадре. Если selfcheck идёт одновременно с OCR, он ловит такой файл
# в glob, а к моменту чтения его уже нет — весь прогон падал
# `FileNotFoundError`, exit 1, и это выглядело как сломанная самопроверка на
# готовом ролике. Поэтому: имя пропускаем, а исчезнувший файл не роняет прогон.
TMP_SUFFIX = (".wmcrop.jpg", ".ocrcrop.jpg")

# OCR МОГ НЕ РАБОТАТЬ ВО ВРЕМЯ ФЕТЧА (24.10). Метку кладёт fetch_assets_news,
# когда tesseract не запускается: тогда «клейм не найдено» ничего не значит.
if os.path.exists(os.path.join(images, ".ocr_dead")):
    FAIL.append("OCR НЕ РАБОТАЛ во время фетча (метка images/.ocr_dead) — "
                "проверка на клейма и текст в кадре НЕ ДЕЛАЛАСЬ. Почини "
                "tesseract и прогони заново либо отдай кадры на просмотр")

for f in glob.glob(f"{images}/scene_*.jpg"):
    if f.endswith(TMP_SUFFIX):
        continue
    if not os.path.exists(f):
        continue
    kind = subprocess.run(["file", "-b", f], capture_output=True, text=True).stdout
    if "JPEG" not in kind and "JFIF" not in kind:
        FAIL.append(f"{f}: не JPEG ({kind.strip()[:30]}) — build_clips подавится")

# 2b. oversized video source (user, 2026-09-16, furious — a whole 359s
# compilation reel got hand-pinned as a "single scene" clip and copied
# verbatim into images/, which build_clips_1080.py DOES trim correctly at
# build time (-t duration), but a source this large chokes/slows the live
# dashboard's thumbnail step and is a sign a long multi-shot compilation was
# used raw instead of being indexed (SKILL.md rule 3). Catch it before it
# ever reaches fetch/dashboard, not after.
for i, s in ((s["id"], s) for s in scenes):
    if s.get("source") != "local_library":
        continue  # pexels_video/press stock clips are legitimately longer than the cut; only a library exact-file pin risks being a whole compilation
    for f in asset(i):
        if not f.lower().endswith((".mp4", ".mov", ".webm")):
            continue
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", f], capture_output=True, text=True, timeout=10)
            src_dur = float(r.stdout.strip() or 0)
        except Exception:
            continue
        want = s["duration_sec"]
        if src_dur > max(30, want * 5):
            FAIL.append(f"{f}: источник {src_dur:.0f}с при нужных {want:.1f}с — похоже на "
                        f"целую нарезку/компиляцию, взятую как один клип (SKILL.md rule 3, "
                        f"index_library.py detect до использования, не голым файлом)")

# 3. дубли одного файла (no-repeat, SKILL.md rule 4/5)
h = {}
for f in glob.glob(f"{images}/scene_*.*") + glob.glob("overlays/scene_*.*"):
    # `.ready`/`.lock` — СЛУЖЕБНЫЕ МЕТКИ, А НЕ КАДРЫ (06.11): они пустые и,
    # естественно, совпадают по md5 между собой — проверка дублей кричала
    # «одинаковый файл» на метках, которые вкладка ставит по нашей же
    # инструкции. Нулевой файл в сравнение дублей не берём вообще.
    if f.endswith((".json", ".text.png", ".ready", ".lock") + TMP_SUFFIX):
        continue
    try:
        if os.path.getsize(f) == 0:
            continue
    except OSError:
        continue
    # ПУТЬ ЦЕЛИКОМ, А НЕ ОДНО ИМЯ (2026-10-20, улов `usuario-40`). Было
    # `os.path.basename(f)`, и дубль «images/scene_044.jpg + overlays/scene_073.jpg»
    # читался как «две базовые сцены» — вкладка искала совпадение не в том слое.
    # Имена файлов в `images/` и `overlays/` нумеруются независимо, так что без
    # каталога сообщение не просто неполное, а уводит в сторону.
    try:
        _d = open(f, "rb").read()
    except OSError:
        continue          # файл исчез между glob и чтением — временный кроп
    h.setdefault(hashlib.md5(_d).hexdigest(), []).append(f)
for k, v in h.items():
    if len(v) > 1:
        FAIL.append(f"одинаковый файл в: {sorted(v)}")

# 3-бис. ОДНА КАРТИНКА — ОДИН РАЗ НА ВЕСЬ ВИДЕОРЯД (08.11, его слово по
# ролику ПЛАНЕТА «Украина катастрофа»: «этот генератор, голубой, он гуляет…
# у нас же строгий запрет: одну картинку взяли — всё, забыли про неё»).
# Проверка выше ловит только ОДИНАКОВЫЙ ФАЙЛ по md5 и только в `images/` и
# `overlays/`. Мимо неё проходят три случая, все три были в том ролике:
# зеркальный и подрезанный дубль из клон-конвейера, фото рисованных карточек
# (`cards/photo/`) и материал досье — они лежат вне сравнения.
# Считает `povtor_kadrov.py` (похожесть по сетке с вырезами, см. его шапку).
# ДВЕ ДВЕРИ НАРУЖУ, ПОТОМУ ЧТО ГЕЙТ БЛОКИРУЮЩИЙ (правило «сначала
# разрешение, потом рассылка»): файл `.povtor_ok` в папке ролика — когда он
# САМ посмотрел и сказал «так и надо»; `VIDEORYAD_NO_DUP=1` — аварийный
# обход на уже идущей сборке, чтобы правка не отправила вкладку на лишний круг.
try:
    if os.path.exists(".povtor_ok") or os.environ.get("VIDEORYAD_NO_DUP") == "1":
        raise ImportError("повтор кадра не проверяем: стоит разрешение")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import povtor_kadrov as _pk
    _повторы = _pk.группы(_pk.собрать(".", с_клипами=False))
    for _гр in _повторы:
        _сц = sorted({_s for _, _, _s in _гр if _s is not None})
        FAIL.append(
            "ОДНА И ТА ЖЕ КАРТИНКА НА СЦЕНАХ %s — %s. Запрет повтора кадра "
            "внутри видеоряда (его слово 08.11). Зеркало и обрезка повтором "
            "быть не перестают. Лечение: оставить её в ОДНОЙ сцене, остальным "
            "дать новый кадр."
            % (", ".join(str(x) for x in _сц),
               ", ".join("%s %s" % (в, os.path.basename(f)) for f, в, _ in _гр)))
except ImportError as _e:
    WARN.append("повтор кадра НЕ проверен: %s" % _e)

# 3-ТЕР. КАРТОЧКА БЕЗ ЗАДАНИЯ НА ОТРИСОВКУ = ЧЁРНЫЙ КАДР (08.11, улов
# вкладки `usuario-47` на третьем клоне: четыре вида из восемнадцати).
# Внешний агент умеет поставить сцене `"source": "card:bubbles"` и на этом
# останавливается — доступа к WSL у него нет, задание `cards/queue/scene_NNN.json`
# создаёт только наш инструмент. Дальше всё выглядит здорово: приёмка такую
# сцену принимает, `query_lint` молчит (за `card:*` фетч не идёт по
# устройству), `obyazatelno` засчитывает вид как стоящий — а рисовать нечего,
# и в сборку сцена уходит БЕЗ КАДРА. Ровно тот класс, что «успех может значить
# ничего не сделано», поэтому здесь блокер.
_карточки = {}
for _sc in scenes:
    _src = str(_sc.get("source", ""))
    if _src.startswith("card:"):
        _карточки[str(_sc.get("id"))] = _src[5:]
if _карточки:
    _без = []
    for _sid, _вид in sorted(_карточки.items(), key=lambda x: int(x[0])):
        _задание = os.path.join("cards", "queue", "scene_%03d.json" % int(_sid))
        _готово = glob.glob(os.path.join("cards", "*", "scene_%03d.*" % int(_sid)))
        if not os.path.exists(_задание) and not _готово:
            _без.append("%s (%s)" % (_sid, _вид))
    if _без:
        FAIL.append(
            "КАРТОЧКА БЕЗ ЗАДАНИЯ НА ОТРИСОВКУ — сцены %s. Источник `card:*` "
            "стоит, а в `cards/queue/` пусто: рисовать нечего, фетч за такой "
            "сценой не идёт, в ролике будет чёрный кадр. Поставь карточку "
            "инструментом: `card_put.py <scenes.json> <сцена> <вид> …` или "
            "`element_put.py` — он сам положит задание в очередь."
            % ", ".join(_без))

# 3-КВАТЕР. КАРТОЧКА С ФОТО, А ФОТО В КАДРЕ НЕТ (09.11, улов вкладки
# `usuario-2c` на `planeta-ukraina-forma-1011`, сцены 70 и 100).
# Снимки лежали в `images/card070.jpg` и `images/card100.jpg`, чистка папки
# забора их снесла — и карточки отрисовались с ПУСТЫМ местом под фото: у
# сплита чёрная левая половина, у досье тёмный прямоугольник вместо снимка.
# Прогон отчитался успехом, эта проверка молчала (клип на месте, длительность
# сходится), лист перекрытий тоже (он показывает постер, а пустое поле на
# чёрной гамме ПЛАНЕТЫ читается как часть фона). Поймал пользователь глазами.
# Путь снимка чинится в `cards_queue.keep_photo`, но ТРЕТИЙ РУБЕЖ обязан быть
# независим от путей: смотрим сам КАДР. Если задание обещает фото, в рамке под
# фото не может быть ровного пятна.
#
# ЧИСЛО: среднеквадратичное отклонение яркости в рамке ниже 12 из 255.
# Замерено по 138 живым постерам карточек с фото (все ролики на диске):
# у 137 из них разброс 23,2…100,7 (минимум — размытый фон у «глубины
# резкости»); у 138-го, сцена 36 ролика `planeta-rasplata-0911-cloud`, ровно
# 0,0 — и это НАСТОЯЩИЙ брак того же класса, уехавший в сданный ролик. Голый
# фон канала в той же рамке даёт 1,1-2,2, бумага досье без снимка — 4,
# тёмная заглушка облака — 0-3. Порог 12 стоит посреди зазора.
_ФОТО_РАМКИ = {           # вид → рамки, где обязан лежать снимок (кадр 1920x1080)
    # сплит: половина кадра с лицом; сторона бывает и левой, и правой
    "split": [(40, 80, 560, 1000), (1360, 80, 1880, 1000)],
    "quote_variants.quote_split": [(40, 80, 560, 1000), (1360, 80, 1880, 1000)],
    # досье: окно снимка на бумаге, 330x230 от (750,470) на листе от (370,236)
    "dossier": [(1130, 716, 1442, 928)],
    "cinematic.dossier": [(1130, 716, 1442, 928)],
    # слабое фото в своём окне: окно 0,40 ширины от x=150
    "photo": [(170, 300, 898, 820)],
    "photo_card.photo_card": [(170, 300, 898, 820)],
    # кадр в рамке плёнки: 975x712 по центру, ниже на 74
    "film_frame": [(500, 286, 1420, 942)],
    "film.film_single": [(500, 286, 1420, 942)],
    # глубина резкости: снимок во весь кадр, края трогает подпись
    "dof": [(300, 180, 1620, 900)],
    "cinematic.depth_of_field": [(300, 180, 1620, 900)],
}
_ПОРОГ_ФОТО = 12.0
_пустые_карточки = []
for _sc in scenes:
    if not str(_sc.get("source", "")).startswith("card:"):
        continue
    _i = int(_sc.get("id", 0))
    _зад = os.path.join("cards", "queue", "scene_%03d.json" % _i)
    if not os.path.isfile(_зад):
        continue                      # «карточка без задания» ловится выше
    try:
        _j = json.load(open(_зад, encoding="utf-8"))
    except Exception:
        continue
    _рамки = _ФОТО_РАМКИ.get(str(_j.get("view", "")))
    # фото не обещано (цитата, тезисы, карта, диаграмма) либо вид с
    # неизвестной геометрией — такие не трогаем вовсе
    if not _рамки or not (_j.get("kwargs") or {}).get("photo"):
        continue
    _кадр = os.path.join("cards", "scene_%03d.jpg" % _i)
    _врем = None
    if not os.path.isfile(_кадр):
        _клип = os.path.join(images, "scene_%03d.mp4" % _i)
        if not os.path.isfile(_клип):
            continue                  # клипа нет — об этом кричит проверка выше
        _врем = os.path.join("cards", ".photo_check_%03d.jpg" % _i)
        try:
            _d = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration", "-of", "csv=p=0", _клип],
                                capture_output=True, text=True, timeout=20)
            _dur = float((_d.stdout or "").strip() or 0)
            _ss = "%.2f" % (max(0.5, _dur * 0.85) if _dur > 1.0 else 0.5)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", _ss, "-i", _клип,
                            "-frames:v", "1", _врем], capture_output=True, timeout=60)
        except Exception:
            pass
        if not os.path.isfile(_врем):
            continue
        _кадр = _врем
    try:
        import numpy as _np
        from PIL import Image as _Im
        with _Im.open(_кадр) as _im:
            _im = _im.convert("L")
            if _im.size != (1920, 1080):
                _im = _im.resize((1920, 1080), _Im.LANCZOS)
            _a = _np.asarray(_im, _np.float32)
        _раз = max(float(_a[y0:y1, x0:x1].std()) for (x0, y0, x1, y1) in _рамки)
    except Exception as _e:
        WARN.append("сцена %d: фото карточки не проверено (%s: %s)"
                    % (_i, type(_e).__name__, _e))
        _раз = None
    finally:
        if _врем and os.path.isfile(_врем):
            try:
                os.remove(_врем)
            except OSError:
                pass
    if _раз is not None and _раз < _ПОРОГ_ФОТО:
        _пустые_карточки.append("сцена %d (%s, фото %s): разброс %.1f при "
                                "пороге %.0f"
                                % (_i, _j.get("view"),
                                   os.path.basename((_j.get("kwargs") or {})["photo"]),
                                   _раз, _ПОРОГ_ФОТО))
if _пустые_карточки:
    FAIL.append(
        "У КАРТОЧКИ ОБЕЩАНО ФОТО, А МЕСТО ПОД НЕГО ПУСТОЕ — " +
        "; ".join(_пустые_карточки) +
        ". В рамке под снимком ровное пятно: у сплита это чёрная левая "
        "половина, у досье тёмный прямоугольник. Снимок потерялся между "
        "постановкой карточки и прогоном (чаще всего его снесла чистка папки "
        "забора из `images/`). Положи снимок в `cards/photo/`, переставь "
        "карточку тем же инструментом и перерисуй: "
        "`python3 ~/.claude/skills/news-video/fullcycle/cards_cloud.py "
        "<ролик>.scenes.json`.")

# 4. overlays.json — ОБЯЗАН быть до дашборда, ~3/мин, anchor по каналу (SKILL.md 3b)
if not os.path.exists("overlays.json"):
    FAIL.append("overlays.json НЕТ — всплывашки не расставлены (SKILL.md 3b, обязательно ДО дашборда)")
else:
    ov = json.load(open("overlays.json", encoding="utf-8"))
    n_ov = len([k for k in ov if k != "anchor"])
    # per_min считается ниже, по минутам БЕЗ рисованных кадров (09.11).
    # ПЕРВАЯ ВСПЛЫВАШКА — НЕ ПОЗЖЕ ЧЕТВЁРТОЙ СЦЕНЫ (слово пользователя 26.10:
    # «всплывашка должна появляться в первых 4 кадрах»). Он смотрит начало
    # ролика как зритель: пустой старт читается как «ничего не происходит»,
    # а зритель уходит именно там. Повод: два ролика подряд начинались с
    # 11-й сцены (`planeta-nato1997-2710` и `planeta-kiev-zima-2710`).
    # Лечится ОДНОЙ всплывашкой, а не перестановкой — поэтому блокер.
    # НАШ ЭЛЕМЕНТ ИДЁТ ЧИСТЫМ. Гейт переехал в раздел 6-бис ниже и стал
    # ОДНИМ на три места (09.11): здесь он работал только когда
    # `overlays.json` есть, а поле `fx` на рисованной сцене надо ловить
    # всегда. Правило, граница «наложение против содержания элемента» и текст
    # отказа — в `template/cards_queue.py`, функции `слои_на_карточках` и
    # `отказ_слои`; их же командой зовёт `cloud/ship.sh`.
    # ЗНАМЕНАТЕЛЬ ВСЕХ НОРМ НИЖЕ — ТОЛЬКО ОБЫЧНЫЕ СЦЕНЫ (09.11, его правило о
    # чистых элементах). На рисованный кадр слой запрещён, поэтому считать
    # карточки в норму надписей и всплывашек — значит требовать слой, который
    # гейт тут же забракует: вилка и лишний круг правок. У роликов 09-10.11
    # карточек 15-17 из 67-71 сцены, то есть ЧЕТВЕРТЬ.
    _card_ids = {int(sc["id"]) for sc in scenes
                 if str(sc.get("source", "")).startswith("card:")}
    _обычных = max(1, len(ids) - len(_card_ids))
    _обычных_сек = sum(sc["duration_sec"] for sc in scenes
                       if int(sc["id"]) not in _card_ids) or total
    per_min = n_ov / (_обычных_сек / 60)

    _ov_ids = sorted(int(k) for k in ov if k.isdigit())
    if _ov_ids and _ov_ids[0] > 4:
        FAIL.append(
            f"первая всплывашка только на сцене {_ov_ids[0]} — по правилу 26.10 "
            f"она обязана быть в первых ЧЕТЫРЁХ сценах. Добавь одну на сцену 1-4 "
            f"(это одна всплывашка, не круг правок)")
    # Плотность всплывашек — всегда ПРЕДУПРЕЖДЕНИЕ, не блокер: пользователь
    # удаляет лишние на дашборде (его правки = финал). ПЛАНЕТА целится в ~3/мин,
    # поиск-только идёт реже (прецедент «Чудовищные потери 2» ~1.3/мин).
    if per_min < 2.5:
        WARN.append(f"всплывашек {n_ov} ({per_min:.1f}/мин) — на ПЛАНЕТЕ ~3/мин; меньше — ок, если это твои правки")
    # ФОТО-ВСПЛЫВАШКИ СЧИТАЮТСЯ ОТДЕЛЬНО (2026-10-20, прямая реакция пользователя:
    # «очень мало всплывашек» при 38 из 74 сцен, то есть формально больше половины).
    # Разгадка: из 38 только 4 были ФОТО, остальное текст. Пользователь смотрит
    # дашборд КАРТИНКАМИ, и текстовый слой для него всплывашкой не читается.
    # Ориентир — не меньше одной фото-всплывашки на 6-7 сцен.
    _n_ph = len([1 for k, v in ov.items()
                 if k != "anchor" and str(v.get("photo") or "").strip()])
    # СЧЁТ ПО ОБЫЧНЫМ СЦЕНАМ (09.11): на рисованных слоёв не бывает.
    _n_sc = _обычных
    if _n_ph * 7 < _n_sc:
        WARN.append(f"ФОТО-всплывашек всего {_n_ph} на {_n_sc} сцен — пользователь "
                    f"читает дашборд картинками, и текстовый слой ему всплывашкой не "
                    f"кажется («очень мало всплывашек» при 38 из 74, где фото было 4). "
                    f"Ориентир: одна фото-всплывашка на 6-7 сцен, то есть ~{_n_sc // 7}.")
    # у всех всплывашек пустой sound -> видеоряд выйдет без звука всплывашек
    # (feedback_overlays_sound_field_lost, 2026-09-08). Переприсвоить sound
    # (['whoosh','zatvor','pop'][i%3]) и локально прогнать build_overlays.py sfx.
    # ЦВЕТ НАДПИСЕЙ — ОДИН НА ВЕСЬ РОЛИК (2026-10-22, прямое наблюдение
    # пользователя на дашборде 8793: «все записи пришли одинакового цвета»).
    # Дефолт теперь считается по кругу от номера сцены, но вкладка может
    # проставить один цвет РУКАМИ всем подряд — ровно это и случилось, 21 из 21
    # белых. Это предупреждение, а не блокер: один цвет бывает и осознанным.
    _tcols = [str((v.get("text") or {}).get("color") or "").lower()
              for k, v in ov.items() if k != "anchor" and isinstance(v.get("text"), dict)
              and ((v.get("text") or {}).get("words") or (v.get("text") or {}).get("text"))]
    _tcols = [c for c in _tcols if c]
    # СЧИТАТЬ НАДО ДОЛЮ, А НЕ ЧИСЛО РАЗНЫХ ЦВЕТОВ (08.11, его слово по
    # готовому дашборду: «снова тексты идут одного цвета, только белый и
    # только позиция вверху… старая грабли»). Проверка ниже смотрела, сколько
    # РАЗНЫХ цветов, и молчала на ролике, где цветов было восемь, но белых
    # 18 из 31, а клетка `tc` занимала 25 из 31. Монотонность — это
    # ПРЕОБЛАДАНИЕ, а не бедность набора. Лечится одной командой:
    # `template/nadpisi_spread.py overlays.json`.
    _tpos = [str((v.get("text") or {}).get("pos") or "").lower()
             for k, v in ov.items() if k != "anchor" and isinstance(v.get("text"), dict)
             and not str((v.get("text") or {}).get("style") or "").startswith("mask")
             and ((v.get("text") or {}).get("words") or (v.get("text") or {}).get("text"))]
    _tpos = [x for x in _tpos if x]
    for _что, _ряд in (("ЦВЕТ", _tcols), ("МЕСТО", _tpos)):
        if len(_ряд) < 6:
            continue
        _top = max(set(_ряд), key=_ряд.count)
        _доля = round(100 * _ряд.count(_top) / len(_ряд))
        if _доля > 60:
            FAIL.append(
                "НАДПИСИ ОДНООБРАЗНЫ ПО «%s»: %s занимает %d%% (%d из %d). "
                "Потолок 60%%. Развести одной командой: python3 "
                "~/.claude/skills/news-video/template/nadpisi_spread.py "
                "overlays.json" % (_что, _top, _доля, _ряд.count(_top), len(_ряд)))
    if len(_tcols) >= 5 and len(set(_tcols)) < 3:
        WARN.append(
            "надписей %d, а цветов всего %d (%s) — пользователь просил РАЗНЫЕ "
            "(белый/жёлтый/красный/зелёный/оранжевый). Пустое поле color дашборд "
            "и сборка теперь заполняют по кругу от номера сцены сами: проще "
            "убрать color из overlays.json, чем расставлять руками."
            % (len(_tcols), len(set(_tcols)), ", ".join(sorted(set(_tcols)))))
    snd = [v.get("sound") or (v.get("text", {}).get("sound", "") if isinstance(v.get("text"), dict) else "")
           for k, v in ov.items() if k != "anchor"]
    if snd and not any(snd):
        FAIL.append("у ВСЕХ всплывашек sound='' — видеоряд соберётся БЕЗ звука "
                    "всплывашек. Переприсвоить sound в overlays.json.")
    # ЗВУКИ НАЗНАЧЕНЫ, А САМИХ ФАЙЛОВ В ПАПКЕ НЕТ (2026-10-20, улов `usuario-40`:
    # готовый видеоряд приехал с ОДНИМ потоком, без звуковой дорожки вовсе).
    # Проверка поля `sound` этого не видела: поле заполнено, exit 0. Каталог
    # `sfx/` есть только у проектов, унаследованных копированием от прошлых
    # роликов; свежая папка (`scenes_from_srt.py` + свои файлы) его не получает,
    # и раннер молча собирает немое видео — в логе это тонет среди двух десятков
    # строк «звук 'whoosh' не найден».
    if any(snd):
        _proj_sfx = glob.glob("sfx/*.mp3") + glob.glob("sfx/*.wav")
        _skill_sfx = glob.glob(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "sfx", "*.mp3"))
        if not _proj_sfx and _skill_sfx:
            WARN.append("звуки всплывашкам назначены, а каталога sfx/ в папке "
                        "ролика НЕТ. Для облака не страшно — ship.sh дольёт "
                        "штатные из скилла; но ЛОКАЛЬНАЯ сборка выйдет НЕМОЙ. "
                        "Хочешь наверняка: cp -r ~/.claude/skills/news-video/"
                        "template/sfx .")
        elif not _proj_sfx and not _skill_sfx:
            FAIL.append("звуки всплывашкам назначены, но файлов нет НИ в папке "
                        "ролика, ни в скилле — видеоряд будет немым. Восстанови "
                        "~/.claude/skills/news-video/template/sfx/ (оригиналы: "
                        "D:\\YouTube\\МЕДИОТЕКА\\Звуки).")
    ch = (meta.get("channel") or "").upper()
    # КАНАЛ ПО ИМЕНИ ПАПКИ, ЕСЛИ В ШАПКЕ ЕГО НЕТ. Поле `channel` ставит не
    # каждая вкладка (вчера его не было ни в одном живом проекте), а проверки
    # ниже без канала молча не выполняются — ровно так на ПЛАНЕТУ и приехали
    # 30 запрещённых надписей.
    if not ch:
        # 1) путь к папке ролика на D: — там имя канала есть ВСЕГДА
        #    (`.source_dir` кладёт ship.sh/вкладка). Имя папки проекта
        #    ненадёжно: очередь зовётся `isterika-2210`, канал в ней потерян.
        # Где искать `.source_dir`: в самой папке; в папке замера из кэша
        # очереди (её пишет ship.sh); в соседней папке, чьё имя ЗАКАНЧИВАЕТСЯ
        # именем очереди (`planeta-isterika-2210` против `isterika-2210-cloud`).
        _cwd = os.path.abspath(".")
        _q = os.path.basename(_cwd)
        _q = _q[:-6] if _q.endswith("-cloud") else _q
        _dirs = [_cwd, os.path.join(os.path.dirname(_cwd), _q)]
        try:
            _pd = io.open(os.path.expanduser(
                "~/.cache/videoryad/%s.phasedir" % _q), encoding="utf-8").read().strip()
            if _pd:
                _dirs.append(_pd)
        except Exception:
            pass
        try:
            for _sib in os.listdir(os.path.dirname(_cwd)):
                if _sib.endswith(_q) and _sib != os.path.basename(_cwd):
                    _dirs.append(os.path.join(os.path.dirname(_cwd), _sib))
        except Exception:
            pass
        _hay = ""
        for _d in _dirs:
            try:
                _hay = io.open(os.path.join(_d, ".source_dir"),
                               encoding="utf-8").read().upper()
                if _hay.strip():
                    break
            except Exception:
                continue
        _hay += " " + os.path.abspath(".").upper()
        for _key, _name in (("ПЛАНЕТА", "ПЛАНЕТА"), ("5 МИНУТ", "5 МИНУТ"),
                            ("5МИНУТ", "5 МИНУТ"), ("ОЛЬКА", "ОЛЬКА"),
                            ("ДИПЛОМАТИЯ", "ДИПЛОМАТИЯ СИЛЫ"),
                            ("ПЕРЕВОД", "ПЕРЕВОД")):
            if _key in _hay:
                ch = _name
                break
        # 2) последний рубеж — префикс имени папки
        if not ch:
            _b = os.path.basename(os.path.abspath(".")).lower()
            for _pref, _name in (("planeta", "ПЛАНЕТА"), ("5min", "5 МИНУТ"),
                                 ("olka", "ОЛЬКА"), ("ds-", "ДИПЛОМАТИЯ СИЛЫ"),
                                 ("perevod", "ПЕРЕВОД")):
                if _b.startswith(_pref) or ("-" + _pref) in _b:
                    ch = _name
                    break

    # ТЕКСТОВЫЕ ВСПЛЫВАШКИ — ТОЛЬКО ДЛЯ «5 МИНУТ» (2026-10-21, прямое слово
    # пользователя: «Планете не применять надписи… без моей команды»).
    # Правило было в SKILL.md с 2026-10-08 и всё равно нарушилось: вкладка
    # поставила на ПЛАНЕТУ 30 надписей против 12 фото-всплывашек. Текстом
    # такое не держится — держит только код.
    # Разрешение на конкретный ролик: положить в папку файл `.text-overlays-ok`
    # (пользователь попросил надписи явно). Пустой файл, содержимое не важно.
    # НАДПИСЬ ИЗ-ПОД МАСКИ — НЕ «ТЕКСТОВАЯ ВСПЛЫВАШКА 5 МИНУТ» (07.11).
    # Он выбрал этот приём из витрины кандидатов и сказал прямо: «попробуем
    # применить на канал ПЛАНЕТА, будет примерно собираться так же, как и
    # на канал 5 МИНУТ» → «ставь в сборку на завтра». Это заголовок блока
    # внутри ролика (смена темы), а не поток коротких фактов капсом, из-за
    # которых запрет 21.10 и появился. Поэтому маски из счёта исключены —
    # иначе два правила убивают друг друга: обязательный элемент N-текст
    # ставится, и тот же ролик валится запретом надписей на ПЛАНЕТЕ.
    _MASK_ST = ("mask", "mask_plate")

    def _is_mask(v):
        t = v.get("text")
        return isinstance(t, dict) and \
            str(t.get("style", "")).strip().lower() in _MASK_ST

    _masks = [k for k, v in ov.items()
              if str(k).isdigit() and isinstance(v, dict) and _is_mask(v)]
    _texts = [k for k, v in ov.items()
              if str(k).isdigit() and isinstance(v, dict)
              and (v.get("text") or v.get("words")) and not _is_mask(v)]
    # ПОТОЛОК НА МАСКИ СЧИТАЕТСЯ ОТ ДЛИНЫ РОЛИКА (08.11, его слово: «надписей
    # нужно чуть больше, на 60 сцен всего две-три; чтобы было примерно СЕМЬ
    # на 60 сцен»). Норма — одна на 8-9 сцен, потолок на три выше нормы:
    # прежняя жёсткая четвёрка теперь ниже самой нормы и ругалась бы на
    # правильном ролике.
    # ТОЛЬКО ОБЫЧНЫЕ СЦЕНЫ В ЗНАМЕНАТЕЛЕ (09.11): надпись на `card:*`
    # запрещена, значит и в норму карточки не идут.
    _норма_масок = max(1, int(round(_обычных / 8.5)))
    if len(_masks) > _норма_масок + 3:
        WARN.append(
            "НАДПИСЕЙ ИЗ-ПОД МАСКИ %d при норме %d на %d сцен (сцены %s). "
            "Это заголовок блока на смену темы: когда их заметно больше "
            "нормы, рубеж перестаёт читаться."
            % (len(_masks), _норма_масок, _обычных,
               ", ".join(sorted(_masks, key=int)[:10])))
    if _texts and ch and "5 МИНУТ" not in ch and not os.path.exists(".text-overlays-ok"):
        FAIL.append(
            f"ТЕКСТОВЫЕ ВСПЛЫВАШКИ НА КАНАЛЕ {ch}: их {len(_texts)} "
            f"(сцены {', '.join(sorted(_texts, key=int)[:10])}"
            f"{'…' if len(_texts) > 10 else ''}). Надписи — фишка «5 МИНУТ»; "
            f"на остальных каналах только по ПРЯМОЙ просьбе пользователя. "
            f"Убрать их из overlays.json, либо — если он попросил явно — "
            f"создать в папке ролика пустой файл .text-overlays-ok")

    # НА «5 МИНУТ» НАДПИСИ ОБЯЗАТЕЛЬНЫ (06.11, его прямое слово, зло:
    # «почему при сборке на „Планету“ пропали надписи… надписей не должно
    # быть ТОЛЬКО на „Планете“, а на „5 минут“ надписи ДОЛЖНЫ быть, я их не
    # убирал»). Что случилось: 05.11 норму всплывашек переписали на «около
    # десяти», вкладки стали считать этим числом ВСЁ — и надписи исчезли
    # совсем. Замер по сданным: до 05.11 их ставили по 30-40 на ролик, с
    # 05.11 — НОЛЬ на всех роликах подряд, включая «5 МИНУТ».
    # Запрет на других каналах уже держался кодом, а обязательность здесь —
    # нет: правило существовало только текстом и поэтому потерялось.
    # НАДПИСЬ ВНИЗУ — ЭТО МЕСТО СУБТИТРОВ (его слово 28.10 и ещё раз 06.11:
    # «они должны идти в верхней части или в середине»). `build_overlays.py`
    # низ поднимает сам, но ловим ДО дашборда: иначе вкладка увидит на экране
    # не то, что задумала, и спишет это на перекрытие.
    _low = sorted(k for k, v in ov.items()
                  if str(k).isdigit() and isinstance(v, dict)
                  and (v.get("text") or v.get("words"))
                  and str(v.get("pos", "tc")).lower().startswith("b"))
    if _low:
        FAIL.append(
            "НАДПИСЬ ВНИЗУ КАДРА (сцены %s): там идут субтитры, они будут "
            "перекрыты. Надписи только ВЕРХ или СЕРЕДИНА — `pos` из "
            "t*/m* (tl/tc/tr/ml/mc/mr)." % ", ".join(_low[:10]))

    # ИСКЛЮЧЕНИЕ НА КОНКРЕТНЫЙ РОЛИК — ПУСТОЙ ФАЙЛ `.no-text-overlays-ok`
    # (06.11, его прямое слово по роликам в работе: «это для следующих
    # сборок, сейчас ничего не меняем, оставляем как есть»). Правило
    # обязательных надписей вступило в силу посреди смены, и три готовых
    # ролика переделывать он не захотел — каждый стоил бы полутора часов.
    if ch and "5 МИНУТ" in ch and not _texts and os.path.exists(".no-text-overlays-ok"):
        WARN.append("надписей нет, но стоит разрешение `.no-text-overlays-ok` "
                    "(его решение по этому ролику) — пропускаю")
    elif ch and "5 МИНУТ" in ch and not _texts:
        _need = max(8, int(total / 60 * 2)) if total else 20
        FAIL.append(
            "НА «5 МИНУТ» НЕТ НИ ОДНОЙ НАДПИСИ. Это фишка канала и его прямое "
            "требование: норма ~2 на минуту, на этом ролике это около %d штук. "
            "Ставятся в overlays.json ключом `words` (вид закреплён 21.10: "
            "тёмная пластина, цветная черта слева, белый Roboto Condensed "
            "капсом). Фото-всплывашки их не заменяют — это РАЗНЫЕ слои."
            % _need)

    # НАДПИСЕЙ СТАЛО СЛИШКОМ МНОГО — ПОТОЛОК СВЕРХУ (07.11, его прямое
    # слово по сданным роликам: «надо уменьшить количество надписей. Очень
    # их много. Ну, бесполезные абсолютно. Уменьшить на 30%»). Было ~3 на
    # минуту (на роликах дня выходило 49 и 46 штук), стало ~2 — это и есть
    # минус 30%. Снизу правило по-прежнему блокер (надписи обязательны),
    # сверху — предупреждение: лишние он снимает на дашборде сам.
    if ch and "5 МИНУТ" in ch and _texts and total:
        _cap = int(total / 60 * 2 * 1.2)
        if len(_texts) > _cap:
            WARN.append(
                "НАДПИСЕЙ %d при норме ~2 на минуту (потолок %d на этом "
                "ролике). Его слово 07.11: «очень их много, бесполезные "
                "абсолютно». Снимай те, что ничего не добавляют к кадру: "
                "пересказ реплики, общие слова, повтор уже сказанного."
                % (len(_texts), _cap))

    # НАДПИСИ АГЕНТА ПОТЕРЯЛИСЬ ПО ДОРОГЕ (28.10, улов Flamingo — пользователь
    # поймал это САМ, двумя заходами). Codex кладёт надписи ВНУТРЬ сцен:
    # `scenes[].overlays = [{"type":"text","text":{"words":…}}]`. Дашборд и
    # сборка читают СОВСЕМ ДРУГОЙ файл — `overlays.json` вида
    # `{"<id>": {"text": {...}}}`, и перенос делается руками. На
    # `5min-flamingo-2810` в файле агента было 20 надписей, в `overlays.json` —
    # НОЛЬ, и ролик уехал на дашборд без единой надписи на канале, где они
    # разрешены и являются фишкой. Это тот же класс «поле в JSON ≠ то, что
    # читает сборщик», и держать его можно только кодом.
    _agent_texts = []
    for _s in scenes:
        for _o in (_s.get("overlays") or []):
            if isinstance(_o, dict) and (_o.get("type") == "text"
                                         or isinstance(_o.get("text"), dict)):
                _agent_texts.append(_s["id"])
                break
    # ВАЖНО: гейт действует ТОЛЬКО там, где надписи РАЗРЕШЕНЫ. На ПЛАНЕТЕ они
    # запрещены, агент всё равно их предлагает, и вкладка СОЗНАТЕЛЬНО не
    # переносит — без этого условия гейт валил бы её зря (поймано на своей же
    # проверке, до раскатки).
    _texts_allowed = ("5 МИНУТ" in (ch or "")) or os.path.exists(".text-overlays-ok")
    if _agent_texts and not _texts and _texts_allowed:
        FAIL.append(
            f"НАДПИСИ ЕСТЬ В СЦЕНАХ, НО НЕ ПЕРЕНЕСЕНЫ В `overlays.json`: "
            f"в раскадровке их {len(_agent_texts)} (сцены "
            f"{', '.join(map(str, _agent_texts[:10]))}"
            f"{'…' if len(_agent_texts) > 10 else ''}), в overlays.json ноль. "
            f"Дашборд и сборка читают ТОЛЬКО overlays.json — ролик уедет без "
            f"надписей. Формат записи: \"<id>\": {{\"text\": {{\"words\": "
            f"\"…\", \"at\": 3.0}}}}; на сцену, где уже есть фото-всплывашка "
            f"или карточка, надпись не ставить — вторая запись затирает первую")

    # ОДИН ФАЙЛ В СЦЕНЕ И ВО ВСПЛЫВАШКЕ — БАН ОДНОЙ ВАЛИТ ДРУГУЮ (28.10,
    # улов вкладки «Переговоры Москва»): сцена 45 и её всплывашка приехали
    # ОДНИМ кадром Овального кабинета; вкладка меняла всплывашку, `refetch`
    # забанил md5 на два дня — и `selfcheck` свалил прогон на «ЗАБАНЕННЫЙ КАДР
    # В СБОРКЕ: images/scene_045.jpg». Сказать об этом надо ДО замены, пока
    # она дешёвая.
    import hashlib as _hl
    def _md5f(_p):
        try:
            with open(_p, "rb") as _f:
                return _hl.md5(_f.read()).hexdigest()
        except OSError:
            return ""
    _img_md5 = {}
    for _p in glob.glob(os.path.join("images", "scene_*")):
        if _p.endswith((".json", ".text.png", ".lock")) or ".ovthumb." in _p:
            continue
        _h = _md5f(_p)
        if _h:
            _img_md5.setdefault(_h, os.path.basename(_p))
    _same = []
    for _p in glob.glob(os.path.join("overlays", "scene_*")):
        if _p.endswith((".json", ".text.png", ".lock")) or ".ovthumb." in _p:
            continue
        _h = _md5f(_p)
        if _h and _h in _img_md5:
            _same.append(f"{os.path.basename(_p)} = images/{_img_md5[_h]}")
    if _same:
        WARN.append("ОДИН И ТОТ ЖЕ ФАЙЛ в сцене и во всплывашке (%d): %s. "
                    "Меняй — но помни: бан по md5 заденет ОБА места, и "
                    "`selfcheck` свалит прогон на забаненном кадре в сборке. "
                    "Сначала замени кадр сцены или всплывашки БЕЗ `--ban`, "
                    "потом добивай." % (len(_same), "; ".join(_same[:5])))

    want = "bottom" if "ПЛАНЕТА" in ch or "ПЛАНЕТА" == ch else "top"
    if ch and ov.get("anchor", "bottom") != want:
        FAIL.append(f"overlays anchor={ov.get('anchor','bottom')}, для канала {ch} нужен {want} (SKILL.md 3b)")
    for k, v in ov.items():
        if k == "anchor":
            continue
        ph = v.get("photo", "")
        tb = v.get("text") if isinstance(v.get("text"), dict) else None
        has_txt = bool(tb and str(tb.get("words") or tb.get("text") or "").strip())
        if not ph and has_txt:
            continue                       # чисто текст-всплывашка — фото не нужно
        if not os.path.exists(ph):
            # ФАЙЛ МОЖЕТ ЛЕЖАТЬ С ДРУГИМ РАСШИРЕНИЕМ (2026-10-22, улов
            # `usuario-92`): карта из медиатеки приезжает .png, а в
            # overlays.json записан привычный .jpg. Сборка теперь такой путь
            # разрешает сама, но сказать об этом надо — иначе разойдутся
            # дашборд (показывает по записанному пути) и готовый ролик.
            _alt = [c for c in sorted(glob.glob(os.path.splitext(ph)[0] + ".*"))
                    if not c.endswith((".text.png", ".json")) and os.path.getsize(c) > 0]
            if _alt:
                WARN.append(f"всплывашка {k}: в overlays.json записан "
                            f"{os.path.basename(ph)}, а на диске "
                            f"{os.path.basename(_alt[0])} — сборка возьмёт "
                            f"файл с диска, но на дашборде всплывашка может "
                            f"не показаться. Поправь путь в overlays.json")
                ph = _alt[0]
            else:
                FAIL.append(f"всплывашка {k}: файла нет ({ph})")
                continue
        oh = hashlib.md5(open(ph, "rb").read()).hexdigest()
        bf = asset(int(k))
        if bf and hashlib.md5(open(bf[0], "rb").read()).hexdigest() == oh:
            FAIL.append(f"всплывашка {k} = базовый кадр сцены (нельзя, SKILL.md 3b)")

    # 4b. всплывашка называет ТОГО ЖЕ человека/институт, что и базовый кадр —
    # не ловится md5 (два РАЗНЫХ файла одного и того же человека всё ещё
    # нарушение, user 2026-10-05/08: "Трамп всплывашка иллюстрирует Трампа",
    # "Сибига иллюстрирует Сибигу"). Сверяем имена собственные в запросах,
    # а не пиксели — работает даже когда это два разных фото одного лица.
    import re as _re
    def _names(text):
        # includes Ukrainian-only letters (і/ї/є/ґ) — without them a Cyrillic
        # word truncates mid-letter ("Київ"->"Ки", "Чернігівський"->"Черн")
        # and those stubs false-match across unrelated scenes (found live,
        # session 2026-10-08, peer session on an all-Ukrainian "5 МИНУТ" build).
        # ПУТЬ МЕДИАТЕКИ — НЕ ЗАПРОС (2026-10-22, улов `usuario-82`): у сцен
        # с источником local_library в source_query лежит путь вида
        # «ПОЛИТИКА/ПУТИН/файл.jpg». Слова пути брались целиком, и база
        # «ПОЛИТИКА/ПУТИН/…» со всплывашкой «ПОЛИТИКА/КАРТЫ/УКРАИНА/…»
        # пересекались по ОБЩЕМУ КОРНЮ «ПОЛИТИКА» — selfcheck валил прогон
        # «тот же человек/объект», хотя объекты разные. Вкладка обходила это
        # переименованием пути. Берём только значащие сегменты: без первого
        # (раздел медиатеки) и без имени файла.
        t = text or ""
        if "/" in t:
            segs = [x for x in t.replace("\\", "/").split("/") if x.strip()]
            # ПОСЛЕДНИЙ СЕГМЕНТ ОТБРАСЫВАТЬ ТОЛЬКО ЕСЛИ ЭТО ИМЯ ФАЙЛА
            # (2026-10-29). Сцена БАЗЫ несёт путь ПАПКИ без файла
            # («БАЗА/БЫТ-УКРАИНА/ТРАНСФОРМАТОРНАЯ-ПОДСТАНЦИЯ-СЕТКОЙ»), и
            # прежнее правило выбрасывало ровно тот сегмент, в котором смысл,
            # оставляя раздел «БЫТ-УКРАИНА». Тогда подстанция и эскалатор
            # метро считались ОДНИМ объектом, и selfcheck ВАЛИЛ прогон. На
            # 5 МИНУТ, где движение закрывается базой, под это попадала любая
            # пара кадров из одного раздела.
            _last = segs[-1] if segs else ""
            _isfile = "." in _last and len(_last.rsplit(".", 1)[-1]) <= 5
            if not _isfile:
                # папка БАЗЫ: смысл только в ИМЕНИ ОБЪЕКТА, раздел («БЫТ-
                # УКРАИНА», «ВЛАСТЬ-РОССИЯ») общий у десятка разных кадров
                segs = segs[-1:]
            elif len(segs) > 2:
                segs = segs[1:-1]
            elif len(segs) == 2:
                segs = segs[:1]
            t = " ".join(segs)
        return set(_re.findall(r"[А-ЯЁІЇЄҐ][а-яёіїєґА-ЯЁІЇЄҐ]+", t))
    _STOP = {"КАРТЫ", "Карты", "Украины", "Украина", "Украине", "Киев", "Киева", "Москва", "Москвы",
              "России", "Россия", "Верховная", "Рада", "Радой", "Радою", "НАТО",
              "МИД", "МЗС", "Кремль", "США", "ЕС", "Индии", "Индия",
              # Ukrainian/other-language forms of the same stop-words — without
              # these, a scene/overlay pair written in Ukrainian (or naming a
              # country other than RU/UA) false-flagged as a name collision
              # just because both mentioned "Україна"/"Ємен" (user_56 report,
              # cross-session, 2026-10-10). Add more language forms here as
              # they're caught, same spirit as the a3 cheat-sheet below.
              "Україна", "України", "Україні", "Україну", "Україною",
              "Київ", "Києва", "Києві", "Київу", "Москві", "Росія", "Росії",
              "Росію", "Росією", "ЗСУ", "Кремля", "Кремлі", "Ємен", "Ємену",
              "Йемен", "Йемену", "Йемена", "ЄС", "Індія", "Індії",
              # РАСПРОСТРАНЁННЫЕ ЛИЧНЫЕ ИМЕНА — НЕ «ТОТ ЖЕ ЧЕЛОВЕК»
              # (26.10, улов `usuario-d9`, ложная блокировка перед самой
              # отдачей дашборда): база «Владимир Путин», всплывашка
              # «Владимир Зеленский» — люди РАЗНЫЕ, а проверка видела общее
              # ИМЯ и валила прогон. Вкладка обошла, убрав имя из запроса,
              # то есть ухудшила запрос ради прохождения проверки. Человека
              # различает фамилия, поэтому личные имена в сверку не берём;
              # если совпала ещё и фамилия — пара всё равно упадёт.
              "Владимир", "Володимир", "Дмитрий", "Дмитро", "Сергей",
              "Сергій", "Александр", "Олександр", "Андрей", "Андрій",
              "Виктор", "Віктор", "Михаил", "Михайло", "Николай", "Микола",
              "Юрий", "Юрій", "Петр", "Пётр", "Петро", "Иван", "Іван",
              "Алексей", "Олексій", "Валерий", "Валерій", "Игорь", "Ігор",
              "Денис", "Максим", "Антон", "Павел", "Павло", "Олег", "Роман",
              "Эмманюэль", "Дональд", "Джо", "Джон", "Кир", "Фридрих",
              "Реджеп", "Си", "Нарендра", "Биньямин", "Урсула", "Марко"}
    # ГЕОГРАФИЯ — НЕ «ТОТ ЖЕ ЧЕЛОВЕК» (2026-10-17, БЛОКЕР на
    # planeta-tri-bukvy-1810: девять FAIL из девяти были совпадением
    # страноведческого слова — «Германии», «Европейского», «Словакии»,
    # «Эстонии»). База «здание ЕЦБ во Франкфурте» + всплывашка «Кристин
    # Лагард глава Европейского центрального банка» — это ОДОБРЕННЫЙ приём
    # «лицо того, кто в этом здании решает», а проверка его бракует. На
    # ролике, где все 85 сцен про Германию и ЕС, секция была неработоспособна
    # и обходилась косметикой запроса, то есть не работала вовсе.
    # Поэтому из сравнения выбрасываются страны, города и производные от них
    # прилагательные — по КОРНЮ, а не поимённым списком форм.
    # Фамилии НЕ трогаем: «Зеленский», «Навальный» и прочие -ский остаются,
    # иначе проверка потеряет главный свой случай.
    _GEO_STEMS = (
        "герман", "немецк", "европ", "евросоюз", "брюссел", "страсбург",
        "франкфурт", "берлин", "мюнхен", "гамбург", "кёльн", "кельн",
        "дрезден", "штутгарт", "дюссельдорф", "бонн", "рамштайн",
        "словак", "словацк", "словен", "чехи", "чешск", "праг", "венгр",
        "будапешт", "польш", "польск", "варшав", "эстон", "таллин",
        "латви", "рига", "литв", "вильнюс", "франц", "париж", "итали",
        "рим", "испан", "мадрид", "португал", "греци", "афин", "турци",
        "анкар", "стамбул", "румын", "бухарест", "болгар", "софи",
        "серби", "хорват", "австри", "вен", "швейцар", "женев", "швеци",
        "стокгольм", "норвег", "осло", "финлянд", "хельсинки", "дани",
        "копенгаген", "нидерланд", "амстердам", "роттердам", "гааг",
        "бельги", "люксембург", "ирланд", "британ", "англи", "лондон",
        "шотланд", "америк", "вашингтон", "сша", "китай", "кита", "пекин",
        "япони", "токио", "коре", "инди", "иран", "тегеран", "ирак",
        "израил", "иерусалим", "сири", "египт", "африк", "азербайджан",
        "армени", "грузи", "казахстан", "белорус", "беларус", "минск",
        "молдов", "кишинёв", "кишинев", "балти", "крым", "донецк",
        "луганск", "харьков", "одесс", "львов", "днепр", "запорож",
        "херсон", "мариупол", "киев", "київ", "москв", "петербург",
        "украин", "україн", "росси", "росі", "брюссель",
    )

    def _is_geo(w):
        lw = w.lower()
        return any(lw.startswith(st) for st in _GEO_STEMS)

    # КЛИП КАРТОЧКИ СТАРШЕ СВОЕГО ЗАДАНИЯ = ПЕРЕВЫПУСК НЕ ОТРИСОВАН (29.10).
    # `card_put.py` переписывает задание в `cards/queue`, но клип остаётся
    # прежним до следующего прогона `cards_cloud.py`. Вкладка едва не отдала
    # дашборд со старой карточкой, которую пользователь уже забраковал.
    for _qj in sorted(glob.glob(os.path.join("cards", "queue", "scene_*.json"))):
        _sid = os.path.basename(_qj)[6:9]
        _clip = os.path.join("images", "scene_%s.mp4" % _sid)
        if os.path.exists(_clip) and os.path.getmtime(_clip) < os.path.getmtime(_qj):
            FAIL.append("карточка сцены %s НЕ ПЕРЕРИСОВАНА: задание новее клипа "
                        "— прогони `cards_cloud.py`, иначе на экране старая "
                        "версия" % int(_sid))

    _by_id = {s["id"]: s for s in scenes}
    _ovq_path = None
    for _cand in glob.glob("*overlays_fetch*.json") + glob.glob("*overlay*fetch*.scenes.json"):
        _ovq_path = _cand
        break
    if _ovq_path and os.path.exists(_ovq_path):
        _ovq = {s["id"]: s.get("source_query", "") for s in json.load(open(_ovq_path, encoding="utf-8"))["scenes"]}
        for k, v in ov.items():
            if k == "anchor":
                continue
            sid = int(k)
            base_q = _by_id.get(sid, {}).get("source_query", "")
            ov_q = _ovq.get(sid, "")
            shared = (_names(base_q) - _STOP) & (_names(ov_q) - _STOP)
            shared = {w for w in shared if not _is_geo(w)}
            if shared:
                FAIL.append(f"всплывашка {k}: тот же человек/объект ({', '.join(sorted(shared))}) "
                            f"что и базовый кадр — база: {base_q!r}, всплывашка: {ov_q!r}")
        # 4c. ИМЯ В ТЕКСТОВОЙ ВСПЛЫВАШКЕ ДОЛЖНО СТОЯТЬ НА КАДРЕ ЭТОГО ЧЕЛОВЕКА
        # (2026-10-18, третий случай за два дня — значит проверять должен код).
        # Дефект рождается не при расстановке, а при ПРАВКЕ: вкладка меняет
        # базовый кадр, а именная надпись остаётся от прежнего. Живьём:
        # «надпись Анна Скороход, а на фотографии Зеленский» (17.10) и
        # «ВАННАЧЧИ: ЕВРОПА — НЕ БАНКОМАТ» на панораме Рима, куда база уехала
        # после замены (18.10). Зритель читает это как «подписали не того».
        #
        # Как отличаем ИМЯ от обычного слова капсом, не заводя стоп-листа:
        # слово из надписи считается именем, только если где-то в ТЕКСТАХ сцен
        # встречается то же слово с ЗАГЛАВНОЙ буквы («Ванначчи», «Скороход»).
        # «ЗАКОННЫЕ», «НОЯБРЬ», «ГРАНИЦА» в текстах идут со строчной и именами
        # не считаются. Эвристику «текст без цифры и имени = абстракция» тут
        # НЕ повторяем — её сняли 17.10 за 26 ложных из 41.
        # Это WARN, а не FAIL: бывает законный случай (надпись про человека,
        # которого кадр подразумевает), и блокировать сдачу из-за него нельзя.
        # ПОЧИНЕНО 2026-10-18 В ТОТ ЖЕ ЧАС: первая версия давала 6 ложных из 6
        # на живом ролике («ПОДПИСИ», «БАНКОМАТ», «ОПЕРАЦИЯ», «БОЛЬШЕ»,
        # «ДОХОДЫ»). Причина системная: в закадровом тексте полно слов В НАЧАЛЕ
        # ПРЕДЛОЖЕНИЯ, и они тоже с заглавной («Банкомат. Подошёл. Вставил
        # карту»), а надписи вкладка строит из ключевых слов фразы — почти
        # каждое где-то открывает предложение. Стенд этого не показал, потому
        # что проверочные надписи в текстах шли со строчной.
        # Теперь имя засчитывается, только если слово встречается с заглавной
        # НЕ в начале предложения (фамилия внутри фразы стоит всегда) И нигде
        # не встречается со строчной (нарицательное хоть раз да будет строчным).
        _all_text = " ".join(sc.get("text", "") or "" for sc in scenes)
        _lower_seen = {w.lower() for w in _re.findall(r"[а-яёіїєґ]{5,}", _all_text)}
        # ДОРАБОТКА 2026-10-18 (вторая правка в тот же час, обе дыры нашла
        # рабочая вкладка на живом ролике — шума стало 6 → 2 → 0):
        # (а) ЦИТАТА тоже начинается с заглавной: «Он начал писать "Операция
        #     отклонена"» — слово внутри фразы, со строчной нигде не встречается,
        #     оба прежних условия проходит честно. Поэтому открывающая кавычка
        #     считается началом предложения наравне с точкой.
        # (б) правило написано про ЛЮДЕЙ («надпись ставится на кадр ЭТОГО
        #     человека»), а ловило любое имя собственное, включая страны:
        #     «ЗВОНОК В КАНАДУ И ЯПОНИЮ» — законная надпись, страну достаточно
        #     НАЗВАТЬ в тексте, в кадре она быть не обязана. Разводим дёшево,
        #     без справочника стран: имя человека в текстах почти всегда идёт
        #     ПАРОЙ с другим словом с заглавной («Роберто Ванначчи», «Анна
        #     Скороход», «Майкл Флинн»), а страна в перечислении стоит одна.
        _pair_caps = set()
        _CAP = r"[А-ЯЁІЇЄҐ][а-яёіїєґ]+"
        for _sc in scenes:
            for _m in _re.finditer(r"(%s)\s+(%s)" % (_CAP, _CAP), _sc.get("text", "") or ""):
                for _g in (_m.group(1), _m.group(2)):
                    if len(_g) >= 5:
                        _pair_caps.add(_g.lower()[:5])
        _OPEN_Q = "«\"'„“("
        _name_pool = set()
        for _sc in scenes:
            _t = _sc.get("text", "") or ""
            for _m in _re.finditer(r"[А-ЯЁІЇЄҐ][а-яёіїєґА-ЯЁІЇЄҐ]{4,}", _t):
                _w = _m.group(0)
                _raw = _t[:_m.start()].rstrip(" ")
                if not _raw or _raw[-1] in ".!?…:;" or _raw[-1] in _OPEN_Q:
                    continue              # начало предложения ИЛИ цитаты
                if _w.lower() in _lower_seen:
                    continue              # где-то со строчной = нарицательное
                if _is_geo(_w) or _w in _STOP:
                    continue              # страна, город, институт
                if _w.lower()[:5] not in _pair_caps:
                    continue              # одиночное имя собственное = не человек
                _name_pool.add(_w.lower()[:5])
        for k, v in ov.items():
            if k == "anchor" or not isinstance(v, dict):
                continue
            _tb = v.get("text") or {}
            _words = str(_tb.get("words") or "")
            if not _words:
                continue
            sid = int(k)
            # У СЦЕНЫ `direct_url` СВЕРЯТЬ НАДО `visual_prompt`, А НЕ
            # `source_query` (07.11, улов вкладки `usuario-65`). В
            # `source_query` у таких сцен лежит адрес `cdn4.telesco.pe/...`,
            # в котором имени нет по устройству — и проверка честно не
            # находила «КАЛЛАС» в ссылке, ругаясь на кадр, где Каллас и
            # изображена. Три ложных срабатывания из трёх на одном ролике.
            # Описание вложения вкладка кладёт в `visual_prompt`, оттуда и
            # берём. Для прочих источников порядок прежний.
            _sc_row = _by_id.get(sid, {})
            _base_q = (_sc_row.get("source_query", "") or "").lower()
            if (str(_sc_row.get("source", "")).startswith("direct_url")
                    or _base_q.startswith("http")):
                _base_q = ((_sc_row.get("visual_prompt", "") or "").lower()
                           or _base_q)
            for _tok in _re.findall(r"[А-ЯЁІЇЄҐ]{5,}", _words):
                _stem = _tok.lower()[:5]
                if _stem not in _name_pool or _is_geo(_tok):
                    continue
                if _stem not in _base_q:
                    WARN.append(
                        f"всплывашка {k}: надпись называет «{_tok}», а базовый "
                        f"кадр этой сцены про другое ({_base_q!r}) — именная "
                        f"надпись ставится ТОЛЬКО на кадр этого человека; "
                        f"частая причина: базу меняли, а надпись осталась")

        # ЛИШНИЕ ЗАПИСИ В FETCH-ФАЙЛЕ = ВОСКРЕШЕНИЕ СНЯТОГО (2026-10-16).
        # Пользователь снимает всплывашки на дашборде, overlays.json худеет,
        # а overlays_fetch.scenes.json остаётся прежним — и облако набирает
        # кадры для снятых, после чего они возвращаются в ролик. Правило 13
        # велит подрезать fetch-файл руками, но проверку легко проскочить:
        # раньше selfcheck сверял overlays.json только с файлами на диске и
        # на это не ругался вовсе (поймано живьём на planeta-yalta-1710,
        # 55 записей против 44). Стоит миллисекунду, закрывает весь класс.
        _ov_ids = {int(k) for k in ov if k != "anchor"}
        _extra = sorted(set(_ovq) - _ov_ids)
        if _extra:
            FAIL.append(
                f"{_ovq_path}: лишние {len(_extra)} записей, которых нет в overlays.json "
                f"(id: {', '.join(map(str, _extra[:12]))}{'…' if len(_extra) > 12 else ''}) — "
                f"облако наберёт кадры для СНЯТЫХ всплывашек и они вернутся в ролик. "
                f"Подрезать fetch-файл до состава overlays.json перед ship (SKILL.md п.13)")

# 5. видео-лид (SKILL.md rule 7) — ПРЕДУПРЕЖДЕНИЕ, не блокер: пользователь
# может сознательно наменять фото в первой трети на дашборде (его правки =
# финал). Флагаем, чтобы он знал, но сборку не держим.
# Соседний скрипт — ПО ПОЛНОМУ ПУТИ ОТ СЕБЯ, а не по имени из cwd
# (2026-10-17): selfcheck теперь гоняется из template при cwd = папка
# проекта, и голое имя искалось бы в проекте, где копии может не быть.
_HERE = os.path.dirname(os.path.abspath(__file__))
r = subprocess.run(["python3", os.path.join(_HERE, "check_lead.py"), scenes_path, images],
                   capture_output=True, text=True)
if r.returncode != 0:
    WARN.append("видео-лид не выполнен (см. ниже) — ок, если это твои правки на дашборде:\n     "
                + (r.stdout + r.stderr).strip().replace("\n", "\n     ")[:400])

# 4b-бис. СТОК ЗАПРЕЩЁН ПОЛНОСТЬЮ (28.10, прямое слово пользователя после
# просмотра шести роликов смены: «стоковые кадры вообще не попадают в тему,
# они просто разрывают смысловой сюжет, нахуй не нужны, удаляем их, не берём
# больше эти пиксели в новостную сборку»). Был коридор 10-20% хронометража —
# теперь ни одной сцены. Приёмка раскадровки это уже валит, здесь ФИНАЛЬНЫЙ
# гейт: сцена могла стать стоковой и после приёмки, руками или рефетчем.
_stock_scenes = [s["id"] for s in scenes
                 if str(s.get("source", "")).startswith("pexels")]
if _stock_scenes:
    FAIL.append("СТОК В СБОРКЕ (%d сцен: %s) — запрещён полностью с 28.10. "
                "Замени источник: медиатека (открыта на всех каналах), "
                "press_photo, web_search, direct_url из досье или карточка"
                % (len(_stock_scenes),
                   ", ".join(map(str, _stock_scenes[:12]))))

# 4c. ВИДЕО КОРОЧЕ СВОЕЙ СЦЕНЫ = ВИДИМАЯ ПЕТЛЯ (2026-10-17). build_clips
# добивает короткий источник `-stream_loop -1`, то есть клип 6,0 с на сцене
# 10,0 с проигрывается полтора раза подряд — зритель видит повтор движения.
# В логе фетча при этом честный `ok`: файл скачан, он просто короткий.
# Ловится только сверкой длительности файла с `duration_sec` сцены.
_short = []
for _s in scenes:
    _a = asset(_s["id"])
    if not _a or not _a[0].lower().endswith((".mp4", ".mov")):
        continue
    try:
        _pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", _a[0]],
                             capture_output=True, text=True)
        _d = float((_pr.stdout or "0").strip() or 0)
    except Exception:
        continue
    _need = float(_s.get("duration_sec") or 0)
    if _d and _need and _d < _need - 0.25:
        _short.append(f"сцена {_s['id']}: клип {_d:.1f}с на сцену {_need:.1f}с "
                      f"(петля ×{_need/_d:.1f})")
# ПОРОГ РАЗВЕДЁН НА ДВА (28.10, улов вкладки 2 на `5min-kiev-obrechen-2810`):
# клип 4,6 с на сцену 12,0 с — петля ×2,6, движение повторяется два с
# половиной раза и это видно глазом, а `selfcheck` печатал лишь WARN и
# отвечал «чисто». Петля до ×2 на глаз почти не читается (её сцена 17: ×1,1),
# от ×2 — читается всегда. Значит ×2 и выше валит прогон, остальное остаётся
# предупреждением.
_loop_hard, _loop_soft = [], []
for _line in _short:
    try:
        _x = float(_line.rsplit("×", 1)[1].rstrip(")"))
    except (IndexError, ValueError):
        _x = 0.0
    (_loop_hard if _x >= 2.0 else _loop_soft).append(_line)
if _loop_hard:
    FAIL.append("видео КОРОЧЕ своей сцены БОЛЬШЕ ЧЕМ ВДВОЕ — повтор движения "
                "виден глазом, заменить файл или укоротить сцену:\n     "
                + "\n     ".join(_loop_hard[:10]))
if _loop_soft:
    WARN.append("видео КОРОЧЕ своей сцены — будет повтор движения, "
                "заменить или укоротить сцену:\n     "
                + "\n     ".join(_loop_soft[:10]))

# 5a. ВСПЛЫВАШКА С ТЕМ ЖЕ ЗАПРОСОМ, ЧТО И БАЗОВЫЙ КАДР (2026-10-17).
# Найдено прямо в журнале отказов: на 5min-gerasimov сцена 7 — и база, и
# всплывашка «Московский Кремль Спасская башня флаг России», пользователь
# снял со словами «не понимаю наличие этой всплывашки». Это механическая
# ошибка классификации, глазами её ловить незачем.
try:
    _ovq = {}
    for _cand in glob.glob("*overlays_fetch*.json") + glob.glob("*overlay*fetch*.scenes.json"):
        try:
            for _o in json.load(open(_cand, encoding="utf-8")).get("scenes", []):
                _ovq[int(_o.get("id", -1))] = (_o.get("source_query") or "").strip().lower()
        except (OSError, ValueError, TypeError):
            continue
    for _s in scenes:
        _q = (_s.get("source_query") or "").strip().lower()
        if _q and _ovq.get(_s["id"]) == _q:
            FAIL.append(f"всплывашка {_s['id']}: запрос ТОТ ЖЕ, что у базового кадра "
                        f"(«{_q[:50]}») — она ничего не добавляет, переписать или снять")
except Exception:
    pass

# 5b. СВЕРКА ВСЕЙ СБОРКИ С АКТИВНЫМ БАН-ЛИСТОМ (2026-10-17). Фетчер баны
# чтит на всех путях (скачивание, кэш, библиотека, дашбордная замена), и всё
# же на `planeta-svergnut-1810` забаненный девять дней назад кадр (чужое лицо,
# выдаваемое поиском за Гончаренко) оказался в готовой сборке. Поймала его
# только ручная сверка перед ship — ни фетчер, ни selfcheck, ни четыре
# субагента не увидели: лицо похожее, на плитке не отличить. Путь, которым он
# прошёл, по логам восстановить не удалось — значит нужен ПОСЛЕДНИЙ рубеж,
# который не зависит от того, каким путём файл попал в папку.
_ban_path = os.environ.get("VIDEORYAD_BANNED_FILE") or os.path.expanduser(
    "~/projects/media-library/.banned_md5.json")
try:
    import time as _t
    _ban_raw = json.load(open(_ban_path, encoding="utf-8"))
    _today = _t.strftime("%Y-%m-%d")
    # ЧУЖОЙ ВРЕМЕННЫЙ БАН — НЕ НАШЕ ДЕЛО (06.11, улов `usuario-c8`: восемь
    # активных чужих банов на чистых кадрах, и ВЕСЬ второй круг ушёл на них).
    # Временный бан рефетча означает «не возвращай этот кадр В ТОМ ролике»;
    # с 06.11 в записи стоит `project`. Вечный бан (`--ban`, без срока)
    # остаётся общим: такой кадр плох сам по себе.
    _proj_now = os.environ.get("VIDEORYAD_PROJECT") or os.path.basename(os.path.abspath("."))
    _ban = set()
    for m, e in _ban_raw.items():
        if not isinstance(e, dict):
            _ban.add(m)
            continue
        _until = e.get("until")
        if _until and _until < _today:
            continue
        _own = str(e.get("project") or "")
        if _until and _own and _own != _proj_now \
                and _own.rstrip("-cloud") != _proj_now.rstrip("-cloud"):
            continue
        _ban.add(m)
except (OSError, ValueError):
    _ban_raw, _ban = {}, set()
# СЦЕНЫ-КАРТОЧКИ ИЗ СВЕРКИ ИСКЛЮЧЕНЫ (04.11, улов `usuario-af`). Облако
# кладёт всем сценам `card:*` ОДНУ И ТУ ЖЕ заглушку ~34 КБ до прогона
# `cards_cloud.py`. Кто-то её однажды забанил — и предупреждение «забаненный
# кадр в сборке» стало всплывать на каждой карточной сцене каждого ролика.
# Это ложная тревога: карточку рисуем мы сами, бан-лист к ней отношения не
# имеет.
_card_sids = {int(s["id"]) for s in scenes
              if str(s.get("source", "")).startswith("card")}


def _sid_of(path):
    import re as _re2
    m = _re2.search(r"scene_(\d+)", os.path.basename(path))
    return int(m.group(1)) if m else -1


# УБРАННОЕ ИЗ БАЗЫ ПО КЛЕЙМУ АПСКЕЙЛЕРА — ТОТ ЖЕ ПОСЛЕДНИЙ РУБЕЖ (04.11,
# предложение `usuario-af`, подтверждённое живым случаем в тот же час).
# Кадры с замощённым «Magnific» убираются из базы в `_БРАК-апскейлер`, но
# вкладка, зафетчившая кадр ДО уборки, уже держит его у себя и узнает об
# этом только от пользователя. Сверка по md5 стоит секунды и ловит то, чего
# не видно на контактном листе. Живой случай: `ЛЮДИ-ОФИСЕ-МОНИТОРАМИ__05`
# стоял в сцене 44 готового набора.
_wm_dir = os.environ.get("VIDEORYAD_UPSCALED_DIR") or "/mnt/d/media-library/_БРАК-апскейлер"
_wm = {}
try:
    for _f in sorted(glob.glob(os.path.join(_wm_dir, "*"))):
        if os.path.isfile(_f):
            _wm[hashlib.md5(open(_f, "rb").read()).hexdigest()] = os.path.basename(_f)
except OSError:
    _wm = {}

if _ban or _wm:
    _checked = 0
    for _p in sorted(glob.glob(f"{images}/scene_*.*") + glob.glob("overlays/scene_*.*")):
        if _p.endswith((".json", ".revframe.jpg", ".ovthumb.jpg") + TMP_SUFFIX):
            continue
        if _sid_of(_p) in _card_sids:
            continue
        try:
            _h = hashlib.md5(open(_p, "rb").read()).hexdigest()
        except OSError:
            continue
        _checked += 1
        if _h in _ban:
            _why = (_ban_raw.get(_h) or {}).get("reason", "")
            FAIL.append(f"ЗАБАНЕННЫЙ КАДР В СБОРКЕ: {_p} (md5 {_h[:10]}) — "
                        f"бан от {(_ban_raw.get(_h) or {}).get('date','?')}: {_why or 'без причины'}. "
                        f"Заменить до сборки.")
        if _h in _wm:
            FAIL.append(f"КАДР С КЛЕЙМОМ АПСКЕЙЛЕРА В СБОРКЕ: {_p} — это "
                        f"{_wm[_h]}, убранный из базы. На контактном листе "
                        f"клеймо не видно, в готовом файле видно. Заменить "
                        f"рефетчем из той же папки.")
    print(f"[selfcheck] сверка с бан-листом: {_checked} файлов против "
          f"{len(_ban)} активных банов и {len(_wm)} убранных по клейму"
          + (f" (сцены-карточки пропущены: {len(_card_sids)})" if _card_sids else ""))

# 6. сцена 1 = видео — БЫЛО hard FAIL, РАЗЖАЛОВАНО В WARN (user, 2026-10-08,
# зло: "исключаем из правила первый кадр видео... топчетесь на одном месте и
# какую-то ерунду явную подсовываете" — после того как search-only канал
# (5 МИНУТ) не смог найти реальное видео конкретного события ни с одной
# формулировкой запроса, и единственной альтернативой жёсткому гейту было
# либо нерелевантный сток, либо AI-фабрикация). Правило "видео лучше, если
# есть осмысленное" остаётся советом (см. ниже), но больше не блокер.
any_video = any(a and a[0].endswith((".mp4", ".mov")) for a in (asset(i) for i in ids))
a1 = asset(ids[0])
if a1 and not a1[0].endswith((".mp4", ".mov")):
    if any_video:
        WARN.append(f"сцена {ids[0]} не видео (было бы по старому правилу видео-лида, "
                    "но правило сцена-1=видео отменено 2026-10-08 — это не блокер)")
    else:
        WARN.append("во всём ролике нет ни одного видео — весь видеоряд из фото (Ken Burns). "
                    "Ок для канала на поиске-только; для ПЛАНЕТЫ так быть не должно.")

# 6-бис. НА НАШИХ ЭЛЕМЕНТАХ СЛОЁВ НЕ БЫВАЕТ — ЖЁСТКИЙ ОТКАЗ (09.11, его
# прямое слово, дважды за полчаса, второй раз с требованием «зашей в память и
# в скиллы, зашей жёстким правилом»: «На наших элементах не должны быть ни
# надписей, ни всплывашек… там уже всё есть, там полный цикл законченный
# всего, там не надо ничего больше иллюстрировать»).
#
# Правило держалось с 06.11 и всё равно доезжало до его глаз: проверок было
# ДВЕ (эта и в разделе 4), обе частичные — одна смотрела только всплывашки и
# только при живом `overlays.json`, другая не знала про надпись из-под маски.
# Теперь ОДНА, и она же — в `cloud/ship.sh` перед полной сборкой. Список
# видов слоёв, граница «наложение против содержания элемента» и текст отказа
# живут в `template/cards_queue.py` (`слои_на_карточках`, `отказ_слои`).
#
# ЧТО ИМЕННО ЗАПРЕЩЕНО: наложения ПОВЕРХ рисованного кадра — надпись, надпись
# из-под маски, фото-всплывашка, переход/эффект `fx`, блик с пылинками,
# видео-врезка. ЧТО НЕ ТРОГАЕМ: текст ВНУТРИ элемента (реплика цитаты-сплита,
# числа в `pie`/`bars`/`slider`/`map`, тезисы в `pull`/`wall`/`poster`, строки
# в `dossier`) — это и есть содержание карточки, без него она пустая плашка.
# Поэтому гейт смотрит на `overlays.json` и поле `fx`, а в задание карточки не
# заглядывает вовсе.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cards_queue as _cq
    _наруш = _cq.слои_на_карточках(scenes, None, ".")
    if _наруш:
        FAIL.append(_cq.отказ_слои(_наруш))
except Exception as _e:
    WARN.append("не проверить слои на рисованных кадрах (%s: %s) — посмотри "
                "`template/cards_queue.py`" % (type(_e).__name__, _e))

# 7. ОБЯЗАТЕЛЬНЫЕ ЭЛЕМЕНТЫ (06.11, его прямое слово: «сделать эти элементы
# обязательными при сборке»). Список один на все гейты и лежит отдельно —
# `template/obyazatelno.py`; здесь только гейт ДАШБОРДА. Перед полной сборкой
# тот же список спрашивает `cloud/ship.sh`, с гейтом `video`.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import obyazatelno as _ob
    # путь к сценам нужен элементам-НАДПИСЯМ: они живут в `overlays.json`
    # рядом, а не в `scenes.json` (07.11, надпись из-под маски)
    for _b in _ob.check(scenes, str(meta.get("channel", "")), "dashboard",
                        scenes_path):
        FAIL.append(_b)
except Exception as _e:                  # список не прочитался — скажем вслух
    WARN.append("не проверить обязательные элементы (%s: %s) — посмотри "
                "`template/obyazatelno.py`" % (type(_e).__name__, _e))

print("=" * 60)
print(f"САМОПРОВЕРКА: {scenes_path}  ({len(scenes)} сцен, {total:.0f}с, канал {meta.get('channel','?')})")
print("=" * 60)
if WARN:
    print("\n⚠ ПРЕДУПРЕЖДЕНИЯ:")
    for w in WARN:
        print("  -", w)
if FAIL:
    print(f"\n❌ НАРУШЕНИЙ: {len(FAIL)} — чинить ДО отдачи дашборда:")
    for x in FAIL:
        print("  -", x)
    sys.exit(1)
print("\n✅ всё чисто — дашборд можно отдавать")
