"""定时任务工具。"""

from __future__ import annotations

import uuid
from typing import Any

from elebot.agent.tools.base import Tool, tool_parameters
from elebot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from elebot.session.manager import SessionManager
from elebot.tasks.helpers import (
    build_scheduled_task,
    build_task_proposal_payload,
    format_task_summary,
)
from elebot.tasks.service import TaskService

PENDING_TASK_PROPOSAL_KEY = "pending_task_proposal"
TASK_CONFIRM_YES = {"是", "创建吧", "帮我加上", "可以提醒我"}


class _TaskTool(Tool):
    """任务工具共享基类。"""

    def __init__(
        self,
        task_service: TaskService,
        default_timezone: str | None = None,
        session_manager: SessionManager | None = None,
    ):
        """初始化任务工具。

        参数:
            task_service: 任务领域服务。
            default_timezone: 默认时区名称。
            session_manager: 会话管理器。

        返回:
            无返回值。
        """
        self.task_service = task_service
        self.default_timezone = default_timezone
        self.session_manager = session_manager

    def _load_pending_proposal(self, session_key: str) -> dict[str, Any] | None:
        """读取待确认任务 proposal。

        参数:
            session_key: 会话键。

        返回:
            proposal 字典；不存在时返回 ``None``。
        """
        if self.session_manager is None:
            return None
        session = self.session_manager.get_or_create(session_key)
        proposal = session.metadata.get(PENDING_TASK_PROPOSAL_KEY)
        return proposal if isinstance(proposal, dict) else None

    def _save_pending_proposal(self, session_key: str, proposal: dict[str, Any] | None) -> None:
        """保存或清除待确认 proposal。"""
        if self.session_manager is None:
            return
        session = self.session_manager.get_or_create(session_key)
        if proposal is None:
            session.metadata.pop(PENDING_TASK_PROPOSAL_KEY, None)
        else:
            session.metadata[PENDING_TASK_PROPOSAL_KEY] = proposal
        self.session_manager.save(session)


@tool_parameters(
    tool_parameters_schema(
        content=StringSchema("任务触发时发送给 agent 的内容", min_length=1),
        schedule_type=StringSchema(
            "任务类型：once / interval / daily",
            enum=["once", "interval", "daily"],
        ),
        run_at=StringSchema("一次性任务的 ISO 时间", nullable=True),
        interval_seconds=IntegerSchema(
            description="间隔任务的秒数",
            minimum=1,
            nullable=True,
        ),
        daily_time=StringSchema("每日任务时间，格式 HH:MM", nullable=True),
        timezone=StringSchema("任务时区，例如 Asia/Shanghai", nullable=True),
        session_key=StringSchema("任务绑定的会话键", min_length=1),
        required=["content", "schedule_type", "session_key"],
    )
)
class CreateTaskTool(_TaskTool):
    """创建定时任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "create_task"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "Create a scheduled task after the user has clearly confirmed the reminder."

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(
        self,
        *,
        content: str,
        schedule_type: str,
        session_key: str,
        run_at: str | None = None,
        interval_seconds: int | None = None,
        daily_time: str | None = None,
        timezone: str | None = None,
        **kwargs: Any,
    ) -> str:
        """创建任务。

        返回:
            任务创建结果文本。
        """
        proposal = self._load_pending_proposal(session_key)
        if proposal is None:
            return "Error: 创建任务前必须先提出任务建议并等待用户确认。"
        if proposal.get("content") != content or proposal.get("schedule_type") != schedule_type:
            return "Error: 当前任务参数与待确认 proposal 不一致，请重新确认。"
        task, error = build_scheduled_task(
            content=content,
            schedule_type=schedule_type,
            session_key=session_key,
            default_timezone=self.default_timezone or "Asia/Shanghai",
            run_at=run_at,
            interval_seconds=interval_seconds,
            daily_time=daily_time,
            timezone=timezone,
            source="agent",
            task_id=f"task_{uuid.uuid4().hex[:12]}",
        )
        if error or task is None:
            return f"Error: {error}"
        self.task_service.upsert(task)
        self._save_pending_proposal(session_key, None)
        return (
            f"已创建任务：`{task.task_id}`\n"
            f"{format_task_summary(task)}"
        )


@tool_parameters(
    tool_parameters_schema(
        content=StringSchema("任务触发时发送给 agent 的内容", min_length=1),
        schedule_type=StringSchema(
            "任务类型：once / interval / daily",
            enum=["once", "interval", "daily"],
        ),
        run_at=StringSchema("一次性任务的 ISO 时间", nullable=True),
        interval_seconds=IntegerSchema(
            description="间隔任务的秒数",
            minimum=1,
            nullable=True,
        ),
        daily_time=StringSchema("每日任务时间，格式 HH:MM", nullable=True),
        timezone=StringSchema("任务时区，例如 Asia/Shanghai", nullable=True),
        session_key=StringSchema("任务绑定的会话键", min_length=1),
        required=["content", "schedule_type", "session_key"],
    )
)
class ProposeTaskTool(_TaskTool):
    """提出待确认的任务建议。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "propose_task"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "Propose a scheduled task and ask the user to confirm before creation."

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(
        self,
        *,
        content: str,
        schedule_type: str,
        session_key: str,
        run_at: str | None = None,
        interval_seconds: int | None = None,
        daily_time: str | None = None,
        timezone: str | None = None,
        **kwargs: Any,
    ) -> str:
        """保存待确认 proposal 并返回确认话术。"""
        proposal, error = build_task_proposal_payload(
            content=content,
            schedule_type=schedule_type,
            session_key=session_key,
            default_timezone=self.default_timezone or "Asia/Shanghai",
            run_at=run_at,
            interval_seconds=interval_seconds,
            daily_time=daily_time,
            timezone=timezone,
        )
        if error or proposal is None:
            return f"Error: {error}"
        self._save_pending_proposal(session_key, proposal)
        task, _ = build_scheduled_task(
            content=proposal["content"],
            schedule_type=proposal["schedule_type"],
            session_key=proposal["session_key"],
            default_timezone=self.default_timezone or "Asia/Shanghai",
            run_at=proposal.get("run_at"),
            interval_seconds=proposal.get("interval_seconds"),
            daily_time=proposal.get("daily_time"),
            timezone=proposal.get("timezone"),
            source="agent",
        )
        assert task is not None
        return (
            "我理解为要创建下面这个任务：\n"
            f"{format_task_summary(task)}\n"
            "如果确认，请直接回复“是”或“创建吧”。"
        )


@tool_parameters(
    tool_parameters_schema(
        session_key=StringSchema("可选；只列出某个会话下的任务", nullable=True),
    )
)
class ListTasksTool(_TaskTool):
    """列出定时任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "list_tasks"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "List scheduled tasks, optionally filtered by session_key."

    @property
    def read_only(self) -> bool:
        """声明该工具为只读工具。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, *, session_key: str | None = None, **kwargs: Any) -> str:
        """列出任务。

        返回:
            任务列表文本。
        """
        tasks = self.task_service.list_all()
        if session_key:
            tasks = self.task_service.list_by_session(session_key)
        if not tasks:
            return "当前没有任务。"
        lines = ["当前任务："]
        for task in tasks:
            status = "启用" if task.enabled else "禁用"
            lines.append(
                f"- `{task.task_id}` {task.schedule_type} {status} "
                f"[{task.session_key}] -> {task.content} "
                f"(next: {task.next_run_at or '无'})"
            )
        return "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要更新的任务 ID", min_length=1),
        content=StringSchema("更新后的任务内容", min_length=1, nullable=True),
        schedule_type=StringSchema(
            "更新后的任务类型：once / interval / daily",
            enum=["once", "interval", "daily"],
            nullable=True,
        ),
        run_at=StringSchema("更新后的一次性任务 ISO 时间", nullable=True),
        interval_seconds=IntegerSchema(
            description="更新后的间隔秒数",
            minimum=1,
            nullable=True,
        ),
        daily_time=StringSchema("更新后的每日任务时间，格式 HH:MM", nullable=True),
        timezone=StringSchema("更新后的任务时区", nullable=True),
        required=["task_id"],
    )
)
class UpdateTaskTool(_TaskTool):
    """更新定时任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "update_task"

    @property
    def description(self) -> str:
        """返回工具用途说明。"""
        return "Update an existing scheduled task."

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。"""
        return True

    async def execute(
        self,
        *,
        task_id: str,
        content: str | None = None,
        schedule_type: str | None = None,
        run_at: str | None = None,
        interval_seconds: int | None = None,
        daily_time: str | None = None,
        timezone: str | None = None,
        **kwargs: Any,
    ) -> str:
        """更新任务。"""
        existing = self.task_service.get(task_id)
        if existing is None:
            return f"找不到任务：`{task_id}`。"
        task, error = build_scheduled_task(
            content=content or existing.content,
            schedule_type=schedule_type or existing.schedule_type,
            session_key=existing.session_key,
            default_timezone=self.default_timezone or "Asia/Shanghai",
            run_at=run_at if run_at is not None else existing.run_at,
            interval_seconds=interval_seconds if interval_seconds is not None else existing.interval_seconds,
            daily_time=daily_time if daily_time is not None else existing.daily_time,
            timezone=timezone or existing.timezone,
            source=existing.source,
            task_id=existing.task_id,
            existing=existing,
        )
        if error or task is None:
            return f"Error: {error}"
        self.task_service.upsert(task)
        return (
            f"已更新任务：`{task.task_id}`\n"
            f"{format_task_summary(task)}"
        )


__all__ = [
    "CreateTaskTool",
    "ListTasksTool",
    "ProposeTaskTool",
    "RemoveTaskTool",
    "TASK_CONFIRM_YES",
    "UpdateTaskTool",
    "PENDING_TASK_PROPOSAL_KEY",
]


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要删除的任务 ID", min_length=1),
        required=["task_id"],
    )
)
class RemoveTaskTool(_TaskTool):
    """删除定时任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "remove_task"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "Remove a scheduled task by task_id."

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, *, task_id: str, **kwargs: Any) -> str:
        """删除任务。

        返回:
            删除结果文本。
        """
        if self.task_service.remove(task_id):
            return f"已删除任务：`{task_id}`。"
        return f"找不到任务：`{task_id}`。"
