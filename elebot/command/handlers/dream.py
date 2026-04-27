"""Dream 相关 slash 命令。"""

from __future__ import annotations

from elebot.agent.memory.store import DreamLogDetails, DreamRestoreDetails, DreamVersion
from elebot.bus.events import OutboundMessage
from elebot.command.router import CommandContext


def _format_changed_files(changed_files: list[str]) -> str:
    """把变更文件列表格式化为展示文本。

    参数:
        changed_files: 变更文件路径列表。

    返回:
        用户可读的文件列表文本。
    """
    if not changed_files:
        return "没有检测到已跟踪记忆文件的变更。"
    return ", ".join(f"`{path}`" for path in changed_files)


def _format_dream_log_content(result: DreamLogDetails) -> str:
    """构造 Dream 版本日志展示文本。

    参数:
        result: Dream 日志查询结果。

    返回:
        面向用户的展示文本。
    """
    assert result.commit is not None
    files_line = _format_changed_files(result.changed_files)
    lines = [
        "## Dream 更新",
        "",
        "下面是你指定的 Dream 记忆变更。"
        if result.requested_sha
        else "下面是最近一次 Dream 记忆变更。",
        "",
        f"- 提交：`{result.commit.sha}`",
        f"- 时间：{result.commit.timestamp}",
        f"- 变更文件：{files_line}",
    ]
    if result.diff:
        lines.extend(
            [
                "",
                f"如果要撤销这次变更，可以执行 `/dream-restore {result.commit.sha}`。",
                "",
                "```diff",
                result.diff.rstrip(),
                "```",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Dream 已记录这个版本，但当前没有可展示的文件差异。",
            ]
        )
    return "\n".join(lines)


def _format_dream_restore_list(commits: list[DreamVersion]) -> str:
    """构造可恢复的 Dream 版本列表文本。

    参数:
        commits: 最近可恢复的 Dream 版本列表。

    返回:
        面向用户的展示文本。
    """
    lines = [
        "## Dream 恢复",
        "",
        "请选择要恢复的 Dream 记忆版本，最新的排在最前面：",
        "",
    ]
    for commit in commits:
        lines.append(f"- `{commit.sha}` {commit.timestamp} - {commit.message.splitlines()[0]}")
    lines.extend(
        [
            "",
            "恢复前可以先用 `/dream-log <sha>` 预览某个版本。",
            "确认后可用 `/dream-restore <sha>` 执行恢复。",
        ]
    )
    return "\n".join(lines)


def _format_dream_restore_content(result: DreamRestoreDetails) -> str:
    """构造 Dream 恢复结果文本。

    参数:
        result: Dream 恢复结果。

    返回:
        面向用户的展示文本。
    """
    changed_files = _format_changed_files(result.changed_files) if result.changed_files else "已跟踪的记忆文件"
    if result.status == "ok":
        assert result.new_sha is not None
        return (
            f"已将 Dream 记忆恢复到 `{result.requested_sha}` 之前的状态。\n\n"
            f"- 新的安全提交：`{result.new_sha}`\n"
            f"- 已恢复文件：{changed_files}\n\n"
            f"可以执行 `/dream-log {result.new_sha}` 查看这次恢复带来的差异。"
        )
    return (
        f"无法恢复 Dream 变更 `{result.requested_sha}`。\n\n"
        "它可能不存在，或者它本身就是第一份保存版本，前面没有更早状态可供恢复。"
    )


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """手动触发一次 Dream 整理任务。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    ctx.loop.trigger_dream_background(ctx.msg.channel, ctx.msg.chat_id)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="Dream 执行中…",
    )


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """展示 Dream 最近一次或指定版本的变更内容。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    sha = ctx.args.strip().split()[0] if ctx.args.strip() else None
    result = ctx.loop.memory_store.show_dream_version(sha)
    if result.status == "never_run":
        content = "Dream 还没有运行过。可以手动执行 `/dream`，或等待下一次整理。"
    elif result.status == "unavailable":
        content = "当前无法查看 Dream 历史，因为记忆版本记录尚未初始化。"
    elif result.status == "not_found":
        assert result.requested_sha is not None
        content = (
            f"找不到 Dream 变更 `{result.requested_sha}`。\n\n"
            "可以先用 `/dream-restore` 查看最近版本列表，"
            "或直接用 `/dream-log` 查看最新一次变更。"
        )
    elif result.status == "empty":
        content = "Dream 记忆目前还没有保存过任何版本。"
    else:
        content = _format_dream_log_content(result)

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """从历史 Dream 提交恢复记忆文件。

    参数:
        ctx: 当前命令上下文。

    返回:
        标准出站消息。
    """
    args = ctx.args.strip()
    if not args:
        commits = ctx.loop.memory_store.list_dream_versions(max_entries=10)
        if not ctx.loop.memory_store.git.is_initialized():
            content = "当前无法查看 Dream 历史，因为记忆版本记录尚未初始化。"
        elif not commits:
            content = "Dream 记忆目前还没有可恢复的历史版本。"
        else:
            content = _format_dream_restore_list(commits)
    else:
        sha = args.split()[0]
        result = ctx.loop.memory_store.restore_dream_version(sha)
        if result.status == "unavailable":
            content = "当前无法查看 Dream 历史，因为记忆版本记录尚未初始化。"
        else:
            content = _format_dream_restore_content(result)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )
