"""全局 Skill 扫描与 metadata 解析。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from elebot.config.paths import GLOBAL_SKILLS_DIR, get_skill_usage_log_path


@dataclass(slots=True)
class SkillMetadata:
    """描述注入到提示词中的 Skill 元数据。"""

    name: str
    description: str


@dataclass(slots=True)
class SkillSpec:
    """表示一个可供 Agent 发现的全局 Skill。"""

    key: str
    root: Path
    skill_file: Path
    metadata: SkillMetadata


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
        if not self.root.exists() or not self.root.is_dir():
            return []

        skill_specs: list[SkillSpec] = []
        for skill_dir in sorted(self.root.iterdir(), key=lambda item: item.name):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            metadata = self._parse_metadata(skill_dir.name, skill_file.read_text(encoding="utf-8"))
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
            包含启用状态、键名、展示名和描述的字典列表。
        """
        discovered = self._discover_all()
        items: list[dict[str, Any]] = []
        for skill_dir in discovered:
            skill_file = skill_dir / "SKILL.md"
            metadata = self._parse_metadata(skill_dir.name, skill_file.read_text(encoding="utf-8"))
            items.append(
                {
                    "key": skill_dir.name,
                    "name": metadata.name,
                    "description": metadata.description,
                    "skill_file": skill_file,
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
        payload = {
            "skill": skill.key,
            "name": skill.metadata.name,
            "description": skill.metadata.description,
            "channel": channel or "",
            "chat_id": chat_id or "",
            "trigger": trigger,
        }
        log_path = get_skill_usage_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def uninstall(self, skill_key: str) -> tuple[bool, str]:
        """卸载指定 skill，并同步清理配置引用。

        参数:
            skill_key: 目标 skill 键名。

        返回:
            ``(是否成功, 提示文本)``。
        """
        import shutil

        skill_dir = self.root / skill_key
        if not skill_dir.exists():
            return False, f"找不到 skill：`{skill_key}`。"
        if not (skill_dir / "SKILL.md").is_file():
            return False, f"`{skill_key}` 不是合法 skill 目录。"

        shutil.rmtree(skill_dir)
        return True, f"已卸载 skill：`{skill_key}`。"

    def _discover_all(self) -> list[Path]:
        """返回所有带 ``SKILL.md`` 的 skill 目录。"""
        if not self.root.exists() or not self.root.is_dir():
            return []
        skill_dirs: list[Path] = []
        for skill_dir in sorted(self.root.iterdir(), key=lambda item: item.name):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                skill_dirs.append(skill_dir)
        return skill_dirs

    @staticmethod
    def _parse_metadata(skill_key: str, content: str) -> SkillMetadata:
        """从 ``SKILL.md`` 中解析 name 与 description。

        参数:
            skill_key: Skill 目录名。
            content: ``SKILL.md`` 全文。

        返回:
            仅包含 ``name`` 与 ``description`` 的元数据对象。
        """
        name = skill_key
        description = ""

        frontmatter = SkillRegistry._extract_frontmatter(content)
        if not frontmatter:
            return SkillMetadata(name=name, description=description)

        for raw_line in frontmatter.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            normalized_key = key.strip().lower()
            normalized_value = value.strip().strip("\"'")
            if normalized_key == "name" and normalized_value:
                name = normalized_value
            elif normalized_key == "description" and normalized_value:
                description = normalized_value
        return SkillMetadata(name=name, description=description)

    @staticmethod
    def _extract_frontmatter(content: str) -> str:
        """提取文件开头的 frontmatter。

        参数:
            content: ``SKILL.md`` 全文。

        返回:
            frontmatter 文本；不存在时返回空字符串。
        """
        if not content.startswith("---"):
            return ""

        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            return ""

        collected: list[str] = []
        for line in lines[1:]:
            if line.strip() == "---":
                return "\n".join(collected)
            collected.append(line)
        return ""
