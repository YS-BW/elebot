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
    """从 JSON 配置文件加载配置；不存在时返回默认配置。"""
    path = config_path or get_config_path()

    config = Config()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            config = Config.model_validate(data)
        except (json.JSONDecodeError, ValueError, pydantic.ValidationError) as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            logger.warning("Using default configuration.")

    _apply_ssrf_whitelist(config)
    return config


def _apply_ssrf_whitelist(config: Config) -> None:
    """把配置中的 SSRF 白名单同步到网络安全模块。"""
    from elebot.security.network import configure_ssrf_whitelist

    configure_ssrf_whitelist(config.tools.ssrf_whitelist)


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
