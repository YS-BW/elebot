"""终端交互期间的按键监听辅助。"""

from __future__ import annotations

import asyncio
import os
import select
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

_ESCAPE_SEQUENCE_PREFIXES = {b"[", b"O", b"]", b"P", b"^", b"_"}


def _is_final_csi_byte(chunk: bytes) -> bool:
    """判断字节是否是 ANSI/CSI 控制序列的终止字节。

    参数:
        chunk: 单个字节数据。

    返回:
        如果是 CSI 终止字节则返回 ``True``，否则返回 ``False``。
    """
    if not chunk:
        return False
    return 0x40 <= chunk[0] <= 0x7E


def _drain_csi_sequence(
    *,
    read_byte: Callable[[], bytes],
    wait_for_byte: Callable[[float], bool],
    is_closed: Callable[[], bool],
    sequence_timeout: float,
) -> None:
    """消费完整的 CSI 控制序列，避免残留到下一次输入。

    参数:
        read_byte: 读取一个字节的回调。
        wait_for_byte: 等待后续字节是否到达的回调。
        is_closed: 判断监听器是否已关闭的回调。
        sequence_timeout: 等待序列后续字节的超时时间。

    返回:
        无返回值。
    """
    while not is_closed() and wait_for_byte(sequence_timeout):
        chunk = read_byte()
        if not chunk:
            return
        if _is_final_csi_byte(chunk):
            return


def _drain_ss3_sequence(
    *,
    read_byte: Callable[[], bytes],
    wait_for_byte: Callable[[float], bool],
    is_closed: Callable[[], bool],
    sequence_timeout: float,
) -> None:
    """消费 SS3 控制序列，例如方向键和功能键。

    参数:
        read_byte: 读取一个字节的回调。
        wait_for_byte: 等待后续字节是否到达的回调。
        is_closed: 判断监听器是否已关闭的回调。
        sequence_timeout: 等待序列后续字节的超时时间。

    返回:
        无返回值。
    """
    while not is_closed() and wait_for_byte(sequence_timeout):
        chunk = read_byte()
        if not chunk:
            return
        if _is_final_csi_byte(chunk):
            return


def _drain_string_escape_sequence(
    *,
    read_byte: Callable[[], bytes],
    wait_for_byte: Callable[[float], bool],
    is_closed: Callable[[], bool],
    sequence_timeout: float,
) -> None:
    """消费以 `BEL` 或 `ST` 结尾的字符串型控制序列。

    参数:
        read_byte: 读取一个字节的回调。
        wait_for_byte: 等待后续字节是否到达的回调。
        is_closed: 判断监听器是否已关闭的回调。
        sequence_timeout: 等待序列后续字节的超时时间。

    返回:
        无返回值。
    """
    saw_escape = False
    while not is_closed() and wait_for_byte(sequence_timeout):
        chunk = read_byte()
        if not chunk:
            return
        if saw_escape:
            if chunk == b"\\":
                return
            saw_escape = chunk == b"\x1b"
            continue
        if chunk == b"\x07":
            return
        saw_escape = chunk == b"\x1b"


def _drain_generic_escape_bytes(
    *,
    read_byte: Callable[[], bytes],
    wait_for_byte: Callable[[float], bool],
    is_closed: Callable[[], bool],
    sequence_timeout: float,
) -> None:
    """消费未明确分类的 `Esc` 后续字节，避免半截残留。

    参数:
        read_byte: 读取一个字节的回调。
        wait_for_byte: 等待后续字节是否到达的回调。
        is_closed: 判断监听器是否已关闭的回调。
        sequence_timeout: 等待序列后续字节的超时时间。

    返回:
        无返回值。
    """
    while not is_closed() and wait_for_byte(sequence_timeout):
        if not read_byte():
            return


def _consume_escape_follow_up(
    *,
    first_byte: bytes,
    read_byte: Callable[[], bytes],
    wait_for_byte: Callable[[float], bool],
    is_closed: Callable[[], bool],
    sequence_timeout: float,
) -> None:
    """消费 `Esc` 之后的控制序列剩余字节。

    参数:
        first_byte: `Esc` 后紧跟的第一个字节。
        read_byte: 读取一个字节的回调。
        wait_for_byte: 等待后续字节是否到达的回调。
        is_closed: 判断监听器是否已关闭的回调。
        sequence_timeout: 等待序列后续字节的超时时间。

    返回:
        无返回值。
    """
    if first_byte == b"[":
        _drain_csi_sequence(
            read_byte=read_byte,
            wait_for_byte=wait_for_byte,
            is_closed=is_closed,
            sequence_timeout=sequence_timeout,
        )
        return
    if first_byte == b"O":
        _drain_ss3_sequence(
            read_byte=read_byte,
            wait_for_byte=wait_for_byte,
            is_closed=is_closed,
            sequence_timeout=sequence_timeout,
        )
        return
    if first_byte in {b"]", b"P", b"^", b"_"}:
        _drain_string_escape_sequence(
            read_byte=read_byte,
            wait_for_byte=wait_for_byte,
            is_closed=is_closed,
            sequence_timeout=sequence_timeout,
        )
        return
    _drain_generic_escape_bytes(
        read_byte=read_byte,
        wait_for_byte=wait_for_byte,
        is_closed=is_closed,
        sequence_timeout=sequence_timeout,
    )


def _is_standalone_escape(
    *,
    read_byte: Callable[[], bytes],
    wait_for_byte: Callable[[float], bool],
    is_closed: Callable[[], bool],
    sequence_timeout: float,
) -> bool:
    """判断刚读到的 `Esc` 是否是真实的用户中断键。

    参数:
        read_byte: 读取一个字节的回调。
        wait_for_byte: 等待后续字节是否到达的回调。
        is_closed: 判断监听器是否已关闭的回调。
        sequence_timeout: 用来区分孤立 `Esc` 与控制序列的短暂窗口。

    返回:
        如果当前 `Esc` 是独立按键则返回 ``True``，否则返回 ``False``。
    """
    if is_closed():
        return False
    if not wait_for_byte(sequence_timeout):
        return True

    next_byte = read_byte()
    if not next_byte:
        return False

    if next_byte in _ESCAPE_SEQUENCE_PREFIXES:
        _consume_escape_follow_up(
            first_byte=next_byte,
            read_byte=read_byte,
            wait_for_byte=wait_for_byte,
            is_closed=is_closed,
            sequence_timeout=sequence_timeout,
        )
        return False

    _drain_generic_escape_bytes(
        read_byte=read_byte,
        wait_for_byte=wait_for_byte,
        is_closed=is_closed,
        sequence_timeout=sequence_timeout,
    )
    return False


class EscInterruptWatcher:
    """在活跃回复期间监听终端 `Esc` 按键。"""

    def __init__(
        self,
        poll_interval: float = 0.1,
        sequence_timeout: float = 0.03,
    ) -> None:
        """初始化按键监听器。

        参数:
            poll_interval: 阻塞轮询 stdin 的间隔秒数。
            sequence_timeout: 判断孤立 `Esc` 的短暂等待窗口秒数。

        返回:
            无返回值。
        """
        self._poll_interval = poll_interval
        self._sequence_timeout = sequence_timeout
        self._closed = threading.Event()

    async def wait(self) -> bool:
        """等待用户按下真实的 `Esc` 中断键。

        参数:
            无。

        返回:
            探测到真实 `Esc` 时返回 ``True``；监听不可用或被关闭时返回 ``False``。
        """
        return await asyncio.to_thread(self._wait_blocking)

    def close(self) -> None:
        """请求停止监听器。

        参数:
            无。

        返回:
            无返回值。
        """
        self._closed.set()

    def _get_stdin_fd(self) -> int | None:
        """获取标准输入文件描述符。

        参数:
            无。

        返回:
            成功时返回文件描述符，失败时返回 ``None``。
        """
        try:
            return sys.stdin.fileno()
        except Exception:
            return None

    def _is_tty(self, stdin_fd: int) -> bool:
        """判断当前标准输入是否是可交互终端。

        参数:
            stdin_fd: 标准输入文件描述符。

        返回:
            是 TTY 时返回 ``True``，否则返回 ``False``。
        """
        return os.isatty(stdin_fd)

    def _enter_cbreak_mode(self, stdin_fd: int) -> Any | None:
        """把终端切到 cbreak 模式，并返回原始属性。

        参数:
            stdin_fd: 标准输入文件描述符。

        返回:
            成功时返回原始终端属性，失败时返回 ``None``。
        """
        import termios
        import tty

        original_attrs = termios.tcgetattr(stdin_fd)
        tty.setcbreak(stdin_fd)
        return original_attrs

    def _restore_terminal_mode(self, stdin_fd: int, original_attrs: Any | None) -> None:
        """恢复终端原始模式。

        参数:
            stdin_fd: 标准输入文件描述符。
            original_attrs: 之前保存的终端属性。

        返回:
            无返回值。
        """
        if original_attrs is None:
            return
        try:
            import termios

            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, original_attrs)
        except Exception:
            return

    def _wait_for_input(self, stdin_fd: int, timeout: float) -> bool:
        """等待标准输入在给定时间内变为可读。

        参数:
            stdin_fd: 标准输入文件描述符。
            timeout: 最长等待秒数。

        返回:
            可读时返回 ``True``，超时或关闭时返回 ``False``。
        """
        deadline = time.monotonic() + timeout
        while not self._closed.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            ready, _, _ = select.select([stdin_fd], [], [], min(self._poll_interval, remaining))
            if ready:
                return True
        return False

    def _read_byte(self, stdin_fd: int) -> bytes:
        """从标准输入读取一个字节。

        参数:
            stdin_fd: 标准输入文件描述符。

        返回:
            读取到的字节；EOF 时返回空字节串。
        """
        return os.read(stdin_fd, 1)

    def _wait_blocking(self) -> bool:
        """在阻塞终端读取循环里等待真实的 `Esc` 中断。"""
        stdin_fd = self._get_stdin_fd()
        if stdin_fd is None or not self._is_tty(stdin_fd):
            return False

        original_attrs: Any | None = None
        try:
            original_attrs = self._enter_cbreak_mode(stdin_fd)
            while not self._closed.is_set():
                if not self._wait_for_input(stdin_fd, self._poll_interval):
                    continue
                chunk = self._read_byte(stdin_fd)
                if not chunk:
                    return False
                if chunk != b"\x1b":
                    continue
                if _is_standalone_escape(
                    read_byte=lambda: self._read_byte(stdin_fd),
                    wait_for_byte=lambda timeout: self._wait_for_input(stdin_fd, timeout),
                    is_closed=self._closed.is_set,
                    sequence_timeout=self._sequence_timeout,
                ):
                    return True
            return False
        except Exception:
            return False
        finally:
            self._restore_terminal_mode(stdin_fd, original_attrs)


def create_interrupt_watcher() -> EscInterruptWatcher | None:
    """在可用时创建默认的 `Esc` 监听器。

    参数:
        无。

    返回:
        支持 TTY 时返回监听器，否则返回 ``None``。
    """
    try:
        stdin_fd = sys.stdin.fileno()
    except Exception:
        return None
    if not os.isatty(stdin_fd):
        return None
    return EscInterruptWatcher()
