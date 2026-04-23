"""消息投递工具，用于向用户发送文本与附件。"""

from typing import Any, Awaitable, Callable

from elebot.agent.tools.base import Tool, tool_parameters
from elebot.agent.tools.schema import ArraySchema, StringSchema, tool_parameters_schema
from elebot.bus.events import OutboundMessage


@tool_parameters(
    tool_parameters_schema(
        content=StringSchema("The message content to send"),
        channel=StringSchema("Optional: target channel (telegram, discord, etc.)"),
        chat_id=StringSchema("Optional: target chat/user ID"),
        media=ArraySchema(
            StringSchema(""),
            description="Optional: list of file paths to attach (images, audio, documents)",
        ),
        required=["content"],
    )
)
class MessageTool(Tool):
    """负责向各聊天渠道发送消息的工具。"""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        """初始化消息工具。

        参数:
            send_callback: 真实发送消息的回调。
            default_channel: 默认渠道名。
            default_chat_id: 默认聊天对象标识。
            default_message_id: 默认引用消息标识。

        返回:
            无返回值。
        """
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id
        self._sent_in_turn: bool = False

    def set_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """设置默认消息上下文。

        参数:
            channel: 默认渠道名。
            chat_id: 默认聊天对象标识。
            message_id: 默认引用消息标识。

        返回:
            无返回值。
        """
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """更新消息发送回调。

        参数:
            callback: 新的发送回调。

        返回:
            无返回值。
        """
        self._send_callback = callback

    def start_turn(self) -> None:
        """开始新一轮对话时重置发送标记。

        返回:
            无返回值。
        """
        self._sent_in_turn = False

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "message"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return (
            "Send a message to the user, optionally with file attachments. "
            "This is the ONLY way to deliver files (images, documents, audio, video) to the user. "
            "Use the 'media' parameter with file paths to attach files. "
            "Do NOT use read_file to send files — that only reads content for your own analysis."
        )

    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        **kwargs: Any
    ) -> str:
        """发送一条消息到目标渠道。

        参数:
            content: 消息正文。
            channel: 目标渠道名。
            chat_id: 目标聊天对象标识。
            message_id: 可选引用消息标识。
            media: 附件路径列表。
            **kwargs: 兼容额外参数。

        返回:
            发送结果文本。
        """
        from elebot.utils.helpers import strip_think
        content = strip_think(content)
        
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        # 只有发回原会话时才继承默认 message_id，跨会话复用会把回复错误路由到旧会话。
        if channel == self._default_channel and chat_id == self._default_chat_id:
            message_id = message_id or self._default_message_id
        else:
            message_id = None

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        if not self._send_callback:
            return "Error: Message sending not configured"

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata={
                "message_id": message_id,
            } if message_id else {},
        )

        try:
            await self._send_callback(msg)
            if channel == self._default_channel and chat_id == self._default_chat_id:
                self._sent_in_turn = True
            media_info = f" with {len(media)} attachments" if media else ""
            return f"Message sent to {channel}:{chat_id}{media_info}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
