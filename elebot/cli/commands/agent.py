"""agent 命令。"""

from __future__ import annotations

import asyncio

import typer
from loguru import logger

from elebot.cli.render import print_agent_response, print_cli_progress_line
from elebot.cli.runtime_support import _load_runtime_config, _make_runtime
from elebot.cli.stream import StreamRenderer
from elebot.utils.restart import (
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)
from elebot.utils.workspace import sync_workspace_templates


def register_agent_command(app: typer.Typer) -> None:
    """注册 agent 命令。

    参数:
        app: 根 `Typer` 应用实例。

    返回:
        无返回值。
    """

    @app.command()
    def agent(
        message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
        session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
        logs: bool = typer.Option(False, "--logs/--no-logs", help="Show elebot runtime logs during chat"),
    ) -> None:
        """直接与主代理交互。

        参数:
            message: 一次性发送给代理的消息。
            session_id: 会话标识。
            workspace: 工作区覆盖路径。
            config: 配置文件路径。
            markdown: 是否按 Markdown 渲染回复。
            logs: 是否显示运行日志。

        返回:
            无返回值。
        """
        loaded_config = _load_runtime_config(config, workspace)
        sync_workspace_templates(loaded_config.workspace_path)

        if logs:
            logger.enable("elebot")
        else:
            logger.disable("elebot")

        runtime = _make_runtime(loaded_config)

        restart_notice = consume_restart_notice_from_env()
        if restart_notice and should_show_cli_restart_notice(restart_notice, session_id):
            print_agent_response(
                format_restart_completed_message(restart_notice.started_at_raw),
                render_markdown=False,
            )

        thinking = None

        async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
            del tool_hint
            print_cli_progress_line(content, thinking)

        if message:
            async def run_once() -> None:
                """执行单次 CLI 直连对话。

                返回:
                    无返回值。
                """
                nonlocal thinking
                renderer = StreamRenderer(render_markdown=markdown)
                thinking = renderer.spinner
                response = await runtime.run_once(
                    message,
                    session_id=session_id,
                    on_progress=_cli_progress,
                    on_stream=renderer.on_delta,
                    on_stream_end=renderer.on_end,
                )
                if not renderer.streamed:
                    await renderer.close()
                    print_agent_response(
                        response.content if response else "",
                        render_markdown=markdown,
                        metadata=response.metadata if response else None,
                    )
                thinking = None
                await runtime.close()

            asyncio.run(run_once())
        else:
            asyncio.run(runtime.run_interactive(session_id=session_id, markdown=markdown))
