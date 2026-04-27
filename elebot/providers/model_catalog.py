"""提供方模型目录与向导辅助。"""

from __future__ import annotations

from dataclasses import dataclass

from elebot.providers.registry import find_by_name


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """描述一个可供配置向导复用的模型条目。"""

    provider_name: str
    name: str
    aliases: tuple[str, ...] = ()
    recommended_context_window_tokens: int | None = None


_STABLE_PROVIDER_MODELS: dict[str, tuple[ModelSpec, ...]] = {
    "openai": (
        ModelSpec(
            provider_name="openai",
            name="gpt-5",
            aliases=("openai/gpt-5",),
            recommended_context_window_tokens=400_000,
        ),
        ModelSpec(
            provider_name="openai",
            name="gpt-5-mini",
            aliases=("openai/gpt-5-mini",),
            recommended_context_window_tokens=400_000,
        ),
        ModelSpec(
            provider_name="openai",
            name="gpt-4.1",
            aliases=("openai/gpt-4.1",),
            recommended_context_window_tokens=1_047_576,
        ),
        ModelSpec(
            provider_name="openai",
            name="gpt-4.1-mini",
            aliases=("openai/gpt-4.1-mini",),
            recommended_context_window_tokens=1_047_576,
        ),
    ),
    "anthropic": (
        ModelSpec(
            provider_name="anthropic",
            name="claude-sonnet-4-20250514",
            aliases=("anthropic/claude-sonnet-4-20250514", "claude-sonnet-4"),
            recommended_context_window_tokens=200_000,
        ),
        ModelSpec(
            provider_name="anthropic",
            name="claude-opus-4-20250514",
            aliases=("anthropic/claude-opus-4-20250514", "claude-opus-4"),
            recommended_context_window_tokens=200_000,
        ),
        ModelSpec(
            provider_name="anthropic",
            name="claude-3-7-sonnet-20250219",
            aliases=("anthropic/claude-3-7-sonnet-20250219",),
            recommended_context_window_tokens=200_000,
        ),
    ),
    "dashscope": (
        ModelSpec(
            provider_name="dashscope",
            name="qwen3_6_plus",
            aliases=("dashscope/qwen3_6_plus", "qwen3.6-plus"),
            recommended_context_window_tokens=1_000_000,
        ),
        ModelSpec(
            provider_name="dashscope",
            name="qwen3_5_plus",
            aliases=("dashscope/qwen3_5_plus", "qwen3.5-plus"),
            recommended_context_window_tokens=1_000_000,
        ),
        ModelSpec(
            provider_name="dashscope",
            name="qwen-plus",
            aliases=("dashscope/qwen-plus",),
            recommended_context_window_tokens=131_072,
        ),
    ),
    "deepseek": (
        ModelSpec(
            provider_name="deepseek",
            name="deepseek-v4-flash",
            aliases=("deepseek/deepseek-v4-flash",),
            recommended_context_window_tokens=65_536,
        ),
        ModelSpec(
            provider_name="deepseek",
            name="deepseek-chat",
            aliases=("deepseek/deepseek-chat",),
            recommended_context_window_tokens=65_536,
        ),
        ModelSpec(
            provider_name="deepseek",
            name="deepseek-reasoner",
            aliases=("deepseek/deepseek-reasoner",),
            recommended_context_window_tokens=65_536,
        ),
    ),
    "gemini": (
        ModelSpec(
            provider_name="gemini",
            name="gemini-2.5-pro",
            aliases=("google/gemini-2.5-pro", "gemini-2.5-pro-preview"),
            recommended_context_window_tokens=1_048_576,
        ),
        ModelSpec(
            provider_name="gemini",
            name="gemini-2.5-flash",
            aliases=("google/gemini-2.5-flash", "gemini-2.5-flash-preview"),
            recommended_context_window_tokens=1_048_576,
        ),
    ),
    "moonshot": (
        ModelSpec(
            provider_name="moonshot",
            name="kimi-k2.5",
            aliases=("moonshot/kimi-k2.5",),
            recommended_context_window_tokens=262_144,
        ),
        ModelSpec(
            provider_name="moonshot",
            name="kimi-k2-turbo-preview",
            aliases=("moonshot/kimi-k2-turbo-preview",),
            recommended_context_window_tokens=128_000,
        ),
    ),
}


def _normalize_provider_name(provider: str) -> str:
    """把 provider 名称归一化成注册表键名。"""
    spec = find_by_name(provider)
    if spec is not None:
        return spec.name
    return provider.replace("-", "_").strip().lower()


def _normalize_model_name(model_name: str) -> str:
    """把模型名归一化成便于比较的形式。"""
    return model_name.strip().lower().replace("_", "-")


def _iter_candidates(provider: str) -> tuple[ModelSpec, ...]:
    """返回指定 provider 下可用的模型候选。"""
    normalized_provider = _normalize_provider_name(provider)
    if normalized_provider == "auto":
        combined: list[ModelSpec] = []
        for models in _STABLE_PROVIDER_MODELS.values():
            combined.extend(models)
        return tuple(combined)
    return _STABLE_PROVIDER_MODELS.get(normalized_provider, ())


def list_models(provider: str = "auto") -> list[ModelSpec]:
    """列出当前支持的模型目录条目。

    参数:
        provider: 提供方名称；传 ``auto`` 时返回全部稳定 provider 条目。

    返回:
        可用于向导展示的模型条目列表。
    """
    return list(_iter_candidates(provider))


def find_model(model_name: str, provider: str = "auto") -> ModelSpec | None:
    """按模型名查找模型条目。

    参数:
        model_name: 待查找的模型名，允许带 provider 前缀。
        provider: 当前选中的提供方名称。

    返回:
        命中的模型条目；未命中时返回 ``None``。
    """
    normalized_model = _normalize_model_name(model_name)
    for model_spec in _iter_candidates(provider):
        candidates = (model_spec.name, *model_spec.aliases)
        for candidate in candidates:
            normalized_candidate = _normalize_model_name(candidate)
            if normalized_model == normalized_candidate:
                return model_spec
            if "/" in normalized_candidate and normalized_model == normalized_candidate.split("/", 1)[1]:
                return model_spec
    return None


def suggest_models(partial: str, provider: str = "auto", limit: int = 20) -> list[str]:
    """根据输入前缀返回模型建议。

    参数:
        partial: 用户已输入的模型前缀。
        provider: 当前选中的提供方名称。
        limit: 最多返回的候选数量。

    返回:
        去重后的模型名称列表。
    """
    normalized_partial = _normalize_model_name(partial)
    suggestions: list[str] = []
    seen: set[str] = set()

    for model_spec in _iter_candidates(provider):
        for candidate in (model_spec.name, *model_spec.aliases):
            normalized_candidate = _normalize_model_name(candidate)
            stripped_candidate = normalized_candidate.split("/", 1)[1] if "/" in normalized_candidate else normalized_candidate
            if normalized_partial and normalized_partial not in normalized_candidate and normalized_partial not in stripped_candidate:
                continue
            if model_spec.name in seen:
                break
            seen.add(model_spec.name)
            suggestions.append(model_spec.name)
            break
        if len(suggestions) >= limit:
            break

    return suggestions[:limit]


def get_recommended_context_window(model_name: str, provider: str = "auto") -> int | None:
    """获取模型建议上下文窗口上限。

    参数:
        model_name: 模型名称。
        provider: 提供方名称。

    返回:
        推荐的上下文窗口大小；目录未覆盖时返回 ``None``。
    """
    model_spec = find_model(model_name, provider=provider)
    if model_spec is None:
        return None
    return model_spec.recommended_context_window_tokens


def get_model_suggestions(partial: str, provider: str = "auto", limit: int = 20) -> list[str]:
    """兼容向导现有调用，返回模型补全建议。"""
    return suggest_models(partial=partial, provider=provider, limit=limit)


def get_model_context_limit(model: str, provider: str = "auto") -> int | None:
    """兼容向导现有调用，返回模型推荐上下文窗口。"""
    return get_recommended_context_window(model_name=model, provider=provider)


def format_token_count(tokens: int) -> str:
    """格式化 token 数量，便于在界面里展示。

    参数:
        tokens: token 数值。

    返回:
        带千分位分隔符的字符串。
    """
    return f"{tokens:,}"
