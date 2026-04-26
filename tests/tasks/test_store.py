"""定时任务存储测试。"""

from pathlib import Path

from elebot.tasks.models import ScheduledTask
from elebot.tasks.store import TaskStore


def _task(task_id: str = "task_1") -> ScheduledTask:
    return ScheduledTask(
        task_id=task_id,
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


def test_store_upsert_get_list_delete(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.json")

    store.upsert(_task())
    assert len(store.list_all()) == 1
    assert store.get("task_1") is not None

    updated = _task()
    updated.content = "提醒提交周报"
    store.upsert(updated)
    assert store.get("task_1").content == "提醒提交周报"

    assert store.delete("task_1") is True
    assert store.list_all() == []


def test_store_load_all_returns_empty_for_missing_file(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "missing.json")
    assert store.load_all() == []


def test_store_update_status_updates_runtime_fields(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    task = _task()
    store.upsert(task)

    ok = store.update_status(
        "task_1",
        last_status="running",
        last_error=None,
        last_finished_at="2026-04-26T14:00:00+08:00",
        run_count=2,
    )

    assert ok is True
    stored = store.get("task_1")
    assert stored.last_status == "running"
    assert stored.run_count == 2
