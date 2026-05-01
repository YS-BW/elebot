"""负责 prompt_toolkit 交互循环。"""

from __future__ import annotations

import asyncio
import signal
import sys
import uuid
from collections import deque
from typing import Any, Callable

from elebot import __logo__
from elebot.bus.events import InboundMessage
from elebot.cli.history import (
    flush_pending_tty_input,
    init_prompt_session,
    read_interactive_input_async,
    restore_terminal,
)
from elebot.cli.keys import create_interrupt_watcher
from elebot.cli.render import (
    console,
    print_agent_response,
    print_interactive_progress_line,
    print_interactive_response,
)
from elebot.cli.stream import StreamRenderer

EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}


def is_exit_command(command: str) -> bool:
    """判断输入是否表示结束交互会话。"""
    return command.lower() in EXIT_COMMANDS


def _install_signal_handlers() -> None:
    """捕获常见退出信号，优先恢复终端状态再退出。"""

    def _handle_signal(signum, _frame) -> None:
        signal_name = signal.Signals(signum).name
        restore_terminal()
        console.print(f"\nReceived {signal_name}, goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _handle_signal)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)


async def run_interactive_loop(
    *,
    agent_loop: Any,
    bus: Any,
    session_id: str,
    markdown: bool,
    renderer_factory: Callable[..., StreamRenderer] = StreamRenderer,
    manage_agent_loop: bool = True,
    interrupt_session: Callable[[str, str], Any] | None = None,
    interrupt_watcher_factory: Callable[[], Any | None] = create_interrupt_watcher,
) -> None:
    """运行交互聊天循环，并通过 bus 与 agent 协作。

    参数:
        agent_loop: 当前会话复用的主循环对象。
        bus: 与主循环共享的消息总线。
        session_id: 当前交互会话标识。
        markdown: 是否按 Markdown 渲染回复。
        renderer_factory: 流式渲染器工厂，便于测试注入。
        manage_agent_loop: 是否由交互循环负责启动和关闭 `agent_loop`。
        interrupt_session: 当前活跃轮次的中断回调。
        interrupt_watcher_factory: 中断按键监听器工厂。

    返回:
        无返回值。
    """
    init_prompt_session()
    console.print(
        f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n"
    )

    if ":" in session_id:
        cli_channel, cli_chat_id = session_id.split(":", 1)
    else:
        cli_channel, cli_chat_id = "cli", session_id

    _install_signal_handlers()

    bus_task = (
        asyncio.create_task(agent_loop.run()) if manage_agent_loop else None
    )
    turn_done = asyncio.Event()
    turn_done.set()
    turn_response: list[tuple[str, dict[str, Any]]] = []
    pending_notifications: deque[tuple[str, dict[str, Any]]] = deque()
    renderer: StreamRenderer | None = None
    active_turn_id: str | None = None

    async def _drain_pending_notifications() -> None:
        """按顺序输出输入期间暂存的后台消息。"""
        while pending_notifications:
            content, metadata = pending_notifications.popleft()
            await print_interactive_response(
                content,
                render_markdown=markdown,
                metadata=metadata,
            )

    def _belongs_to_active_turn(metadata: dict[str, Any] | None) -> bool:
        """判断一条 outbound 是否属于当前正在处理的交互轮次。"""
        if active_turn_id is None:
            return False
        return (metadata or {}).get("_interactive_turn_id") == active_turn_id

    async def _print_active_turn_progress(
        text: str,
        *,
        tool_transition: bool = False,
    ) -> None:
        """把当前轮次的提示统一交给 renderer，避免 active turn 混用 prompt 重绘通道。"""
        if renderer is None:
            await print_interactive_progress_line(text, None)
            return
        if tool_transition:
            await renderer.on_tool_transition(text)
            return
        await renderer.on_progress(text)

    async def _consume_outbound() -> None:
        nonlocal renderer

        while True:
            try:
                message = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                metadata = dict(message.metadata or {})
                belongs_to_active_turn = _belongs_to_active_turn(metadata)

                if metadata.get("_stream_delta"):
                    if renderer and belongs_to_active_turn:
                        await renderer.on_delta(message.content)
                    continue
                if metadata.get("_stream_end"):
                    if renderer and belongs_to_active_turn:
                        await renderer.on_end(
                            resuming=metadata.get("_resuming", False),
                        )
                    continue
                if metadata.get("_streamed"):
                    if belongs_to_active_turn:
                        turn_done.set()
                    continue
                if metadata.get("_tool_transition"):
                    if belongs_to_active_turn:
                        await _print_active_turn_progress(
                            message.content,
                            tool_transition=True,
                        )
                    elif active_turn_id is not None:
                        pending_notifications.append((message.content, metadata))
                    elif message.content:
                        await print_interactive_progress_line(message.content, None)
                    continue

                if metadata.get("_progress"):
                    if belongs_to_active_turn:
                        await _print_active_turn_progress(message.content)
                    elif active_turn_id is not None:
                        pending_notifications.append((message.content, metadata))
                    elif message.content:
                        await print_interactive_progress_line(message.content, None)
                    continue

                if belongs_to_active_turn and not turn_done.is_set():
                    if message.content:
                        turn_response.append((message.content, metadata))
                    turn_done.set()
                elif active_turn_id is not None and message.content:
                    pending_notifications.append((message.content, metadata))
                elif message.content:
                    await print_interactive_response(
                        message.content,
                        render_markdown=markdown,
                        metadata=metadata,
                    )

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    outbound_task = asyncio.create_task(_consume_outbound())

    try:
        while True:
            try:
                flush_pending_tty_input()
                if renderer:
                    renderer.stop_for_input()
                user_input = await read_interactive_input_async()
                command = user_input.strip()

                if is_exit_command(command):
                    restore_terminal()
                    console.print("\nGoodbye!")
                    break

                await _drain_pending_notifications()
                if not command:
                    continue

                turn_done.clear()
                turn_response.clear()
                active_turn_id = uuid.uuid4().hex
                renderer = renderer_factory(render_markdown=markdown)

                await bus.publish_inbound(
                    InboundMessage(
                        channel=cli_channel,
                        sender_id="user",
                        chat_id=cli_chat_id,
                        content=user_input,
                        metadata={
                            "_wants_stream": True,
                            "_interactive_turn_id": active_turn_id,
                        },
                    )
                )

                watcher = interrupt_watcher_factory() if interrupt_session is not None else None
                interrupt_task: asyncio.Task[Any] | None = None
                turn_done_task = asyncio.create_task(turn_done.wait())
                try:
                    if watcher is not None:
                        interrupt_task = asyncio.create_task(watcher.wait())
                        while not turn_done.is_set():
                            wait_set = {turn_done_task}
                            if interrupt_task is not None:
                                wait_set.add(interrupt_task)
                            done, _pending = await asyncio.wait(
                                wait_set,
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if turn_done_task in done:
                                break
                            if interrupt_task is not None and interrupt_task in done:
                                if not interrupt_task.result():
                                    # 非真实 Esc 中断（如 Windows 平台限制），跳过
                                    interrupt_task = None
                                    continue
                                interrupt_result = interrupt_session(
                                    session_id,
                                    "user_interrupt",
                                )
                                if (
                                    getattr(interrupt_result, "accepted", False)
                                    or getattr(interrupt_result, "already_interrupting", False)
                                ):
                                    await _print_active_turn_progress(
                                        "正在中断当前回复...",
                                    )
                                interrupt_task = None
                                watcher.close()
                                await turn_done.wait()
                                break
                    else:
                        await turn_done.wait()
                finally:
                    turn_done_task.cancel()
                    if interrupt_task is not None:
                        interrupt_task.cancel()
                    if watcher is not None:
                        watcher.close()
                    await asyncio.gather(
                        *[
                            task
                            for task in (turn_done_task, interrupt_task)
                            if task is not None
                        ],
                        return_exceptions=True,
                    )

                if turn_response:
                    content, metadata = turn_response[0]
                    if content and not metadata.get("_streamed"):
                        if renderer:
                            await renderer.close()
                        print_agent_response(
                            content,
                            render_markdown=markdown,
                            metadata=metadata,
                        )
                elif renderer and not renderer.streamed:
                    await renderer.close()
                active_turn_id = None
                await _drain_pending_notifications()
            except KeyboardInterrupt:
                restore_terminal()
                console.print("\nGoodbye!")
                break
            except EOFError:
                restore_terminal()
                console.print("\nGoodbye!")
                break
    finally:
        if manage_agent_loop:
            agent_loop.stop()
        outbound_task.cancel()
        pending_tasks = [outbound_task]
        if bus_task is not None:
            pending_tasks.append(bus_task)
        await asyncio.gather(*pending_tasks, return_exceptions=True)
        if manage_agent_loop:
            await agent_loop.close_mcp()
