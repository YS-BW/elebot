"""Slash 命令路由导出。"""

from elebot.command.builtin import register_builtin_commands
from elebot.command.router import CommandContext, CommandRouter

__all__ = ["CommandContext", "CommandRouter", "register_builtin_commands"]
