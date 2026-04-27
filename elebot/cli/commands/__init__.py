"""CLI 命令注册入口。"""

from __future__ import annotations

import typer

from elebot.cli.commands.agent import register_agent_command
from elebot.cli.commands.onboard import register_onboard_command
from elebot.cli.commands.status import register_status_command


def register_commands(app: typer.Typer) -> None:
    """向根 CLI 注册当前保留的命令。

    参数:
        app: 根 `Typer` 应用实例。

    返回:
        无返回值。
    """
    register_onboard_command(app)
    register_agent_command(app)
    register_status_command(app)
