"""定时任务到消息的转换。"""

from __future__ import annotations

from elebot.bus.events import InboundMessage
from elebot.tasks.models import ScheduledTask


def build_task_inbound_message(task: ScheduledTask) -> InboundMessage:
    """把任务转换成标准入站消息。

    参数:
        task: 待触发任务。

    返回:
        可直接投递到消息总线的入站消息。
    """
    channel, _, chat_id = task.session_key.partition(":")
    content = (
        "系统定时任务触发：\n"
        f"- 任务 ID：{task.task_id}\n"
        f"- 任务类型：{task.schedule_type}\n"
        f"- 任务内容：{task.content}\n"
        f"- 第 {task.run_count + 1} 次触发\n"
        "这是一次自动任务触发，不是用户实时输入。"
    )
    return InboundMessage(
        channel="system",
        sender_id="scheduler",
        chat_id=chat_id or "scheduled",
        content=content,
        session_key_override=task.session_key,
        metadata={
            "task_id": task.task_id,
            "schedule_type": task.schedule_type,
            "scheduled_trigger": True,
            "original_channel": channel or "",
            "task_content": task.content,
            "task_source": task.source,
            "task_run_count": task.run_count + 1,
        },
    )
