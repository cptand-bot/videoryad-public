#!/bin/bash
# СТОРОЖ ВТОРОЙ СТАТЬИ — НИКТО НЕ ЖДЁТ ПОТЕРЯННЫЙ ЗАХОД (12.11.2026).
#
# Его слово 12.11: «ни в коем случае не останавливаться и в очередь не стоять…
# 3 часа делаем ролик, он живёт 3 часа на ютубе».
# Повод: заход на вторую статью «Ялты 2.0» был заказан в 10:14 и ПОТЕРЯЛСЯ —
# в журнале заходов его нет вовсе. Узнали через 45 минут, когда вкладка
# ПЛАНЕТЫ отстояла полный круг ожидания впустую.
#
# Раз в 5 минут смотрит папки тем. Если лежит ЗАДАНИЕ-РЕРАЙТ.txt, ответа нет,
# процесса агента по этому файлу нет и прошло больше 12 минут — запускает
# заход ЗАНОВО на менее загруженном аккаунте (основной / eva).
#
#   bash rerayt_storozh.sh          # один проход
#   bash rerayt_storozh.sh --cron   # поставить в cron, раз в 5 минут
set -u
SK="$HOME/.claude/skills/news-video"
NEWS="${VIDEORYAD_NEWS_DIR:-/mnt/d/YouTube/НОВОСТИ}"
LOG="$SK/base/rerayt_storozh.log"
IDLE_MIN=12

if [ "${1:-}" = "--cron" ]; then
  crontab -l 2>/dev/null | grep -v "rerayt_storozh.sh" > /tmp/_cron.$$ || true
  echo "*/5 * * * * bash $SK/template/rerayt_storozh.sh >> $LOG 2>&1" >> /tmp/_cron.$$
  crontab /tmp/_cron.$$ && rm -f /tmp/_cron.$$ && echo "сторож второй статьи в cron, раз в 5 минут"
  exit 0
fi

NOW="$(date '+%Y-%m-%d %H:%M')"
for TASK in "$NEWS"/*/*/[0-3][0-9]-[01][0-9]/*/ЗАДАНИЕ-РЕРАЙТ.txt; do
  [ -f "$TASK" ] || continue
  DIR="$(dirname "$TASK")"
  ANS="${TASK%.txt}.ОТВЕТ.txt"
  [ -s "$ANS" ] && continue
  AGE=$(( ( $(date +%s) - $(stat -c %Y "$TASK") ) / 60 ))
  [ "$AGE" -lt "$IDLE_MIN" ] && continue
  # ТОЛЬКО СЕГОДНЯШНЯЯ РАБОТА (12.11, поймано на первом же прогоне): без
  # этого сторож поднял брошенные задания двухдневной давности и сжёг бы на
  # них лимит агента. Потолок 180 минут — дольше живой заход не идёт.
  [ "$AGE" -gt 180 ] && continue
  if pgrep -f "$(basename "$DIR")/ЗАДАНИЕ-РЕРАЙТ.txt" >/dev/null 2>&1; then
    continue
  fi
  J="$SK/template/upakovka_lib/codex_zahody.tsv"
  MAIN=$(grep -c "основной" "$J" 2>/dev/null || echo 0)
  EVA=$(grep -c "eva" "$J" 2>/dev/null || echo 0)
  ACC="основной"; [ "$MAIN" -gt "$EVA" ] && ACC="eva"
  echo "$NOW  ПОТЕРЯН заход: $DIR (возраст $AGE мин) → перезапуск на $ACC"
  if [ "$ACC" = "eva" ]; then
    CODEX_ACCOUNT=eva setsid bash "$SK/template/codex_ask.sh" "$TASK" >> "$LOG" 2>&1 &
  else
    setsid bash "$SK/template/codex_ask.sh" "$TASK" >> "$LOG" 2>&1 &
  fi
  sleep 2
done
