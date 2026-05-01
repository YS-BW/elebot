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
from elebot.cron import CronJob
from elebot.providers.base import LLMProvider
from elebot.providers.factory import build_provider
from elebot.providers.transcription import build_transcription_provider
from elebot.runtime.lifecycle import RuntimeLifecycle
from elebot.runtime.models import (
    DreamLogResult,
    DreamRestoreResult,
    InterruptReason,
    InterruptResult,
    RuntimeStatusSnapshot,
)
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
        transcription_provider = build_transcription_provider(config)
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
                transcription_provider=transcription_provider,
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

    def interrupt_session(
        self,
        session_id: str,
        reason: InterruptReason = "user_interrupt",
    ) -> InterruptResult:
        """向指定会话发出中断请求。

        参数:
            session_id: 目标会话键。
            reason: 本次中断的触发原因。

        返回:
            当前中断请求的处理结果。
        """
        return self.agent_loop.interrupt_session(session_id, reason)

    def reset_session(self, session_id: str) -> None:
        """重置指定会话。

        参数:
            session_id: 目标会话键。

        返回:
            无返回值。
        """
        self.agent_loop.reset_session(session_id)

    async def get_status_snapshot(self, session_id: str) -> RuntimeStatusSnapshot:
        """获取指定会话的运行状态快照。

        参数:
            session_id: 目标会话键。

        返回:
            对外可复用的 runtime 状态快照。
        """
        snapshot = await self.agent_loop.build_status_snapshot(session_id)
        return RuntimeStatusSnapshot(
            version=snapshot.version,
            model=snapshot.model,
            start_time=snapshot.start_time,
            last_usage=snapshot.last_usage,
            context_window_tokens=snapshot.context_window_tokens,
            session_msg_count=snapshot.session_msg_count,
            context_tokens_estimate=snapshot.context_tokens_estimate,
            search_usage_text=snapshot.search_usage_text,
        )

    def trigger_dream(self, channel: str, chat_id: str) -> None:
        """在后台触发一次 Dream。

        参数:
            channel: 结果回推的消息渠道。
            chat_id: 结果回推的会话标识。

        返回:
            无返回值。
        """
        self.agent_loop.trigger_dream_background(channel, chat_id)

    def list_cron_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """列出当前 cron jobs。

        参数:
            include_disabled: 是否包含已禁用 job。

        返回:
            当前 cron job 列表。
        """
        return self.agent_loop.list_cron_jobs(include_disabled=include_disabled)

    def remove_cron_job(self, job_id: str) -> bool:
        """删除指定 cron job。

        参数:
            job_id: 目标 job 标识。

        返回:
            删除成功时返回 ``True``。
        """
        return self.agent_loop.remove_cron_job(job_id)

    async def transcribe_audio(self, file_path: str) -> str:
        """通过 runtime 级 provider 转写一段音频。

        参数:
            file_path: 本地音频文件路径。

        返回:
            转写文本；未配置 provider 或转写失败时返回空字符串。
        """
        provider = self.state.transcription_provider
        if provider is None:
            return ""
        return await provider.transcribe(file_path)


    def get_dream_log(self, sha: str | None = None) -> DreamLogResult:
        """查看最近一次或指定 Dream 版本差异。

        参数:
            sha: 可选的目标提交 SHA。

        返回:
            对外可复用的 Dream 日志结果。
        """
        result = self.agent_loop.memory_store.show_dream_version(sha)
        commit = result.commit
        return DreamLogResult(
            status=result.status,
            requested_sha=result.requested_sha,
            sha=commit.sha if commit else None,
            timestamp=commit.timestamp if commit else None,
            message=commit.message if commit else result.message,
            diff=result.diff,
            changed_files=result.changed_files,
        )

    def restore_dream_version(self, sha: str) -> DreamRestoreResult:
        """恢复指定 Dream 版本。

        参数:
            sha: 需要回退的 Dream 提交 SHA。

        返回:
            对外可复用的 Dream 恢复结果。
        """
        result = self.agent_loop.memory_store.restore_dream_version(sha)
        return DreamRestoreResult(
            status=result.status,
            requested_sha=result.requested_sha,
            new_sha=result.new_sha,
            changed_files=result.changed_files,
            message=result.message,
        )

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
                interrupt_session=self.interrupt_session,
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
