"""elebot 顶层公共导出。"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
import tomllib


def _read_pyproject_version() -> str | None:
    """当包元数据不可用时，从源码仓库读取版本号。"""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("project", {}).get("version")


def _resolve_version() -> str:
    """优先读取已安装包版本，源码运行时回退到仓库版本。"""
    try:
        return _pkg_version("elebot")
    except PackageNotFoundError:
        # 源码环境经常没有 dist-info，这里回退以保证入口和测试都能拿到版本号。
        return _read_pyproject_version() or "0.1.5"


__version__ = _resolve_version()
__logo__ = "🐈"

from elebot.facade import Elebot, RunResult

__all__ = ["Elebot", "RunResult"]
