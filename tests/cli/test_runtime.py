"""runtime 入口的最小行为测试。"""

from __future__ import annotations

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
    agent_loop.run.assert_awaited_once()
    agent_loop.stop.assert_called_once()
    agent_loop.close_mcp.assert_awaited_once()
