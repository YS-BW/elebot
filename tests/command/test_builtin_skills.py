from __future__ import annotations

from types import SimpleNamespace

import pytest

from elebot.bus.events import InboundMessage
from elebot.command.builtin import build_help_text, register_builtin_commands
from elebot.command.handlers.skills import cmd_skill_manage
from elebot.command.router import CommandContext, CommandRouter


def _make_ctx(raw: str) -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, loop=SimpleNamespace())


@pytest.mark.asyncio
async def test_skill_command_lists_installed_skills(monkeypatch) -> None:
    fake_items = [
        {
            "key": "minimax-docx",
            "name": "minimax-docx",
            "description": "处理 Word 文档",
            "skill_file": "/tmp/minimax-docx/SKILL.md",
        },
        {
            "key": "release-note",
            "name": "Release Note",
            "description": "生成发布说明",
            "skill_file": "/tmp/release-note/SKILL.md",
        },
    ]

    class _FakeRegistry:
        def list_status(self):
            return fake_items

    monkeypatch.setattr(
        "elebot.command.handlers.skills.SkillRegistry",
        lambda: _FakeRegistry(),
    )

    ctx = _make_ctx("/skill list")
    ctx.args = "list"
    out = await cmd_skill_manage(ctx)
    assert "## Skills" in out.content
    assert "`minimax-docx` minimax-docx" in out.content
    assert "`release-note` Release Note" in out.content


def test_help_text_contains_new_skills_commands() -> None:
    help_text = build_help_text()
    assert "/skill list" in help_text
    assert "/skill install <source>" in help_text
    assert "/skill uninstall <name>" in help_text
    assert "/skill —" not in help_text
    assert "/stop" not in help_text


@pytest.mark.asyncio
async def test_skill_manage_install_calls_manager(monkeypatch) -> None:
    install_calls: list[str] = []

    class _FakeManager:
        def install(self, source: str):
            install_calls.append(source)
            return True, f"已安装 skill：`{source}`。"

    monkeypatch.setattr(
        "elebot.command.handlers.skills.SkillManager",
        lambda: _FakeManager(),
    )

    ctx = _make_ctx('/skill install "/tmp/demo skill"')
    ctx.args = 'install "/tmp/demo skill"'
    out = await cmd_skill_manage(ctx)
    assert install_calls == ["/tmp/demo skill"]
    assert "已安装 skill" in out.content


@pytest.mark.asyncio
async def test_skill_manage_uninstall_calls_manager(monkeypatch) -> None:
    uninstall_calls: list[str] = []

    class _FakeManager:
        def uninstall(self, skill_key: str):
            uninstall_calls.append(skill_key)
            return True, f"已卸载 skill：`{skill_key}`。"

    monkeypatch.setattr(
        "elebot.command.handlers.skills.SkillManager",
        lambda: _FakeManager(),
    )

    ctx = _make_ctx("/skill uninstall demo")
    ctx.args = "uninstall demo"
    out = await cmd_skill_manage(ctx)
    assert uninstall_calls == ["demo"]
    assert "已卸载 skill" in out.content


@pytest.mark.asyncio
async def test_skill_manage_invalid_usage_returns_help() -> None:
    ctx = _make_ctx("/skill invalid")
    ctx.args = "invalid"
    out = await cmd_skill_manage(ctx)
    assert "/skill list" in out.content
    assert "/skill install <source>" in out.content
    assert "/skill uninstall <name>" in out.content


@pytest.mark.asyncio
async def test_bare_skill_command_is_not_registered() -> None:
    router = CommandRouter()
    register_builtin_commands(router)

    ctx = _make_ctx("/skill")
    result = await router.dispatch(ctx)

    assert result is None
