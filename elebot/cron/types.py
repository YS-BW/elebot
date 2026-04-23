"""中文模块说明：冻结模块，保留实现且不接入默认主链路。"""


from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CronSchedule:
    """中文说明：CronSchedule。"""
    """Schedule definition for a cron job."""
    kind: Literal["at", "every", "cron"]
    # 中文说明：For "at": timestamp in ms
    at_ms: int | None = None
    # 中文说明：For "every": interval in ms
    every_ms: int | None = None
    # 中文说明：For "cron": cron expression (e.g. "0 9 * * *")
    expr: str | None = None
    # 中文说明：Timezone for cron expressions
    tz: str | None = None


@dataclass
class CronPayload:
    """中文说明：CronPayload。"""
    """What to do when the job runs."""
    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""
    # 中文说明：Deliver response to channel
    deliver: bool = False
    channel: str | None = None  # 中文说明：e.g. "whatsapp"
    to: str | None = None  # 中文说明：e.g. phone number


@dataclass
class CronRunRecord:
    """中文说明：CronRunRecord。"""
    """A single execution record for a cron job."""
    run_at_ms: int
    status: Literal["ok", "error", "skipped"]
    duration_ms: int = 0
    error: str | None = None


@dataclass
class CronJobState:
    """中文说明：CronJobState。"""
    """Runtime state of a job."""
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error", "skipped"] | None = None
    last_error: str | None = None
    run_history: list[CronRunRecord] = field(default_factory=list)


@dataclass
class CronJob:
    """中文说明：CronJob。"""
    """A scheduled job."""
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
        """中文说明：from_dict。

        参数:
            kwargs: 待补充参数说明。

        返回:
            待补充返回值说明。
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
    """中文说明：CronStore。"""
    """Persistent store for cron jobs."""
    version: int = 1
    jobs: list[CronJob] = field(default_factory=list)
