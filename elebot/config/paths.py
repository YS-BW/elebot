"""基于当前配置上下文的运行时路径助手。"""

from __future__ import annotations

from pathlib import Path

from elebot.config.loader import get_config_path
from elebot.utils.helpers import ensure_dir


ELEBOT_HOME_DIR = Path.home() / ".elebot"
DEFAULT_WORKSPACE_DIR = ELEBOT_HOME_DIR / "workspace"
DEFAULT_HISTORY_PATH = ELEBOT_HOME_DIR / "history" / "cli_history"
DEFAULT_BRIDGE_DIR = ELEBOT_HOME_DIR / "bridge"


def get_data_dir() -> Path:
    """返回当前实例的运行时数据目录。"""
    return ensure_dir(get_config_path().parent)


def get_runtime_subdir(name: str) -> Path:
    """返回当前实例下的命名运行时子目录。"""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """返回媒体目录；传入频道名时再细分子目录。"""
    media_dir = get_runtime_subdir("media")
    return ensure_dir(media_dir / channel) if channel else media_dir


def get_cron_dir() -> Path:
    """返回定时任务存储目录。"""
    return get_runtime_subdir("cron")


def get_logs_dir() -> Path:
    """返回日志目录。"""
    return get_runtime_subdir("logs")


def get_workspace_path(workspace: str | None = None) -> Path:
    """解析并确保工作区目录存在。"""
    workspace_path = Path(workspace).expanduser() if workspace else DEFAULT_WORKSPACE_DIR
    return ensure_dir(workspace_path)


def is_default_workspace(workspace: str | Path | None) -> bool:
    """判断工作区是否落在默认 `~/.elebot/workspace`。"""
    current_path = Path(workspace).expanduser() if workspace is not None else DEFAULT_WORKSPACE_DIR
    return current_path.resolve(strict=False) == DEFAULT_WORKSPACE_DIR.resolve(strict=False)


def get_cli_history_path() -> Path:
    """返回共享 CLI 历史文件路径。"""
    return DEFAULT_HISTORY_PATH


def get_bridge_install_dir() -> Path:
    """返回共享 WhatsApp bridge 安装目录。"""
    return DEFAULT_BRIDGE_DIR
