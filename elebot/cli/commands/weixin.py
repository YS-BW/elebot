"""`elebot channel` 命令组。"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import typer
from loguru import logger

from elebot.channels import ChannelManager
from elebot.channels.weixin import WeixinChannel
from elebot.bus.queue import MessageBus
from elebot.cli.render import console
from elebot.cli.runtime_support import _load_runtime_config, _make_runtime
from elebot.config.loader import load_config, resolve_config_env_vars, set_config_path
from elebot.config.paths import get_logs_dir, get_runtime_subdir
from elebot.runtime.models import InterruptResult, RuntimeStatusSnapshot
from elebot.utils.workspace import sync_workspace_templates


class _ChannelLoginRuntime:
    """给 channel 登录流程使用的最小 runtime stub。"""

    def __init__(self) -> None:
        """初始化最小 bus 持有者。"""
        self.bus = MessageBus()

    def interrupt_session(
        self,
        session_id: str,
        reason: str = "user_interrupt",
    ) -> InterruptResult:
        """登录流程不会使用中断控制面。"""
        return InterruptResult(
            session_id=session_id,
            reason=reason,
            accepted=False,
            cancelled_tasks=0,
            already_interrupting=False,
        )

    def reset_session(self, session_id: str) -> None:
        """登录流程不会使用会话重置。"""
        del session_id

    async def get_status_snapshot(self, session_id: str) -> RuntimeStatusSnapshot:
        """登录流程不会使用状态查询。"""
        del session_id
        raise RuntimeError("status snapshot is not available during channel login")


def resolve_weixin_state_path(loaded_config) -> Path:
    """返回微信登录态文件路径。"""
    state_dir = (
        Path(loaded_config.channels.weixin.state_dir).expanduser()
        if loaded_config.channels.weixin.state_dir
        else get_runtime_subdir("weixin")
    )
    return state_dir / "account.json"


def validate_weixin_enabled(loaded_config) -> None:
    """检查 weixin 是否已启用。"""
    if loaded_config.channels.weixin.enabled:
        return
    raise typer.BadParameter(
        "当前未启用 weixin channel。\n"
        "请先在配置中把 `channels.weixin.enabled` 设为 true。"
    )


def validate_weixin_ready(loaded_config) -> None:
    """检查 weixin 启动前提。"""
    validate_weixin_enabled(loaded_config)
    has_inline_token = bool(str(loaded_config.channels.weixin.token or "").strip())
    state_path = resolve_weixin_state_path(loaded_config)
    has_saved_state = state_path.is_file()
    if has_inline_token or has_saved_state:
        return
    raise typer.BadParameter(
        "weixin channel 已启用，但未找到可用登录态。\n"
        "请先运行：elebot channel login"
    )


def _get_channel_service_pid_path() -> Path:
    """返回 channel service 的 pid 文件路径。"""
    return get_logs_dir() / "channels-service.pid"


def _get_channel_service_log_path() -> Path:
    """返回 channel service 的日志文件路径。"""
    return get_logs_dir() / "channels-service.log"


def _read_service_pid(pid_path: Path) -> int | None:
    """读取 pid 文件中的进程号。"""
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _is_process_alive(pid: int) -> bool:
    """判断给定进程是否仍然存活。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def get_channel_service_owner() -> str | None:
    """返回当前 channel service 的 owner。"""
    return "weixin"


def get_channel_service_state() -> tuple[str, int | None]:
    """返回 channel 后台 service 当前状态。"""
    pid_path = _get_channel_service_pid_path()
    pid = _read_service_pid(pid_path)
    if pid is None:
        return ("stale", None) if pid_path.exists() else ("stopped", None)
    if _is_process_alive(pid):
        return ("running", pid)
    return ("stale", pid)


def list_channel_service_pids() -> list[int]:
    """列出当前运行中的所有 channel 服务进程。"""
    try:
        output = subprocess.check_output(
            [
                "pgrep",
                "-fal",
                r"python -m elebot channel (_serve_internal|run)|/elebot channel (_serve_internal|run)",
            ],
            text=True,
        )
    except Exception:
        return []

    pids: list[int] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        try:
            pids.append(int(parts[0]))
        except (ValueError, IndexError):
            continue
    return pids


def _cleanup_stale_pid_file() -> None:
    """清理失效 pid 文件。"""
    pid_path = _get_channel_service_pid_path()
    if pid_path.exists():
        pid_path.unlink()


def _build_service_command(config: str | None, workspace: str | None) -> list[str]:
    """构造后台 channel service 的启动命令。"""
    command = [sys.executable, "-m", "elebot", "channel", "_serve_internal"]
    if config:
        command.extend(["--config", str(Path(config).expanduser().resolve())])
    if workspace:
        command.extend(["--workspace", workspace])
    return command


def _wait_for_process_exit(pid: int, timeout_seconds: float) -> bool:
    """等待目标进程在限定时间内退出。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _is_process_alive(pid):
            return True
        time.sleep(0.1)
    return not _is_process_alive(pid)


def _follow_log_file(log_path: Path) -> None:
    """以前台方式持续输出 channel service 日志。"""
    if not log_path.exists():
        raise typer.BadParameter(f"日志文件不存在：{log_path}")

    with log_path.open("r", encoding="utf-8", errors="replace") as log_file:
        log_file.seek(0, os.SEEK_END)
        try:
            while True:
                line = log_file.readline()
                if line:
                    typer.echo(line, nl=False)
                    continue
                time.sleep(0.2)
        except KeyboardInterrupt:
            raise typer.Exit(0) from None


async def _run_weixin_channel(loaded_config) -> None:
    """按当前配置以前台方式启动 weixin channel。"""
    runtime = _make_runtime(loaded_config, silent=True)
    manager = ChannelManager(loaded_config, runtime)
    await runtime.start()
    await manager.start_all()
    try:
        await manager.wait()
    finally:
        await manager.stop_all()
        await runtime.close()


def _start_weixin_service(config: str | None, workspace: str | None) -> None:
    """启动后台 weixin service。"""
    status, pid = get_channel_service_state()
    if status == "running":
        owner = get_channel_service_owner() or "unknown"
        console.print(f"channel service 已被 {owner} 占用，pid={pid}")
        raise typer.Exit(0)
    if status == "stale":
        _cleanup_stale_pid_file()

    loaded_config = _load_runtime_config(config, workspace, silent=True)
    validate_weixin_ready(loaded_config)

    logs_dir = get_logs_dir()
    log_path = _get_channel_service_log_path()
    pid_path = _get_channel_service_pid_path()
    logs_dir.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            _build_service_command(config, workspace),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(Path.cwd()),
        )

    pid_path.write_text(str(process.pid), encoding="utf-8")
    logger.info(
        "Weixin service started in background: pid={} log={}",
        process.pid,
        log_path,
    )
    console.print(f"weixin service 已启动，pid={process.pid}")
    console.print(f"日志文件：{log_path}")


def _stop_weixin_service() -> None:
    """停止后台 weixin service。"""
    status, pid = get_channel_service_state()
    pid_path = _get_channel_service_pid_path()

    if status == "stopped":
        console.print("weixin service 当前未运行")
        raise typer.Exit(0)

    if status == "stale" or pid is None:
        _cleanup_stale_pid_file()
        console.print("weixin service 的 pid 文件已失效，已清理")
        raise typer.Exit(0)

    os.kill(pid, signal.SIGTERM)
    if not _wait_for_process_exit(pid, timeout_seconds=5.0):
        raise typer.Exit("weixin service 停止超时，请检查进程状态")

    if pid_path.exists():
        pid_path.unlink()
    logger.info("Weixin service stopped: pid={}", pid)
    console.print(f"weixin service 已停止，pid={pid}")


def register_channel_command(app: typer.Typer) -> None:
    """注册 `channel` 命令组。"""
    channel_app = typer.Typer(help="Manage external channel service")

    @channel_app.callback(invoke_without_command=True)
    def channel_group(ctx: typer.Context) -> None:
        """处理 channel 命令组的空子命令场景。"""
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    @channel_app.command("login")
    def login(
        force: bool = typer.Option(False, "--force", "-f", help="Force re-authentication"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """执行当前启用 channel 的交互式登录。"""
        resolved_config_path = Path(config).expanduser().resolve() if config else None
        if resolved_config_path is not None:
            set_config_path(resolved_config_path)

        loaded_config = resolve_config_env_vars(load_config(resolved_config_path))
        runtime = _ChannelLoginRuntime()
        channel = WeixinChannel(loaded_config.channels.weixin, runtime)
        success = asyncio.run(channel.login(force=force))
        if not success:
            raise typer.Exit(1)

    @channel_app.command("run")
    def run(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """以前台方式运行当前启用的 channel，并默认打印日志。"""
        service_state, service_pid = get_channel_service_state()
        if service_state == "running":
            owner = get_channel_service_owner() or "unknown"
            raise typer.BadParameter(
                f"channel service 已被 {owner} 占用，pid={service_pid}。\n"
                "请先执行 `elebot channel stop`，再运行 `elebot channel run`。"
            )
        if service_state == "stale":
            _cleanup_stale_pid_file()

        loaded_config = _load_runtime_config(config, workspace, silent=True)
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        validate_weixin_ready(loaded_config)

        logger.enable("elebot")
        asyncio.run(_run_weixin_channel(loaded_config))

    @channel_app.command("_serve_internal", hidden=True)
    def serve_internal(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """后台 service 专用入口，绕过外层互斥检查。"""
        loaded_config = _load_runtime_config(config, workspace, silent=True)
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        validate_weixin_ready(loaded_config)

        logger.enable("elebot")
        asyncio.run(_run_weixin_channel(loaded_config))

    @channel_app.command("start")
    def start(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """后台启动当前启用的 channel service。"""
        _start_weixin_service(config, workspace)

    @channel_app.command("log")
    def log() -> None:
        """实时展示后台 channel service 日志，Ctrl+C 退出但不影响后台。"""
        _follow_log_file(_get_channel_service_log_path())

    @channel_app.command("stop")
    def stop() -> None:
        """停止后台 channel service。"""
        _stop_weixin_service()

    @channel_app.command("restart")
    def restart(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """重启后台 channel service；未运行时则直接启动。"""
        status, _pid = get_channel_service_state()
        if status == "running":
            _stop_weixin_service()
        elif status == "stale":
            _cleanup_stale_pid_file()
        _start_weixin_service(config, workspace)

    app.add_typer(channel_app, name="channel")
