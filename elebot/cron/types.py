"""Cron 调度核心数据类型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class CronSchedule:
    """描述一个 cron job 的调度方式。"""

    kind: Literal["at", "every", "cron"]
    at_ms: int | None = None
    every_ms: int | None = None
    expr: str | None = None
    tz: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CronSchedule":
        """从字典恢复调度对象。"""
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        """导出可持久化的调度字典。"""
        return asdict(self)


@dataclass(slots=True)
class CronPayload:
    """描述 job 触发后要执行的 agent 指令。"""

    message: str
    channel: str = "cli"
    chat_id: str = "direct"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CronPayload":
        """从字典恢复 payload 对象。"""
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        """导出可持久化的 payload 字典。"""
        return asdict(self)


@dataclass(slots=True)
class CronRunRecord:
    """记录一次 job 执行结果。"""

    run_at_ms: int
    status: Literal["ok", "error"]
    duration_ms: int = 0
    error: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CronRunRecord":
        """从字典恢复执行记录。"""
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        """导出可持久化的执行记录。"""
        return asdict(self)


@dataclass(slots=True)
class CronJobState:
    """描述 job 的运行态。"""

    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error"] | None = None
    last_error: str | None = None
    run_history: list[CronRunRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CronJobState":
        """从字典恢复运行态对象。"""
        return cls(
            next_run_at_ms=payload.get("next_run_at_ms"),
            last_run_at_ms=payload.get("last_run_at_ms"),
            last_status=payload.get("last_status"),
            last_error=payload.get("last_error"),
            run_history=[
                item if isinstance(item, CronRunRecord) else CronRunRecord.from_dict(item)
                for item in payload.get("run_history", [])
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        """导出可持久化的运行态字典。"""
        data = asdict(self)
        data["run_history"] = [item.to_dict() for item in self.run_history]
        return data


@dataclass(slots=True)
class CronJob:
    """描述一个完整的 cron job。"""

    id: str
    name: str
    enabled: bool
    schedule: CronSchedule
    payload: CronPayload
    state: CronJobState = field(default_factory=CronJobState)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    delete_after_run: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CronJob":
        """从字典恢复 job 对象。"""
        return cls(
            id=payload["id"],
            name=payload["name"],
            enabled=payload.get("enabled", True),
            schedule=CronSchedule.from_dict(payload.get("schedule", {"kind": "every"})),
            payload=CronPayload.from_dict(payload.get("payload", {"message": ""})),
            state=CronJobState.from_dict(payload.get("state", {})),
            created_at_ms=payload.get("created_at_ms", 0),
            updated_at_ms=payload.get("updated_at_ms", 0),
            delete_after_run=payload.get("delete_after_run", False),
        )

    def to_dict(self) -> dict[str, Any]:
        """导出可持久化的 job 字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "schedule": self.schedule.to_dict(),
            "payload": self.payload.to_dict(),
            "state": self.state.to_dict(),
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "delete_after_run": self.delete_after_run,
        }
