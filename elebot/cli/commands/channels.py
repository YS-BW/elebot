"""`elebot channels` 命令组。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from elebot.bus.queue import MessageBus
from elebot.channels.weixin import WeixinChannel
from elebot.config.loader import load_config, resolve_config_env_vars, set_config_path
from elebot.runtime.models import InterruptResult, RuntimeStatusSnapshot


class _ChannelLoginRuntime:
    """给 channel 登录流程使用的最小 runtime stub。"""

    def __init__(self) -> None:
        """初始化最小 bus 持有者。"""
        self.bus = MessageBus()

    def interrupt_session(
        self,
        session_id: str,
        reason: str = "user_interrupt",
    ) -> InterruptResult:
        """登录流程不会使用中断控制面。"""
        return InterruptResult(
            session_id=session_id,
            reason=reason,
            accepted=False,
            cancelled_tasks=0,
            already_interrupting=False,
        )

    def reset_session(self, session_id: str) -> None:
        """登录流程不会使用会话重置。"""
        del session_id

    async def get_status_snapshot(self, session_id: str) -> RuntimeStatusSnapshot:
        """登录流程不会使用状态查询。"""
        del session_id
        raise RuntimeError("status snapshot is not available during channel login")


def register_channels_command(app: typer.Typer) -> None:
    """注册 `channels` 命令组。

    参数:
        app: 根 `Typer` 应用实例。

    返回:
        无返回值。
    """
    channels_app = typer.Typer(help="Manage built-in channels")

    @channels_app.command("login")
    def login(
        channel_name: str = typer.Argument(..., help="Channel name"),
        force: bool = typer.Option(False, "--force", "-f", help="Force re-authentication"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """执行内置 channel 的交互式登录。"""
        resolved_config_path = Path(config).expanduser().resolve() if config else None
        if resolved_config_path is not None:
            set_config_path(resolved_config_path)

        if channel_name != "weixin":
            raise typer.BadParameter("Only 'weixin' is supported in this command")

        loaded_config = resolve_config_env_vars(load_config(resolved_config_path))
        runtime = _ChannelLoginRuntime()
        channel = WeixinChannel(loaded_config.channels.weixin, runtime)
        success = asyncio.run(channel.login(force=force))
        if not success:
            raise typer.Exit(1)

    app.add_typer(channels_app, name="channels")
