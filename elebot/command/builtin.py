"""内置 slash 命令协议与注册入口。"""

from __future__ import annotations

from elebot.command.handlers.dream import cmd_dream, cmd_dream_log, cmd_dream_restore
from elebot.command.handlers.runtime import cmd_help, cmd_restart, cmd_status
from elebot.command.handlers.session import cmd_new
from elebot.command.handlers.skills import cmd_skill_manage
from elebot.command.handlers.tasks import cmd_task_manage
from elebot.command.router import CommandRouter

SLASH_COMMAND_SPECS: list[tuple[str, str]] = [
    ("/new", "开始新会话"),
    ("/restart", "重启 elebot"),
    ("/status", "查看当前状态"),
    ("/dream", "手动触发 Dream 整理"),
    ("/dream-log", "查看最近一次 Dream 变更"),
    ("/dream-restore", "恢复到之前的 Dream 版本"),
    ("/skill list", "查看当前已安装 skills"),
    ("/skill install <source>", "安装一个 skill"),
    ("/skill uninstall <name>", "卸载一个 skill"),
    ("/task", "查看当前会话定时任务"),
    ("/task list", "列出全部定时任务"),
    ("/task remove <task_id>", "删除一个定时任务"),
    ("/help", "查看可用命令"),
]


def build_help_text() -> str:
    """构造各渠道共用的帮助文本。

    参数:
        无。

    返回:
        当前可用 slash 命令的展示文本。
    """
    lines = ["🍌 elebot 命令："]
    lines.extend(f"{command} — {description}" for command, description in SLASH_COMMAND_SPECS)
    return "\n".join(lines)


def register_builtin_commands(router: CommandRouter) -> None:
    """注册默认内置 slash 命令。

    参数:
        router: 当前命令路由器。

    返回:
        无返回值。
    """
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.prefix("/skill ", cmd_skill_manage)
    router.exact("/task", cmd_task_manage)
    router.prefix("/task ", cmd_task_manage)
    router.exact("/help", cmd_help)
