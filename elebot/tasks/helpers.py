"""定时任务的校验、构造与格式化辅助函数。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from elebot.tasks.models import ScheduledTask
from elebot.tasks.scheduler import compute_next_run
from elebot.utils.time import timestamp

_DAILY_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")


def validate_daily_time(daily_time: str | None) -> str | None:
    """校验每日任务时间字符串。

    参数:
        daily_time: 待校验的时间字符串。

    返回:
        错误信息；合法时返回 ``None``。
    """
    if not daily_time:
        return "daily 任务必须提供 daily_time。"
    if not _DAILY_TIME_PATTERN.match(daily_time):
        return "daily_time 必须是 HH:MM 格式。"
    hour_text, minute_text = daily_time.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 23:
        return "daily_time 的小时必须在 00-23 之间。"
    if minute < 0 or minute > 59:
        return "daily_time 的分钟必须在 00-59 之间。"
    return None


def parse_run_at(
    run_at: str | None,
    *,
    default_timezone: str,
    reject_past: bool = True,
) -> tuple[str | None, str | None]:
    """解析并规范化一次性任务时间。

    参数:
        run_at: 原始时间字符串。
        default_timezone: 默认时区名称。
        reject_past: 是否拒绝过去时间。

    返回:
        ``(规范化后的 ISO 文本, 错误信息)``。
    """
    if not run_at:
        return None, "once 任务必须提供 run_at。"
    from zoneinfo import ZoneInfo

    try:
        parsed = datetime.fromisoformat(run_at)
    except ValueError:
        return None, "run_at 必须是合法的 ISO 时间。"

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))

    if reject_past and parsed <= datetime.now(parsed.tzinfo):
        return None, "run_at 不能早于当前时间。"

    return parsed.isoformat(), None


def build_scheduled_task(
    *,
    content: str,
    schedule_type: str,
    session_key: str,
    default_timezone: str,
    run_at: str | None = None,
    interval_seconds: int | None = None,
    daily_time: str | None = None,
    timezone: str | None = None,
    source: str = "agent",
    task_id: str | None = None,
    existing: ScheduledTask | None = None,
) -> tuple[ScheduledTask | None, str | None]:
    """构造并校验任务对象。

    参数:
        content: 任务触发内容。
        schedule_type: 任务类型。
        session_key: 绑定会话键。
        default_timezone: 默认时区名称。
        run_at: 一次性任务时间。
        interval_seconds: 间隔任务秒数。
        daily_time: 每日任务时间。
        timezone: 任务时区。
        source: 任务来源。
        task_id: 可选任务 ID。
        existing: 更新时的旧任务对象。

    返回:
        ``(任务对象, 错误信息)``。
    """
    effective_timezone = timezone or default_timezone or "Asia/Shanghai"
    normalized_run_at = run_at

    if schedule_type == "once":
        normalized_run_at, error = parse_run_at(
            run_at,
            default_timezone=effective_timezone,
            reject_past=True,
        )
        if error:
            return None, error
    elif schedule_type == "interval":
        if not interval_seconds:
            return None, "interval 任务必须提供 interval_seconds。"
    elif schedule_type == "daily":
        error = validate_daily_time(daily_time)
        if error:
            return None, error
    else:
        return None, "不支持的 schedule_type。"

    now_text = timestamp()
    task = ScheduledTask(
        task_id=task_id or existing.task_id if existing else task_id or f"task_{uuid.uuid4().hex[:12]}",
        session_key=session_key,
        content=content,
        schedule_type=schedule_type,
        run_at=normalized_run_at,
        interval_seconds=interval_seconds,
        daily_time=daily_time,
        timezone=effective_timezone,
        enabled=True if existing is None else existing.enabled,
        created_at=existing.created_at if existing else now_text,
        updated_at=now_text,
        last_run_at=existing.last_run_at if existing else None,
        next_run_at=normalized_run_at,
        source=source if existing is None else existing.source,
        run_count=existing.run_count if existing else 0,
        last_status=existing.last_status if existing else None,
        last_error=existing.last_error if existing else None,
        last_finished_at=existing.last_finished_at if existing else None,
    )
    if schedule_type != "once":
        task.next_run_at = compute_next_run(
            task,
            datetime.now().astimezone(),
            default_timezone=effective_timezone,
        )
    return task, None


def format_task_summary(task: ScheduledTask) -> str:
    """格式化任务摘要。

    参数:
        task: 目标任务。

    返回:
        供提示或展示的摘要文本。
    """
    return (
        f"- 类型：{task.schedule_type}\n"
        f"- 会话：{task.session_key}\n"
        f"- 内容：{task.content}\n"
        f"- 下次触发：{task.next_run_at or '无'}"
    )


def build_task_proposal_payload(
    *,
    content: str,
    schedule_type: str,
    session_key: str,
    default_timezone: str,
    run_at: str | None = None,
    interval_seconds: int | None = None,
    daily_time: str | None = None,
    timezone: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """生成待确认任务 proposal。

    参数:
        与任务字段一致。

    返回:
        ``(proposal 字典, 错误信息)``。
    """
    task, error = build_scheduled_task(
        content=content,
        schedule_type=schedule_type,
        session_key=session_key,
        default_timezone=default_timezone,
        run_at=run_at,
        interval_seconds=interval_seconds,
        daily_time=daily_time,
        timezone=timezone,
        source="agent",
    )
    if error or task is None:
        return None, error
    proposal = {
        "content": task.content,
        "schedule_type": task.schedule_type,
        "session_key": task.session_key,
        "run_at": task.run_at,
        "interval_seconds": task.interval_seconds,
        "daily_time": task.daily_time,
        "timezone": task.timezone,
        "proposed_at": timestamp(),
    }
    return proposal, None
