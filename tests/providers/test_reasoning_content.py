"""Tests for reasoning_content extraction in OpenAICompatProvider.

Covers non-streaming (_parse) and streaming (_parse_chunks) paths for
providers that return a reasoning_content field (e.g. MiMo, DeepSeek-R1).
"""

from types import SimpleNamespace
from unittest.mock import patch

from elebot.providers.base import LLMResponse, ToolCallRequest
from elebot.providers.openai_compat_provider import OpenAICompatProvider
from elebot.providers.registry import find_by_name

# ── _parse: non-streaming ─────────────────────────────────────────────────


def test_parse_dict_extracts_reasoning_content() -> None:
    """reasoning_content at message level is surfaced in LLMResponse."""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": "42",
                "reasoning_content": "Let me think step by step…",
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
    }

    result = provider._parse(response)

    assert result.content == "42"
    assert result.reasoning_content == "Let me think step by step…"


def test_parse_dict_reasoning_content_none_when_absent() -> None:
    """reasoning_content is None when the response doesn't include it."""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {"content": "hello"},
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.reasoning_content is None


# ── _parse_chunks: streaming dict branch ─────────────────────────────────


def test_parse_chunks_dict_accumulates_reasoning_content() -> None:
    """reasoning_content deltas in dict chunks are joined into one string."""
    chunks = [
        {
            "choices": [{
                "finish_reason": None,
                "delta": {"content": None, "reasoning_content": "Step 1. "},
            }],
        },
        {
            "choices": [{
                "finish_reason": None,
                "delta": {"content": None, "reasoning_content": "Step 2."},
            }],
        },
        {
            "choices": [{
                "finish_reason": "stop",
                "delta": {"content": "answer"},
            }],
        },
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "answer"
    assert result.reasoning_content == "Step 1. Step 2."


def test_parse_chunks_dict_reasoning_content_none_when_absent() -> None:
    """reasoning_content is None when no chunk contains it."""
    chunks = [
        {"choices": [{"finish_reason": "stop", "delta": {"content": "hi"}}]},
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "hi"
    assert result.reasoning_content is None


# ── _parse_chunks: streaming SDK-object branch ────────────────────────────


def _make_reasoning_chunk(reasoning: str | None, content: str | None, finish: str | None):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=None)
    choice = SimpleNamespace(finish_reason=finish, delta=delta)
    return SimpleNamespace(choices=[choice], usage=None)


def test_parse_chunks_sdk_accumulates_reasoning_content() -> None:
    """reasoning_content on SDK delta objects is joined across chunks."""
    chunks = [
        _make_reasoning_chunk("Think… ", None, None),
        _make_reasoning_chunk("Done.", None, None),
        _make_reasoning_chunk(None, "result", "stop"),
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "result"
    assert result.reasoning_content == "Think… Done."


def test_parse_chunks_sdk_reasoning_content_none_when_absent() -> None:
    """reasoning_content is None when SDK deltas carry no reasoning_content."""
    chunks = [_make_reasoning_chunk(None, "hello", "stop")]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.reasoning_content is None


def test_sanitize_messages_backfills_reasoning_content_for_deepseek_tool_calls() -> None:
    """DeepSeek 工具调用历史在重放前应补齐空的 reasoning_content。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=find_by_name("deepseek"))

    sanitized = provider._sanitize_messages(
        [
            {"role": "user", "content": "run command"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1234567890",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1234567890",
                "name": "exec",
                "content": "ok",
            },
        ]
    )

    assistant_message = next(message for message in sanitized if message.get("role") == "assistant")
    assert assistant_message["reasoning_content"] == ""


def test_sanitize_messages_backfills_reasoning_content_for_deepseek_error_placeholder() -> None:
    """DeepSeek 重放带占位 assistant 历史时也要补齐空的 reasoning_content。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=find_by_name("deepseek"))

    sanitized = provider._sanitize_messages(
        [
            {"role": "user", "content": "run command"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1234567890",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
                "reasoning_content": "",
            },
            {
                "role": "tool",
                "tool_call_id": "call_1234567890",
                "name": "exec",
                "content": "ok",
            },
            {
                "role": "assistant",
                "content": "[Assistant reply unavailable due to model error.]",
            },
            {"role": "user", "content": "retry"},
        ]
    )

    assistant_messages = [
        message for message in sanitized if message.get("role") == "assistant"
    ]
    assert len(assistant_messages) == 2
    assert assistant_messages[0]["reasoning_content"] == ""
    assert assistant_messages[1]["reasoning_content"] == ""


def test_sanitize_messages_keeps_other_providers_unchanged() -> None:
    """非 DeepSeek provider 不应强行补 reasoning_content。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=find_by_name("dashscope"))

    sanitized = provider._sanitize_messages(
        [
            {"role": "user", "content": "run command"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1234567890",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1234567890",
                "name": "exec",
                "content": "ok",
            },
        ]
    )

    assistant_message = next(message for message in sanitized if message.get("role") == "assistant")
    assert "reasoning_content" not in assistant_message


def test_sanitize_messages_keeps_other_provider_error_placeholder_unchanged() -> None:
    """非 DeepSeek provider 不应给普通 assistant 历史强行补 reasoning_content。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=find_by_name("dashscope"))

    sanitized = provider._sanitize_messages(
        [
            {"role": "user", "content": "run command"},
            {
                "role": "assistant",
                "content": "[Assistant reply unavailable due to model error.]",
            },
            {"role": "user", "content": "retry"},
        ]
    )

    assistant_message = next(message for message in sanitized if message.get("role") == "assistant")
    assert "reasoning_content" not in assistant_message


def test_normalize_response_backfills_reasoning_content_for_deepseek_tool_calls() -> None:
    """DeepSeek 缺失 reasoning_content 的工具调用响应要归一化为空字符串。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=find_by_name("deepseek"))

    result = provider._normalize_reasoning_response(
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="call_1", name="exec", arguments={})],
            reasoning_content=None,
        )
    )

    assert result.reasoning_content == ""


def test_normalize_response_keeps_none_for_non_tool_call_response() -> None:
    """普通非工具调用响应缺少 reasoning_content 时继续保持 None。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=find_by_name("deepseek"))

    result = provider._normalize_reasoning_response(
        LLMResponse(content="hello", tool_calls=[], reasoning_content=None)
    )

    assert result.reasoning_content is None
