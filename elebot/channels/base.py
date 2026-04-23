"""中文模块说明：冻结模块，保留实现且不接入默认主链路。"""


from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from loguru import logger

from elebot.bus.events import InboundMessage, OutboundMessage
from elebot.bus.queue import MessageBus


class BaseChannel(ABC):
    """所有通道实现都要遵守的最小抽象接口。

    这层只定义消息总线接入、发送和生命周期约束，
    不关心具体平台是 Telegram、Discord 还是其他私有通道。
    """

    name: str = "base"
    display_name: str = "Base"
    transcription_provider: str = "groq"
    transcription_api_key: str = ""

    def __init__(self, config: Any, bus: MessageBus):
        """绑定通道配置和消息总线。"""
        self.config = config
        self.bus = bus
        self._running = False

    async def transcribe_audio(self, file_path: str | Path) -> str:
        """把音频文件转成文本。

        这里故意把失败收口为空字符串，
        因为转写只是增强能力，不应该因为语音识别失败就把整条消息链路打断。
        """
        if not self.transcription_api_key:
            return ""
        try:
            if self.transcription_provider == "openai":
                from elebot.providers.transcription import OpenAITranscriptionProvider
                provider = OpenAITranscriptionProvider(api_key=self.transcription_api_key)
            else:
                from elebot.providers.transcription import GroqTranscriptionProvider
                provider = GroqTranscriptionProvider(api_key=self.transcription_api_key)
            return await provider.transcribe(file_path)
        except Exception as e:
            logger.warning("{}: audio transcription failed: {}", self.name, e)
            return ""

    async def login(self, force: bool = False) -> bool:
        """执行通道自己的登录流程。

        默认实现直接返回成功；
        只有确实需要扫码或重新鉴权的通道才覆盖它。
        """
        return True

    @abstractmethod
    async def start(self) -> None:
        """启动通道并持续监听外部消息。"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止通道并释放外部连接。"""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """把一条出站消息发到对应平台。

        约定失败时直接抛异常，
        这样统一重试策略只需要放在 ChannelManager 一处维护。
        """
        pass

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        """发送一段流式增量文本。

        只有支持流式展示的通道才需要覆盖它。
        同样要求把失败抛出去，让外层统一决定是否重试。
        """
        pass

    @property
    def supports_streaming(self) -> bool:
        """只有配置开启且子类真的实现了 `send_delta` 才算支持流式。"""
        cfg = self.config
        streaming = cfg.get("streaming", False) if isinstance(cfg, dict) else getattr(cfg, "streaming", False)
        return bool(streaming) and type(self).send_delta is not BaseChannel.send_delta

    def is_allowed(self, sender_id: str) -> bool:
        """检查当前发送者是否在白名单里。"""
        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list:
            logger.warning("{}: allow_from is empty — all access denied", self.name)
            return False
        if "*" in allow_list:
            return True
        return str(sender_id) in allow_list

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """把通道侧收到的消息转成统一的总线事件。

        这里先做权限检查，再决定是否补 `_wants_stream` 标记，
        这样所有具体通道都可以复用同一条入站收口逻辑。
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                "Access denied for sender {} on channel {}. "
                "Add them to allowFrom list in config to grant access.",
                sender_id, self.name,
            )
            return

        meta = metadata or {}
        if self.supports_streaming:
            meta = {**meta, "_wants_stream": True}

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=meta,
            session_key_override=session_key,
        )

        await self.bus.publish_inbound(msg)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """返回 onboarding 阶段使用的最小默认配置。"""
        return {"enabled": False}

    @property
    def is_running(self) -> bool:
        """返回当前通道是否处于运行态。"""
        return self._running
