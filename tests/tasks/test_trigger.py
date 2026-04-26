"""定时任务触发消息测试。"""

from elebot.tasks.models import ScheduledTask
from elebot.tasks.trigger import build_task_inbound_message


def test_build_task_inbound_message_preserves_session_and_metadata() -> None:
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

    msg = build_task_inbound_message(task)

    assert msg.channel == "system"
    assert msg.sender_id == "scheduler"
    assert msg.session_key == "cli:direct"
    assert msg.session_key_override == "cli:direct"
    assert msg.metadata["task_id"] == "task_1"
    assert msg.metadata["scheduled_trigger"] is True
    assert msg.metadata["task_run_count"] == 1
    assert "任务类型" in msg.content
