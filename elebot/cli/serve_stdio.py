"""`elebot serve stdio` 的 JSONL 入口实现。"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Awaitable, Callable

from elebot.runtime.app import ElebotRuntime
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
)


class StdioServer:
    """基于标准输入输出的 JSONL 协议入口。"""

    def __init__(
        self,
        runtime: ElebotRuntime,
        *,
        reader: Callable[[], Awaitable[str | None]] | None = None,
        writer: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        """绑定 runtime 和可替换的 IO。"""
        self.runtime = runtime
        self._reader = reader or self._read_line
        self._writer = writer or self._write_event
        self._active_runs: dict[str, asyncio.Task[None]] = {}
        self._write_lock = asyncio.Lock()

    async def serve(self) -> None:
        """持续读取 JSONL 请求并复用 runtime 处理。"""
        await self._emit(build_ready_event(transport="stdio"))
        try:
            while True:
                line = await self._reader()
                if line is None:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                request, error = self._parse_request(stripped)
                if error is not None:
                    await self._emit(error)
                    continue
                if request is None:
                    continue
                await self._handle_request(request)
        finally:
            if self._active_runs:
                await asyncio.gather(*self._active_runs.values(), return_exceptions=True)
            await self.runtime.close()

    async def _handle_request(self, request: dict[str, Any]) -> None:
        """处理一条结构化请求。"""
        req_type = str(request.get("type") or "").strip()
        session_id = str(request.get("session_id") or "").strip()
        if req_type == "input":
            content = request.get("content")
            if not session_id:
                await self._emit(build_error_event("input request requires session_id"))
                return
            if not isinstance(content, str) or not content:
                await self._emit(build_error_event("input request requires non-empty content", session_id=session_id))
                return
            if session_id in self._active_runs:
                await self._emit(build_error_event("session is already running", session_id=session_id))
                return
            task = asyncio.create_task(self._run_input(session_id, content))
            self._active_runs[session_id] = task
            task.add_done_callback(lambda _task, key=session_id: self._active_runs.pop(key, None))
            return

        if req_type == "interrupt":
            if not session_id:
                await self._emit(build_error_event("interrupt request requires session_id"))
                return
            result = self.runtime.interrupt_session(session_id)
            await self._emit(build_interrupt_result_event(result))
            return

        if req_type == "reset_session":
            if not session_id:
                await self._emit(build_error_event("reset_session request requires session_id"))
                return
            self.runtime.reset_session(session_id)
            await self._emit(build_reset_done_event(session_id=session_id))
            return

        if req_type == "status":
            if not session_id:
                await self._emit(build_error_event("status request requires session_id"))
                return
            snapshot = await self.runtime.get_status_snapshot(session_id)
            await self._emit(build_status_result_event(snapshot, session_id=session_id))
            return

        await self._emit(build_error_event(f"unknown request type: {req_type or '<empty>'}", session_id=session_id or None))

    async def _run_input(self, session_id: str, content: str) -> None:
        """执行一轮直连请求，并把过程事件写回 JSONL。"""

        async def on_progress(text: str, *, tool_hint: bool = False) -> None:
            await self._emit(build_progress_event(session_id=session_id, content=text, tool_hint=tool_hint))

        async def on_stream(delta: str) -> None:
            await self._emit(build_delta_event(session_id=session_id, content=delta))

        async def on_stream_end(*, resuming: bool = False) -> None:
            await self._emit(build_stream_end_event(session_id=session_id, resuming=resuming))

        try:
            response = await self.runtime.run_once(
                content,
                session_id=session_id,
                on_progress=on_progress,
                on_stream=on_stream,
                on_stream_end=on_stream_end,
            )
        except Exception as exc:
            await self._emit(build_error_event(str(exc), session_id=session_id))
            return
        if response is None:
            return
        await self._emit(build_message_event(session_id=session_id, message=response))

    def _parse_request(self, raw: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """把一行 JSON 解析成请求对象。"""
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            return None, build_error_event("invalid JSON request")
        if not isinstance(request, dict):
            return None, build_error_event("request must be a JSON object")
        return request, None

    async def _emit(self, payload: dict[str, Any]) -> None:
        """输出一条结构化事件。"""
        async with self._write_lock:
            await self._writer(payload)

    @staticmethod
    async def _read_line() -> str | None:
        """异步读取 stdin 的下一行。"""
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":
            return None
        return line

    @staticmethod
    async def _write_event(payload: dict[str, Any]) -> None:
        """把结构化事件写成一行 JSON。"""
        text = json.dumps(payload, ensure_ascii=False)
        await asyncio.to_thread(sys.stdout.write, f"{text}\n")
        await asyncio.to_thread(sys.stdout.flush)
