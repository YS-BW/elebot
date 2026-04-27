"""文本相关的低层工具函数。"""

from __future__ import annotations

import re


def strip_think(text: str) -> str:
    """移除思考标签及未闭合尾块。

    参数:
        text: 原始文本。

    返回:
        剥离 think 内容后的文本。
    """
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"^\s*<think>[\s\S]*$", "", text)
    text = re.sub(r"<thought>[\s\S]*?</thought>", "", text)
    text = re.sub(r"^\s*<thought>[\s\S]*$", "", text)
    return text.strip()


def image_placeholder_text(path: str | None, *, empty: str = "[image]") -> str:
    """生成图片占位文本。

    参数:
        path: 图片原始路径。
        empty: 路径缺失时的占位文本。

    返回:
        面向日志或历史的图片占位文本。
    """
    return f"[image: {path}]" if path else empty


def truncate_text(text: str, max_chars: int) -> str:
    """按固定后缀截断文本。

    参数:
        text: 原始文本。
        max_chars: 最大字符数。

    返回:
        截断后的文本。
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """把长文本拆成多段，优先保留人能读懂的断点。

    参数:
        content: 待拆分的文本。
        max_len: 每段最大长度。

    返回:
        每段长度不超过上限的文本列表。
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        pos = cut.rfind("\n")
        if pos <= 0:
            pos = cut.rfind(" ")
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks
