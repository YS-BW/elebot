"""管理 EleBot runtime 的启动与关闭流程。"""

from __future__ import annotations

import asyncio

from elebot.runtime.state import RuntimeState


class RuntimeLifecycle:
    """管理 runtime 主循环任务的生命周期。"""

    def __init__(self, state: RuntimeState) -> None:
        """绑定要管理的 runtime 状态。

        参数:
            state: 当前 runtime 的共享状态对象。

        返回:
            无返回值。
        """
        self._state = state

    def is_running(self) -> bool:
        """判断后台主循环是否处于运行中。

        参数:
            无。

        返回:
            如果后台任务存在且尚未结束，则返回 `True`。
        """
        task = self._state.serve_task
        return task is not None and not task.done()

    async def start(self) -> asyncio.Task[None]:
        """在后台启动主循环，并返回任务句柄。

        参数:
            无。

        返回:
            承载 `agent_loop.run()` 的后台任务。
        """
        if self.is_running():
            return self._state.serve_task

        task = asyncio.create_task(self._state.agent_loop.run())
        self._state.serve_task = task
        self._state.started = True
        task.add_done_callback(self._handle_task_done)
        await asyncio.sleep(0)
        return task

    def request_stop(self) -> None:
        """请求主循环停止消费新消息。

        参数:
            无。

        返回:
            无返回值。
        """
        self._state.agent_loop.stop()

    async def wait(self) -> None:
        """等待后台主循环结束。

        参数:
            无。

        返回:
            无返回值。
        """
        task = self._state.serve_task
        if task is None:
            return
        await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        """停止 runtime 并释放主循环外部资源。

        参数:
            无。

        返回:
            无返回值。
        """
        self.request_stop()
        await self.wait()
        await self._state.agent_loop.close_mcp()
        self._state.serve_task = None
        self._state.started = False

    def _handle_task_done(self, task: asyncio.Task[None]) -> None:
        """在后台任务结束时回收状态标记。

        参数:
            task: 已结束的后台主循环任务。

        返回:
            无返回值。
        """
        if self._state.serve_task is task:
            self._state.serve_task = None
        self._state.started = False
