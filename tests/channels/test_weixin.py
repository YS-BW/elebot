"""个人微信 channel 测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from elebot.bus.events import OutboundMessage
from elebot.bus.queue import MessageBus
from elebot.channels.weixin import WeixinChannel
from elebot.config.schema import Config


class _FakeRuntime:
    def __init__(self) -> None:
        self.bus = MessageBus()
        self.transcribe_audio = AsyncMock(return_value="")

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
async def test_weixin_process_message_publishes_image_inbound_media(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    image_path = tmp_path / "wechat-photo.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xdbfake-jpeg")
    channel._download_image_item = AsyncMock(return_value=str(image_path))

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-image",
            "from_user_id": "wx-user",
            "context_token": "ctx-image",
            "item_list": [
                {"type": 2, "image_item": {"media": {"full_url": "https://example.com/a.jpg"}}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "用户发送了一张图片，请结合附件理解。"
    assert inbound.media == [str(image_path)]
    assert inbound.metadata["message_id"] == "m-image"


@pytest.mark.asyncio
async def test_weixin_process_message_merges_text_and_image(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    image_path = tmp_path / "wechat-photo-2.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xdbfake-jpeg-2")
    channel._download_image_item = AsyncMock(return_value=str(image_path))

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-text-image",
            "from_user_id": "wx-user",
            "context_token": "ctx-text-image",
            "item_list": [
                {"type": 1, "text_item": {"text": "帮我看看"}},
                {"type": 2, "image_item": {"media": {"full_url": "https://example.com/b.jpg"}}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "帮我看看\n用户发送了一张图片，请结合附件理解。"
    assert inbound.media == [str(image_path)]


@pytest.mark.asyncio
async def test_weixin_process_message_publishes_file_attachment_metadata(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    file_path = tmp_path / "wechat-report.pdf"
    file_path.write_bytes(b"%PDF-1.7 fake")
    channel._download_file_item = AsyncMock(return_value={
        "kind": "file",
        "path": str(file_path),
        "filename": "report.pdf",
        "mime": "application/pdf",
        "size": len(file_path.read_bytes()),
    })

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-file",
            "from_user_id": "wx-user",
            "context_token": "ctx-file",
            "item_list": [
                {"type": 4, "file_item": {"file_name": "report.pdf"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "用户发送了文件，请结合附件处理。"
    assert inbound.media == [str(file_path)]
    assert inbound.metadata["attachments"] == [{
        "kind": "file",
        "path": str(file_path),
        "filename": "report.pdf",
        "mime": "application/pdf",
        "size": len(file_path.read_bytes()),
    }]


@pytest.mark.asyncio
async def test_weixin_process_message_file_download_failure_keeps_clear_text(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._download_file_item = AsyncMock(return_value=None)

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-file-fail",
            "from_user_id": "wx-user",
            "context_token": "ctx-file-fail",
            "item_list": [
                {"type": 4, "file_item": {"file_name": "report.pdf"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "用户发送了一个文件（report.pdf），但当前未能下载文件内容。"
    assert inbound.media == []
    assert inbound.metadata["attachments"] == []


@pytest.mark.asyncio
async def test_weixin_download_image_item_saves_local_file(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    image_bytes = b"\xff\xd8\xff\xdbplain-jpeg"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.com/plain.jpg")
        return httpx.Response(200, content=image_bytes)

    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        saved_path = await channel._download_image_item(
            {"media": {"full_url": "https://example.com/plain.jpg"}}
        )
    finally:
        await channel._client.aclose()
        channel._client = None

    assert saved_path is not None
    saved_file = Path(saved_path)
    assert saved_file.exists()
    assert saved_file.read_bytes() == image_bytes
    assert saved_file.parent.name == "weixin"


@pytest.mark.asyncio
async def test_weixin_download_file_item_saves_local_file_and_metadata(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    file_bytes = b"hello from weixin file"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.com/report.txt")
        return httpx.Response(200, content=file_bytes)

    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await channel._download_file_item(
            {
                "file_name": "report.txt",
                "media": {"full_url": "https://example.com/report.txt"},
            }
        )
    finally:
        await channel._client.aclose()
        channel._client = None

    assert result is not None
    saved_file = Path(result["path"])
    assert saved_file.exists()
    assert saved_file.read_bytes() == file_bytes
    assert result["filename"] == "report.txt"
    assert result["mime"] == "text/plain"
    assert result["size"] == len(file_bytes)


@pytest.mark.asyncio
async def test_weixin_process_message_uses_voice_text_when_present(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-voice-text",
            "from_user_id": "wx-user",
            "context_token": "ctx-voice-text",
            "item_list": [
                {"type": 3, "voice_item": {"text": "帮我查一下天气"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "帮我查一下天气"
    assert inbound.media == []
    channel.runtime.transcribe_audio.assert_not_awaited()


@pytest.mark.asyncio
async def test_weixin_process_message_transcribes_voice_via_runtime(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    voice_path = tmp_path / "voice.amr"
    voice_path.write_bytes(b"#!AMR\nvoice")
    channel._download_voice_item = AsyncMock(return_value=str(voice_path))
    channel.runtime.transcribe_audio = AsyncMock(return_value="提醒我明天开会")

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-voice",
            "from_user_id": "wx-user",
            "context_token": "ctx-voice",
            "item_list": [
                {"type": 3, "voice_item": {"media": {"full_url": "https://example.com/voice.amr", "aes_key": "abcd"}}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "提醒我明天开会"
    assert inbound.media == [str(voice_path)]
    channel.runtime.transcribe_audio.assert_awaited_once_with(str(voice_path))


@pytest.mark.asyncio
async def test_weixin_send_message_drops_final_text_even_with_cached_context_token(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-5"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_message(
        OutboundMessage(channel="weixin", chat_id="wx-user", content="reply")
    )

    channel._api_post.assert_not_awaited()


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
async def test_weixin_send_delta_flushes_once_part_marker_appears(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_delta("wx-user", "你好", {"_session_id": "weixin:wx-user", "message_id": "m1", "_stream_delta": True})
    channel._api_post.assert_not_awaited()
    assert channel._stream_buffers["weixin:wx-user:m1"] == "你好"

    await channel.send_delta("wx-user", "<part>", {"_session_id": "weixin:wx-user", "message_id": "m1", "_stream_delta": True})
    channel._api_post.assert_awaited_once()
    body = channel._api_post.await_args.args[1]
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "你好"
    assert channel._stream_buffers["weixin:wx-user:m1"] == ""


@pytest.mark.asyncio
async def test_weixin_send_delta_flushes_multiple_parts_from_single_delta(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-2"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_delta(
        "wx-user",
        "第一条消息<part>第二条消息<part>第三条消息<part>",
        {"_session_id": "weixin:wx-user", "message_id": "m2", "_stream_delta": True},
    )

    assert channel._api_post.await_count == 3
    assert channel._api_post.await_args_list[0].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第一条消息"
    assert channel._api_post.await_args_list[1].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第二条消息"
    assert channel._api_post.await_args_list[2].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第三条消息"
    assert channel._stream_buffers["weixin:wx-user:m2"] == ""


@pytest.mark.asyncio
async def test_weixin_send_delta_flushes_when_part_marker_crosses_delta_boundary(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-3"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_delta("wx-user", "先说前半句", {"_session_id": "weixin:wx-user", "message_id": "m3", "_stream_delta": True})
    channel._api_post.assert_not_awaited()
    await channel.send_delta("wx-user", "<part>再说后半句", {"_session_id": "weixin:wx-user", "message_id": "m3", "_stream_delta": True})

    channel._api_post.assert_awaited_once()
    body = channel._api_post.await_args.args[1]
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "先说前半句"
    assert channel._stream_buffers["weixin:wx-user:m3"] == "再说后半句"


@pytest.mark.asyncio
async def test_weixin_send_delta_keeps_long_text_buffered_until_part_or_end(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-4"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    long_text = (
        "这是一段没有换行但是会越来越长，"
        "而且还会继续往后写很多很多字，"
        "直到超过微信流式单段允许等待的上限，"
        "这时候应该主动切出去，"
        "否则用户会一直看到一整坨内容，"
        "体验就会很生硬。"
    )

    await channel.send_delta("wx-user", long_text, {"_session_id": "weixin:wx-user", "message_id": "m4", "_stream_delta": True})

    assert channel._api_post.await_count == 0
    assert channel._stream_buffers["weixin:wx-user:m4"] == long_text


@pytest.mark.asyncio
async def test_weixin_send_delta_flushes_tail_on_stream_end(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-5"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_delta("wx-user", "还差一点", {"_session_id": "weixin:wx-user", "message_id": "m5", "_stream_delta": True})
    channel._api_post.assert_not_awaited()
    await channel.send_delta("wx-user", "", {"_session_id": "weixin:wx-user", "message_id": "m5", "_stream_end": True})

    assert channel._api_post.await_count == 1
    body = channel._api_post.await_args.args[1]
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "还差一点"
    assert channel._stream_buffers == {}
    assert channel._stream_has_delta == {}


@pytest.mark.asyncio
async def test_weixin_send_delta_ignores_empty_tail_on_stream_end(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-6"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_delta("wx-user", "这段已经完整触发发送。<part>", {"_session_id": "weixin:wx-user", "message_id": "m6", "_stream_delta": True})
    assert channel._api_post.await_count == 1
    await channel.send_delta("wx-user", "", {"_session_id": "weixin:wx-user", "message_id": "m6", "_stream_end": True})
    assert channel._api_post.await_count == 1


@pytest.mark.asyncio
async def test_weixin_send_delta_skips_empty_parts(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-6b"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_delta("wx-user", "第一条<part><part>第二条<part>", {"_session_id": "weixin:wx-user", "message_id": "m6b", "_stream_delta": True})

    assert channel._api_post.await_count == 2
    assert channel._api_post.await_args_list[0].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第一条"
    assert channel._api_post.await_args_list[1].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第二条"


@pytest.mark.asyncio
async def test_weixin_send_message_without_stream_delta_drops_final_text(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-final-drop"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="最终整段文本",
            metadata={"_session_id": "weixin:wx-user", "message_id": "m7"},
        )
    )

    channel._api_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_weixin_send_message_allows_cron_final_text_and_splits_parts(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-cron"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="该写作业了！<part>别拖啦，现在开始吧💪<part>",
            metadata={"_cron_job_id": "cron_123"},
        )
    )

    assert channel._api_post.await_count == 2
    assert channel._api_post.await_args_list[0].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "该写作业了！"
    assert channel._api_post.await_args_list[1].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "别拖啦，现在开始吧💪"



@pytest.mark.asyncio
async def test_weixin_send_message_after_stream_delta_does_not_repeat(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-final-skip"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_delta("wx-user", "这段已经通过流式发出。", {"_session_id": "weixin:wx-user", "message_id": "m8", "_stream_delta": True})
    await channel.send_delta("wx-user", "", {"_session_id": "weixin:wx-user", "message_id": "m8", "_stream_end": True})
    assert channel._api_post.await_count == 1

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="这段已经通过流式发出。",
            metadata={"_session_id": "weixin:wx-user", "message_id": "m8"},
        )
    )

    assert channel._api_post.await_count == 1


@pytest.mark.asyncio
async def test_weixin_send_delta_does_not_enforce_prompt_only_segment_limit(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-limit"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    eleven_lines = "<part>".join(f"第{i}条" for i in range(1, 12)) + "<part>"

    await channel.send_delta("wx-user", eleven_lines, {"_session_id": "weixin:wx-user", "message_id": "m9", "_stream_delta": True})

    assert channel._api_post.await_count == 11
    assert channel._stream_buffers["weixin:wx-user:m9"] == ""
