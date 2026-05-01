"""轻量历史压缩。"""

from __future__ import annotations

import asyncio
import weakref
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from elebot.agent.memory.store import MemoryStore
from elebot.agent.tokens import estimate_message_tokens, estimate_prompt_tokens_chain
from elebot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from elebot.providers.base import LLMProvider
    from elebot.session.manager import Session, SessionManager


class Consolidator:
    """在上下文超预算时，把旧消息压缩成历史摘要。"""

    _MAX_CONSOLIDATION_ROUNDS = 5
    _MAX_CHUNK_MESSAGES = 60  # 单轮压缩条数设上限，避免一次摘要过大而失稳。
    _SAFETY_BUFFER = 1024  # 预留额外余量，抵消 token 估算偏差带来的越界风险。

    def __init__(
        self,
        store: MemoryStore,
        provider: LLMProvider,
        model: str,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable[..., list[dict[str, Any]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        max_completion_tokens: int = 4096,
    ):
        """绑定压缩流程所需的会话、模型和估算回调。

        参数:
            store: 记忆存储 owner。
            provider: 当前主模型 provider。
            model: 默认模型名。
            sessions: 会话管理器。
            context_window_tokens: 上下文窗口大小。
            build_messages: 构造 prompt 消息的回调。
            get_tool_definitions: 获取工具定义的回调。
            max_completion_tokens: 本轮保留给模型输出的 token 上限。

        返回:
            无返回值。
        """
        self.store = store
        self.provider = provider
        self.model = model
        self.sessions = sessions
        self.context_window_tokens = context_window_tokens
        self.max_completion_tokens = max_completion_tokens
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """返回某个会话共享的压缩锁。

        参数:
            session_key: 会话唯一键。

        返回:
            该会话对应的异步锁实例。
        """
        return self._locks.setdefault(session_key, asyncio.Lock())

    def pick_consolidation_boundary(
        self,
        session: Session,
        tokens_to_remove: int,
    ) -> tuple[int, int] | None:
        """选择一个安全的压缩边界。

        参数:
            session: 当前会话对象。
            tokens_to_remove: 期望至少移除的旧 token 数。

        返回:
            `(结束下标, 已移除 token 数)`；找不到安全边界时返回 ``None``。
        """
        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None

        removed_tokens = 0
        last_boundary: tuple[int, int] | None = None
        for index in range(start, len(session.messages)):
            message = session.messages[index]
            if index > start and message.get("role") == "user":
                last_boundary = (index, removed_tokens)
                if removed_tokens >= tokens_to_remove:
                    return last_boundary
            removed_tokens += estimate_message_tokens(message)

        return last_boundary

    def _cap_consolidation_boundary(
        self,
        session: Session,
        end_idx: int,
    ) -> int | None:
        """在不打断用户轮次的前提下限制单轮压缩块大小。"""
        start = session.last_consolidated
        if end_idx - start <= self._MAX_CHUNK_MESSAGES:
            return end_idx

        capped_end = start + self._MAX_CHUNK_MESSAGES
        for index in range(capped_end, start, -1):
            if session.messages[index].get("role") == "user":
                return index
        return None

    def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        """估算当前会话在正常视图下的提示词大小。

        参数:
            session: 需要估算的会话对象。

        返回:
            `(估算 token 数, 估算来源说明)` 元组。
        """
        history = session.get_history(max_messages=0)
        channel, chat_id = (
            session.key.split(":", 1) if ":" in session.key else (None, None)
        )
        probe_messages = self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            chat_id=chat_id,
        )
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )

    async def archive(self, messages: list[dict]) -> str | None:
        """把一段旧消息总结后写入历史文件。

        参数:
            messages: 需要归档的消息数组。

        返回:
            摘要成功时返回摘要文本；无消息或归档失败时返回 ``None``。
        """
        if not messages:
            return None
        try:
            formatted = MemoryStore._format_messages(messages)
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": render_template(
                            "CONSOLIDATOR_ARCHIVE.md",
                            strip=True,
                        ),
                    },
                    {"role": "user", "content": formatted},
                ],
                tools=None,
                tool_choice=None,
            )
            summary = response.content or "[no summary]"
            self.store.append_history(summary)
            return summary
        except Exception:
            logger.warning("Consolidation LLM call failed, raw-dumping to history")
            self.store.raw_archive(messages)
            return None

    async def maybe_consolidate_by_tokens(self, session: Session) -> None:
        """在提示词超预算时循环压缩旧消息。

        参数:
            session: 需要检查并压缩的会话对象。

        返回:
            无返回值。
        """
        if not session.messages or self.context_window_tokens <= 0:
            return

        lock = self.get_lock(session.key)
        async with lock:
            budget = (
                self.context_window_tokens
                - self.max_completion_tokens
                - self._SAFETY_BUFFER
            )
            target = budget // 2
            try:
                estimated, source = self.estimate_session_prompt_tokens(session)
            except Exception:
                logger.exception("Token estimation failed for {}", session.key)
                estimated, source = 0, "error"
            if estimated <= 0:
                return
            if estimated < budget:
                unconsolidated_count = len(session.messages) - session.last_consolidated
                logger.debug(
                    "Token consolidation idle {}: {}/{} via {}, msgs={}",
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                    unconsolidated_count,
                )
                return

            for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
                if estimated <= target:
                    return

                boundary = self.pick_consolidation_boundary(
                    session,
                    max(1, estimated - target),
                )
                if boundary is None:
                    logger.debug(
                        "Token consolidation: no safe boundary for {} (round {})",
                        session.key,
                        round_num,
                    )
                    return

                end_idx = self._cap_consolidation_boundary(session, boundary[0])
                if end_idx is None:
                    logger.debug(
                        "Token consolidation: no capped boundary for {} (round {})",
                        session.key,
                        round_num,
                    )
                    return

                chunk = session.messages[session.last_consolidated : end_idx]
                if not chunk:
                    return

                logger.info(
                    "Token consolidation round {} for {}: {}/{} via {}, chunk={} msgs",
                    round_num,
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                    len(chunk),
                )
                if not await self.archive(chunk):
                    return
                session.last_consolidated = end_idx
                self.sessions.save(session)

                try:
                    estimated, source = self.estimate_session_prompt_tokens(session)
                except Exception:
                    logger.exception("Token estimation failed for {}", session.key)
                    estimated, source = 0, "error"
                if estimated <= 0:
                    return
