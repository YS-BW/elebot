"""runtime 内部结构化返回类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

InterruptReason = Literal["user_interrupt", "runtime_interrupt", "tool_interrupt"]


@dataclass(slots=True)
class RuntimeStatusSnapshot:
    """描述 runtime 暴露给外部入口的状态快照。"""

    version: str
    model: str
    start_time: float
    last_usage: dict[str, int]
    context_window_tokens: int
    session_msg_count: int
    context_tokens_estimate: int
    search_usage_text: str | None = None


@dataclass(slots=True)
class InterruptResult:
    """描述一次会话中断请求的处理结果。"""

    session_id: str
    reason: InterruptReason
    accepted: bool
    cancelled_tasks: int
    already_interrupting: bool = False


@dataclass(slots=True)
class DreamLogResult:
    """描述 runtime 层暴露的 Dream 日志结果。"""

    status: str
    requested_sha: str | None = None
    sha: str | None = None
    timestamp: str | None = None
    message: str | None = None
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DreamRestoreResult:
    """描述 runtime 层暴露的 Dream 恢复结果。"""

    status: str
    requested_sha: str
    new_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    message: str | None = None
