import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts.prompt import CompleteStyle

from elebot.cli import history, render
from elebot.cli import stream as stream_mod


@pytest.fixture
def mock_prompt_session():
    """Mock the global prompt session."""
    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock()
    with patch("elebot.cli.history._PROMPT_SESSION", mock_session), patch(
        "elebot.cli.history.patch_stdout"
    ):
        yield mock_session


@pytest.mark.asyncio
async def test_read_interactive_input_async_returns_input(mock_prompt_session):
    """read_interactive_input_async should return user input from prompt_session."""
    mock_prompt_session.prompt_async.return_value = "hello world"

    result = await history.read_interactive_input_async()

    assert result == "hello world"
    mock_prompt_session.prompt_async.assert_called_once()
    args, _ = mock_prompt_session.prompt_async.call_args
    assert isinstance(args[0], HTML)


@pytest.mark.asyncio
async def test_read_interactive_input_async_handles_eof(mock_prompt_session):
    """EOFError should be normalized to KeyboardInterrupt."""
    mock_prompt_session.prompt_async.side_effect = EOFError()

    with pytest.raises(KeyboardInterrupt):
        await history.read_interactive_input_async()


def test_init_prompt_session_creates_session(monkeypatch, tmp_path):
    """init_prompt_session should initialize the global session."""
    history._PROMPT_SESSION = None
    monkeypatch.delenv("PROMPT_TOOLKIT_NO_CPR", raising=False)
    monkeypatch.setattr(
        "elebot.config.paths.get_cli_history_path", lambda: tmp_path / "history"
    )

    with patch("elebot.cli.history.PromptSession") as mock_session_cls:
        history.init_prompt_session()

    assert history._PROMPT_SESSION is not None
    mock_session_cls.assert_called_once()
    _, kwargs = mock_session_cls.call_args
    assert kwargs["multiline"] is False
    assert kwargs["enable_open_in_editor"] is False
    assert kwargs["complete_while_typing"] is True
    assert kwargs["complete_style"] is CompleteStyle.COLUMN
    assert isinstance(kwargs["completer"], history.SlashCommandCompleter)
    assert os.environ["PROMPT_TOOLKIT_NO_CPR"] == "1"


def test_slash_command_completer_returns_all_commands_on_slash() -> None:
    """输入单个斜杠时应列出全部 slash 命令。"""
    completer = history.SlashCommandCompleter()

    completions = list(
        completer.get_completions(Document(text="/", cursor_position=1), None)
    )

    texts = [completion.text for completion in completions]
    assert "/help" in texts
    assert "/new" in texts
    assert "/dream-restore" in texts
    assert all(completion.display_meta for completion in completions)


def test_slash_command_completer_filters_by_prefix() -> None:
    """前缀输入应只返回匹配的 slash 命令。"""
    completer = history.SlashCommandCompleter()

    completions = list(
        completer.get_completions(Document(text="/dre", cursor_position=4), None)
    )

    texts = [completion.text for completion in completions]
    assert texts == ["/dream", "/dream-log", "/dream-restore"]


def test_slash_command_completer_ignores_non_command_input() -> None:
    """普通文本和带空格参数的输入都不应再触发命令候选。"""
    completer = history.SlashCommandCompleter()

    plain = list(completer.get_completions(Document(text="hello", cursor_position=5), None))
    with_args = list(
        completer.get_completions(Document(text="/dream abc", cursor_position=10), None)
    )

    assert plain == []
    assert with_args == []


def test_thinking_spinner_pause_stops_and_restarts():
    """Pause should stop the active spinner and restart it afterward."""
    spinner = MagicMock()
    mock_console = MagicMock()
    mock_console.status.return_value = spinner

    thinking = stream_mod.ThinkingSpinner(console=mock_console)
    with thinking:
        with thinking.pause():
            pass

    assert spinner.method_calls == [
        call.start(),
        call.stop(),
        call.start(),
        call.stop(),
    ]


def test_print_cli_progress_line_pauses_spinner_before_printing():
    """CLI progress output should pause spinner to avoid garbled lines."""
    order: list[str] = []
    spinner = MagicMock()
    spinner.start.side_effect = lambda: order.append("start")
    spinner.stop.side_effect = lambda: order.append("stop")
    mock_console = MagicMock()
    mock_console.status.return_value = spinner

    with patch.object(render.console, "print", side_effect=lambda *_args, **_kwargs: order.append("print")):
        thinking = stream_mod.ThinkingSpinner(console=mock_console)
        with thinking:
            render.print_cli_progress_line("tool running", thinking)

    assert order == ["start", "stop", "print", "start", "stop"]


@pytest.mark.asyncio
async def test_print_interactive_progress_line_pauses_spinner_before_printing():
    """Interactive progress output should also pause spinner cleanly."""
    order: list[str] = []
    spinner = MagicMock()
    spinner.start.side_effect = lambda: order.append("start")
    spinner.stop.side_effect = lambda: order.append("stop")
    mock_console = MagicMock()
    mock_console.status.return_value = spinner

    async def fake_print(_text: str) -> None:
        order.append("print")

    with patch("elebot.cli.render.print_interactive_line", side_effect=fake_print):
        thinking = stream_mod.ThinkingSpinner(console=mock_console)
        with thinking:
            await render.print_interactive_progress_line("tool running", thinking)

    assert order == ["start", "stop", "print", "start", "stop"]


def test_response_renderable_uses_text_for_explicit_plain_rendering():
    status = (
        "🍌 elebot v0.1.4.post5\n"
        "🧠 Model: MiniMax-M2.7\n"
        "📊 Tokens: 20639 in / 29 out"
    )

    renderable = render.response_renderable(
        status,
        render_markdown=True,
        metadata={"render_as": "text"},
    )

    assert renderable.__class__.__name__ == "Text"


def test_response_renderable_preserves_normal_markdown_rendering():
    renderable = render.response_renderable("**bold**", render_markdown=True)

    assert renderable.__class__.__name__ == "Markdown"


def test_response_renderable_without_metadata_keeps_markdown_path():
    help_text = "🍌 elebot 命令：\n/status — 查看当前状态\n/help — 查看可用命令"

    renderable = render.response_renderable(help_text, render_markdown=True)

    assert renderable.__class__.__name__ == "Markdown"


def test_stream_renderer_stop_for_input_stops_spinner():
    """stop_for_input should stop the active spinner to avoid prompt_toolkit conflicts."""
    spinner = MagicMock()
    mock_console = MagicMock()
    mock_console.status.return_value = spinner

    with patch.object(stream_mod, "_make_console", return_value=mock_console):
        renderer = stream_mod.StreamRenderer(show_spinner=True)
        spinner.start.assert_called_once()
        renderer.stop_for_input()
        spinner.stop.assert_called_once()


@pytest.mark.asyncio
async def test_stream_renderer_tool_transition_reuses_same_spinner_instance():
    spinner = MagicMock()
    mock_console = MagicMock()
    mock_console.status.return_value = spinner

    with patch.object(stream_mod, "_make_console", return_value=mock_console):
        renderer = stream_mod.StreamRenderer(show_spinner=True)
        await renderer.on_tool_transition('cron_create("提醒我看书")')

    assert spinner.method_calls == [
        call.start(),
        call.stop(),
        call.start(),
    ]


@pytest.mark.asyncio
async def test_stream_renderer_starts_live_on_first_visible_token():
    spinner = MagicMock()
    mock_console = MagicMock()
    mock_console.status.return_value = spinner
    live = MagicMock()

    with patch.object(stream_mod, "_make_console", return_value=mock_console), \
         patch.object(stream_mod, "Live", return_value=live) as live_cls:
        renderer = stream_mod.StreamRenderer(show_spinner=True)
        await renderer.on_delta("你好")

    live_cls.assert_called_once()
    live.start.assert_called_once()
    live.update.assert_called()
    live.refresh.assert_called()
    mock_console.print.assert_called_once()


@pytest.mark.asyncio
async def test_stream_renderer_ends_current_live_block_before_tool_resume():
    spinner = MagicMock()
    mock_console = MagicMock()
    mock_console.status.return_value = spinner
    live = MagicMock()

    with patch.object(stream_mod, "_make_console", return_value=mock_console), \
         patch.object(stream_mod, "Live", return_value=live) as live_cls:
        renderer = stream_mod.StreamRenderer(show_spinner=True)
        await renderer.on_delta("好的，我来设置 2 分钟后打开微信。")
        await renderer.on_end(resuming=True)

    live_cls.assert_called_once()
    live.start.assert_called_once()
    live.stop.assert_called_once()
    assert spinner.start.call_count == 2


@pytest.mark.asyncio
async def test_stream_renderer_keeps_long_response_in_body_channel_before_tool_resume():
    spinner = MagicMock()
    mock_console = MagicMock()
    mock_console.status.return_value = spinner
    live = MagicMock()

    with patch.object(stream_mod, "_make_console", return_value=mock_console), \
         patch.object(stream_mod, "Live", return_value=live) as live_cls:
        renderer = stream_mod.StreamRenderer(show_spinner=True)
        await renderer.on_delta("a" * 121)
        await renderer.on_end(resuming=True)

    live_cls.assert_called_once()
    live.start.assert_called_once()
    live.stop.assert_called_once()


def test_make_console_uses_force_terminal():
    """Console should be created with force_terminal=True for proper ANSI handling."""
    console = stream_mod._make_console()
    assert console._force_terminal is True
