"""个人微信 channel 测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from elebot.bus.events import OutboundMessage
from elebot.bus.queue import MessageBus
from elebot.channels.weixin import WeixinChannel
from elebot.config.schema import Config


class _FakeRuntime:
    def __init__(self) -> None:
        self.bus = MessageBus()


def _make_channel(tmp_path: Path, *, allow_from: list[str] | None = None) -> WeixinChannel:
    config = Config().channels.weixin
    config.enabled = True
    config.state_dir = str(tmp_path)
    if allow_from is not None:
        config.allow_from = allow_from
    return WeixinChannel(config, _FakeRuntime())


@pytest.mark.asyncio
async def test_weixin_process_message_publishes_text_inbound(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m1",
            "from_user_id": "wx-user",
            "context_token": "ctx-1",
            "item_list": [
                {"type": 1, "text_item": {"text": "你好"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.channel == "weixin"
    assert inbound.sender_id == "wx-user"
    assert inbound.chat_id == "wx-user"
    assert inbound.content == "你好"
    assert inbound.metadata["message_id"] == "m1"
    assert inbound.metadata["_session_id"] == "weixin:wx-user"


@pytest.mark.asyncio
async def test_weixin_process_message_respects_allow_from(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path, allow_from=["friend-a"])

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m2",
            "from_user_id": "stranger",
            "context_token": "ctx-2",
            "item_list": [
                {"type": 1, "text_item": {"text": "hello"}},
            ],
        }
    )

    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_weixin_process_message_deduplicates_message_id(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    message = {
        "message_type": 1,
        "message_id": "m3",
        "from_user_id": "wx-user",
        "context_token": "ctx-3",
        "item_list": [
            {"type": 1, "text_item": {"text": "hello"}},
        ],
    }

    await channel._process_message(message)
    await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    await channel._process_message(message)

    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_weixin_process_message_persists_context_token(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m4",
            "from_user_id": "wx-user",
            "context_token": "ctx-4",
            "item_list": [
                {"type": 1, "text_item": {"text": "persist"}},
            ],
        }
    )

    saved = json.loads((tmp_path / "account.json").read_text(encoding="utf-8"))
    assert saved["context_tokens"] == {"wx-user": "ctx-4"}


@pytest.mark.asyncio
async def test_weixin_send_message_uses_cached_context_token(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-5"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_message(
        OutboundMessage(channel="weixin", chat_id="wx-user", content="reply")
    )

    channel._api_post.assert_awaited_once()
    endpoint = channel._api_post.await_args.args[0]
    body = channel._api_post.await_args.args[1]
    assert endpoint == "ilink/bot/sendmessage"
    assert body["msg"]["to_user_id"] == "wx-user"
    assert body["msg"]["client_id"].startswith("elebot-")
    assert body["msg"]["context_token"] == "ctx-5"
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "reply"


@pytest.mark.asyncio
async def test_weixin_send_message_without_context_token_drops_outbound(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_message(
        OutboundMessage(channel="weixin", chat_id="wx-user", content="reply")
    )

    channel._api_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_weixin_progress_and_delta_are_noop(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)

    await channel.send_progress("wx-user", "tool", {}, tool_hint=True)
    await channel.send_delta("wx-user", "你", {"_stream_delta": True})

    assert channel.bus.outbound_size == 0
