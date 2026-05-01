"""provider 装配入口测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from elebot.config.schema import Config
from elebot.providers.factory import build_provider


def test_build_provider_uses_forced_openai_backend() -> None:
    """显式指定 openai 时应装配对应 backend。"""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                }
            },
            "providers": {"openai": {"apiKey": "openai-test-key"}},
        }
    )

    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "OpenAICompatProvider"
    assert provider._spec is not None
    assert provider._spec.name == "openai"


def test_build_provider_uses_xiaomi_mimo_for_default_first_run() -> None:
    """首次默认主链路应装配小米 MIMO 的兼容 provider。"""
    config = Config.model_validate(
        {
            "providers": {"xiaomi_mimo": {"apiKey": "mimo-test-key"}},
        }
    )

    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "OpenAICompatProvider"
    assert provider.get_default_model() == "mimo-v2.5"
    assert provider._spec is not None
    assert provider._spec.name == "xiaomi_mimo"
    assert provider._effective_base == "https://api.xiaomimimo.com/v1"


def test_build_provider_applies_default_generation_settings() -> None:
    """provider 应继承配置里的默认 generation 参数。"""
    config = Config.model_validate(
        {
            "providers": {"dashscope": {"apiKey": "dashscope-test-key"}},
            "agents": {
                "defaults": {
                    "provider": "dashscope",
                    "model": "qwen3_6_plus",
                    "temperature": 0.6,
                    "max_tokens": 4096,
                    "reasoning_effort": "medium",
                }
            },
        }
    )

    with patch("elebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.generation.temperature == pytest.approx(0.6)
    assert provider.generation.max_tokens == 4096
    assert provider.generation.reasoning_effort == "medium"


def test_build_provider_rejects_unknown_forced_provider() -> None:
    """未知强制 provider 应立即报错。"""
    config = Config()
    config.agents.defaults.provider = "missing-provider"

    with pytest.raises(ValueError, match="Unknown provider configured: missing-provider"):
        build_provider(config)


def test_build_provider_rejects_missing_api_key_for_remote_provider() -> None:
    """远端 openai 兼容 provider 缺少 key 时应报错。"""
    config = Config()
    config.agents.defaults.provider = "openai"
    config.agents.defaults.model = "gpt-4o"

    with pytest.raises(ValueError, match="No API key configured for provider 'openai'"):
        build_provider(config)
