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


def test_parse_dict_extracts_pseudo_tool_call_markup() -> None:
    """兼容模型把工具调用写成伪 XML 文本时，应恢复成结构化 tool_calls。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": (
                    "<tool_call>\n"
                    "<function=cron_create>\n"
                    "<parameter=at>2026-04-29T13:56:00+08:00</parameter>\n"
                    "<parameter=instruction>请立即执行命令打开微信：exec(\"open -a WeChat\")</parameter>\n"
                    "</function>\n"
                    "</tool_call>"
                ),
            },
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "cron_create"
    assert result.tool_calls[0].arguments == {
        "at": "2026-04-29T13:56:00+08:00",
        "instruction": "请立即执行命令打开微信：exec(\"open -a WeChat\")",
    }


def test_parse_dict_preserves_cron_create_arguments() -> None:
    """结构化 tool_calls 应保留当前协议的 cron_create 参数。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": "好的，我来设置。",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "cron_create",
                            "arguments": "{\"instruction\":\"打开微信\",\"every_seconds\":60}",
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }],
    }

    result = provider._parse(response)

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {
        "instruction": "打开微信",
        "every_seconds": 60,
    }


def test_parse_dict_preserves_nested_arguments_shape() -> None:
    """当前协议外的嵌套参数不再被 provider 擅自改写。"""
    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "cron_create",
                            "arguments": (
                                "{\"job\":{"
                                "\"at\":\"2026-04-29T14:11:00+08:00\","
                                "\"payload\":{\"instruction\":\"请打开微信\"}"
                                "}}"
                            ),
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }],
    }

    result = provider._parse(response)

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {
        "job": {
            "at": "2026-04-29T14:11:00+08:00",
            "payload": {"instruction": "请打开微信"},
        }
    }


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


def test_parse_chunks_extracts_pseudo_tool_call_markup() -> None:
    """流式兼容文本也应在收尾时恢复成真实工具调用。"""
    chunks = [
        {
            "choices": [{
                "finish_reason": None,
                "delta": {"content": "<tool_call>\n<function=cron_create>\n"},
            }],
        },
        {
            "choices": [{
                "finish_reason": None,
                "delta": {
                    "content": (
                        "<parameter=every_seconds>60</parameter>\n"
                    )
                },
            }],
        },
        {
            "choices": [{
                "finish_reason": "stop",
                "delta": {
                    "content": (
                        "<parameter=instruction>打开微信</parameter>\n"
                        "</function>\n</tool_call>"
                    )
                },
            }],
        },
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "cron_create"
    assert result.tool_calls[0].arguments == {
        "every_seconds": 60,
        "instruction": "打开微信",
    }


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
