"""提供可复用的 EleBot 进程内 runtime 入口。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from elebot.agent.loop import AgentLoop
from elebot.bus.events import OutboundMessage
from elebot.bus.queue import MessageBus
from elebot.cli.interactive import run_interactive_loop
from elebot.cli.stream import StreamRenderer
from elebot.config.schema import Config
from elebot.providers.base import LLMProvider
from elebot.providers.factory import build_provider
from elebot.runtime.lifecycle import RuntimeLifecycle
from elebot.runtime.state import RuntimeState

if TYPE_CHECKING:
    from elebot.providers.base import LLMProvider


class ElebotRuntime:
    """封装 CLI 可复用的进程内 runtime 入口。"""

    def __init__(self, state: RuntimeState) -> None:
        """绑定 runtime 的共享状态和生命周期对象。

        参数:
            state: 已装配完成的 runtime 状态。

        返回:
            无返回值。
        """
        self.state = state
        self.lifecycle = RuntimeLifecycle(state)

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        provider_builder: Callable[[Config], LLMProvider] | None = None,
        bus_factory: Callable[[], MessageBus] | None = None,
        agent_loop_factory: Callable[..., AgentLoop] | None = None,
    ) -> "ElebotRuntime":
        """从配置对象装配一份完整 runtime。

        参数:
            config: 已完成环境变量展开和命令行覆盖的配置对象。
            provider_builder: 自定义 provider 构建函数，便于入口层复用现有校验逻辑。
            bus_factory: 自定义总线工厂，便于测试或上层注入。
            agent_loop_factory: 自定义主循环工厂，便于测试或入口层替换。

        返回:
            一份可直接启动或执行单次调用的 runtime。
        """
        resolved_provider_builder = provider_builder or build_provider
        resolved_bus_factory = bus_factory or MessageBus
        resolved_agent_loop_factory = agent_loop_factory or AgentLoop

        bus = resolved_bus_factory()
        provider = resolved_provider_builder(config)
        defaults = config.agents.defaults
        agent_loop = resolved_agent_loop_factory(
            bus=bus,
            provider=provider,
            workspace=config.workspace_path,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=defaults.context_window_tokens,
            web_config=config.tools.web,
            context_block_limit=defaults.context_block_limit,
            max_tool_result_chars=defaults.max_tool_result_chars,
            provider_retry_mode=defaults.provider_retry_mode,
            exec_config=config.tools.exec,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            mcp_servers=config.tools.mcp_servers,
            timezone=defaults.timezone,
            unified_session=defaults.unified_session,
            session_ttl_minutes=defaults.session_ttl_minutes,
        )
        return cls(
            RuntimeState(
                config=config,
                bus=bus,
                provider=provider,
                agent_loop=agent_loop,
            )
        )

    @property
    def bus(self) -> MessageBus:
        """返回 runtime 持有的消息总线。

        参数:
            无。

        返回:
            当前 runtime 的消息总线实例。
        """
        return self.state.bus

    @property
    def agent_loop(self) -> AgentLoop:
        """返回 runtime 持有的主循环对象。

        参数:
            无。

        返回:
            当前 runtime 的 AgentLoop 实例。
        """
        return self.state.agent_loop

    async def run_once(
        self,
        message: str,
        *,
        session_id: str,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """执行一次直连消息处理。

        参数:
            message: 本轮用户输入。
            session_id: 要写入的会话标识。
            on_progress: 进度回调。
            on_stream: 流式增量回调。
            on_stream_end: 流式结束回调。

        返回:
            主链路生成的标准出站消息；如果没有正文则可能返回 `None`。
        """
        return await self.agent_loop.process_direct(
            message,
            session_id,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
        )

    async def run_interactive(
        self,
        *,
        session_id: str,
        markdown: bool,
        renderer_factory: Callable[..., StreamRenderer] = StreamRenderer,
    ) -> None:
        """运行基于终端输入循环的交互模式。

        参数:
            session_id: 当前交互会话标识。
            markdown: 是否按 Markdown 渲染回复。
            renderer_factory: 流式渲染器工厂，便于测试注入。

        返回:
            无返回值。
        """
        manage_runtime_lifecycle = not self.lifecycle.is_running()
        if manage_runtime_lifecycle:
            await self.start()
        try:
            await run_interactive_loop(
                agent_loop=self.agent_loop,
                bus=self.bus,
                session_id=session_id,
                markdown=markdown,
                renderer_factory=renderer_factory,
                manage_agent_loop=False,
            )
        finally:
            if manage_runtime_lifecycle:
                await self.close()

    async def start(self) -> None:
        """在后台启动 runtime 主循环。

        参数:
            无。

        返回:
            无返回值。
        """
        await self.lifecycle.start()

    async def wait(self) -> None:
        """等待后台主循环结束。

        参数:
            无。

        返回:
            无返回值。
        """
        await self.lifecycle.wait()

    def stop(self) -> None:
        """请求停止后台主循环。

        参数:
            无。

        返回:
            无返回值。
        """
        self.lifecycle.request_stop()

    async def close(self) -> None:
        """关闭 runtime 并释放外部资源。

        参数:
            无。

        返回:
            无返回值。
        """
        await self.lifecycle.close()
