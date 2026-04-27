"""全局 Skill 扫描与摘要生成。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from elebot.agent.skills.models import SkillSpec
from elebot.agent.skills.parser import parse_skill_metadata
from elebot.config.paths import GLOBAL_SKILLS_DIR


class SkillRegistry:
    """负责扫描全局 Skill 目录并生成提示词摘要。"""

    def __init__(
        self,
        root: Path | None = None,
    ):
        """初始化 Skill 注册表。

        参数:
            root: Skill 根目录；为空时使用 ``~/.elebot/skills``。

        返回:
            无返回值。
        """
        self.root = (root or GLOBAL_SKILLS_DIR).expanduser()

    def scan(self) -> list[SkillSpec]:
        """扫描全局 Skill 目录。

        返回:
            按目录名排序后的 Skill 列表。
        """
        skill_specs: list[SkillSpec] = []
        for skill_dir in self._discover_all():
            skill_file = skill_dir / "SKILL.md"
            metadata = parse_skill_metadata(
                skill_dir.name,
                skill_file.read_text(encoding="utf-8"),
            )
            skill_specs.append(
                SkillSpec(
                    key=skill_dir.name,
                    root=skill_dir,
                    skill_file=skill_file,
                    metadata=metadata,
                )
            )
        return skill_specs

    def build_prompt_summary(self) -> str:
        """生成注入 system prompt 的 Skill 摘要。

        返回:
            面向模型的 Skill 摘要文本；无 Skill 时返回空字符串。
        """
        skills = self.scan()
        if not skills:
            return ""

        lines = [
            "# 可用 Skills",
            "",
            "以下是当前可用的全局 skills。"
            "当用户请求与某个 skill 高度相关时，先读取对应 `SKILL.md`，"
            "再按其中说明决定是否继续读取 `template.md`、`examples/`、`references/`，"
            "或执行 `scripts/` 下的脚本。",
            "",
        ]
        for skill in skills:
            display_name = skill.metadata.name or skill.key
            description = skill.metadata.description or "暂无描述。"
            lines.append(
                f"- `{skill.key}`: {display_name}；{description}；读取路径：`{skill.skill_file}`"
            )
        return "\n".join(lines)

    def list_status(self) -> list[dict[str, Any]]:
        """返回当前 skill 状态列表，供命令展示。

        返回:
            包含键名、展示名、描述和主文件路径的字典列表。
        """
        items: list[dict[str, Any]] = []
        for skill in self.scan():
            items.append(
                {
                    "key": skill.key,
                    "name": skill.metadata.name,
                    "description": skill.metadata.description,
                    "skill_file": skill.skill_file,
                }
            )
        return items

    def record_usage(
        self,
        skill: SkillSpec,
        *,
        channel: str | None = None,
        chat_id: str | None = None,
        trigger: str = "model",
    ) -> None:
        """记录一次 skill 使用事件。

        参数:
            skill: 被使用的 Skill。
            channel: 消息来源通道。
            chat_id: 会话标识。
            trigger: 触发来源，默认 ``model``。

        返回:
            无返回值。
        """
        # 日志路径从 skills 包入口读取，保证测试和上层 monkeypatch
        # `elebot.agent.skills.get_skill_usage_log_path` 时能稳定生效。
        from elebot.agent import skills as skills_module

        payload = {
            "skill": skill.key,
            "name": skill.metadata.name,
            "description": skill.metadata.description,
            "channel": channel or "",
            "chat_id": chat_id or "",
            "trigger": trigger,
        }
        log_path = skills_module.get_skill_usage_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _discover_all(self) -> list[Path]:
        """返回所有带 ``SKILL.md`` 的 skill 目录。"""
        if not self.root.exists() or not self.root.is_dir():
            return []

        skill_dirs: list[Path] = []
        for skill_dir in sorted(self.root.iterdir(), key=lambda item: item.name):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                skill_dirs.append(skill_dir)
        return skill_dirs
