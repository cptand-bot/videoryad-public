#!/usr/bin/env bash
# ВСЕ МАШИННЫЕ ПРОВЕРКИ РОЛИКА — ОДНОЙ КОМАНДОЙ, ОТВЕТ ОДНОЙ СТРОКОЙ.
#
#   bash template/nuli.sh <ролик>.scenes.json
#
# ЗАЧЕМ (14.11.2026, его слово «если можно убрать из модели — убираем»).
# Пять проверок вкладка гоняла по одной: запусти → прочитай вывод → реши →
# следующая. Это пять запросов МОДЕЛИ, а в конце смены один запрос стоит
# 250-400 К токенов. Решения тут нет вовсе: проверка либо даёт ноль, либо
# называет номера сцен. Поэтому их гоняет скрипт, а модель видит одну
# строку: «ЧИСТО» или перечень того, что не ноль.
#
# ИМЕНА ПЕРЕМЕННЫХ ЛАТИНИЦЕЙ: bash кириллицу в именах не принимает вовсе
# («not a valid identifier»), и первый вариант этого скрипта рапортовал
# «ЕСТЬ ЗАМЕЧАНИЯ» на пустом месте. Комментарии и вывод — по-русски.
#
# Код возврата: 0 — все пять чисто; 1 — есть замечания (они в выводе).
set -uo pipefail
T="$(cd "$(dirname "$0")" && pwd)"
SCENES="${1:-}"
[ -n "$SCENES" ] && [ -f "$SCENES" ] || { echo "ОШИБКА: нет файла сцен: ${SCENES:-—}"; exit 2; }
PROJ="$(cd "$(dirname "$SCENES")" && pwd)"
BASE="$(basename "$SCENES")"
cd "$PROJ" || exit 2

itog=""; bad=0; log="$(mktemp)"
run_check () {            # имя · команда…
    name="$1"; shift
    if "$@" > "$log" 2>&1; then
        itog="$itog $name:0"
    else
        bad=1
        line="$(grep -m1 -E "^(ОШИБКА|!!|ОТКАЗ)" "$log" | cut -c1-150)"
        [ -z "$line" ] && line="$(tail -1 "$log" | cut -c1-150)"
        itog="$itog $name:ЕСТЬ"
        printf '  [%s] %s\n' "$name" "$line"
    fi
}

run_check ревизия   python3 "$T/revizia_kartochek.py" "$BASE"
run_check имена     python3 "$T/imena_pod_kadrom.py"  "$BASE"
run_check дети      python3 "$T/deti_gate.py" check "$PROJ"
run_check повторы   python3 "$T/povtor_kadrov.py"     "$BASE"
run_check selfcheck python3 "$T/selfcheck.py"         "$BASE"
rm -f "$log"

if [ "$bad" = 0 ]; then
    echo "ЧИСТО:$itog — дашборд можно отдавать"
else
    echo "ЕСТЬ ЗАМЕЧАНИЯ:$itog — строки выше, дашборд не отдавать"
fi
exit "$bad"
