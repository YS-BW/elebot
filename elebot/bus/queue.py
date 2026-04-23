"""异步消息总线队列。"""

import asyncio

from elebot.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """解耦渠道与 Agent 的异步消息总线。"""

    def __init__(self):
        """初始化消息总线。"""
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """发布一条入站消息。"""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """消费下一条入站消息。"""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """发布一条出站消息。"""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """消费下一条出站消息。"""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """返回待处理入站消息数。"""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """返回待发送出站消息数。"""
        return self.outbound.qsize()
