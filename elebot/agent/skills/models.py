"""Skill 子系统的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
