"""消息总线事件类型。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundMessage:
    """从聊天渠道接收到的消息。"""

    channel: str  # 渠道名称，例如 telegram、discord、slack、whatsapp
    sender_id: str  # 发送者标识
    chat_id: str  # 会话或频道标识
    content: str  # 消息正文
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # 媒体资源地址
    metadata: dict[str, Any] = field(default_factory=dict)  # 渠道特定附加信息
    session_key_override: str | None = None  # 可选线程级会话覆盖键

    @property
    def session_key(self) -> str:
        """返回会话唯一键。"""
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """要发送到聊天渠道的消息。"""

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

