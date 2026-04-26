"""定时任务工具测试。"""

import pytest

from elebot.agent.tools.task_tools import (
    CreateTaskTool,
    ListTasksTool,
    ProposeTaskTool,
    RemoveTaskTool,
    UpdateTaskTool,
)
from elebot.session.manager import SessionManager
from elebot.tasks.store import TaskStore


@pytest.mark.asyncio
async def test_create_task_validates_schedule_shape(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    sessions = SessionManager(tmp_path / "workspace")
    tool = CreateTaskTool(store=store, default_timezone="Asia/Shanghai", session_manager=sessions)

    err = await tool.execute(
        content="提醒总结会议",
        schedule_type="once",
        session_key="cli:direct",
    )
    assert "必须先提出任务建议" in err

    propose = ProposeTaskTool(store=store, default_timezone="Asia/Shanghai", session_manager=sessions)
    bad_daily = await propose.execute(
        content="提醒总结会议",
        schedule_type="daily",
        daily_time="25:99",
        session_key="cli:direct",
    )
    assert "daily_time" in bad_daily

    past_once = await propose.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2020-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    assert "run_at 不能早于当前时间" in past_once

    preview = await propose.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2099-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    assert "如果确认" in preview

    ok = await tool.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2099-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    assert "已创建任务" in ok
    assert len(store.list_all()) == 1


@pytest.mark.asyncio
async def test_list_tasks_can_filter_by_session(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    sessions = SessionManager(tmp_path / "workspace")
    propose = ProposeTaskTool(store=store, default_timezone="Asia/Shanghai", session_manager=sessions)
    create = CreateTaskTool(store=store, default_timezone="Asia/Shanghai", session_manager=sessions)
    await propose.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2099-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    await create.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2099-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    await propose.execute(
        content="提醒提交日报",
        schedule_type="once",
        run_at="2099-04-26T15:00:00+08:00",
        session_key="cli:work",
    )
    await create.execute(
        content="提醒提交日报",
        schedule_type="once",
        run_at="2099-04-26T15:00:00+08:00",
        session_key="cli:work",
    )

    tool = ListTasksTool(store=store)
    result = await tool.execute(session_key="cli:direct")
    assert "cli:direct" in result
    assert "cli:work" not in result


@pytest.mark.asyncio
async def test_remove_task_deletes_existing_task(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    sessions = SessionManager(tmp_path / "workspace")
    propose = ProposeTaskTool(store=store, default_timezone="Asia/Shanghai", session_manager=sessions)
    create = CreateTaskTool(store=store, default_timezone="Asia/Shanghai", session_manager=sessions)
    await propose.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2099-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    await create.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2099-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    task_id = store.list_all()[0].task_id

    tool = RemoveTaskTool(store=store)
    result = await tool.execute(task_id=task_id)
    assert "已删除任务" in result
    assert store.list_all() == []


@pytest.mark.asyncio
async def test_update_task_changes_schedule_and_content(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    sessions = SessionManager(tmp_path / "workspace")
    propose = ProposeTaskTool(store=store, default_timezone="Asia/Shanghai", session_manager=sessions)
    create = CreateTaskTool(store=store, default_timezone="Asia/Shanghai", session_manager=sessions)
    await propose.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2099-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    await create.execute(
        content="提醒总结会议",
        schedule_type="once",
        run_at="2099-04-26T14:00:00+08:00",
        session_key="cli:direct",
    )
    task_id = store.list_all()[0].task_id

    tool = UpdateTaskTool(store=store, default_timezone="Asia/Shanghai")
    result = await tool.execute(
        task_id=task_id,
        content="提醒提交周报",
        run_at="2099-04-26T15:00:00+08:00",
    )
    assert "已更新任务" in result
    updated = store.get(task_id)
    assert updated.content == "提醒提交周报"
    assert updated.run_at == "2099-04-26T15:00:00+08:00"
