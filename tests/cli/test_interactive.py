import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from elebot.bus.events import OutboundMessage
from elebot.cli import interactive


class _FakeBus:
    def __init__(self) -> None:
        self.inbound_messages = []
        self._outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, message) -> None:
        self.inbound_messages.append(message)
        base_meta = dict(message.metadata or {})
        await self._outbound.put(
            OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="hello",
                metadata={**base_meta, "_stream_delta": True},
            )
        )
        await self._outbound.put(
            OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="",
                metadata={**base_meta, "_stream_end": True},
            )
        )
        await self._outbound.put(
            OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="",
                metadata={**base_meta, "_streamed": True},
            )
        )

    async def consume_outbound(self) -> OutboundMessage:
        return await self._outbound.get()


class _FakeAgentLoop:
    def __init__(self) -> None:
        self.channels_config = None
        self._stop = asyncio.Event()
        self.stop_called = False
        self.close_mcp = AsyncMock()

    async def run(self) -> None:
        await self._stop.wait()

    def stop(self) -> None:
        self.stop_called = True
        self._stop.set()


class _FakeInterruptResult:
    def __init__(self, *, accepted: bool = True, already_interrupting: bool = False) -> None:
        self.accepted = accepted
        self.already_interrupting = already_interrupting


class _FakeInterruptWatcher:
    def __init__(self, *, trigger: bool) -> None:
        self._trigger = trigger
        self.closed = False

    async def wait(self) -> None:
        if self._trigger:
            await asyncio.sleep(0)
            return
        await asyncio.sleep(60)

    def close(self) -> None:
        self.closed = True


class _FakeRenderer:
    instances = []

    def __init__(self, **_kwargs) -> None:
        self.streamed = False
        self.spinner = None
        self.deltas = []
        self.ended = []
        self.close = AsyncMock()
        self.stop_for_input_calls = 0
        self.__class__.instances.append(self)

    async def on_delta(self, delta: str) -> None:
        self.streamed = True
        self.deltas.append(delta)

    async def on_end(self, *, resuming: bool = False) -> None:
        self.ended.append(resuming)

    def stop_for_input(self) -> None:
        self.stop_for_input_calls += 1


class _FakePreambleRenderer(_FakeRenderer):
    async def on_end(self, *, resuming: bool = False):
        self.ended.append(resuming)
        if resuming:
            return ["好的，我来设置 2 分钟后打开微信。"]
        return None


@pytest.mark.asyncio
async def test_run_interactive_loop_routes_streamed_turn_and_exits(monkeypatch):
    bus = _FakeBus()
    agent_loop = _FakeAgentLoop()
    restore_terminal = MagicMock()
    print_agent_response = MagicMock()
    _FakeRenderer.instances = []

    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr(
        "elebot.cli.interactive.read_interactive_input_async",
        AsyncMock(side_effect=["hello", "exit"]),
    )
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", restore_terminal)
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", print_agent_response)
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_response", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    await interactive.run_interactive_loop(
        agent_loop=agent_loop,
        bus=bus,
        session_id="cli:test",
        markdown=True,
        renderer_factory=_FakeRenderer,
    )

    assert len(bus.inbound_messages) == 1
    inbound = bus.inbound_messages[0]
    assert inbound.channel == "cli"
    assert inbound.chat_id == "test"
    assert inbound.content == "hello"
    assert inbound.metadata["_wants_stream"] is True
    assert isinstance(inbound.metadata.get("_interactive_turn_id"), str)

    renderer = _FakeRenderer.instances[0]
    assert renderer.deltas == ["hello"]
    assert renderer.ended == [False]
    renderer.close.assert_not_awaited()

    assert agent_loop.stop_called is True
    agent_loop.close_mcp.assert_awaited_once()
    restore_terminal.assert_called_once()
    print_agent_response.assert_not_called()


@pytest.mark.asyncio
async def test_run_interactive_loop_can_skip_agent_lifecycle_management(monkeypatch):
    """当生命周期已交给 runtime 托管时，交互层不应重复 stop/close 主循环。"""
    bus = _FakeBus()
    agent_loop = _FakeAgentLoop()
    restore_terminal = MagicMock()

    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr(
        "elebot.cli.interactive.read_interactive_input_async",
        AsyncMock(side_effect=["hello", "exit"]),
    )
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", restore_terminal)
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", MagicMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_response", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    await interactive.run_interactive_loop(
        agent_loop=agent_loop,
        bus=bus,
        session_id="cli:test",
        markdown=True,
        renderer_factory=_FakeRenderer,
        manage_agent_loop=False,
    )

    assert agent_loop.stop_called is False
    agent_loop.close_mcp.assert_not_awaited()
    restore_terminal.assert_called_once()


@pytest.mark.asyncio
async def test_run_interactive_loop_esc_interrupts_active_turn(monkeypatch):
    bus = _FakeBus()
    agent_loop = _FakeAgentLoop()
    restore_terminal = MagicMock()
    print_agent_response = MagicMock()
    print_progress = AsyncMock()
    interrupt_calls: list[tuple[str, str]] = []

    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr(
        "elebot.cli.interactive.read_interactive_input_async",
        AsyncMock(side_effect=["hello", "exit"]),
    )
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", restore_terminal)
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", print_agent_response)
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_response", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", print_progress)
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    def _interrupt(session_id: str, reason: str):
        interrupt_calls.append((session_id, reason))
        return _FakeInterruptResult(accepted=True)

    await interactive.run_interactive_loop(
        agent_loop=agent_loop,
        bus=bus,
        session_id="cli:test",
        markdown=True,
        renderer_factory=_FakeRenderer,
        interrupt_session=_interrupt,
        interrupt_watcher_factory=lambda: _FakeInterruptWatcher(trigger=True),
    )

    assert interrupt_calls == [("cli:test", "user_interrupt")]
    print_progress.assert_any_await("正在中断当前回复...", None)
    restore_terminal.assert_called_once()


@pytest.mark.asyncio
async def test_run_interactive_loop_ignores_interrupt_without_watcher(monkeypatch):
    bus = _FakeBus()
    agent_loop = _FakeAgentLoop()
    restore_terminal = MagicMock()
    interrupt_calls: list[tuple[str, str]] = []

    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr(
        "elebot.cli.interactive.read_interactive_input_async",
        AsyncMock(side_effect=["hello", "exit"]),
    )
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", restore_terminal)
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", MagicMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_response", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    def _interrupt(session_id: str, reason: str):
        interrupt_calls.append((session_id, reason))
        return _FakeInterruptResult(accepted=True)

    await interactive.run_interactive_loop(
        agent_loop=agent_loop,
        bus=bus,
        session_id="cli:test",
        markdown=True,
        renderer_factory=_FakeRenderer,
        interrupt_session=_interrupt,
        interrupt_watcher_factory=lambda: None,
    )

    assert interrupt_calls == []
    restore_terminal.assert_called_once()


@pytest.mark.asyncio
async def test_run_interactive_loop_renders_tool_preamble_as_progress_lines(monkeypatch):
    class _PreambleBus(_FakeBus):
        async def publish_inbound(self, message) -> None:
            self.inbound_messages.append(message)
            base_meta = dict(message.metadata or {})
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="好的，我来设置 2 分钟后打开微信。",
                    metadata={**base_meta, "_stream_delta": True},
                )
            )
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="",
                    metadata={**base_meta, "_stream_end": True, "_resuming": True},
                )
            )
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content='cron("add")',
                    metadata={**base_meta, "_progress": True},
                )
            )
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="已设置！",
                    metadata={**base_meta, "_stream_delta": True},
                )
            )
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="",
                    metadata={**base_meta, "_stream_end": True},
                )
            )
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="",
                    metadata={**base_meta, "_streamed": True},
                )
            )

    bus = _PreambleBus()
    agent_loop = _FakeAgentLoop()
    print_progress = AsyncMock()

    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr(
        "elebot.cli.interactive.read_interactive_input_async",
        AsyncMock(side_effect=["2 分钟后打开微信", "exit"]),
    )
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", MagicMock())
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", MagicMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_response", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", print_progress)
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    await interactive.run_interactive_loop(
        agent_loop=agent_loop,
        bus=bus,
        session_id="cli:test",
        markdown=True,
        renderer_factory=_FakePreambleRenderer,
    )

    texts = [call.args[0] for call in print_progress.await_args_list]
    assert texts[:2] == ["好的，我来设置 2 分钟后打开微信。", 'cron("add")']


@pytest.mark.asyncio
async def test_run_interactive_loop_buffers_background_notifications_until_active_turn_finishes(monkeypatch):
    class _SlowTurnBus(_FakeBus):
        async def publish_inbound(self, message) -> None:
            self.inbound_messages.append(message)
            base_meta = dict(message.metadata or {})
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="正在处理",
                    metadata={**base_meta, "_stream_delta": True},
                )
            )
            await asyncio.sleep(0.05)
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="",
                    metadata={**base_meta, "_stream_end": True},
                )
            )
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="",
                    metadata={**base_meta, "_streamed": True},
                )
            )

    bus = _SlowTurnBus()
    agent_loop = _FakeAgentLoop()
    printed: list[str] = []
    order: list[tuple[str, str]] = []
    inbound_published = asyncio.Event()

    async def fake_read_input() -> str:
        return "hello" if not inbound_published.is_set() else "exit"

    original_publish_inbound = bus.publish_inbound

    async def publish_inbound_and_record(message) -> None:
        order.append(("inbound", message.content))
        inbound_published.set()
        await original_publish_inbound(message)

    bus.publish_inbound = publish_inbound_and_record  # type: ignore[method-assign]

    async def emit_background_notification() -> None:
        await inbound_published.wait()
        await bus._outbound.put(
            OutboundMessage(
                channel="cli",
                chat_id="test",
                content="微信已打开 ✅",
                metadata={},
            )
        )

    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.read_interactive_input_async", fake_read_input)
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", MagicMock())
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", MagicMock())
    monkeypatch.setattr(
        "elebot.cli.interactive.print_interactive_response",
        AsyncMock(side_effect=lambda content, **_kwargs: printed.append(content) or order.append(("notify", content))),
    )
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    background_task = asyncio.create_task(emit_background_notification())
    try:
        await interactive.run_interactive_loop(
            agent_loop=agent_loop,
            bus=bus,
            session_id="cli:test",
            markdown=True,
            renderer_factory=_FakeRenderer,
        )
    finally:
        await asyncio.gather(background_task, return_exceptions=True)

    assert printed == ["微信已打开 ✅"]
    assert order[0] == ("inbound", "hello")
    assert order[1] == ("notify", "微信已打开 ✅")


@pytest.mark.asyncio
async def test_run_interactive_loop_preserves_background_notification_order(monkeypatch):
    class _SlowTurnBus(_FakeBus):
        async def publish_inbound(self, message) -> None:
            self.inbound_messages.append(message)
            base_meta = dict(message.metadata or {})
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="准备中",
                    metadata={**base_meta, "_stream_delta": True},
                )
            )
            await asyncio.sleep(0.05)
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="",
                    metadata={**base_meta, "_stream_end": True},
                )
            )
            await self._outbound.put(
                OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="",
                    metadata={**base_meta, "_streamed": True},
                )
            )

    bus = _SlowTurnBus()
    agent_loop = _FakeAgentLoop()
    printed: list[str] = []
    inbound_published = asyncio.Event()

    async def fake_read_input() -> str:
        return "hello" if not inbound_published.is_set() else "exit"

    original_publish_inbound = bus.publish_inbound

    async def publish_inbound_and_mark(message) -> None:
        inbound_published.set()
        await original_publish_inbound(message)

    bus.publish_inbound = publish_inbound_and_mark  # type: ignore[method-assign]

    async def emit_background_notifications() -> None:
        await inbound_published.wait()
        for content in ("任务 A 已完成", "任务 B 已完成"):
            await bus._outbound.put(
                OutboundMessage(
                    channel="cli",
                    chat_id="test",
                    content=content,
                    metadata={},
                )
            )
    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.read_interactive_input_async", fake_read_input)
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", MagicMock())
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", MagicMock())
    monkeypatch.setattr(
        "elebot.cli.interactive.print_interactive_response",
        AsyncMock(side_effect=lambda content, **_kwargs: printed.append(content)),
    )
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    background_task = asyncio.create_task(emit_background_notifications())
    try:
        await interactive.run_interactive_loop(
            agent_loop=agent_loop,
            bus=bus,
            session_id="cli:test",
            markdown=True,
            renderer_factory=_FakeRenderer,
        )
    finally:
        await asyncio.gather(background_task, return_exceptions=True)

    assert printed == ["任务 A 已完成", "任务 B 已完成"]


@pytest.mark.asyncio
async def test_run_interactive_loop_shows_background_notifications_immediately_when_agent_idle(monkeypatch):
    bus = _FakeBus()
    agent_loop = _FakeAgentLoop()
    printed: list[str] = []
    first_read_started = asyncio.Event()
    allow_first_read_return = asyncio.Event()
    notification_printed = asyncio.Event()
    order: list[tuple[str, str]] = []

    async def fake_read_input() -> str:
        if not first_read_started.is_set():
            first_read_started.set()
            await allow_first_read_return.wait()
            return "exit"
        return "exit"

    async def emit_background_notification() -> None:
        await first_read_started.wait()
        await bus._outbound.put(
            OutboundMessage(
                channel="cli",
                chat_id="test",
                content="提醒已经到了",
                metadata={},
            )
        )

    async def fake_print_interactive_response(content, **_kwargs):
        printed.append(content)
        order.append(("notify", content))
        notification_printed.set()

    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.read_interactive_input_async", fake_read_input)
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", MagicMock())
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", MagicMock())
    monkeypatch.setattr(
        "elebot.cli.interactive.print_interactive_response",
        AsyncMock(side_effect=fake_print_interactive_response),
    )
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    background_task = asyncio.create_task(emit_background_notification())
    loop_task = asyncio.create_task(
        interactive.run_interactive_loop(
            agent_loop=agent_loop,
            bus=bus,
            session_id="cli:test",
            markdown=True,
            renderer_factory=_FakeRenderer,
        )
    )
    try:
        await asyncio.wait_for(notification_printed.wait(), timeout=2)
        assert printed == ["提醒已经到了"]
        allow_first_read_return.set()
        await loop_task
    finally:
        allow_first_read_return.set()
        await asyncio.gather(background_task, loop_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_run_interactive_loop_active_watcher_can_finish_without_interrupt(monkeypatch):
    bus = _FakeBus()
    agent_loop = _FakeAgentLoop()
    restore_terminal = MagicMock()
    interrupt_calls: list[tuple[str, str]] = []

    monkeypatch.setattr("elebot.cli.interactive.init_prompt_session", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive._install_signal_handlers", lambda: None)
    monkeypatch.setattr(
        "elebot.cli.interactive.read_interactive_input_async",
        AsyncMock(side_effect=["hello", "exit"]),
    )
    monkeypatch.setattr("elebot.cli.interactive.flush_pending_tty_input", lambda: None)
    monkeypatch.setattr("elebot.cli.interactive.restore_terminal", restore_terminal)
    monkeypatch.setattr("elebot.cli.interactive.print_agent_response", MagicMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_response", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.print_interactive_progress_line", AsyncMock())
    monkeypatch.setattr("elebot.cli.interactive.console.print", lambda *_args, **_kwargs: None)

    def _interrupt(session_id: str, reason: str):
        interrupt_calls.append((session_id, reason))
        return _FakeInterruptResult(accepted=True)

    await interactive.run_interactive_loop(
        agent_loop=agent_loop,
        bus=bus,
        session_id="cli:test",
        markdown=True,
        renderer_factory=_FakeRenderer,
        interrupt_session=_interrupt,
        interrupt_watcher_factory=lambda: _FakeInterruptWatcher(trigger=False),
    )

    assert interrupt_calls == []
    restore_terminal.assert_called_once()
