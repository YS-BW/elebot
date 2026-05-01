"""搜索工具，提供 glob 与 grep 两类能力。"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, TypeVar

from elebot.agent.tools.filesystem import ListDirTool, _FsTool

_DEFAULT_HEAD_LIMIT = 250
_logger = logging.getLogger(__name__)


class _WindowsSearchBackend:
    """Windows Search 索引查询后端，懒初始化，不可用时自动降级。"""

    def __init__(self) -> None:
        """初始化后端，尝试连接 Windows Search。"""
        self._conn: Any = None
        self._available: bool | None = None  # None = 未检测

    def available(self) -> bool:
        """检查 Windows Search 是否可用。

        返回:
            可用时返回 ``True``。
        """
        if self._available is not None:
            return self._available
        if sys.platform != "win32":
            self._available = False
            return False
        try:
            import win32com.client

            conn = win32com.client.Dispatch("ADODB.Connection")
            conn.Open(
                "Provider=Search.CollatorDSO;Extended Properties='Application=Windows';"
            )
            # 验证连接可用
            rs = conn.Execute(
                "SELECT TOP 1 System.ItemPathDisplay FROM SystemIndex"
            )[0]
            rs.Close()
            self._conn = conn
            self._available = True
        except Exception:
            _logger.debug("Windows Search 不可用，回退到 os.walk", exc_info=True)
            self._available = False
        return self._available

    def search_files(self, keyword: str, max_results: int = 250) -> list[tuple[str, float]]:
        """按文件名搜索，返回 (路径, 修改时间) 列表。

        参数:
            keyword: 文件名关键词。
            max_results: 最大结果数。

        返回:
            (路径, mtime) 元组列表。
        """
        if not self.available():
            return []
        try:
            kw = keyword.replace("'", "''")
            sql = (
                f"SELECT TOP {max_results} "
                f"System.ItemPathDisplay, System.DateModified "
                f"FROM SystemIndex "
                f"WHERE CONTAINS(System.ItemNameDisplay, '\"{kw}*\"') "
                f"ORDER BY System.DateModified DESC"
            )
            rs = self._conn.Execute(sql)[0]
            results: list[tuple[str, float]] = []
            while not rs.EOF:
                path = rs.Fields.Item(0).Value or ""
                mod_time = rs.Fields.Item(1).Value
                if path:
                    # 将 COM 日期转为 timestamp
                    try:
                        mtime = float(mod_time) if mod_time else 0.0
                    except (TypeError, ValueError):
                        mtime = 0.0
                    results.append((path, mtime))
                rs.MoveNext()
            rs.Close()
            return results
        except Exception:
            _logger.debug("Windows Search 文件名查询失败", exc_info=True)
            return []

    def search_content(
        self, keyword: str, max_results: int = 250
    ) -> list[str]:
        """按内容搜索，返回匹配的文件路径列表。

        参数:
            keyword: 搜索关键词。
            max_results: 最大结果数。

        返回:
            匹配的文件路径列表。
        """
        if not self.available():
            return []
        try:
            kw = keyword.replace("'", "''")
            sql = (
                f"SELECT TOP {max_results} System.ItemPathDisplay "
                f"FROM SystemIndex "
                f"WHERE CONTAINS(System.Search.Contents, '\"{kw}\"') "
                f"ORDER BY System.DateModified DESC"
            )
            rs = self._conn.Execute(sql)[0]
            results: list[str] = []
            while not rs.EOF:
                path = rs.Fields.Item(0).Value or ""
                if path and path not in results:
                    results.append(path)
                rs.MoveNext()
            rs.Close()
            return results
        except Exception:
            _logger.debug("Windows Search 内容查询失败", exc_info=True)
            return []


# 全局懒实例
_ws_backend = _WindowsSearchBackend()
T = TypeVar("T")
_TYPE_GLOB_MAP = {
    "py": ("*.py", "*.pyi"),
    "python": ("*.py", "*.pyi"),
    "js": ("*.js", "*.jsx", "*.mjs", "*.cjs"),
    "ts": ("*.ts", "*.tsx", "*.mts", "*.cts"),
    "tsx": ("*.tsx",),
    "jsx": ("*.jsx",),
    "json": ("*.json",),
    "md": ("*.md", "*.mdx"),
    "markdown": ("*.md", "*.mdx"),
    "go": ("*.go",),
    "rs": ("*.rs",),
    "rust": ("*.rs",),
    "java": ("*.java",),
    "sh": ("*.sh", "*.bash"),
    "yaml": ("*.yaml", "*.yml"),
    "yml": ("*.yaml", "*.yml"),
    "toml": ("*.toml",),
    "sql": ("*.sql",),
    "html": ("*.html", "*.htm"),
    "css": ("*.css", "*.scss", "*.sass"),
}


def _normalize_pattern(pattern: str) -> str:
    return pattern.strip().replace("\\", "/")


def _match_glob(rel_path: str, name: str, pattern: str) -> bool:
    normalized = _normalize_pattern(pattern)
    if not normalized:
        return False
    if "/" in normalized or normalized.startswith("**"):
        return PurePosixPath(rel_path).match(normalized)
    return fnmatch.fnmatch(name, normalized)


def _is_binary(raw: bytes) -> bool:
    if b"\x00" in raw:
        return True
    sample = raw[:4096]
    if not sample:
        return False
    non_text = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return (non_text / len(sample)) > 0.2


def _paginate(items: list[T], limit: int | None, offset: int) -> tuple[list[T], bool]:
    if limit is None:
        return items[offset:], False
    sliced = items[offset : offset + limit]
    truncated = len(items) > offset + limit
    return sliced, truncated


def _pagination_note(limit: int | None, offset: int, truncated: bool) -> str | None:
    if truncated:
        if limit is None:
            return f"(pagination: offset={offset})"
        return f"(pagination: limit={limit}, offset={offset})"
    if offset > 0:
        return f"(pagination: offset={offset})"
    return None


def _matches_type(name: str, file_type: str | None) -> bool:
    if not file_type:
        return True
    lowered = file_type.strip().lower()
    if not lowered:
        return True
    patterns = _TYPE_GLOB_MAP.get(lowered, (f"*.{lowered}",))
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in patterns)


class _SearchTool(_FsTool):
    _IGNORE_DIRS = set(ListDirTool._IGNORE_DIRS)

    def _display_path(self, target: Path, root: Path) -> str:
        if self._workspace:
            try:
                return target.relative_to(self._workspace).as_posix()
            except ValueError:
                pass
        return target.relative_to(root).as_posix()

    def _iter_files(self, root: Path) -> Iterable[Path]:
        if root.is_file():
            yield root
            return

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in self._IGNORE_DIRS)
            current = Path(dirpath)
            for filename in sorted(filenames):
                yield current / filename

    def _iter_entries(
        self,
        root: Path,
        *,
        include_files: bool,
        include_dirs: bool,
    ) -> Iterable[Path]:
        if root.is_file():
            if include_files:
                yield root
            return

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in self._IGNORE_DIRS)
            current = Path(dirpath)
            if include_dirs:
                for dirname in dirnames:
                    yield current / dirname
            if include_files:
                for filename in sorted(filenames):
                    yield current / filename


class GlobTool(_SearchTool):
    """按 glob 模式查找文件或目录。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "glob"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return (
            "Find files matching a glob pattern (e.g. '*.py', 'tests/**/test_*.py'). "
            "Results are sorted by modification time (newest first). "
            "Skips .git, node_modules, __pycache__, and other noise directories."
        )

    @property
    def read_only(self) -> bool:
        """声明该工具为只读工具。

        返回:
            恒为 ``True``。
        """
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        """返回工具参数 Schema。

        返回:
            glob 工具参数定义字典。
        """
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match, e.g. '*.py' or 'tests/**/test_*.py'",
                    "minLength": 1,
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search from (default '.')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Legacy alias for head_limit",
                    "minimum": 1,
                    "maximum": 1000,
                },
                "head_limit": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default 250)",
                    "minimum": 0,
                    "maximum": 1000,
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip the first N matching entries before returning results",
                    "minimum": 0,
                    "maximum": 100000,
                },
                "entry_type": {
                    "type": "string",
                    "enum": ["files", "dirs", "both"],
                    "description": "Whether to match files, directories, or both (default files)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        max_results: int | None = None,
        head_limit: int | None = None,
        offset: int = 0,
        entry_type: str = "files",
        **kwargs: Any,
    ) -> str:
        """执行 glob 搜索。

        参数:
            pattern: glob 模式。
            path: 搜索起点目录。
            max_results: 旧版结果上限别名。
            head_limit: 当前结果上限。
            offset: 结果偏移量。
            entry_type: 搜索文件、目录或两者。
            **kwargs: 兼容额外参数。

        返回:
            搜索结果文本。
        """
        try:
            root = self._resolve(path or ".")
            if not root.exists():
                return f"Error: Path not found: {path}"
            if not root.is_dir():
                return f"Error: Not a directory: {path}"

            if head_limit is not None:
                limit = None if head_limit == 0 else head_limit
            elif max_results is not None:
                limit = max_results
            else:
                limit = _DEFAULT_HEAD_LIMIT

            normalized = _normalize_pattern(pattern)
            matches: list[tuple[str, float]] = []

            # Windows Search 快速路径：简单文件名模式且搜索文件时
            if (
                _ws_backend.available()
                and "/" not in normalized
                and not normalized.startswith("**")
                and entry_type == "files"
            ):
                keyword = self._glob_to_keyword(pattern)
                if keyword:
                    ws_results = _ws_backend.search_files(
                        keyword, max_results=limit * 2 if limit else 500,
                    )
                    root_str = str(root)
                    root_prefix = root_str.rstrip("\\") + "\\"
                    # 用户指定了具体路径时，只返回该路径下的结果
                    # 未指定时（默认工作区），搜索全盘，返回绝对路径
                    scope_filter = path and path not in (".", "")
                    for ws_path, mtime in ws_results:
                        if ws_path == root_str:
                            continue
                        name = os.path.basename(ws_path)
                        if not fnmatch.fnmatch(name, pattern):
                            continue
                        if scope_filter:
                            if not ws_path.startswith(root_prefix):
                                continue
                            try:
                                rel = os.path.relpath(ws_path, root_str).replace("\\", "/")
                            except ValueError:
                                continue
                            matches.append((rel, mtime))
                        else:
                            matches.append((ws_path, mtime))
                    if matches:
                        matches.sort(key=lambda item: (-item[1], item[0]))
                        ordered = [name for name, _ in matches]
                        paged, truncated = _paginate(ordered, limit, offset)
                        result = "\n".join(paged)
                        if note := _pagination_note(limit, offset, truncated):
                            result += f"\n\n{note}"
                        return result

            # 兜底：os.walk 遍历
            include_files = entry_type in {"files", "both"}
            include_dirs = entry_type in {"dirs", "both"}
            for entry in self._iter_entries(
                root,
                include_files=include_files,
                include_dirs=include_dirs,
            ):
                rel_path = entry.relative_to(root).as_posix()
                if _match_glob(rel_path, entry.name, pattern):
                    display = self._display_path(entry, root)
                    if entry.is_dir():
                        display += "/"
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        mtime = 0.0
                    matches.append((display, mtime))

            if not matches:
                return f"No paths matched pattern '{pattern}' in {path}"

            matches.sort(key=lambda item: (-item[1], item[0]))
            ordered = [name for name, _ in matches]
            paged, truncated = _paginate(ordered, limit, offset)
            result = "\n".join(paged)
            if note := _pagination_note(limit, offset, truncated):
                result += f"\n\n{note}"
            return result
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error finding files: {e}"

    @staticmethod
    def _glob_to_keyword(pattern: str) -> str | None:
        """从简单 glob 模式中提取搜索关键词。

        参数:
            pattern: glob 模式，如 ``*.py`` 或 ``test_*.json``。

        返回:
            提取的关键词，无法提取时返回 ``None``。
        """
        # 去掉 * 和 ? 通配符，保留字面部分
        parts = re.split(r"[\*\?]", pattern)
        keyword = "".join(parts).strip(". ")
        return keyword if keyword else None


class GrepTool(_SearchTool):
    """按正则或纯文本搜索文件内容。"""
    _MAX_RESULT_CHARS = 128_000
    _MAX_FILE_BYTES = 2_000_000

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "grep"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return (
            "Search file contents with a regex pattern. "
            "Default output_mode is files_with_matches (file paths only); "
            "use content mode for matching lines with context. "
            "Skips binary and files >2 MB. Supports glob/type filtering."
        )

    @property
    def read_only(self) -> bool:
        """声明该工具为只读工具。

        返回:
            恒为 ``True``。
        """
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        """返回工具参数 Schema。

        返回:
            grep 工具参数定义字典。
        """
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex or plain text pattern to search for",
                    "minLength": 1,
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search in (default '.')",
                },
                "glob": {
                    "type": "string",
                    "description": "Optional file filter, e.g. '*.py' or 'tests/**/test_*.py'",
                },
                "type": {
                    "type": "string",
                    "description": "Optional file type shorthand, e.g. 'py', 'ts', 'md', 'json'",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default false)",
                },
                "fixed_strings": {
                    "type": "boolean",
                    "description": "Treat pattern as plain text instead of regex (default false)",
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": (
                        "content: matching lines with optional context; "
                        "files_with_matches: only matching file paths; "
                        "count: matching line counts per file. "
                        "Default: files_with_matches"
                    ),
                },
                "context_before": {
                    "type": "integer",
                    "description": "Number of lines of context before each match",
                    "minimum": 0,
                    "maximum": 20,
                },
                "context_after": {
                    "type": "integer",
                    "description": "Number of lines of context after each match",
                    "minimum": 0,
                    "maximum": 20,
                },
                "max_matches": {
                    "type": "integer",
                    "description": (
                        "Legacy alias for head_limit in content mode"
                    ),
                    "minimum": 1,
                    "maximum": 1000,
                },
                "max_results": {
                    "type": "integer",
                    "description": (
                        "Legacy alias for head_limit in files_with_matches or count mode"
                    ),
                    "minimum": 1,
                    "maximum": 1000,
                },
                "head_limit": {
                    "type": "integer",
                    "description": (
                        "Maximum number of results to return. In content mode this limits "
                        "matching line blocks; in other modes it limits file entries. "
                        "Default 250"
                    ),
                    "minimum": 0,
                    "maximum": 1000,
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip the first N results before applying head_limit",
                    "minimum": 0,
                    "maximum": 100000,
                },
            },
            "required": ["pattern"],
        }

    @staticmethod
    def _format_block(
        display_path: str,
        lines: list[str],
        match_line: int,
        before: int,
        after: int,
    ) -> str:
        start = max(1, match_line - before)
        end = min(len(lines), match_line + after)
        block = [f"{display_path}:{match_line}"]
        for line_no in range(start, end + 1):
            marker = ">" if line_no == match_line else " "
            block.append(f"{marker} {line_no}| {lines[line_no - 1]}")
        return "\n".join(block)

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        type: str | None = None,
        case_insensitive: bool = False,
        fixed_strings: bool = False,
        output_mode: str = "files_with_matches",
        context_before: int = 0,
        context_after: int = 0,
        max_matches: int | None = None,
        max_results: int | None = None,
        head_limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> str:
        """执行内容搜索。

        参数:
            pattern: 搜索模式。
            path: 搜索起点。
            glob: 文件 glob 过滤。
            type: 文件类型过滤。
            case_insensitive: 是否忽略大小写。
            fixed_strings: 是否按纯文本匹配。
            output_mode: 输出模式。
            context_before: 前置上下文行数。
            context_after: 后置上下文行数。
            max_matches: content 模式下的旧版上限别名。
            max_results: files/count 模式下的旧版上限别名。
            head_limit: 当前结果上限。
            offset: 结果偏移量。
            **kwargs: 兼容额外参数。

        返回:
            搜索结果文本。
        """
        try:
            target = self._resolve(path or ".")
            if not target.exists():
                return f"Error: Path not found: {path}"
            if not (target.is_dir() or target.is_file()):
                return f"Error: Unsupported path: {path}"

            flags = re.IGNORECASE if case_insensitive else 0
            try:
                needle = re.escape(pattern) if fixed_strings else pattern
                regex = re.compile(needle, flags)
            except re.error as e:
                return f"Error: invalid regex pattern: {e}"

            if head_limit is not None:
                limit = None if head_limit == 0 else head_limit
            elif output_mode == "content" and max_matches is not None:
                limit = max_matches
            elif output_mode != "content" and max_results is not None:
                limit = max_results
            else:
                limit = _DEFAULT_HEAD_LIMIT
            blocks: list[str] = []
            result_chars = 0
            seen_content_matches = 0
            truncated = False
            size_truncated = False
            skipped_binary = 0
            skipped_large = 0
            matching_files: list[str] = []
            counts: dict[str, int] = {}
            file_mtimes: dict[str, float] = {}
            root = target if target.is_dir() else target.parent

            # Windows Search 快速路径：files_with_matches 模式，无 glob/type 限制
            if (
                _ws_backend.available()
                and output_mode == "files_with_matches"
                and not glob
                and not type
                and target.is_dir()
            ):
                ws_paths = _ws_backend.search_content(
                    pattern, max_results=limit * 3 if limit else 750,
                )
                root_str = str(root)
                root_prefix = root_str.rstrip("\\") + "\\"
                for ws_path in ws_paths:
                    if ws_path == root_str:
                        continue
                    if not ws_path.startswith(root_prefix):
                        continue
                    try:
                        fp = Path(ws_path)
                        raw = fp.read_bytes()
                    except (OSError, PermissionError):
                        continue
                    if len(raw) > self._MAX_FILE_BYTES:
                        skipped_large += 1
                        continue
                    if _is_binary(raw):
                        skipped_binary += 1
                        continue
                    try:
                        content = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        skipped_binary += 1
                        continue
                    if regex.search(content):
                        rel = os.path.relpath(ws_path, root_str).replace("\\", "/")
                        if rel not in matching_files:
                            matching_files.append(rel)
                            try:
                                file_mtimes[rel] = fp.stat().st_mtime
                            except OSError:
                                file_mtimes[rel] = 0.0
                    if limit is not None and len(matching_files) >= limit:
                        truncated = True
                        break

                if matching_files:
                    notes: list[str] = []
                    # 收集本地 mtime 并按与 os.walk 相同规则排序
                    for mf in list(matching_files):
                        try:
                            file_mtimes[mf] = (root / mf).stat().st_mtime
                        except OSError:
                            file_mtimes[mf] = 0.0
                    ordered_files = sorted(
                        matching_files,
                        key=lambda name: (-file_mtimes.get(name, 0.0), name),
                    )
                    paged, truncated = _paginate(ordered_files, limit, offset)
                    result = "\n".join(paged)
                    if truncated:
                        notes.append(f"(pagination: limit={limit}, offset={offset})")
                    if skipped_binary:
                        notes.append(f"(skipped {skipped_binary} binary/unreadable files)")
                    if skipped_large:
                        notes.append(f"(skipped {skipped_large} large files)")
                    if notes:
                        result += "\n\n" + "\n".join(notes)
                    return result
                # 无匹配则回退到 os.walk

            for file_path in self._iter_files(target):
                rel_path = file_path.relative_to(root).as_posix()
                if glob and not _match_glob(rel_path, file_path.name, glob):
                    continue
                if not _matches_type(file_path.name, type):
                    continue

                raw = file_path.read_bytes()
                if len(raw) > self._MAX_FILE_BYTES:
                    skipped_large += 1
                    continue
                if _is_binary(raw):
                    skipped_binary += 1
                    continue
                try:
                    mtime = file_path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    skipped_binary += 1
                    continue

                lines = content.splitlines()
                display_path = self._display_path(file_path, root)
                file_had_match = False
                for idx, line in enumerate(lines, start=1):
                    if not regex.search(line):
                        continue
                    file_had_match = True

                    if output_mode == "count":
                        counts[display_path] = counts.get(display_path, 0) + 1
                        continue
                    if output_mode == "files_with_matches":
                        if display_path not in matching_files:
                            matching_files.append(display_path)
                            file_mtimes[display_path] = mtime
                        break

                    seen_content_matches += 1
                    if seen_content_matches <= offset:
                        continue
                    if limit is not None and len(blocks) >= limit:
                        truncated = True
                        break
                    block = self._format_block(
                        display_path,
                        lines,
                        idx,
                        context_before,
                        context_after,
                    )
                    extra_sep = 2 if blocks else 0
                    if result_chars + extra_sep + len(block) > self._MAX_RESULT_CHARS:
                        size_truncated = True
                        break
                    blocks.append(block)
                    result_chars += extra_sep + len(block)
                if output_mode == "count" and file_had_match:
                    if display_path not in matching_files:
                        matching_files.append(display_path)
                        file_mtimes[display_path] = mtime
                if output_mode in {"count", "files_with_matches"} and file_had_match:
                    continue
                if truncated or size_truncated:
                    break

            if output_mode == "files_with_matches":
                if not matching_files:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    ordered_files = sorted(
                        matching_files,
                        key=lambda name: (-file_mtimes.get(name, 0.0), name),
                    )
                    paged, truncated = _paginate(ordered_files, limit, offset)
                    result = "\n".join(paged)
            elif output_mode == "count":
                if not counts:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    ordered_files = sorted(
                        matching_files,
                        key=lambda name: (-file_mtimes.get(name, 0.0), name),
                    )
                    ordered, truncated = _paginate(ordered_files, limit, offset)
                    lines = [f"{name}: {counts[name]}" for name in ordered]
                    result = "\n".join(lines)
            else:
                if not blocks:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    result = "\n\n".join(blocks)

            notes: list[str] = []
            if output_mode == "content" and truncated:
                notes.append(
                    f"(pagination: limit={limit}, offset={offset})"
                )
            elif output_mode == "content" and size_truncated:
                notes.append("(output truncated due to size)")
            elif truncated and output_mode in {"count", "files_with_matches"}:
                notes.append(
                    f"(pagination: limit={limit}, offset={offset})"
                )
            elif output_mode in {"count", "files_with_matches"} and offset > 0:
                notes.append(f"(pagination: offset={offset})")
            elif output_mode == "content" and offset > 0 and blocks:
                notes.append(f"(pagination: offset={offset})")
            if skipped_binary:
                notes.append(f"(skipped {skipped_binary} binary/unreadable files)")
            if skipped_large:
                notes.append(f"(skipped {skipped_large} large files)")
            if output_mode == "count" and counts:
                notes.append(
                    f"(total matches: {sum(counts.values())} in {len(counts)} files)"
                )
            if notes:
                result += "\n\n" + "\n".join(notes)
            return result
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error searching files: {e}"
