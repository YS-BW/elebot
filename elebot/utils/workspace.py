"""工作区模板与初始化相关工具。"""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """把内置模板同步到工作区。

    参数:
        workspace: 工作区根目录。
        silent: 是否静默跳过终端输出。

    返回:
        本次新增的相对路径列表。
    """
    from importlib.resources import files as pkg_files

    try:
        tpl = pkg_files("elebot") / "templates" / "workspace"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path) -> None:
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md") and not item.name.startswith("."):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "history.jsonl")

    if added and not silent:
        from rich.console import Console

        for name in added:
            Console().print(f"  [dim]已创建 {name}[/dim]")

    try:
        from elebot.utils.gitstore import GitStore

        git_store = GitStore(
            workspace,
            tracked_files=["SOUL.md", "USER.md", "memory/MEMORY.md"],
        )
        git_store.init()
    except Exception:
        logger.warning("Failed to initialize git store for {}", workspace)

    return added
