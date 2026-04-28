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
        await self._outbound.put(
            OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="hello",
                metadata={"_stream_delta": True},
            )
        )
        await self._outbound.put(
            OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="",
                metadata={"_stream_end": True},
            )
        )
        await self._outbound.put(
            OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="",
                metadata={"_streamed": True},
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
    assert inbound.metadata == {"_wants_stream": True}

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
