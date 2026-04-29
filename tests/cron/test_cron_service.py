from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from elebot.cron import CronSchedule, CronService


def _future_iso(minutes: int = 5) -> str:
    return (datetime.now().astimezone() + timedelta(minutes=minutes)).isoformat()


def test_cron_service_add_list_remove(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")

    job = service.add_job(
        name="check-news",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="检查今天的 AI 新闻",
        channel="cli",
        chat_id="direct",
    )

    jobs = service.list_jobs()
    assert [item.id for item in jobs] == [job.id]
    assert jobs[0].payload.message == "检查今天的 AI 新闻"

    assert service.remove_job(job.id) is True
    assert service.list_jobs() == []


def test_cron_service_reuses_recent_duplicate_job(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    schedule = CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso()).timestamp() * 1000))

    first = service.add_job(
        name="open-wechat",
        schedule=schedule,
        message="打开微信",
        channel="cli",
        chat_id="direct",
        delete_after_run=True,
    )
    second = service.add_job(
        name="open-wechat",
        schedule=schedule,
        message="打开微信",
        channel="cli",
        chat_id="direct",
        delete_after_run=True,
    )

    assert second.id == first.id
    assert len(service.list_jobs(include_disabled=True)) == 1


def test_cron_service_rejects_invalid_schedule_inputs(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")

    with pytest.raises(ValueError, match="unknown timezone"):
        service.add_job(
            name="bad-tz",
            schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="Mars/Phobos"),
            message="hello",
            channel="cli",
            chat_id="direct",
        )

    with pytest.raises(ValueError, match="invalid cron expression"):
        service.add_job(
            name="bad-cron",
            schedule=CronSchedule(kind="cron", expr="not-a-cron", tz="Asia/Shanghai"),
            message="hello",
            channel="cli",
            chat_id="direct",
        )

    with pytest.raises(ValueError, match="at must be in the future"):
        service.add_job(
            name="past",
            schedule=CronSchedule(kind="at", at_ms=1),
            message="hello",
            channel="cli",
            chat_id="direct",
        )


@pytest.mark.asyncio
async def test_cron_service_runs_due_job_and_records_state(tmp_path) -> None:
    calls: list[str] = []

    async def _on_job(job) -> None:
        calls.append(job.id)

    service = CronService(
        tmp_path / "cron" / "jobs.json",
        on_job=_on_job,
        default_timezone="Asia/Shanghai",
    )
    job = service.add_job(
        name="once",
        schedule=CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso()).timestamp() * 1000)),
        message="一分钟后提醒我",
        channel="cli",
        chat_id="direct",
        delete_after_run=True,
    )

    service.start()
    stored = service.get_job(job.id)
    assert stored is not None
    stored.state.next_run_at_ms = 0

    await service.run_due_jobs()
    await service.stop()

    assert calls == [job.id]
    assert service.get_job(job.id) is None


@pytest.mark.asyncio
async def test_cron_service_disables_one_shot_job_when_not_delete_after_run(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    job = service.add_job(
        name="once-keep",
        schedule=CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso()).timestamp() * 1000)),
        message="保留一次性任务记录",
        channel="cli",
        chat_id="direct",
        delete_after_run=False,
    )

    service.start()
    stored = service.get_job(job.id)
    assert stored is not None
    stored.state.next_run_at_ms = 0

    await service.run_due_jobs()
    await service.stop()

    hidden = service.list_jobs()
    all_jobs = service.list_jobs(include_disabled=True)
    assert hidden == []
    assert len(all_jobs) == 1
    assert all_jobs[0].enabled is False
    assert all_jobs[0].state.last_status == "ok"
    assert len(all_jobs[0].state.run_history) == 1
