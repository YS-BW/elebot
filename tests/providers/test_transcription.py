"""语音转写 provider 测试。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from elebot.config.schema import Config
from elebot.providers.transcription import (
    QwenAsrTranscriptionProvider,
    build_transcription_provider,
)


class _FakeAsyncClient:
    """最小可控的 AsyncClient 替身。"""

    def __init__(self, *, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, *, headers: dict, json: dict) -> httpx.Response:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.response


@pytest.mark.asyncio
async def test_qwen_asr_transcription_provider_posts_openai_compatible_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """应按 DashScope OpenAI 兼容协议发送音频转写请求。"""
    audio_path = tmp_path / "voice.amr"
    audio_path.write_bytes(b"#!AMR\nhello-audio")

    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": "提醒我十分钟后开会",
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
    )
    fake_client = _FakeAsyncClient(response=response)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

    provider = QwenAsrTranscriptionProvider(api_key="dashscope-key")
    text = await provider.transcribe(audio_path)

    assert text == "提醒我十分钟后开会"
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer dashscope-key"
    assert call["json"]["model"] == "qwen3-asr-flash"
    assert call["json"]["messages"][0]["content"][0]["type"] == "input_audio"
    assert call["json"]["messages"][0]["content"][0]["input_audio"]["data"].startswith(
        "data:audio/amr;base64,"
    )
    assert call["json"]["asr_options"] == {"enable_itn": False}


@pytest.mark.asyncio
async def test_build_transcription_provider_requires_api_key() -> None:
    """未配置 API Key 时不应构建转写 provider。"""
    config = Config()
    config.transcription.api_key = ""
    provider = build_transcription_provider(config)
    assert provider is None
