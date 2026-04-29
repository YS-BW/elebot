"""Cron 调度 owner。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from croniter import croniter
from loguru import logger

from elebot.cron.types import CronJob, CronJobState, CronPayload, CronRunRecord, CronSchedule


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)


class CronService:
    """负责 cron job 的持久化、调度与执行。"""

    _MAX_RUN_HISTORY = 20
    _DUPLICATE_WINDOW_MS = 60_000

    def __init__(
        self,
        store_path: Path,
        *,
        on_job: Callable[[CronJob], Awaitable[None]] | None = None,
        default_timezone: str = "Asia/Shanghai",
        max_sleep_ms: int = 300_000,
    ) -> None:
        """初始化 cron 服务。"""
        self.store_path = store_path
        self.on_job = on_job
        self.default_timezone = default_timezone
        self.max_sleep_ms = max_sleep_ms
        self._jobs: list[CronJob] = []
        self._running = False
        self._timer_task: asyncio.Task[None] | None = None

    def _load_jobs(self) -> list[CronJob]:
        """从磁盘读取当前 job 列表。"""
        if not self.store_path.exists():
            return []
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode cron store {}: {}", self.store_path, exc)
            return []
        return [CronJob.from_dict(item) for item in payload.get("jobs", [])]

    def _save_jobs(self) -> None:
        """把当前 job 列表写回磁盘。"""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "jobs": [job.to_dict() for job in self._jobs],
        }
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _validate_timezone(tz_name: str) -> None:
        """校验 IANA 时区是否合法。"""
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(tz_name)
        except Exception as exc:
            raise ValueError(f"unknown timezone '{tz_name}'") from exc

    def _compute_next_run(
        self,
        schedule: CronSchedule,
        now_ms: int,
        *,
        allow_past_at: bool = False,
    ) -> int | None:
        """计算下一次触发时间。"""
        if schedule.kind == "at":
            if schedule.at_ms is None:
                return None
            if allow_past_at:
                return schedule.at_ms
            return schedule.at_ms if schedule.at_ms > now_ms else None

        if schedule.kind == "every":
            if schedule.every_ms is None or schedule.every_ms <= 0:
                return None
            return now_ms + schedule.every_ms

        if schedule.kind == "cron":
            if not schedule.expr:
                return None
            from zoneinfo import ZoneInfo

            tz_name = schedule.tz or self.default_timezone
            tz = ZoneInfo(tz_name)
            base_dt = datetime.fromtimestamp(now_ms / 1000, tz=tz)
            return int(croniter(schedule.expr, base_dt).get_next(datetime).timestamp() * 1000)

        return None

    def _validate_schedule(self, schedule: CronSchedule, *, now_ms: int | None = None) -> None:
        """校验调度参数，避免创建永远不会执行的 job。"""
        current_ms = _now_ms() if now_ms is None else now_ms
        if schedule.tz and schedule.kind != "cron":
            raise ValueError("tz can only be used with cron_expr")
        if schedule.kind == "at":
            if schedule.at_ms is None:
                raise ValueError("at schedule requires at_ms")
            if schedule.at_ms <= current_ms:
                raise ValueError("at must be in the future")
            return
        if schedule.kind == "every":
            if schedule.every_ms is None or schedule.every_ms <= 0:
                raise ValueError("every_seconds must be > 0")
            return
        if schedule.kind == "cron":
            if not schedule.expr:
                raise ValueError("cron_expr is required")
            if schedule.tz:
                self._validate_timezone(schedule.tz)
            try:
                next_run = self._compute_next_run(schedule, current_ms)
            except Exception as exc:
                raise ValueError(f"invalid cron expression '{schedule.expr}'") from exc
            if next_run is None:
                raise ValueError(f"invalid cron expression '{schedule.expr}'")
            return
        raise ValueError(f"unsupported schedule kind '{schedule.kind}'")

    def _recompute_next_runs(self) -> None:
        """在启动或更新后统一刷新下一次触发时间。"""
        now_ms = _now_ms()
        for job in self._jobs:
            if not job.enabled:
                job.state.next_run_at_ms = None
                continue
            allow_past_at = job.schedule.kind == "at" and job.state.last_run_at_ms is None
            if allow_past_at and job.state.next_run_at_ms is not None:
                continue
            job.state.next_run_at_ms = self._compute_next_run(
                job.schedule,
                now_ms,
                allow_past_at=allow_past_at,
            )

    def _next_wake_ms(self) -> int | None:
        """返回最早的一次待触发时间。"""
        candidates = [
            job.state.next_run_at_ms
            for job in self._jobs
            if job.enabled and job.state.next_run_at_ms is not None
        ]
        return min(candidates) if candidates else None

    def _arm_timer(self) -> None:
        """重新挂下一次定时检查。"""
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None
        if not self._running:
            return

        next_wake_ms = self._next_wake_ms()
        if next_wake_ms is None:
            delay_ms = self.max_sleep_ms
        else:
            delay_ms = min(self.max_sleep_ms, max(0, next_wake_ms - _now_ms()))

        async def _tick() -> None:
            await asyncio.sleep(delay_ms / 1000)
            if self._running:
                await self.run_due_jobs()

        self._timer_task = asyncio.create_task(_tick())

    def start(self) -> None:
        """启动后台调度。"""
        if self._running:
            return
        self._running = True
        self._jobs = self._load_jobs()
        self._recompute_next_runs()
        self._save_jobs()
        self._arm_timer()
        logger.info("Cron service started with {} job(s)", len(self._jobs))

    async def stop(self) -> None:
        """停止后台调度。"""
        self._running = False
        task = self._timer_task
        self._timer_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def run_due_jobs(self) -> None:
        """执行当前已经到点的 job。"""
        now_ms = _now_ms()
        due_jobs = [
            job for job in self._jobs
            if job.enabled and job.state.next_run_at_ms is not None and job.state.next_run_at_ms <= now_ms
        ]
        for job in due_jobs:
            await self._execute_job(job)
        self._save_jobs()
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        """执行单个 job 并更新状态。"""
        start_ms = _now_ms()
        logger.info("Cron: executing job '{}' ({})", job.name, job.id)
        status = "ok"
        error: str | None = None
        try:
            if self.on_job is not None:
                await self.on_job(job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status = "error"
            error = str(exc)
            logger.exception("Cron: job '{}' failed", job.id)

        end_ms = _now_ms()
        job.state.last_run_at_ms = start_ms
        job.state.last_status = status
        job.state.last_error = error
        job.updated_at_ms = end_ms
        job.state.run_history.append(
            CronRunRecord(
                run_at_ms=start_ms,
                status=status,
                duration_ms=end_ms - start_ms,
                error=error,
            )
        )
        job.state.run_history = job.state.run_history[-self._MAX_RUN_HISTORY :]

        if job.schedule.kind == "at":
            if job.delete_after_run:
                self._jobs = [item for item in self._jobs if item.id != job.id]
                return
            job.enabled = False
            job.state.next_run_at_ms = None
            return

        job.state.next_run_at_ms = self._compute_next_run(job.schedule, _now_ms())

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """返回当前 job 列表。"""
        if not self._running and not self._jobs:
            self._jobs = self._load_jobs()
            self._recompute_next_runs()
        jobs = self._jobs if include_disabled else [job for job in self._jobs if job.enabled]
        return sorted(jobs, key=lambda item: item.state.next_run_at_ms or float("inf"))

    def get_job(self, job_id: str) -> CronJob | None:
        """按 ID 获取 job。"""
        for job in self.list_jobs(include_disabled=True):
            if job.id == job_id:
                return job
        return None

    def add_job(
        self,
        *,
        name: str,
        schedule: CronSchedule,
        message: str,
        channel: str,
        chat_id: str,
        delete_after_run: bool = False,
    ) -> CronJob:
        """新增一个 cron job。"""
        now_ms = _now_ms()
        self._validate_schedule(schedule, now_ms=now_ms)
        self._jobs = self.list_jobs(include_disabled=True)
        for existing in self._jobs:
            if not existing.enabled:
                continue
            if existing.schedule.to_dict() != schedule.to_dict():
                continue
            if existing.payload.message != message:
                continue
            if existing.payload.channel != channel or existing.payload.chat_id != chat_id:
                continue
            if existing.delete_after_run != delete_after_run:
                continue
            if abs(existing.created_at_ms - now_ms) > self._DUPLICATE_WINDOW_MS:
                continue
            logger.info("Cron: reuse duplicate job '{}' ({})", existing.name, existing.id)
            return existing

        job = CronJob(
            id=f"cron_{uuid.uuid4().hex[:12]}",
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(message=message, channel=channel, chat_id=chat_id),
            state=CronJobState(
                next_run_at_ms=self._compute_next_run(schedule, now_ms),
            ),
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            delete_after_run=delete_after_run,
        )
        self._jobs.append(job)
        self._save_jobs()
        self._arm_timer()
        logger.info("Cron: added job '{}' ({})", job.name, job.id)
        return job

    def remove_job(self, job_id: str) -> bool:
        """删除一个 cron job。"""
        if not self._running and not self._jobs:
            self._jobs = self._load_jobs()
        before = len(self._jobs)
        self._jobs = [job for job in self._jobs if job.id != job_id]
        changed = len(self._jobs) != before
        if changed:
            self._save_jobs()
            self._arm_timer()
            logger.info("Cron: removed job {}", job_id)
        return changed
