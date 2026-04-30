"""cron 调度工具。"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

from elebot.agent.tools.base import Tool, tool_parameters
from elebot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from elebot.cron import CronJob, CronJobState, CronSchedule, CronService


class _BaseCronTool(Tool):
    """封装 CRUD 调度工具共享的校验与格式化逻辑。"""

    def __init__(self, cron_service: CronService, default_timezone: str = "Asia/Shanghai") -> None:
        """初始化共享调度工具状态。"""
        self._cron = cron_service
        self._default_timezone = default_timezone

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

    @staticmethod
    def _describe_kind(job: CronJob) -> str:
        """返回 job 类型的中文描述。"""
        mapping = {"at": "一次性", "every": "周期", "cron": "Cron"}
        return mapping.get(job.schedule.kind, job.schedule.kind)

    @staticmethod
    def _normalize_instruction(instruction: str | None) -> str | None:
        """去除首尾空白，并拦截空指令。"""
        if instruction is None:
            return None
        normalized = instruction.strip()
        if not normalized:
            return None
        return normalized

    @staticmethod
    def _build_name(instruction: str) -> str:
        """按固定规则生成 job 展示名。"""
        return instruction[:30].strip()

    def _build_schedule(
        self,
        *,
        after_seconds: int | None,
        at: str | None,
        every_seconds: int | None,
    ) -> tuple[CronSchedule, bool] | str:
        """把极简结构化时间参数转换成底层调度对象。"""
        provided = sum(
            1 for value in (after_seconds, at, every_seconds)
            if value not in (None, "")
        )
        if provided != 1:
            return "Error: exactly one of after_seconds, at, or every_seconds is required"

        try:
            from zoneinfo import ZoneInfo

            default_tz = ZoneInfo(self._default_timezone)
        except Exception:
            return f"Error: unknown timezone '{self._default_timezone}'"

        if after_seconds is not None:
            run_at = datetime.now(tz=default_tz) + timedelta(seconds=after_seconds)
            return (
                CronSchedule(kind="at", at_ms=int(run_at.timestamp() * 1000)),
                True,
            )

        if every_seconds is not None:
            return (
                CronSchedule(kind="every", every_ms=every_seconds * 1000),
                False,
            )

        try:
            run_at = datetime.fromisoformat(at or "")
        except ValueError:
            return (
                "Error: invalid ISO datetime format. "
                "Expected e.g. 2026-04-29T09:30:00"
            )
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=default_tz)
        return (
            CronSchedule(kind="at", at_ms=int(run_at.timestamp() * 1000)),
            True,
        )

    def _list_jobs(self) -> str:
        """列出当前 enabled cron jobs。"""
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
            return "Error: job_id is required"
        if self._cron.remove_job(job_id):
            return f"已删除 cron 任务：`{job_id}`"
        return f"Error: cron 任务 `{job_id}` 不存在"

    @staticmethod
    def _reject_unexpected_kwargs(kwargs: dict[str, Any]) -> str | None:
        """拒绝当前协议之外的额外参数。"""
        if not kwargs:
            return None
        unexpected = ", ".join(sorted(kwargs))
        return f"Error: unexpected parameters: {unexpected}"


@tool_parameters(
    tool_parameters_schema(
        instruction=StringSchema("任务触发时要执行的具体指令"),
        after_seconds=IntegerSchema(
            description="从现在起多少秒后执行一次",
            minimum=1,
            nullable=True,
        ),
        at=StringSchema("一次性触发的 ISO 时间", nullable=True),
        every_seconds=IntegerSchema(
            description="按秒重复执行",
            minimum=1,
            nullable=True,
        ),
        required=["instruction"],
    )
)
class CronCreateTool(_BaseCronTool):
    """创建新的 cron job。"""

    def __init__(self, cron_service: CronService, default_timezone: str = "Asia/Shanghai") -> None:
        """初始化创建工具。"""
        super().__init__(cron_service, default_timezone=default_timezone)
        self._channel = "cli"
        self._chat_id = "direct"
        self._cron_context: ContextVar[bool] = ContextVar("cron_context", default=False)

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "cron_create"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return (
            "Create a scheduled job for reminders, delayed actions, or recurring actions. "
            "Provide instruction plus exactly one of after_seconds, at, or every_seconds. "
            f"Naive ISO datetime values default to {self._default_timezone}."
        )

    def set_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
    ) -> None:
        """记录当前会话上下文，供创建任务时复用。"""
        del message_id
        self._channel = channel
        self._chat_id = chat_id

    def set_cron_context(self, active: bool):
        """标记当前是否处于 cron 回调内部。"""
        return self._cron_context.set(active)

    def reset_cron_context(self, token) -> None:
        """恢复之前的 cron 上下文标记。"""
        self._cron_context.reset(token)

    async def execute(
        self,
        *,
        instruction: str,
        after_seconds: int | None = None,
        at: str | None = None,
        every_seconds: int | None = None,
        **kwargs: Any,
    ) -> str:
        """创建一个新的 cron job。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if self._cron_context.get():
            return "Error: cannot create a new cron job from inside a running cron job."

        normalized = self._normalize_instruction(instruction)
        if normalized is None:
            return "Error: instruction is required"

        schedule_result = self._build_schedule(
            after_seconds=after_seconds,
            at=at,
            every_seconds=every_seconds,
        )
        if isinstance(schedule_result, str):
            return schedule_result
        schedule, delete_after_run = schedule_result

        try:
            job = self._cron.add_job(
                name=self._build_name(normalized),
                schedule=schedule,
                message=normalized,
                channel=self._channel,
                chat_id=self._chat_id,
                delete_after_run=delete_after_run,
            )
        except ValueError as exc:
            return f"Error: {exc}"

        return f"已创建 cron 任务：`{job.id}`（{job.name}）"


@tool_parameters(tool_parameters_schema())
class CronListTool(_BaseCronTool):
    """列出当前 enabled cron jobs。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "cron_list"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "List the currently enabled scheduled jobs."

    @property
    def read_only(self) -> bool:
        """声明该工具是只读工具。"""
        return True

    async def execute(self, **kwargs: Any) -> str:
        """列出当前 enabled cron jobs。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        return self._list_jobs()


@tool_parameters(
    tool_parameters_schema(
        job_id=StringSchema("要删除的 job ID"),
        required=["job_id"],
    )
)
class CronDeleteTool(_BaseCronTool):
    """删除指定 cron job。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "cron_delete"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Delete a scheduled job by job_id."

    async def execute(self, *, job_id: str | None = None, **kwargs: Any) -> str:
        """删除指定 cron job。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        return self._remove_job(job_id)


@tool_parameters(
    tool_parameters_schema(
        job_id=StringSchema("要更新的 job ID"),
        instruction=StringSchema("新的任务指令；不传则保持不变", nullable=True),
        after_seconds=IntegerSchema(
            description="改成从现在起多少秒后执行一次",
            minimum=1,
            nullable=True,
        ),
        at=StringSchema("改成新的 ISO 一次性触发时间", nullable=True),
        every_seconds=IntegerSchema(
            description="改成新的按秒重复执行间隔",
            minimum=1,
            nullable=True,
        ),
        required=["job_id"],
    )
)
class CronUpdateTool(_BaseCronTool):
    """更新指定 cron job。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "cron_update"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return (
            "Update an existing scheduled job by job_id. "
            "You may change instruction, or replace the schedule using exactly one "
            "of after_seconds, at, or every_seconds."
        )

    async def execute(
        self,
        *,
        job_id: str | None = None,
        instruction: str | None = None,
        after_seconds: int | None = None,
        at: str | None = None,
        every_seconds: int | None = None,
        **kwargs: Any,
    ) -> str:
        """更新指定 cron job。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error

        if not job_id:
            return "Error: job_id is required"

        schedule_values = (after_seconds, at, every_seconds)
        schedule_provided = sum(1 for value in schedule_values if value not in (None, "")) > 0

        normalized_instruction = self._normalize_instruction(instruction)
        if instruction is not None and normalized_instruction is None:
            return "Error: instruction must not be empty"
        if normalized_instruction is None and not schedule_provided:
            return "Error: at least one of instruction, after_seconds, at, or every_seconds is required"

        schedule: CronSchedule | None = None
        delete_after_run: bool | None = None
        if schedule_provided:
            schedule_result = self._build_schedule(
                after_seconds=after_seconds,
                at=at,
                every_seconds=every_seconds,
            )
            if isinstance(schedule_result, str):
                return schedule_result
            schedule, delete_after_run = schedule_result

        try:
            job = self._cron.update_job(
                job_id,
                message=normalized_instruction,
                name=self._build_name(normalized_instruction) if normalized_instruction else None,
                schedule=schedule,
                delete_after_run=delete_after_run,
            )
        except ValueError as exc:
            return f"Error: {exc}"

        if job is None:
            return f"Error: cron 任务 `{job_id}` 不存在"
        return f"已更新 cron 任务：`{job.id}`（{job.name}）"
