"""EleBot 命令行命令集合。"""

import asyncio
import os
import sys
from pathlib import Path

# Windows 控制台默认编码不稳定，这里提前强制为 UTF-8，避免中文输出乱码。
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # 这里同步重绑 stdout/stderr，避免环境变量生效前已经拿到旧编码句柄。
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer

from elebot import __logo__, __version__
from elebot.cli.render import console, print_agent_response, print_cli_progress_line
from elebot.cli.stream import StreamRenderer
from elebot.config.paths import get_workspace_path
from elebot.config.schema import Config
from elebot.providers.factory import build_provider
from elebot.runtime import ElebotRuntime
from elebot.utils.helpers import sync_workspace_templates
from elebot.utils.restart import (
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)

app = typer.Typer(
    name="elebot",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=f"{__logo__} elebot - Personal AI Assistant",
    no_args_is_help=True,
)


def version_callback(value: bool):
    """处理 `--version` 选项并在需要时立即退出。

    参数:
        value: 是否触发版本输出。

    返回:
        无返回值。
    """
    if value:
        console.print(f"{__logo__} elebot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """定义 CLI 根命令。

    参数:
        version: 是否输出版本并立即退出。

    返回:
        无返回值。
    """
    pass


# 这里开始是初始化与向导相关命令。


@app.command()
def onboard(
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    wizard: bool = typer.Option(False, "--wizard", help="Use interactive wizard"),
):
    """初始化配置文件与工作区。

    参数:
        workspace: 覆盖默认工作区目录。
        config: 指定配置文件路径。
        wizard: 是否启用交互式向导。

    返回:
        无返回值。
    """
    from elebot.config.loader import get_config_path, load_config, save_config, set_config_path
    from elebot.config.schema import Config

    if config:
        config_path = Path(config).expanduser().resolve()
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")
    else:
        config_path = get_config_path()

    def _apply_workspace_override(loaded: Config) -> Config:
        if workspace:
            loaded.agents.defaults.workspace = workspace
        return loaded

    # 先决定是新建配置还是在原配置上补齐缺失字段，避免误覆盖用户已有值。
    if config_path.exists():
        if wizard:
            config = _apply_workspace_override(load_config(config_path))
        else:
            console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
            console.print(
                "  [bold]y[/bold] = overwrite with defaults (existing values will be lost)"
            )
            console.print(
                "  [bold]N[/bold] = refresh config, keeping existing values and adding new fields"
            )
            if typer.confirm("Overwrite?"):
                config = _apply_workspace_override(Config())
                save_config(config, config_path)
                console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
            else:
                config = _apply_workspace_override(load_config(config_path))
                save_config(config, config_path)
                console.print(
                    f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)"
                )
    else:
        config = _apply_workspace_override(Config())
        # 向导模式下由后续统一决定是否保存，避免用户中途取消却留下半成品配置。
        if not wizard:
            save_config(config, config_path)
            console.print(f"[green]✓[/green] Created config at {config_path}")

    # 启用向导时，把最终是否落盘的决定权交给向导结果。
    if wizard:
        from elebot.cli.onboard import run_onboard

        try:
            result = run_onboard(initial_config=config)
            if not result.should_save:
                console.print("[yellow]Configuration discarded. No changes were saved.[/yellow]")
                return

            config = result.config
            save_config(config, config_path)
            console.print(f"[green]✓[/green] Config saved at {config_path}")
        except Exception as e:
            console.print(f"[red]✗[/red] Error during configuration: {e}")
            console.print("[yellow]Please run 'elebot onboard' again to complete setup.[/yellow]")
            raise typer.Exit(1)
    # 工作区优先使用配置里的路径，这样命令行临时参数和配置文件能保持一致。
    workspace_path = get_workspace_path(config.workspace_path)
    if not workspace_path.exists():
        workspace_path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace_path}")

    sync_workspace_templates(workspace_path)

    agent_cmd = 'elebot agent -m "Hello!"'
    if config:
        agent_cmd += f" --config {config_path}"

    console.print(f"\n{__logo__} elebot is ready!")
    console.print("\nNext steps:")
    if wizard:
        console.print(f"  1. Chat: [cyan]{agent_cmd}[/cyan]")
    else:
        console.print(f"  1. Add your API key to [cyan]{config_path}[/cyan]")
        console.print("     Get one at: https://dashscope.console.aliyun.com")
        console.print(f"  2. Chat: [cyan]{agent_cmd}[/cyan]")

def _make_provider(config: Config):
    """根据当前配置实例化对应的 LLM 提供方。

    参数:
        config: 已解析完成的运行时配置。

    返回:
        配置好默认生成参数的提供方实例。
    """
    try:
        return build_provider(config)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        text = str(exc)
        if "No API key configured" in text:
            console.print("Set one in ~/.elebot/config.json under providers section")
        if "Azure OpenAI requires" in text:
            console.print("Set them in ~/.elebot/config.json under providers.azure_openai section")
            console.print("Use the model field to specify the deployment name.")
        raise typer.Exit(1) from exc


def _load_runtime_config(config: str | None = None, workspace: str | None = None) -> Config:
    """加载运行时配置，并按需覆盖当前工作区。

    参数:
        config: 可选的配置文件路径。
        workspace: 可选的工作区覆盖路径。

    返回:
        解析并展开环境变量后的配置对象。
    """
    from elebot.config.loader import load_config, resolve_config_env_vars, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")

    try:
        loaded = resolve_config_env_vars(load_config(config_path))
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    _warn_deprecated_config_keys(config_path)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


def _make_runtime(config: Config) -> ElebotRuntime:
    """根据当前配置装配一份 CLI 复用的 runtime。

    参数:
        config: 已解析完成的运行时配置。

    返回:
        供 CLI 启动或单次调用的 runtime 实例。
    """
    from elebot.agent.loop import AgentLoop
    from elebot.bus.queue import MessageBus

    return ElebotRuntime.from_config(
        config,
        provider_builder=_make_provider,
        bus_factory=MessageBus,
        agent_loop_factory=AgentLoop,
    )


def _warn_deprecated_config_keys(config_path: Path | None) -> None:
    """提示用户移除已经废弃的配置键。

    参数:
        config_path: 当前命令解析出的配置文件路径；为空时回退到默认路径。

    返回:
        无返回值。
    """
    import json

    from elebot.config.loader import get_config_path

    path = config_path or get_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if "memoryWindow" in raw.get("agents", {}).get("defaults", {}):
        console.print(
            "[dim]Hint: `memoryWindow` in your config is no longer used "
            "and can be safely removed.[/dim]"
        )

# 这里开始是直接面向主链路的 agent 命令。


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show elebot runtime logs during chat"),
):
    """直接与主代理交互。

    参数:
        message: 一次性发送给代理的消息。
        session_id: 会话标识。
        workspace: 工作区覆盖路径。
        config: 配置文件路径。
        markdown: 是否按 Markdown 渲染回复。
        logs: 是否显示运行日志。

    返回:
        无返回值。
    """
    from loguru import logger

    config = _load_runtime_config(config, workspace)
    sync_workspace_templates(config.workspace_path)

    if logs:
        logger.enable("elebot")
    else:
        logger.disable("elebot")

    runtime = _make_runtime(config)

    restart_notice = consume_restart_notice_from_env()
    if restart_notice and should_show_cli_restart_notice(restart_notice, session_id):
        print_agent_response(
            format_restart_completed_message(restart_notice.started_at_raw),
            render_markdown=False,
        )

    thinking = None

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        print_cli_progress_line(content, thinking)

    if message:
        async def run_once():
            """执行单次 CLI 直连对话。

            返回:
                无返回值。
            """
            nonlocal thinking
            renderer = StreamRenderer(render_markdown=markdown)
            thinking = renderer.spinner
            response = await runtime.run_once(
                message,
                session_id=session_id,
                on_progress=_cli_progress,
                on_stream=renderer.on_delta,
                on_stream_end=renderer.on_end,
            )
            if not renderer.streamed:
                await renderer.close()
                print_agent_response(
                    response.content if response else "",
                    render_markdown=markdown,
                    metadata=response.metadata if response else None,
                )
            thinking = None
            await runtime.close()

        asyncio.run(run_once())
    else:
        asyncio.run(runtime.run_interactive(session_id=session_id, markdown=markdown))

# 这里开始是状态查看命令。


@app.command()
def status():
    """显示 EleBot 当前状态。

    返回:
        无返回值。
    """
    from elebot.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} elebot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from elebot.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")

        # 直接遍历注册表比手写字段列表更稳，新增提供方时这里无需额外同步。
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                # 本地部署通常不靠 key 鉴权，因此展示 api_base 更符合排查习惯。
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")


# 这里开始是 OAuth 提供方登录命令。

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider", hidden=True)


_LOGIN_HANDLERS: dict[str, callable] = {}


def _register_login(name: str):
    def decorator(fn):
        """把登录处理函数注册到名称映射表。

        参数:
            fn: 实际登录处理函数。

        返回:
            原始处理函数。
        """
        _LOGIN_HANDLERS[name] = fn
        return fn

    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"),
):
    """登录一个 OAuth 提供方。

    参数:
        provider: 提供方名称。

    返回:
        无返回值。
    """
    from elebot.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive

        token = None
        try:
            token = get_token()
        except Exception:
            pass
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]")
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    try:
        from elebot.providers.github_copilot_provider import login_github_copilot

        console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")
        token = login_github_copilot(
            print_fn=lambda s: console.print(s),
            prompt_fn=lambda s: typer.prompt(s),
        )
        account = token.account_id or "GitHub"
        console.print(f"[green]✓ Authenticated with GitHub Copilot[/green]  [dim]{account}[/dim]")
    except Exception as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
