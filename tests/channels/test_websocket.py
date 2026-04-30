"""WebSocket channel 集成测试。"""

from __future__ import annotations

import asyncio
import json
import socket

import pytest
from websockets.asyncio.client import connect

from elebot.bus.events import OutboundMessage
from elebot.bus.queue import MessageBus
from elebot.channels.websocket import WebSocketChannel
from elebot.config.schema import Config
from elebot.runtime.models import InterruptResult, RuntimeStatusSnapshot


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _FakeRuntime:
    def __init__(self) -> None:
        self.bus = MessageBus()
        self.interrupt_calls: list[str] = []
        self.reset_calls: list[str] = []
        self.status_calls: list[str] = []

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


@pytest.mark.asyncio
async def test_websocket_ready_and_plain_text_input() -> None:
    config = Config()
    config.channels.websocket.port = _free_port()
    config.channels.websocket.path = "/ws"
    runtime = _FakeRuntime()
    channel = WebSocketChannel(config.channels.websocket, runtime)
    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.05)

    try:
        async with connect(f"ws://127.0.0.1:{config.channels.websocket.port}/ws?client_id=alice&chat_id=course&session_id=websocket:custom") as ws:
            ready = json.loads(await ws.recv())
            assert ready["type"] == "ready"
            assert ready["chat_id"] == "course"
            assert ready["session_id"] == "websocket:custom"

            await ws.send("你好")
            inbound = await asyncio.wait_for(runtime.bus.consume_inbound(), timeout=1.0)
            assert inbound.channel == "websocket"
            assert inbound.sender_id == "alice"
            assert inbound.chat_id == "course"
            assert inbound.content == "你好"
            assert inbound.session_key_override == "websocket:custom"
            assert inbound.metadata["_session_id"] == "websocket:custom"
            assert inbound.metadata["_wants_stream"] is True
    finally:
        await channel.stop()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_websocket_handles_control_frames_and_outbound_events() -> None:
    config = Config()
    config.channels.websocket.port = _free_port()
    config.channels.websocket.path = "/ws"
    runtime = _FakeRuntime()
    channel = WebSocketChannel(config.channels.websocket, runtime)
    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.05)

    try:
        async with connect(f"ws://127.0.0.1:{config.channels.websocket.port}/ws?client_id=alice") as ws:
            ready = json.loads(await ws.recv())
            session_id = ready["session_id"]
            chat_id = ready["chat_id"]

            await ws.send(json.dumps({"type": "interrupt", "session_id": session_id}))
            interrupt = json.loads(await ws.recv())
            assert interrupt["type"] == "interrupt_result"
            assert runtime.interrupt_calls == [session_id]

            await ws.send(json.dumps({"type": "status", "session_id": session_id}))
            status = json.loads(await ws.recv())
            assert status["type"] == "status_result"
            assert status["snapshot"]["model"] == "deepseek-v4-flash"

            await ws.send(json.dumps({"type": "reset_session", "session_id": session_id}))
            reset = json.loads(await ws.recv())
            assert reset["type"] == "reset_done"
            assert runtime.reset_calls == [session_id]

            await channel.send_progress(chat_id, "tool running", {"_session_id": session_id}, tool_hint=True)
            await channel.send_delta(chat_id, "你", {"_session_id": session_id, "_stream_delta": True})
            await channel.send_delta(chat_id, "", {"_session_id": session_id, "_stream_end": True, "_resuming": False})
            await channel.send_message(
                OutboundMessage(
                    channel="websocket",
                    chat_id=chat_id,
                    content="你好",
                    metadata={"_session_id": session_id},
                )
            )
            progress = json.loads(await ws.recv())
            delta = json.loads(await ws.recv())
            stream_end = json.loads(await ws.recv())
            message = json.loads(await ws.recv())

            assert progress["type"] == "progress"
            assert progress["tool_hint"] is True
            assert delta["type"] == "delta"
            assert stream_end["type"] == "stream_end"
            assert message["type"] == "message"
            assert message["content"] == "你好"
    finally:
        await channel.stop()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_websocket_disconnect_clears_connection_and_drops_future_outbound() -> None:
    config = Config()
    config.channels.websocket.port = _free_port()
    runtime = _FakeRuntime()
    channel = WebSocketChannel(config.channels.websocket, runtime)
    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.05)

    try:
        async with connect(f"ws://127.0.0.1:{config.channels.websocket.port}/?client_id=alice") as ws:
            ready = json.loads(await ws.recv())
            chat_id = ready["chat_id"]
        await asyncio.sleep(0.05)
        assert chat_id not in channel._connections
        await channel.send_message(
            OutboundMessage(channel="websocket", chat_id=chat_id, content="still ok", metadata={})
        )
    finally:
        await channel.stop()
        await asyncio.gather(task, return_exceptions=True)
