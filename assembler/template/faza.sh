#!/usr/bin/env bash
# ФАЗА — одна команда вместо десятков шагов переписки (09.11.2026).
#
#   bash template/faza.sh final   <проект>
#   bash template/faza.sh fetch   <проект> <труба> [nm-очереди]
#   bash template/faza.sh krug    <проект> <сцены через запятую>
#   bash template/faza.sh sdacha  <проект> <nm-очереди> <труба> "<папка на D:>"
#
# Зачем: расход токенов = ЧИСЛО ШАГОВ × РАЗМЕР ПЕРЕПИСКИ. Замер 09.11 дал 325
# шагов на ролик, из них 52 — опрос облака «не готово ли» и десятки поштучных
# вызовов одного и того же инструмента. Фаза делает всю последовательность
# внутри ОДНОГО шага: подробности уходят в `<проект>/.faza-<nm>.log`,
# в переписку печатается summary по строке на под-step.
#
# Договор вывода (его же читает монитор): каждая строка итога начинается с
# `[ОК]` или `[ОТКАЗ]`; падение фазы печатает `ОШИБКА:` и возвращает rc 1.
# Признаком готовности считается РЕЗУЛЬТАТ (файл, строка в логе), а не статус
# прогона и не rc возврата обёртки.
# ВНИМАНИЕ: имена переменных и функций ТОЛЬКО латиницей — bash отвергает
# кириллические идентификаторы («not a valid identifier»), поймано 09.11.
set -uo pipefail
SK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$SK/template"
FAZA="${1:-}"; shift || true
PROJ="${1:-}"; shift || true
[ -n "$FAZA" ] && [ -n "$PROJ" ] || { echo "ОШИБКА: faza.sh <final|fetch|krug|sdacha> <проект> …"; exit 1; }
if [ "$FAZA" = "tema" ] || [ "$FAZA" = "start" ]; then
    # здесь второй аргумент — КАНАЛ (tema) или ключ георадара (start)
    CHANNEL="$PROJ"; PROJ="$HOME/projects"
else
    [ -d "$PROJ" ] || { echo "ОШИБКА: папки проекта нет: $PROJ"; exit 1; }
    PROJ="$(cd "$PROJ" && pwd)"
fi
LOG="$PROJ/.faza-$FAZA.log"
# ФАЗЫ `start` И `tema` РАБОТАЮТ ДО СОЗДАНИЯ ПРОЕКТА, и PROJ у них — ОБЩИЙ
# `~/projects`. Общий лог каждая вкладка обнуляла на входе, и причина чужого
# провала терялась (10.11: почему не заказалась вторая статья — выяснилось
# только разбором кода). Поэтому у них лог СВОЙ, по номеру процесса.
if [ "$FAZA" = "tema" ] || [ "$FAZA" = "start" ]; then
    LOG="$PROJ/.faza-$FAZA-$$.log"
fi
: > "$LOG"
# СЦЕНАРИЙ — ТОЛЬКО ПРИНЯТЫЙ ФАЙЛ ПРОЕКТА (10.11, улов `usuario-d3`,
# полчаса потерь). Под глоб `*.scenes.json` попадал и СЫРОЙ ответ агента
# `codex.scenes.json`: фаза молча линтовала его вместо принятого и упорно
# отказывала по досье (59 поисковых сцен против 50), хотя `dossier_use`
# на принятом файле отвечал «чисто». Сначала ищем `<имя проекта>.scenes.json`,
# и только если его нет — любой другой, но сырые файлы агента не берём.
SCENES="$PROJ/$(basename "$PROJ").scenes.json"
if [ ! -f "$SCENES" ]; then
  SCENES="$(ls "$PROJ"/*.scenes.json 2>/dev/null \
            | grep -v iz_oblaka | grep -v '/codex\.' | head -1)"
fi
[ -f "$SCENES" ] || SCENES=""
FAILED=0
NOTES=0

# step <nm> <команда…> — вывод в лог; в переписку: вердикт, число замечаний и
# до трёх САМЫХ ЗНАЧИМЫХ строк. Код 0 ещё НЕ значит «чисто»: selfcheck и
# photo_quality печатают находки и выходят нулём (поймано 09.11 на первом же
# прогоне: «[ОК] selfcheck» спрятал в лог фантомное approved и две неверные
# надписи). Решает не код возврата, а найденное в выводе.
MARK='ОШИБКА|ОТКАЗ|ЗАПРЕТ|!!|НЕ ВЫТЯНУТА|ФАНТОМ|ПОСМОТРЕТЬ ГЛАЗАМИ|подозрит|ИСЧЕРПАНА|не совпал|битый|НЕ НАЙДЕН|лишн'
step() {
    local nm="$1"; shift
    local out; out="$(mktemp)"
    echo "=== $nm: $* ===" >> "$LOG"
    local rc=0
    "$@" > "$out" 2>&1 || rc=$?
    cat "$out" >> "$LOG"
    # строки-«всё хорошо» под маску не идут: «подозрительных нет», «повторов нет»
    local n; n="$(grep -E "$MARK" "$out" 2>/dev/null | grep -cvE "(нет|чисто|ровное|не найдено)\s*$|ых нет" || true)"
    [ -n "$n" ] || n=0
    if [ "$rc" -ne 0 ]; then
        echo "[ОТКАЗ] $nm (код $rc)"
        grep -hE "$MARK" "$out" | grep -vE "(нет|чисто|ровное|не найдено)\s*$|ых нет" | head -3 | cut -c1-200 | sed 's/^[ \t-]*/        · /'
        FAILED=$((FAILED+1))
    elif [ "$n" -gt 0 ]; then
        echo "[СМОТРИ] $nm — замечаний $n:"
        grep -hE "$MARK" "$out" | grep -vE "(нет|чисто|ровное|не найдено)\s*$|ых нет" | head -3 | cut -c1-200 | sed 's/^[ \t-]*/        · /'
        NOTES=$((NOTES+n))
    else
        echo "[ОК]    $nm"
    fi
    rm -f "$out"
    return 0
}

# pick_pipe <проект> — свободная труба + ЗАМОК на неё. Без замка две вкладки,
# стартовавшие в одну минуту, получали ОДНУ трубу: `gh run list` показывает
# «completed» у обеих, пока ни одна ещё не запушила (поймано 09.11 на проверке).
# Замок — каталог (атомарный mkdir) в base/truby/, старше 4 часов считается
# брошенным. Освобождает `faza.sh sdacha` или `free_pipe`.
LOCKS="$SK/base/truby"
pick_pipe() {
    local proj="$1" pp st
    mkdir -p "$LOCKS"
    for pp in cptand-pub andiv-pub olga-pub pyat shest rezerv; do
        if [ -d "$LOCKS/$pp" ]; then
            local age=$(( ( $(date +%s) - $(stat -c %Y "$LOCKS/$pp") ) / 60 ))
            if [ "$age" -lt 240 ]; then continue; fi
            rm -rf "$LOCKS/$pp"
        fi
        st="$(bash "$SK/cloud/va.sh" "$pp" gh run list --workflow videoryad-cloud.yml --limit 1 2>/dev/null | head -1 | cut -f1)"
        [ "$st" = "completed" ] || continue
        if mkdir "$LOCKS/$pp" 2>/dev/null; then
            echo "$proj" > "$LOCKS/$pp/kto"
            echo "$pp"; return 0
        fi
    done
    return 1
}
free_pipe() {
    local pp="$1"
    [ -n "$pp" ] && rm -rf "$LOCKS/$pp" 2>/dev/null
}

# wait_pipe <проект> <минут> — ждать СВОБОДНУЮ трубу внутри одного шага.
# Труб шесть, значит одновременно в полёте шесть роликов; седьмая вкладка не
# должна падать — она ждёт, пока кто-то сдаст и освободит замок (его сценарий
# 09.11: три статьи × два канала = шесть вкладок за полтора часа).
wait_pipe() {
    local proj="$1" mins="${2:-90}" pp
    local deadline=$(( $(date +%s) + mins*60 )) said=0
    while :; do
        pp="$(pick_pipe "$proj" || true)"
        [ -n "$pp" ] && { echo "$pp"; return 0; }
        if [ "$(date +%s)" -ge "$deadline" ]; then return 1; fi
        [ "$said" -eq 0 ] && { echo "·· все шесть труб заняты — жду свободную, проверяю каждые 60 с" >&2; said=1; }
        sleep 60
    done
}

# kill_dash <папка проекта> — погасить ДАШБОРД ЭТОГО ролика и только его.
# Различать дашборды можно ТОЛЬКО по рабочей папке процесса: у разных роликов
# одного канала файл сцен называется одинаково, и `pgrep -f` возвращает чужие
# pid (правило из памяти, 22.10). Шесть дашбордов разом — это 250 МБ, но
# держать сданные незачем.
kill_dash() {
    local proj="$1" pid cwd n=0
    for pid in $(pgrep -f "review\.py" 2>/dev/null); do
        cwd="$(readlink -f /proc/$pid/cwd 2>/dev/null || true)"
        [ "$cwd" = "$proj" ] || continue
        kill "$pid" 2>/dev/null && n=$((n+1))
    done
    [ "$n" -gt 0 ] && echo "[ОК]    дашборд этого ролика погашен ($n процесс)"
    return 0
}

# mem_check <что собираемся делать> — предупредить, если памяти в обрез.
# На машине 7,9 ГБ: семь сессий Claude (~370-450 МБ каждая) + шесть дашбордов
# (40 МБ) + сторож и упаковка (65 МБ) ≈ 3,6 ГБ. Внешний агент добавляет до
# полутора гигабайт разом — вот при нём и упираемся.
mem_check() {
    local free_mb; free_mb="$(free -m | awk '/^Mem:/{print $7}')"
    if [ "${free_mb:-9999}" -lt 900 ]; then
        echo "[СМОТРИ] памяти свободно ${free_mb} МБ — перед «$1» погаси дашборды сданных роликов (cloud/dash.sh) и не зови внешнего агента параллельно"
        NOTES=$((NOTES+1))
    fi
}

# gotovyy_mp4 <папка> — путь к ГОТОВОМУ ролику, если он СВЕЖЕЕ исходников.
# Зачем (11.11): `faza.sh sdacha` начиналась с полной сборки всегда, и вкладка,
# повторившая фазу после чистки забора, снова ждала облако семь минут на уже
# готовом файле. Свежесть решает mtime: правили сцены, слои, субтитры или кадры
# ПОСЛЕ сборки — собирать заново; не правили — файл тот самый, идём к доставке.
# Принудительно пересобрать: VIDEORYAD_SDACHA_REBUILD=1.
gotovyy_mp4() {
    local d="$1" mp4 t_mp4 t_src t f
    mp4="$(ls -S "$d"/*.mp4 2>/dev/null | head -1)"
    [ -n "$mp4" ] || return 1
    t_mp4="$(stat -c %Y "$mp4" 2>/dev/null || echo 0)"
    t_src=0
    for f in "$d"/*.scenes.json "$d/overlays.json" "$d/captions.ass" \
             $(ls -t "$d/images"/* 2>/dev/null | head -1); do
        [ -f "$f" ] || continue
        t="$(stat -c %Y "$f" 2>/dev/null || echo 0)"
        [ "$t" -gt "$t_src" ] && t_src="$t"
    done
    [ "$t_mp4" -ge "$t_src" ] || return 1
    echo "$mp4"
}

summary() {
    echo "--------------------------------------------------------------"
    if [ "$FAILED" -eq 0 ]; then
        if [ "$NOTES" -gt 0 ]; then
            echo "ИТОГ фазы $FAZA: отказов нет, но ЗАМЕЧАНИЙ $NOTES — разобрать до дашборда. Лог: $LOG"
        else
            echo "ИТОГ фазы $FAZA: чисто. Подробности: $LOG"
        fi
    else
        echo "ИТОГ фазы $FAZA: ОТКАЗОВ $FAILED — читай $LOG (grep -nE 'ОШИБКА|ОТКАЗ|!!')"
    fi
    [ "$FAILED" -eq 0 ] || return 1
}

case "$FAZA" in

# ---------------------------------------------------------------- КЛОН
# ТРЕТИЙ ЭКЗЕМПЛЯР ТЕМЫ СОБИРАЕТСЯ ПОЧТИ МГНОВЕННО (11.11, его слово:
# «у них есть два источника для дашборда — Планета и 5 минут; добить туда
# 10-15-20% нового — элементарно, и тут же отсылать на сборку без
# утверждения… ну не 3,5 часа делать, дольше, чем с нуля»).
# Один ход вместо шести фаз: кадры донора → фетч ТОЛЬКО по остатку →
# машинные сита → полная сборка. Дашборд НЕ поднимается: клон идёт без
# утверждения, он собран из кадров, которые он уже видел и утвердил вчера.
klon)
    [ -n "$SCENES" ] || { echo "ОШИБКА: не нашёл <проект>.scenes.json в $PROJ"; exit 1; }
    cd "$PROJ" || exit 1
    PIPE="${1:-}"; QNAME="${2:-$(basename "$PROJ")}"
    step "кадры донора"     python3 "$T/kadry_klon.py" "$SCENES"
    _NADO=$(python3 - "$SCENES" <<'PYK'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
sc = d.get("scenes", d) if isinstance(d, dict) else d
print(sum(1 for s in sc if str(s.get("source", "")) not in ("local_donor",)
          and not str(s.get("source", "")).startswith("card")))
PYK
)
    echo "[ОК]    осталось искать: $_NADO сцен из $(python3 -c "
import json,sys
d=json.load(open('$SCENES',encoding='utf-8')); sc=d.get('scenes',d) if isinstance(d,dict) else d
print(len(sc))")"
    if [ "${_NADO:-0}" -gt 0 ]; then
        if [ -z "$PIPE" ] || [ "$PIPE" = "--wait" ]; then
            PIPE="$(wait_pipe "$PROJ" 90 || true)"
            [ -n "$PIPE" ] || { echo "ОШИБКА: за 90 мин ни одна труба не освободилась"; exit 1; }
            echo "[ОК]    труба: $PIPE (взята замком)"
        fi
        step "фетч остатка"  bash "$SK/cloud/va.sh" "$PIPE" bash "$SK/cloud/ship.sh" "$PROJ" "$QNAME" --fetch-only
        step "забор"         bash "$SK/cloud/va.sh" "$PIPE" bash "$SK/cloud/get.sh" "$QNAME" --wait-fetch
    else
        echo "[ОК]    фетч не нужен вовсе — все сцены закрыты кадрами доноров"
    fi
    step "selfcheck"        python3 "$T/selfcheck.py" "$SCENES" images
    step "обязательные"     python3 "$T/obyazatelno.py" "$SCENES" --gate dashboard
    step "повтор кадров"    python3 "$T/povtor_kadrov.py" "$PROJ"
    step "гейт детей"       python3 "$T/deti_gate.py" check "$PROJ"
    echo ""
    echo "ДАЛЬШЕ: дашборд НЕ поднимаем (клон идёт без утверждения) —"
    echo "  bash $0 sdacha $QNAME ${PIPE:-<труба>} \"<папка темы на D:>\""
    summary
    ;;

# ---------------------------------------------------------------- ФИНАЛ
# Все машинные сита подряд. Раньше это 8-11 отдельных шагов переписки.
final)
    [ -n "$SCENES" ] || { echo "ОШИБКА: не нашёл <проект>.scenes.json в $PROJ"; exit 1; }
    cd "$PROJ" || exit 1
    step "selfcheck"        python3 "$T/selfcheck.py" "$SCENES" images
    step "обязательные"     python3 "$T/obyazatelno.py" "$SCENES" --gate dashboard
    step "слои на карточках" python3 "$T/cards_queue.py" --gate "$SCENES" "$PROJ"
    step "дедуп"            python3 "$T/autodedup.py" "$SCENES" images
    step "повтор кадров"    python3 "$T/povtor_kadrov.py" "$PROJ"
    step "качество фото"    python3 "$T/photo_quality.py" "$SCENES" images
    step "клейма (лист)"    python3 "$T/wm_sheet.py" images
    step "перекрытие слоёв" python3 "$T/check_overlay_overlap.py" "$PROJ"
    summary
    ;;

# ---------------------------------------------------------------- ФЕТЧ
# ship --fetch-only + ОЖИДАНИЕ ВНУТРИ ШАГА (get.sh --wait-fetch) + забор.
# Раньше: отправка, затем 15-30 опросов `gh run view` из переписки.
fetch)
    mem_check "fetch"
    PIPE="${1:-}"; QNAME="${2:-$(basename "$PROJ")}"
    if [ -z "$PIPE" ] || [ "$PIPE" = "--wait" ]; then
        # трубу не назвали — берём свободную сами и ЖДЁМ её, если все заняты
        PIPE="$(wait_pipe "$PROJ" 90 || true)"
        [ -n "$PIPE" ] || { echo "ОШИБКА: за 90 мин ни одна из шести труб не освободилась"; exit 1; }
        echo "[ОК]    труба: $PIPE (взята замком)"
    fi
    step "отправка фетча"   bash "$SK/cloud/va.sh" "$PIPE" bash "$SK/cloud/ship.sh" "$PROJ" "$QNAME" --fetch-only
    if [ "$FAILED" -eq 0 ]; then
        step "ожидание и забор" bash "$SK/cloud/va.sh" "$PIPE" bash "$SK/cloud/get.sh" "$QNAME" --wait-fetch
    fi
    # ПРИЗНАК РЕЗУЛЬТАТА — ФАЙЛЫ, А НЕ СТАТУС ПРОГОНА. СЧИТАТЬ ТАМ, КУДА
    # ЗАБОР РЕАЛЬНО ЛЁГ (11.11): `get.sh` кладёт его в
    # `~/projects/<имя очереди>-cloud`, а счётчик смотрел только в
    # `$PROJ/images` — и на каждом ролике, который ведётся из папки забора,
    # печаталось «кадров в images: 0» при живом фетче. Ложная тревога на
    # каждом ролике с суффиксом `-cloud`. Берём папку с НАИБОЛЬШИМ числом
    # кадров из четырёх возможных.
    NFRAMES=0; IMGDIR="$PROJ/images"
    for d in "$PROJ" "$PROJ-cloud" "$HOME/projects/$QNAME-cloud" "${PROJ%-cloud}"; do
        [ -d "$d/images" ] || continue
        n=$(ls "$d/images"/scene_*.jpg "$d/images"/scene_*.mp4 2>/dev/null | wc -l)
        [ "$n" -gt "$NFRAMES" ] && { NFRAMES="$n"; IMGDIR="$d/images"; }
    done
    echo "[ОК]    кадров: $NFRAMES ($IMGDIR)"
    [ "$NFRAMES" -gt 0 ] || { echo "ОШИБКА: фетч не принёс ни одного кадра — смотри $LOG"; FAILED=$((FAILED+1)); }
    # «КАДРОВ 63» ≠ «63 КАДРА» (12.11, улов `usuario-e3`, класс «успех значит
    # ничего не сделано»). Фаза считала НАЛИЧИЕ файла, а 40 из 63 оказались
    # тёмными облачными заглушками на 33 КБ: все 16 библиотечных сцен облако
    # закрыть физически не может (медиатека на D:), плюс мёртвые к моменту
    # прогона адреса телеграма. Ловим той же яркостью, что `cards_cloud`.
    python3 - "$IMGDIR" <<'PYZ' || true
import glob, os, sys
кат = sys.argv[1]
пусто = []
for f in sorted(glob.glob(os.path.join(кат, "scene_*.jpg"))):
    try:
        if os.path.getsize(f) > 60000:
            continue
        from PIL import Image, ImageStat
        if ImageStat.Stat(Image.open(f).convert("L")).mean[0] < 45:
            пусто.append(os.path.basename(f))
    except Exception:
        continue
if пусто:
    print("[СМОТРИ] ЗАГЛУШЕК ВМЕСТО КАДРОВ: %d — %s"
          % (len(пусто), ", ".join(пусто[:12]) + (" …" if len(пусто) > 12 else "")))
    print("         Библиотечные сцены облако не закрывает (медиатека на D:) —")
    print("         добери локально: python3 ~/.claude/skills/news-video/template/"
          "fetch_parallel.py <ролик>.scenes.json images "
          "~/.claude/skills/news-video/template/.env 5")
    print("         Умершие адреса телеграма: прогнать tg_media.py заново —")
    print("         токены новые, файлы те же.")
else:
    print("[ОК]    заглушек среди кадров нет (проверено яркостью)")
PYZ
    summary
    ;;

# ---------------------------------------------------------------- КРУГ ПРАВОК
# Замены ПАЧКОЙ из запаса кандидатов + кроп углов по каждому новому файлу +
# три машинных сита. Раньше: refetch по одной сцене, ban_file по одному файлу,
# zoom по одному кадру — 20-30 шагов.
krug)
    SIDS="${1:-}"
    [ -n "$SIDS" ] || { echo "ОШИБКА: faza.sh krug <проект> <сцены через запятую>"; exit 1; }
    [ -n "$SCENES" ] || { echo "ОШИБКА: не нашёл <проект>.scenes.json"; exit 1; }
    cd "$PROJ" || exit 1
    # ИСЧЕРПАННЫЙ ЗАПАС — НЕ ОШИБКА ФАЗЫ (11.11). `refetch.py --next` отвечает
    # кодом 1, когда НИ ОДНОЙ замены взять не удалось, а у сцен из поиска
    # запаса кандидатов нет по устройству. Фаза печатала «[ОТКАЗ] замена из
    # запаса» и валилась целиком — выглядело как поломка круга, хотя лечение
    # другое и известное: переписать запрос и сходить за кадром в облако.
    ZOUT="$(mktemp)"
    python3 "$T/refetch.py" --scenes "$SCENES" --next "$SIDS" > "$ZOUT" 2>&1; ZRC=$?
    echo "=== замена из запаса ===" >> "$LOG"; cat "$ZOUT" >> "$LOG"
    if [ "$ZRC" -eq 0 ]; then
        echo "[ОК]    замена из запаса"
    elif grep -q "ИТОГ ПО ДИСКУ: заменено из запаса" "$ZOUT"; then
        echo "[ОК]    ЗАПАС ИСЧЕРПАН — это не поломка круга:"
        grep -h "запаса нет у сцен" "$ZOUT" | head -1 | cut -c1-200 | sed 's/^[ \t]*/        · /'
        echo "        · лечение: ПЕРЕПИСАТЬ запрос этих сцен (субъект в запросе!)"
        echo "          и сходить за кадром в облако: faza.sh fetch <проект> <труба>"
        echo "          (ship.sh --fetch-only), запас на диске тут уже не поможет"
        NOTES=$((NOTES+1))
    else
        echo "[ОТКАЗ] замена из запаса (код $ZRC)"
        grep -hE "$MARK" "$ZOUT" | head -3 | cut -c1-200 | sed 's/^[ \t-]*/        · /'
        FAILED=$((FAILED+1))
    fi
    rm -f "$ZOUT"
    # кроп углов обязателен по КАЖДОМУ новому файлу (улов 28.10), пачкой
    for s in ${SIDS//,/ }; do
        fb=$(printf "%s/images/scene_%03d" "$PROJ" "$s")
        for e in jpg mp4; do
            [ -f "$fb.$e" ] && step "углы scene_$s.$e" python3 "$T/zoom.py" "$fb.$e" --corners
        done
    done
    step "клейма (лист)"    python3 "$T/wm_sheet.py" images
    step "качество фото"    python3 "$T/photo_quality.py" "$SCENES" images
    step "selfcheck"        python3 "$T/selfcheck.py" "$SCENES" images
    summary
    ;;

# ---------------------------------------------------------------- СДАЧА
# Субтитры → полная сборка → ожидание → забор → проверка по ГОТОВОМУ файлу →
# доставка dd + сверка хэша → оповещение → отметка в реестре.
sdacha)
    mem_check "sdacha"
    QNAME="${1:-}"; PIPE="${2:-}"; DEST="${3:-}"
    [ -n "$QNAME" ] && [ -n "$PIPE" ] && [ -n "$DEST" ] || { echo "ОШИБКА: faza.sh sdacha <проект> <имя> <труба> \"<папка на D:>\""; exit 1; }
    [ -d "$DEST" ] || { echo "ОШИБКА: папки доставки нет: $DEST"; exit 1; }
    cd "$PROJ" || exit 1
    # СДАЧА НЕ НАЧИНАЕТСЯ СО СБОРКИ, ЕСЛИ ГОТОВЫЙ ФАЙЛ УЖЕ ЛЕЖИТ (11.11).
    # Два случая за смену: вкладка повторяла `sdacha` на СВОЁМ ЖЕ собранном
    # ролике — уходила вторая полная сборка и семь минут ожидания, а вердикт
    # гейта детей к тому моменту уносила чистка забора, и фаза печатала
    # «ПРОВЕРКА ДЕТИ НЕ ПРОЙДЕНА — СБОРКУ ДЕРЖУ» на уже доставленном ролике.
    READY=""
    if [ "${VIDEORYAD_SDACHA_REBUILD:-0}" != "1" ]; then
        READY="$(gotovyy_mp4 "$PROJ" || true)"
    fi
    if [ -n "$READY" ]; then
        echo "[ОК]    готовый файл уже собран и свежее сцен/слоёв — сборку пропускаю"
        echo "        ($(basename "$READY"); пересобрать принудительно: VIDEORYAD_SDACHA_REBUILD=1)"
    else
        step "полная сборка"  bash "$SK/cloud/va.sh" "$PIPE" bash "$SK/cloud/ship.sh" "$PROJ" "$QNAME"
        if [ "$FAILED" -eq 0 ]; then
            step "ожидание и забор" bash "$SK/cloud/va.sh" "$PIPE" bash "$SK/cloud/get.sh" "$QNAME" --wait
        fi
        READY="$(ls -S "$PROJ"/*.mp4 2>/dev/null | head -1)"
    fi
    if [ -z "$READY" ]; then
        echo "ОШИБКА: готового .mp4 в проекте нет — сборка не доехала, смотри $LOG"
        FAILED=$((FAILED+1)); summary; exit 1
    fi
    echo "[ОК]    готовый файл: $(basename "$READY") ($(du -m "$READY" | cut -f1) МБ)"
    [ -n "$SCENES" ] && step "сито по готовому" python3 "$T/final_sheet.py" "$READY" --scenes "$SCENES"
    # ФОНОВАЯ МУЗЫКА — ТОЛЬКО НА ПЛАНЕТЕ (11.11, его заказ и четыре пробы на
    # слух: 20% → 40% → 10% от голоса → 40% → 50%, принято последнее, ≈2%).
    # Два трека подряд и по кругу через весь ролик, в конце 10 с затухания до
    # нуля. Считается ЛОКАЛЬНО: треки лежат на `D:`, раннер их не видит, а
    # везти чужую музыку в публичный репозиторий незачем. Видео не
    # перекодируется (`-c:v copy`), на 13 минутах это ~30 с.
    # Инструмент сам отказывается работать на любом канале, кроме ПЛАНЕТЫ, —
    # проверка канала не дублируется здесь.
    # ПРОВАЛ МУЗЫКИ НАЗЫВАЕТСЯ ВСЛУХ (12.11). Было: `if ... ; fi` без ветки
    # отказа — не нашлись треки на `D:` или упал ffmpeg, и ролик ПЛАНЕТЫ
    # уезжал БЕЗ МУЗЫКИ молча, с рапортом «сдано». Код 0 на чужом канале —
    # это норма (инструмент сам отказывается и файла не делает), а код ≠ 0
    # бывает ТОЛЬКО на ПЛАНЕТЕ и значит потерянную музыку.
    _MUZ_OUT="${READY%.mp4} С МУЗЫКОЙ.mp4"
    python3 "$T/muzyka.py" "$READY" --out "$_MUZ_OUT" >> "$LOG" 2>&1; _MUZRC=$?
    if [ "$_MUZRC" -eq 0 ] && [ -s "$_MUZ_OUT" ]; then
        echo "[ОК]    фоновая музыка ПЛАНЕТЫ наложена"
        READY="$_MUZ_OUT"
    elif [ "$_MUZRC" -ne 0 ]; then
        echo "[ОТКАЗ] МУЗЫКА НЕ ЛЕГЛА (код $_MUZRC). Это ПЛАНЕТА — без музыки"
        echo "        ролик не сдаём. Хвост журнала: tail -40 $LOG"
        FAILED=$((FAILED+1))
    fi
    TARGET="$DEST/$(basename "$READY")"
    step "доставка dd" dd if="$READY" of="$TARGET" bs=1M conv=fsync status=none
    A=$(md5sum "$READY" | cut -d' ' -f1); B=$(md5sum "$TARGET" 2>/dev/null | cut -d' ' -f1)
    if [ "$A" = "$B" ] && [ -n "$B" ]; then
        echo "[ОК]    хэш совпал · на диске $(du -m "$TARGET" | cut -f1) МБ"
        # ПОВОД ПИШЕТСЯ СЛОВАМИ, А НЕ КЛЮЧОМ (10.11, улов `usuario-d3`):
        # гейт `notify.sh` ищет повод ГРЕПОМ ПО ВСЕЙ СТРОКЕ, слова «video» в
        # его списке нет — и штатная сдача через фазу оповещение НЕ отправляла
        # вовсе, хотя пользователь ждёт пузырь именно на этот повод.
        bash "$SK/cloud/notify.sh" "видеоряд лёг на диск D:" "$TARGET" >> "$LOG" 2>&1 \
            && echo "[ОК]    оповещение ушло" || echo "[ОТКАЗ] оповещение не ушло (см. лог)"
        python3 "$T/zanyato.py" --sdat --iz-proekta "$PROJ" >> "$LOG" 2>&1 \
            && echo "[ОК]    тема отмечена сданной" || echo "[ОТКАЗ] реестр не отметил"
        free_pipe "$PIPE"
        echo "[ОК]    труба $PIPE освобождена"
        # СНИМАЕМ И ЛЮБОЙ ДРУГОЙ ЗАМОК ЭТОГО ПРОЕКТА (11.11,
        # `НА-РАСКАТКУ` п.13). Замок помнит, КТО его взял, — а `sdacha`
        # снимала только трубу из аргумента. Ролик, у которого круг шёл по
        # одной трубе, а сборка по другой, оставлял первый замок висеть:
        # 11.11 так висели `andiv-pub` и `pyat` при сданных роликах, и
        # следующая вкладка считала трубы занятыми, пока замку не стукнет
        # четыре часа.
        for _lk in "$LOCKS"/*/kto; do
            [ -f "$_lk" ] || continue
            if [ "$(cat "$_lk" 2>/dev/null)" = "$PROJ" ]; then
                _lp="$(basename "$(dirname "$_lk")")"
                [ "$_lp" = "$PIPE" ] && continue
                free_pipe "$_lp"
                echo "[ОК]    снят и прежний замок трубы $_lp (его держал этот же проект)"
            fi
        done
        kill_dash "$PROJ"
    else
        echo "ОШИБКА: хэш НЕ совпал ($A ≠ ${B:-нет файла}) — файл на D: битый"
        FAILED=$((FAILED+1))
    fi
    summary
    ;;

# ---------------------------------------------------------------- СТАРТ ПО КЛЮЧУ
# Он положил текст в папку темы и кинул вкладке ОДИН ключ георадара
# (`PROD_…`/`ARM_…`/`AN_…`). Больше от него ничего не приходит: канал, папка,
# труба и порт выясняются здесь. Его слово 09.11: «скидываю ей вот этот ID
# записи в георадаре, и тогда она его подхватывает и начинает делать».
start)
    KEY="$CHANNEL"   # второй аргумент фазы start — это ключ
    NEWS="${VIDEORYAD_NEWS_DIR:-/mnt/d/YouTube/НОВОСТИ}"
    case "$KEY" in
        PROD_*|ARM_*|AN_*) : ;;
        *) echo "ОШИБКА: это не ключ георадара: '$KEY' (ждём PROD_… / ARM_… / AN_…)"; exit 1;;
    esac
    WAITMIN=45
    # КАНАЛ ВКЛАДКИ — ОБЯЗАТЕЛЕН (10.11, его слово: «Она должна была работать
    # на канал Планета, а не на канал 5 минут. Я же все пометил, все вкладки
    # подписал»). До этой правки `start` брал САМУЮ СВЕЖУЮ СВОБОДНУЮ тему ПО
    # ВСЕМ КАНАЛАМ: подпись вкладки код не видел вовсе, и две вкладки менялись
    # каналами просто по тому, кто раньше стартовал. Ключ один на все каналы,
    # поэтому развести их может только канал, названный вслух.
    WANT_CH="${VIDEORYAD_CHANNEL:-}"
    # ТЕМУ НАЗЫВАЕТ ОН, А НЕ КОД (11.11, его прямое слово: «Ты должен был ей
    # раздать последовательно, как я и говорил. Я же последовательно, специально
    # открывал эти вкладки, давал конкретную инструкцию»). До этой правки
    # `start` брал САМУЮ СВЕЖУЮ свободную тему канала по дате файла, и окно,
    # которое он подписал «МОСТЫ», забрало «Лаврова» — просто потому, что текст
    # Лаврова лёг на диск позже. Подпись окна код не видел вовсе.
    WANT_TEMA="${VIDEORYAD_TEMA:-}"
    while [ $# -gt 0 ]; do
        case "${1:-}" in
            --wait) WAITMIN="${2:-45}"; shift 2 || true ;;
            --lyuboy-kanal) WANT_CH="ЛЮБОЙ"; shift ;;
            --tema) WANT_TEMA="${2:-}"; shift 2 || true ;;
            "") shift ;;
            *) if [ -z "$WANT_CH" ]; then WANT_CH="$1"; elif [ -z "$WANT_TEMA" ]; then WANT_TEMA="$1"; fi; shift ;;
        esac
    done
    if [ -z "$WANT_CH" ]; then
        echo "ОШИБКА: не назван КАНАЛ вкладки — без него start уедет на чужой канал."
        echo "  зови так:  faza.sh start $KEY \"ПЛАНЕТА\"   (или \"5 МИНУТ\", \"ДИПЛОМАТИЯ СИЛЫ\" …)"
        echo "  канал пишется ТОЧНО как папка в $NEWS"
        echo "  свободные темы по каналам:"
        python3 - "$NEWS" <<'PYCH'
import glob, os, sys
news = sys.argv[1]
by = {}
for t in glob.glob(os.path.join(news, "*", "*", "[0-3][0-9]-[01][0-9]", "*")):
    if not os.path.isdir(t):
        continue
    if [f for f in glob.glob(os.path.join(t, "*.mp4"))
       if os.path.getsize(f) >= 100 * 1024 * 1024]:
        continue
    txt = [f for f in glob.glob(os.path.join(t, "*.txt"))
           if not any(k in os.path.basename(f) for k in ("ЗАДАНИЕ", "БРИФ", "УПАКОВКА", "ОТВЕТ"))]
    if not txt:
        continue
    ch = t[len(news):].strip(os.sep).split(os.sep)[0]
    by.setdefault(ch, []).append(os.path.basename(t))
for ch in sorted(by):
    print("    %-18s %s" % (ch, ", ".join(sorted(by[ch])[:4])))
PYCH
        echo "  (осознанно взять любой канал: --lyuboy-kanal)"
        exit 1
    fi
    if [ -n "$WANT_TEMA" ]; then
        echo "ключ досье: $KEY · канал: $WANT_CH · ТЕМА НАЗВАНА: $WANT_TEMA · ждать до $WAITMIN мин"
    else
        echo "ключ досье: $KEY · канал вкладки: $WANT_CH · ТЕМА НЕ НАЗВАНА (возьму самую свежую свободную) · ждать до $WAITMIN мин"
        echo "  чтобы взять ИМЕННО свою тему:  faza.sh start $KEY \"$WANT_CH\" --tema \"2-Мосты приказ отдан\""
    fi
    # САМАЯ СВЕЖАЯ тема с текстом по ВСЕМ каналам, кроме сданных и занятых:
    # он кладёт текст прямо перед тем, как кинуть ключ, поэтому свежесть и есть
    # признак «это она».
    DEADLINE=$(( $(date +%s) + WAITMIN*60 ))
    SAID=0
    while :; do
    CAND_LIST="$(python3 - "$NEWS" <<'PYEOF'
import glob, json, os, re, sys
news = sys.argv[1]
rows = []


def _kl(x):
    return re.sub(r"[^а-яёa-z0-9]", "", (x or "").lower())


_REESTR = os.path.expanduser("~/.claude/skills/news-video/base/zanyato.json")
_SDANO = set()
try:
    with open(_REESTR, encoding="utf-8") as _f:
        for _z in (json.load(_f).get("записи") or {}).values():
            if _z.get("состояние") == "сдано" and \
                    (_z.get("работа") or "") == "видеоряд":
                _SDANO.add((_kl(_z.get("канал")), _kl(_z.get("тема")),
                            (_z.get("день") or "").strip()))
except (OSError, ValueError, AttributeError):
    _SDANO = set()        # реестра нет или он битый — сито просто молчит


def _sdano(t):
    ч = os.path.abspath(t).split(os.sep)
    if len(ч) < 4:
        return False
    канал, день, тема = ч[-4], ч[-2], ч[-1]
    return (_kl(канал), _kl(тема), день.strip()) in _SDANO
for t in glob.glob(os.path.join(news, "*", "*", "[0-3][0-9]-[01][0-9]", "*")):
    if not os.path.isdir(t):
        continue
    # ТЕМА СДАНА — СМОТРИМ РАЗМЕР, А НЕ ИМЯ (улов 10.11, `usuario-ad`):
    # у каналов имя готового файла РАЗНОЕ — «…ГОТОВО.mp4», «… ВИДЕОРЯД.mp4»,
    # «…ГОТОВОЕ_ВИДЕО.mp4», «… ГОТОВЫЙ С ОЗВУЧКОЙ.mp4». Фильтр по одному
    # «*ГОТОВО.mp4» отдал вкладке СДАННУЮ тему ПЛАНЕТЫ вместо ожидания текста.
    # Пробы и образцы в папках тем ≤ 53 МБ, готовый ролик от 152 МБ.
    if [f for f in glob.glob(os.path.join(t, "*.mp4"))
       if os.path.getsize(f) >= 100 * 1024 * 1024]:
        continue
    txt = [f for f in glob.glob(os.path.join(t, "*.txt"))
           if not any(k in os.path.basename(f) for k in ("ЗАДАНИЕ", "БРИФ", "УПАКОВКА", "ОТВЕТ"))]
    if not txt:
        continue
    # РЕЕСТР — ВТОРОЕ СИТО ПОСЛЕ РАЗМЕРА mp4 (11.11, блокер `НА-РАСКАТКУ` п.1).
    # Размер ловит тему, чей готовый файл лежит в КОРНЕ её папки; если ролик
    # доставлен в другое место, тема снова выглядит свободной и `start` берёт
    # её по второму разу — вкладка уходит работать по чужому готовому ролику.
    # Запись «сдано» по работе «видеоряд» закрывает и этот случай.
    if _sdano(t):
        continue
    rows.append((max(os.path.getmtime(f) for f in txt), t))
rows.sort(reverse=True)
for _, t in rows[:12]:
    print(t)
PYEOF
)"
    TAKEN=""; PRJ=""
    while IFS= read -r td; do
        [ -n "$td" ] || continue
        CH="$(echo "$td" | sed "s|$NEWS/||" | cut -d/ -f1)"
        DAY="$(echo "$td" | sed "s|$NEWS/||" | cut -d/ -f3)"
        TNAME="$(basename "$td")"
        # ЧУЖОЙ КАНАЛ ПРОПУСКАЕМ МОЛЧА — см. правку 10.11 выше.
        if [ "$WANT_CH" != "ЛЮБОЙ" ] && [ "$CH" != "$WANT_CH" ]; then continue; fi
        # ТЕМА НАЗВАНА — БЕРЁМ ТОЛЬКО ЕЁ, свежесть больше ничего не решает.
        # Сверка нестрогая по регистру и пробелам: он пишет «2-Мосты приказ
        # отдан», в папке «2-МОСТЫ приказ отдан» — это одна и та же тема.
        if [ -n "$WANT_TEMA" ]; then
            if ! python3 - "$TNAME" "$WANT_TEMA" <<'PYT'
import re, sys
def key(x):
    return re.sub(r"[^а-яёa-z0-9]", "", x.lower())
have, want = key(sys.argv[1]), key(sys.argv[2])
sys.exit(0 if (have == want or want in have or have in want) else 1)
PYT
            then continue; fi
        fi
        SLUG="$(python3 - "$td" "$CH" "$DAY" <<'PYEOF'
import re, sys, os
t, ch, day = sys.argv[1], sys.argv[2], sys.argv[3]
name = os.path.basename(t.rstrip("/"))
tr = {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
      "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
      "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"}
lat = lambda x: "".join(tr.get(c, c) for c in x.lower())
chs = {"ПЛАНЕТА":"planeta","5 МИНУТ":"5min","ДИПЛОМАТИЯ СИЛЫ":"ds","ОЛЬКА НОВОСТИ":"olka",
       "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО":"perevod"}.get(ch, lat(ch)[:8])
w = [w for w in re.split(r"[^А-Яа-яЁёA-Za-z0-9]+", name) if w][:3]
print("%s-%s-%s" % (chs, "-".join(lat(x) for x in w)[:34].strip("-"), day.replace("-","")))
PYEOF
)"
        CAND="$HOME/projects/$SLUG"
        mkdir -p "$CAND"
        # КОДЫ take_folder: 0 — комплект полный · 1 — папка ЗАБРАНА, но в ней
        # ещё нет srt/озвучки (сторож их сделает, раскадровка идёт по тексту) ·
        # 2 — тему ведёт другая вкладка. Только 2 означает «не наша».
        python3 "$T/take_folder.py" "$td" "$CAND" >> "$LOG" 2>&1; TFRC=$?
        if [ "$TFRC" -eq 0 ] || [ "$TFRC" -eq 1 ]; then
            TAKEN="$td"; PRJ="$CAND"; CHANNEL="$CH"
            echo "[ОК]    тема взята: $CH · $TNAME (день $DAY)"
            [ "$TFRC" -eq 1 ] && echo "        комплект пока неполный — полную сборку не начинать, сторож догонит"
            break
        else
            rmdir "$CAND" 2>/dev/null
            echo "  — $CH · $TNAME: ведёт другая вкладка"
        fi
    done <<< "$CAND_LIST"
    [ -n "$TAKEN" ] && break
    # свободной темы пока нет: либо текст второго канала ещё пишется, либо все
    # темы разобраны. Ждём ВНУТРИ шага — это дешевле, чем опрашивать диск из
    # переписки, и вкладку можно открыть сразу, не дожидаясь первой.
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
        echo "ОШИБКА: за $WAITMIN мин свободной темы так и не появилось (текст второго канала не пришёл или все темы заняты)"
        exit 1
    fi
    [ "$SAID" -eq 0 ] && { echo "·· свободной темы нет — жду появления текста, проверяю каждые 30 с"; SAID=1; }
    sleep 30
    done
    echo "$KEY" > "$PRJ/.geo_key"
    echo "$CHANNEL" > "$PRJ/.channel"
    PIPE_FREE="$(pick_pipe "$PRJ" || true)"
    [ -n "$PIPE_FREE" ] || echo "[СМОТРИ] все шесть труб заняты — фаза fetch дождётся свободной сама"
    # ВТОРАЯ СТАТЬЯ, УПАКОВКА И ПРЕВЬЮ ЗАПУСКАЮТСЯ ЗДЕСЬ ЖЕ И В ФОНЕ.
    # Его вопрос 09.11: «как будет приходить написание второго варианта статьи
    # на канал ПЛАНЕТА? Я должен сидеть и ждать?» — нет: `tema_start.py` пускает
    # три ветки параллельно и ничего не ждёт, вкладка в это же время ведёт
    # видеоряд. Дважды не запустится: метка в папке темы + проверка, что в
    # зеркальной папке текста ещё нет.
    MIRROR=""
    case "$CHANNEL" in
        "5 МИНУТ") MIRROR="ПЛАНЕТА" ;;
        "ПЛАНЕТА") MIRROR="5 МИНУТ" ;;
    esac
    if [ -n "$MIRROR" ]; then
        MDIR="$NEWS/$MIRROR/$(echo "$TAKEN" | sed "s|$NEWS/$CHANNEL/||")"
        MTXT="$(ls "$MDIR"/*.txt 2>/dev/null | grep -vE "ЗАДАНИЕ|БРИФ|УПАКОВКА|ОТВЕТ" | head -1)"
        if [ -f "${TAKEN%/}/.tema_start" ]; then
            echo "[ОК]    вторая статья и упаковка уже запускались (метка в папке темы)"
        elif [ -n "$MTXT" ]; then
            echo "[ОК]    на $MIRROR текст уже лежит — вторую статью не заказываю"
        else
            if [ "${VIDEORYAD_DRY:-0}" = "1" ]; then
                echo "[ОК]    (проверка) запустил бы: tema_start.py ${TAKEN%/} --key $KEY --channel-2 $MIRROR"
                echo "        зеркальная папка: $MDIR"
                false
            elif python3 "$T/tema_start.py" "${TAKEN%/}" --key "$KEY" --channel-2 "$MIRROR" >> "$LOG" 2>&1; then
                date '+%Y-%m-%d %H:%M' > "${TAKEN%/}/.tema_start"
                echo "[ОК]    запущены в фоне: вторая статья на $MIRROR · упаковка · пять превью"
            elif [ "${VIDEORYAD_DRY:-0}" != "1" ]; then
                echo "[СМОТРИ] вторая статья/упаковка не запустились — ЗАКАЖИ ЯВНО:"
                echo "         python3 $T/tema_start.py \"${TAKEN%/}\" --key $KEY --channel-2 $MIRROR --only rewrite"
                echo "         причина — в $LOG (строки с «!!»)"
                NOTES=$((NOTES+1))
            fi
        fi
    fi

    # сразу и подготовка: досье по ключу, вложения постов, линты
    echo "·· подготовка по ключу"
    bash "${BASH_SOURCE[0]}" podgotovka "$PRJ" "$KEY" 2>&1 | sed 's/^/   /'
    echo "--------------------------------------------------------------"
    echo "КАНАЛ:   $CHANNEL"
    echo "ТЕМА:    $(basename "$TAKEN")"
    echo "ПАПКА:   ${TAKEN%/}"
    echo "ПРОЕКТ:  $PRJ"
    echo "КЛЮЧ:    $KEY"
    echo "ТРУБА:   ${PIPE_FREE:-все заняты, взять позже}"
    echo "ФАЙЛЫ:   txt $(ls "$PRJ"/*.txt 2>/dev/null | wc -l) · srt $(ls "$PRJ"/*.srt 2>/dev/null | wc -l) · озвучка $(ls "$PRJ"/narration.* 2>/dev/null | wc -l) · вложений годных $(python3 - "$PRJ" <<'PYEOF'
import glob, json, os, sys
n = 0
for f in glob.glob(os.path.join(sys.argv[1], "tg.json")):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list):
                n += len(v)
    elif isinstance(d, list):
        n += len(d)
print(n)
PYEOF
)"
    if ! ls "$PRJ"/narration.* >/dev/null 2>&1; then
        echo "ЖДЁМ:    озвучки ещё нет — сторож делает её сам, раскадровку начинай по тексту"
    fi
    echo "ДАЛЬШЕ:  задание на раскадровку внешнему агенту → приёмка → faza.sh fetch $PRJ ${PIPE_FREE:-<труба>}"
    summary
    ;;

# ---------------------------------------------------------------- ТЕМА
# Вкладка сама берёт следующую СВОБОДНУЮ тему своего канала: реестр, папка,
# проект, свободная труба. Раньше это раздавал координатор пятью строками
# вручную на каждую тему (его слово 09.11: «это чисто ручная работа, блядь»).
tema)
    # ТЕМУ МОЖНО НАЗВАТЬ И БЕЗ КЛЮЧА (12.11, улов `usuario-e3`). `start`
    # требует ключ георадара, а `--tema` у него только ДОПОЛНЕНИЕ; `tema`
    # же брала ПЕРВУЮ свободную — и вкладка, которой назвали её тему
    # голосом, не могла взять именно её: либо ключа ещё нет, либо чужая
    # тема уходила первой. Теперь: `faza.sh tema "5 МИНУТ" --tema "<имя>"`
    # (и `--wait <минут>`, если текста ещё нет на диске).
    WANT_TEMA="${VIDEORYAD_TEMA:-}"
    WAITMIN=0
    _ARGS=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --tema) WANT_TEMA="${2:-}"; shift 2 || true ;;
            --wait) WAITMIN="${2:-45}"; shift 2 || true ;;
            --key) KEY="${2:-}"; shift 2 || true ;;
            *) _ARGS+=("$1"); shift ;;
        esac
    done
    set -- "${_ARGS[@]:-}"
    DAY_IN="${1:-}"
    NEWS="${VIDEORYAD_NEWS_DIR:-/mnt/d/YouTube/НОВОСТИ}"
    CH_DIR="$NEWS/$CHANNEL"
    [ -d "$CH_DIR" ] || { echo "ОШИБКА: папки канала нет: $CH_DIR (канал пишется как в пути)"; exit 1; }
    if [ -n "$DAY_IN" ]; then
        DAYDIR="$(ls -d "$CH_DIR"/*/"$DAY_IN" 2>/dev/null | head -1)"
    else
        DAYDIR="$(ls -dt "$CH_DIR"/*/[0-3][0-9]-[01][0-9] 2>/dev/null | head -1)"
    fi
    [ -n "$DAYDIR" ] || { echo "ОШИБКА: папок дня у канала нет"; exit 1; }
    DAY="$(basename "$DAYDIR")"
    echo "канал: $CHANNEL · день: $DAY"
    # ДВЕРЬ РЕЕСТРА ОДНА — `take_folder.py`: он сам отмечает тему занятой и
    # отвечает кодом 2, если её уже ведёт другая вкладка. Отдельный
    # `zanyato --vzyat` здесь делать НЕЛЬЗЯ: он займёт тему, и забор сам себе
    # ответит «тему уже ведёт…» (поймано на первом же прогоне 09.11).
    TAKEN=""; PRJ=""
    for td in "$DAYDIR"/*/; do
        [ -d "$td" ] || continue
        TNAME="$(basename "$td")"
        # СДАННОСТЬ ПО РАЗМЕРУ, НЕ ПО ИМЕНИ — см. тот же улов 10.11 выше.
        if python3 -c 'import glob,os,sys; sys.exit(0 if [f for f in glob.glob(os.path.join(sys.argv[1],"*.mp4")) if os.path.getsize(f)>=100*1024*1024] else 1)' "$td" 2>/dev/null; then
            echo "  — $TNAME: уже сдана"; continue
        fi
        # ТЕМА НАЗВАНА — БЕРЁМ ТОЛЬКО ЕЁ, сверка нестрогая (регистр, пробелы,
        # хвост «5 минут» в имени папки): он говорит «Ялта 2.0», в папке
        # «2-РФ-США-ЕВРОПА-Ялта 2.0 5 минут».
        if [ -n "${WANT_TEMA:-}" ]; then
            if ! python3 - "$TNAME" "$WANT_TEMA" <<'PYT'
import re, sys
def key(x):
    return re.sub(r"[^а-яёa-z0-9]", "", x.lower())
have, want = key(sys.argv[1]), key(sys.argv[2])
sys.exit(0 if (have == want or want in have or have in want) else 1)
PYT
            then continue; fi
        fi
        TXT="$(ls "$td"*.txt 2>/dev/null | grep -vE "ЗАДАНИЕ|БРИФ|УПАКОВКА|ОТВЕТ" | head -1)"
        # ТЕКСТА ЕЩЁ НЕТ: названную тему ЖДЁМ ВНУТРИ ШАГА, если дали --wait.
        if [ -z "$TXT" ] && [ -n "${WANT_TEMA:-}" ] && [ "${WAITMIN:-0}" -gt 0 ]; then
            echo "  — $TNAME: текста ещё нет, жду до $WAITMIN мин (проверка каждые 30 с)"
            _DL=$(( $(date +%s) + WAITMIN*60 ))
            while [ "$(date +%s)" -lt "$_DL" ]; do
                sleep 30
                TXT="$(ls "$td"*.txt 2>/dev/null | grep -vE "ЗАДАНИЕ|БРИФ|УПАКОВКА|ОТВЕТ" | head -1)"
                [ -n "$TXT" ] && { echo "  — $TNAME: текст появился"; break; }
            done
        fi
        if [ -z "$TXT" ]; then echo "  — $TNAME: текста ещё нет"; continue; fi
        SLUG="$(python3 - "$td" "$CHANNEL" "$DAY" <<'PYEOF'
import re, sys, os
t, ch, day = sys.argv[1], sys.argv[2], sys.argv[3]
name = os.path.basename(t.rstrip("/"))
tr = {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
      "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
      "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"}
def lat(x):
    return "".join(tr.get(c, c) for c in x.lower())
chs = {"ПЛАНЕТА":"planeta","5 МИНУТ":"5min","ДИПЛОМАТИЯ СИЛЫ":"ds","ОЛЬКА НОВОСТИ":"olka",
       "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО":"perevod"}.get(ch, lat(ch)[:8])
w = [w for w in re.split(r"[^А-Яа-яЁёA-Za-z0-9]+", name) if w][:3]
print("%s-%s-%s" % (chs, "-".join(lat(x) for x in w)[:34].strip("-"), day.replace("-","")))
PYEOF
)"
        CAND="$HOME/projects/$SLUG"
        mkdir -p "$CAND"
        python3 "$T/take_folder.py" "$td" "$CAND" >> "$LOG" 2>&1; TFRC=$?
        if [ "$TFRC" -eq 0 ] || [ "$TFRC" -eq 1 ]; then
            TAKEN="$td"; PRJ="$CAND"
            echo "[ОК]    взята тема: $TNAME → $PRJ"
            [ "$TFRC" -eq 1 ] && echo "        комплект пока неполный — полную сборку не начинать, сторож догонит"
            break
        else
            rmdir "$CAND" 2>/dev/null
            echo "  — $TNAME: ведёт другая вкладка (реестр)"
        fi
    done
    [ -n "$TAKEN" ] || { echo "ОШИБКА: свободных тем канала $CHANNEL за $DAY нет"; exit 1; }
    SLUG="$(python3 - "$TAKEN" "$CHANNEL" "$DAY" <<'PYEOF'
import re, sys, os
t, ch, day = sys.argv[1], sys.argv[2], sys.argv[3]
name = os.path.basename(t.rstrip("/"))
tr = {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
      "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
      "х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"}
def lat(x):
    return "".join(tr.get(c, tr.get(c.lower(), c).upper() if c.isupper() else c) for c in x.lower())
chs = {"ПЛАНЕТА":"planeta","5 МИНУТ":"5min","ДИПЛОМАТИЯ СИЛЫ":"ds","ОЛЬКА НОВОСТИ":"olka",
       "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО":"perevod"}.get(ch, lat(ch)[:8])
w = [w for w in re.split(r"[^А-Яа-яЁёA-Za-z0-9]+", name) if w][:3]
print("%s-%s-%s" % (chs, "-".join(lat(x) for x in w)[:34].strip("-"), day.replace("-","")))
PYEOF
)"
    # ТРИ ПАРАЛЛЕЛЬНЫЕ ВЕТКИ ЗАПУСКАЕТ И `tema` ТОЖЕ (12.11, улов `usuario-e3`).
    # Было: их пускал только `start`, а взявшая тему по имени вкладка уходила
    # в видеоряд — и вторая статья, упаковка и пять превью по этой теме не
    # заказывались ВООБЩЕ. Поймано на «Ялте 2.0»: метки `.tema_start` в папке
    # не было, второй канал стоял пустой. Ключ берём из `--key`/окружения;
    # без ключа `tema_start.py` не зовём и говорим об этом вслух.
    KEY="${VIDEORYAD_KEY:-${KEY:-}}"
    MIRROR=""
    case "$CHANNEL" in
        "5 МИНУТ") MIRROR="ПЛАНЕТА" ;;
        "ПЛАНЕТА") MIRROR="5 МИНУТ" ;;
    esac
    if [ -n "$MIRROR" ]; then
        MDIR="$NEWS/$MIRROR/$(echo "${TAKEN%/}" | sed "s|$NEWS/$CHANNEL/||")"
        MTXT="$(ls "$MDIR"/*.txt 2>/dev/null | grep -vE "ЗАДАНИЕ|БРИФ|УПАКОВКА|ОТВЕТ" | head -1)"
        if [ -f "${TAKEN%/}/.tema_start" ]; then
            echo "[ОК]    вторая статья и упаковка уже запускались (метка в папке темы)"
        elif [ -n "$MTXT" ]; then
            echo "[ОК]    на $MIRROR текст уже лежит — вторую статью не заказываю"
        elif [ -z "$KEY" ]; then
            echo "[СМОТРИ] ВТОРАЯ СТАТЬЯ, УПАКОВКА И ПРЕВЬЮ НЕ ЗАКАЗАНЫ: нет ключа."
            echo "         Дай ключ — faza.sh tema \"$CHANNEL\" --tema \"…\" --key <ARM_…>"
            echo "         или закажи явно: python3 $T/tema_start.py \"${TAKEN%/}\" --key <ключ> --channel-2 $MIRROR"
            NOTES=$((NOTES+1))
        elif python3 "$T/tema_start.py" "${TAKEN%/}" --key "$KEY" --channel-2 "$MIRROR" >> "$LOG" 2>&1; then
            date '+%Y-%m-%d %H:%M' > "${TAKEN%/}/.tema_start"
            echo "[ОК]    запущены в фоне: вторая статья на $MIRROR · упаковка · пять превью"
        else
            echo "[СМОТРИ] вторая статья/упаковка не запустились — закажи явно:"
            echo "         python3 $T/tema_start.py \"${TAKEN%/}\" --key $KEY --channel-2 $MIRROR --only rewrite"
            NOTES=$((NOTES+1))
        fi
    fi
    PIPE_FREE="$(pick_pipe "$PRJ" || true)"
    [ -n "$PIPE_FREE" ] || echo "[СМОТРИ] все шесть труб заняты — фаза fetch дождётся свободной сама"
    echo "--------------------------------------------------------------"
    echo "ТЕМА:    $(basename "$TAKEN")"
    echo "ПАПКА:   ${TAKEN%/}"
    echo "ПРОЕКТ:  $PRJ"
    echo "ТРУБА:   ${PIPE_FREE:-все заняты, взять позже}"
    echo "ФАЙЛЫ:   txt $(ls "$PRJ"/*.txt 2>/dev/null | wc -l) · srt $(ls "$PRJ"/*.srt 2>/dev/null | wc -l) · озвучка $(ls "$PRJ"/narration.* 2>/dev/null | wc -l)"
    echo "ДАЛЬШЕ:  bash template/faza.sh podgotovka $PRJ [ключ георадара]"
    summary
    ;;

# ---------------------------------------------------------------- ПОДГОТОВКА
# Георадар → вложения постов → приёмка раскадровки → линты до чистого.
# Раскадровку пишет внешний агент; эта фаза готовит ей вход и проверяет выход.
podgotovka)
    KEY="${1:-}"
    cd "$PROJ" || exit 1
    GEO="$(ls -t /mnt/d/_ГЕОРАДАР-КОПИЯ/*.xlsx 2>/dev/null | head -1)"
    # ВОЗРАСТ КОПИИ НАЗЫВАЕМ ВСЛУХ (10.11, улов `usuario-d3`, отозвавшей свой
    # же неверный вывод). Запись по ключу `…_LONDON_PHONE_…_332` в живой
    # таблице БЫЛА — 16 постов, — но локальные копии были утренние, а запись
    # завели в 14:47. Инструмент сказал «ключ не встретился», вкладка прочла
    # это как «записи нет вовсе» и повела ролик без досье. Drive виден только
    # из сессии Claude, сам скрипт выгрузку обновить не может — поэтому он
    # обязан хотя бы ЗАЯВИТЬ, по какому снимку работает.
    if [ -n "$GEO" ]; then
        _geo_age_h=$(( ( $(date +%s) - $(stat -c %Y "$GEO") ) / 3600 ))
        echo "        · георадар: копия $(basename "$GEO"), снимок $(stat -c %y "$GEO" | cut -c1-16) (${_geo_age_h} ч назад)"
        if [ "$_geo_age_h" -ge 3 ]; then
            echo "        · ВНИМАНИЕ: копии больше трёх часов. «Ключа нет» по ней"
            echo "          означает «нет В ЭТОЙ КОПИИ» — положи свежую выгрузку"
            echo "          в /mnt/d/_ГЕОРАДАР-КОПИЯ/ и повтори, прежде чем решать."
        fi
    fi
    if [ -n "$KEY" ] && [ -n "$GEO" ]; then
        # пустое или несуществующее досье — НЕ отказ фазы: ролик идёт дальше на
        # поиске и базе, координатору уходит строка (правило 23.10)
        GLOUT="$(mktemp)"
        python3 "$T/geo_links.py" "$GEO" "$KEY" --out "$PROJ/links.txt" > "$GLOUT" 2>&1 || true
        cat "$GLOUT" >> "$LOG"
        grep -hE "НЕ ВСТРЕТИЛСЯ|НЕСУЩЕСТВУЮЩИЙ" "$GLOUT" | head -1 | cut -c1-200 | sed 's/^/        · /'
        rm -f "$GLOUT"
        if [ -s "$PROJ/links.txt" ]; then
            echo "[ОК]    ссылки досье: $(wc -l < "$PROJ/links.txt") шт"
            step "вложения постов" bash -c "cd '$PROJ' && python3 '$T/tg_media.py' --json tg.json \$(cat links.txt)"
        else
            echo "[СМОТРИ] досье по ключу $KEY пусто — работаем без вложений, координатору строкой"
            NOTES=$((NOTES+1))
        fi
    else
        echo "[ОК]    ключа досье нет — шаг георадара пропущен"
    fi
    if [ -z "$SCENES" ]; then
        echo "--------------------------------------------------------------"
        echo "РАСКАДРОВКИ ЕЩЁ НЕТ: отдай задание внешнему агенту, прими его файл"
        echo "  python3 $T/accept_scenes.py <его.json> --srt <srt> --channel \"<КАНАЛ>\" --fix --out $(basename "$PROJ").scenes.json"
        echo "  и повтори: bash template/faza.sh podgotovka $PROJ"
        summary; exit 0
    fi
    step "линт запросов"  python3 "$T/query_lint.py" "$SCENES"
    step "сверка пинов"   python3 "$T/check_pins.py" "$SCENES"
    # учёт материала досье имеет смысл только когда вложения реально скачаны
    if [ -f "$PROJ/tg.json" ]; then
        step "материал досье" python3 "$T/dossier_use.py" "$SCENES"
    else
        echo "[ОК]    вложений досье нет — учёт пропущен"
    fi
    summary
    ;;

# ---------------------------------------------------------------- ПОСЛЕ ФЕТЧА
# Карточки облаком → слои (всплывашки/надписи/эффекты) → контактные листы.
posle_fetcha)
    mem_check "posle_fetcha"
    PIPE="${1:-}"
    [ -n "$SCENES" ] || { echo "ОШИБКА: не нашёл <проект>.scenes.json"; exit 1; }
    cd "$PROJ" || exit 1
    if [ -n "$PIPE" ]; then
        step "карточки облаком" bash "$SK/cloud/va.sh" "$PIPE" python3 "$SK/fullcycle/cards_cloud.py" "$SCENES"
    else
        echo "[СМОТРИ] труба не названа — карточки не отрисованы"; NOTES=$((NOTES+1))
    fi
    step "слои (всплывашки/надписи)" python3 "$T/build_overlays.py" build "$PROJ"
    # fx_put --auto отвечает кодом 1 и когда ставить НЕЧЕГО (нормы соблюдены,
    # зазор не позволяет) — это не отказ фазы, а штатный ответ
    FXOUT="$(mktemp)"
    python3 "$T/fx_put.py" "$SCENES" --auto > "$FXOUT" 2>&1; FXRC=$?
    cat "$FXOUT" >> "$LOG"
    if [ "$FXRC" -eq 0 ]; then
        echo "[ОК]    эффекты"
    elif grep -q "ставить не буду\|нечего\|уже сто" "$FXOUT"; then
        echo "[ОК]    эффекты — ставить нечего (нормы соблюдены)"
    else
        echo "[ОТКАЗ] эффекты (код $FXRC)"; grep -hE "$MARK" "$FXOUT" | head -2 | cut -c1-200 | sed 's/^/        · /'
        FAILED=$((FAILED+1))
    fi
    rm -f "$FXOUT"
    step "контактные листы" python3 "$T/contact_sheet.py" "$SCENES" images thumbs
    if [ -f "$PROJ/overlays.json" ]; then
        step "листы парами" python3 "$T/pair_sheet.py" "$PROJ" thumbs
    else
        echo "[ОК]    всплывашек нет — листы парами не нужны"
    fi
    summary
    ;;

*) echo "ОШИБКА: неизвестная фаза '$FAZA' (start|tema|podgotovka|fetch|posle_fetcha|krug|final|sdacha)"; exit 1;;
esac
