"""管理 CLI 历史记录与终端输入安全。"""

from __future__ import annotations

import os
import select
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout


class SafeFileHistory(FileHistory):
    """写入历史前清洗代理项，避免 prompt_toolkit 落盘时报错。"""

    def store_string(self, string: str) -> None:
        """写入历史记录前先替换非法 UTF-8 代理项。

        参数:
            string: 待写入的历史文本。

        返回:
            无返回值。
        """
        safe_text = string.encode("utf-8", errors="surrogateescape").decode(
            "utf-8", errors="replace"
        )
        super().store_string(safe_text)


_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None


def flush_pending_tty_input() -> None:
    """清空模型输出期间堆积的按键，避免它们污染下一次输入。"""
    try:
        stdin_fd = sys.stdin.fileno()
        if not os.isatty(stdin_fd):
            return
    except Exception:
        return

    try:
        import termios

        termios.tcflush(stdin_fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([stdin_fd], [], [], 0)
            if not ready:
                break
            if not os.read(stdin_fd, 4096):
                break
    except Exception:
        return


def restore_terminal() -> None:
    """恢复终端原始状态，避免回显和行缓冲被 prompt_toolkit 留脏。"""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def init_prompt_session() -> None:
    """初始化带持久化历史的 prompt_toolkit 会话。"""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from elebot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=SafeFileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,
    )


async def read_interactive_input_async() -> str:
    """读取一行交互输入，并把 EOF 统一转换成退出信号。"""
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call init_prompt_session() first")

    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc
