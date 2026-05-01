"""Shell 命令沙箱后端。"""

import shlex
from pathlib import Path

from elebot.config.paths import get_media_dir


def _bwrap(command: str, workspace: str, cwd: str) -> str:
    """把命令包装进 bubblewrap 沙箱。

    参数:
        command: 原始命令。
        workspace: 工作区路径。
        cwd: 当前工作目录。

    返回:
        包装后的命令字符串。
    """
    ws = Path(workspace).resolve()
    media = get_media_dir().resolve()

    try:
        sandbox_cwd = str(ws / Path(cwd).resolve().relative_to(ws))
    except ValueError:
        sandbox_cwd = str(ws)

    required = ["/usr"]
    optional = [
        "/bin",
        "/lib",
        "/lib64",
        "/etc/alternatives",
        "/etc/ssl/certs",
        "/etc/resolv.conf",
        "/etc/ld.so.cache",
    ]

    args = ["bwrap", "--new-session", "--die-with-parent"]
    for path in required:
        args += ["--ro-bind", path, path]
    for path in optional:
        args += ["--ro-bind-try", path, path]
    args += [
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--tmpfs", str(ws.parent),        # 隐藏工作区父目录，避免顺手看到配置目录等敏感内容。
        "--dir", str(ws),                 # 重新建挂载点，确保后续 bind 到同一路径。
        "--bind", str(ws), str(ws),
        "--ro-bind-try", str(media), str(media),  # 媒体目录保留只读，便于命令读取上传附件。
        "--chdir", sandbox_cwd,
        "--", "sh", "-c", command,
    ]
    return shlex.join(args)


_BACKENDS = {"bwrap": _bwrap}


def wrap_command(sandbox: str, command: str, workspace: str, cwd: str) -> str:
    """按指定后端包装命令。

    参数:
        sandbox: 沙箱后端名称。
        command: 原始命令。
        workspace: 工作区路径。
        cwd: 当前工作目录。

    返回:
        包装后的命令字符串。
    """
    if backend := _BACKENDS.get(sandbox):
        return backend(command, workspace, cwd)
    raise ValueError(f"Unknown sandbox backend {sandbox!r}. Available: {list(_BACKENDS)}")
