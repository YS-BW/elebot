"""负责 prompt_toolkit 交互循环。"""

from __future__ import annotations

import asyncio
import signal
import sys
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
from elebot.cli.stream import StreamRenderer, ThinkingSpinner

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

    thinking: ThinkingSpinner | None = None
    bus_task = (
        asyncio.create_task(agent_loop.run()) if manage_agent_loop else None
    )
    turn_done = asyncio.Event()
    turn_done.set()
    turn_response: list[tuple[str, dict[str, Any]]] = []
    renderer: StreamRenderer | None = None

    async def _consume_outbound() -> None:
        nonlocal renderer, thinking

        while True:
            try:
                message = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

                if message.metadata.get("_stream_delta"):
                    if renderer:
                        await renderer.on_delta(message.content)
                    continue
                if message.metadata.get("_stream_end"):
                    if renderer:
                        await renderer.on_end(
                            resuming=message.metadata.get("_resuming", False),
                        )
                    continue
                if message.metadata.get("_streamed"):
                    turn_done.set()
                    continue

                if message.metadata.get("_progress"):
                    await print_interactive_progress_line(message.content, thinking)
                    continue

                if not turn_done.is_set():
                    if message.content:
                        turn_response.append((message.content, dict(message.metadata or {})))
                    turn_done.set()
                elif message.content:
                    await print_interactive_response(
                        message.content,
                        render_markdown=markdown,
                        metadata=message.metadata,
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
                if not command:
                    continue

                if is_exit_command(command):
                    restore_terminal()
                    console.print("\nGoodbye!")
                    break

                turn_done.clear()
                turn_response.clear()
                renderer = renderer_factory(render_markdown=markdown)
                thinking = renderer.spinner

                await bus.publish_inbound(
                    InboundMessage(
                        channel=cli_channel,
                        sender_id="user",
                        chat_id=cli_chat_id,
                        content=user_input,
                        metadata={"_wants_stream": True},
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
                                interrupt_task.result()
                                interrupt_result = interrupt_session(
                                    session_id,
                                    "user_interrupt",
                                )
                                if (
                                    getattr(interrupt_result, "accepted", False)
                                    or getattr(interrupt_result, "already_interrupting", False)
                                ):
                                    await print_interactive_progress_line(
                                        "正在中断当前回复...",
                                        thinking,
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
                thinking = renderer.spinner if renderer else None
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
