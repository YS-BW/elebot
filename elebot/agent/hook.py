"""定义 Agent 运行阶段可复用的生命周期 Hook。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from elebot.providers.base import LLMResponse, ToolCallRequest


@dataclass(slots=True)
class AgentHookContext:
    """承载单轮迭代中可被 Hook 观察和补充的共享状态。"""

    iteration: int
    messages: list[dict[str, Any]]
    response: LLMResponse | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    tool_events: list[dict[str, str]] = field(default_factory=list)
    final_content: str | None = None
    stop_reason: str | None = None
    error: str | None = None


class AgentHook:
    """定义 AgentRunner 暴露给外层扩展点的最小生命周期接口。"""

    def __init__(self, reraise: bool = False) -> None:
        """配置当前 Hook 的异常策略。

        `reraise=True` 适合主链路自带 Hook，
        因为这类异常通常意味着内部状态不一致，不应该被静默吞掉。
        """
        self._reraise = reraise

    def wants_streaming(self) -> bool:
        """声明当前 Hook 是否关心流式正文增量。"""
        return False

    async def before_iteration(self, context: AgentHookContext) -> None:
        """在单轮模型调用开始前介入。"""
        pass

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        """在收到新的流式正文片段时介入。"""
        pass

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        """在当前一段流式输出收尾时介入。"""
        pass

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """在工具真正开始执行前介入。"""
        pass

    async def after_iteration(self, context: AgentHookContext) -> None:
        """在一轮模型与工具交互完成后介入。"""
        pass

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        """在最终回复对外暴露前做最后一次整理。"""
        return content


class CompositeHook(AgentHook):
    """把多个 Hook 组合成一条顺序执行的生命周期管线。

    这里对异步阶段做异常隔离，是为了允许业务方挂自定义 Hook 而不直接拖垮主循环。
    但 `finalize_content` 仍然保持串行直通，因为内容被改坏时应该尽快暴露问题。
    """

    __slots__ = ("_hooks",)

    def __init__(self, hooks: list[AgentHook]) -> None:
        """初始化组合 Hook。

        参数:
            hooks: 需要按顺序执行的 Hook 列表。

        返回:
            None
        """
        super().__init__()
        self._hooks = list(hooks)

    def wants_streaming(self) -> bool:
        """判断是否有任一子 Hook 需要流式回调。

        参数:
            无。

        返回:
            只要任一子 Hook 需要流式回调就返回 `True`。
        """
        return any(h.wants_streaming() for h in self._hooks)

    async def _for_each_hook_safe(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        for h in self._hooks:
            if getattr(h, "_reraise", False):
                await getattr(h, method_name)(*args, **kwargs)
                continue

            try:
                await getattr(h, method_name)(*args, **kwargs)
            except Exception:
                logger.exception("AgentHook.{} error in {}", method_name, type(h).__name__)

    async def before_iteration(self, context: AgentHookContext) -> None:
        """把迭代开始事件转发给所有子 Hook。

        参数:
            context: 当前迭代上下文。

        返回:
            None
        """
        await self._for_each_hook_safe("before_iteration", context)

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        """把流式文本增量转发给所有子 Hook。

        参数:
            context: 当前迭代上下文。
            delta: 本次收到的文本增量。

        返回:
            None
        """
        await self._for_each_hook_safe("on_stream", context, delta)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        """把流式结束事件转发给所有子 Hook。

        参数:
            context: 当前迭代上下文。
            resuming: 是否会在工具执行后恢复同一轮流式输出。

        返回:
            None
        """
        await self._for_each_hook_safe("on_stream_end", context, resuming=resuming)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """把工具执行前事件转发给所有子 Hook。

        参数:
            context: 当前迭代上下文。

        返回:
            None
        """
        await self._for_each_hook_safe("before_execute_tools", context)

    async def after_iteration(self, context: AgentHookContext) -> None:
        """把迭代结束事件转发给所有子 Hook。

        参数:
            context: 当前迭代上下文。

        返回:
            None
        """
        await self._for_each_hook_safe("after_iteration", context)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        """按顺序串联所有子 Hook 的内容收尾逻辑。

        参数:
            context: 当前迭代上下文。
            content: 当前整理出的最终文本。

        返回:
            经过所有子 Hook 处理后的文本。
        """
        for h in self._hooks:
            content = h.finalize_content(context, content)
        return content
