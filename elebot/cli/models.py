"""向导模式使用的模型信息辅助函数。"""

from __future__ import annotations

from typing import Any


def get_all_models() -> list[str]:
    """返回当前可用模型列表。

    返回:
        当前实现暂时返回空列表。
    """
    return []


def find_model_info(model_name: str) -> dict[str, Any] | None:
    """按模型名查找模型元信息。

    参数:
        model_name: 模型名称。

    返回:
        当前实现暂时返回 ``None``。
    """
    return None


def get_model_context_limit(model: str, provider: str = "auto") -> int | None:
    """获取模型建议上下文窗口上限。

    参数:
        model: 模型名称。
        provider: 提供方名称。

    返回:
        当前实现暂时返回 ``None``。
    """
    return None


def get_model_suggestions(partial: str, provider: str = "auto", limit: int = 20) -> list[str]:
    """根据输入前缀返回模型建议。

    参数:
        partial: 用户已输入的模型前缀。
        provider: 提供方名称。
        limit: 最多返回的候选数量。

    返回:
        当前实现暂时返回空列表。
    """
    return []


def format_token_count(tokens: int) -> str:
    """格式化 token 数量，便于在界面里展示。

    参数:
        tokens: token 数值。

    返回:
        带千分位分隔符的字符串。
    """
    return f"{tokens:,}"
