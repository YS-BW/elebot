"""多通道入口的基础抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from elebot.bus.events import InboundMessage, OutboundMessage
from elebot.bus.queue import MessageBus
from elebot.runtime.models import InterruptReason, InterruptResult, RuntimeStatusSnapshot
from elebot.runtime.protocol import default_session_id


class ChannelRuntimeControl(Protocol):
    """供 channel 调用的 runtime 薄控制面。"""

    bus: MessageBus

    def interrupt_session(
        self,
        session_id: str,
        reason: InterruptReason = "user_interrupt",
    ) -> InterruptResult:
        """向指定会话发出中断请求。"""

    def reset_session(self, session_id: str) -> None:
        """重置指定会话。"""

    async def get_status_snapshot(self, session_id: str) -> RuntimeStatusSnapshot:
        """获取指定会话的状态快照。"""


class BaseChannel(ABC):
    """多通道入口的基础适配器。"""

    name = "base"

    def __init__(self, config: Any, runtime: ChannelRuntimeControl) -> None:
        """绑定 channel 配置和 runtime 控制面。"""
        self.config = config
        self.runtime = runtime
        self.bus = runtime.bus
        self._running = False

    @property
    def supports_streaming(self) -> bool:
        """当前 channel 是否启用正文流式输出。"""
        return bool(getattr(self.config, "streaming", False))

    async def publish_input(
        self,
        *,
        client_id: str,
        chat_id: str,
        content: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """把外部输入标准化成 InboundMessage 并发到 bus。"""
        inbound_metadata = dict(metadata or {})
        session_key = session_id or str(
            inbound_metadata.get("_session_id") or default_session_id(self.name, chat_id)
        )
        inbound_metadata["_session_id"] = session_key
        if self.supports_streaming:
            inbound_metadata["_wants_stream"] = True
        await self.bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                sender_id=client_id,
                chat_id=chat_id,
                content=content,
                metadata=inbound_metadata,
                session_key_override=session_id,
            )
        )

    @abstractmethod
    async def start(self) -> None:
        """启动 channel 监听。"""

    @abstractmethod
    async def stop(self) -> None:
        """停止 channel 并释放资源。"""

    @abstractmethod
    async def send_message(self, message: OutboundMessage) -> None:
        """发送最终消息事件。"""

    @abstractmethod
    async def send_progress(
        self,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        *,
        tool_hint: bool = False,
    ) -> None:
        """发送进度事件。"""

    @abstractmethod
    async def send_delta(
        self,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """发送正文增量或流结束事件。"""
