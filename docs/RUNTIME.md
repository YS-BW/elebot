# RUNTIME

这篇文档只讲 EleBot 当前已经落地的进程内 runtime，不讨论还没做的系统服务注册、托盘、桌面壳或者 Web 入口。

相关源码：

- [elebot/cli/commands.py](../elebot/cli/commands.py#L196-L343)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L22-L225)
- [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L10-L106)
- [elebot/runtime/state.py](../elebot/runtime/state.py#L14-L35)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L200)
- [tests/cli/test_runtime.py](../tests/cli/test_runtime.py#L13-L88)

## 1. 先记住 runtime 解决了什么问题

在当前实现里，`runtime` 解决的不是“系统后台常驻”这个最终产品问题，而是先把下面这件事收口：

```text
CLI 不再自己拼 MessageBus + Provider + AgentLoop
```

现在这部分装配被统一挪进了 `ElebotRuntime`。

所以你可以把它理解成：

```text
runtime = 主链路运行时装配层 + 生命周期管理层
```

它现在负责三件事：

1. 从配置装配 `Bus`、`provider`、`AgentLoop`
2. 给 CLI 提供统一入口：单次调用、交互模式、后台启动
3. 持有主循环生命周期，避免 CLI 自己管理一套

## 2. 当前启动链路长什么样

现在 `elebot agent` 的入口先加载配置，再装配 runtime，最后才决定是走单次模式还是交互模式。

对应代码在 [elebot/cli/commands.py](../elebot/cli/commands.py#L196-L343)。

简化后的代码可以这样看：

```python
config = _load_runtime_config(config, workspace)
sync_workspace_templates(config.workspace_path)
runtime = _make_runtime(config)

if message:
    response = await runtime.run_once(...)
    await runtime.close()
else:
    await runtime.run_interactive(...)
```

这段代码里可以直接抓住三个层次：

- `_load_runtime_config(...)`
  - 负责解析配置、处理 `--config` 和 `--workspace`
- `_make_runtime(config)`
  - 负责把配置变成一份可运行的 `ElebotRuntime`
- `runtime.run_once()` / `runtime.run_interactive()`
  - 负责真正进入主链路

所以 `commands.py` 现在的职责已经从“自己组装主链路”变成“命令入口 + 参数处理 + 调 runtime”。

## 3. `ElebotRuntime.from_config()` 到底装了什么

runtime 的组装入口在 [elebot/runtime/app.py](../elebot/runtime/app.py#L51-L103)。

核心代码：

```python
bus = resolved_bus_factory()
provider = resolved_provider_builder(config)
defaults = config.agents.defaults
agent_loop = resolved_agent_loop_factory(
    bus=bus,
    provider=provider,
    workspace=config.workspace_path,
    model=defaults.model,
    max_iterations=defaults.max_tool_iterations,
    context_window_tokens=defaults.context_window_tokens,
    web_config=config.tools.web,
    context_block_limit=defaults.context_block_limit,
    max_tool_result_chars=defaults.max_tool_result_chars,
    provider_retry_mode=defaults.provider_retry_mode,
    exec_config=config.tools.exec,
    restrict_to_workspace=config.tools.restrict_to_workspace,
    mcp_servers=config.tools.mcp_servers,
    timezone=defaults.timezone,
    unified_session=defaults.unified_session,
    session_ttl_minutes=defaults.session_ttl_minutes,
)
```

这里不要把它想得太复杂，它本质上就是做了一次“主链路依赖收口”：

- `bus`
  - 提供统一入站 / 出站消息通道
- `provider`
  - 负责模型调用
- `agent_loop`
  - 继续复用现有主链路执行逻辑

然后它把这三样东西连同配置一起塞进 `RuntimeState`。

## 4. `RuntimeState` 里放了什么

`RuntimeState` 在 [elebot/runtime/state.py](../elebot/runtime/state.py#L14-L35)。

核心代码：

```python
@dataclass(slots=True)
class RuntimeState:
    config: Config
    bus: MessageBus
    provider: LLMProvider
    agent_loop: AgentLoop
    serve_task: asyncio.Task[None] | None = None
    started: bool = False
```

这几个字段可以按两类理解：

**依赖对象**

- `config`
- `bus`
- `provider`
- `agent_loop`

**运行态字段**

- `serve_task`
  - 后台运行 `agent_loop.run()` 时持有的协程任务
- `started`
  - 当前 runtime 是否已经进入运行态

所以 `RuntimeState` 不是业务状态仓库，它只是 runtime 的共享运行上下文。

## 5. 生命周期是谁在管

生命周期逻辑在 [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L10-L106)。

你可以直接看这三个方法：

```python
async def start(self) -> asyncio.Task[None]:
    if self.is_running():
        return self._state.serve_task

    task = asyncio.create_task(self._state.agent_loop.run())
    self._state.serve_task = task
    self._state.started = True
    task.add_done_callback(self._handle_task_done)
    await asyncio.sleep(0)
    return task

async def wait(self) -> None:
    task = self._state.serve_task
    if task is None:
        return
    await asyncio.gather(task, return_exceptions=True)

async def close(self) -> None:
    self.request_stop()
    await self.wait()
    await self._state.agent_loop.close_mcp()
    self._state.serve_task = None
    self._state.started = False
```

这三个动作分别对应：

- `start()`
  - 启动长期 `agent_loop.run()`
- `wait()`
  - 等待后台主循环结束
- `close()`
  - 停止消费、等待退出、释放 MCP 资源

所以现在“后台主循环什么时候启动、什么时候结束、什么时候清理资源”不再是 CLI 零散控制，而是 runtime 自己控制。

## 6. 单次模式怎么走 runtime

单次模式走的是 [elebot/runtime/app.py](../elebot/runtime/app.py#L129-L156) 的 `run_once()`。

核心代码：

```python
return await self.agent_loop.process_direct(
    message,
    session_id,
    on_progress=on_progress,
    on_stream=on_stream,
    on_stream_end=on_stream_end,
)
```

这里没有走长期 `run()` 循环，而是直接复用 `AgentLoop.process_direct(...)`。

也就是说：

```text
单次模式 = runtime 负责装配 + AgentLoop.process_direct() 负责执行
```

所以 runtime 不是重写主链路，而是把 CLI 到主链路之间的装配动作收口了。

## 7. 交互模式怎么走 runtime

交互模式现在分成两层：

### 7.1 runtime 层

在 [elebot/runtime/app.py](../elebot/runtime/app.py#L158-L182)：

```python
await run_interactive_loop(
    agent_loop=self.agent_loop,
    bus=self.bus,
    session_id=session_id,
    markdown=markdown,
    renderer_factory=renderer_factory,
    manage_agent_loop=False,
)
```

这里最关键的是：

```python
manage_agent_loop=False
```

这表示交互层现在只负责输入输出，不再重复启动和关闭 `agent_loop.run()`。

### 7.2 CLI 交互层

在 [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L200)：

```python
bus_task = (
    asyncio.create_task(agent_loop.run()) if manage_agent_loop else None
)
```

以及最终清理：

```python
if manage_agent_loop:
    agent_loop.stop()
...
if manage_agent_loop:
    await agent_loop.close_mcp()
```

这段逻辑的意思是：

- 直接单独调用 `run_interactive_loop()` 时
  - 它仍然可以兼容旧的“自己托管主循环”方式
- 通过 `ElebotRuntime.run_interactive()` 调用时
  - 主循环已经由 runtime 托管
  - 交互层不再重复 stop / close

所以当前交互链路已经变成：

```text
commands.agent()
  ↓
runtime.run_interactive()
  ↓
runtime.start()          # 仅在当前还没启动长期主循环时触发
  ↓
interactive.run_interactive_loop(manage_agent_loop=False)
  ↓
runtime.close()          # 仅在本次由 runtime 自己启动时触发
```

## 8. 现在的 runtime 边界在哪里

这一步已经完成的是“进程内 runtime 分层”，不是“系统守护进程产品化”。

当前已经有：

- `elebot/runtime/`
- 统一 runtime 装配入口
- 统一 lifecycle
- CLI 改为复用 runtime

当前还没有：

- `launchd`
- `systemd`
- Windows Service
- 独立后台守护进程
- 托盘 / 菜单栏
- Web / desktop 外壳

所以“系统级后台运行”这个模块当前完成的是第一阶段，不是最终形态。

## 9. 测试怎么验证 runtime

runtime 行为测试在 [tests/cli/test_runtime.py](../tests/cli/test_runtime.py#L13-L88)。

你可以先看两个最关键的断言：

```python
await runtime.start()
await runtime.wait()
await runtime.close()

agent_loop.run.assert_awaited_once()
agent_loop.stop.assert_called_once()
agent_loop.close_mcp.assert_awaited_once()
```

这组测试验证的是：

- runtime 确实负责启动主循环
- runtime 确实负责停止主循环
- runtime 确实负责释放外部资源

交互模式额外验证的是：

```python
await runtime.run_interactive(session_id="cli:test", markdown=True)
assert captured["manage_agent_loop"] is False
```

这说明交互层已经不再重复托管生命周期。

## 10. 你现在应该怎么理解这个模块

最简单的理解方式是：

```text
以前：
CLI 自己装配主链路，自己决定怎么启动 / 停止

现在：
CLI 只负责入口参数和展示
runtime 负责装配和生命周期
AgentLoop 继续负责真正的主链路执行
```

这也是为什么模块一现在已经能作为后续“中断能力、多端入口、多通道能力”的基础层继续往下做。
