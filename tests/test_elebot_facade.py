"""公共 Python facade 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from elebot.agent.loop import DirectProcessResult
from elebot.facade import Elebot, RunResult


def _write_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    data = {
        "providers": {"dashscope": {"apiKey": "dashscope-test-key"}},
        "agents": {"defaults": {"model": "qwen3_6_plus"}},
    }
    if overrides:
        data.update(overrides)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data))
    return config_path


def test_from_config_missing_file():
    with pytest.raises(FileNotFoundError):
        Elebot.from_config("/nonexistent/config.json")


def test_from_config_creates_instance(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Elebot.from_config(config_path, workspace=tmp_path)
    assert bot._loop is not None
    assert bot._loop.workspace == tmp_path


def test_from_config_default_path():
    from elebot.config.schema import Config

    with patch("elebot.config.loader.load_config") as mock_load, \
         patch("elebot.facade._make_provider") as mock_prov:
        mock_load.return_value = Config()
        mock_prov.return_value = MagicMock()
        mock_prov.return_value.get_default_model.return_value = "test"
        mock_prov.return_value.generation.max_tokens = 4096
        Elebot.from_config()
        mock_load.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_run_returns_result(tmp_path):
    bot = Elebot.from_config(_write_config(tmp_path), workspace=tmp_path)
    bot._loop.process_direct_result = AsyncMock(
        return_value=DirectProcessResult(
            outbound=None,
            final_content="Hello back!",
            tools_used=["list_dir"],
            messages=[{"role": "assistant", "content": "Hello back!"}],
        )
    )

    result = await bot.run("hi")

    assert isinstance(result, RunResult)
    assert result.content == "Hello back!"
    assert result.tools_used == ["list_dir"]
    assert result.messages == [{"role": "assistant", "content": "Hello back!"}]
    bot._loop.process_direct_result.assert_awaited_once_with("hi", session_key="sdk:default")


@pytest.mark.asyncio
async def test_run_with_hooks(tmp_path):
    from elebot.agent.hook import AgentHook, AgentHookContext

    config_path = _write_config(tmp_path)
    bot = Elebot.from_config(config_path, workspace=tmp_path)

    class TestHook(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            pass

    bot._loop.process_direct_result = AsyncMock(
        return_value=DirectProcessResult(outbound=None, final_content="done")
    )

    result = await bot.run("hi", hooks=[TestHook()])

    assert result.content == "done"
    assert bot._loop._extra_hooks == []


@pytest.mark.asyncio
async def test_run_hooks_restored_on_error(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Elebot.from_config(config_path, workspace=tmp_path)

    from elebot.agent.hook import AgentHook

    bot._loop.process_direct_result = AsyncMock(side_effect=RuntimeError("boom"))
    original_hooks = bot._loop._extra_hooks

    with pytest.raises(RuntimeError):
        await bot.run("hi", hooks=[AgentHook()])

    assert bot._loop._extra_hooks is original_hooks


@pytest.mark.asyncio
async def test_run_none_response(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Elebot.from_config(config_path, workspace=tmp_path)
    bot._loop.process_direct_result = AsyncMock(return_value=DirectProcessResult(outbound=None))

    result = await bot.run("hi")
    assert result.content == ""


def test_workspace_override(tmp_path):
    config_path = _write_config(tmp_path)
    custom_ws = tmp_path / "custom_workspace"
    custom_ws.mkdir()

    bot = Elebot.from_config(config_path, workspace=custom_ws)
    assert bot._loop.workspace == custom_ws


def test_sdk_make_provider_uses_github_copilot_backend():
    from elebot.config.schema import Config
    from elebot.facade import _make_provider

    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "github-copilot",
                    "model": "github-copilot/gpt-4.1",
                }
            }
        }
    )

    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = _make_provider(config)

    assert provider.__class__.__name__ == "GitHubCopilotProvider"


def test_make_provider_uses_dashscope_openai_compat_for_default_qwen() -> None:
    from elebot.config.schema import Config
    from elebot.facade import _make_provider

    config = Config.model_validate(
        {
            "providers": {"dashscope": {"apiKey": "dashscope-test-key"}},
            "agents": {"defaults": {"model": "qwen3_6_plus"}},
        }
    )

    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = _make_provider(config)

    assert provider.__class__.__name__ == "OpenAICompatProvider"
    assert provider.get_default_model() == "qwen3_6_plus"
    assert provider._spec is not None
    assert provider._spec.name == "dashscope"
    assert provider._effective_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"


@pytest.mark.asyncio
async def test_run_custom_session_key(tmp_path):
    config_path = _write_config(tmp_path)
    bot = Elebot.from_config(config_path, workspace=tmp_path)

    bot._loop.process_direct_result = AsyncMock(
        return_value=DirectProcessResult(outbound=None, final_content="ok")
    )

    await bot.run("hi", session_key="user-alice")
    bot._loop.process_direct_result.assert_awaited_once_with("hi", session_key="user-alice")


@pytest.mark.asyncio
async def test_run_persists_multi_turn_history_and_filters_thinking(tmp_path):
    from elebot.providers.base import LLMResponse, ToolCallRequest
    from elebot.session.manager import SessionManager

    bot = Elebot.from_config(_write_config(tmp_path), workspace=tmp_path)
    call_index = {"value": 0}

    async def fake_chat_with_retry(*, messages, **kwargs):
        call_index["value"] += 1
        if call_index["value"] == 1:
            return LLMResponse(
                content="先看一下目录",
                tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
            )
        if call_index["value"] == 2:
            return LLMResponse(content="<think>内部推理</think>第一轮完成")
        assert any(
            message.get("role") == "assistant" and message.get("content") == "第一轮完成"
            for message in messages
        )
        return LLMResponse(content="<think>不要出现在正文里</think>第二轮完成")

    fake_provider = MagicMock()
    fake_provider.chat_with_retry = fake_chat_with_retry
    fake_provider.get_default_model.return_value = "qwen3_6_plus"
    fake_provider.generation.max_tokens = 8192

    bot._loop.provider = fake_provider
    bot._loop.runner.provider = fake_provider

    first = await bot.run("第一轮", session_key="sdk:thread-1")
    second = await bot.run("第二轮", session_key="sdk:thread-1")

    assert first.content == "第一轮完成"
    assert first.tools_used == ["list_dir"]
    assert second.content == "第二轮完成"
    assert "<think>" not in second.content

    reloaded = SessionManager(tmp_path).get_or_create("sdk:thread-1")
    assert [message["content"] for message in reloaded.messages if message["role"] == "user"] == ["第一轮", "第二轮"]
    assert [message["content"] for message in reloaded.messages if message["role"] == "assistant"][-2:] == [
        "第一轮完成",
        "第二轮完成",
    ]
    assert any(message.get("role") == "tool" for message in reloaded.messages)


def test_import_from_top_level():
    from elebot import Elebot as E, RunResult as R
    assert E is Elebot
    assert R is RunResult
