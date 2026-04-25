"""全局 Skill 注册表测试。"""

import json
from pathlib import Path

from elebot.agent.skills import SkillRegistry


def _write_skill(root: Path, key: str, content: str) -> Path:
    """创建测试用 skill 文件。"""
    skill_dir = root / key
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def test_scan_returns_only_dirs_with_skill_md(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    _write_skill(
        skills_root,
        "git-commit",
        "---\nname: Git Commit\ndescription: 整理提交\n---\n\n# body\n",
    )
    (skills_root / "broken").mkdir()

    registry = SkillRegistry(skills_root)
    skills = registry.scan()

    assert [item.key for item in skills] == ["git-commit"]


def test_frontmatter_parses_name_and_description_only(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    _write_skill(
        skills_root,
        "release-note",
        (
            "---\n"
            "name: Release Note\n"
            "description: 生成发布说明\n"
            "homepage: https://example.com\n"
            "metadata: ignored\n"
            "---\n\n"
            "# body\n"
        ),
    )

    skill = SkillRegistry(skills_root).scan()[0]
    assert skill.metadata.name == "Release Note"
    assert skill.metadata.description == "生成发布说明"


def test_missing_frontmatter_falls_back_to_directory_name(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    _write_skill(skills_root, "api-debug", "# API Debug\n")

    skill = SkillRegistry(skills_root).scan()[0]
    assert skill.metadata.name == "api-debug"
    assert skill.metadata.description == ""


def test_build_prompt_summary_contains_metadata_not_body(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    skill_file = _write_skill(
        skills_root,
        "api-debug",
        "---\nname: API Debug\ndescription: 排查接口错误\n---\n\n# API Debug\n\nsecret body\n",
    )

    summary = SkillRegistry(skills_root).build_prompt_summary()
    assert "# 可用 Skills" in summary
    assert "API Debug" in summary
    assert "排查接口错误" in summary
    assert str(skill_file) in summary
    assert "secret body" not in summary


def test_record_usage_writes_jsonl_log(tmp_path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    _write_skill(
        skills_root,
        "docx",
        "---\nname: DOCX\ndescription: 处理文档\n---\n",
    )
    log_path = tmp_path / "logs" / "skill_usage.jsonl"
    monkeypatch.setattr("elebot.agent.skills.get_skill_usage_log_path", lambda: log_path)

    registry = SkillRegistry(skills_root)
    skill = registry.scan()[0]
    registry.record_usage(skill, channel="cli", chat_id="direct", trigger="explicit")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["skill"] == "docx"
    assert payload["trigger"] == "explicit"


def test_uninstall_removes_directory_and_config_refs(tmp_path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    skill_file = _write_skill(skills_root, "demo", "---\nname: Demo\n---\n")

    ok, message = SkillRegistry(skills_root).uninstall("demo")
    assert ok is True
    assert "已卸载 skill" in message
    assert not skill_file.exists()
