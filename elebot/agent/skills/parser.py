"""Skill Markdown 解析逻辑。"""

from __future__ import annotations

from elebot.agent.skills.models import SkillMetadata


def extract_frontmatter(content: str) -> str:
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


def parse_skill_metadata(skill_key: str, content: str) -> SkillMetadata:
    """从 ``SKILL.md`` 中解析 name 与 description。

    参数:
        skill_key: Skill 目录名。
        content: ``SKILL.md`` 全文。

    返回:
        仅包含 ``name`` 与 ``description`` 的元数据对象。
    """
    name = skill_key
    description = ""

    frontmatter = extract_frontmatter(content)
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
