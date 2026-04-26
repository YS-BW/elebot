"""定时任务调度计算测试。"""

from datetime import datetime

from elebot.tasks.models import ScheduledTask
from elebot.tasks.scheduler import collect_due_tasks, compute_next_run, is_due


def _task(schedule_type: str, **overrides) -> ScheduledTask:
    payload = dict(
        task_id="task_1",
        session_key="cli:direct",
        content="提醒总结会议",
        schedule_type=schedule_type,
        run_at=None,
        interval_seconds=None,
        daily_time=None,
        timezone="Asia/Shanghai",
        enabled=True,
        created_at="2026-04-26T10:00:00+08:00",
        updated_at="2026-04-26T10:00:00+08:00",
        last_run_at=None,
        next_run_at=None,
        source="agent",
    )
    payload.update(overrides)
    return ScheduledTask(**payload)


def test_once_task_due_and_next_run_none() -> None:
    now = datetime.fromisoformat("2026-04-26T14:00:01+08:00")
    task = _task(
        "once",
        run_at="2026-04-26T14:00:00+08:00",
        next_run_at="2026-04-26T14:00:00+08:00",
    )
    assert is_due(task, now) is True
    assert compute_next_run(task, now) is None


def test_interval_task_computes_next_run() -> None:
    now = datetime.fromisoformat("2026-04-26T14:00:05+08:00")
    task = _task(
        "interval",
        interval_seconds=60,
        next_run_at="2026-04-26T14:00:00+08:00",
    )
    assert compute_next_run(task, now) == "2026-04-26T14:01:00+08:00"


def test_daily_task_computes_next_run() -> None:
    now = datetime.fromisoformat("2026-04-26T14:00:00+08:00")
    task = _task("daily", daily_time="14:30")
    assert compute_next_run(task, now) == "2026-04-26T14:30:00+08:00"


def test_collect_due_tasks_filters_non_due() -> None:
    now = datetime.fromisoformat("2026-04-26T14:00:00+08:00")
    due = _task("once", next_run_at="2026-04-26T13:59:00+08:00")
    not_due = _task("once", task_id="task_2", next_run_at="2026-04-26T14:05:00+08:00")
    tasks = collect_due_tasks([due, not_due], now)
    assert [task.task_id for task in tasks] == ["task_1"]
