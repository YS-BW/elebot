# Agent 主循环

这篇文档只讲 agent 主链路怎么跑，不讲 provider 细节实现。

相关源码：

- [elebot/agent/loop.py](../elebot/agent/loop.py#L333-L979)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L180)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L15-L144)

## 1. 主循环总览

可以先记住这一条：

```text
InboundMessage
  ↓
AgentLoop.run()
  ↓
_dispatch()
  ↓
_process_message_result()
  ↓
ContextBuilder.build_messages()
  ↓
AgentRunner.run()
  ↓
_save_turn()
  ↓
OutboundMessage
```

## 2. 入口：`AgentLoop.run()`

实现见 [elebot/agent/loop.py](../elebot/agent/loop.py#L430-L495)。

核心代码：

```python
while self._running:
    try:
        msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
    except asyncio.TimeoutError:
        self.auto_compact.check_expired(self._schedule_background)
        continue

    raw = msg.content.strip()
    if self.commands.is_priority(raw):
        ...
        continue

    task = asyncio.create_task(self._dispatch(msg))
```

这段逻辑做了三件事：

1. 从 bus 持续取消息
2. 空闲时顺手检查过期 session
3. 把普通消息交给 `_dispatch()` 异步处理

## 3. 同 session 串行，跨 session 并发

这件事在 [elebot/agent/loop.py](../elebot/agent/loop.py#L497-L580) 的 `_dispatch()` 完成。

核心代码：

```python
session_key = self._effective_session_key(msg)
lock = self._session_locks.setdefault(session_key, asyncio.Lock())

async with lock, gate:
    response = await self._process_message(...)
```

含义很直接：

- 同一个 `session_key` 共享同一把锁
- 所以同一个 session 不会并发执行两轮 agent
- 不同 session 则可以并发

这就是当前项目的并发边界。

## 4. 为什么要有 pending queue

还是在 `_dispatch()`：

```python
pending = asyncio.Queue(maxsize=20)
self._pending_queues[session_key] = pending
```

如果同一个 session 已经在跑，新的消息不会立刻启动第二个竞争任务，而是优先尝试塞进待注入队列：

```python
if effective_key in self._pending_queues:
    self._pending_queues[effective_key].put_nowait(pending_msg)
    continue
```

这说明当前设计不是“同 session 并发多轮”，而是：

> 当前一轮还没跑完时，后续追问优先作为注入消息并入这一轮。

## 5. `_process_message_result()` 是真正的核心入口

实现见 [elebot/agent/loop.py](../elebot/agent/loop.py#L635-L733)。

代码结构可以简化成这样：

```python
session = self.sessions.get_or_create(key)
if self._restore_runtime_checkpoint(session):
    self.sessions.save(session)

session, pending = self.auto_compact.prepare_session(session, key)

if result := await self.commands.dispatch(ctx):
    return DirectProcessResult(...)

await self.consolidator.maybe_consolidate_by_tokens(session)

history = session.get_history(max_messages=0)
initial_messages = self.context.build_messages(...)

final_content, tools_used, all_msgs, stop_reason, had_injections = await self._run_agent_loop(...)

self._save_turn(session, all_msgs, 1 + len(history))
self.sessions.save(session)
```

这就是一轮正常请求的主体流程。

## 6. 这一步里先做了哪些预处理

### 6.1 恢复未完成检查点

```python
if self._restore_runtime_checkpoint(session):
    self.sessions.save(session)
```

如果上次执行半路中断，会先把中间状态补回 session。

### 6.2 消费空闲压缩带回来的摘要

```python
session, pending = self.auto_compact.prepare_session(session, key)
```

这里返回的 `pending` 会作为恢复摘要进入本轮上下文。

### 6.3 优先处理本地命令

```python
if result := await self.commands.dispatch(ctx):
    return DirectProcessResult(...)
```

像 `/new`、`/dream`、`/status` 这类命令不会进模型。

### 6.4 必要时做 token 压缩

```python
await self.consolidator.maybe_consolidate_by_tokens(session)
```

这一步是为了防止当前上下文太长跑不动。

## 7. `_run_agent_loop()` 负责什么

实现见 [elebot/agent/loop.py](../elebot/agent/loop.py#L339-L428)。

这层主要做两件事：

1. 组装 `AgentRunSpec`
2. 把外部回调桥接给 `AgentRunner`

核心代码：

```python
result = await self.runner.run(AgentRunSpec(
    initial_messages=initial_messages,
    tools=self.tools,
    model=self.model,
    max_iterations=self.max_iterations,
    ...
    checkpoint_callback=_checkpoint,
    injection_callback=_drain_pending,
))
```

你可以把它理解成：

- `AgentLoop` 管 session / bus / command / memory
- `AgentRunner` 专注一轮内部的 LLM + tools 循环

## 8. 流式输出是怎么接回 CLI 的

在 `_dispatch()` 里，如果消息声明 `_wants_stream`，就会挂载两个回调：

```python
async def on_stream(delta: str) -> None:
    meta["_stream_delta"] = True
    await self.bus.publish_outbound(OutboundMessage(...))

async def on_stream_end(*, resuming: bool = False) -> None:
    meta["_stream_end"] = True
    meta["_resuming"] = resuming
    await self.bus.publish_outbound(OutboundMessage(...))
```

这说明：

- agent 不直接操作终端
- 它只把流式事件发回 bus
- CLI 收到后自行渲染

## 9. 一轮结束后，为什么还要再调一次压缩

看 [elebot/agent/loop.py](../elebot/agent/loop.py#L709-L712)：

```python
self._save_turn(session, all_msgs, 1 + len(history))
self._clear_runtime_checkpoint(session)
self.sessions.save(session)
self._schedule_background(self.consolidator.maybe_consolidate_by_tokens(session))
```

这说明 agent 在一轮结束后会：

1. 先把新增消息写回 session
2. 再后台检查一次会不会超 token

所以 token 压缩既可能发生在处理前，也可能发生在处理后。

## 10. `/stop` 为什么现在只能停任务，不能像 nanobot 那样中断当前生成

`/stop` 实现在 [elebot/command/builtin.py](../elebot/command/builtin.py#L27-L42)：

```python
tasks = loop._active_tasks.pop(msg.session_key, [])
cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
```

它能做的是：

- 找到当前 session 的 asyncio task
- 对 task 发取消

但当前交互模式下，没有更细粒度的“流式生成即时抢占协议”。  
所以它更像任务取消，不是 provider 级别的强中断。

## 11. 这条主循环怎么退出

在 [elebot/cli/interactive.py](../elebot/cli/interactive.py#L176-L180)：

```python
agent_loop.stop()
outbound_task.cancel()
await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
await agent_loop.close_mcp()
```

所以关闭交互模式时会做三件事：

- 停止 agent loop
- 取消出站消费任务
- 清理 MCP 连接和后台任务

## 12. 读完这篇后，下一步看什么

推荐继续看：

- [上下文构建](./context-construction.md)
- [记忆系统设计](./memory-design.md)
