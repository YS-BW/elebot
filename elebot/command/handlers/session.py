"""会话控制类 slash 命令。"""

from __future__ import annotations

from elebot.bus.events import OutboundMessage
from elebot.command.router import CommandContext


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """停止当前会话下的活动任务。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    cancelled = await ctx.loop.cancel_session_tasks(ctx.key)
    content = f"已停止 {cancelled} 个任务。" if cancelled else "当前没有可停止的任务。"
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata=dict(ctx.msg.metadata or {}),
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """开启全新会话。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    ctx.loop.reset_session(ctx.key)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="已开始新会话。",
        metadata=dict(ctx.msg.metadata or {}),
    )
