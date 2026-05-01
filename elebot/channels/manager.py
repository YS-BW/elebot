"""多通道入口的启动和 outbound 路由 owner。"""

from __future__ import annotations

import asyncio

from loguru import logger

from elebot.bus.events import OutboundMessage
from elebot.channels.base import BaseChannel, ChannelRuntimeControl
from elebot.channels.weixin import WeixinChannel
from elebot.config.schema import Config


class ChannelManager:
    """管理已启用 channel 的启动、停止和消息路由。"""

    def __init__(
        self,
        config: Config,
        runtime: ChannelRuntimeControl,
        *,
        channel_factories: dict[str, type[BaseChannel]] | None = None,
    ) -> None:
        """基于当前配置初始化可用 channel。"""
        self.config = config
        self.runtime = runtime
        self.bus = runtime.bus
        self._channel_factories = channel_factories or {
            "weixin": WeixinChannel,
        }
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task[None] | None = None
        self._channel_tasks: list[asyncio.Task[None]] = []
        self._init_channels()

    def _init_channels(self) -> None:
        """按配置启用 channel。"""
        if self.config.channels.weixin.enabled:
            factory = self._channel_factories["weixin"]
            self.channels["weixin"] = factory(self.config.channels.weixin, self.runtime)

    async def start_all(self) -> None:
        """启动所有 channel 和 outbound dispatcher。"""
        if self._dispatch_task is not None:
            return
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        self._channel_tasks = [asyncio.create_task(channel.start()) for channel in self.channels.values()]
        await asyncio.sleep(0)

    async def wait(self) -> None:
        """等待所有 channel 主任务结束。"""
        if self._channel_tasks:
            await asyncio.gather(*self._channel_tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """停止所有 channel 和 dispatcher。"""
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None
        for channel in self.channels.values():
            try:
                await channel.stop()
            except Exception as exc:  # pragma: no cover - 防御性收尾
                logger.warning("Failed to stop channel {}: {}", channel.name, exc)
        if self._channel_tasks:
            await asyncio.gather(*self._channel_tasks, return_exceptions=True)
            self._channel_tasks.clear()

    async def _dispatch_outbound(self) -> None:
        """消费 runtime.bus.outbound 并路由到目标 channel。"""
        while True:
            try:
                message = await self.bus.consume_outbound()
            except asyncio.CancelledError:
                raise

            channel = self.channels.get(message.channel)
            if channel is None:
                logger.debug("No channel registered for outbound message: {}", message.channel)
                continue
            try:
                await self._route_message(channel, message)
            except Exception as exc:  # pragma: no cover - 防御性日志
                logger.warning(
                    "Channel {} failed to send outbound message to {}: {}",
                    channel.name,
                    message.chat_id,
                    exc,
                )

    async def _route_message(self, channel: BaseChannel, message: OutboundMessage) -> None:
        """根据 outbound metadata 选择对应的 channel 发送方法。"""
        metadata = dict(message.metadata or {})
        if metadata.get("_tool_transition"):
            await channel.send_progress(message.chat_id, message.content, metadata, tool_hint=True)
            return
        if metadata.get("_progress"):
            await channel.send_progress(message.chat_id, message.content, metadata, tool_hint=False)
            return
        if metadata.get("_stream_delta") or metadata.get("_stream_end"):
            await channel.send_delta(message.chat_id, message.content, metadata)
            return
        await channel.send_message(message)
