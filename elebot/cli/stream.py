"""负责 CLI 流式渲染与 spinner。"""

from __future__ import annotations

import sys
import time

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from elebot import __logo__


def _make_console() -> Console:
    """为流式输出创建强制 ANSI 的 Console，避免 Live 在重定向下失效。"""
    return Console(file=sys.stdout, force_terminal=True)


class ThinkingSpinner:
    """封装 CLI 思考 spinner，并支持临时暂停。"""

    def __init__(self, console: Console | None = None):
        terminal_console = console or _make_console()
        self._spinner = terminal_console.status("[dim]elebot is thinking...[/dim]", spinner="dots")
        self._active = False

    def __enter__(self):
        self._spinner.start()
        self._active = True
        return self

    def __exit__(self, *exc):
        self._active = False
        self._spinner.stop()
        return False

    def pause(self):
        """返回一个上下文管理器，在额外输出时临时停掉 spinner。"""
        from contextlib import contextmanager

        @contextmanager
        def _context():
            if self._spinner and self._active:
                self._spinner.stop()
            try:
                yield
            finally:
                if self._spinner and self._active:
                    self._spinner.start()

        return _context()


class StreamRenderer:
    """以 Rich Live 渲染流式回复，并在首个可见 token 前展示 spinner。"""

    def __init__(self, render_markdown: bool = True, show_spinner: bool = True):
        self._render_markdown = render_markdown
        self._show_spinner = show_spinner
        self._buffer = ""
        self._live: Live | None = None
        self._last_refresh_at = 0.0
        self.streamed = False
        self._spinner: ThinkingSpinner | None = None
        self._start_spinner()

    @property
    def spinner(self) -> ThinkingSpinner | None:
        """暴露当前 spinner，供进度输出在打印前安全暂停。"""
        return self._spinner

    def _render(self):
        return Markdown(self._buffer) if self._render_markdown and self._buffer else Text(self._buffer or "")

    def _start_spinner(self) -> None:
        if self._show_spinner:
            self._spinner = ThinkingSpinner()
            self._spinner.__enter__()

    def _stop_spinner(self) -> None:
        if self._spinner:
            self._spinner.__exit__(None, None, None)
            self._spinner = None

    async def on_delta(self, delta: str) -> None:
        """接收增量文本，并按节流策略刷新 Live 视图。"""
        self.streamed = True
        self._buffer += delta
        if self._live is None:
            if not self._buffer.strip():
                return
            self._stop_spinner()
            terminal_console = _make_console()
            terminal_console.print()
            terminal_console.print(f"[cyan]{__logo__} elebot[/cyan]")
            self._live = Live(self._render(), console=terminal_console, auto_refresh=False)
            self._live.start()
        now = time.monotonic()
        if "\n" in delta or (now - self._last_refresh_at) > 0.05:
            self._live.update(self._render())
            self._live.refresh()
            self._last_refresh_at = now

    async def on_end(self, *, resuming: bool = False) -> None:
        """结束当前流式渲染；恢复续写时重新拉起 spinner。"""
        if self._live:
            self._live.update(self._render())
            self._live.refresh()
            self._live.stop()
            self._live = None
        self._stop_spinner()
        if resuming:
            self._buffer = ""
            self._start_spinner()
        else:
            _make_console().print()

    def stop_for_input(self) -> None:
        """在读取下一次用户输入前停掉 spinner，避免 prompt_toolkit 冲突。"""
        self._stop_spinner()

    async def close(self) -> None:
        """在没有完整流式轮次时关闭 Live 和 spinner。"""
        if self._live:
            self._live.stop()
            self._live = None
        self._stop_spinner()
