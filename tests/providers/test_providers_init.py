"""Tests for lazy provider exports from elebot.providers."""

from __future__ import annotations

import importlib
import sys


def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "elebot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "elebot.providers.anthropic_provider", raising=False)
    monkeypatch.delitem(sys.modules, "elebot.providers.openai_compat_provider", raising=False)
    monkeypatch.delitem(sys.modules, "elebot.providers.azure_openai_provider", raising=False)

    providers = importlib.import_module("elebot.providers")

    assert "elebot.providers.anthropic_provider" not in sys.modules
    assert "elebot.providers.openai_compat_provider" not in sys.modules
    assert "elebot.providers.azure_openai_provider" not in sys.modules
    assert providers.__all__ == [
        "LLMProvider",
        "LLMResponse",
        "AnthropicProvider",
        "OpenAICompatProvider",
        "AzureOpenAIProvider",
    ]


def test_explicit_provider_import_still_works(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "elebot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "elebot.providers.anthropic_provider", raising=False)

    namespace: dict[str, object] = {}
    exec("from elebot.providers import AnthropicProvider", namespace)

    assert namespace["AnthropicProvider"].__name__ == "AnthropicProvider"
    assert "elebot.providers.anthropic_provider" in sys.modules
