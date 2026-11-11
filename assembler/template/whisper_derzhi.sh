#!/usr/bin/env bash
# ДЕРЖАТЬ РАСПОЗНАВАТЕЛЬ ДИКТОВКИ ТЁПЛЫМ — ВСЕГДА.
#
# Его слово, ТРИ ДНЯ ПОДРЯД (последний раз 11.11.2026): «с какого перепугу
# расшифровывается на моей машине? Почему не сразу? Почему долго?»
#
# Почему было «не сразу»: сайдкар с моделью поднимался ТОЛЬКО по факту первой
# диктовки и выходил через `VIDEORYAD_WHISPER_IDLE=180` секунд тишины. Значит
# каждая диктовка после трёх минут паузы снова грузила 600 МБ модели — а он
# диктует редко и вразбивку, то есть платил загрузку КАЖДЫЙ раз. Автозапуска
# не было вообще: в `crontab` по whisper/voice/sidecar было пусто (сверено
# 11.11).
#
# Теперь: cron раз в минуту держит сайдкар живым, простой выставлен в СУТКИ.
# Первая диктовка больше не платит загрузку модели — платит только счёт.
#
#   bash whisper_derzhi.sh            # поднять, если лежит (так зовёт cron)
#   bash whisper_derzhi.sh --status   # сказать, жив ли, и выйти
#   bash whisper_derzhi.sh --stop     # остановить (нужно крайне редко)
#
# Проверка — ПО СОКЕТУ И ОТВЕТУ, а не по живому процессу: от умершего
# сайдкара остаётся оболочка процесса, и `pgrep` на это врёт. На этом уже
# обжигались с дашбордами роликов.
set -u
T="$HOME/.claude/skills/news-video/template"
LOG="/tmp/videoryad-whisper-$(id -u).log"
MODEL="${VIDEORYAD_WHISPER_MODEL:-base}"
SOCK="${TMPDIR:-/tmp}/videoryad-whisper-$(id -u)-$MODEL.sock"
# СУТКИ, А НЕ ТРИ МИНУТЫ — в этом вся правка.
export VIDEORYAD_WHISPER_IDLE="${VIDEORYAD_WHISPER_IDLE:-86400}"
export VIDEORYAD_WHISPER_MODEL="$MODEL"

# ПРИОРИТЕТ НЕ СНИЖАЕМ. Замер 11.11: под `nice -n 19` тот же отрывок считался
# 101 с вместо 17 — диктовка интерактивная и короткая, ей нужен процессор
# сейчас. Правило `nice` остаётся для тяжёлых прогонов ffmpeg, не для этого.
живой() { [ -S "$SOCK" ] && timeout 20 python3 "$T/voice_note.py" --warm >/dev/null 2>&1; }

case "${1:-}" in
  --status)
      if живой; then echo "сайдкар жив: модель $MODEL, сокет $SOCK"
      else echo "сайдкара нет (сокет $SOCK)"; fi
      exit 0 ;;
  --stop)
      # СВОЙ PID ИСКЛЮЧАЕМ: `pkill -f` матчит собственную командную строку и
      # убивает сам себя — наступали на это дважды 11.11 (улов `usuario-2b`).
      for _p in $(pgrep -f "voice_note.py --sidecar" | grep -v "^$$\$"); do
          kill "$_p" 2>/dev/null
      done
      rm -f "$SOCK"; echo "остановлен"; exit 0 ;;
esac

# ОДИН НА ВСЮ МАШИНУ: без замка cron раз в минуту наплодил бы копий по 600 МБ.
exec 9>"/tmp/videoryad-whisper-derzhi.lock"
flock -n 9 || exit 0

живой && exit 0
rm -f "$SOCK"
printf '%s поднимаю сайдкар (модель %s, простой %s с)\n' "$(date '+%F %T')" \
       "$MODEL" "$VIDEORYAD_WHISPER_IDLE" >>"$LOG"
setsid python3 "$T/voice_note.py" --sidecar >>"$LOG" 2>&1 &
for _ in $(seq 1 30); do sleep 1; живой && break; done
живой && printf '%s сайдкар поднят\n' "$(date '+%F %T')" >>"$LOG" \
       || printf '%s САЙДКАР НЕ ПОДНЯЛСЯ\n' "$(date '+%F %T')" >>"$LOG"
