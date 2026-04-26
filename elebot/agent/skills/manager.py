"""Skill 文件系统管理。"""

from __future__ import annotations

import shutil
from pathlib import Path

from elebot.config.paths import GLOBAL_SKILLS_DIR


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

    def uninstall(self, skill_key: str) -> tuple[bool, str]:
        """卸载指定 skill。

        参数:
            skill_key: 目标 skill 键名。

        返回:
            ``(是否成功, 提示文本)``。
        """
        skill_dir = self.root / skill_key
        if not skill_dir.exists():
            return False, f"找不到 skill：`{skill_key}`。"
        if not (skill_dir / "SKILL.md").is_file():
            return False, f"`{skill_key}` 不是合法 skill 目录。"

        shutil.rmtree(skill_dir)
        return True, f"已卸载 skill：`{skill_key}`。"
