"""中文模块说明：冻结模块，保留实现且不接入默认主链路。"""


from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from loguru import logger

from elebot.bus.events import InboundMessage, OutboundMessage
from elebot.bus.queue import MessageBus


class BaseChannel(ABC):
    """中文说明：BaseChannel。"""
    """
    Abstract base class for chat channel implementations.

    Each channel (Telegram, Discord, etc.) should implement this interface
    to integrate with the elebot message bus.
    """

    name: str = "base"
    display_name: str = "Base"
    transcription_provider: str = "groq"
    transcription_api_key: str = ""

    def __init__(self, config: Any, bus: MessageBus):
        """中文说明：__init__。

        参数:
            config: 待补充参数说明。
            bus: 待补充参数说明。

        返回:
            待补充返回值说明。
        """
        """
        Initialize the channel.

        Args:
            config: Channel-specific configuration.
            bus: The message bus for communication.
        """
        self.config = config
        self.bus = bus
        self._running = False

    async def transcribe_audio(self, file_path: str | Path) -> str:
        """中文说明：transcribe_audio。

        参数:
            file_path: 待补充参数说明。

        返回:
            待补充返回值说明。
        """
        """Transcribe an audio file via Whisper (OpenAI or Groq). Returns empty string on failure."""
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
        """中文说明：login。

        参数:
            force: 待补充参数说明。

        返回:
            待补充返回值说明。
        """
        """
        Perform channel-specific interactive login (e.g. QR code scan).

        Args:
            force: If True, ignore existing credentials and force re-authentication.

        Returns True if already authenticated or login succeeds.
        Override in subclasses that support interactive login.
        """
        return True

    @abstractmethod
    async def start(self) -> None:
        """中文说明：start。

        参数:
            无。

        返回:
            待补充返回值说明。
        """
        """
        Start the channel and begin listening for messages.

        This should be a long-running async task that:
        1. Connects to the chat platform
        2. Listens for incoming messages
        3. Forwards messages to the bus via _handle_message()
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """中文说明：stop。

        参数:
            无。

        返回:
            待补充返回值说明。
        """
        """Stop the channel and clean up resources."""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """中文说明：send。

        参数:
            msg: 待补充参数说明。

        返回:
            待补充返回值说明。
        """
        """
        Send a message through this channel.

        Args:
            msg: The message to send.

        Implementations should raise on delivery failure so the channel manager
        can apply any retry policy in one place.
        """
        pass

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        """中文说明：send_delta。

        参数:
            chat_id: 待补充参数说明。
            delta: 待补充参数说明。
            metadata: 待补充参数说明。

        返回:
            待补充返回值说明。
        """
        """Deliver a streaming text chunk.

        Override in subclasses to enable streaming. Implementations should
        raise on delivery failure so the channel manager can retry.

        Streaming contract: ``_stream_delta`` is a chunk, ``_stream_end`` ends
        the current segment, and stateful implementations must key buffers by
        ``_stream_id`` rather than only by ``chat_id``.
        """
        pass

    @property
    def supports_streaming(self) -> bool:
        """中文说明：supports_streaming。

        参数:
            无。

        返回:
            待补充返回值说明。
        """
        """True when config enables streaming AND this subclass implements send_delta."""
        cfg = self.config
        streaming = cfg.get("streaming", False) if isinstance(cfg, dict) else getattr(cfg, "streaming", False)
        return bool(streaming) and type(self).send_delta is not BaseChannel.send_delta

    def is_allowed(self, sender_id: str) -> bool:
        """中文说明：is_allowed。

        参数:
            sender_id: 待补充参数说明。

        返回:
            待补充返回值说明。
        """
        """Check if *sender_id* is permitted.  Empty list → deny all; ``"*"`` → allow all."""
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
        """
        Handle an incoming message from the chat platform.

        This method checks permissions and forwards to the bus.

        Args:
            sender_id: The sender's identifier.
            chat_id: The chat/channel identifier.
            content: Message text content.
            media: Optional list of media URLs.
            metadata: Optional channel-specific metadata.
            session_key: Optional session key override (e.g. thread-scoped sessions).
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
        """中文说明：default_config。

        参数:
            无。

        返回:
            待补充返回值说明。
        """
        """Return default config for onboard. Override in plugins to auto-populate config.json."""
        return {"enabled": False}

    @property
    def is_running(self) -> bool:
        """中文说明：is_running。

        参数:
            无。

        返回:
            待补充返回值说明。
        """
        """Check if the channel is running."""
        return self._running
