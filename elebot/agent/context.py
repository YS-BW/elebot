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
    _MAX_RECENT_HISTORY = 50
    _RUNTIME_CONTEXT_END = "[/运行时上下文]"

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
        parts = [self._get_identity(channel=channel)]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory_store.get_memory_context()
        if memory:
            parts.append(f"# 记忆\n\n{memory}")

        skills_summary = self.skill_registry.build_prompt_summary()
        if skills_summary:
            parts.append(skills_summary)

        entries = self.memory_store.read_unprocessed_history(
            since_cursor=self.memory_store.get_last_dream_cursor()
        )
        if entries:
            capped = entries[-self._MAX_RECENT_HISTORY:]
            parts.append("# 最近历史\n\n" + "\n".join(
                f"- [{e['timestamp']}] {e['content']}" for e in capped
            ))

        parts.append(render_template("agent/task_rules.md"))

        return "\n\n---\n\n".join(parts)

    def _get_identity(self, channel: str | None = None) -> str:
        """返回身份提示词主体。"""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return render_template(
            "agent/identity.md",
            workspace_path=workspace_path,
            runtime=runtime,
            platform_policy=render_template("agent/platform_policy.md", system=system),
            channel=channel or "",
        )

    @staticmethod
    def _build_runtime_context(
        channel: str | None, chat_id: str | None, timezone: str | None = None,
        session_summary: str | None = None,
    ) -> str:
        """构造注入到用户消息前的运行时元数据块。"""
        lines = [f"当前时间：{current_time_str(timezone)}"]
        if channel and chat_id:
            lines += [f"通道：{channel}", f"会话 ID：{chat_id}"]
        if session_summary:
            lines += ["", "[恢复的会话]", session_summary]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines) + "\n" + ContextBuilder._RUNTIME_CONTEXT_END

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

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        media: list[str] | None = None,
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
        )
        user_content = self._build_user_content(current_message, media)

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

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

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
            return text
        return images + [{"type": "text", "text": text}]

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
