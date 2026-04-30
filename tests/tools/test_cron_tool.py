from __future__ import annotations

from elebot.agent.tools.cron import (
    CronCreateTool,
    CronDeleteTool,
    CronListTool,
    CronUpdateTool,
)
from elebot.cron import CronService


def _make_tools(tmp_path):
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    create = CronCreateTool(service, default_timezone="Asia/Shanghai")
    create.set_context("cli", "direct")
    return service, create, CronListTool(service, default_timezone="Asia/Shanghai"), CronDeleteTool(
        service,
        default_timezone="Asia/Shanghai",
    ), CronUpdateTool(service, default_timezone="Asia/Shanghai")


async def test_cron_tools_create_list_delete(tmp_path) -> None:
    service, create, listing, delete, _update = _make_tools(tmp_path)

    created = await create.execute(
        instruction="打开浏览器搜索小红书",
        every_seconds=60,
    )

    assert "已创建 cron 任务" in created

    listed = await listing.execute()
    assert "当前有 1 个 cron 任务" in listed
    assert "打开浏览器搜索小红书" in listed

    job_id = service.list_jobs(include_disabled=True)[0].id
    removed = await delete.execute(job_id=job_id)
    assert removed == f"已删除 cron 任务：`{job_id}`"


async def test_cron_create_tool_naive_at_uses_default_timezone(tmp_path) -> None:
    _service, create, listing, _delete, _update = _make_tools(tmp_path)

    result = await create.execute(
        instruction="明天早上提醒我",
        at="2099-04-29T09:30:00",
    )

    assert "已创建 cron 任务" in result
    listed = await listing.execute()
    assert "(Asia/Shanghai)" in listed


async def test_cron_create_tool_requires_exactly_one_time_field(tmp_path) -> None:
    _service, create, _listing, _delete, _update = _make_tools(tmp_path)

    missing = await create.execute(instruction="打开微信")
    multiple = await create.execute(
        instruction="打开微信",
        after_seconds=60,
        every_seconds=60,
    )

    assert missing == "Error: exactly one of after_seconds, at, or every_seconds is required"
    assert multiple == "Error: exactly one of after_seconds, at, or every_seconds is required"


async def test_cron_delete_tool_requires_job_id(tmp_path) -> None:
    _service, _create, _listing, delete, _update = _make_tools(tmp_path)

    result = await delete.execute()

    assert result == "Error: job_id is required"


async def test_cron_delete_tool_reports_missing_job(tmp_path) -> None:
    _service, _create, _listing, delete, _update = _make_tools(tmp_path)

    result = await delete.execute(job_id="cron_missing")

    assert result == "Error: cron 任务 `cron_missing` 不存在"


async def test_cron_update_tool_rewrites_instruction_only(tmp_path) -> None:
    service, create, listing, _delete, update = _make_tools(tmp_path)
    await create.execute(instruction="打开微信", every_seconds=60)
    job_id = service.list_jobs(include_disabled=True)[0].id

    result = await update.execute(
        job_id=job_id,
        instruction="打开浏览器",
    )

    assert result == f"已更新 cron 任务：`{job_id}`（打开浏览器）"
    listed = await listing.execute()
    assert "打开浏览器" in listed
    assert "打开微信" not in listed


async def test_cron_update_tool_replaces_schedule(tmp_path) -> None:
    service, create, _listing, _delete, update = _make_tools(tmp_path)
    await create.execute(instruction="打开微信", every_seconds=60)
    job_id = service.list_jobs(include_disabled=True)[0].id

    result = await update.execute(
        job_id=job_id,
        at="2099-04-29T09:30:00",
    )

    assert result == f"已更新 cron 任务：`{job_id}`（打开微信）"
    job = service.get_job(job_id)
    assert job is not None
    assert job.schedule.kind == "at"
    assert job.delete_after_run is True


async def test_cron_update_tool_allows_instruction_and_schedule_together(tmp_path) -> None:
    service, create, _listing, _delete, update = _make_tools(tmp_path)
    await create.execute(instruction="打开微信", every_seconds=60)
    job_id = service.list_jobs(include_disabled=True)[0].id

    result = await update.execute(
        job_id=job_id,
        instruction="提醒我去看书",
        after_seconds=120,
    )

    assert result == f"已更新 cron 任务：`{job_id}`（提醒我去看书）"
    job = service.get_job(job_id)
    assert job is not None
    assert job.payload.message == "提醒我去看书"
    assert job.schedule.kind == "at"
    assert job.delete_after_run is True


async def test_cron_update_tool_requires_change(tmp_path) -> None:
    _service, _create, _listing, _delete, update = _make_tools(tmp_path)

    result = await update.execute(job_id="cron_1")

    assert result == "Error: at least one of instruction, after_seconds, at, or every_seconds is required"


async def test_cron_update_tool_rejects_multiple_time_fields(tmp_path) -> None:
    _service, _create, _listing, _delete, update = _make_tools(tmp_path)

    result = await update.execute(
        job_id="cron_1",
        after_seconds=60,
        every_seconds=60,
    )

    assert result == "Error: exactly one of after_seconds, at, or every_seconds is required"
