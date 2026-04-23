"""基于 Git 的记忆文件版本存储。"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass
class CommitInfo:
    """简化后的提交信息。"""

    sha: str  # 短 SHA（8 位）
    message: str
    timestamp: str  # 已格式化的时间字符串

    def format(self, diff: str = "") -> str:
        """格式化提交信息，必要时附带 diff。"""
        header = f"## {self.message.splitlines()[0]}\n`{self.sha}` — {self.timestamp}\n"
        if diff:
            return f"{header}\n```diff\n{diff}\n```"
        return f"{header}\n(no file changes)"


class GitStore:
    """为记忆文件提供基于 Git 的版本控制能力。"""

    def __init__(self, workspace: Path, tracked_files: list[str]):
        """初始化 Git 存储。"""
        self._workspace = workspace
        self._tracked_files = tracked_files

    def is_initialized(self) -> bool:
        """判断工作区是否已经初始化为 Git 仓库。"""
        return (self._workspace / ".git").is_dir()

    # 初始化相关操作

    def init(self) -> bool:
        """初始化 Git 仓库并写入首个提交。"""
        if self.is_initialized():
            return False

        try:
            from dulwich import porcelain

            porcelain.init(str(self._workspace))

            # 这里的 .gitignore 只放行受控文件，避免记忆仓库被无关文件污染。
            gitignore = self._workspace / ".gitignore"
            gitignore.write_text(self._build_gitignore(), encoding="utf-8")

            # 初始提交不能是空仓，因此需要先补齐缺失的受控文件。
            for rel in self._tracked_files:
                p = self._workspace / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_text("", encoding="utf-8")

            # 初始化时直接提交，保证后续 Dream/restore 有明确基线。
            porcelain.add(str(self._workspace), paths=[".gitignore"] + self._tracked_files)
            porcelain.commit(
                str(self._workspace),
                message=b"init: elebot memory store",
                author=b"elebot <elebot@dream>",
                committer=b"elebot <elebot@dream>",
            )
            logger.info("Git store initialized at {}", self._workspace)
            return True
        except Exception:
            logger.warning("Git store init failed for {}", self._workspace)
            return False

    # 日常提交操作

    def auto_commit(self, message: str) -> str | None:
        """在有变更时自动提交记忆文件。"""
        if not self.is_initialized():
            return None

        try:
            from dulwich import porcelain

            # 仓库只追踪受控文件，因此这里只要发现变更就可以直接提交。
            st = porcelain.status(str(self._workspace))
            if not st.unstaged and not any(st.staged.values()):
                return None

            msg_bytes = message.encode("utf-8") if isinstance(message, str) else message
            porcelain.add(str(self._workspace), paths=self._tracked_files)
            sha_bytes = porcelain.commit(
                str(self._workspace),
                message=msg_bytes,
                author=b"elebot <elebot@dream>",
                committer=b"elebot <elebot@dream>",
            )
            if sha_bytes is None:
                return None
            sha = sha_bytes.hex()[:8]
            logger.debug("Git auto-commit: {} ({})", sha, message)
            return sha
        except Exception:
            logger.warning("Git auto-commit failed: {}", message)
            return None

    # 内部辅助方法

    def _resolve_sha(self, short_sha: str) -> bytes | None:
        """将短 SHA 前缀解析为完整 SHA。"""
        try:
            from dulwich.repo import Repo

            with Repo(str(self._workspace)) as repo:
                try:
                    sha = repo.refs[b"HEAD"]
                except KeyError:
                    return None

                while sha:
                    if sha.hex().startswith(short_sha):
                        return sha
                    commit = repo[sha]
                    if commit.type_name != b"commit":
                        break
                    sha = commit.parents[0] if commit.parents else None
            return None
        except Exception:
            return None

    def _build_gitignore(self) -> str:
        """根据受控文件生成 .gitignore 内容。"""
        dirs: set[str] = set()
        for f in self._tracked_files:
            parent = str(Path(f).parent)
            if parent != ".":
                dirs.add(parent)
        lines = ["/*"]
        for d in sorted(dirs):
            lines.append(f"!{d}/")
        for f in self._tracked_files:
            lines.append(f"!{f}")
        lines.append("!.gitignore")
        return "\n".join(lines) + "\n"

    # 查询历史

    def log(self, max_entries: int = 20) -> list[CommitInfo]:
        """返回简化后的提交历史。"""
        if not self.is_initialized():
            return []

        try:
            from dulwich.repo import Repo

            entries: list[CommitInfo] = []
            with Repo(str(self._workspace)) as repo:
                try:
                    head = repo.refs[b"HEAD"]
                except KeyError:
                    return []

                sha = head
                while sha and len(entries) < max_entries:
                    commit = repo[sha]
                    if commit.type_name != b"commit":
                        break
                    ts = time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.localtime(commit.commit_time),
                    )
                    msg = commit.message.decode("utf-8", errors="replace").strip()
                    entries.append(CommitInfo(
                        sha=sha.hex()[:8],
                        message=msg,
                        timestamp=ts,
                    ))
                    sha = commit.parents[0] if commit.parents else None

            return entries
        except Exception:
            logger.warning("Git log failed")
            return []

    def diff_commits(self, sha1: str, sha2: str) -> str:
        """比较两个提交之间的差异。"""
        if not self.is_initialized():
            return ""

        try:
            from dulwich import porcelain

            full1 = self._resolve_sha(sha1)
            full2 = self._resolve_sha(sha2)
            if not full1 or not full2:
                return ""

            out = io.BytesIO()
            porcelain.diff(
                str(self._workspace),
                commit=full1,
                commit2=full2,
                outstream=out,
            )
            return out.getvalue().decode("utf-8", errors="replace")
        except Exception:
            logger.warning("Git diff_commits failed")
            return ""

    def find_commit(self, short_sha: str, max_entries: int = 20) -> CommitInfo | None:
        """按短 SHA 前缀查找提交。"""
        for c in self.log(max_entries=max_entries):
            if c.sha.startswith(short_sha):
                return c
        return None

    def show_commit_diff(self, short_sha: str, max_entries: int = 20) -> tuple[CommitInfo, str] | None:
        """查找提交并返回它与父提交的差异。"""
        commits = self.log(max_entries=max_entries)
        for i, c in enumerate(commits):
            if c.sha.startswith(short_sha):
                if i + 1 < len(commits):
                    diff = self.diff_commits(commits[i + 1].sha, c.sha)
                else:
                    diff = ""
                return c, diff
        return None

    # 恢复历史版本

    def revert(self, commit: str) -> str | None:
        """撤销指定提交带来的记忆文件变更。"""
        if not self.is_initialized():
            return None

        try:
            from dulwich.repo import Repo

            full_sha = self._resolve_sha(commit)
            if not full_sha:
                logger.warning("Git revert: SHA not found: {}", commit)
                return None

            with Repo(str(self._workspace)) as repo:
                commit_obj = repo[full_sha]
                if commit_obj.type_name != b"commit":
                    return None

                if not commit_obj.parents:
                    logger.warning("Git revert: cannot revert root commit {}", commit)
                    return None

                # 直接恢复父提交树，语义上才是真正撤销本次修改。
                parent_obj = repo[commit_obj.parents[0]]
                tree = repo[parent_obj.tree]

                restored: list[str] = []
                for filepath in self._tracked_files:
                    content = self._read_blob_from_tree(repo, tree, filepath)
                    if content is not None:
                        dest = self._workspace / filepath
                        dest.write_text(content, encoding="utf-8")
                        restored.append(filepath)

            if not restored:
                return None

            # 恢复完成后再补一条新提交，方便后续审计与再次回滚。
            msg = f"revert: undo {commit}"
            return self.auto_commit(msg)
        except Exception:
            logger.warning("Git revert failed for {}", commit)
            return None

    @staticmethod
    def _read_blob_from_tree(repo, tree, filepath: str) -> str | None:
        """按路径逐层读取树中的文件内容。"""
        parts = Path(filepath).parts
        current = tree
        for part in parts:
            try:
                entry = current[part.encode()]
            except KeyError:
                return None
            obj = repo[entry[1]]
            if obj.type_name == b"blob":
                return obj.data.decode("utf-8", errors="replace")
            if obj.type_name == b"tree":
                current = obj
            else:
                return None
        return None
