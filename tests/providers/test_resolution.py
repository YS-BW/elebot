"""provider 解析策略测试。"""

from __future__ import annotations

import pytest

from elebot.config.schema import Config
from elebot.providers.resolution import resolve_provider


def test_resolution_prefers_explicit_openai_prefix() -> None:
    """显式前缀为 openai 时应命中对应 provider。"""
    config = Config()
    config.agents.defaults.model = "openai/gpt-4.1"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "openai"
    assert resolution.backend == "openai_compat"
    assert resolution.api_base is None


def test_resolution_prefers_explicit_anthropic_prefix() -> None:
    """显式前缀为 anthropic 时应命中对应 provider。"""
    config = Config()
    config.agents.defaults.model = "anthropic/claude-sonnet-4-20250514"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "anthropic"
    assert resolution.backend == "anthropic"
    assert resolution.api_base is None


def test_resolution_uses_keyword_match_for_default_qwen() -> None:
    """默认 qwen 主链路应按关键字匹配到 dashscope。"""
    config = Config.model_validate(
        {
            "providers": {"dashscope": {"apiKey": "dashscope-test-key"}},
            "agents": {"defaults": {"model": "qwen3_6_plus", "provider": "auto"}},
        }
    )

    resolution = resolve_provider(config)

    assert resolution.provider_name == "dashscope"
    assert resolution.backend == "openai_compat"
    assert resolution.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_resolution_allows_explicit_ollama_prefix_without_api_key() -> None:
    """本地 provider 不要求 API Key 即可通过显式前缀命中。"""
    config = Config()
    config.agents.defaults.model = "ollama/llama3.2"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "ollama"
    assert resolution.api_base == "http://localhost:11434/v1"


def test_resolution_detects_local_provider_by_api_base() -> None:
    """无前缀模型名时，应能通过本地 api_base 识别 provider。"""
    config = Config.model_validate(
        {
            "providers": {"ollama": {"apiBase": "http://127.0.0.1:11434/v1"}},
            "agents": {"defaults": {"model": "llama3.2", "provider": "auto"}},
        }
    )

    resolution = resolve_provider(config)

    assert resolution.provider_name == "ollama"
    assert resolution.api_base == "http://127.0.0.1:11434/v1"


def test_resolution_uses_gateway_fallback_when_model_is_generic() -> None:
    """没有模型关键字时，应回退到可用网关 provider。"""
    config = Config.model_validate(
        {
            "providers": {"openrouter": {"apiKey": "sk-or-test"}},
            "agents": {"defaults": {"model": "grok-4-fast", "provider": "auto"}},
        }
    )

    resolution = resolve_provider(config)

    assert resolution.provider_name == "openrouter"
    assert resolution.api_base == "https://openrouter.ai/api/v1"


def test_resolution_uses_forced_provider_and_infers_default_api_base() -> None:
    """强制指定本地 provider 时应推断默认 api_base。"""
    config = Config()
    config.agents.defaults.provider = "ollama"
    config.agents.defaults.model = "llama3.2"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "ollama"
    assert resolution.api_base == "http://localhost:11434/v1"


def test_resolution_rejects_unknown_forced_provider() -> None:
    """未知强制 provider 应立即报错。"""
    config = Config()
    config.agents.defaults.provider = "missing-provider"

    with pytest.raises(ValueError, match="Unknown provider configured: missing-provider"):
        resolve_provider(config)
