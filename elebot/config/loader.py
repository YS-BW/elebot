"""配置加载与保存。"""

import json
import os
import re
from pathlib import Path

import pydantic
from loguru import logger

from elebot.config.schema import Config

# 运行时允许切换配置文件路径，以便同一进程支持多实例。
_current_config_path: Path | None = None

_REMOVED_TOP_LEVEL_KEYS = ("channels", "api", "gateway")


def set_config_path(path: Path) -> None:
    """设置当前配置文件路径。"""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """返回当前配置文件路径。"""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".elebot" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """从 JSON 配置文件加载配置。

    参数:
        config_path: 可选的配置文件路径，未提供时使用当前活动路径。

    返回:
        解析后的配置对象；当文件不存在时返回默认配置。

    异常:
        ValueError: 配置文件内容非法，或仍包含已移除的顶层配置段。
    """
    path = config_path or get_config_path()

    if not path.exists():
        return Config()

    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件不是合法 JSON: {path}") from exc

    _raise_if_removed_keys_present(data, path)

    try:
        return Config.model_validate(data)
    except pydantic.ValidationError as exc:
        raise ValueError(f"配置文件校验失败: {path}\n{exc}") from exc


def save_config(config: Config, config_path: Path | None = None) -> None:
    """把配置保存为 JSON 文件。"""
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_config_env_vars(config: Config) -> Config:
    """返回已解析 `${VAR}` 环境变量占位符的新配置对象。"""
    data = config.model_dump(mode="json", by_alias=True)
    data = _resolve_env_vars(data)
    return Config.model_validate(data)


def _resolve_env_vars(obj: object) -> object:
    """递归解析字符串中的 `${VAR}` 占位符。"""
    if isinstance(obj, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _env_replace, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def _env_replace(match: re.Match[str]) -> str:
    """将单个环境变量占位符替换为实际值。"""
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(
            f"Environment variable '{name}' referenced in config is not set"
        )
    return value


def _raise_if_removed_keys_present(data: object, path: Path) -> None:
    """检查配置中是否仍包含已移除的 Frozen 顶层字段。

    参数:
        data: 原始 JSON 解析结果。
        path: 当前配置文件路径。

    返回:
        无返回值。

    异常:
        ValueError: 命中已移除字段时抛出，提示用户手动清理旧配置。
    """
    if not isinstance(data, dict):
        return

    removed_keys = [key for key in _REMOVED_TOP_LEVEL_KEYS if key in data]
    if not removed_keys:
        return

    removed_list = ", ".join(removed_keys)
    raise ValueError(
        f"配置文件包含已移除的顶层字段: {removed_list}。"
        f"请从 {path} 删除这些字段后重试。"
    )
