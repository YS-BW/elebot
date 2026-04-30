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


def test_cron_service_update_job_preserves_id_and_history(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    job = service.add_job(
        name="open-wechat",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="打开微信",
        channel="cli",
        chat_id="direct",
    )
    created_at_ms = job.created_at_ms
    job.state.last_run_at_ms = 123
    job.state.last_status = "ok"
    job.state.run_history = []

    updated = service.update_job(
        job.id,
        message="打开浏览器",
        name="打开浏览器",
        schedule=CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso(10)).timestamp() * 1000)),
        delete_after_run=True,
    )

    assert updated is not None
    assert updated.id == job.id
    assert updated.created_at_ms == created_at_ms
    assert updated.updated_at_ms >= created_at_ms
    assert updated.payload.message == "打开浏览器"
    assert updated.name == "打开浏览器"
    assert updated.schedule.kind == "at"
    assert updated.delete_after_run is True
    assert updated.enabled is True
    assert updated.state.last_run_at_ms == 123
    assert updated.state.last_status == "ok"


def test_cron_service_update_job_returns_none_when_missing(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")

    assert service.update_job("cron_missing", message="hi") is None


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
