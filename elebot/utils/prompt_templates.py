"""加载并渲染 `elebot/templates/` 下的提示词模板。"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"


@lru_cache
def _environment() -> Environment:
    # 这里渲染的是纯文本提示词，不能启用 HTML 转义。
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_ROOT)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(name: str, *, strip: bool = False, **kwargs: Any) -> str:
    """渲染指定模板文件。

    参数:
        name: 模板相对路径，如 ``IDENTITY.md``。
        strip: 是否移除尾部换行。
        **kwargs: 模板渲染变量。

    返回:
        渲染后的模板文本。
    """
    text = _environment().get_template(name).render(**kwargs)
    return text.rstrip() if strip else text
