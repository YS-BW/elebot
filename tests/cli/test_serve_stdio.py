"""`elebot serve stdio` 协议测试。"""

from __future__ import annotations

import asyncio

import pytest

from elebot.bus.events import OutboundMessage
from elebot.cli.serve_stdio import StdioServer
from elebot.runtime.models import InterruptResult, RuntimeStatusSnapshot


class _FakeRuntime:
    def __init__(self) -> None:
        self.run_once_calls: list[tuple[str, str]] = []
        self.interrupt_calls: list[str] = []
        self.reset_calls: list[str] = []
        self.status_calls: list[str] = []
        self.closed = False

    async def run_once(
        self,
        message: str,
        *,
        session_id: str,
        on_progress=None,
        on_stream=None,
        on_stream_end=None,
    ) -> OutboundMessage:
        self.run_once_calls.append((session_id, message))
        if on_progress is not None:
            await on_progress("tool running", tool_hint=True)
        if on_stream is not None:
            await on_stream("你好")
        if on_stream_end is not None:
            await on_stream_end(resuming=False)
        return OutboundMessage(channel="stdio", chat_id=session_id, content=f"done:{message}")

    def interrupt_session(self, session_id: str, reason: str = "user_interrupt") -> InterruptResult:
        self.interrupt_calls.append(session_id)
        return InterruptResult(
            session_id=session_id,
            reason=reason,
            accepted=True,
            cancelled_tasks=1,
            already_interrupting=False,
        )

    def reset_session(self, session_id: str) -> None:
        self.reset_calls.append(session_id)

    async def get_status_snapshot(self, session_id: str) -> RuntimeStatusSnapshot:
        self.status_calls.append(session_id)
        return RuntimeStatusSnapshot(
            version="0.1.5",
            model="deepseek-v4-flash",
            start_time=1.0,
            last_usage={"prompt_tokens": 1, "completion_tokens": 2},
            context_window_tokens=4096,
            session_msg_count=3,
            context_tokens_estimate=99,
            search_usage_text=None,
        )

    async def close(self) -> None:
        self.closed = True


def _make_reader(lines: list[str | None]):
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    for line in lines:
        queue.put_nowait(line)

    async def _reader() -> str | None:
        return await queue.get()

    return _reader


@pytest.mark.asyncio
async def test_stdio_server_handles_input_and_stream_events() -> None:
    runtime = _FakeRuntime()
    events: list[dict] = []
    server = StdioServer(
        runtime,
        reader=_make_reader(['{"type":"input","session_id":"stdio:s1","content":"hello"}', None]),
        writer=lambda payload: _collect(events, payload),
    )

    await server.serve()

    assert [event["type"] for event in events] == [
        "ready",
        "progress",
        "delta",
        "stream_end",
        "message",
    ]
    assert events[1]["tool_hint"] is True
    assert events[-1]["content"] == "done:hello"
    assert runtime.run_once_calls == [("stdio:s1", "hello")]
    assert runtime.closed is True


@pytest.mark.asyncio
async def test_stdio_server_handles_interrupt_reset_and_status() -> None:
    runtime = _FakeRuntime()
    events: list[dict] = []
    server = StdioServer(
        runtime,
        reader=_make_reader(
            [
                '{"type":"interrupt","session_id":"stdio:s1"}',
                '{"type":"reset_session","session_id":"stdio:s1"}',
                '{"type":"status","session_id":"stdio:s1"}',
                None,
            ]
        ),
        writer=lambda payload: _collect(events, payload),
    )

    await server.serve()

    assert [event["type"] for event in events] == [
        "ready",
        "interrupt_result",
        "reset_done",
        "status_result",
    ]
    assert runtime.interrupt_calls == ["stdio:s1"]
    assert runtime.reset_calls == ["stdio:s1"]
    assert runtime.status_calls == ["stdio:s1"]


@pytest.mark.asyncio
async def test_stdio_server_reports_invalid_json_and_unknown_type() -> None:
    runtime = _FakeRuntime()
    events: list[dict] = []
    server = StdioServer(
        runtime,
        reader=_make_reader(
            [
                "not-json",
                '{"type":"unknown","session_id":"stdio:s1"}',
                '{"type":"input","session_id":"stdio:s2"}',
                None,
            ]
        ),
        writer=lambda payload: _collect(events, payload),
    )

    await server.serve()

    assert events[0]["type"] == "ready"
    assert events[1]["type"] == "error"
    assert "invalid JSON" in events[1]["message"]
    assert events[2]["type"] == "error"
    assert "unknown request type" in events[2]["message"]
    assert events[3]["type"] == "error"
    assert "non-empty content" in events[3]["message"]


@pytest.mark.asyncio
async def test_stdio_server_supports_multiple_sessions_sequentially() -> None:
    runtime = _FakeRuntime()
    events: list[dict] = []
    server = StdioServer(
        runtime,
        reader=_make_reader(
            [
                '{"type":"input","session_id":"stdio:a","content":"first"}',
                '{"type":"input","session_id":"stdio:b","content":"second"}',
                None,
            ]
        ),
        writer=lambda payload: _collect(events, payload),
    )

    await server.serve()

    message_events = [event for event in events if event["type"] == "message"]
    assert [event["session_id"] for event in message_events] == ["stdio:a", "stdio:b"]
    assert runtime.run_once_calls == [("stdio:a", "first"), ("stdio:b", "second")]


async def _collect(events: list[dict], payload: dict) -> None:
    events.append(payload)
