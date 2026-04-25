from __future__ import annotations

from types import SimpleNamespace

import pytest

from elebot.bus.events import InboundMessage
from elebot.command.builtin import build_help_text, cmd_skill_manage
from elebot.command.router import CommandContext


def _make_ctx(raw: str = "/skill") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, loop=SimpleNamespace())


@pytest.mark.asyncio
async def test_skill_command_lists_skills(monkeypatch) -> None:
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
        "elebot.command.builtin.SkillRegistry",
        lambda: _FakeRegistry(),
    )

    out = await cmd_skill_manage(_make_ctx())
    assert "## Skills" in out.content
    assert "`minimax-docx` minimax-docx" in out.content
    assert "`release-note` Release Note" in out.content


def test_help_text_contains_skills_command() -> None:
    help_text = build_help_text()
    assert "/skill" in help_text


@pytest.mark.asyncio
async def test_skill_manage_uninstall(monkeypatch) -> None:
    class _FakeRegistry:
        def uninstall(self, skill_key: str):
            return True, f"已卸载 skill：`{skill_key}`。"

    monkeypatch.setattr(
        "elebot.command.builtin.SkillRegistry",
        lambda: _FakeRegistry(),
    )

    ctx = _make_ctx("/skill uninstall demo")
    ctx.args = "uninstall demo"
    out = await cmd_skill_manage(ctx)
    assert "已卸载 skill" in out.content


@pytest.mark.asyncio
async def test_skill_manage_invalid_usage(monkeypatch) -> None:
    class _FakeRegistry:
        pass

    monkeypatch.setattr(
        "elebot.command.builtin.SkillRegistry",
        lambda: _FakeRegistry(),
    )

    ctx = _make_ctx("/skill invalid")
    ctx.args = "invalid"
    out = await cmd_skill_manage(ctx)
    assert "用法：" in out.content or "不支持的 skill 操作" in out.content
