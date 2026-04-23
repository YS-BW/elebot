"""工具注册表，负责动态管理与调度 Agent 工具。"""

from typing import Any

from elebot.agent.tools.base import Tool


class ToolRegistry:
    """维护工具实例并提供统一调用入口。"""

    def __init__(self):
        """初始化空工具注册表。

        返回:
            无返回值。
        """
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具实例。

        参数:
            tool: 待注册工具。

        返回:
            无返回值。
        """
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """按名称注销工具。

        参数:
            name: 工具名称。

        返回:
            无返回值。
        """
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """按名称获取工具。

        参数:
            name: 工具名称。

        返回:
            对应工具实例；不存在时返回 ``None``。
        """
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """判断工具是否已注册。

        参数:
            name: 工具名称。

        返回:
            已注册时返回 ``True``。
        """
        return name in self._tools

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        """Extract a normalized tool name from either OpenAI or flat schemas."""
        fn = schema.get("function")
        if isinstance(fn, dict):
            name = fn.get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name")
        return name if isinstance(name, str) else ""

    def get_definitions(self) -> list[dict[str, Any]]:
        """按稳定顺序导出工具定义列表。

        返回:
            先内置后 MCP 的工具定义字典列表。
        """
        definitions = [tool.to_schema() for tool in self._tools.values()]
        builtins: list[dict[str, Any]] = []
        mcp_tools: list[dict[str, Any]] = []
        for schema in definitions:
            name = self._schema_name(schema)
            if name.startswith("mcp_"):
                mcp_tools.append(schema)
            else:
                builtins.append(schema)

        builtins.sort(key=self._schema_name)
        mcp_tools.sort(key=self._schema_name)
        return builtins + mcp_tools

    def prepare_call(
        self,
        name: str,
        params: dict[str, Any],
    ) -> tuple[Tool | None, dict[str, Any], str | None]:
        """解析、预转换并校验一次工具调用。

        参数:
            name: 工具名称。
            params: 原始参数字典。

        返回:
            三元组 ``(tool, cast_params, error)``。
        """
        # 这里先拦截明显错误的参数形态，避免把低质量错误信息泄露到更深层调用链。
        if not isinstance(params, dict) and name in ('write_file', 'read_file'):
            return None, params, (
                f"Error: Tool '{name}' parameters must be a JSON object, got {type(params).__name__}. "
                "Use named parameters: tool_name(param1=\"value1\", param2=\"value2\")"
            )

        tool = self._tools.get(name)
        if not tool:
            return None, params, (
                f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
            )

        cast_params = tool.cast_params(params)
        errors = tool.validate_params(cast_params)
        if errors:
            return tool, cast_params, (
                f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors)
            )
        return tool, cast_params, None

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        """按名称执行一个工具。

        参数:
            name: 工具名称。
            params: 工具参数。

        返回:
            工具执行结果或错误提示。
        """
        _HINT = "\n\n[Analyze the error above and try a different approach.]"
        tool, params, error = self.prepare_call(name, params)
        if error:
            return error + _HINT

        try:
            assert tool is not None  # 这里能断言非空，是因为 prepare_call 已完成存在性校验。
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """返回当前已注册的工具名称列表。

        返回:
            工具名列表。
        """
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
