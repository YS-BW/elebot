"""提供方选择与解析逻辑。"""

from __future__ import annotations

from dataclasses import dataclass

from elebot.config.schema import Config, ProviderConfig
from elebot.providers.registry import PROVIDERS, ProviderSpec, find_by_name


@dataclass(slots=True)
class ProviderResolution:
    """描述一次 provider 解析结果。"""

    model: str
    provider_name: str | None
    provider_config: ProviderConfig | None
    spec: ProviderSpec | None
    backend: str
    api_base: str | None


def resolve_provider(config: Config, model: str | None = None) -> ProviderResolution:
    """根据配置与模型名解析 provider 归属。

    参数:
        config: 已完成环境变量展开和命令行覆盖的配置对象。
        model: 可选的模型名；为空时使用默认模型。

    返回:
        包含 provider 名称、配置、spec、backend 和解析后 api_base 的结果对象。

    异常:
        ValueError: 当强制指定了未知 provider 时抛出。
    """
    resolved_model = model or config.agents.defaults.model
    provider_config, provider_name = _match_provider(config, resolved_model)
    spec = find_by_name(provider_name) if provider_name else None
    api_base = _resolve_api_base(provider_config, spec)
    return ProviderResolution(
        model=resolved_model,
        provider_name=provider_name,
        provider_config=provider_config,
        spec=spec,
        backend=spec.backend if spec else "openai_compat",
        api_base=api_base,
    )


def _match_provider(
    config: Config,
    model: str,
) -> tuple[ProviderConfig | None, str | None]:
    """按当前项目既有优先级匹配 provider。

    参数:
        config: 根配置对象。
        model: 待解析的模型名。

    返回:
        `(provider_config, provider_name)` 元组；未命中时返回 `(None, None)`。

    异常:
        ValueError: 当强制 provider 名称非法时抛出。
    """
    model_lower = model.lower()
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")

    # 显式模型前缀必须优先，避免默认 provider 抢走已声明路由的模型。
    if model_prefix:
        spec = find_by_name(normalized_prefix)
        if spec is not None:
            return getattr(config.providers, spec.name, None), spec.name

    forced_provider = config.agents.defaults.provider
    if forced_provider != "auto":
        spec = find_by_name(forced_provider)
        if spec is None:
            raise ValueError(f"Unknown provider configured: {forced_provider}")
        return getattr(config.providers, spec.name, None), spec.name

    model_normalized = model_lower.replace("-", "_")

    def _keyword_matches(keyword: str) -> bool:
        normalized_keyword = keyword.lower()
        return (
            normalized_keyword in model_lower
            or normalized_keyword.replace("-", "_") in model_normalized
        )

    # 显式 provider 前缀优先，避免 generic 关键字把已声明路由的模型抢走。
    for spec in PROVIDERS:
        provider_config = getattr(config.providers, spec.name, None)
        if provider_config and model_prefix and normalized_prefix == spec.name:
            if spec.is_local or provider_config.api_key:
                return provider_config, spec.name

    # 关键字匹配顺序跟随注册表，保证行为稳定。
    for spec in PROVIDERS:
        provider_config = getattr(config.providers, spec.name, None)
        if provider_config and any(_keyword_matches(keyword) for keyword in spec.keywords):
            if spec.is_local or provider_config.api_key:
                return provider_config, spec.name

    # 本地 provider 常会承载无前缀模型名，因此在这里补一层 api_base 识别兜底。
    local_fallback: tuple[ProviderConfig, str] | None = None
    for spec in PROVIDERS:
        if not spec.is_local:
            continue
        provider_config = getattr(config.providers, spec.name, None)
        if not (provider_config and provider_config.api_base):
            continue
        if (
            spec.detect_by_base_keyword
            and spec.detect_by_base_keyword in provider_config.api_base
        ):
            return provider_config, spec.name
        if local_fallback is None:
            local_fallback = (provider_config, spec.name)
    if local_fallback is not None:
        return local_fallback

    # 最后按网关优先顺序兜底，避免 generic 模型名完全失配。
    for spec in PROVIDERS:
        provider_config = getattr(config.providers, spec.name, None)
        if provider_config and provider_config.api_key:
            return provider_config, spec.name

    return None, None


def _resolve_api_base(
    provider_config: ProviderConfig | None,
    spec: ProviderSpec | None,
) -> str | None:
    """推导本轮装配最终使用的 api_base。

    参数:
        provider_config: 匹配到的 provider 配置。
        spec: 匹配到的 provider 元数据。

    返回:
        用户显式配置的 api_base，或根据 spec 推断出的默认地址。
    """
    if provider_config and provider_config.api_base:
        return provider_config.api_base
    if spec and spec.default_api_base:
        return spec.default_api_base
    return None
