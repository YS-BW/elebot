"""provider 模型目录测试。"""

from __future__ import annotations

from elebot.providers.model_catalog import (
    find_model,
    get_model_context_limit,
    list_models,
    suggest_models,
)


def test_list_models_returns_dashscope_catalog() -> None:
    """稳定 provider 应返回内置模型目录。"""
    models = list_models("dashscope")

    names = [item.name for item in models]
    assert "qwen3_6_plus" in names
    assert "qwen-plus" in names


def test_list_models_returns_deepseek_v4_flash() -> None:
    """DeepSeek 目录应包含当前默认模型。"""
    models = list_models("deepseek")

    names = [item.name for item in models]
    assert "deepseek-v4-flash" in names


def test_find_model_accepts_prefixed_alias() -> None:
    """带 provider 前缀的模型名应能命中目录条目。"""
    model = find_model("anthropic/claude-sonnet-4-20250514")

    assert model is not None
    assert model.provider_name == "anthropic"
    assert model.name == "claude-sonnet-4-20250514"


def test_suggest_models_filters_by_prefix() -> None:
    """模型补全应按输入前缀过滤。"""
    suggestions = suggest_models("gpt", provider="openai")

    assert "gpt-5" in suggestions
    assert "gpt-4.1" in suggestions


def test_get_model_context_limit_returns_known_hint() -> None:
    """目录内模型应返回推荐上下文窗口。"""
    assert get_model_context_limit("qwen3_6_plus", provider="dashscope") == 1_000_000


def test_unsupported_provider_returns_empty_catalog() -> None:
    """未覆盖的 provider 应返回空建议与空推荐值。"""
    assert list_models("ollama") == []
    assert suggest_models("llama", provider="ollama") == []
    assert get_model_context_limit("llama3.2", provider="ollama") is None
