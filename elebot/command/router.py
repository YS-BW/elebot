"""最小化 slash 命令路由表。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from elebot.bus.events import InboundMessage, OutboundMessage
    from elebot.session.manager import Session

Handler = Callable[["CommandContext"], Awaitable["OutboundMessage | None"]]


@dataclass
class CommandContext:
    """命令处理器生成响应所需的上下文。"""

    msg: InboundMessage
    session: Session | None
    key: str
    raw: str
    args: str = ""
    loop: Any = None


class CommandRouter:
    """基于字典和前缀表的命令分发器。"""

    def __init__(self) -> None:
        """初始化命令路由容器。"""
        self._priority: dict[str, Handler] = {}
        self._exact: dict[str, Handler] = {}
        self._prefix: list[tuple[str, Handler]] = []
        self._interceptors: list[Handler] = []

    def priority(self, cmd: str, handler: Handler) -> None:
        """注册优先级命令。"""
        self._priority[cmd] = handler

    def exact(self, cmd: str, handler: Handler) -> None:
        """注册精确匹配命令。"""
        self._exact[cmd] = handler

    def prefix(self, pfx: str, handler: Handler) -> None:
        """注册前缀匹配命令。"""
        self._prefix.append((pfx, handler))
        self._prefix.sort(key=lambda p: len(p[0]), reverse=True)

    def intercept(self, handler: Handler) -> None:
        """注册兜底拦截器。"""
        self._interceptors.append(handler)

    def is_priority(self, text: str) -> bool:
        """判断文本是否命中优先级命令。"""
        return text.strip().lower() in self._priority

    async def dispatch_priority(self, ctx: CommandContext) -> OutboundMessage | None:
        """分发优先级命令。"""
        handler = self._priority.get(ctx.raw.lower())
        if handler:
            return await handler(ctx)
        return None

    async def dispatch(self, ctx: CommandContext) -> OutboundMessage | None:
        """按精确、前缀、拦截器顺序分发普通命令。"""
        cmd = ctx.raw.lower()

        if handler := self._exact.get(cmd):
            return await handler(ctx)

        for pfx, handler in self._prefix:
            if cmd.startswith(pfx):
                ctx.args = ctx.raw[len(pfx):]
                return await handler(ctx)

        for interceptor in self._interceptors:
            result = await interceptor(ctx)
            if result is not None:
                return result

        return None
