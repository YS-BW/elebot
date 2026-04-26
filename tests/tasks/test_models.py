"""定时任务模型测试。"""

from elebot.tasks.models import ScheduledTask


def test_scheduled_task_round_trip_dict() -> None:
    task = ScheduledTask(
        task_id="task_1",
        session_key="cli:direct",
        content="提醒总结会议",
        schedule_type="once",
        run_at="2026-04-26T14:00:00+08:00",
        interval_seconds=None,
        daily_time=None,
        timezone="Asia/Shanghai",
        enabled=True,
        created_at="2026-04-26T10:00:00+08:00",
        updated_at="2026-04-26T10:00:00+08:00",
        last_run_at=None,
        next_run_at="2026-04-26T14:00:00+08:00",
        source="agent",
    )

    restored = ScheduledTask.from_dict(task.to_dict())

    assert restored == task
    assert restored.run_count == 0
