"""status 命令。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.table import Table

from elebot import __logo__
from elebot.cli.render import console
from elebot.cli.commands.weixin import (
    get_channel_service_owner,
    get_channel_service_state,
    list_channel_service_pids,
    resolve_weixin_state_path,
)


def _format_home_path(path: Path) -> str:
    """把家目录下的绝对路径压缩成 `~` 开头。"""
    try:
        return str(path).replace(str(Path.home()), "~", 1)
    except Exception:
        return str(path)


def _render_status_table(rows: list[tuple[str, str, str]]) -> None:
    """按三列统一渲染状态表。"""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("字段", style="cyan", no_wrap=True)
    table.add_column("当前值", style="white")
    table.add_column("说明", style="white")
    for key, value, desc in rows:
        table.add_row(key, value, desc)
    console.print(table)


def register_status_command(app: typer.Typer) -> None:
    """注册 status 命令。

    参数:
        app: 根 `Typer` 应用实例。

    返回:
        无返回值。
    """

    @app.command()
    def status() -> None:
        """显示 EleBot 当前状态。

        返回:
            无返回值。
        """
        from elebot.config.loader import get_config_path, load_config
        from elebot.providers.registry import find_by_name

        config_path = get_config_path()
        config = load_config()
        workspace = config.workspace_path
        channel_enabled = config.channels.weixin.enabled
        channel_owner = "weixin" if channel_enabled else "-"
        weixin_state_path = resolve_weixin_state_path(config)
        channel_logged_in = bool(str(config.channels.weixin.token or "").strip()) or weixin_state_path.exists()
        service_state, service_pid = get_channel_service_state()
        service_pids = list_channel_service_pids()
        service_log_path = Path.home() / ".elebot" / "logs" / "channels-service.log"
        channel_uptime = ""

        provider_spec = find_by_name(config.agents.defaults.provider)
        provider_label = provider_spec.label if provider_spec is not None else config.agents.defaults.provider

        if service_pid is not None:
            if service_state == "running":
                try:
                    started_at = datetime.fromtimestamp(Path(f'/proc/{service_pid}').stat().st_ctime)
                except Exception:
                    try:
                        import subprocess

                        output = subprocess.check_output(
                            ["ps", "-p", str(service_pid), "-o", "lstart="],
                            text=True,
                        ).strip()
                        if output:
                            started_at = datetime.strptime(output, "%a %b %d %H:%M:%S %Y")
                        else:
                            started_at = None
                    except Exception:
                        started_at = None
                if started_at is not None:
                    duration = datetime.now() - started_at
                    seconds = int(duration.total_seconds())
                    hours, remainder = divmod(seconds, 3600)
                    minutes, secs = divmod(remainder, 60)
                    channel_uptime = f"{hours}h {minutes}m {secs}s"

        console.print(f"{__logo__} elebot Status\n")
        workspace_value = _format_home_path(workspace) if workspace.exists() else "不存在"
        config_value = _format_home_path(config_path)
        log_value = _format_home_path(service_log_path)
        running_value = "yes" if service_state == "running" else "no"
        enabled_value = "yes" if channel_enabled else "no"
        logged_in_value = "yes" if channel_logged_in else "no"

        _render_status_table(
            [
                ("Config", config_value, "当前加载的配置文件路径"),
                ("Workspace", workspace_value, "当前工作区目录状态"),
                ("Provider", config.agents.defaults.provider, "当前默认模型提供方"),
                ("Model", config.agents.defaults.model, "当前默认对话模型"),
                ("Timezone", config.agents.defaults.timezone, "agent 默认使用的时区"),
                ("Channel Enabled", enabled_value, "是否启用了外部 channel 入口"),
                ("Channel Owner", channel_owner, "当前唯一 channel 的实现 owner"),
                ("Channel Running", running_value, "当前是否有 channel 服务正在运行"),
                ("Channel Logged In", logged_in_value, "当前是否已有可用登录态"),
                ("Channel Uptime", channel_uptime or "-", "当前运行时长；未运行时为空"),
                ("Channel Log", log_value, "后台服务日志文件路径"),
            ],
        )
