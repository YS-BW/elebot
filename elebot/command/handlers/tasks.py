"""任务管理类 slash 命令。"""

from __future__ import annotations

from elebot.bus.events import OutboundMessage
from elebot.command.router import CommandContext


async def cmd_task_manage(ctx: CommandContext) -> OutboundMessage:
    """处理任务查看与删除命令。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    task_service = ctx.loop.task_service
    args = ctx.args.strip()

    def _render(items, *, current_only: bool) -> str:
        if not items:
            return "当前没有任务。"
        title = "当前会话定时任务：" if current_only else "全部定时任务："
        lines = ["## Tasks", "", title, ""]
        for item in items:
            status = "启用" if item.enabled else "禁用"
            lines.append(
                f"- `{item.task_id}` {item.schedule_type} {status} "
                f"[{item.session_key}] -> {item.content} "
                f"(next: {item.next_run_at or '无'}, status: {item.last_status or 'idle'})"
            )
        lines.extend(["", "删除用法：`/task remove <task_id>`"])
        return "\n".join(lines)

    if not args:
        content = _render(task_service.list_by_session(ctx.key), current_only=True)
    elif args.lower() == "list":
        content = _render(task_service.list_all(), current_only=False)
    else:
        parts = args.split(None, 1)
        action = parts[0].lower()
        if action != "remove" or len(parts) != 2 or not parts[1].strip():
            content = "用法：`/task`、`/task list`、`/task remove <task_id>`"
        else:
            task_id = parts[1].strip()
            if task_service.remove(task_id):
                content = f"已删除任务：`{task_id}`。"
            else:
                content = f"找不到任务：`{task_id}`。"

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )
