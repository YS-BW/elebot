"""定时任务数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class ScheduledTask:
    """表示一个可持久化的定时任务。"""

    task_id: str
    session_key: str
    content: str
    schedule_type: str
    run_at: str | None
    interval_seconds: int | None
    daily_time: str | None
    timezone: str | None
    enabled: bool
    created_at: str
    updated_at: str
    last_run_at: str | None
    next_run_at: str | None
    source: str
    run_count: int = 0
    last_status: str | None = None
    last_error: str | None = None
    last_finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """把任务对象转换为可序列化字典。

        返回:
            包含全部字段的字典。
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScheduledTask":
        """从字典恢复任务对象。

        参数:
            payload: 任务字典。

        返回:
            反序列化后的任务对象。
        """
        return cls(
            task_id=str(payload["task_id"]),
            session_key=str(payload["session_key"]),
            content=str(payload["content"]),
            schedule_type=str(payload["schedule_type"]),
            run_at=payload.get("run_at"),
            interval_seconds=payload.get("interval_seconds"),
            daily_time=payload.get("daily_time"),
            timezone=payload.get("timezone"),
            enabled=bool(payload.get("enabled", True)),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            last_run_at=payload.get("last_run_at"),
            next_run_at=payload.get("next_run_at"),
            source=str(payload.get("source") or "agent"),
            run_count=int(payload.get("run_count") or 0),
            last_status=payload.get("last_status"),
            last_error=payload.get("last_error"),
            last_finished_at=payload.get("last_finished_at"),
        )
