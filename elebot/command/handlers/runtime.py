"""运行时控制类 slash 命令。"""

from __future__ import annotations

import asyncio
import os
import sys

from elebot.bus.events import OutboundMessage
from elebot.command.router import CommandContext
from elebot.command.runtime_status import build_status_content
from elebot.utils.restart import set_restart_notice_to_env


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """通过 `os.execv` 原地重启当前进程。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    message = ctx.msg
    set_restart_notice_to_env(channel=message.channel, chat_id=message.chat_id)

    async def _do_restart() -> None:
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "elebot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(
        channel=message.channel,
        chat_id=message.chat_id,
        content="正在重启……",
        metadata=dict(message.metadata or {}),
    )


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """生成当前会话的状态消息。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    snapshot = await ctx.loop.build_status_snapshot(ctx.key)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=snapshot.version,
            model=snapshot.model,
            start_time=snapshot.start_time,
            last_usage=snapshot.last_usage,
            context_window_tokens=snapshot.context_window_tokens,
            session_msg_count=snapshot.session_msg_count,
            context_tokens_estimate=snapshot.context_tokens_estimate,
            search_usage_text=snapshot.search_usage_text,
        ),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """返回可用 slash 命令列表。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    from elebot.command.builtin import build_help_text

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_help_text(),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )
