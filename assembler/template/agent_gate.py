# -*- coding: utf-8 -*-
"""ХУК: СУБАГЕНТ ТОЛЬКО ПО ИМЕНИ, ИНАЧЕ ОТКАЗ (16.11.2026).

Его требование: «я должен 100%, 150% быть уверенным в том, что работают
дешёвые модели… жёстко зашить». Безымянный субагент НАСЛЕДУЕТ модель вкладки,
то есть идёт по цене Opus; переменной «модель субагентов по умолчанию» в
Claude Code нет (проверено по документации 16.11). Единственный надёжный
способ — не дать позвать субагента без имени: модель зашита в самом описании
агента (`~/.claude/agents/*.md`, поле `model`).

Стоит хуком `PreToolUse` на инструмент `Agent`: на вход приходит JSON с
`tool_name` и `tool_input` (там `subagent_type` и `prompt`), ответ —
`permissionDecision: deny` с причиной. Разрешённые имена — ниже; наши четыре
сидят на Haiku и Sonnet, служебные `claude-code-guide` и `Explore` оставлены
(они нужны редко и по делу).

Разовое исключение: `VIDEORYAD_AGENT_OK=1` в окружении сессии.
"""

import json
import os
import sys

# Наши — у каждого в описании стоит model: haiku/sonnet.
НАШИ = {
    "listy": "Haiku · контактные листы",
    "mehanika": "Haiku · найти/промерить/скопировать/посчитать",
    "kadry": "Sonnet · осмотр кадров и карточек",
    "hozyaystvo": "Sonnet · стейджинг, база, сверка, диски",
}
# Служебные, которые пускаем как есть.
СЛУЖЕБНЫЕ = {"claude-code-guide", "statusline-setup", "Explore", "Plan"}


def main():
    if os.environ.get("VIDEORYAD_AGENT_OK") == "1":
        return 0
    try:
        вход = json.load(sys.stdin)
    except Exception:
        return 0                      # не разобрали вход — не мешаем
    if str(вход.get("tool_name") or "") != "Agent":
        return 0
    ти = вход.get("tool_input") or {}
    имя = str(ти.get("subagent_type") or "").strip()
    if имя in НАШИ or имя in СЛУЖЕБНЫЕ:
        return 0

    список = "\n".join("    %-12s — %s" % (k, v) for k, v in НАШИ.items())
    причина = (
        ("субагент «%s» не из списка" % имя) if имя else
        "субагент позван БЕЗ ИМЕНИ (subagent_type не указан)"
    ) + (
        ": такой наследует модель вкладки, то есть пойдёт по цене самой "
        "дорогой модели. Его требование 16.11: «я должен 100%, 150% быть "
        "уверенным, что работают дешёвые модели… жёстко зашить».\n"
        "  Зови по имени — модель зашита в описании агента:\n" + список +
        "\n  Ничего из этого не подходит — делай сам в основном потоке или "
        "скажи координатору; разовое исключение — VIDEORYAD_AGENT_OK=1."
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": причина,
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
