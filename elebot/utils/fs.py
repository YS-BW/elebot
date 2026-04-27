"""文件系统相关的低层工具函数。"""

from __future__ import annotations

import re
from pathlib import Path

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def ensure_dir(path: Path) -> Path:
    """确保目录存在并返回该路径。

    参数:
        path: 目标目录路径。

    返回:
        已确保存在的目录路径。
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """将不安全文件名字符替换为下划线。

    参数:
        name: 原始文件名。

    返回:
        可安全落盘的文件名。
    """
    return _UNSAFE_CHARS.sub("_", name).strip()
