"""EleBot 多通道入口适配层。"""

from elebot.channels.base import BaseChannel, ChannelRuntimeControl
from elebot.channels.manager import ChannelManager
from elebot.channels.websocket import WebSocketChannel
from elebot.channels.weixin import WeixinChannel

__all__ = [
    "BaseChannel",
    "ChannelManager",
    "ChannelRuntimeControl",
    "WeixinChannel",
    "WebSocketChannel",
]
