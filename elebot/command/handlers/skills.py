"""Skill 管理类 slash 命令。"""

from __future__ import annotations

from elebot.agent.skills import SkillManager, SkillRegistry
from elebot.bus.events import OutboundMessage
from elebot.command.router import CommandContext


async def cmd_skill_manage(ctx: CommandContext) -> OutboundMessage:
    """处理 skill 列表、安装与卸载命令。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    args = ctx.args.strip()
    parts = args.split(None, 1)
    action = parts[0].lower() if parts else ""

    if action == "list" and len(parts) == 1:
        content = _build_skill_list_content(SkillRegistry().list_status())
    elif action == "install":
        if len(parts) != 2 or not parts[1].strip():
            content = "请提供 skill 来源。用法：`/skill install <source>`"
        else:
            _, content = SkillManager().install(_strip_wrapping_quotes(parts[1].strip()))
    elif action == "uninstall":
        if len(parts) != 2 or not parts[1].strip():
            content = "请提供 skill 名称。用法：`/skill uninstall <name>`"
        else:
            _, content = SkillManager().uninstall(_strip_wrapping_quotes(parts[1].strip()))
    else:
        content = (
            "用法：`/skill list`、`/skill install <source>`、"
            "`/skill uninstall <name>`"
        )

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def _build_skill_list_content(items: list[dict[str, object]]) -> str:
    """构造 skill 列表展示文案。

    参数:
        items: `SkillRegistry.list_status()` 返回的技能状态列表。

    返回:
        面向终端展示的文本。
    """
    if not items:
        return (
            "当前没有发现可用 skills。\n\n"
            "默认目录：`~/.elebot/skills`\n"
            "安装用法：`/skill install <source>`\n"
            "每个 skill 目录至少需要包含 `SKILL.md`。"
        )

    lines = [
        "## Skills",
        "",
        "当前全局 skill 目录：`~/.elebot/skills`",
        "",
    ]
    for item in items:
        description = str(item.get("description") or "暂无描述。")
        display_name = str(item.get("name") or item.get("key") or "")
        lines.append(f"- `{item['key']}` {display_name}：{description}")
    lines.extend(
        [
            "",
            "安装用法：`/skill install <source>`",
            "卸载用法：`/skill uninstall <name>`",
        ]
    )
    return "\n".join(lines)


def _strip_wrapping_quotes(text: str) -> str:
    """移除参数最外层的配对引号。

    参数:
        text: 原始命令参数。

    返回:
        去除外层引号后的字符串。
    """
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text
