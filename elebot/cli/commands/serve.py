"""`elebot serve` 命令组。"""

from __future__ import annotations

import asyncio

import typer
from loguru import logger

from elebot.channels import ChannelManager
from elebot.cli.runtime_support import _load_runtime_config, _make_runtime
from elebot.cli.serve_stdio import StdioServer
from elebot.utils.workspace import sync_workspace_templates


def register_serve_command(app: typer.Typer) -> None:
    """注册 `serve` 命令组。"""
    serve_app = typer.Typer(help="Scriptable runtime entrypoints")

    async def _run_channel_manager(loaded_config, *, websocket_only: bool = False) -> None:
        """按当前配置启动 channel manager。

        参数:
            loaded_config: 已解析完成的配置对象。
            websocket_only: 是否只启动 websocket。

        返回:
            无返回值。
        """
        runtime = _make_runtime(loaded_config, silent=True)
        manager_config = loaded_config.model_copy(deep=True)
        if websocket_only:
            manager_config.channels.websocket.enabled = True
            manager_config.channels.weixin.enabled = False
        manager = ChannelManager(manager_config, runtime)
        await runtime.start()
        await manager.start_all()
        try:
            await manager.wait()
        finally:
            await manager.stop_all()
            await runtime.close()

    @serve_app.command("stdio")
    def serve_stdio(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        logs: bool = typer.Option(False, "--logs/--no-logs", help="Show elebot runtime logs"),
    ) -> None:
        """启动基于 stdin/stdout 的 JSONL 协议入口。"""
        loaded_config = _load_runtime_config(config, workspace, silent=True)
        sync_workspace_templates(loaded_config.workspace_path, silent=True)

        if logs:
            logger.enable("elebot")
        else:
            logger.disable("elebot")

        runtime = _make_runtime(loaded_config, silent=True)
        asyncio.run(StdioServer(runtime).serve())

    @serve_app.command("channels")
    def serve_channels(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        logs: bool = typer.Option(False, "--logs/--no-logs", help="Show elebot runtime logs"),
    ) -> None:
        """启动所有已启用的内置 channel。"""
        loaded_config = _load_runtime_config(config, workspace, silent=True)
        sync_workspace_templates(loaded_config.workspace_path, silent=True)

        if logs:
            logger.enable("elebot")
        else:
            logger.disable("elebot")

        asyncio.run(_run_channel_manager(loaded_config))

    @serve_app.command("websocket")
    def serve_websocket(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        logs: bool = typer.Option(False, "--logs/--no-logs", help="Show elebot runtime logs"),
    ) -> None:
        """启动本机 websocket channel。"""
        loaded_config = _load_runtime_config(config, workspace, silent=True)
        loaded_config.channels.websocket.enabled = True
        sync_workspace_templates(loaded_config.workspace_path, silent=True)

        if logs:
            logger.enable("elebot")
        else:
            logger.disable("elebot")

        asyncio.run(_run_channel_manager(loaded_config, websocket_only=True))

    app.add_typer(serve_app, name="serve")
