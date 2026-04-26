"""定时任务调度计算。"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from elebot.tasks.models import ScheduledTask


def _resolve_timezone(task: ScheduledTask, default_timezone: str | None = None):
    """解析任务时区对象。

    参数:
        task: 目标任务。
        default_timezone: 默认时区名称。

    返回:
        时区对象；解析失败时返回本地时区。
    """
    from zoneinfo import ZoneInfo

    timezone_name = task.timezone or default_timezone
    try:
        return ZoneInfo(timezone_name) if timezone_name else datetime.now().astimezone().tzinfo
    except Exception:
        return datetime.now().astimezone().tzinfo


def _parse_iso_datetime(value: str | None, task: ScheduledTask, default_timezone: str | None = None) -> datetime | None:
    """解析 ISO 时间字符串。

    参数:
        value: ISO 时间文本。
        task: 目标任务。
        default_timezone: 默认时区名称。

    返回:
        解析后的时间对象；为空时返回 ``None``。
    """
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_resolve_timezone(task, default_timezone))
    return parsed


def is_due(
    task: ScheduledTask,
    now: datetime,
    *,
    default_timezone: str | None = None,
) -> bool:
    """判断任务是否到期。

    参数:
        task: 目标任务。
        now: 当前时间。
        default_timezone: 默认时区名称。

    返回:
        到期时返回 ``True``。
    """
    if not task.enabled or not task.next_run_at:
        return False
    due_at = _parse_iso_datetime(task.next_run_at, task, default_timezone)
    return due_at is not None and due_at <= now


def compute_next_run(
    task: ScheduledTask,
    now: datetime,
    *,
    default_timezone: str | None = None,
) -> str | None:
    """计算任务下一次触发时间。

    参数:
        task: 目标任务。
        now: 当前时间。
        default_timezone: 默认时区名称。

    返回:
        下一次触发的 ISO 时间字符串；无后续触发时返回 ``None``。
    """
    tz = _resolve_timezone(task, default_timezone)
    localized_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)

    if task.schedule_type == "once":
        return None

    if task.schedule_type == "interval":
        seconds = int(task.interval_seconds or 0)
        if seconds <= 0:
            return None
        base = _parse_iso_datetime(task.next_run_at, task, default_timezone) or localized_now
        while base <= localized_now:
            base += timedelta(seconds=seconds)
        return base.isoformat()

    if task.schedule_type == "daily":
        if not task.daily_time:
            return None
        hour_text, minute_text = task.daily_time.split(":", 1)
        target_clock = time(hour=int(hour_text), minute=int(minute_text), tzinfo=tz)
        candidate = datetime.combine(localized_now.date(), target_clock)
        if candidate <= localized_now:
            candidate += timedelta(days=1)
        return candidate.isoformat()

    return None


def collect_due_tasks(
    tasks: list[ScheduledTask],
    now: datetime,
    *,
    default_timezone: str | None = None,
) -> list[ScheduledTask]:
    """筛选当前到期任务。

    参数:
        tasks: 任务列表。
        now: 当前时间。
        default_timezone: 默认时区名称。

    返回:
        当前到期的任务列表。
    """
    return [task for task in tasks if is_due(task, now, default_timezone=default_timezone)]
