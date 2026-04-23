"""加载并整理 Agent 可见技能。"""

import json
import os
import re
import shutil
from pathlib import Path

# 默认内置技能目录，按当前文件位置解析。
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# 提取标准 frontmatter，兼容独占行的 `---` 和 CRLF 换行。
_STRIP_SKILL_FRONTMATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)


def _escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SkillsLoader:
    """负责发现、读取和汇总技能文件。"""

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None, disabled_skills: set[str] | None = None):
        """初始化技能加载器。

        参数:
            workspace: 当前工作区目录。
            builtin_skills_dir: 内置技能目录；为空时使用默认目录。
            disabled_skills: 需要过滤掉的技能名称集合。

        返回:
            None
        """
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.disabled_skills = disabled_skills or set()

    def _skill_entries_from_dir(self, base: Path, source: str, *, skip_names: set[str] | None = None) -> list[dict[str, str]]:
        if not base.exists():
            return []
        entries: list[dict[str, str]] = []
        for skill_dir in base.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            name = skill_dir.name
            if skip_names is not None and name in skip_names:
                continue
            entries.append({"name": name, "path": str(skill_file), "source": source})
        return entries

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """列出当前可见的技能清单。

        参数:
            filter_unavailable: 为真时过滤掉依赖条件未满足的技能。

        返回:
            由技能名称、路径和来源组成的字典列表。
        """
        skills = self._skill_entries_from_dir(self.workspace_skills, "workspace")
        workspace_names = {entry["name"] for entry in skills}
        if self.builtin_skills and self.builtin_skills.exists():
            skills.extend(
                self._skill_entries_from_dir(self.builtin_skills, "builtin", skip_names=workspace_names)
            )

        if self.disabled_skills:
            skills = [s for s in skills if s["name"] not in self.disabled_skills]

        if filter_unavailable:
            return [skill for skill in skills if self._check_requirements(self._get_skill_meta(skill["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """按名称读取技能正文。

        参数:
            name: 技能目录名称。

        返回:
            读取到的技能 Markdown 文本；不存在时返回 `None`。
        """
        roots = [self.workspace_skills]
        if self.builtin_skills:
            roots.append(self.builtin_skills)
        for root in roots:
            path = root / name / "SKILL.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """读取指定技能并整理成可注入上下文的文本。

        参数:
            skill_names: 需要加载的技能名称列表。

        返回:
            适合直接注入系统提示词的技能文本。
        """
        parts = [
            f"### Skill: {name}\n\n{self._strip_frontmatter(markdown)}"
            for name in skill_names
            if (markdown := self.load_skill(name))
        ]
        return "\n\n---\n\n".join(parts)

    def build_skills_summary(self) -> str:
        """构造全部技能的摘要视图。

        参数:
            无。

        返回:
            供渐进式加载使用的 XML 摘要文本；无技能时返回空字符串。
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        lines: list[str] = ["<skills>"]
        for entry in all_skills:
            skill_name = entry["name"]
            meta = self._get_skill_meta(skill_name)
            available = self._check_requirements(meta)
            lines.extend(
                [
                    f'  <skill available="{str(available).lower()}">',
                    f"    <name>{_escape_xml(skill_name)}</name>",
                    f"    <description>{_escape_xml(self._get_skill_description(skill_name))}</description>",
                    f"    <location>{entry['path']}</location>",
                ]
            )
            if not available:
                missing = self._get_missing_requirements(meta)
                if missing:
                    lines.append(f"    <requires>{_escape_xml(missing)}</requires>")
            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        requires = skill_meta.get("requires", {})
        required_bins = requires.get("bins", [])
        required_env_vars = requires.get("env", [])
        return ", ".join(
            [f"CLI: {command_name}" for command_name in required_bins if not shutil.which(command_name)]
            + [f"ENV: {env_name}" for env_name in required_env_vars if not os.environ.get(env_name)]
        )

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # 描述缺失时退回技能名，至少保证摘要仍可读。

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return content
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if match:
            return content[match.end():].strip()
        return content

    def _parse_elebot_metadata(self, raw: str) -> dict:
        """Parse skill metadata JSON from frontmatter (supports elebot and openclaw keys)."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        payload = data.get("elebot", data.get("openclaw", {}))
        return payload if isinstance(payload, dict) else {}

    def _check_requirements(self, skill_meta: dict) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        requires = skill_meta.get("requires", {})
        required_bins = requires.get("bins", [])
        required_env_vars = requires.get("env", [])
        return all(shutil.which(cmd) for cmd in required_bins) and all(
            os.environ.get(var) for var in required_env_vars
        )

    def _get_skill_meta(self, name: str) -> dict:
        """Get elebot metadata for a skill (cached in frontmatter)."""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_elebot_metadata(meta.get("metadata", ""))

    def get_always_skills(self) -> list[str]:
        """返回默认总是启用且依赖满足的技能名称列表。

        参数:
            无。

        返回:
            需要自动注入上下文的技能名称列表。
        """
        return [
            entry["name"]
            for entry in self.list_skills(filter_unavailable=True)
            if (meta := self.get_skill_metadata(entry["name"]) or {})
            and (
                self._parse_elebot_metadata(meta.get("metadata", "")).get("always")
                or meta.get("always")
            )
        ]

    def get_skill_metadata(self, name: str) -> dict | None:
        """读取技能 frontmatter 元数据。

        参数:
            name: 技能名称。

        返回:
            解析后的元数据字典；缺失或格式不合法时返回 `None`。
        """
        content = self.load_skill(name)
        if not content or not content.startswith("---"):
            return None
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if not match:
            return None
        metadata: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"\'')
        return metadata
