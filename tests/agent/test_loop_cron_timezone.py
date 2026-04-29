from __future__ import annotations

from unittest.mock import MagicMock

from elebot.agent.loop import AgentLoop
from elebot.agent.tools.cron import CronTool
from elebot.bus.queue import MessageBus


def test_agent_loop_registers_cron_tool_with_default_timezone(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        timezone="Asia/Shanghai",
    )

    tool = loop.tools.get("cron")
    assert isinstance(tool, CronTool)
    assert tool._default_timezone == "Asia/Shanghai"
    assert loop.cron_service.default_timezone == "Asia/Shanghai"
