"""Agent 消息结构相关辅助。"""

from __future__ import annotations

import base64
from typing import Any


def detect_image_mime(data: bytes) -> str | None:
    """根据文件头字节识别图片 MIME 类型。

    参数:
        data: 原始二进制数据。

    返回:
        识别出的图片 MIME；非支持格式时返回 ``None``。
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_image_content_blocks(raw: bytes, mime: str, path: str, label: str) -> list[dict[str, Any]]:
    """构造包含图片与说明文本的消息块。

    参数:
        raw: 图片原始字节。
        mime: 图片 MIME 类型。
        path: 图片路径。
        label: 说明文本。

    返回:
        可直接传给 provider 的内容块数组。
    """
    b64 = base64.b64encode(raw).decode()
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
            "_meta": {"path": path},
        },
        {"type": "text", "text": label},
    ]


def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    reasoning_items: list[dict[str, Any]] | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """构造兼容各 provider 的 assistant 消息。

    参数:
        content: 助手正文。
        tool_calls: 可选工具调用列表。
        reasoning_content: 可选推理文本。
        reasoning_items: 可选推理载荷。
        thinking_blocks: 可选思考块。

    返回:
        统一格式的助手消息字典。
    """
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if reasoning_content is not None or thinking_blocks:
        message["reasoning_content"] = reasoning_content if reasoning_content is not None else ""
    if reasoning_items:
        message["reasoning_items"] = reasoning_items
    if thinking_blocks:
        message["thinking_blocks"] = thinking_blocks
    return message


def find_legal_message_start(messages: list[dict[str, Any]]) -> int:
    """找到合法消息片段的起始下标。

    参数:
        messages: 消息数组。

    返回:
        应保留的合法起始下标。
    """
    declared: set[str] = set()
    start = 0
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant":
            for tool_call in message.get("tool_calls") or []:
                if isinstance(tool_call, dict) and tool_call.get("id"):
                    declared.add(str(tool_call["id"]))
        elif role == "tool":
            tool_call_id = message.get("tool_call_id")
            if tool_call_id and str(tool_call_id) not in declared:
                start = index + 1
                declared.clear()
                for previous in messages[start : index + 1]:
                    if previous.get("role") == "assistant":
                        for tool_call in previous.get("tool_calls") or []:
                            if isinstance(tool_call, dict) and tool_call.get("id"):
                                declared.add(str(tool_call["id"]))
    return start


def stringify_text_blocks(content: list[dict[str, Any]]) -> str | None:
    """把纯文本块列表拼接成字符串。

    参数:
        content: 内容块列表。

    返回:
        成功时返回拼接文本；包含非文本块时返回 ``None``。
    """
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            return None
        if block.get("type") != "text":
            return None
        text = block.get("text")
        if not isinstance(text, str):
            return None
        parts.append(text)
    return "\n".join(parts)
