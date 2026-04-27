"""定时任务持久化。"""

from __future__ import annotations

import json
from pathlib import Path

from elebot.config.paths import get_tasks_store_path
from elebot.tasks.models import ScheduledTask
from elebot.utils.time import timestamp


class TaskStore:
    """管理任务文件的读写与查询。"""

    def __init__(self, path: Path | None = None):
        """初始化任务存储。

        参数:
            path: 自定义任务文件路径；为空时使用默认路径。

        返回:
            无返回值。
        """
        self.path = path or get_tasks_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> list[ScheduledTask]:
        """加载全部任务。

        返回:
            任务列表；文件不存在或为空时返回空列表。
        """
        if not self.path.exists():
            return []
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        payload = json.loads(raw)
        return [ScheduledTask.from_dict(item) for item in payload]

    def save_all(self, tasks: list[ScheduledTask]) -> None:
        """保存全部任务。

        参数:
            tasks: 待持久化任务列表。

        返回:
            无返回值。
        """
        serialized = [task.to_dict() for task in tasks]
        self.path.write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_all(self) -> list[ScheduledTask]:
        """列出全部任务。

        返回:
            当前任务列表。
        """
        return self.load_all()

    def get(self, task_id: str) -> ScheduledTask | None:
        """按 ID 获取任务。

        参数:
            task_id: 任务标识。

        返回:
            找到时返回任务对象，否则返回 ``None``。
        """
        for task in self.load_all():
            if task.task_id == task_id:
                return task
        return None

    def upsert(self, task: ScheduledTask) -> None:
        """插入或更新任务。

        参数:
            task: 目标任务。

        返回:
            无返回值。
        """
        tasks = self.load_all()
        for index, existing in enumerate(tasks):
            if existing.task_id == task.task_id:
                tasks[index] = task
                self.save_all(tasks)
                return
        tasks.append(task)
        self.save_all(tasks)

    def delete(self, task_id: str) -> bool:
        """删除指定任务。

        参数:
            task_id: 任务标识。

        返回:
            删除成功时返回 ``True``。
        """
        tasks = self.load_all()
        kept = [task for task in tasks if task.task_id != task_id]
        if len(kept) == len(tasks):
            return False
        self.save_all(kept)
        return True

    def update_status(
        self,
        task_id: str,
        *,
        last_status: str,
        last_error: str | None = None,
        last_finished_at: str | None = None,
        run_count: int | None = None,
    ) -> bool:
        """更新任务执行状态。

        参数:
            task_id: 任务标识。
            last_status: 最新状态。
            last_error: 最近错误信息。
            last_finished_at: 最近完成时间。
            run_count: 可选运行次数覆盖值。

        返回:
            找到并更新时返回 ``True``。
        """
        tasks = self.load_all()
        for task in tasks:
            if task.task_id != task_id:
                continue
            task.last_status = last_status
            task.last_error = last_error
            task.last_finished_at = last_finished_at
            if run_count is not None:
                task.run_count = run_count
            task.updated_at = timestamp()
            self.save_all(tasks)
            return True
        return False
