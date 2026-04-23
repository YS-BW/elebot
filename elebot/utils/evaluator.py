"""后台任务结果评估。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from elebot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from elebot.providers.base import LLMProvider

_EVALUATE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_notification",
            "description": "Decide whether the user should be notified about this background task result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "should_notify": {
                        "type": "boolean",
                        "description": "true = result contains actionable/important info the user should see; false = routine or empty, safe to suppress",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One-sentence reason for the decision",
                    },
                },
                "required": ["should_notify"],
            },
        },
    }
]

async def evaluate_response(
    response: str,
    task_context: str,
    provider: LLMProvider,
    model: str,
) -> bool:
    """判断后台任务结果是否需要通知用户。

    参数:
        response: 后台任务产生的结果文本。
        task_context: 任务上下文描述。
        provider: 用于评估的模型提供方。
        model: 评估时使用的模型名。

    返回:
        需要通知用户时返回 True，否则返回 False。
    """
    try:
        llm_response = await provider.chat_with_retry(
            messages=[
                {"role": "system", "content": render_template("agent/evaluator.md", part="system")},
                {"role": "user", "content": render_template(
                    "agent/evaluator.md",
                    part="user",
                    task_context=task_context,
                    response=response,
                )},
            ],
            tools=_EVALUATE_TOOL,
            model=model,
            max_tokens=256,
            temperature=0.0,
        )

        if not llm_response.has_tool_calls:
            logger.warning("evaluate_response: no tool call returned, defaulting to notify")
            return True

        args = llm_response.tool_calls[0].arguments
        should_notify = args.get("should_notify", True)
        reason = args.get("reason", "")
        logger.info("evaluate_response: should_notify={}, reason={}", should_notify, reason)
        return bool(should_notify)

    except Exception:
        logger.exception("evaluate_response failed, defaulting to notify")
        return True
