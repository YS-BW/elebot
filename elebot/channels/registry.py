"""中文模块说明：冻结模块，保留实现且不接入默认主链路。"""


from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from elebot.channels.base import BaseChannel

_INTERNAL = frozenset({"base", "manager", "registry"})


def discover_channel_names() -> list[str]:
    """中文说明：discover_channel_names。

    参数:
        无。

    返回:
        待补充返回值说明。
    """
    """Return all built-in channel module names by scanning the package (zero imports)."""
    import elebot.channels as pkg

    return [
        name
        for _, name, ispkg in pkgutil.iter_modules(pkg.__path__)
        if name not in _INTERNAL and not ispkg
    ]


def load_channel_class(module_name: str) -> type[BaseChannel]:
    """中文说明：load_channel_class。

    参数:
        module_name: 待补充参数说明。

    返回:
        待补充返回值说明。
    """
    """Import *module_name* and return the first BaseChannel subclass found."""
    from elebot.channels.base import BaseChannel as _Base

    mod = importlib.import_module(f"elebot.channels.{module_name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseChannel subclass in elebot.channels.{module_name}")


def discover_plugins() -> dict[str, type[BaseChannel]]:
    """中文说明：discover_plugins。

    参数:
        无。

    返回:
        待补充返回值说明。
    """
    """Discover external channel plugins registered via entry_points."""
    from importlib.metadata import entry_points

    plugins: dict[str, type[BaseChannel]] = {}
    for ep in entry_points(group="elebot.channels"):
        try:
            cls = ep.load()
            plugins[ep.name] = cls
        except Exception as e:
            logger.warning("Failed to load channel plugin '{}': {}", ep.name, e)
    return plugins


def discover_all() -> dict[str, type[BaseChannel]]:
    """中文说明：discover_all。

    参数:
        无。

    返回:
        待补充返回值说明。
    """
    """Return all channels: built-in (pkgutil) merged with external (entry_points).

    Built-in channels take priority — an external plugin cannot shadow a built-in name.
    """
    builtin: dict[str, type[BaseChannel]] = {}
    for modname in discover_channel_names():
        try:
            builtin[modname] = load_channel_class(modname)
        except ImportError as e:
            logger.debug("Skipping built-in channel '{}': {}", modname, e)

    external = discover_plugins()
    shadowed = set(external) & set(builtin)
    if shadowed:
        logger.warning("Plugin(s) shadowed by built-in channels (ignored): {}", shadowed)

    return {**external, **builtin}
