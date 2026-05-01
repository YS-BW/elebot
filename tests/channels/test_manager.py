"""ChannelManager 路由测试。"""

from __future__ import annotations

import asyncio

import pytest

from elebot.bus.events import OutboundMessage
from elebot.bus.queue import MessageBus
from elebot.channels.base import BaseChannel
from elebot.channels.manager import ChannelManager
from elebot.config.schema import Config


class _FakeRuntime:
    def __init__(self) -> None:
        self.bus = MessageBus()


class _FakeChannel(BaseChannel):
    name = "weixin"

    def __init__(self, config, runtime) -> None:
        super().__init__(config, runtime)
        self.started = False
        self.stopped = False
        self.messages: list[OutboundMessage] = []
        self.progresses: list[tuple[str, str, bool]] = []
        self.deltas: list[tuple[str, str, dict]] = []
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self.started = True
        await self._stop_event.wait()

    async def stop(self) -> None:
        self.stopped = True
        self._stop_event.set()

    async def send_message(self, message: OutboundMessage) -> None:
        self.messages.append(message)

    async def send_progress(self, chat_id: str, content: str, metadata=None, *, tool_hint: bool = False) -> None:
        self.progresses.append((chat_id, content, tool_hint))

    async def send_delta(self, chat_id: str, content: str, metadata=None) -> None:
        self.deltas.append((chat_id, content, dict(metadata or {})))


class _FakeWeixinChannel(_FakeChannel):
    name = "weixin"


@pytest.mark.asyncio
async def test_channel_manager_routes_outbound_metadata() -> None:
    config = Config()
    config.channels.weixin.enabled = True
    runtime = _FakeRuntime()
    manager = ChannelManager(
        config,
        runtime,
        channel_factories={"weixin": _FakeChannel},
    )

    await manager.start_all()

    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content='cron_create("提醒我看书")',
            metadata={"_tool_transition": True},
        )
    )
    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content="running",
            metadata={"_progress": True},
        )
    )
    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content="你",
            metadata={"_stream_delta": True},
        )
    )
    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content="",
            metadata={"_stream_end": True, "_resuming": False},
        )
    )
    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content="你好",
            metadata={},
        )
    )

    await asyncio.sleep(0.05)
    channel = manager.channels["weixin"]
    assert isinstance(channel, _FakeChannel)
    assert channel.started is True
    assert channel.progresses == [
        ("room1", 'cron_create("提醒我看书")', True),
        ("room1", "running", False),
    ]
    assert channel.deltas[0][0:2] == ("room1", "你")
    assert channel.deltas[1][2]["_stream_end"] is True
    assert channel.messages[0].content == "你好"

    await manager.stop_all()
    assert channel.stopped is True


def test_channel_manager_initializes_enabled_weixin_channel() -> None:
    config = Config()
    config.channels.weixin.enabled = True
    runtime = _FakeRuntime()

    manager = ChannelManager(
        config,
        runtime,
        channel_factories={"weixin": _FakeWeixinChannel},
    )

    channel = manager.channels["weixin"]
    assert isinstance(channel, _FakeWeixinChannel)
