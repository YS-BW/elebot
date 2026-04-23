import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from prompt_toolkit.formatted_text import HTML

from elebot.cli import history
from elebot.cli import render
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
        "🐈 elebot v0.1.4.post5\n"
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
    help_text = "🐈 elebot commands:\n/status — Show bot status\n/help — Show available commands"

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


def test_stream_renderer_exposes_spinner_property():
    spinner = MagicMock()
    mock_console = MagicMock()
    mock_console.status.return_value = spinner

    with patch.object(stream_mod, "_make_console", return_value=mock_console):
        renderer = stream_mod.StreamRenderer(show_spinner=True)

    assert renderer.spinner is not None


def test_make_console_uses_force_terminal():
    """Console should be created with force_terminal=True for proper ANSI handling."""
    console = stream_mod._make_console()
    assert console._force_terminal is True
