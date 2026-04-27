"""status 命令。"""

from __future__ import annotations

import typer

from elebot import __logo__
from elebot.cli.render import console


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
        from elebot.providers.registry import PROVIDERS

        config_path = get_config_path()
        config = load_config()
        workspace = config.workspace_path

        console.print(f"{__logo__} elebot Status\n")
        console.print(
            f"Config: {config_path} "
            f"{'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
        )
        console.print(
            f"Workspace: {workspace} "
            f"{'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
        )

        if config_path.exists():
            console.print(f"Model: {config.agents.defaults.model}")
            for spec in PROVIDERS:
                provider_config = getattr(config.providers, spec.name, None)
                if provider_config is None:
                    continue
                if spec.is_local:
                    if provider_config.api_base:
                        console.print(f"{spec.label}: [green]✓ {provider_config.api_base}[/green]")
                    else:
                        console.print(f"{spec.label}: [dim]not set[/dim]")
                    continue
                has_key = bool(provider_config.api_key)
                console.print(
                    f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
                )
