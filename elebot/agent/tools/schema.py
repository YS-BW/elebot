"""工具参数使用的 JSON Schema 片段类型集合。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from elebot.agent.tools.base import Schema


class StringSchema(Schema):
    """字符串参数 Schema。"""

    def __init__(
        self,
        description: str = "",
        *,
        min_length: int | None = None,
        max_length: int | None = None,
        enum: tuple[Any, ...] | list[Any] | None = None,
        nullable: bool = False,
    ) -> None:
        """初始化字符串参数 Schema。

        参数:
            description: 字段描述。
            min_length: 最小长度。
            max_length: 最大长度。
            enum: 可选枚举值。
            nullable: 是否允许空值。

        返回:
            无返回值。
        """
        self._description = description
        self._min_length = min_length
        self._max_length = max_length
        self._enum = tuple(enum) if enum is not None else None
        self._nullable = nullable

    def to_json_schema(self) -> dict[str, Any]:
        """导出 JSON Schema 片段。

        返回:
            当前字符串参数的 Schema 字典。
        """
        t: Any = "string"
        if self._nullable:
            t = ["string", "null"]
        d: dict[str, Any] = {"type": t}
        if self._description:
            d["description"] = self._description
        if self._min_length is not None:
            d["minLength"] = self._min_length
        if self._max_length is not None:
            d["maxLength"] = self._max_length
        if self._enum is not None:
            d["enum"] = list(self._enum)
        return d


class IntegerSchema(Schema):
    """整数参数 Schema。"""

    def __init__(
        self,
        value: int = 0,
        *,
        description: str = "",
        minimum: int | None = None,
        maximum: int | None = None,
        enum: tuple[int, ...] | list[int] | None = None,
        nullable: bool = False,
    ) -> None:
        """初始化整数参数 Schema。

        参数:
            value: 兼容旧签名保留的占位值。
            description: 字段描述。
            minimum: 最小值。
            maximum: 最大值。
            enum: 可选枚举值。
            nullable: 是否允许空值。

        返回:
            无返回值。
        """
        self._value = value
        self._description = description
        self._minimum = minimum
        self._maximum = maximum
        self._enum = tuple(enum) if enum is not None else None
        self._nullable = nullable

    def to_json_schema(self) -> dict[str, Any]:
        """导出 JSON Schema 片段。

        返回:
            当前整数参数的 Schema 字典。
        """
        t: Any = "integer"
        if self._nullable:
            t = ["integer", "null"]
        d: dict[str, Any] = {"type": t}
        if self._description:
            d["description"] = self._description
        if self._minimum is not None:
            d["minimum"] = self._minimum
        if self._maximum is not None:
            d["maximum"] = self._maximum
        if self._enum is not None:
            d["enum"] = list(self._enum)
        return d


class NumberSchema(Schema):
    """数值参数 Schema。"""

    def __init__(
        self,
        value: float = 0.0,
        *,
        description: str = "",
        minimum: float | None = None,
        maximum: float | None = None,
        enum: tuple[float, ...] | list[float] | None = None,
        nullable: bool = False,
    ) -> None:
        """初始化数值参数 Schema。

        参数:
            value: 兼容旧签名保留的占位值。
            description: 字段描述。
            minimum: 最小值。
            maximum: 最大值。
            enum: 可选枚举值。
            nullable: 是否允许空值。

        返回:
            无返回值。
        """
        self._value = value
        self._description = description
        self._minimum = minimum
        self._maximum = maximum
        self._enum = tuple(enum) if enum is not None else None
        self._nullable = nullable

    def to_json_schema(self) -> dict[str, Any]:
        """导出 JSON Schema 片段。

        返回:
            当前数值参数的 Schema 字典。
        """
        t: Any = "number"
        if self._nullable:
            t = ["number", "null"]
        d: dict[str, Any] = {"type": t}
        if self._description:
            d["description"] = self._description
        if self._minimum is not None:
            d["minimum"] = self._minimum
        if self._maximum is not None:
            d["maximum"] = self._maximum
        if self._enum is not None:
            d["enum"] = list(self._enum)
        return d


class BooleanSchema(Schema):
    """布尔参数 Schema。"""

    def __init__(
        self,
        *,
        description: str = "",
        default: bool | None = None,
        nullable: bool = False,
    ) -> None:
        """初始化布尔参数 Schema。

        参数:
            description: 字段描述。
            default: 默认值。
            nullable: 是否允许空值。

        返回:
            无返回值。
        """
        self._description = description
        self._default = default
        self._nullable = nullable

    def to_json_schema(self) -> dict[str, Any]:
        """导出 JSON Schema 片段。

        返回:
            当前布尔参数的 Schema 字典。
        """
        t: Any = "boolean"
        if self._nullable:
            t = ["boolean", "null"]
        d: dict[str, Any] = {"type": t}
        if self._description:
            d["description"] = self._description
        if self._default is not None:
            d["default"] = self._default
        return d


class ArraySchema(Schema):
    """数组参数 Schema。"""

    def __init__(
        self,
        items: Any | None = None,
        *,
        description: str = "",
        min_items: int | None = None,
        max_items: int | None = None,
        nullable: bool = False,
    ) -> None:
        """初始化数组参数 Schema。

        参数:
            items: 元素 Schema。
            description: 字段描述。
            min_items: 最少元素数。
            max_items: 最多元素数。
            nullable: 是否允许空值。

        返回:
            无返回值。
        """
        self._items_schema: Any = items if items is not None else StringSchema("")
        self._description = description
        self._min_items = min_items
        self._max_items = max_items
        self._nullable = nullable

    def to_json_schema(self) -> dict[str, Any]:
        """导出 JSON Schema 片段。

        返回:
            当前数组参数的 Schema 字典。
        """
        t: Any = "array"
        if self._nullable:
            t = ["array", "null"]
        d: dict[str, Any] = {
            "type": t,
            "items": Schema.fragment(self._items_schema),
        }
        if self._description:
            d["description"] = self._description
        if self._min_items is not None:
            d["minItems"] = self._min_items
        if self._max_items is not None:
            d["maxItems"] = self._max_items
        return d


class ObjectSchema(Schema):
    """对象参数 Schema。"""

    def __init__(
        self,
        properties: Mapping[str, Any] | None = None,
        *,
        required: list[str] | None = None,
        description: str = "",
        additional_properties: bool | dict[str, Any] | None = None,
        nullable: bool = False,
        **kwargs: Any,
    ) -> None:
        """初始化对象参数 Schema。

        参数:
            properties: 字段定义映射。
            required: 必填字段名列表。
            description: 对象描述。
            additional_properties: 是否允许额外字段。
            nullable: 是否允许空值。
            **kwargs: 额外字段定义。

        返回:
            无返回值。
        """
        self._properties = dict(properties or {}, **kwargs)
        self._required = list(required or [])
        self._root_description = description
        self._additional_properties = additional_properties
        self._nullable = nullable

    def to_json_schema(self) -> dict[str, Any]:
        """导出 JSON Schema 片段。

        返回:
            当前对象参数的 Schema 字典。
        """
        t: Any = "object"
        if self._nullable:
            t = ["object", "null"]
        props = {k: Schema.fragment(v) for k, v in self._properties.items()}
        out: dict[str, Any] = {"type": t, "properties": props}
        if self._required:
            out["required"] = self._required
        if self._root_description:
            out["description"] = self._root_description
        if self._additional_properties is not None:
            out["additionalProperties"] = self._additional_properties
        return out


def tool_parameters_schema(
    *,
    required: list[str] | None = None,
    description: str = "",
    **properties: Any,
) -> dict[str, Any]:
    """构建工具参数根 Schema。

    参数:
        required: 必填字段列表。
        description: 根对象描述。
        **properties: 字段 Schema 定义。

    返回:
        ``type=object`` 的根 Schema 字典。
    """
    return ObjectSchema(
        required=required,
        description=description,
        **properties,
    ).to_json_schema()
