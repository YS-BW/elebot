"""空闲会话自动压缩模块。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

from elebot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from elebot.agent.memory import Consolidator


class AutoCompact:
    """按空闲时间主动归档会话前缀，并保留最近可继续对话的尾部消息。"""

    _RECENT_SUFFIX_MESSAGES = 8

    def __init__(
        self,
        sessions: SessionManager,
        consolidator: Consolidator,
        session_ttl_minutes: int = 0,
    ):
        """初始化自动压缩器。

        参数:
            sessions: 会话管理器，用于读取和保存会话。
            consolidator: 会话归档器，用于把旧消息压缩成摘要。
            session_ttl_minutes: 会话空闲多少分钟后触发压缩；小于等于 0 表示禁用。

        返回:
            None。
        """
        self.sessions = sessions
        self.consolidator = consolidator
        self._ttl = session_ttl_minutes
        self._archiving: set[str] = set()
        self._summaries: dict[str, tuple[str, datetime]] = {}

    def _is_expired(self, ts: datetime | str | None) -> bool:
        if self._ttl <= 0 or not ts:
            return False
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return (datetime.now() - ts).total_seconds() >= self._ttl * 60

    @staticmethod
    def _format_summary(text: str, last_active: datetime) -> str:
        idle_min = int((datetime.now() - last_active).total_seconds() / 60)
        return f"Inactive for {idle_min} minutes.\nPrevious conversation summary: {text}"

    def _split_unconsolidated(
        self, session: Session,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """把未归档消息拆成可归档前缀和需要保留的最近后缀。"""
        tail = list(session.messages[session.last_consolidated:])
        if not tail:
            return [], []

        probe = Session(
            key=session.key,
            messages=tail.copy(),
            created_at=session.created_at,
            updated_at=session.updated_at,
            metadata={},
            last_consolidated=0,
        )
        probe.retain_recent_legal_suffix(self._RECENT_SUFFIX_MESSAGES)
        kept = probe.messages
        cut = len(tail) - len(kept)
        return tail[:cut], kept

    def check_expired(self, schedule_background: Callable[[Coroutine], None]) -> None:
        """检查已过期会话并提交后台归档任务。

        参数:
            schedule_background: 后台任务调度函数，负责接收归档协程。

        返回:
            None。
        """
        for info in self.sessions.list_sessions():
            key = info.get("key", "")
            if key and key not in self._archiving and self._is_expired(info.get("updated_at")):
                self._archiving.add(key)
                logger.debug("Auto-compact: scheduling archival for {} (idle > {} min)", key, self._ttl)
                schedule_background(self._archive(key))

    async def _archive(self, key: str) -> None:
        try:
            self.sessions.invalidate(key)
            session = self.sessions.get_or_create(key)
            archive_msgs, kept_msgs = self._split_unconsolidated(session)
            if not archive_msgs and not kept_msgs:
                logger.debug("Auto-compact: skipping {}, no un-consolidated messages", key)
                session.updated_at = datetime.now()
                self.sessions.save(session)
                return

            last_active = session.updated_at
            summary = ""
            if archive_msgs:
                summary = await self.consolidator.archive(archive_msgs) or ""
            if summary and summary != "(nothing)":
                self._summaries[key] = (summary, last_active)
                session.metadata["_last_summary"] = {"text": summary, "last_active": last_active.isoformat()}
            session.messages = kept_msgs
            session.last_consolidated = 0
            session.updated_at = datetime.now()
            self.sessions.save(session)
            logger.info(
                "Auto-compact: archived {} (archived={}, kept={}, summary={})",
                key,
                len(archive_msgs),
                len(kept_msgs),
                bool(summary),
            )
        except Exception:
            logger.exception("Auto-compact: failed for {}", key)
        finally:
            self._archiving.discard(key)

    def prepare_session(self, session: Session, key: str) -> tuple[Session, str | None]:
        """在处理新消息前重新加载会话，并取出一次性恢复摘要。

        参数:
            session: 当前已加载的会话对象。
            key: 会话唯一标识。

        返回:
            包含最新会话对象和可选恢复摘要的元组。
        """
        if key in self._archiving or self._is_expired(session.updated_at):
            logger.info("Auto-compact: reloading session {} (archiving={})", key, key in self._archiving)
            session = self.sessions.get_or_create(key)
        # 优先消费内存摘要，避免进程未重启时重复读取持久化元数据。
        # 同步清理元数据副本，避免过期的 _last_summary 再次写回磁盘。
        entry = self._summaries.pop(key, None)
        if entry:
            session.metadata.pop("_last_summary", None)
            return session, self._format_summary(entry[0], entry[1])
        if "_last_summary" in session.metadata:
            meta = session.metadata.pop("_last_summary")
            self.sessions.save(session)
            return session, self._format_summary(meta["text"], datetime.fromisoformat(meta["last_active"]))
        return session, None
