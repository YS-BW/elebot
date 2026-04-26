"""Skill 使用日志。"""

from __future__ import annotations

import json

from elebot.agent.skills.models import SkillSpec
from elebot.config.paths import get_skill_usage_log_path


def record_skill_usage(
    skill: SkillSpec,
    *,
    channel: str | None = None,
    chat_id: str | None = None,
    trigger: str = "model",
) -> None:
    """记录一次 skill 使用事件。

    参数:
        skill: 被使用的 Skill。
        channel: 消息来源通道。
        chat_id: 会话标识。
        trigger: 触发来源，默认 ``model``。

    返回:
        无返回值。
    """
    payload = {
        "skill": skill.key,
        "name": skill.metadata.name,
        "description": skill.metadata.description,
        "channel": channel or "",
        "chat_id": chat_id or "",
        "trigger": trigger,
    }
    log_path = get_skill_usage_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
