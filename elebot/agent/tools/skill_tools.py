"""全局 skill 管理工具。"""

from __future__ import annotations

from typing import Any

from elebot.agent.skills import SkillManager, SkillRegistry
from elebot.agent.tools.base import Tool, tool_parameters
from elebot.agent.tools.schema import StringSchema, tool_parameters_schema


class _SkillTool(Tool):
    """skill 管理工具共享基类。"""

    def __init__(
        self,
        *,
        manager: SkillManager | None = None,
        registry: SkillRegistry | None = None,
    ) -> None:
        """初始化 skill 管理工具。

        参数:
            manager: 可选的 skill 管理 owner。
            registry: 可选的 skill 只读注册表。

        返回:
            无返回值。
        """
        self.manager = manager or SkillManager()
        self.registry = registry or SkillRegistry()


@tool_parameters(tool_parameters_schema(required=[]))
class ListSkillsTool(_SkillTool):
    """列出当前已安装 skill。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "list_skills"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "List all installed global skills available under ~/.elebot/skills."

    @property
    def read_only(self) -> bool:
        """声明该工具只读取状态。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, **kwargs: Any) -> str:
        """返回当前已安装 skill 列表。

        参数:
            **kwargs: 无额外参数。

        返回:
            面向模型和终端的技能列表文本。
        """
        del kwargs
        items = self.registry.list_status()
        if not items:
            return "当前没有已安装的 skills。"

        lines = ["当前已安装的 skills："]
        for item in items:
            display_name = str(item.get("name") or item.get("key") or "")
            description = str(item.get("description") or "暂无描述。")
            lines.append(f"- `{item['key']}` {display_name}：{description}")
        return "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        source=StringSchema("Skill 来源：本地目录、下载链接或 Git 链接", min_length=1),
        required=["source"],
    )
)
class InstallSkillTool(_SkillTool):
    """安装一个全局 skill。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "install_skill"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return (
            "Install a global skill from a local directory, downloadable archive URL, "
            "or Git repository URL."
        )

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, *, source: str, **kwargs: Any) -> str:
        """安装指定来源的 skill。

        参数:
            source: skill 来源。
            **kwargs: 预留的额外参数。

        返回:
            安装结果文本。
        """
        del kwargs
        ok, message = self.manager.install(source)
        if not ok:
            return f"Error: {message}"
        return message


@tool_parameters(
    tool_parameters_schema(
        skill_key=StringSchema("要卸载的 skill 目录名", min_length=1),
        required=["skill_key"],
    )
)
class UninstallSkillTool(_SkillTool):
    """卸载一个全局 skill。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "uninstall_skill"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "Remove an installed global skill from ~/.elebot/skills."

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, *, skill_key: str, **kwargs: Any) -> str:
        """卸载指定 skill。

        参数:
            skill_key: skill 目录名。
            **kwargs: 预留的额外参数。

        返回:
            卸载结果文本。
        """
        del kwargs
        ok, message = self.manager.uninstall(skill_key)
        if not ok:
            return f"Error: {message}"
        return message
