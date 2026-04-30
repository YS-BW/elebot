"""CLI 复用的 runtime 装配与错误包装。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from elebot.agent.loop import AgentLoop
from elebot.bus.queue import MessageBus
from elebot.cli.render import console
from elebot.config.schema import Config
from elebot.providers.factory import build_provider
from elebot.runtime import ElebotRuntime


def _make_provider(config: Config, *, silent: bool = False):
    """根据当前配置实例化对应的 LLM 提供方。

    参数:
        config: 已解析完成的运行时配置。

    返回:
        配置好默认生成参数的提供方实例。
    """
    try:
        return build_provider(config)
    except ValueError as exc:
        if not silent:
            console.print(f"[red]Error: {exc}[/red]")
        text = str(exc)
        if "No API key configured" in text:
            if not silent:
                console.print("Set one in ~/.elebot/config.json under providers section")
        if "Azure OpenAI requires" in text:
            if not silent:
                console.print("Set them in ~/.elebot/config.json under providers.azure_openai section")
                console.print("Use the model field to specify the deployment name.")
        raise typer.Exit(1) from exc


def _load_runtime_config(
    config: str | None = None,
    workspace: str | None = None,
    *,
    silent: bool = False,
) -> Config:
    """加载运行时配置，并按需覆盖当前工作区。

    参数:
        config: 可选的配置文件路径。
        workspace: 可选的工作区覆盖路径。

    返回:
        解析并展开环境变量后的配置对象。
    """
    from elebot.config.loader import load_config, resolve_config_env_vars, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            if not silent:
                console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        if not silent:
            console.print(f"[dim]Using config: {config_path}[/dim]")

    try:
        loaded = resolve_config_env_vars(load_config(config_path))
    except ValueError as exc:
        if not silent:
            console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)
    _warn_deprecated_config_keys(config_path, silent=silent)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


def _make_runtime(config: Config, *, silent: bool = False):
    """根据当前配置装配一份 CLI 复用的 runtime。

    参数:
        config: 已解析完成的运行时配置。

    返回:
        供 CLI 启动或单次调用的 runtime 实例。
    """
    provider_builder = _make_provider if not silent else lambda cfg: _make_provider(cfg, silent=True)

    return ElebotRuntime.from_config(
        config,
        provider_builder=provider_builder,
        bus_factory=MessageBus,
        agent_loop_factory=AgentLoop,
    )


def _warn_deprecated_config_keys(config_path: Path | None, *, silent: bool = False) -> None:
    """提示用户移除已经废弃的配置键。

    参数:
        config_path: 当前命令解析出的配置文件路径；为空时回退到默认路径。

    返回:
        无返回值。
    """
    from elebot.config.loader import get_config_path

    path = config_path or get_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if "memoryWindow" in raw.get("agents", {}).get("defaults", {}):
        if not silent:
            console.print(
                "[dim]Hint: `memoryWindow` in your config is no longer used "
                "and can be safely removed.[/dim]"
            )
