"""子代理创建工具。"""

from typing import TYPE_CHECKING, Any

from elebot.agent.tools.base import Tool, tool_parameters
from elebot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from elebot.agent.subagent import SubagentManager


@tool_parameters(
    tool_parameters_schema(
        task=StringSchema("The task for the subagent to complete"),
        label=StringSchema("Optional short label for the task (for display)"),
        required=["task"],
    )
)
class SpawnTool(Tool):
    """用于创建后台子代理执行独立任务。"""

    def __init__(self, manager: "SubagentManager"):
        """初始化子代理工具。

        参数:
            manager: 子代理管理器。

        返回:
            无返回值。
        """
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        """设置子代理回传结果所使用的来源上下文。

        参数:
            channel: 来源渠道名。
            chat_id: 来源会话标识。

        返回:
            无返回值。
        """
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "spawn"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )

    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """创建一个子代理执行指定任务。

        参数:
            task: 子代理要执行的任务描述。
            label: 可选的短标签。
            **kwargs: 兼容额外参数。

        返回:
            子代理创建结果文本。
        """
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
        )
