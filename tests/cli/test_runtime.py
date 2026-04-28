"""runtime 入口的最小行为测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from elebot.config.schema import Config
from elebot.runtime.app import ElebotRuntime


@pytest.mark.asyncio
async def test_runtime_start_wait_and_close_manage_loop_lifecycle() -> None:
    """runtime 应统一管理后台主循环的启动和关闭。"""
    config = Config()
    agent_loop = MagicMock()
    agent_loop.run = AsyncMock(return_value=None)
    agent_loop.close_mcp = AsyncMock(return_value=None)

    runtime = ElebotRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        bus_factory=lambda: object(),
        agent_loop_factory=lambda **_kwargs: agent_loop,
    )

    await runtime.start()
    await runtime.wait()
    await runtime.close()

    agent_loop.run.assert_awaited_once()
    agent_loop.stop.assert_called_once()
    agent_loop.close_mcp.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_run_once_delegates_to_agent_loop() -> None:
    """单次调用入口应直接复用 AgentLoop.process_direct。"""
    config = Config()
    agent_loop = MagicMock()
    agent_loop.process_direct = AsyncMock(return_value="ok")

    runtime = ElebotRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        bus_factory=lambda: object(),
        agent_loop_factory=lambda **_kwargs: agent_loop,
    )

    result = await runtime.run_once("hello", session_id="cli:test")

    assert result == "ok"
    agent_loop.process_direct.assert_awaited_once_with(
        "hello",
        "cli:test",
        on_progress=None,
        on_stream=None,
        on_stream_end=None,
    )


@pytest.mark.asyncio
async def test_runtime_run_interactive_delegates_without_restarting_loop(monkeypatch) -> None:
    """交互入口通过 runtime 调用时，不应再由 CLI 自己托管主循环生命周期。"""
    config = Config()
    agent_loop = MagicMock()
    agent_loop.run = AsyncMock(return_value=None)
    agent_loop.close_mcp = AsyncMock(return_value=None)
    bus = object()
    captured: dict[str, object] = {}

    async def _fake_run_interactive_loop(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("elebot.runtime.app.run_interactive_loop", _fake_run_interactive_loop)

    runtime = ElebotRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        bus_factory=lambda: bus,
        agent_loop_factory=lambda **_kwargs: agent_loop,
    )

    await runtime.run_interactive(session_id="cli:test", markdown=True)

    assert captured["agent_loop"] is agent_loop
    assert captured["bus"] is bus
    assert captured["session_id"] == "cli:test"
    assert captured["markdown"] is True
    assert captured["manage_agent_loop"] is False
    assert captured["interrupt_session"] == runtime.interrupt_session
    agent_loop.run.assert_awaited_once()
    agent_loop.stop.assert_called_once()
    agent_loop.close_mcp.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_control_apis_delegate_to_owner_objects() -> None:
    """runtime 新增控制面应只委托给 owner，不自行承载业务逻辑。"""
    config = Config()
    agent_loop = MagicMock()
    agent_loop.interrupt_session = MagicMock(
        return_value=MagicMock(
            session_id="cli:test",
            reason="user_interrupt",
            accepted=True,
            cancelled_tasks=1,
            already_interrupting=False,
        )
    )
    agent_loop.reset_session = MagicMock()
    agent_loop.build_status_snapshot = AsyncMock(
        return_value=MagicMock(
            version="0.1.5",
            model="test-model",
            start_time=12.0,
            last_usage={"prompt_tokens": 3, "completion_tokens": 5},
            context_window_tokens=1024,
            session_msg_count=4,
            context_tokens_estimate=256,
            search_usage_text="search",
        )
    )
    agent_loop.trigger_dream_background = MagicMock()
    agent_loop.task_service = MagicMock()
    agent_loop.task_service.list_all.return_value = ["all-task"]
    agent_loop.task_service.list_by_session.return_value = ["session-task"]
    agent_loop.task_service.remove.return_value = True
    agent_loop.memory_store = MagicMock()
    agent_loop.memory_store.show_dream_version.return_value = MagicMock(
        status="ok",
        requested_sha=None,
        commit=MagicMock(sha="abcd1234", timestamp="2026-04-27 12:00", message="dream: latest"),
        diff="diff --git a/SOUL.md b/SOUL.md",
        changed_files=["SOUL.md"],
    )
    agent_loop.memory_store.restore_dream_version.return_value = MagicMock(
        status="ok",
        requested_sha="abcd1234",
        new_sha="eeee9999",
        changed_files=["SOUL.md"],
        message=None,
    )

    runtime = ElebotRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        bus_factory=lambda: object(),
        agent_loop_factory=lambda **_kwargs: agent_loop,
    )

    interrupt = runtime.interrupt_session("cli:test")
    runtime.reset_session("cli:test")
    snapshot = await runtime.get_status_snapshot("cli:test")
    runtime.trigger_dream("cli", "direct")
    assert runtime.list_tasks() == ["all-task"]
    assert runtime.list_tasks("cli:test") == ["session-task"]
    assert runtime.remove_task("task_1") is True
    dream_log = runtime.get_dream_log()
    dream_restore = runtime.restore_dream_version("abcd1234")

    agent_loop.interrupt_session.assert_called_once_with("cli:test", "user_interrupt")
    agent_loop.reset_session.assert_called_once_with("cli:test")
    agent_loop.build_status_snapshot.assert_awaited_once_with("cli:test")
    agent_loop.trigger_dream_background.assert_called_once_with("cli", "direct")
    agent_loop.task_service.list_all.assert_called_once_with()
    agent_loop.task_service.list_by_session.assert_called_once_with("cli:test")
    agent_loop.task_service.remove.assert_called_once_with("task_1")
    agent_loop.memory_store.show_dream_version.assert_called_once_with(None)
    agent_loop.memory_store.restore_dream_version.assert_called_once_with("abcd1234")
    assert snapshot.model == "test-model"
    assert interrupt.cancelled_tasks == 1
    assert dream_log.sha == "abcd1234"
    assert dream_restore.new_sha == "eeee9999"


def test_cli_entry_import_does_not_trigger_runtime_cycle() -> None:
    """CLI 入口导入不应因为 runtime 顶层导出触发循环依赖。

    参数:
        无。

    返回:
        无返回值。
    """
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", "import elebot.__main__"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
