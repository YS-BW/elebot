"""Agent 工具抽象与参数校验基础设施。"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar

_ToolT = TypeVar("_ToolT", bound="Tool")

# 这里维护统一类型映射，保证参数预转换与校验阶段使用同一套判断规则。
_JSON_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class Schema(ABC):
    """描述工具参数 JSON Schema 片段的抽象基类。"""

    @staticmethod
    def resolve_json_schema_type(t: Any) -> str | None:
        """解析 JSON Schema ``type`` 中的非空主类型。

        参数:
            t: 原始 ``type`` 字段值。

        返回:
            解析出的主类型字符串；无法解析时返回 ``None``。
        """
        if isinstance(t, list):
            return next((x for x in t if x != "null"), None)
        return t  # type: ignore[return-value]

    @staticmethod
    def subpath(path: str, key: str) -> str:
        """拼接嵌套字段路径。

        参数:
            path: 当前路径前缀。
            key: 子字段名。

        返回:
            拼接后的字段路径字符串。
        """
        return f"{path}.{key}" if path else key

    @staticmethod
    def validate_json_schema_value(val: Any, schema: dict[str, Any], path: str = "") -> list[str]:
        """按 JSON Schema 片段校验参数值。

        参数:
            val: 待校验的值。
            schema: JSON Schema 片段。
            path: 当前字段路径。

        返回:
            错误信息列表；为空表示校验通过。
        """
        raw_type = schema.get("type")
        nullable = (isinstance(raw_type, list) and "null" in raw_type) or schema.get("nullable", False)
        t = Schema.resolve_json_schema_type(raw_type)
        label = path or "parameter"

        if nullable and val is None:
            return []
        if t == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
            return [f"{label} should be integer"]
        if t == "number" and (
            not isinstance(val, _JSON_TYPE_MAP["number"]) or isinstance(val, bool)
        ):
            return [f"{label} should be number"]
        if t in _JSON_TYPE_MAP and t not in ("integer", "number") and not isinstance(val, _JSON_TYPE_MAP[t]):
            return [f"{label} should be {t}"]

        errors: list[str] = []
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")
        if t == "object":
            props = schema.get("properties", {})
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {Schema.subpath(path, k)}")
            for k, v in val.items():
                if k in props:
                    errors.extend(Schema.validate_json_schema_value(v, props[k], Schema.subpath(path, k)))
        if t == "array":
            if "minItems" in schema and len(val) < schema["minItems"]:
                errors.append(f"{label} must have at least {schema['minItems']} items")
            if "maxItems" in schema and len(val) > schema["maxItems"]:
                errors.append(f"{label} must be at most {schema['maxItems']} items")
            if "items" in schema:
                prefix = f"{path}[{{}}]" if path else "[{}]"
                for i, item in enumerate(val):
                    errors.extend(
                        Schema.validate_json_schema_value(item, schema["items"], prefix.format(i))
                    )
        return errors

    @staticmethod
    def fragment(value: Any) -> dict[str, Any]:
        """把 Schema 对象或现成字典统一转换为片段字典。

        参数:
            value: Schema 实例或 JSON Schema 字典。

        返回:
            统一后的 JSON Schema 片段字典。
        """
        # 先尝试 to_json_schema，避免把实现该方法的 Schema 对象误当成普通 dict。
        to_js = getattr(value, "to_json_schema", None)
        if callable(to_js):
            return to_js()
        if isinstance(value, dict):
            return value
        raise TypeError(f"Expected schema object or dict, got {type(value).__name__}")

    @abstractmethod
    def to_json_schema(self) -> dict[str, Any]:
        """返回当前对象对应的 JSON Schema 片段。

        返回:
            可供统一校验逻辑使用的 Schema 字典。
        """
        ...

    def validate_value(self, value: Any, path: str = "") -> list[str]:
        """校验单个参数值。

        参数:
            value: 待校验的值。
            path: 当前字段路径。

        返回:
            错误信息列表；为空表示校验通过。
        """
        return Schema.validate_json_schema_value(value, self.to_json_schema(), path)


class Tool(ABC):
    """定义 Agent 可调用工具的统一抽象。"""

    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    _BOOL_TRUE = frozenset(("true", "1", "yes"))
    _BOOL_FALSE = frozenset(("false", "0", "no"))

    @staticmethod
    def _resolve_type(t: Any) -> str | None:
        """从联合类型里提取主类型。

        参数:
            t: 原始 ``type`` 字段值。

        返回:
            非空主类型名称。
        """
        return Schema.resolve_json_schema_type(t)

    @property
    @abstractmethod
    def name(self) -> str:
        """返回工具调用使用的名称。

        返回:
            工具名称字符串。
        """
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """返回工具参数的 JSON Schema。

        返回:
            参数约束字典。
        """
        ...

    @property
    def read_only(self) -> bool:
        """判断工具是否只读。

        返回:
            只读工具返回 ``True``。
        """
        return False

    @property
    def concurrency_safe(self) -> bool:
        """判断工具是否适合与其它工具并发执行。

        返回:
            可并发时返回 ``True``。
        """
        return self.read_only and not self.exclusive

    @property
    def exclusive(self) -> bool:
        """判断工具是否需要独占执行。

        返回:
            需要独占时返回 ``True``。
        """
        return False

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """执行工具主体逻辑。

        参数:
            **kwargs: 经过校验后的工具参数。

        返回:
            字符串结果或内容块列表。
        """
        ...

    def _cast_object(self, obj: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(obj, dict):
            return obj
        props = schema.get("properties", {})
        return {k: self._cast_value(v, props[k]) if k in props else v for k, v in obj.items()}

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """在校验前按 Schema 做安全类型预转换。

        参数:
            params: 原始参数字典。

        返回:
            预转换后的参数字典。
        """
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            return params
        return self._cast_object(params, schema)

    def _cast_value(self, val: Any, schema: dict[str, Any]) -> Any:
        t = self._resolve_type(schema.get("type"))

        if t == "boolean" and isinstance(val, bool):
            return val
        if t == "integer" and isinstance(val, int) and not isinstance(val, bool):
            return val
        if t in self._TYPE_MAP and t not in ("boolean", "integer", "array", "object"):
            expected = self._TYPE_MAP[t]
            if isinstance(val, expected):
                return val

        if isinstance(val, str) and t in ("integer", "number"):
            try:
                return int(val) if t == "integer" else float(val)
            except ValueError:
                return val

        if t == "string":
            return val if val is None else str(val)

        if t == "boolean" and isinstance(val, str):
            low = val.lower()
            if low in self._BOOL_TRUE:
                return True
            if low in self._BOOL_FALSE:
                return False
            return val

        if t == "array" and isinstance(val, list):
            items = schema.get("items")
            return [self._cast_value(x, items) for x in val] if items else val

        if t == "object" and isinstance(val, dict):
            return self._cast_object(val, schema)

        return val

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """按参数 Schema 校验调用参数。

        参数:
            params: 待校验参数字典。

        返回:
            错误信息列表；为空表示校验通过。
        """
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return Schema.validate_json_schema_value(params, {**schema, "type": "object"}, "")

    def to_schema(self) -> dict[str, Any]:
        """导出 OpenAI function calling 所需的工具定义。

        返回:
            OpenAI 风格工具描述字典。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def tool_parameters(schema: dict[str, Any]) -> Callable[[type[_ToolT]], type[_ToolT]]:
    """为工具类挂载参数 Schema 装饰器。

    参数:
        schema: 工具参数的根 Schema 字典。

    返回:
        一个类装饰器，用于注入 ``parameters`` 属性实现。
    """

    def decorator(cls: type[_ToolT]) -> type[_ToolT]:
        """把 Schema 固化到工具类上并补齐 ``parameters`` 属性。

        参数:
            cls: 待装饰的工具类。

        返回:
            注入参数属性后的工具类。
        """
        frozen = deepcopy(schema)

        @property
        def parameters(self: Any) -> dict[str, Any]:
            """返回工具参数 Schema 的独立副本。

            返回:
                当前工具的参数 Schema 副本。
            """
            return deepcopy(frozen)

        cls._tool_parameters_schema = deepcopy(frozen)
        cls.parameters = parameters  # type: ignore[assignment]

        abstract = getattr(cls, "__abstractmethods__", None)
        if abstract is not None and "parameters" in abstract:
            cls.__abstractmethods__ = frozenset(abstract - {"parameters"})  # type: ignore[misc]

        return cls

    return decorator
