"""负责 CLI 流式渲染与 spinner。"""

from __future__ import annotations

import sys
import time
from contextlib import nullcontext

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
        """初始化思考中 spinner。

        参数:
            console: 可选的输出终端对象。

        返回:
            无返回值。
        """
        terminal_console = console or _make_console()
        self._spinner = terminal_console.status("[dim]elebot is thinking...[/dim]", spinner="dots")
        self._active = False

    @property
    def active(self) -> bool:
        """返回当前 spinner 是否处于显示状态。"""
        return self._active

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def start(self) -> None:
        """启动 spinner；重复调用时保持幂等。"""
        if self._active:
            return
        self._spinner.start()
        self._active = True

    def stop(self) -> None:
        """停止 spinner；重复调用时保持幂等。"""
        if not self._active:
            return
        self._spinner.stop()
        self._active = False

    def pause(self):
        """返回一个上下文管理器，在额外输出时临时停掉 spinner。"""
        from contextlib import contextmanager

        @contextmanager
        def _context():
            was_active = self._active
            if was_active:
                self._spinner.stop()
            try:
                yield
            finally:
                if was_active:
                    self._spinner.start()

        return _context()


class StreamRenderer:
    """以 Rich Live 渲染流式回复，并在首个可见 token 前展示 spinner。"""

    def __init__(self, render_markdown: bool = True, show_spinner: bool = True):
        """初始化流式渲染器。

        参数:
            render_markdown: 是否按 Markdown 渲染回复。
            show_spinner: 是否在首个可见 token 前显示 spinner。

        返回:
            无返回值。
        """
        self._render_markdown = render_markdown
        self._show_spinner = show_spinner
        self._buffer = ""
        self._live: Live | None = None
        self._last_refresh_at = 0.0
        self.streamed = False
        self._console = _make_console()
        self._spinner: ThinkingSpinner | None = (
            ThinkingSpinner(console=self._console) if self._show_spinner else None
        )
        self._ensure_spinner()

    def _render(self, content: str | None = None):
        text = self._buffer if content is None else content
        return Markdown(text) if self._render_markdown and text else Text(text or "")

    def _has_visible_buffer(self) -> bool:
        """判断当前缓冲里是否已有可见正文。"""
        return bool(self._buffer.strip())

    def _pause_spinner(self):
        """在额外输出前短暂停掉 spinner，避免和正文或提示行抢光标。"""
        if self._spinner and self._spinner.active:
            return self._spinner.pause()
        return nullcontext()

    def _ensure_spinner(self) -> None:
        """在当前不是正文流阶段时保持 spinner 可见。"""
        if self._live is not None:
            return
        if self._spinner:
            self._spinner.start()

    def _hide_spinner(self) -> None:
        """在进入正文流或结束 turn 时隐藏 spinner。"""
        if self._spinner:
            self._spinner.stop()

    def _start_live(self) -> None:
        """把当前缓冲升级为正式 assistant 流式输出。"""
        if self._live is not None:
            return
        self._hide_spinner()
        self._console.print(f"[cyan]{__logo__} elebot[/cyan]")
        self._live = Live(self._render(), console=self._console, auto_refresh=False)
        self._live.start()

    def _print_progress_line(self, text: str) -> None:
        with self._pause_spinner():
            self._console.print(f"  [dim]↳ {text}[/dim]")

    async def on_delta(self, delta: str) -> None:
        """接收增量文本，并按节流策略刷新 Live 视图。"""
        self.streamed = True
        self._buffer += delta
        if self._live is None and self._has_visible_buffer():
            self._start_live()
        if self._live is None:
            return
        now = time.monotonic()
        if self._last_refresh_at == 0.0 or "\n" in delta or (now - self._last_refresh_at) > 0.05:
            self._live.update(self._render())
            self._live.refresh()
            self._last_refresh_at = now

    async def on_end(self, *, resuming: bool = False) -> None:
        """结束当前流式渲染；恢复续写时保持同一个 spinner 继续显示。"""
        had_live = self._live is not None
        if self._live:
            self._live.update(self._render())
            self._live.refresh()
            self._live.stop()
            self._live = None
        self._last_refresh_at = 0.0
        self._buffer = ""
        if resuming:
            self._ensure_spinner()
            return
        self._hide_spinner()
        if had_live:
            self._console.print()

    async def on_progress(self, text: str) -> None:
        """输出当前轮次的普通进度提示。"""
        self._ensure_spinner()
        self._print_progress_line(text)

    async def on_tool_transition(self, text: str) -> None:
        """输出工具交接提示，并保持后续 spinner 连续。"""
        self._ensure_spinner()
        self._print_progress_line(text)

    def stop_for_input(self) -> None:
        """在读取下一次用户输入前停掉 spinner，避免 prompt_toolkit 冲突。"""
        self._hide_spinner()

    async def close(self) -> None:
        """在没有完整流式轮次时关闭 Live 和 spinner。"""
        if self._live:
            self._live.stop()
            self._live = None
        self._hide_spinner()
        self._buffer = ""
        self._last_refresh_at = 0.0
