"""WebSocket channel 实现。"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from loguru import logger
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from elebot.bus.events import OutboundMessage
from elebot.channels.base import BaseChannel
from elebot.runtime.protocol import (
    build_delta_event,
    build_error_event,
    build_interrupt_result_event,
    build_message_event,
    build_progress_event,
    build_ready_event,
    build_reset_done_event,
    build_status_result_event,
    build_stream_end_event,
    default_session_id,
)


def _normalize_path(path: str) -> str:
    """把路径统一成 websocket handler 可比较的形式。"""
    normalized = path.strip() or "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


class WebSocketChannel(BaseChannel):
    """本机 WebSocket channel。"""

    name = "websocket"
    _HOST = "127.0.0.1"

    def __init__(self, config: Any, runtime) -> None:
        """初始化 websocket 连接状态。"""
        super().__init__(config, runtime)
        self._connections: dict[str, ServerConnection] = {}
        self._send_lock = asyncio.Lock()
        self._stop_event: asyncio.Event | None = None
        self._server_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """启动本机 websocket server。"""
        self._running = True
        self._stop_event = asyncio.Event()
        expected_path = _normalize_path(self.config.path)

        async def process_request(connection: ServerConnection, request: Any) -> Any:
            parsed = urlsplit(request.path)
            if _normalize_path(parsed.path) != expected_path:
                return connection.respond(404, "Not Found")
            query = parse_qs(parsed.query, keep_blank_values=False)
            client_id = (query.get("client_id") or [""])[0].strip()
            if not client_id:
                return connection.respond(400, "client_id is required")
            return None

        async def handler(connection: ServerConnection) -> None:
            await self._handle_connection(connection)

        logger.info(
            "WebSocket channel listening on ws://{}:{}{}",
            self._HOST,
            self.config.port,
            expected_path,
        )

        async def runner() -> None:
            async with serve(
                handler,
                self._HOST,
                self.config.port,
                process_request=process_request,
            ):
                assert self._stop_event is not None
                await self._stop_event.wait()

        self._server_task = asyncio.create_task(runner())
        await self._server_task

    async def stop(self) -> None:
        """停止 websocket server 并关闭连接。"""
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        for connection in list(self._connections.values()):
            try:
                await connection.close()
            except Exception:  # pragma: no cover - 防御性收尾
                pass
        self._connections.clear()
        if self._server_task is not None:
            await asyncio.gather(self._server_task, return_exceptions=True)
            self._server_task = None

    async def send_message(self, message: OutboundMessage) -> None:
        """发送最终消息事件。"""
        session_id = self._session_id_for(message.chat_id, message.metadata)
        await self._send_event(
            message.chat_id,
            build_message_event(session_id=session_id, message=message),
        )

    async def send_progress(
        self,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        *,
        tool_hint: bool = False,
    ) -> None:
        """发送进度事件。"""
        await self._send_event(
            chat_id,
            build_progress_event(
                session_id=self._session_id_for(chat_id, metadata),
                content=content,
                tool_hint=tool_hint,
            ),
        )

    async def send_delta(
        self,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """发送正文增量或片段结束事件。"""
        session_id = self._session_id_for(chat_id, metadata)
        metadata = dict(metadata or {})
        if metadata.get("_stream_end"):
            await self._send_event(
                chat_id,
                build_stream_end_event(
                    session_id=session_id,
                    resuming=bool(metadata.get("_resuming", False)),
                ),
            )
            return
        await self._send_event(
            chat_id,
            build_delta_event(session_id=session_id, content=content),
        )

    async def _handle_connection(self, connection: ServerConnection) -> None:
        """处理单个 websocket 连接。"""
        request = connection.request
        assert request is not None
        parsed = urlsplit(request.path)
        query = parse_qs(parsed.query, keep_blank_values=False)
        client_id = (query.get("client_id") or [""])[0].strip()
        chat_id = ((query.get("chat_id") or [client_id])[0] or client_id).strip()
        default_session = ((query.get("session_id") or [""])[0] or "").strip() or default_session_id(
            self.name,
            chat_id,
        )
        self._connections[chat_id] = connection
        await self._send_on_connection(
            connection,
            build_ready_event(
                channel=self.name,
                client_id=client_id,
                chat_id=chat_id,
                session_id=default_session,
            ),
        )
        try:
            async for raw in connection:
                await self._handle_frame(
                    connection,
                    client_id=client_id,
                    chat_id=chat_id,
                    default_session=default_session,
                    raw=raw,
                )
        except ConnectionClosed:
            pass
        finally:
            existing = self._connections.get(chat_id)
            if existing is connection:
                self._connections.pop(chat_id, None)

    async def _handle_frame(
        self,
        connection: ServerConnection,
        *,
        client_id: str,
        chat_id: str,
        default_session: str,
        raw: str,
    ) -> None:
        """解析一条客户端 frame。"""
        payload = self._parse_frame(raw)
        if isinstance(payload, str):
            override_session = (
                default_session
                if default_session != default_session_id(self.name, chat_id)
                else None
            )
            await self.publish_input(
                client_id=client_id,
                chat_id=chat_id,
                content=payload,
                session_id=override_session,
                metadata={"_session_id": default_session},
            )
            return

        req_type = str(payload.get("type") or "").strip()
        session_id = str(payload.get("session_id") or default_session).strip() or default_session
        if req_type == "input":
            content = payload.get("content")
            if not isinstance(content, str) or not content:
                await self._send_on_connection(
                    connection,
                    build_error_event("input request requires non-empty content", session_id=session_id),
                )
                return
            override_session = (
                session_id
                if session_id != default_session_id(self.name, chat_id)
                else None
            )
            await self.publish_input(
                client_id=client_id,
                chat_id=chat_id,
                content=content,
                session_id=override_session,
                metadata={"_session_id": session_id},
            )
            return
        if req_type == "interrupt":
            result = self.runtime.interrupt_session(session_id)
            await self._send_on_connection(connection, build_interrupt_result_event(result))
            return
        if req_type == "reset_session":
            self.runtime.reset_session(session_id)
            await self._send_on_connection(connection, build_reset_done_event(session_id=session_id))
            return
        if req_type == "status":
            snapshot = await self.runtime.get_status_snapshot(session_id)
            await self._send_on_connection(
                connection,
                build_status_result_event(snapshot, session_id=session_id),
            )
            return
        await self._send_on_connection(
            connection,
            build_error_event(f"unknown request type: {req_type or '<empty>'}", session_id=session_id),
        )

    @staticmethod
    def _parse_frame(raw: str) -> str | dict[str, Any]:
        """把 websocket frame 解析成纯文本输入或结构化请求。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(data, dict):
            return data
        return raw

    def _session_id_for(self, chat_id: str, metadata: dict[str, Any] | None) -> str:
        """从 outbound metadata 里恢复会话键。"""
        metadata = dict(metadata or {})
        raw = metadata.get("_session_id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return default_session_id(self.name, chat_id)

    async def _send_event(self, chat_id: str, payload: dict[str, Any]) -> None:
        """按 chat_id 找到连接并发送事件。"""
        connection = self._connections.get(chat_id)
        if connection is None:
            logger.info("Drop websocket outbound for {}: no active connection", chat_id)
            return
        await self._send_on_connection(connection, payload)

    async def _send_on_connection(
        self,
        connection: ServerConnection,
        payload: dict[str, Any],
    ) -> None:
        """向指定连接发送 JSON 事件。"""
        async with self._send_lock:
            await connection.send(json.dumps(payload, ensure_ascii=False))
