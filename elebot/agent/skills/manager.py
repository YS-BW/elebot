"""Skill 文件系统管理。"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
from dulwich import porcelain

from elebot.config.paths import GLOBAL_SKILLS_DIR
from elebot.utils.fs import ensure_dir

ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)
GITHUB_HOSTS = {"github.com", "www.github.com"}
COMMON_GIT_HOSTS = {
    "github.com",
    "www.github.com",
    "gitlab.com",
    "www.gitlab.com",
    "bitbucket.org",
    "www.bitbucket.org",
}


class SkillManager:
    """负责处理 Skill 目录级管理动作。"""

    def __init__(self, root: Path | None = None):
        """初始化 Skill 管理器。

        参数:
            root: Skill 根目录；为空时使用 ``~/.elebot/skills``。

        返回:
            无返回值。
        """
        self.root = (root or GLOBAL_SKILLS_DIR).expanduser()

    def install(self, source: str) -> tuple[bool, str]:
        """安装指定来源的 skill。

        参数:
            source: 本地目录、下载链接或 Git 链接。

        返回:
            ``(是否成功, 提示文本)``。
        """
        source_text = source.strip()
        if not source_text:
            return False, "请提供 skill 来源。"

        ensure_dir(self.root)
        local_path = Path(source_text).expanduser()
        if local_path.exists():
            try:
                skill_dir = self._resolve_local_skill_dir(local_path)
            except Exception as exc:
                return False, str(exc)

            skill_key = skill_dir.name
            target_dir = self.root / skill_key
            if self._target_exists(target_dir):
                return (
                    False,
                    f"skill 已存在：`{skill_key}`。请先执行 `/skill uninstall {skill_key}`。",
                )

            self._install_local_skill_dir(skill_dir, target_dir)
            return True, f"已安装 skill：`{skill_key}`。"

        with tempfile.TemporaryDirectory(prefix="elebot-skill-") as temp_dir:
            staging_root = Path(temp_dir)
            try:
                skill_dir = self._materialize_skill_dir(source_text, staging_root)
            except Exception as exc:
                return False, str(exc)

            skill_key = skill_dir.name
            target_dir = self.root / skill_key
            if self._target_exists(target_dir):
                return (
                    False,
                    f"skill 已存在：`{skill_key}`。请先执行 `/skill uninstall {skill_key}`。",
                )

            shutil.copytree(skill_dir, target_dir)
            return True, f"已安装 skill：`{skill_key}`。"

    def uninstall(self, skill_key: str) -> tuple[bool, str]:
        """卸载指定 skill。

        参数:
            skill_key: 目标 skill 键名。

        返回:
            ``(是否成功, 提示文本)``。
        """
        skill_dir = self.root / skill_key
        if not skill_dir.exists() and not skill_dir.is_symlink():
            return False, f"找不到 skill：`{skill_key}`。"
        if skill_dir.is_symlink():
            skill_dir.unlink()
            return True, f"已卸载 skill：`{skill_key}`。"
        if not (skill_dir / "SKILL.md").is_file():
            return False, f"`{skill_key}` 不是合法 skill 目录。"

        shutil.rmtree(skill_dir)
        return True, f"已卸载 skill：`{skill_key}`。"

    def _resolve_local_skill_dir(self, source_dir: Path) -> Path:
        """解析并校验本地来源目录。

        参数:
            source_dir: 用户给出的本地目录。

        返回:
            校验通过后的 skill 根目录。
        """
        if not source_dir.is_dir():
            raise ValueError("本地来源必须是目录，不能直接传 `SKILL.md` 文件。")
        return self._require_skill_dir(source_dir, "本地目录")

    def _target_exists(self, target_dir: Path) -> bool:
        """判断目标 skill 路径是否已经被占用。

        参数:
            target_dir: 目标安装目录。

        返回:
            已存在文件、目录或符号链接时返回 ``True``。
        """
        return target_dir.exists() or target_dir.is_symlink()

    def _should_link_local_skill(self) -> bool:
        """判断本地 skill 安装是否应优先使用符号链接。

        参数:
            无。

        返回:
            非 Windows 平台返回 ``True``，Windows 返回 ``False``。
        """
        return os.name != "nt"

    def _install_local_skill_dir(self, source_dir: Path, target_dir: Path) -> None:
        """按平台策略安装本地 skill 目录。

        参数:
            source_dir: 已校验的本地 skill 目录。
            target_dir: 目标安装路径。

        返回:
            无返回值。
        """
        if self._should_link_local_skill():
            target_dir.symlink_to(source_dir.resolve(), target_is_directory=True)
            return
        shutil.copytree(source_dir, target_dir)

    def _materialize_skill_dir(self, source: str, staging_root: Path) -> Path:
        """将来源解析成一个可复制的合法 skill 目录。

        参数:
            source: 原始来源字符串。
            staging_root: 临时工作目录。

        返回:
            已解析出的 skill 目录路径。
        """
        github_tree = self._parse_github_tree_source(source)
        if github_tree is not None:
            return self._materialize_github_tree_source(
                repo_url=github_tree[0],
                branch=github_tree[1],
                subdir=github_tree[2],
                staging_root=staging_root,
            )

        if self._is_git_source(source):
            return self._materialize_git_source(source, staging_root)

        if self._is_http_url(source):
            return self._materialize_archive_source(source, staging_root)

        raise ValueError(
            f"不支持的 skill 来源：`{source}`。请提供本地目录、下载链接或 git 链接。"
        )

    def _materialize_archive_source(self, source: str, staging_root: Path) -> Path:
        """下载并解压压缩包来源。

        参数:
            source: 下载链接。
            staging_root: 临时工作目录。

        返回:
            已解析出的唯一 skill 目录路径。
        """
        archive_path = self._download_archive(source, staging_root)
        extract_root = staging_root / "extract"
        extract_root.mkdir(parents=True, exist_ok=True)
        try:
            shutil.unpack_archive(str(archive_path), str(extract_root))
        except (shutil.ReadError, ValueError) as exc:
            raise ValueError(
                "下载链接不是受支持的压缩包，或内容无法解压成单个 skill 目录。"
            ) from exc
        return self._find_unique_skill_dir(extract_root)

    def _materialize_git_source(self, source: str, staging_root: Path) -> Path:
        """拉取 Git 仓库并校验根目录就是 skill。

        参数:
            source: Git 仓库地址。
            staging_root: 临时工作目录。

        返回:
            仓库根目录对应的 skill 路径。
        """
        repo_root = staging_root / "repo"
        self._clone_git_repo(source, repo_root, branch=None)
        return self._require_skill_dir(repo_root, "Git 仓库根目录")

    def _materialize_github_tree_source(
        self,
        *,
        repo_url: str,
        branch: str,
        subdir: Path,
        staging_root: Path,
    ) -> Path:
        """拉取 GitHub tree 链接指向的子目录。

        参数:
            repo_url: 仓库克隆地址。
            branch: 目标分支。
            subdir: 仓库内 skill 子目录。
            staging_root: 临时工作目录。

        返回:
            子目录对应的 skill 路径。
        """
        repo_root = staging_root / "repo"
        self._clone_git_repo(repo_url, repo_root, branch=branch)
        skill_dir = repo_root / subdir
        if not skill_dir.exists():
            raise ValueError(f"Git 来源里找不到目录：`{subdir.as_posix()}`。")
        return self._require_skill_dir(skill_dir, "Git 子目录")

    def _download_archive(self, source: str, staging_root: Path) -> Path:
        """下载远端压缩包到临时目录。

        参数:
            source: 下载链接。
            staging_root: 临时工作目录。

        返回:
            本地压缩包路径。
        """
        archive_name = Path(urlparse(source).path).name or "skill-download"
        archive_path = staging_root / archive_name
        try:
            with httpx.Client(follow_redirects=True, timeout=30.0) as client:
                response = client.get(source)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"下载 skill 失败：{exc}") from exc

        archive_path.write_bytes(response.content)
        return archive_path

    def _clone_git_repo(self, source: str, target_dir: Path, branch: str | None) -> None:
        """克隆远端仓库到临时目录。

        参数:
            source: 仓库地址。
            target_dir: 目标目录。
            branch: 指定分支；为空时使用远端默认分支。

        返回:
            无返回值。
        """
        try:
            porcelain.clone(
                source=source,
                target=str(target_dir),
                checkout=True,
                depth=1,
                branch=branch,
                errstream=io.BytesIO(),
                outstream=io.BytesIO(),
            )
        except Exception as exc:
            raise ValueError(f"拉取 Git skill 失败：{exc}") from exc

    def _require_skill_dir(self, skill_dir: Path, source_label: str) -> Path:
        """校验目录根是否为合法 skill。

        参数:
            skill_dir: 待校验目录。
            source_label: 提示信息中的来源说明。

        返回:
            校验通过后的原目录路径。
        """
        if not (skill_dir / "SKILL.md").is_file():
            raise ValueError(f"{source_label}缺少 `SKILL.md`，不是合法 skill 目录。")
        return skill_dir

    def _find_unique_skill_dir(self, root: Path) -> Path:
        """在解压目录里查找唯一 skill 目录。

        参数:
            root: 解压后的根目录。

        返回:
            唯一命中的 skill 目录路径。
        """
        candidates: dict[str, Path] = {}
        for skill_file in root.rglob("SKILL.md"):
            skill_dir = skill_file.parent
            candidates[str(skill_dir.resolve())] = skill_dir

        skill_dirs = sorted(candidates.values(), key=lambda item: str(item))
        if not skill_dirs:
            raise ValueError("下载内容里没有发现合法 skill 目录。")
        if len(skill_dirs) > 1:
            raise ValueError("下载内容包含多个 skill 目录，无法自动选择。")
        return skill_dirs[0]

    def _parse_github_tree_source(self, source: str) -> tuple[str, str, Path] | None:
        """解析 GitHub tree 链接。

        参数:
            source: 原始来源字符串。

        返回:
            ``(repo_url, branch, subdir)``；不是 GitHub tree 链接时返回 ``None``。
        """
        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"} or parsed.netloc not in GITHUB_HOSTS:
            return None

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 5 or parts[2] != "tree":
            return None

        owner, repo_name, _, branch = parts[:4]
        subdir = Path(*parts[4:])
        repo_path = f"/{owner}/{repo_name.removesuffix('.git')}.git"
        repo_url = urlunparse((parsed.scheme, parsed.netloc, repo_path, "", "", ""))
        return repo_url, branch, subdir

    def _is_git_source(self, source: str) -> bool:
        """判断来源是否应按 Git 仓库处理。

        参数:
            source: 原始来源字符串。

        返回:
            是否是受支持的 Git 来源。
        """
        if source.startswith(("git@", "ssh://", "git://")):
            return True

        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"}:
            return False
        if self._parse_github_tree_source(source) is not None:
            return False
        if self._looks_like_archive_path(parsed.path):
            return False

        path_parts = [part for part in parsed.path.split("/") if part]
        return parsed.netloc in COMMON_GIT_HOSTS and len(path_parts) >= 2

    def _is_http_url(self, source: str) -> bool:
        """判断来源是否是 HTTP 下载链接。

        参数:
            source: 原始来源字符串。

        返回:
            是否为 HTTP 或 HTTPS 链接。
        """
        parsed = urlparse(source)
        return parsed.scheme in {"http", "https"}

    def _looks_like_archive_path(self, path: str) -> bool:
        """判断 URL 路径是否像受支持的压缩包。

        参数:
            path: URL 路径部分。

        返回:
            是否命中已知压缩包后缀。
        """
        lowered_path = path.lower()
        return any(lowered_path.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)
