"""定时任务后台轮询服务。"""

from __future__ import annotations

import asyncio
from datetime import datetime

from elebot.bus.queue import MessageBus
from elebot.tasks.models import ScheduledTask
from elebot.tasks.scheduler import collect_due_tasks, compute_next_run
from elebot.tasks.store import TaskStore
from elebot.tasks.trigger import build_task_inbound_message
from elebot.utils.helpers import timestamp


class TaskService:
    """在 Agent 进程内轮询并触发定时任务。"""

    def __init__(
        self,
        bus: MessageBus,
        *,
        store: TaskStore | None = None,
        poll_interval_seconds: int = 10,
        default_timezone: str | None = None,
    ):
        """初始化任务服务。

        参数:
            bus: 用于投递触发消息的消息总线。
            store: 任务存储。
            poll_interval_seconds: 轮询间隔秒数。
            default_timezone: 默认时区名称。

        返回:
            无返回值。
        """
        self.bus = bus
        self.store = store or TaskStore()
        self.poll_interval_seconds = poll_interval_seconds
        self.default_timezone = default_timezone
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """启动后台轮询。

        返回:
            无返回值。
        """
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """停止后台轮询。

        返回:
            无返回值。
        """
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        """后台循环调度任务。"""
        while self._running:
            await self.tick()
            await asyncio.sleep(self.poll_interval_seconds)

    async def tick(self) -> None:
        """执行一次调度检查。

        返回:
            无返回值。
        """
        now = datetime.now().astimezone()
        tasks = self.store.load_all()
        due_tasks = collect_due_tasks(tasks, now, default_timezone=self.default_timezone)
        if not due_tasks:
            return

        updated: dict[str, ScheduledTask] = {}
        for task in due_tasks:
            await self.bus.publish_inbound(build_task_inbound_message(task))
            task.last_run_at = now.isoformat()
            task.updated_at = timestamp()
            task.run_count += 1
            task.last_status = "triggered"
            task.last_error = None
            if task.schedule_type == "once":
                task.enabled = False
                task.next_run_at = None
            else:
                task.next_run_at = compute_next_run(
                    task,
                    now,
                    default_timezone=self.default_timezone,
                )
            updated[task.task_id] = task

        merged: list[ScheduledTask] = []
        for task in tasks:
            merged.append(updated.get(task.task_id, task))
        self.store.save_all(merged)

    def defer(self, task_id: str | None, *, reason: str) -> None:
        """延后一次任务触发。

        参数:
            task_id: 任务标识。
            reason: 延后原因。

        返回:
            无返回值。
        """
        if not task_id:
            return
        task = self.store.get(str(task_id))
        if task is None:
            return
        task.last_status = f"deferred:{reason}"
        task.last_error = None
        task.updated_at = timestamp()
        self.store.upsert(task)

    def mark_running(self, task_id: str | None) -> None:
        """标记任务已进入执行中状态。"""
        if not task_id:
            return
        self.store.update_status(
            str(task_id),
            last_status="running",
            last_error=None,
        )

    def mark_finished(self, task_id: str | None, *, status: str, error: str | None = None) -> None:
        """标记任务执行完成状态。"""
        if not task_id:
            return
        self.store.update_status(
            str(task_id),
            last_status=status,
            last_error=error,
            last_finished_at=timestamp(),
        )
