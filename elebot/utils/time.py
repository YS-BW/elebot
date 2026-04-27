"""时间相关的低层工具函数。"""

from __future__ import annotations

import time
from datetime import datetime


def timestamp() -> str:
    """返回当前 ISO 时间戳字符串。

    返回:
        当前时间的 ISO 格式字符串。
    """
    return datetime.now().isoformat()


def current_time_str(timezone: str | None = None) -> str:
    """返回带时区信息的当前时间字符串。

    参数:
        timezone: 可选的 IANA 时区名。

    返回:
        带时区与 UTC 偏移的格式化时间字符串。
    """
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(timezone) if timezone else None
    except (KeyError, Exception):
        tz = None

    now = datetime.now(tz=tz) if tz else datetime.now().astimezone()
    offset = now.strftime("%z")
    offset_fmt = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    tz_name = timezone or (time.strftime("%Z") or "UTC")
    return f"{now.strftime('%Y-%m-%d %H:%M (%A)')} ({tz_name}, UTC{offset_fmt})"
