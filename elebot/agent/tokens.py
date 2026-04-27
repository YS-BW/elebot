"""Agent 提示词与消息 token 估算。"""

from __future__ import annotations

import json
from typing import Any

import tiktoken


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """使用 tiktoken 估算提示词 token 数。

    参数:
        messages: 消息数组。
        tools: 可选工具定义列表。

    返回:
        估算出的 token 数；失败时返回 ``0``。
    """
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        parts: list[str] = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "")
                        if text:
                            parts.append(text)

            tool_calls = message.get("tool_calls")
            if tool_calls:
                parts.append(json.dumps(tool_calls, ensure_ascii=False))

            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                parts.append(reasoning_content)

            for key in ("name", "tool_call_id"):
                value = message.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)

        if tools:
            parts.append(json.dumps(tools, ensure_ascii=False))

        per_message_overhead = len(messages) * 4
        return len(encoding.encode("\n".join(parts))) + per_message_overhead
    except Exception:
        return 0


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """估算单条消息贡献的 token 数。

    参数:
        message: 单条消息。

    返回:
        估算出的 token 数。
    """
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            else:
                parts.append(json.dumps(part, ensure_ascii=False))
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))

    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))

    reasoning_content = message.get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content:
        parts.append(reasoning_content)

    payload = "\n".join(parts)
    if not payload:
        return 4
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return max(4, len(encoding.encode(payload)) + 4)
    except Exception:
        return max(4, len(payload) // 4 + 4)


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """按 provider 计数器优先、tiktoken 兜底的顺序估算 token。

    参数:
        provider: 当前 provider。
        model: 当前模型名。
        messages: 消息数组。
        tools: 可选工具定义列表。

    返回:
        ``(估算 token 数, 估算来源)`` 元组。
    """
    provider_counter = getattr(provider, "estimate_prompt_tokens", None)
    if callable(provider_counter):
        try:
            tokens, source = provider_counter(messages, tools, model)
            if isinstance(tokens, (int, float)) and tokens > 0:
                return int(tokens), str(source or "provider_counter")
        except Exception:
            pass

    estimated = estimate_prompt_tokens(messages, tools)
    if estimated > 0:
        return int(estimated), "tiktoken"
    return 0, "none"
