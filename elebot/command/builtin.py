"""内置 slash 命令处理器。"""

from __future__ import annotations

import asyncio
import os
import sys

from elebot import __version__
from elebot.bus.events import OutboundMessage
from elebot.command.router import CommandContext, CommandRouter
from elebot.utils.helpers import build_status_content
from elebot.utils.restart import set_restart_notice_to_env

SLASH_COMMAND_SPECS: list[tuple[str, str]] = [
    ("/new", "开始新会话"),
    ("/stop", "停止当前任务"),
    ("/restart", "重启 elebot"),
    ("/status", "查看当前状态"),
    ("/dream", "手动触发 Dream 整理"),
    ("/dream-log", "查看最近一次 Dream 变更"),
    ("/dream-restore", "恢复到之前的 Dream 版本"),
    ("/help", "查看可用命令"),
]


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """停止当前会话下的活动任务。"""
    loop = ctx.loop
    msg = ctx.msg
    tasks = loop._active_tasks.pop(msg.session_key, [])
    cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    content = f"已停止 {cancelled} 个任务。" if cancelled else "当前没有可停止的任务。"
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content=content,
        metadata=dict(msg.metadata or {})
    )


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """通过 `os.execv` 原地重启当前进程。"""
    msg = ctx.msg
    set_restart_notice_to_env(channel=msg.channel, chat_id=msg.chat_id)

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "elebot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content="正在重启……",
        metadata=dict(msg.metadata or {})
    )


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """生成当前会话的状态消息。"""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    try:
        ctx_est, _ = loop.consolidator.estimate_session_prompt_tokens(session)
    except Exception:
        pass
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)
    
    # 搜索用量只是附加信息，失败时不能影响 /status 主响应。
    search_usage_text: str | None = None
    try:
        from elebot.utils.searchusage import fetch_search_usage
        web_cfg = getattr(loop, "web_config", None)
        search_cfg = getattr(web_cfg, "search", None) if web_cfg else None
        if search_cfg is not None:
            provider = getattr(search_cfg, "provider", "duckduckgo")
            api_key = getattr(search_cfg, "api_key", "") or None
            usage = await fetch_search_usage(provider=provider, api_key=api_key)
            search_usage_text = usage.format()
    except Exception:
        pass  # /status 必须稳定返回，不能因为附加信息查询失败而中断。
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__, model=loop.model,
            start_time=loop._start_time, last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
            search_usage_text=search_usage_text,
        ),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """开启全新会话。"""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated:]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.consolidator.archive(snapshot))
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content="已开始新会话。",
        metadata=dict(ctx.msg.metadata or {})
    )


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """手动触发一次 Dream 整理任务。"""
    import time

    loop = ctx.loop
    msg = ctx.msg

    async def _run_dream():
        t0 = time.monotonic()
        try:
            did_work = await loop.dream.run()
            elapsed = time.monotonic() - t0
            if did_work:
                content = f"Dream 已完成，耗时 {elapsed:.1f}s。"
            else:
                content = "Dream：没有需要处理的内容。"
        except Exception as e:
            elapsed = time.monotonic() - t0
            content = f"Dream 执行失败，耗时 {elapsed:.1f}s：{e}"
        await loop.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    asyncio.create_task(_run_dream())
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content="Dream 执行中…",
    )


def _extract_changed_files(diff: str) -> list[str]:
    """从 unified diff 中提取变更文件路径。"""
    files: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3]
        if path.startswith("b/"):
            path = path[2:]
        if path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def _format_changed_files(diff: str) -> str:
    """把变更文件列表格式化为展示文本。"""
    files = _extract_changed_files(diff)
    if not files:
        return "没有检测到已跟踪记忆文件的变更。"
    return ", ".join(f"`{path}`" for path in files)


def _format_dream_log_content(commit, diff: str, *, requested_sha: str | None = None) -> str:
    """构造 Dream 版本日志展示文本。"""
    files_line = _format_changed_files(diff)
    lines = [
        "## Dream 更新",
        "",
        "下面是你指定的 Dream 记忆变更。" if requested_sha else "下面是最近一次 Dream 记忆变更。",
        "",
        f"- 提交：`{commit.sha}`",
        f"- 时间：{commit.timestamp}",
        f"- 变更文件：{files_line}",
    ]
    if diff:
        lines.extend([
            "",
            f"如果要撤销这次变更，可以执行 `/dream-restore {commit.sha}`。",
            "",
            "```diff",
            diff.rstrip(),
            "```",
        ])
    else:
        lines.extend([
            "",
            "Dream 已记录这个版本，但当前没有可展示的文件差异。",
        ])
    return "\n".join(lines)


def _format_dream_restore_list(commits: list) -> str:
    """构造可恢复的 Dream 版本列表文本。"""
    lines = [
        "## Dream 恢复",
        "",
        "请选择要恢复的 Dream 记忆版本，最新的排在最前面：",
        "",
    ]
    for c in commits:
        lines.append(f"- `{c.sha}` {c.timestamp} - {c.message.splitlines()[0]}")
    lines.extend([
        "",
        "恢复前可以先用 `/dream-log <sha>` 预览某个版本。",
        "确认后可用 `/dream-restore <sha>` 执行恢复。",
    ])
    return "\n".join(lines)


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """展示 Dream 最近一次或指定版本的变更内容。"""
    store = ctx.loop.consolidator.store
    git = store.git

    if not git.is_initialized():
        if store.get_last_dream_cursor() == 0:
            msg = "Dream 还没有运行过。可以手动执行 `/dream`，或等待下一次整理。"
        else:
            msg = "当前无法查看 Dream 历史，因为记忆版本记录尚未初始化。"
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=msg, metadata={"render_as": "text"},
        )

    args = ctx.args.strip()

    if args:
        # 显式指定提交时，优先展示用户要求的那个版本。
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        if not result:
            content = (
                f"找不到 Dream 变更 `{sha}`。\n\n"
                "可以先用 `/dream-restore` 查看最近版本列表，"
                "或直接用 `/dream-log` 查看最新一次变更。"
            )
        else:
            commit, diff = result
            content = _format_dream_log_content(commit, diff, requested_sha=sha)
    else:
        # 默认展示最近一次 Dream 提交及其差异。
        commits = git.log(max_entries=1)
        result = git.show_commit_diff(commits[0].sha) if commits else None
        if result:
            commit, diff = result
            content = _format_dream_log_content(commit, diff)
        else:
            content = "Dream 记忆目前还没有保存过任何版本。"

    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """从历史 Dream 提交恢复记忆文件。"""
    store = ctx.loop.consolidator.store
    git = store.git
    if not git.is_initialized():
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="当前无法查看 Dream 历史，因为记忆版本记录尚未初始化。",
        )

    args = ctx.args.strip()
    if not args:
        # 不带参数时先列出可恢复版本，避免用户盲目回滚。
        commits = git.log(max_entries=10)
        if not commits:
            content = "Dream 记忆目前还没有可恢复的历史版本。"
        else:
            content = _format_dream_restore_list(commits)
    else:
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        changed_files = _format_changed_files(result[1]) if result else "已跟踪的记忆文件"
        new_sha = git.revert(sha)
        if new_sha:
            content = (
                f"已将 Dream 记忆恢复到 `{sha}` 之前的状态。\n\n"
                f"- 新的安全提交：`{new_sha}`\n"
                f"- 已恢复文件：{changed_files}\n\n"
                f"可以执行 `/dream-log {new_sha}` 查看这次恢复带来的差异。"
            )
        else:
            content = (
                f"无法恢复 Dream 变更 `{sha}`。\n\n"
                "它可能不存在，或者它本身就是第一份保存版本，前面没有更早状态可供恢复。"
            )
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """返回可用 slash 命令列表。"""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_help_text(),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def build_help_text() -> str:
    """构造各渠道共用的帮助文本。"""
    lines = ["🍌 elebot 命令："]
    lines.extend(f"{command} — {description}" for command, description in SLASH_COMMAND_SPECS)
    return "\n".join(lines)


def register_builtin_commands(router: CommandRouter) -> None:
    """注册默认内置 slash 命令。"""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.exact("/help", cmd_help)
