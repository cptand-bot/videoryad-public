#!/usr/bin/env bash
# ДЫМОВАЯ ПРОБА ДВЕРЕЙ — ПЕРЕД КАЖДОЙ РАСКАТКОЙ (15.11.2026).
#
# Повод: правка чистки кавычек прошла `ast.parse` («синтаксис чист»), уехала
# на шесть труб и повесила `card_put` вечным циклом на пустом поле. Двадцать
# минут простоя, два убитых прогона облака. Синтаксис не ловит ни вечный
# цикл, ни отказ двери — ловит только ЗАПУСК.
#
# Что делает: зовёт три двери на пробной раскадровке с ЖЁСТКИМ таймаутом.
# Висит дольше 40 с — это провал, а не медленная машина.
set -uo pipefail
# ИМЕНА ПЕРЕМЕННЫХ ТОЛЬКО ЛАТИНИЦЕЙ: bash кириллические не понимает,
# строка исполняется как КОМАНДА («nm=…: command not found») — та же гоча,
# что поймана сегодня в faza.sh (П-0251). Наступил на неё здесь же, при
# написании самой пробы — значит правило нужно в каждом новом скрипте.
T="$(cd "$(dirname "$0")" && pwd)"
SK="$(dirname "$T")"
RAB="$(mktemp -d)"
trap 'rm -rf "$RAB"' EXIT
mkdir -p "$RAB/cards"
python3 - "$RAB" <<'PY'
import json, os, sys
d = sys.argv[1]
сцены = {"scenes": [{"id": i, "text": "Европа теряет рычаги давления, и это видно по решениям последних недель.",
                     "dur": 11.0, "source": "web_search", "source_query": "саммит ЕС Брюссель 2026"}
                    for i in range(1, 31)]}
json.dump(сцены, open(os.path.join(d, os.path.basename(d) + ".scenes.json"), "w",
                      encoding="utf-8"), ensure_ascii=False)
PY
SCENES="$RAB/$(basename "$RAB").scenes.json"
bad=0
proba () {                       # nm · таймаут · команда…
    nm="$1"; tmo="$2"; shift 2
    if timeout "$tmo" "$@" >"$RAB/out.log" 2>&1; then
        echo "  [ОК]     $nm"
    else
        rc=$?
        if [ "$rc" = 124 ]; then
            echo "  [ВИСИТ]  $nm — НЕ ОТВЕТИЛ за ${tmo}s. Это вечный цикл или ожидание, раскатывать НЕЛЬЗЯ."
            bad=1
        else
            # ненулевой rc у двери — норма (гейты отбивают пробный текст),
            # важно, что она ОТВЕТИЛА
            echo "  [ответ]  $nm (rc $rc — гейт отработал, не вис)"
        fi
    fi
}
echo "ДЫМОВАЯ ПРОБА ДВЕРЕЙ:"
proba "card_put --help"    20 python3 "$SK/fullcycle/card_put.py" --help
proba "card_put карточка"  40 python3 "$SK/fullcycle/card_put.py" "$SCENES" 5 paper_typed \
        --text "Европа теряет рычаги давления, и это видно по решениям последних недель."
proba "card_put пустое"    40 python3 "$SK/fullcycle/card_put.py" "$SCENES" 7 paper_typed \
        --text "Европа теряет рычаги давления прямо сейчас." --kick "" --title ""
proba "element_put --help" 20 python3 "$SK/template/element_put.py" --help
proba "style_card --help"  20 python3 "$SK/template/style_card.py" --help
proba "kartochki_srazu"    60 python3 "$SK/template/kartochki_srazu.py" "$SCENES"
if [ "$bad" = 0 ]; then
    echo "ПРОБА ЧИСТА — двери отвечают, можно раскатывать"
    exit 0
fi
echo "ПРОБА ПРОВАЛЕНА — раскатку НЕ делать, чинить дверь" >&2
exit 1
