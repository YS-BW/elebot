"""跟踪文件读取状态，服务于编辑前检查与去重读取。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ReadState:
    """记录单个文件最近一次读取或写入后的状态快照。"""
    mtime: float
    offset: int
    limit: int | None
    content_hash: str | None
    can_dedup: bool


_state: dict[str, ReadState] = {}


def _hash_file(p: str) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def record_read(path: str | Path, offset: int = 1, limit: int | None = None) -> None:
    """记录一次成功读取。

    参数:
        path: 文件路径。
        offset: 读取起始行。
        limit: 读取行数限制。

    返回:
        无返回值。
    """
    p = str(Path(path).resolve())
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return
    _state[p] = ReadState(
        mtime=mtime,
        offset=offset,
        limit=limit,
        content_hash=_hash_file(p),
        can_dedup=True,
    )


def record_write(path: str | Path) -> None:
    """记录一次成功写入。

    参数:
        path: 文件路径。

    返回:
        无返回值。
    """
    p = str(Path(path).resolve())
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        _state.pop(p, None)
        return
    _state[p] = ReadState(
        mtime=mtime,
        offset=1,
        limit=None,
        content_hash=_hash_file(p),
        can_dedup=False,
    )


def check_read(path: str | Path) -> str | None:
    """检查文件是否读过且状态仍然新鲜。

    参数:
        path: 文件路径。

    返回:
        无警告时返回 ``None``，否则返回提示文本。
    """
    p = str(Path(path).resolve())
    entry = _state.get(p)
    if entry is None:
        return "Warning: file has not been read yet. Read it first to verify content before editing."
    try:
        current_mtime = os.path.getmtime(p)
    except OSError:
        return None
    if current_mtime != entry.mtime:
        if entry.content_hash and _hash_file(p) == entry.content_hash:
            entry.mtime = current_mtime
            return None
        return "Warning: file has been modified since last read. Re-read to verify content before editing."
    return None


def is_unchanged(path: str | Path, offset: int = 1, limit: int | None = None) -> bool:
    """判断文件是否与上次相同参数读取时保持不变。

    参数:
        path: 文件路径。
        offset: 读取起始行。
        limit: 读取行数限制。

    返回:
        文件未变化时返回 ``True``。
    """
    p = str(Path(path).resolve())
    entry = _state.get(p)
    if entry is None:
        return False
    if not entry.can_dedup:
        return False
    if entry.offset != offset or entry.limit != limit:
        return False
    try:
        current_mtime = os.path.getmtime(p)
    except OSError:
        return False
    return current_mtime == entry.mtime


def clear() -> None:
    """清空全部读取状态记录。

    返回:
        无返回值。
    """
    _state.clear()
