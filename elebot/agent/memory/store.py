"""记忆存储与 Dream 历史 owner。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from elebot.utils.fs import ensure_dir
from elebot.utils.gitstore import CommitInfo, GitStore
from elebot.utils.text import strip_think


@dataclass(slots=True)
class DreamVersion:
    """表示一条 Dream 历史版本记录。"""

    sha: str
    message: str
    timestamp: str

    @classmethod
    def from_commit(cls, commit: CommitInfo) -> "DreamVersion":
        """把 Git 提交信息转换成 Dream 版本对象。

        参数:
            commit: Git 历史中的提交记录。

        返回:
            对应的 Dream 版本对象。
        """
        return cls(sha=commit.sha, message=commit.message, timestamp=commit.timestamp)


@dataclass(slots=True)
class DreamLogDetails:
    """表示一次 Dream 版本查看结果。"""

    status: str
    requested_sha: str | None = None
    commit: DreamVersion | None = None
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    message: str | None = None


@dataclass(slots=True)
class DreamRestoreDetails:
    """表示一次 Dream 版本恢复结果。"""

    status: str
    requested_sha: str
    new_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    message: str | None = None


class MemoryStore:
    """负责维护记忆目录里的文件事实，不承担模型决策逻辑。"""

    _DEFAULT_MAX_HISTORY = 1000

    def __init__(self, workspace: Path, max_history_entries: int = _DEFAULT_MAX_HISTORY):
        """建立记忆目录下各类文件的固定读写入口。

        参数:
            workspace: 当前工作区目录。
            max_history_entries: history.jsonl 保留的最大条数。

        返回:
            无返回值。
        """
        self.workspace = workspace
        self.max_history_entries = max_history_entries
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "history.jsonl"
        self.soul_file = workspace / "SOUL.md"
        self.user_file = workspace / "USER.md"
        self._cursor_file = self.memory_dir / ".cursor"
        self._dream_cursor_file = self.memory_dir / ".dream_cursor"
        self._git = GitStore(
            workspace,
            tracked_files=["SOUL.md", "USER.md", "memory/MEMORY.md"],
        )
        self._cleanup_legacy_history_files()

    @property
    def git(self) -> GitStore:
        """暴露记忆目录对应的 GitStore。

        参数:
            无。

        返回:
            当前记忆目录对应的 GitStore 实例。
        """
        return self._git

    @staticmethod
    def read_file(path: Path) -> str:
        """读取文本文件，并把“文件不存在”统一折叠为空字符串。

        参数:
            path: 待读取的文件路径。

        返回:
            文件文本；缺失时返回空字符串。
        """
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _cleanup_legacy_history_files(self) -> None:
        """删除旧版历史文件及其备份。

        返回:
            无返回值。
        """
        for path in self.memory_dir.glob("HISTORY.md*"):
            if not path.is_file():
                continue
            try:
                path.unlink()
            except OSError:
                logger.warning("Failed to remove legacy history file {}", path)

    def read_memory(self) -> str:
        """读取长期记忆文件。

        参数:
            无。

        返回:
            `MEMORY.md` 的文本内容；缺失时返回空字符串。
        """
        return self.read_file(self.memory_file)

    def write_memory(self, content: str) -> None:
        """写入长期记忆文件。

        参数:
            content: 需要写入 `MEMORY.md` 的文本。

        返回:
            无返回值。
        """
        self.memory_file.write_text(content, encoding="utf-8")

    def read_soul(self) -> str:
        """读取 `SOUL.md`。

        参数:
            无。

        返回:
            `SOUL.md` 的文本内容；缺失时返回空字符串。
        """
        return self.read_file(self.soul_file)

    def write_soul(self, content: str) -> None:
        """写入 `SOUL.md`。

        参数:
            content: 需要写入的文本内容。

        返回:
            无返回值。
        """
        self.soul_file.write_text(content, encoding="utf-8")

    def read_user(self) -> str:
        """读取 `USER.md`。

        参数:
            无。

        返回:
            `USER.md` 的文本内容；缺失时返回空字符串。
        """
        return self.read_file(self.user_file)

    def write_user(self, content: str) -> None:
        """写入 `USER.md`。

        参数:
            content: 需要写入的文本内容。

        返回:
            无返回值。
        """
        self.user_file.write_text(content, encoding="utf-8")

    def get_memory_context(self) -> str:
        """返回可直接注入提示词的长期记忆片段。

        参数:
            无。

        返回:
            带标题的长期记忆文本；为空时返回空字符串。
        """
        long_term = self.read_memory()
        return f"## 长期记忆\n{long_term}" if long_term else ""

    def append_history(self, entry: str) -> int:
        """向历史文件追加一条记录。

        参数:
            entry: 需要写入历史的文本内容。

        返回:
            新写入记录对应的自增游标。
        """
        cursor = self._next_cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        record = {
            "cursor": cursor,
            "timestamp": timestamp,
            "content": strip_think(entry.rstrip()) or entry.rstrip(),
        }
        with open(self.history_file, "a", encoding="utf-8") as history_file:
            history_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._cursor_file.write_text(str(cursor), encoding="utf-8")
        return cursor

    def _next_cursor(self) -> int:
        """读取当前游标并返回下一值。"""
        if self._cursor_file.exists():
            try:
                return int(self._cursor_file.read_text(encoding="utf-8").strip()) + 1
            except (ValueError, OSError):
                pass
        # 游标文件损坏时退回到读取 JSONL 最后一行，避免历史追加中断。
        last_entry = self._read_last_entry()
        if last_entry:
            return last_entry["cursor"] + 1
        return 1

    def read_unprocessed_history(self, since_cursor: int) -> list[dict[str, Any]]:
        """读取指定游标之后尚未处理的历史记录。

        参数:
            since_cursor: 已处理到的最后游标。

        返回:
            游标大于该值的历史记录列表。
        """
        return [entry for entry in self._read_entries() if entry["cursor"] > since_cursor]

    def compact_history(self) -> None:
        """在历史条目超限时裁掉最旧记录。

        参数:
            无。

        返回:
            无返回值。
        """
        if self.max_history_entries <= 0:
            return
        entries = self._read_entries()
        if len(entries) <= self.max_history_entries:
            return
        kept = entries[-self.max_history_entries :]
        self._write_entries(kept)

    def _read_entries(self) -> list[dict[str, Any]]:
        """读取 history.jsonl 全部记录。"""
        entries: list[dict[str, Any]] = []
        try:
            with open(self.history_file, "r", encoding="utf-8") as history_file:
                for line in history_file:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return entries

    def _read_last_entry(self) -> dict[str, Any] | None:
        """高效读取 JSONL 最后一条记录。"""
        try:
            with open(self.history_file, "rb") as history_file:
                history_file.seek(0, 2)
                size = history_file.tell()
                if size == 0:
                    return None
                read_size = min(size, 4096)
                history_file.seek(size - read_size)
                data = history_file.read().decode("utf-8")
                lines = [line for line in data.split("\n") if line.strip()]
                if not lines:
                    return None
                return json.loads(lines[-1])
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _write_entries(self, entries: list[dict[str, Any]]) -> None:
        """用给定记录整体覆盖 history.jsonl。"""
        with open(self.history_file, "w", encoding="utf-8") as history_file:
            for entry in entries:
                history_file.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_last_dream_cursor(self) -> int:
        """读取 Dream 已处理到的最后游标。

        参数:
            无。

        返回:
            已处理到的游标值；缺失时返回 0。
        """
        if self._dream_cursor_file.exists():
            try:
                return int(self._dream_cursor_file.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass
        return 0

    def set_last_dream_cursor(self, cursor: int) -> None:
        """写入 Dream 已处理到的最后游标。

        参数:
            cursor: 需要保存的最新游标值。

        返回:
            无返回值。
        """
        self._dream_cursor_file.write_text(str(cursor), encoding="utf-8")

    def list_dream_versions(self, max_entries: int = 10) -> list[DreamVersion]:
        """列出最近的 Dream 历史版本。

        参数:
            max_entries: 最多返回多少条版本记录。

        返回:
            版本列表；未初始化时返回空列表。
        """
        if not self.git.is_initialized():
            return []
        return [DreamVersion.from_commit(commit) for commit in self.git.log(max_entries=max_entries)]

    def show_dream_version(self, sha: str | None = None) -> DreamLogDetails:
        """查看最近一次或指定 Dream 版本差异。

        参数:
            sha: 可选的目标提交 SHA。

        返回:
            Dream 版本查看结果对象。
        """
        if not self.git.is_initialized():
            if self.get_last_dream_cursor() == 0:
                return DreamLogDetails(status="never_run", requested_sha=sha)
            return DreamLogDetails(status="unavailable", requested_sha=sha)

        target_sha = sha
        if target_sha is None:
            commits = self.git.log(max_entries=1)
            if not commits:
                return DreamLogDetails(status="empty")
            target_sha = commits[0].sha

        result = self.git.show_commit_diff(target_sha)
        if result is None:
            return DreamLogDetails(status="not_found", requested_sha=target_sha)

        commit, diff = result
        return DreamLogDetails(
            status="ok",
            requested_sha=sha,
            commit=DreamVersion.from_commit(commit),
            diff=diff,
            changed_files=self._extract_changed_files(diff),
        )

    def restore_dream_version(self, sha: str) -> DreamRestoreDetails:
        """把 Dream 记忆恢复到指定版本之前的状态。

        参数:
            sha: 需要回退的 Dream 提交 SHA。

        返回:
            Dream 恢复结果对象。
        """
        if not self.git.is_initialized():
            return DreamRestoreDetails(status="unavailable", requested_sha=sha)

        result = self.git.show_commit_diff(sha)
        changed_files = self._extract_changed_files(result[1]) if result else []
        new_sha = self.git.revert(sha)
        if new_sha is None:
            return DreamRestoreDetails(
                status="not_found",
                requested_sha=sha,
                changed_files=changed_files,
            )
        return DreamRestoreDetails(
            status="ok",
            requested_sha=sha,
            new_sha=new_sha,
            changed_files=changed_files,
        )

    @staticmethod
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

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        """把消息数组格式化成归档文本。"""
        lines: list[str] = []
        for message in messages:
            if not message.get("content"):
                continue
            tools = (
                f" [tools: {', '.join(message['tools_used'])}]"
                if message.get("tools_used")
                else ""
            )
            lines.append(
                f"[{message.get('timestamp', '?')[:16]}] "
                f"{message['role'].upper()}{tools}: {message['content']}"
            )
        return "\n".join(lines)

    def raw_archive(self, messages: list[dict]) -> None:
        """在摘要失败时把原始消息直接写入历史归档。

        参数:
            messages: 需要兜底归档的消息数组。

        返回:
            无返回值。
        """
        self.append_history(
            f"[RAW] {len(messages)} messages\n"
            f"{self._format_messages(messages)}"
        )
        logger.warning(
            "Memory consolidation degraded: raw-archived {} messages",
            len(messages),
        )
