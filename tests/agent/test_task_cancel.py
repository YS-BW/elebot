"""Tests for session interrupt handling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from elebot.config.schema import AgentDefaults
from elebot.runtime.models import InterruptResult

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _make_loop(*, exec_config=None):
    """创建一个最小可用的 AgentLoop 测试实例。

    参数:
        exec_config: 可选的执行工具配置。

    返回:
        `(loop, bus)` 二元组。
    """
    from elebot.agent.loop import AgentLoop
    from elebot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("elebot.agent.loop.ContextBuilder"), patch("elebot.agent.loop.SessionManager"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace, exec_config=exec_config)
    return loop, bus


class TestInterruptSession:
    @pytest.mark.asyncio
    async def test_interrupt_session_rejects_when_no_active_task(self):
        loop, _bus = _make_loop()

        result = loop.interrupt_session("test:c1")

        assert result == InterruptResult(
            session_id="test:c1",
            reason="user_interrupt",
            accepted=False,
            cancelled_tasks=0,
            already_interrupting=False,
        )

    @pytest.mark.asyncio
    async def test_interrupt_session_cancels_active_task(self):
        loop, _bus = _make_loop()
        cancelled = asyncio.Event()

        async def slow_task():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = [task]

        result = loop.interrupt_session("test:c1")
        await asyncio.sleep(0)

        assert result.accepted is True
        assert result.cancelled_tasks == 1
        assert cancelled.is_set()
        assert loop._peek_interrupt_state("test:c1") is not None

    @pytest.mark.asyncio
    async def test_interrupt_session_rejects_duplicate_request(self):
        loop, _bus = _make_loop()

        async def slow_task():
            await asyncio.sleep(60)

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = [task]

        first = loop.interrupt_session("test:c1")
        second = loop.interrupt_session("test:c1")

        assert first.accepted is True
        assert second.already_interrupting is True

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestDispatch:
    def test_exec_tool_not_registered_when_disabled(self):
        from elebot.config.schema import ExecToolConfig

        loop, _bus = _make_loop(exec_config=ExecToolConfig(enable=False))

        assert loop.tools.get("exec") is None

    @pytest.mark.asyncio
    async def test_dispatch_processes_and_publishes(self):
        from elebot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")
        loop._process_message = AsyncMock(
            return_value=OutboundMessage(channel="test", chat_id="c1", content="hi")
        )
        await loop._dispatch(msg)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert out.content == "hi"

    @pytest.mark.asyncio
    async def test_dispatch_interrupted_turn_publishes_interrupted_message(self):
        from elebot.bus.events import InboundMessage
        from elebot.session.manager import Session

        loop, bus = _make_loop()
        session = Session(
            key="test:c1",
            metadata={
                loop._RUNTIME_CHECKPOINT_KEY: {
                    "phase": "awaiting_tools",
                    "assistant_message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_pending",
                                "type": "function",
                                "function": {"name": "exec", "arguments": "{}"},
                            }
                        ],
                    },
                    "completed_tool_results": [],
                    "pending_tool_calls": [
                        {
                            "id": "call_pending",
                            "type": "function",
                            "function": {"name": "exec", "arguments": "{}"},
                        }
                    ],
                }
            },
        )
        loop.sessions.get_or_create.return_value = session
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")

        async def fake_process(*_args, **_kwargs):
            raise asyncio.CancelledError()

        loop._process_message = fake_process
        loop._interrupt_requests["test:c1"] = MagicMock(reason="user_interrupt", handled=False)

        await loop._dispatch(msg)

        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert out.content == "已中断当前回复。"
        assert out.metadata["_interrupted"] is True
        assert session.metadata.get(loop._RUNTIME_CHECKPOINT_KEY) is None
        assert session.messages[-1]["content"] == "Interrupted: tool execution stopped before completion."

    @pytest.mark.asyncio
    async def test_dispatch_streaming_preserves_message_metadata(self):
        from elebot.bus.events import InboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(
            channel="matrix",
            sender_id="u1",
            chat_id="!room:matrix.org",
            content="hello",
            metadata={
                "_wants_stream": True,
                "thread_root_event_id": "$root1",
                "thread_reply_to_event_id": "$reply1",
            },
        )

        async def fake_process(_msg, *, on_stream=None, on_stream_end=None, **kwargs):
            assert on_stream is not None
            assert on_stream_end is not None
            await on_stream("hi")
            await on_stream_end(resuming=False)
            return None

        loop._process_message = fake_process

        await loop._dispatch(msg)
        first = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        second = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

        assert first.metadata["thread_root_event_id"] == "$root1"
        assert first.metadata["thread_reply_to_event_id"] == "$reply1"
        assert first.metadata["_stream_delta"] is True
        assert second.metadata["thread_root_event_id"] == "$root1"
        assert second.metadata["thread_reply_to_event_id"] == "$reply1"
        assert second.metadata["_stream_end"] is True

    @pytest.mark.asyncio
    async def test_processing_lock_serializes(self):
        from elebot.bus.events import InboundMessage, OutboundMessage

        loop, _bus = _make_loop()
        order = []

        async def mock_process(m, **kwargs):
            order.append(f"start-{m.content}")
            await asyncio.sleep(0.05)
            order.append(f"end-{m.content}")
            return OutboundMessage(channel="test", chat_id="c1", content=m.content)

        loop._process_message = mock_process
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="a")
        msg2 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="b")

        t1 = asyncio.create_task(loop._dispatch(msg1))
        t2 = asyncio.create_task(loop._dispatch(msg2))
        await asyncio.gather(t1, t2)
        assert order == ["start-a", "end-a", "start-b", "end-b"]
