from __future__ import annotations

from elebot.agent.tools.cron import CronTool
from elebot.cron import CronService


async def test_cron_tool_add_list_remove(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    tool = CronTool(service, default_timezone="Asia/Shanghai")
    tool.set_context("cli", "direct")

    created = await tool.execute(
        action="add",
        instruction="打开浏览器搜索小红书",
        every_seconds=60,
    )

    assert "已创建 cron 任务" in created

    listed = await tool.execute(action="list")
    assert "当前有 1 个 cron 任务" in listed
    assert "打开浏览器搜索小红书" in listed

    job_id = service.list_jobs(include_disabled=True)[0].id
    removed = await tool.execute(action="remove", job_id=job_id)
    assert removed == f"已删除 cron 任务：`{job_id}`"


async def test_cron_tool_rejects_invalid_timezone_usage(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    tool = CronTool(service, default_timezone="Asia/Shanghai")
    tool.set_context("cli", "direct")

    result = await tool.execute(
        action="add",
        instruction="定时任务",
        every_seconds=60,
        tz="Asia/Shanghai",
    )

    assert result == "Error: tz can only be used with cron_expr"


async def test_cron_tool_naive_at_uses_default_timezone(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    tool = CronTool(service, default_timezone="Asia/Shanghai")
    tool.set_context("cli", "direct")

    result = await tool.execute(
        action="add",
        instruction="明天早上提醒我",
        at="2099-04-29T09:30:00",
    )

    assert "已创建 cron 任务" in result
    listed = await tool.execute(action="list")
    assert "(Asia/Shanghai)" in listed


async def test_cron_tool_remove_requires_job_id(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    tool = CronTool(service, default_timezone="Asia/Shanghai")

    result = await tool.execute(action="remove")

    assert result == "Error: job_id is required for remove"


async def test_cron_tool_accepts_prompt_alias_for_message(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    tool = CronTool(service, default_timezone="Asia/Shanghai")
    tool.set_context("cli", "direct")

    result = await tool.execute(
        action="add",
        prompt="打开微信",
        every_seconds=60,
    )

    assert "已创建 cron 任务" in result
    listed = await tool.execute(action="list")
    assert "打开微信" in listed


async def test_cron_tool_accepts_command_alias_for_message(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    tool = CronTool(service, default_timezone="Asia/Shanghai")
    tool.set_context("cli", "direct")

    result = await tool.execute(
        action="add",
        command="打开微信",
        every_seconds=60,
    )

    assert "已创建 cron 任务" in result
    listed = await tool.execute(action="list")
    assert "打开微信" in listed


async def test_cron_tool_falls_back_to_name_when_instruction_missing(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    tool = CronTool(service, default_timezone="Asia/Shanghai")
    tool.set_context("cli", "direct")

    result = await tool.execute(
        action="add",
        name="打开微信",
        every_seconds=60,
    )

    assert "已创建 cron 任务" in result
    listed = await tool.execute(action="list")
    assert "打开微信" in listed


async def test_cron_tool_accepts_nested_job_payload(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    tool = CronTool(service, default_timezone="Asia/Shanghai")
    tool.set_context("cli", "direct")

    result = await tool.execute(
        action="add",
        job={
            "name": "打开微信",
            "at": "2099-04-29T09:30:00",
            "payload": {"kind": "agentTurn", "instruction": "请打开微信"},
        },
    )

    assert "已创建 cron 任务" in result
    listed = await tool.execute(action="list")
    assert "打开微信" in listed
    assert "请打开微信" in listed
