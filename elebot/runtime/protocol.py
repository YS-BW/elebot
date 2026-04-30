"""对外脚本化入口共享的 JSON 协议辅助函数。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from elebot.bus.events import OutboundMessage
from elebot.runtime.models import InterruptResult, RuntimeStatusSnapshot


def default_session_id(channel: str, chat_id: str) -> str:
    """返回默认会话键。"""
    return f"{channel}:{chat_id}"


def build_ready_event(**payload: Any) -> dict[str, Any]:
    """构造 ready 事件。"""
    return {"type": "ready", **payload}


def build_progress_event(
    *,
    session_id: str,
    content: str,
    tool_hint: bool = False,
) -> dict[str, Any]:
    """构造进度事件。"""
    return {
        "type": "progress",
        "session_id": session_id,
        "content": content,
        "tool_hint": tool_hint,
    }


def build_delta_event(*, session_id: str, content: str) -> dict[str, Any]:
    """构造正文增量事件。"""
    return {
        "type": "delta",
        "session_id": session_id,
        "content": content,
    }


def build_stream_end_event(*, session_id: str, resuming: bool) -> dict[str, Any]:
    """构造流式收尾事件。"""
    return {
        "type": "stream_end",
        "session_id": session_id,
        "resuming": resuming,
    }


def build_message_event(
    *,
    session_id: str,
    message: OutboundMessage,
) -> dict[str, Any]:
    """构造最终消息事件。"""
    return {
        "type": "message",
        "session_id": session_id,
        "content": message.content,
        "reply_to": message.reply_to,
        "media": list(message.media),
        "metadata": dict(message.metadata or {}),
    }


def build_error_event(message: str, *, session_id: str | None = None) -> dict[str, Any]:
    """构造错误事件。"""
    payload: dict[str, Any] = {"type": "error", "message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    return payload


def build_interrupt_result_event(result: InterruptResult) -> dict[str, Any]:
    """构造中断结果事件。"""
    return {
        "type": "interrupt_result",
        "session_id": result.session_id,
        "result": asdict(result),
    }


def build_reset_done_event(*, session_id: str) -> dict[str, Any]:
    """构造会话重置完成事件。"""
    return {"type": "reset_done", "session_id": session_id}


def build_status_result_event(snapshot: RuntimeStatusSnapshot, *, session_id: str) -> dict[str, Any]:
    """构造状态快照事件。"""
    return {
        "type": "status_result",
        "session_id": session_id,
        "snapshot": asdict(snapshot),
    }
