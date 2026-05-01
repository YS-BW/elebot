"""工作区模板初始化测试。"""

from __future__ import annotations

from pathlib import Path

from elebot.utils.workspace import sync_workspace_templates


def test_sync_workspace_templates_uses_workspace_subdir(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    added = sync_workspace_templates(workspace, silent=True)

    assert "AGENTS.md" in added
    assert "SOUL.md" in added
    assert "USER.md" in added
    assert "TOOLS.md" in added
    assert "memory/MEMORY.md" in added
    assert "memory/history.jsonl" in added
    assert (workspace / "AGENTS.md").is_file()
    assert (workspace / "SOUL.md").is_file()
    assert (workspace / "USER.md").is_file()
    assert (workspace / "TOOLS.md").is_file()
    assert (workspace / "memory" / "MEMORY.md").is_file()
    assert (workspace / "memory" / "history.jsonl").is_file()
