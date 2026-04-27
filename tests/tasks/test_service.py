"""定时任务后台服务测试。"""

from datetime import datetime

import pytest

from elebot.bus.queue import MessageBus
from elebot.tasks.models import ScheduledTask
from elebot.tasks.service import TaskService
from elebot.tasks.store import TaskStore


def _task() -> ScheduledTask:
    return ScheduledTask(
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


@pytest.mark.asyncio
async def test_service_tick_publishes_due_task_and_disables_once(tmp_path, monkeypatch) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    store.upsert(_task())
    bus = MessageBus()
    service = TaskService(bus, store=store, poll_interval_seconds=10, default_timezone="Asia/Shanghai")

    class _FakeDatetime:
        @staticmethod
        def now():
            return datetime.fromisoformat("2026-04-26T14:00:01+08:00")

    monkeypatch.setattr("elebot.tasks.service.datetime", _FakeDatetime)
    await service.tick()

    msg = await bus.consume_inbound()
    assert msg.metadata["task_id"] == "task_1"
    stored = store.get("task_1")
    assert stored.enabled is False
    assert stored.next_run_at is None
    assert stored.last_status == "triggered"
    assert stored.run_count == 1


@pytest.mark.asyncio
async def test_service_tick_ignores_non_due_task(tmp_path, monkeypatch) -> None:
    task = _task()
    task.next_run_at = "2026-04-26T14:10:00+08:00"
    store = TaskStore(tmp_path / "tasks.json")
    store.upsert(task)
    bus = MessageBus()
    service = TaskService(bus, store=store, poll_interval_seconds=10, default_timezone="Asia/Shanghai")

    class _FakeDatetime:
        @staticmethod
        def now():
            return datetime.fromisoformat("2026-04-26T14:00:01+08:00")

    monkeypatch.setattr("elebot.tasks.service.datetime", _FakeDatetime)
    await service.tick()

    assert bus.inbound_size == 0


def test_service_list_by_session_remove_and_upsert(tmp_path) -> None:
    """TaskService 应作为统一任务 owner 暴露查询与写入接口。"""
    store = TaskStore(tmp_path / "tasks.json")
    task = _task()
    store.upsert(task)
    bus = MessageBus()
    service = TaskService(bus, store=store, default_timezone="Asia/Shanghai")

    assert service.list_by_session("cli:direct") == [task]
    assert service.get("task_1") == task

    task.content = "提醒提交日报"
    service.upsert(task)
    assert service.get("task_1").content == "提醒提交日报"

    assert service.remove("task_1") is True
    assert service.list_all() == []
