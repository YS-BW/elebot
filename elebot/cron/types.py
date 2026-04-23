"""中文模块说明：冻结模块，保留实现且不接入默认主链路。"""


from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CronSchedule:
    """描述任务何时触发。"""
    kind: Literal["at", "every", "cron"]
    # `at` 模式直接保存绝对时间戳，避免运行时再做二次推导。
    at_ms: int | None = None
    # `every` 模式只关心固定间隔，单位统一用毫秒。
    every_ms: int | None = None
    # `cron` 模式沿用标准表达式，交给 croniter 解析。
    expr: str | None = None
    # 时区只对 cron 表达式生效，固定间隔和单次任务不需要。
    tz: str | None = None


@dataclass
class CronPayload:
    """描述任务触发后要执行什么。"""
    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""
    # 是否把执行结果主动投递回外部通道。
    deliver: bool = False
    channel: str | None = None  # 目标通道名，例如 `whatsapp`。
    to: str | None = None  # 通道内目标标识，例如手机号或 chat id。


@dataclass
class CronRunRecord:
    """记录一次任务执行的结果快照。"""
    run_at_ms: int
    status: Literal["ok", "error", "skipped"]
    duration_ms: int = 0
    error: str | None = None


@dataclass
class CronJobState:
    """保存任务运行过程中的可变状态。"""
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error", "skipped"] | None = None
    last_error: str | None = None
    run_history: list[CronRunRecord] = field(default_factory=list)


@dataclass
class CronJob:
    """表示一条完整的定时任务。"""
    id: str
    name: str
    enabled: bool = True
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind="every"))
    payload: CronPayload = field(default_factory=CronPayload)
    state: CronJobState = field(default_factory=CronJobState)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    delete_after_run: bool = False

    @classmethod
    def from_dict(cls, kwargs: dict):
        """把持久化字典还原成完整的任务对象。

        这里会把嵌套的 schedule、payload、state 和 run_history
        一次性恢复成 dataclass，避免上层到处判断字典结构。
        """
        state_kwargs = dict(kwargs.get("state", {}))
        state_kwargs["run_history"] = [
            record if isinstance(record, CronRunRecord) else CronRunRecord(**record)
            for record in state_kwargs.get("run_history", [])
        ]
        kwargs["schedule"] = CronSchedule(**kwargs.get("schedule", {"kind": "every"}))
        kwargs["payload"] = CronPayload(**kwargs.get("payload", {}))
        kwargs["state"] = CronJobState(**state_kwargs)
        return cls(**kwargs)


@dataclass
class CronStore:
    """表示定时任务文件在内存里的完整状态。"""
    version: int = 1
    jobs: list[CronJob] = field(default_factory=list)
