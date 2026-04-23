"""重启通知相关工具。"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

RESTART_NOTIFY_CHANNEL_ENV = "NANOBOT_RESTART_NOTIFY_CHANNEL"
RESTART_NOTIFY_CHAT_ID_ENV = "NANOBOT_RESTART_NOTIFY_CHAT_ID"
RESTART_STARTED_AT_ENV = "NANOBOT_RESTART_STARTED_AT"


@dataclass(frozen=True)
class RestartNotice:
    """一次重启通知所需的最小信息。"""

    channel: str
    chat_id: str
    started_at_raw: str


def format_restart_completed_message(started_at_raw: str) -> str:
    """生成重启完成提示文本。

    参数:
        started_at_raw: 重启开始时间戳字符串。

    返回:
        面向用户的重启完成文本。
    """
    elapsed_suffix = ""
    if started_at_raw:
        try:
            elapsed_s = max(0.0, time.time() - float(started_at_raw))
            elapsed_suffix = f" in {elapsed_s:.1f}s"
        except ValueError:
            pass
    return f"Restart completed{elapsed_suffix}."


def set_restart_notice_to_env(*, channel: str, chat_id: str) -> None:
    """把重启通知写入环境变量。

    参数:
        channel: 通知目标频道。
        chat_id: 通知目标会话 ID。

    返回:
        None。
    """
    os.environ[RESTART_NOTIFY_CHANNEL_ENV] = channel
    os.environ[RESTART_NOTIFY_CHAT_ID_ENV] = chat_id
    os.environ[RESTART_STARTED_AT_ENV] = str(time.time())


def consume_restart_notice_from_env() -> RestartNotice | None:
    """读取并清空当前进程的重启通知环境变量。

    返回:
        成功时返回重启通知对象，否则返回 None。
    """
    channel = os.environ.pop(RESTART_NOTIFY_CHANNEL_ENV, "").strip()
    chat_id = os.environ.pop(RESTART_NOTIFY_CHAT_ID_ENV, "").strip()
    started_at_raw = os.environ.pop(RESTART_STARTED_AT_ENV, "").strip()
    if not (channel and chat_id):
        return None
    return RestartNotice(channel=channel, chat_id=chat_id, started_at_raw=started_at_raw)


def should_show_cli_restart_notice(notice: RestartNotice, session_id: str) -> bool:
    """判断当前 CLI 会话是否应展示重启通知。

    参数:
        notice: 已解析的重启通知对象。
        session_id: 当前 CLI 会话 ID。

    返回:
        应显示通知时返回 True，否则返回 False。
    """
    if notice.channel != "cli":
        return False
    if ":" in session_id:
        _, cli_chat_id = session_id.split(":", 1)
    else:
        cli_chat_id = session_id
    return not notice.chat_id or notice.chat_id == cli_chat_id
