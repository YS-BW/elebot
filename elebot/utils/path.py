"""路径展示缩写工具。"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse


def abbreviate_path(path: str, max_len: int = 40) -> str:
    """缩写文件路径或 URL，同时尽量保留尾部关键信息。

    参数:
        path: 原始路径或 URL。
        max_len: 最大显示长度。

    返回:
        缩写后的展示文本。
    """
    if not path:
        return path

    # URL 优先保留域名和尾部文件名，否则可读性会明显下降。
    if re.match(r"https?://", path):
        return _abbreviate_url(path, max_len)

    # 统一分隔符后再处理，避免平台差异影响后续逻辑。
    normalized = path.replace("\\", "/")

    # 先把家目录替换成 `~`，通常可以显著缩短展示长度。
    home = os.path.expanduser("~").replace("\\", "/")
    if normalized.startswith(home + "/"):
        normalized = "~" + normalized[len(home):]
    elif normalized == home:
        normalized = "~"

    # 必须在标准化后再判断长度，避免误判。
    if len(normalized) <= max_len:
        return normalized

    # 后续按路径段裁剪，优先保留靠右的层级。
    parts = normalized.rstrip("/").split("/")
    if len(parts) <= 1:
        return normalized[:max_len - 1] + "\u2026"

    # 文件名最能帮助定位，因此始终保留。
    basename = parts[-1]
    # 预算扣掉省略前缀和末尾文件名，剩余空间留给父目录。
    budget = max_len - len(basename) - 3  # 3 个字符来自 "…/" 和最后一个 "/"

    # 从右往左回收父目录，优先保留离文件名最近的层级。
    kept: list[str] = []
    for seg in reversed(parts[:-1]):
        needed = len(seg) + 1  # 当前目录段加一个路径分隔符
        if not kept and needed <= budget:
            kept.append(seg)
            budget -= needed
        elif kept:
            needed_with_sep = len(seg) + 1
            if needed_with_sep <= budget:
                kept.append(seg)
                budget -= needed_with_sep
            else:
                break
        else:
            break

    kept.reverse()
    if kept:
        return "\u2026/" + "/".join(kept) + "/" + basename
    return "\u2026/" + basename


def _abbreviate_url(url: str, max_len: int = 40) -> str:
    """缩写 URL，并尽量保留域名和文件名。

    参数:
        url: 原始 URL。
        max_len: 最大显示长度。

    返回:
        缩写后的 URL 文本。
    """
    if len(url) <= max_len:
        return url

    parsed = urlparse(url)
    domain = parsed.netloc  # 例如 "example.com"
    path_part = parsed.path  # 例如 "/api/v2/resource.json"

    # URL 的最后一段通常最有辨识度。
    segments = path_part.rstrip("/").split("/")
    basename = segments[-1] if segments else ""

    if not basename:
        # 没有明确文件名时只能退化为普通截断。
        return url[: max_len - 1] + "\u2026"

    budget = max_len - len(domain) - len(basename) - 4  # "…/" + "/"
    if budget < 0:
        trunc = max_len - len(domain) - 5  # "…/" + "/"
        return domain + "/\u2026/" + (basename[:trunc] if trunc > 0 else "")

    # URL 路径也沿用“优先保留右侧路径段”的策略。
    kept: list[str] = []
    for seg in reversed(segments[:-1]):
        if len(seg) + 1 <= budget:
            kept.append(seg)
            budget -= len(seg) + 1
        else:
            break

    kept.reverse()
    if kept:
        return domain + "/\u2026/" + "/".join(kept) + "/" + basename
    return domain + "/\u2026/" + basename
