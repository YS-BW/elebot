"""把聊天补全风格的消息与工具定义转换为 Responses API 格式。"""

from __future__ import annotations

import json
from typing import Any


def convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """把消息列表转换为 Responses API 的输入结构。

    参数:
        messages: 聊天补全风格的消息列表。

    返回:
        二元组 ``(system_prompt, input_items)``，分别表示系统提示词与 Responses API 的 ``input`` 数组。
    """
    system_prompt = ""
    input_items: list[dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            system_prompt = content if isinstance(content, str) else ""
            continue

        if role == "user":
            input_items.append(convert_user_message(content))
            continue

        if role == "assistant":
            if isinstance(content, str) and content:
                input_items.append({
                    "type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": content}],
                    "status": "completed", "id": f"msg_{idx}",
                })
            for tool_call in msg.get("tool_calls", []) or []:
                fn = tool_call.get("function") or {}
                call_id, item_id = split_tool_call_id(tool_call.get("id"))
                input_items.append({
                    "type": "function_call",
                    "id": item_id or f"fc_{idx}",
                    "call_id": call_id or f"call_{idx}",
                    "name": fn.get("name"),
                    "arguments": fn.get("arguments") or "{}",
                })
            continue

        if role == "tool":
            call_id, _ = split_tool_call_id(msg.get("tool_call_id"))
            output_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            input_items.append({"type": "function_call_output", "call_id": call_id, "output": output_text})

    return system_prompt, input_items


def convert_user_message(content: Any) -> dict[str, Any]:
    """把单条用户消息内容转换为 Responses API 结构。

    参数:
        content: 用户消息的 ``content`` 字段。

    返回:
        符合 Responses API 要求的用户消息字典。
    """
    if isinstance(content, str):
        return {"role": "user", "content": [{"type": "input_text", "text": content}]}
    if isinstance(content, list):
        converted: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                converted.append({"type": "input_text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url")
                if url:
                    converted.append({"type": "input_image", "image_url": url, "detail": "auto"})
        if converted:
            return {"role": "user", "content": converted}
    return {"role": "user", "content": [{"type": "input_text", "text": ""}]}


def convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把工具定义转换为 Responses API 需要的扁平格式。

    参数:
        tools: OpenAI 风格的工具定义列表。

    返回:
        Responses API 可直接使用的工具列表。
    """
    converted: list[dict[str, Any]] = []
    for tool in tools:
        fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
        name = fn.get("name")
        if not name:
            continue
        params = fn.get("parameters") or {}
        converted.append({
            "type": "function",
            "name": name,
            "description": fn.get("description") or "",
            "parameters": params if isinstance(params, dict) else {},
        })
    return converted


def split_tool_call_id(tool_call_id: Any) -> tuple[str, str | None]:
    """拆分复合形式的工具调用标识。

    参数:
        tool_call_id: 可能形如 ``call_id|item_id`` 的标识值。

    返回:
        二元组 ``(call_id, item_id)``，其中 ``item_id`` 可能为 ``None``。
    """
    if isinstance(tool_call_id, str) and tool_call_id:
        if "|" in tool_call_id:
            call_id, item_id = tool_call_id.split("|", 1)
            return call_id, item_id or None
        return tool_call_id, None
    return "call_0", None
