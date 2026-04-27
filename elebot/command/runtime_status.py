"""运行时状态文案格式化。"""

from __future__ import annotations

import time


def build_status_content(
    *,
    version: str,
    model: str,
    start_time: float,
    last_usage: dict[str, int],
    context_window_tokens: int,
    session_msg_count: int,
    context_tokens_estimate: int,
    search_usage_text: str | None = None,
) -> str:
    """构造面向用户展示的运行时状态文本。

    参数:
        version: 当前版本号。
        model: 当前模型名。
        start_time: 启动时间戳。
        last_usage: 最近一次用量统计。
        context_window_tokens: 当前上下文窗口大小。
        session_msg_count: 当前会话消息数。
        context_tokens_estimate: 当前上下文 token 估算值。
        search_usage_text: 可选搜索用量描述。

    返回:
        供命令直接展示的状态文本。
    """
    uptime_s = int(time.time() - start_time)
    uptime = (
        f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m"
        if uptime_s >= 3600
        else f"{uptime_s // 60}m {uptime_s % 60}s"
    )
    last_in = last_usage.get("prompt_tokens", 0)
    last_out = last_usage.get("completion_tokens", 0)
    cached = last_usage.get("cached_tokens", 0)
    ctx_total = max(context_window_tokens, 0)
    ctx_pct = int((context_tokens_estimate / ctx_total) * 100) if ctx_total > 0 else 0
    ctx_used_str = (
        f"{context_tokens_estimate // 1000}k"
        if context_tokens_estimate >= 1000
        else str(context_tokens_estimate)
    )
    ctx_total_str = f"{ctx_total // 1000}k" if ctx_total > 0 else "n/a"
    token_line = f"\U0001f4ca Tokens: {last_in} in / {last_out} out"
    if cached and last_in:
        token_line += f" ({cached * 100 // last_in}% cached)"
    lines = [
        f"\U0001f408 elebot v{version}",
        f"\U0001f9e0 Model: {model}",
        token_line,
        f"\U0001f4da Context: {ctx_used_str}/{ctx_total_str} ({ctx_pct}%)",
        f"\U0001f4ac Session: {session_msg_count} messages",
        f"\u23f1 Uptime: {uptime}",
    ]
    if search_usage_text:
        lines.append(search_usage_text)
    return "\n".join(lines)
