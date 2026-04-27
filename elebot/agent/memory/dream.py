"""Dream 长期记忆整理流程。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from elebot.agent.memory.store import MemoryStore
from elebot.agent.runner import AgentRunner, AgentRunSpec
from elebot.agent.tools.registry import ToolRegistry
from elebot.utils.prompt_templates import render_template


class Dream:
    """在后台批量吸收历史，并把长期记忆整理成稳定文件。"""

    def __init__(
        self,
        store: MemoryStore,
        provider,
        model: str,
        max_batch_size: int = 20,
        max_iterations: int = 10,
        max_tool_result_chars: int = 16_000,
    ):
        """绑定 Dream 所需的存储、模型和工具预算。

        参数:
            store: 记忆存储 owner。
            provider: 当前主模型 provider。
            model: 默认模型名。
            max_batch_size: 单轮最多处理的历史条数。
            max_iterations: Dream agent 的最大工具迭代次数。
            max_tool_result_chars: Dream agent 工具结果保留上限。

        返回:
            无返回值。
        """
        self.store = store
        self.provider = provider
        self.model = model
        self.max_batch_size = max_batch_size
        self.max_iterations = max_iterations
        self.max_tool_result_chars = max_tool_result_chars
        self._runner = AgentRunner(provider)
        self._tools = self._build_tools()

    def _build_tools(self) -> ToolRegistry:
        """构造 Dream 专用的最小工具集合。"""
        from elebot.agent.tools.filesystem import EditFileTool, ReadFileTool

        tools = ToolRegistry()
        workspace = self.store.workspace
        tools.register(
            ReadFileTool(
                workspace=workspace,
                allowed_dir=workspace,
            )
        )
        tools.register(EditFileTool(workspace=workspace, allowed_dir=workspace))
        return tools

    async def run(self) -> bool:
        """处理尚未进入 Dream 的历史记录。

        参数:
            无。

        返回:
            只要本轮实际处理了历史条目就返回 ``True``。
        """
        last_cursor = self.store.get_last_dream_cursor()
        entries = self.store.read_unprocessed_history(since_cursor=last_cursor)
        if not entries:
            return False

        batch = entries[: self.max_batch_size]
        logger.info(
            "Dream: processing {} entries (cursor {}→{}), batch={}",
            len(entries),
            last_cursor,
            batch[-1]["cursor"],
            len(batch),
        )

        # 先把批次历史整理成稳定文本，便于 Phase 1 做整体分析。
        history_text = "\n".join(f"[{entry['timestamp']}] {entry['content']}" for entry in batch)

        # 当前记忆文件内容需要一并提供，避免 Dream 基于过期上下文改写。
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_memory = self.store.read_memory() or "(empty)"
        current_soul = self.store.read_soul() or "(empty)"
        current_user = self.store.read_user() or "(empty)"

        file_context = (
            f"## 当前日期\n{current_date}\n\n"
            f"## 当前 MEMORY.md（{len(current_memory)} 个字符）\n{current_memory}\n\n"
            f"## 当前 SOUL.md（{len(current_soul)} 个字符）\n{current_soul}\n\n"
            f"## 当前 USER.md（{len(current_user)} 个字符）\n{current_user}"
        )

        # 第一阶段只做分析，第二阶段只负责把结论增量写回记忆文件。
        phase1_prompt = f"## 对话历史\n{history_text}\n\n{file_context}"

        try:
            phase1_response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": render_template("agent/dream_phase1.md", strip=True),
                    },
                    {"role": "user", "content": phase1_prompt},
                ],
                tools=None,
                tool_choice=None,
            )
            analysis = phase1_response.content or ""
            logger.debug(
                "Dream Phase 1 analysis ({} chars): {}",
                len(analysis),
                analysis[:500],
            )
        except Exception:
            logger.exception("Dream Phase 1 failed")
            return False

        # 第二阶段交给 AgentRunner 做增量修改，避免整体覆盖文件。
        phase2_prompt = f"## 分析结果\n{analysis}\n\n{file_context}"
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": render_template("agent/dream_phase2.md", strip=True),
            },
            {"role": "user", "content": phase2_prompt},
        ]

        try:
            result = await self._runner.run(
                AgentRunSpec(
                    initial_messages=messages,
                    tools=self._tools,
                    model=self.model,
                    max_iterations=self.max_iterations,
                    max_tool_result_chars=self.max_tool_result_chars,
                    fail_on_tool_error=False,
                )
            )
            logger.debug(
                "Dream Phase 2 complete: stop_reason={}, tool_events={}",
                result.stop_reason,
                len(result.tool_events),
            )
            for event in result.tool_events or []:
                logger.info(
                    "Dream tool_event: name={}, status={}, detail={}",
                    event.get("name"),
                    event.get("status"),
                    event.get("detail", "")[:200],
                )
        except Exception:
            logger.exception("Dream Phase 2 failed")
            result = None

        # 变更摘要只取成功工具事件，便于后续自动提交时控制噪音。
        changelog: list[str] = []
        if result and result.tool_events:
            for event in result.tool_events:
                if event["status"] == "ok":
                    changelog.append(f"{event['name']}: {event['detail']}")

        # 无论第二阶段是否完整成功，都推进游标，避免反复重跑同一批分析。
        new_cursor = batch[-1]["cursor"]
        self.store.set_last_dream_cursor(new_cursor)
        self.store.compact_history()

        if result and result.stop_reason == "completed":
            logger.info(
                "Dream done: {} change(s), cursor advanced to {}",
                len(changelog),
                new_cursor,
            )
        else:
            reason = result.stop_reason if result else "exception"
            logger.warning(
                "Dream incomplete ({}): cursor advanced to {}",
                reason,
                new_cursor,
            )

        # 只有真正落了文件改动时才自动提交，避免制造空提交噪音。
        if changelog and self.store.git.is_initialized():
            timestamp = batch[-1]["timestamp"]
            sha = self.store.git.auto_commit(
                f"dream: {timestamp}, {len(changelog)} change(s)"
            )
            if sha:
                logger.info("Dream commit: {}", sha)

        return True
