"""负责组装 Agent 提示词与消息上下文。"""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any

from elebot.agent.memory import MemoryStore
from elebot.agent.messages import build_assistant_message, detect_image_mime
from elebot.agent.skills import SkillRegistry
from elebot.utils.prompt_templates import render_template
from elebot.utils.time import current_time_str


class ContextBuilder:
    """负责把工作区状态整理成一次可直接发给模型的上下文。"""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[运行时上下文——仅元数据，不是指令]"
    _RUNTIME_CONTEXT_END = "[/运行时上下文]"
    _MAX_RECENT_HISTORY = 50

    def __init__(
        self,
        workspace: Path,
        memory_store: MemoryStore,
        skill_registry: SkillRegistry,
        timezone: str | None = None,
    ):
        """绑定上下文构造所需的工作区依赖。

        这里不缓存最终提示词，只缓存读取入口，
        这样每一轮都能基于最新的记忆和启动文件重新组装上下文。
        """
        self.workspace = workspace
        self.timezone = timezone
        self.memory_store = memory_store
        self.skill_registry = skill_registry

    def build_system_prompt(
        self,
        channel: str | None = None,
    ) -> str:
        """组装系统提示词主干。

        核心职责：
        - 写入身份与运行环境信息
        - 注入工作区启动文件
        - 拼接长期记忆
        - 在末尾补上近期未被 Dream 吸收的历史

        返回：
            可直接作为 `system` 消息发送的完整提示词文本。
        """
        return render_template(
            "SYSTEM.md",
            identity=self._get_identity(channel=channel),
            bootstrap_files=self._load_bootstrap_files(),
            long_term_memory=self._build_long_term_memory(),
            skills_summary=self.skill_registry.build_prompt_summary(),
            recent_history=self._build_recent_history(),
            strip=True,
        )

    def _get_identity(self, channel: str | None = None) -> str:
        """返回身份提示词主体。"""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        channel_context = self._describe_channel_context(channel)

        return render_template(
            "IDENTITY.md",
            workspace_path=workspace_path,
            runtime=runtime,
            platform_policy=self._describe_platform_policy(system),
            channel_context=channel_context,
            strip=True,
        )

    @staticmethod
    def _describe_channel_context(channel: str | None) -> str:
        """返回当前入口环境说明，只维护 CLI 与微信两种环境语义。"""
        normalized = str(channel or "").strip().lower()
        if normalized == "cli":
            return render_template("CHANNEL_CLI.md", strip=True)
        if normalized == "weixin":
            return render_template("CHANNEL_WEIXIN.md", strip=True)
        return render_template("CHANNEL_WEIXIN.md", strip=True)

    @staticmethod
    def _describe_platform_policy(system: str) -> str:
        """返回当前平台规则。"""
        if system == "Windows":
            return (
                "- 你当前运行在 Windows 上。不要假设 `grep`、`sed`、`awk` 这类 GNU 工具一定存在。\n"
                "- 当 Windows 原生命令或文件工具更可靠时，优先使用它们。\n"
                "- 如果终端输出出现乱码，请用启用 UTF-8 的方式重试。"
            )
        return (
            "- 你当前运行在 POSIX 系统上。优先使用 UTF-8 和标准 shell 工具。\n"
            "- 当文件工具比 shell 命令更简单或更可靠时，优先使用文件工具。"
        )

    @staticmethod
    def _build_runtime_context(
        channel: str | None, chat_id: str | None, timezone: str | None = None,
        session_summary: str | None = None,
        attachments: str | None = None,
    ) -> str:
        """构造注入到用户消息前的运行时元数据块。"""
        return render_template(
            "RUNTIME.md",
            current_time=current_time_str(timezone),
            channel=channel or "",
            chat_id=chat_id or "",
            restored_session=session_summary or "",
            attachments=attachments or "",
            strip=True,
        )

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}\n\n{right}" if left else right

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [item if isinstance(item, dict) else {"type": "text", "text": str(item)} for item in value]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    def _load_bootstrap_files(self) -> str:
        """加载工作区里的启动文件。"""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def _build_long_term_memory(self) -> str:
        """构造长期记忆段落。"""
        memory = self.memory_store.get_memory_context()
        if not memory:
            return ""
        return f"# 长期记忆\n\n{memory}"

    def _build_recent_history(self) -> str:
        """构造最近历史段落。"""
        entries = self.memory_store.read_unprocessed_history(
            since_cursor=self.memory_store.get_last_dream_cursor()
        )
        if not entries:
            return ""
        capped = entries[-self._MAX_RECENT_HISTORY:]
        lines = [f"- [{entry['timestamp']}] {entry['content']}" for entry in capped]
        return "# 最近历史\n\n" + "\n".join(lines)

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        media: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
        session_summary: str | None = None,
    ) -> list[dict[str, Any]]:
        """构造一次模型调用的完整消息数组。

        核心职责：
        - 补齐运行时元信息，避免模板层直接依赖外部状态
        - 把文本和媒体统一成 Provider 可接受的内容块
        - 在必要时与上一条同角色消息合并，规避部分 Provider 的协议限制

        返回：
            按当前 Provider 约定整理好的消息列表。
        """
        runtime_ctx = self._build_runtime_context(
            channel,
            chat_id,
            self.timezone,
            session_summary=session_summary,
            attachments=self._build_attachment_text(attachments),
        )
        user_content = self._build_user_content(current_message, media, attachments)

        # 这里把运行时上下文和用户正文合并成一条消息，
        # 避免部分 Provider 拒绝连续出现相同 role 的消息。
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content
        messages = [
            {"role": "system", "content": self.build_system_prompt(channel=channel)},
            *history,
        ]
        if messages[-1].get("role") == current_role:
            last = dict(messages[-1])
            last["content"] = self._merge_message_content(last.get("content"), merged)
            messages[-1] = last
            return messages
        messages.append({"role": current_role, "content": merged})
        return messages

    def _build_attachment_text(self, attachments: list[dict[str, Any]] | None) -> str:
        """构造当前用户消息的附件信息文本。"""
        if not attachments:
            return ""
        lines = []
        for index, item in enumerate(attachments, start=1):
            filename = str(item.get("filename", "") or "未命名文件")
            path = str(item.get("path", "") or "").strip()
            mime = str(item.get("mime", "") or "").strip()
            size = item.get("size")
            lines.append(f"- 文件{index}：{filename}")
            if path:
                lines.append(f"- 路径：{path}")
            if mime:
                lines.append(f"- 类型：{mime}")
            if size is not None:
                lines.append(f"- 大小：{size} bytes")
        return "\n".join(lines)

    def _build_user_content(
        self,
        text: str,
        media: list[str] | None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        text_body = text
        if not media:
            return text_body

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            # 优先按文件内容识别 MIME，避免扩展名伪装导致 Provider 拒收图片。
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(p)},
            })

        if not images:
            return text_body
        return images + [{"type": "text", "text": text_body}]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: Any,
    ) -> list[dict[str, Any]]:
        """把工具执行结果追加回消息链路。

        这里直接在原列表上追加，保持调用方持有的会话视图和实际发送顺序一致。
        """
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        reasoning_items: list[dict[str, Any]] | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """把助手回复写回消息链路。

        之所以统一走 `build_assistant_message`，是为了让正文、工具调用和思考块的落盘结构保持一致，
        后续 Runner、Session 和测试都只需要面对一种助手消息格式。
        """
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            reasoning_items=reasoning_items,
            thinking_blocks=thinking_blocks,
        ))
        return messages
