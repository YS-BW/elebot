"""基于当前配置上下文的运行时路径助手。"""

from __future__ import annotations

from pathlib import Path

from elebot.config.loader import get_config_path
from elebot.utils.helpers import ensure_dir


ELEBOT_HOME_DIR = Path.home() / ".elebot"
DEFAULT_WORKSPACE_DIR = ELEBOT_HOME_DIR / "workspace"
DEFAULT_HISTORY_PATH = ELEBOT_HOME_DIR / "history" / "cli_history"
GLOBAL_SKILLS_DIR = ELEBOT_HOME_DIR / "skills"


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


def get_logs_dir() -> Path:
    """返回日志目录。"""
    return get_runtime_subdir("logs")


def get_tasks_dir() -> Path:
    """返回任务目录。"""
    return get_runtime_subdir("tasks")


def get_tasks_store_path() -> Path:
    """返回任务存储文件路径。"""
    return get_tasks_dir() / "tasks.json"


def get_skill_usage_log_path() -> Path:
    """返回 skill 使用日志文件路径。"""
    return get_logs_dir() / "skill_usage.jsonl"


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
