"""CLI 主命令测试。"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from elebot.bus.events import OutboundMessage
from elebot.cli.app import app
from elebot.cli.onboard import _try_auto_fill_context_window
from elebot.cli.runtime_support import _make_provider
from elebot.config.schema import Config
from elebot.providers.registry import find_by_name

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """移除终端 ANSI 控制符，方便断言纯文本输出。"""
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


@pytest.fixture
def mock_paths():
    """隔离 onboard 使用的配置和工作区路径。"""
    with (
        patch("elebot.config.loader.get_config_path") as mock_cp,
        patch("elebot.config.loader.save_config") as mock_sc,
        patch("elebot.config.loader.load_config") as mock_lc,
        patch("elebot.cli.commands.onboard.get_workspace_path") as mock_ws,
    ):
        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_lc.side_effect = lambda _config_path=None: Config()

        def _save_config(config: Config, config_path: Path | None = None) -> None:
            target = config_path or config_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(config.model_dump(by_alias=True)),
                encoding="utf-8",
            )

        mock_sc.side_effect = _save_config

        yield config_file, workspace_dir, mock_ws

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths) -> None:
    """首次初始化会创建配置和工作区模板。"""
    config_file, workspace_dir, mock_ws = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "已创建配置文件" in result.stdout
    assert "已创建工作区" in result.stdout
    assert "elebot 已就绪" in result.stdout
    assert "获取地址：https://platform.deepseek.com/" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()
    assert mock_ws.call_args.args == (Config().workspace_path,)


def test_onboard_existing_config_refresh(mock_paths) -> None:
    """拒绝覆盖时应保留原值并刷新缺省字段。"""
    config_file, workspace_dir, _ = mock_paths
    config_file.write_text('{"existing": true}', encoding="utf-8")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "配置文件已存在" in result.stdout
    assert "已刷新配置并保留现有值" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_config_overwrite(mock_paths) -> None:
    """确认覆盖时应重置为默认配置。"""
    config_file, workspace_dir, _ = mock_paths
    config_file.write_text('{"existing": true}', encoding="utf-8")

    result = runner.invoke(app, ["onboard"], input="y\n")

    assert result.exit_code == 0
    assert "已将配置重置为默认值" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths) -> None:
    """工作区已存在时不重复创建，但仍会补齐模板。"""
    config_file, workspace_dir, _ = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "已创建工作区" not in result.stdout
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_help_shows_workspace_and_config_options() -> None:
    """onboard 帮助信息应暴露当前支持的核心参数。"""
    result = runner.invoke(app, ["onboard", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "--config" in stripped_output
    assert "--wizard" in stripped_output


def test_root_help_shows_only_current_commands() -> None:
    """根帮助页只展示当前保留的命令面。"""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "onboard" in stripped_output
    assert "agent" in stripped_output
    assert "status" in stripped_output
    assert "gateway" not in stripped_output
    assert "serve" not in stripped_output
    assert "channels" not in stripped_output
    assert "plugins" not in stripped_output


def test_onboard_interactive_discard_does_not_save_or_create_workspace(
    mock_paths, monkeypatch
) -> None:
    """向导放弃保存时不应落盘任何文件。"""
    config_file, workspace_dir, _ = mock_paths

    from elebot.cli.onboard import OnboardResult

    monkeypatch.setattr(
        "elebot.cli.onboard.run_onboard",
        lambda initial_config: OnboardResult(config=initial_config, should_save=False),
    )

    result = runner.invoke(app, ["onboard", "--wizard"])

    assert result.exit_code == 0
    assert "未保存任何变更" in result.stdout
    assert not config_file.exists()
    assert not workspace_dir.exists()


def test_onboard_uses_explicit_config_and_workspace_paths(tmp_path, monkeypatch) -> None:
    """显式配置路径和工作区路径应写回最终配置。"""
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    result = runner.invoke(
        app,
        ["onboard", "--config", str(config_path), "--workspace", str(workspace_path)],
    )

    assert result.exit_code == 0
    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.workspace_path == workspace_path
    assert (workspace_path / "AGENTS.md").exists()
    compact_output = _strip_ansi(result.stdout).replace("\n", "")
    resolved_config = str(config_path.resolve())
    assert f"--config {resolved_config}" in compact_output


def test_onboard_wizard_preserves_explicit_config_in_next_steps(tmp_path, monkeypatch) -> None:
    """向导模式结束后应继续提示正确的显式配置路径。"""
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    from elebot.cli.onboard import OnboardResult

    monkeypatch.setattr(
        "elebot.cli.onboard.run_onboard",
        lambda initial_config: OnboardResult(config=initial_config, should_save=True),
    )

    result = runner.invoke(
        app,
        ["onboard", "--wizard", "--config", str(config_path), "--workspace", str(workspace_path)],
    )

    assert result.exit_code == 0
    compact_output = _strip_ansi(result.stdout).replace("\n", "")
    resolved_config = str(config_path.resolve())
    assert f'elebot agent -m "你好！" --config {resolved_config}' in compact_output


def test_config_dump_excludes_oauth_provider_blocks() -> None:
    """已移除 provider 字段不应出现在默认导出结果里。"""
    config = Config()

    providers = config.model_dump(by_alias=True)["providers"]

    assert "openaiCodex" not in providers
    assert "githubCopilot" not in providers


def test_make_provider_rejects_unknown_forced_provider(capsys) -> None:
    """CLI 构造 provider 时也应把未知 provider 作为用户错误暴露。"""
    config = Config()
    config.agents.defaults.provider = "missing-provider"

    with pytest.raises(typer.Exit):
        _make_provider(config)

    captured = capsys.readouterr()
    assert "Unknown provider configured: missing-provider" in captured.out


def test_find_by_name_accepts_camel_case_and_hyphen_aliases() -> None:
    """provider 注册表别名解析应保持可用。"""
    assert find_by_name("volcengineCodingPlan") is not None
    assert find_by_name("volcengineCodingPlan").name == "volcengine_coding_plan"
    assert find_by_name("azure-openai") is not None
    assert find_by_name("azure-openai").name == "azure_openai"


@pytest.fixture
def mock_agent_runtime(tmp_path):
    """隔离 agent 命令依赖，只测试命令装配行为。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "default-workspace")

    with (
        patch("elebot.config.loader.load_config", return_value=config) as mock_load_config,
        patch("elebot.config.loader.resolve_config_env_vars", side_effect=lambda c: c),
        patch("elebot.cli.commands.agent.sync_workspace_templates") as mock_sync_templates,
        patch("elebot.cli.runtime_support._make_provider", return_value=object()),
        patch("elebot.cli.commands.agent.print_agent_response") as mock_print_response,
        patch("elebot.cli.runtime_support.MessageBus"),
        patch("elebot.cli.runtime_support.AgentLoop") as mock_agent_loop_cls,
    ):
        agent_loop = MagicMock()
        agent_loop.process_direct = AsyncMock(
            return_value=OutboundMessage(channel="cli", chat_id="direct", content="mock-response"),
        )
        agent_loop.close_mcp = AsyncMock(return_value=None)
        mock_agent_loop_cls.return_value = agent_loop

        yield {
            "config": config,
            "load_config": mock_load_config,
            "sync_templates": mock_sync_templates,
            "agent_loop_cls": mock_agent_loop_cls,
            "agent_loop": agent_loop,
            "print_response": mock_print_response,
        }


def test_agent_help_shows_workspace_and_config_options() -> None:
    """agent 帮助页应保留当前支持的核心参数。"""
    result = runner.invoke(app, ["agent", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "--config" in stripped_output


def test_agent_uses_default_config_when_no_workspace_or_config_flags(mock_agent_runtime) -> None:
    """未显式覆盖时应使用默认配置装配 agent。"""
    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (None,)
    assert mock_agent_runtime["sync_templates"].call_args.args == (
        mock_agent_runtime["config"].workspace_path,
    )
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == (
        mock_agent_runtime["config"].workspace_path
    )
    mock_agent_runtime["agent_loop"].process_direct.assert_awaited_once()
    mock_agent_runtime["print_response"].assert_called_once_with(
        "mock-response", render_markdown=True, metadata={},
    )


def test_agent_uses_explicit_config_path(mock_agent_runtime, tmp_path: Path) -> None:
    """显式配置路径应传给 load_config。"""
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)


def test_agent_config_sets_active_path(monkeypatch, tmp_path: Path) -> None:
    """agent 命令应把显式配置路径设置为当前活动路径。"""
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}", encoding="utf-8")

    config = Config()
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        "elebot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("elebot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("elebot.cli.commands.agent.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("elebot.cli.runtime_support._make_provider", lambda _config: object())
    monkeypatch.setattr("elebot.cli.runtime_support.MessageBus", lambda: object())

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        def stop(self) -> None:
            return None

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("elebot.cli.runtime_support.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("elebot.cli.commands.agent.print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_file.resolve()


def test_agent_overrides_workspace_path(mock_agent_runtime) -> None:
    """显式工作区路径应覆盖配置值。"""
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(app, ["agent", "-m", "hello", "-w", str(workspace_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == workspace_path


def test_agent_workspace_override_wins_over_config_workspace(
    mock_agent_runtime, tmp_path: Path
) -> None:
    """同时传入配置和工作区时，以命令行工作区为准。"""
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}", encoding="utf-8")
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(
        app,
        ["agent", "-m", "hello", "-c", str(config_path), "-w", str(workspace_path)],
    )

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)


def test_agent_hints_about_deprecated_memory_window(mock_agent_runtime, tmp_path) -> None:
    """旧配置键仍会收到清理提示，但不再真正生效。"""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"agents": {"defaults": {"memoryWindow": 42}}}), encoding="utf-8")

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert "memoryWindow" in result.stdout
    assert "no longer used" in result.stdout


def test_agent_rejects_removed_top_level_config_keys(tmp_path: Path) -> None:
    """旧配置仍带 Frozen 顶层字段时应直接提示清理。"""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "providers": {"dashscope": {"apiKey": "still-there"}},
                "channels": {"sendProgress": True},
                "api": {"host": "127.0.0.1"},
                "gateway": {"host": "0.0.0.0"},
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 1
    stripped_output = _strip_ansi(result.stdout)
    assert "已移除的顶层字段: channels, api, gateway" in stripped_output
    assert "删除这些字段后重试" in stripped_output
    assert "No API key configured" not in stripped_output


def test_status_reports_basic_runtime_state(monkeypatch, tmp_path: Path) -> None:
    """status 命令应输出配置、工作区和模型状态。"""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.providers.dashscope.api_key = "test-key"

    monkeypatch.setattr("elebot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("elebot.config.loader.load_config", lambda: config)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "Config:" in stripped
    assert "Workspace:" in stripped
    assert "Model:" in stripped


def test_onboard_auto_fills_context_window_via_model_catalog(monkeypatch) -> None:
    """向导应通过模型目录推荐上下文窗口。"""
    defaults = Config().agents.defaults
    defaults.model = "qwen3_6_plus"
    defaults.provider = "dashscope"

    monkeypatch.setattr(
        "elebot.cli.onboard.get_model_context_limit",
        lambda model, provider: 1_000_000 if (model, provider) == ("qwen3_6_plus", "dashscope") else None,
    )

    _try_auto_fill_context_window(defaults, "qwen3_6_plus")

    assert defaults.context_window_tokens == 1_000_000


def test_onboard_does_not_auto_fill_context_window_for_unsupported_provider(monkeypatch) -> None:
    """未覆盖的 provider 不应强行写入推荐窗口。"""
    defaults = Config().agents.defaults
    defaults.model = "llama3.2"
    defaults.provider = "ollama"

    monkeypatch.setattr("elebot.cli.onboard.get_model_context_limit", lambda *_args, **_kwargs: None)

    _try_auto_fill_context_window(defaults, "llama3.2")

    assert defaults.context_window_tokens == 65_536
