"""负责 CLI 的 Rich 输出渲染。"""

from __future__ import annotations

import sys
from contextlib import nullcontext
from typing import Any, Callable

from prompt_toolkit import print_formatted_text
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.formatted_text import ANSI
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from elebot import __logo__
from elebot.cli.stream import ThinkingSpinner

console = Console()


def make_console() -> Console:
    """创建绑定到 stdout 的 Console，避免被测试或重定向影响。"""
    return Console(file=sys.stdout)


def response_renderable(
    content: str,
    render_markdown: bool,
    metadata: dict[str, Any] | None = None,
):
    """根据返回元数据决定按 Markdown 还是纯文本渲染。"""
    if not render_markdown:
        return Text(content)
    if (metadata or {}).get("render_as") == "text":
        return Text(content)
    return Markdown(content)


def render_interactive_ansi(render_fn: Callable[[Console], None]) -> str:
    """把 Rich 渲染成 ANSI，交给 prompt_toolkit 安全打印。"""
    ansi_console = Console(
        force_terminal=True,
        color_system=console.color_system or "standard",
        width=console.width,
    )
    with ansi_console.capture() as capture:
        render_fn(ansi_console)
    return capture.get()


def print_agent_response(
    response: str,
    render_markdown: bool,
    metadata: dict[str, Any] | None = None,
) -> None:
    """以统一样式打印助手完整回复。"""
    terminal_console = make_console()
    content = response or ""
    body = response_renderable(content, render_markdown, metadata)
    terminal_console.print(f"[cyan]{__logo__} elebot[/cyan]")
    terminal_console.print(body)
    terminal_console.print()


async def print_interactive_line(text: str) -> None:
    """在 prompt_toolkit 会话中打印一行补充信息。"""

    def _write() -> None:
        ansi = render_interactive_ansi(lambda ansi_console: ansi_console.print(f"  [dim]↳ {text}[/dim]"))
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


async def print_interactive_response(
    response: str,
    render_markdown: bool,
    metadata: dict[str, Any] | None = None,
) -> None:
    """在 prompt_toolkit 会话中打印完整回复。"""

    def _write() -> None:
        content = response or ""
        ansi = render_interactive_ansi(
            lambda ansi_console: (
                ansi_console.print(f"[cyan]{__logo__} elebot[/cyan]"),
                ansi_console.print(response_renderable(content, render_markdown, metadata)),
                ansi_console.print(),
            )
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


def print_cli_progress_line(text: str, thinking: ThinkingSpinner | None) -> None:
    """打印 CLI 进度行，并在需要时短暂停止 spinner。"""
    with thinking.pause() if thinking else nullcontext():
        console.print(f"  [dim]↳ {text}[/dim]")


async def print_interactive_progress_line(text: str, thinking: ThinkingSpinner | None) -> None:
    """打印交互模式进度行，并在需要时短暂停止 spinner。"""
    with thinking.pause() if thinking else nullcontext():
        await print_interactive_line(text)
