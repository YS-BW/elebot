"""elebot 顶层公共导出。"""

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path


def _read_pyproject_version() -> str | None:
    """当包元数据不可用时，从源码仓库读取版本号。

    参数:
        无。

    返回:
        `pyproject.toml` 中声明的版本号；文件不存在时返回 `None`。
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("project", {}).get("version")


def _resolve_version() -> str:
    """解析当前运行环境可用的版本号。

    参数:
        无。

    返回:
        优先返回已安装包版本；源码运行时回退到仓库里的版本号。
    """
    try:
        return _pkg_version("elebot")
    except PackageNotFoundError:
        # 源码环境经常没有 dist-info，这里回退以保证入口和测试都能拿到版本号。
        return _read_pyproject_version() or "0.1.5"


__version__ = _resolve_version()
__logo__ = "🍌"

__all__ = ["__version__", "__logo__"]
