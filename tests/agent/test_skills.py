"""全局 Skill 注册表与管理器测试。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from elebot.agent.skills import SkillManager, SkillRegistry


def _write_skill(root: Path, key: str, content: str) -> Path:
    """创建测试用 skill 文件。"""
    skill_dir = root / key
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def _make_zip_archive(tmp_path: Path, source_root: Path, archive_name: str) -> Path:
    """将测试目录打包成 zip 压缩包。"""
    archive_base = tmp_path / archive_name
    archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=source_root)
    return Path(archive_path)


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


def test_install_local_skill_and_registry_scan_updates(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_skill(source_root, "demo", "---\nname: Demo\ndescription: 本地测试\n---\n")
    skills_root = tmp_path / "skills"

    manager = SkillManager(skills_root)
    ok, message = manager.install(str(source_root / "demo"))

    assert ok is True
    assert "已安装 skill" in message
    installed_skill = skills_root / "demo" / "SKILL.md"
    assert installed_skill.exists()

    registry = SkillRegistry(skills_root)
    assert [item.key for item in registry.scan()] == ["demo"]


def test_install_local_skill_requires_skill_md(tmp_path) -> None:
    source_dir = tmp_path / "source" / "broken"
    source_dir.mkdir(parents=True)

    ok, message = SkillManager(tmp_path / "skills").install(str(source_dir))

    assert ok is False
    assert "SKILL.md" in message


def test_install_download_archive_succeeds(tmp_path, monkeypatch) -> None:
    archive_root = tmp_path / "archive-root"
    archive_root.mkdir()
    _write_skill(
        archive_root,
        "skill-creator",
        "---\nname: Skill Creator\ndescription: 生成 skill\n---\n",
    )
    archive_path = _make_zip_archive(tmp_path, archive_root, "skill-download")

    monkeypatch.setattr(
        SkillManager,
        "_download_archive",
        lambda self, source, staging_root: archive_path,
    )

    skills_root = tmp_path / "skills"
    ok, message = SkillManager(skills_root).install("https://example.com/skill-download.zip")

    assert ok is True
    assert "已安装 skill：`skill-creator`" in message
    assert (skills_root / "skill-creator" / "SKILL.md").exists()


def test_install_github_tree_skill_succeeds(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "repo-source"
    skill_dir = repo_root / "plugins" / "skill-creator"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Skill Creator\ndescription: 生成 skill\n---\n",
        encoding="utf-8",
    )
    clone_calls: dict[str, str | None] = {}

    def _fake_clone_repo(self, source: str, target_dir: Path, branch: str | None) -> None:
        clone_calls["source"] = source
        clone_calls["branch"] = branch
        shutil.copytree(repo_root, target_dir)

    monkeypatch.setattr(SkillManager, "_clone_git_repo", _fake_clone_repo)

    url = "https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator"
    ok, message = SkillManager(tmp_path / "skills").install(url)

    assert ok is True
    assert "已安装 skill：`skill-creator`" in message
    assert clone_calls == {
        "source": "https://github.com/anthropics/claude-plugins-official.git",
        "branch": "main",
    }
    assert (tmp_path / "skills" / "skill-creator" / "SKILL.md").exists()


def test_install_rejects_existing_skill(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "demo", "---\nname: Demo\n---\n")
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_skill(source_root, "demo", "---\nname: Demo\n---\n")

    ok, message = SkillManager(skills_root).install(str(source_root / "demo"))

    assert ok is False
    assert "请先执行 `/skill uninstall demo`" in message


def test_install_rejects_ambiguous_archive(tmp_path, monkeypatch) -> None:
    archive_root = tmp_path / "archive-root"
    archive_root.mkdir()
    _write_skill(archive_root, "skill-a", "---\nname: A\n---\n")
    _write_skill(archive_root, "skill-b", "---\nname: B\n---\n")
    archive_path = _make_zip_archive(tmp_path, archive_root, "skill-multi")

    monkeypatch.setattr(
        SkillManager,
        "_download_archive",
        lambda self, source, staging_root: archive_path,
    )

    ok, message = SkillManager(tmp_path / "skills").install("https://example.com/skill-multi.zip")

    assert ok is False
    assert "多个 skill 目录" in message


def test_uninstall_removes_skill_and_registry_scan_updates(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "demo", "---\nname: Demo\n---\n")
    manager = SkillManager(skills_root)

    ok, message = manager.uninstall("demo")

    assert ok is True
    assert "已卸载 skill" in message
    assert SkillRegistry(skills_root).scan() == []


def test_uninstall_missing_skill_fails(tmp_path) -> None:
    ok, message = SkillManager(tmp_path / "skills").uninstall("missing")

    assert ok is False
    assert "找不到 skill" in message


def test_install_download_archive_without_skill_fails(tmp_path, monkeypatch) -> None:
    archive_root = tmp_path / "archive-root"
    archive_root.mkdir()
    (archive_root / "notes.txt").write_text("not a skill", encoding="utf-8")
    archive_path = _make_zip_archive(tmp_path, archive_root, "not-skill")

    monkeypatch.setattr(
        SkillManager,
        "_download_archive",
        lambda self, source, staging_root: archive_path,
    )

    ok, message = SkillManager(tmp_path / "skills").install("https://example.com/not-skill.zip")

    assert ok is False
    assert "没有发现合法 skill 目录" in message


def test_install_local_file_path_rejected(tmp_path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("# not allowed\n", encoding="utf-8")

    ok, message = SkillManager(tmp_path / "skills").install(str(skill_file))

    assert ok is False
    assert "不能直接传 `SKILL.md` 文件" in message
