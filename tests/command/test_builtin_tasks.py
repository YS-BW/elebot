from __future__ import annotations

from types import SimpleNamespace

import pytest

from elebot.bus.events import InboundMessage
from elebot.command.builtin import build_help_text
from elebot.command.handlers.tasks import cmd_task_manage
from elebot.command.router import CommandContext
from elebot.tasks.models import ScheduledTask


def _make_ctx(raw: str = "/task") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, loop=SimpleNamespace())


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


@pytest.mark.asyncio
async def test_task_command_lists_tasks(monkeypatch) -> None:
    class _FakeTaskService:
        def list_by_session(self, session_key: str):
            return [_task()]

    ctx = _make_ctx()
    ctx.loop = SimpleNamespace(task_service=_FakeTaskService())
    out = await cmd_task_manage(ctx)
    assert "## Tasks" in out.content
    assert "`task_1`" in out.content
    assert "当前会话定时任务" in out.content


@pytest.mark.asyncio
async def test_task_command_remove(monkeypatch) -> None:
    class _FakeTaskService:
        def remove(self, task_id: str) -> bool:
            return task_id == "task_1"

    ctx = _make_ctx("/task remove task_1")
    ctx.args = "remove task_1"
    ctx.loop = SimpleNamespace(task_service=_FakeTaskService())
    out = await cmd_task_manage(ctx)
    assert "已删除任务" in out.content


def test_help_text_contains_task_commands() -> None:
    help_text = build_help_text()
    assert "/task" in help_text
