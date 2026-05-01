"""EleBot CLI 根入口。"""

from __future__ import annotations

import os
import sys

import typer
from typer.completion import install_callback, show_callback

from elebot import __logo__, __version__
from elebot.cli.commands import register_commands
from elebot.cli.render import console

# Windows 控制台默认编码不稳定，这里提前强制为 UTF-8，避免中文输出乱码。
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

app = typer.Typer(
    name="elebot",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=f"{__logo__} elebot - Personal AI Assistant",
    no_args_is_help=True,
    add_completion=False,
)


def version_callback(value: bool) -> None:
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
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
    ),
    install_completion: bool = typer.Option(
        False,
        "--install-completion",
        help="为当前 shell 安装补全脚本。",
        callback=install_callback,
        is_eager=True,
    ),
    show_completion: bool = typer.Option(
        False,
        "--show-completion",
        help="显示当前 shell 的补全脚本，便于复制或自定义安装。",
        callback=show_callback,
        is_eager=True,
    ),
) -> None:
    """定义 CLI 根命令。

    参数:
        version: 是否输出版本并立即退出。
        install_completion: 是否为当前 shell 安装补全脚本。
        show_completion: 是否显示当前 shell 的补全脚本。

    返回:
        无返回值。
    """
    del version
    del install_completion
    del show_completion


register_commands(app)
