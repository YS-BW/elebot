"""会话控制类 slash 命令。"""

from __future__ import annotations

from elebot.bus.events import OutboundMessage
from elebot.command.router import CommandContext


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
