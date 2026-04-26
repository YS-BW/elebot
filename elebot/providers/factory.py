"""提供方装配入口。"""

from __future__ import annotations

from elebot.config.schema import Config
from elebot.providers.base import GenerationSettings, LLMProvider
from elebot.providers.registry import find_by_name


def build_provider(config: Config) -> LLMProvider:
    """按当前配置构建 provider。

    参数:
        config: 已完成环境变量展开和命令行覆盖的配置对象。

    返回:
        已实例化并注入默认生成参数的 provider。

    异常:
        ValueError: provider 配置非法或缺少必要凭证时抛出。
    """
    model = config.agents.defaults.model
    forced_provider = config.agents.defaults.provider
    if forced_provider != "auto" and find_by_name(forced_provider) is None:
        raise ValueError(f"Unknown provider configured: {forced_provider}")
    provider_name = config.get_provider_name(model)
    provider_config = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    if backend == "azure_openai":
        if not provider_config or not provider_config.api_key or not provider_config.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (provider_config and provider_config.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    if backend == "openai_codex":
        from elebot.providers.openai_codex_provider import OpenAICodexProvider

        provider: LLMProvider = OpenAICodexProvider(default_model=model)
    elif backend == "github_copilot":
        from elebot.providers.github_copilot_provider import GitHubCopilotProvider

        provider = GitHubCopilotProvider(default_model=model)
    elif backend == "azure_openai":
        from elebot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=provider_config.api_key,
            api_base=provider_config.api_base,
            default_model=model,
        )
    elif backend == "anthropic":
        from elebot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
        )
    else:
        from elebot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider
