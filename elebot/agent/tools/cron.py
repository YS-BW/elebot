"""cron 调度工具。"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from typing import Any

from elebot.agent.tools.base import Tool, tool_parameters
from elebot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from elebot.cron import CronJob, CronJobState, CronSchedule, CronService


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema("要执行的动作", enum=["add", "list", "remove"]),
        name=StringSchema("可选的展示名称；仅作为任务标题，不是执行内容", nullable=True),
        instruction=StringSchema("add 时必填：任务触发时要执行的具体指令", nullable=True),
        every_seconds=IntegerSchema(
            description="按秒重复执行",
            minimum=1,
            nullable=True,
        ),
        cron_expr=StringSchema("Cron 表达式，例如 0 9 * * 1-5", nullable=True),
        tz=StringSchema("Cron 表达式使用的 IANA 时区", nullable=True),
        at=StringSchema("一次性触发的 ISO 时间", nullable=True),
        job_id=StringSchema("要删除的 job ID", nullable=True),
        required=["action"],
    )
)
class CronTool(Tool):
    """给模型使用的统一 cron 工具。"""

    def __init__(self, cron_service: CronService, default_timezone: str = "Asia/Shanghai") -> None:
        """初始化 cron 工具。"""
        self._cron = cron_service
        self._default_timezone = default_timezone
        self._channel = "cli"
        self._chat_id = "direct"
        self._cron_context: ContextVar[bool] = ContextVar("cron_context", default=False)

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "cron"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return (
            "Manage scheduled jobs with a single tool. "
            "Use this instead of exec for any delayed, reminder, or recurring action. "
            "For add, provide instruction as the actual payload and use name only as an optional label. "
            f"Naive ISO datetime values default to {self._default_timezone}."
        )

    def set_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
    ) -> None:
        """记录当前会话上下文，供 add 动作复用。"""
        del message_id
        self._channel = channel
        self._chat_id = chat_id

    def set_cron_context(self, active: bool):
        """标记当前是否处于 cron 回调内部。"""
        return self._cron_context.set(active)

    def reset_cron_context(self, token) -> None:
        """恢复之前的 cron 上下文标记。"""
        self._cron_context.reset(token)

    def _validate_timezone(self, tz_name: str) -> str | None:
        """把时区校验错误转成用户可读文本。"""
        try:
            self._cron._validate_timezone(tz_name)
        except ValueError as exc:
            return f"Error: {exc}"
        return None

    def _display_timezone(self, schedule: CronSchedule) -> str:
        """选择当前 job 展示时应该使用的时区。"""
        return schedule.tz or self._default_timezone

    def _format_timestamp(self, ms: int, tz_name: str) -> str:
        """把毫秒时间戳格式化成人类可读文本。"""
        from zoneinfo import ZoneInfo

        dt = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(tz_name))
        return f"{dt.isoformat()} ({tz_name})"

    def _format_timing(self, schedule: CronSchedule) -> str:
        """格式化 job 的调度说明。"""
        if schedule.kind == "cron" and schedule.expr:
            return f"cron: {schedule.expr} ({self._display_timezone(schedule)})"
        if schedule.kind == "every" and schedule.every_ms is not None:
            seconds = schedule.every_ms // 1000
            return f"every {seconds}s"
        if schedule.kind == "at" and schedule.at_ms is not None:
            return f"at {self._format_timestamp(schedule.at_ms, self._display_timezone(schedule))}"
        return schedule.kind

    def _format_state(self, state: CronJobState, schedule: CronSchedule) -> list[str]:
        """格式化 job 执行状态。"""
        lines: list[str] = []
        tz_name = self._display_timezone(schedule)
        if state.last_run_at_ms is not None:
            detail = f"上次执行：{self._format_timestamp(state.last_run_at_ms, tz_name)}"
            if state.last_status is not None:
                detail += f"（{state.last_status}"
                if state.last_error:
                    detail += f"，{state.last_error}"
                detail += "）"
            lines.append(detail)
        if state.next_run_at_ms is not None:
            lines.append(f"下次触发：{self._format_timestamp(state.next_run_at_ms, tz_name)}")
        return lines

    async def execute(
        self,
        *,
        action: str,
        name: str | None = None,
        instruction: str | None = None,
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        at: str | None = None,
        job_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """执行 cron 工具动作。"""
        job_alias = kwargs.pop("job", None)
        if isinstance(job_alias, dict):
            if not name and isinstance(job_alias.get("name"), str) and job_alias["name"].strip():
                name = job_alias["name"].strip()
            if at in (None, "") and isinstance(job_alias.get("at"), str) and job_alias["at"].strip():
                at = job_alias["at"].strip()
            if every_seconds is None and job_alias.get("every_seconds") not in (None, ""):
                every_seconds = job_alias.get("every_seconds")
            if not cron_expr and isinstance(job_alias.get("cron_expr"), str) and job_alias["cron_expr"].strip():
                cron_expr = job_alias["cron_expr"].strip()
            if not tz and isinstance(job_alias.get("tz"), str) and job_alias["tz"].strip():
                tz = job_alias["tz"].strip()
            payload = job_alias.get("payload")
            if not instruction and isinstance(payload, dict):
                for alias in ("instruction", "message", "prompt", "command"):
                    alias_value = payload.get(alias)
                    if isinstance(alias_value, str) and alias_value.strip():
                        instruction = alias_value.strip()
                        break
        for alias in ("message", "prompt", "command"):
            alias_value = kwargs.pop(alias, None)
            if not instruction and isinstance(alias_value, str) and alias_value.strip():
                instruction = alias_value.strip()
                break
        if not instruction and name and action == "add":
            # 对模型漏传 instruction 的情况做最后一层兜底，避免再次重试创建同一任务。
            instruction = name.strip()
        del kwargs
        if action == "add":
            return self._add_job(
                name=name,
                instruction=instruction,
                every_seconds=every_seconds,
                cron_expr=cron_expr,
                tz=tz,
                at=at,
            )
        if action == "list":
            return self._list_jobs()
        if action == "remove":
            return self._remove_job(job_id)
        return f"Error: unsupported action '{action}'"

    def _add_job(
        self,
        *,
        name: str | None,
        instruction: str | None,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
    ) -> str:
        """新增一个 cron job。"""
        if self._cron_context.get():
            return "Error: cannot create a new cron job from inside a running cron job."
        if not instruction or not instruction.strip():
            return "Error: instruction is required for add"
        instruction = instruction.strip()

        provided = sum(
            1 for value in (every_seconds, cron_expr, at)
            if value not in (None, "")
        )
        if provided != 1:
            return "Error: exactly one of every_seconds, cron_expr, or at is required"

        if tz and not cron_expr:
            return "Error: tz can only be used with cron_expr"
        if tz:
            if error := self._validate_timezone(tz):
                return error

        delete_after_run = False
        try:
            if every_seconds is not None:
                schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
            elif cron_expr:
                effective_tz = tz or self._default_timezone
                if error := self._validate_timezone(effective_tz):
                    return error
                schedule = CronSchedule(kind="cron", expr=cron_expr, tz=effective_tz)
            else:
                from zoneinfo import ZoneInfo

                try:
                    run_at = datetime.fromisoformat(at or "")
                except ValueError:
                    return (
                        "Error: invalid ISO datetime format. "
                        "Expected e.g. 2026-04-29T09:30:00"
                    )
                if run_at.tzinfo is None:
                    if error := self._validate_timezone(self._default_timezone):
                        return error
                    run_at = run_at.replace(tzinfo=ZoneInfo(self._default_timezone))
                schedule = CronSchedule(
                    kind="at",
                    at_ms=int(run_at.timestamp() * 1000),
                )
                delete_after_run = True

            job = self._cron.add_job(
                name=(name or instruction[:30]).strip(),
                schedule=schedule,
                message=instruction,
                channel=self._channel,
                chat_id=self._chat_id,
                delete_after_run=delete_after_run,
            )
        except ValueError as exc:
            return f"Error: {exc}"

        return f"已创建 cron 任务：`{job.id}`（{job.name}）"

    def _describe_kind(self, job: CronJob) -> str:
        """返回 job 类型的中文描述。"""
        mapping = {"at": "一次性", "every": "周期", "cron": "Cron"}
        return mapping.get(job.schedule.kind, job.schedule.kind)

    def _list_jobs(self) -> str:
        """列出当前 cron jobs。"""
        jobs = self._cron.list_jobs()
        if not jobs:
            return "当前没有 cron 任务。"

        lines = [f"当前有 {len(jobs)} 个 cron 任务：", ""]
        for job in jobs:
            status = "已启用" if job.enabled else "已禁用"
            lines.append(f" • {job.id}（{self._describe_kind(job)}，{status}）")
            lines.append(f"    • 名称：{job.name}")
            lines.append(f"    • 指令：{job.payload.message}")
            lines.append(f"    • 调度：{self._format_timing(job.schedule)}")
            for detail in self._format_state(job.state, job.schedule):
                lines.append(f"    • {detail}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _remove_job(self, job_id: str | None) -> str:
        """删除指定 cron job。"""
        if not job_id:
            return "Error: job_id is required for remove"
        if self._cron.remove_job(job_id):
            return f"已删除 cron 任务：`{job_id}`"
        return f"Error: cron 任务 `{job_id}` 不存在"
