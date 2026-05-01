from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from elebot.agent.tools.image_analysis import AnalyzeImageTool
from elebot.providers.base import LLMResponse


@pytest.fixture()
def image_path(tmp_path):
    path = tmp_path / "sample.png"
    path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
    ))
    return path


@pytest.mark.asyncio
async def test_analyze_image_tool_calls_provider_with_multimodal_message(image_path, tmp_path):
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="一张很小的测试图片"))
    tool = AnalyzeImageTool(
        provider=provider,
        model="test-model",
        workspace=tmp_path,
    )

    result = await tool.execute(path=str(image_path), prompt="这张图里有什么？")

    assert result == "一张很小的测试图片"
    provider.chat_with_retry.assert_awaited_once()
    kwargs = provider.chat_with_retry.await_args.kwargs
    assert kwargs["model"] == "test-model"
    messages = kwargs["messages"]
    assert messages[0]["role"] == "user"
    blocks = messages[0]["content"]
    assert blocks[0]["type"] == "image_url"
    assert blocks[1]["text"] == "这张图里有什么？"


@pytest.mark.asyncio
async def test_analyze_image_tool_rejects_non_image_file(tmp_path):
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock()
    text_path = tmp_path / "note.txt"
    text_path.write_text("hello", encoding="utf-8")
    tool = AnalyzeImageTool(
        provider=provider,
        model="test-model",
        workspace=tmp_path,
    )

    result = await tool.execute(path=str(text_path))

    assert result.startswith("Error: Not an image file")
    provider.chat_with_retry.assert_not_awaited()
