"""CLI 主命令测试。"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
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
    assert "获取地址：https://platform.xiaomimimo.com/console/api-keys" in result.stdout
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
    assert "channel" in stripped_output
    assert "status" in stripped_output
    assert "channels" not in stripped_output
    assert "serve" not in stripped_output
    assert "gateway" not in stripped_output
    assert "plugins" not in stripped_output


def test_root_help_localizes_builtin_completion_options() -> None:
    """根帮助页里的补全选项说明应为中文。"""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "为当前 shell 安装补全脚本" in stripped_output
    assert "显示当前 shell" in stripped_output
    assert "的补全脚本" in stripped_output


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


def test_agent_warns_when_default_config_file_is_missing(monkeypatch, tmp_path: Path) -> None:
    """默认配置文件缺失时应提示先运行 onboard。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    missing_config = tmp_path / "missing-config.json"

    monkeypatch.setattr("elebot.config.loader.get_config_path", lambda: missing_config)
    monkeypatch.setattr("elebot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("elebot.config.loader.resolve_config_env_vars", lambda loaded: loaded)
    monkeypatch.setattr("elebot.cli.commands.agent.sync_workspace_templates", lambda *_args, **_kwargs: None)
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

    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "未找到配置文件" in stripped
    assert "elebot onboard" in stripped


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
                "api": {"host": "127.0.0.1"},
                "gateway": {"host": "0.0.0.0"},
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 1
    stripped_output = _strip_ansi(result.stdout)
    assert "已移除的顶层字段: api, gateway" in stripped_output
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
    assert "Config" in stripped
    assert "Workspace" in stripped
    assert "Provider" in stripped
    assert "Model" in stripped
    assert "Timezone" in stripped
    assert "Channel Enabled" in stripped
    assert "Channel Owner" in stripped
    assert "Channel Running" in stripped
    assert "Channel Logged In" in stripped
    assert "Channel Uptime" in stripped
    assert "Channel Log" in stripped


def test_channel_login_invokes_weixin_login(monkeypatch) -> None:
    """channel login 应调用当前微信登录链。"""
    called: dict[str, object] = {}

    class _FakeChannel:
        def __init__(self, config, runtime) -> None:
            called["config"] = config
            called["runtime_has_bus"] = hasattr(runtime, "bus")

        async def login(self, force: bool = False) -> bool:
            called["force"] = force
            return True

    monkeypatch.setattr("elebot.cli.commands.weixin.load_config", lambda _path=None: Config())
    monkeypatch.setattr("elebot.cli.commands.weixin.resolve_config_env_vars", lambda config: config)
    monkeypatch.setattr("elebot.cli.commands.weixin.WeixinChannel", _FakeChannel)

    result = runner.invoke(app, ["channel", "login", "--force"])

    assert result.exit_code == 0
    assert called["runtime_has_bus"] is True
    assert called["force"] is True


def test_channel_without_subcommand_shows_help() -> None:
    """channel 裸调用时应直接展示帮助。"""
    result = runner.invoke(app, ["channel"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "Manage external channel service" in stripped
    assert "login" in stripped
    assert "run" in stripped
    assert "start" in stripped
    assert "log" in stripped
    assert "restart" in stripped
    assert "stop" in stripped


def test_channel_run_starts_channel_manager_with_logs(monkeypatch, tmp_path) -> None:
    """channel run 应复用 runtime 和 channel manager 启动当前启用的微信 channel。"""
    loaded_config = Config()
    loaded_config.channels.weixin.enabled = True
    state_dir = tmp_path / "weixin"
    state_dir.mkdir(parents=True)
    (state_dir / "account.json").write_text("{}", encoding="utf-8")
    loaded_config.channels.weixin.state_dir = str(state_dir)
    events: list[str] = []

    class _FakeRuntime:
        async def start(self) -> None:
            events.append("runtime.start")

        async def close(self) -> None:
            events.append("runtime.close")

    class _FakeManager:
        captured_config = None

        def __init__(self, config, runtime) -> None:
            del runtime
            type(self).captured_config = config

        async def start_all(self) -> None:
            events.append("manager.start_all")

        async def wait(self) -> None:
            events.append("manager.wait")

        async def stop_all(self) -> None:
            events.append("manager.stop_all")

    monkeypatch.setattr("elebot.cli.commands.weixin._load_runtime_config", lambda *_args, **_kwargs: loaded_config)
    monkeypatch.setattr("elebot.cli.commands.weixin.sync_workspace_templates", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("elebot.cli.commands.weixin._make_runtime", lambda *_args, **_kwargs: _FakeRuntime())
    monkeypatch.setattr("elebot.cli.commands.weixin.ChannelManager", _FakeManager)
    monkeypatch.setattr("elebot.cli.commands.weixin.logger.enable", lambda *_args, **_kwargs: events.append("logger.enable"))

    result = runner.invoke(app, ["channel", "run"])

    assert result.exit_code == 0
    assert events == [
        "logger.enable",
        "runtime.start",
        "manager.start_all",
        "manager.wait",
        "manager.stop_all",
        "runtime.close",
    ]
    assert _FakeManager.captured_config.channels.weixin.enabled is True


def test_channel_run_rejects_when_service_is_already_running(monkeypatch) -> None:
    """后台已运行时，channel run 应拒绝再起前台实例。"""
    monkeypatch.setattr("elebot.cli.commands.weixin.get_channel_service_state", lambda: ("running", 2468))

    result = runner.invoke(app, ["channel", "run"])

    assert result.exit_code == 2
    stripped = _strip_ansi(result.stdout + result.stderr)
    assert "channel service 已被 weixin 占用" in stripped
    assert "elebot channel stop" in stripped


def test_channel_run_requires_login_state(monkeypatch, tmp_path) -> None:
    """channel run 在没有登录态时，应直接给出明确提示。"""
    loaded_config = Config()
    loaded_config.channels.weixin.enabled = True
    loaded_config.channels.weixin.state_dir = str(tmp_path / "weixin")

    monkeypatch.setattr("elebot.cli.commands.weixin._load_runtime_config", lambda *_args, **_kwargs: loaded_config)
    monkeypatch.setattr("elebot.cli.commands.weixin.sync_workspace_templates", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["channel", "run"])

    assert result.exit_code == 2
    stripped = _strip_ansi(result.stdout + result.stderr)
    assert "weixin channel 已启用，但未找到可用登录态" in stripped
    assert "elebot channel login" in stripped


def test_channel_run_warns_when_default_config_file_is_missing(monkeypatch, tmp_path: Path) -> None:
    """channel run 在默认配置文件缺失时应提示先运行 onboard。"""
    loaded_config = Config()
    loaded_config.channels.weixin.enabled = True
    state_dir = tmp_path / "weixin"
    state_dir.mkdir(parents=True)
    (state_dir / "account.json").write_text("{}", encoding="utf-8")
    loaded_config.channels.weixin.state_dir = str(state_dir)
    missing_config = tmp_path / "missing-config.json"

    class _FakeRuntime:
        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

    class _FakeManager:
        def __init__(self, config, runtime) -> None:
            del config, runtime

        async def start_all(self) -> None:
            return None

        async def wait(self) -> None:
            return None

        async def stop_all(self) -> None:
            return None

    monkeypatch.setattr("elebot.config.loader.get_config_path", lambda: missing_config)
    monkeypatch.setattr("elebot.config.loader.load_config", lambda _path=None: loaded_config)
    monkeypatch.setattr("elebot.config.loader.resolve_config_env_vars", lambda config: config)
    monkeypatch.setattr("elebot.cli.commands.weixin.sync_workspace_templates", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("elebot.cli.commands.weixin._make_runtime", lambda *_args, **_kwargs: _FakeRuntime())
    monkeypatch.setattr("elebot.cli.commands.weixin.ChannelManager", _FakeManager)
    monkeypatch.setattr("elebot.cli.commands.weixin.logger.enable", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["channel", "run"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "未找到配置文件" in stripped
    assert "elebot onboard" in stripped


def test_channel_run_requires_enabled_channel(monkeypatch) -> None:
    """未启用 channel 时应直接失败退出。"""
    loaded_config = Config()

    monkeypatch.setattr("elebot.cli.commands.weixin._load_runtime_config", lambda *_args, **_kwargs: loaded_config)
    monkeypatch.setattr("elebot.cli.commands.weixin.sync_workspace_templates", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["channel", "run"])

    assert result.exit_code == 2
    stripped = _strip_ansi(result.stdout + result.stderr)
    assert "当前未启用 weixin channel" in stripped


def test_channel_start_spawns_background_process(monkeypatch, tmp_path: Path) -> None:
    """channel start 预检通过后应写 pid 并后台启动。"""
    loaded_config = Config()
    loaded_config.channels.weixin.enabled = True
    weixin_dir = tmp_path / "weixin"
    weixin_dir.mkdir(parents=True)
    (weixin_dir / "account.json").write_text("{}", encoding="utf-8")
    loaded_config.channels.weixin.state_dir = str(weixin_dir)
    pid_path = tmp_path / "channels-service.pid"
    log_path = tmp_path / "channels-service.log"
    captured: dict[str, object] = {}

    class _FakeProcess:
        pid = 43210

    def _fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr("elebot.cli.commands.weixin._load_runtime_config", lambda *_args, **_kwargs: loaded_config)
    monkeypatch.setattr("elebot.cli.commands.weixin.get_channel_service_state", lambda: ("stopped", None))
    monkeypatch.setattr("elebot.cli.commands.weixin._get_channel_service_pid_path", lambda: pid_path)
    monkeypatch.setattr("elebot.cli.commands.weixin._get_channel_service_log_path", lambda: log_path)
    monkeypatch.setattr("elebot.cli.commands.weixin.get_logs_dir", lambda: tmp_path)
    monkeypatch.setattr("elebot.cli.commands.weixin.subprocess.Popen", _fake_popen)

    result = runner.invoke(app, ["channel", "start"])

    assert result.exit_code == 0
    assert pid_path.read_text(encoding="utf-8") == "43210"
    assert captured["command"][:4] == [os.sys.executable, "-m", "elebot", "channel"]
    assert captured["command"][4] == "_serve_internal"
    assert "日志文件" in result.stdout


def test_channel_start_requires_login_state(monkeypatch, tmp_path: Path) -> None:
    """channel start 遇到缺微信登录态时应直接失败。"""
    loaded_config = Config()
    loaded_config.channels.weixin.enabled = True
    loaded_config.channels.weixin.state_dir = str(tmp_path / "weixin")

    monkeypatch.setattr("elebot.cli.commands.weixin._load_runtime_config", lambda *_args, **_kwargs: loaded_config)
    monkeypatch.setattr("elebot.cli.commands.weixin.get_channel_service_state", lambda: ("stopped", None))

    result = runner.invoke(app, ["channel", "start"])

    assert result.exit_code == 2
    stripped = _strip_ansi(result.stdout + result.stderr)
    assert "weixin channel 已启用，但未找到可用登录态" in stripped


def test_channel_start_reports_running_instance(monkeypatch) -> None:
    """channel start 遇到已存活实例时不应重复启动。"""
    monkeypatch.setattr("elebot.cli.commands.weixin.get_channel_service_state", lambda: ("running", 2468))

    result = runner.invoke(app, ["channel", "start"])

    assert result.exit_code == 0
    assert "已被 weixin 占用" in result.stdout


def test_channel_log_follows_existing_log_file(monkeypatch, tmp_path: Path) -> None:
    """channel log 应从现有日志文件实时输出。"""
    log_path = tmp_path / "channels-service.log"
    log_path.write_text("existing line\n", encoding="utf-8")

    monkeypatch.setattr("elebot.cli.commands.weixin._get_channel_service_log_path", lambda: log_path)

    calls = {"count": 0}

    def _fake_sleep(_seconds: float) -> None:
        calls["count"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr("elebot.cli.commands.weixin.time.sleep", _fake_sleep)

    result = runner.invoke(app, ["channel", "log"])

    assert result.exit_code == 0


def test_channel_log_requires_existing_log_file(monkeypatch, tmp_path: Path) -> None:
    """channel log 在日志文件不存在时应直接报错。"""
    log_path = tmp_path / "missing.log"
    monkeypatch.setattr("elebot.cli.commands.weixin._get_channel_service_log_path", lambda: log_path)

    result = runner.invoke(app, ["channel", "log"])

    assert result.exit_code == 2
    stripped = _strip_ansi(result.stdout + result.stderr)
    assert "日志文件不存在" in stripped


def test_channel_stop_terminates_running_process(monkeypatch, tmp_path: Path) -> None:
    """channel stop 应终止存活进程并清理 pid 文件。"""
    pid_path = tmp_path / "channels-service.pid"
    pid_path.write_text("2468", encoding="utf-8")
    seen: dict[str, object] = {}

    monkeypatch.setattr("elebot.cli.commands.weixin.get_channel_service_state", lambda: ("running", 2468))
    monkeypatch.setattr("elebot.cli.commands.weixin._get_channel_service_pid_path", lambda: pid_path)
    monkeypatch.setattr("elebot.cli.commands.weixin._wait_for_process_exit", lambda pid, timeout_seconds: True)
    monkeypatch.setattr("elebot.cli.commands.weixin.os.kill", lambda pid, sig: seen.update({"pid": pid, "sig": sig}))

    result = runner.invoke(app, ["channel", "stop"])

    assert result.exit_code == 0
    assert seen == {"pid": 2468, "sig": signal.SIGTERM}
    assert not pid_path.exists()


def test_channel_stop_cleans_stale_pid(monkeypatch, tmp_path: Path) -> None:
    """channel stop 遇到 stale pid 时应清理并提示。"""
    pid_path = tmp_path / "channels-service.pid"
    pid_path.write_text("9999", encoding="utf-8")

    monkeypatch.setattr("elebot.cli.commands.weixin.get_channel_service_state", lambda: ("stale", 9999))
    monkeypatch.setattr("elebot.cli.commands.weixin._get_channel_service_pid_path", lambda: pid_path)

    result = runner.invoke(app, ["channel", "stop"])

    assert result.exit_code == 0
    assert not pid_path.exists()
    assert "已失效" in result.stdout


def test_channel_restart_restarts_running_process(monkeypatch) -> None:
    """channel restart 遇到运行中实例时应先停再启。"""
    calls: list[tuple[str, object, object]] = []

    monkeypatch.setattr("elebot.cli.commands.weixin.get_channel_service_state", lambda: ("running", 2468))
    monkeypatch.setattr(
        "elebot.cli.commands.weixin._stop_weixin_service",
        lambda: calls.append(("stop", None, None)),
    )
    monkeypatch.setattr(
        "elebot.cli.commands.weixin._start_weixin_service",
        lambda config, workspace: calls.append(("start", config, workspace)),
    )

    result = runner.invoke(app, ["channel", "restart"])

    assert result.exit_code == 0
    assert calls == [("stop", None, None), ("start", None, None)]


def test_channel_restart_starts_when_stopped(monkeypatch) -> None:
    """channel restart 遇到未运行实例时应直接启动。"""
    calls: list[tuple[str, object, object]] = []

    monkeypatch.setattr("elebot.cli.commands.weixin.get_channel_service_state", lambda: ("stopped", None))
    monkeypatch.setattr(
        "elebot.cli.commands.weixin._start_weixin_service",
        lambda config, workspace: calls.append(("start", config, workspace)),
    )

    result = runner.invoke(app, ["channel", "restart"])

    assert result.exit_code == 0
    assert calls == [("start", None, None)]


def test_status_reports_channel_runtime_state(monkeypatch, tmp_path: Path) -> None:
    """status 应输出统一 channel 启用、登录、后台运行状态。"""
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    weixin_dir = tmp_path / "weixin"
    workspace.mkdir()
    weixin_dir.mkdir()
    state_path = weixin_dir / "account.json"
    state_path.write_text("{}", encoding="utf-8")

    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.provider = "xiaomi_mimo"
    config.agents.defaults.model = "mimo-v2.5"
    config.agents.defaults.timezone = "Asia/Shanghai"
    config.channels.weixin.enabled = True
    config.channels.weixin.state_dir = str(weixin_dir)

    monkeypatch.setattr("elebot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("elebot.config.loader.load_config", lambda: config)
    monkeypatch.setattr("elebot.cli.commands.status.get_channel_service_state", lambda: ("running", 1357))
    monkeypatch.setattr("elebot.cli.commands.status.list_channel_service_pids", lambda: [1357, 2468])
    monkeypatch.setattr(
        "elebot.cli.commands.status.Path.home",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "subprocess.check_output",
        lambda *args, **kwargs: "Thu May 01 12:00:00 2026",
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "Provider" in stripped
    assert "xiaomi_mimo" in stripped
    assert "Model" in stripped
    assert "mimo-v2.5" in stripped
    assert "Timezone" in stripped
    assert "Asia/Shanghai" in stripped
    assert "Channel Enabled" in stripped
    assert "Channel Owner" in stripped
    assert "Channel Running" in stripped
    assert "weixin" in stripped
    assert "Channel Logged In" in stripped
    assert "Channel Uptime" in stripped
    assert "Channel Log" in stripped


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
