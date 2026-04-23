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
) -> None:
    """运行交互聊天循环，并通过 bus 与 agent 协作。"""
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
    bus_task = asyncio.create_task(agent_loop.run())
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
                    is_tool_hint = message.metadata.get("_tool_hint", False)
                    channel_config = agent_loop.channels_config
                    if channel_config and is_tool_hint and not channel_config.send_tool_hints:
                        continue
                    if channel_config and not is_tool_hint and not channel_config.send_progress:
                        continue
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

                await turn_done.wait()

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
        agent_loop.stop()
        outbound_task.cancel()
        await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
        await agent_loop.close_mcp()
