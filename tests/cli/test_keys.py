import asyncio
import time

import pytest

from elebot.cli.keys import EscInterruptWatcher, _is_standalone_escape


class _FakeEscapeStream:
    def __init__(self, chunks: bytes) -> None:
        self._chunks = [bytes([value]) for value in chunks]

    def wait_for_byte(self, _timeout: float) -> bool:
        return bool(self._chunks)

    def read_byte(self) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    @property
    def remaining(self) -> list[bytes]:
        return list(self._chunks)


class _TestWatcher(EscInterruptWatcher):
    def __init__(self) -> None:
        super().__init__(poll_interval=0.001, sequence_timeout=0.001)
        self.restored = False

    def _get_stdin_fd(self) -> int | None:
        return 0

    def _is_tty(self, stdin_fd: int) -> bool:
        return True

    def _enter_cbreak_mode(self, stdin_fd: int) -> object:
        return object()

    def _restore_terminal_mode(self, stdin_fd: int, original_attrs: object | None) -> None:
        if original_attrs is not None:
            self.restored = True

    def _wait_for_input(self, stdin_fd: int, timeout: float) -> bool:
        if self._closed.is_set():
            return False
        time.sleep(min(timeout, 0.001))
        return False

    def _read_byte(self, stdin_fd: int) -> bytes:
        return b""


class _BrokenTerminalWatcher(_TestWatcher):
    def _enter_cbreak_mode(self, stdin_fd: int) -> object:
        raise RuntimeError("unsupported terminal")


def test_isolated_escape_triggers_interrupt() -> None:
    stream = _FakeEscapeStream(b"")

    interrupted = _is_standalone_escape(
        read_byte=stream.read_byte,
        wait_for_byte=stream.wait_for_byte,
        is_closed=lambda: False,
        sequence_timeout=0.001,
    )

    assert interrupted is True


def test_cpr_sequence_is_consumed_without_interrupt() -> None:
    stream = _FakeEscapeStream(b"[38;1R")

    interrupted = _is_standalone_escape(
        read_byte=stream.read_byte,
        wait_for_byte=stream.wait_for_byte,
        is_closed=lambda: False,
        sequence_timeout=0.001,
    )

    assert interrupted is False
    assert stream.remaining == []


def test_arrow_key_sequence_is_ignored() -> None:
    stream = _FakeEscapeStream(b"[A")

    interrupted = _is_standalone_escape(
        read_byte=stream.read_byte,
        wait_for_byte=stream.wait_for_byte,
        is_closed=lambda: False,
        sequence_timeout=0.001,
    )

    assert interrupted is False
    assert stream.remaining == []


def test_function_key_sequence_is_ignored() -> None:
    stream = _FakeEscapeStream(b"OP")

    interrupted = _is_standalone_escape(
        read_byte=stream.read_byte,
        wait_for_byte=stream.wait_for_byte,
        is_closed=lambda: False,
        sequence_timeout=0.001,
    )

    assert interrupted is False
    assert stream.remaining == []


@pytest.mark.asyncio
async def test_watcher_wait_exits_cleanly_after_close() -> None:
    watcher = _TestWatcher()
    wait_task = asyncio.create_task(watcher.wait())

    await asyncio.sleep(0.01)
    watcher.close()
    interrupted = await asyncio.wait_for(wait_task, timeout=0.2)

    assert interrupted is False
    assert watcher.restored is True


@pytest.mark.asyncio
async def test_watcher_wait_reports_false_when_terminal_mode_is_unsupported() -> None:
    watcher = _BrokenTerminalWatcher()

    interrupted = await watcher.wait()

    assert interrupted is False
    assert watcher.restored is False
