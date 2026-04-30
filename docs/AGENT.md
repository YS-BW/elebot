# Agent 主循环

这篇文档只讲 `AgentLoop` 当前真实落地的执行链路，不讨论已经删除的旧子代理体系，也不把中断能力写成未来设想。

相关源码：

- [elebot/agent/loop.py](../elebot/agent/loop.py#L84-L1420)
- [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L24-L95)
- [elebot/agent/context.py](../elebot/agent/context.py#L16-L239)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L11-L58)
- [elebot/cron/service.py](../elebot/cron/service.py#L25-L384)

## 1. `AgentLoop` 现在是什么 owner

`AgentLoop` 仍然是主链路执行 owner。

它负责把下面这些东西串起来：

- `Bus`
- `SessionManager`
- `ContextBuilder`
- `MemoryStore / Consolidator / Dream`
- `CronService`
- `CommandRouter`
- `ToolRegistry`
- `AgentRunner`

可以先把它理解成：

```text
AgentLoop = 会话内控制中心
```

## 2. 初始化阶段会装哪些东西

`AgentLoop.__init__()` 当前只做装配和绑定，不再把各种副作用散在别的模块里。

初始化时会完成四件事：

1. 绑定外部依赖，例如 `Bus`、provider、workspace
2. 创建执行 owner，例如 `MemoryStore`、`CronService`、`CommandRouter`
3. 通过 [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L24-L95) 注册默认工具
4. 注册当前保留的 slash 命令

这里要注意两条已经固定下来的边界：

- 工具集合的定义在 `default_tools.py`，不再塞回 `loop.py`
- 命令系统只是协议层，真正的业务 owner 还是 `AgentLoop`、`CronService`、`MemoryStore`

## 3. 一条消息怎么进入主循环

`run()` 会持续消费 `Bus` 的入站消息，再按会话分发到 `_dispatch()`。

可以先记成：

```text
Bus.consume_inbound()
  ↓
AgentLoop._dispatch()
  ↓
AgentLoop._process_message_result()
```

`_dispatch()` 这一层会负责：

- 为流式回复转发 `_stream_delta / _stream_end`
- 为每个会话维护独立活跃任务
- 捕获真正的中断取消
- 保证最终一定有一条可结束本轮的 outbound

## 4. 一条普通消息怎么处理

真正的会话内处理入口在 `_process_message_result()`。

当前顺序固定是：

1. 读取或创建 session
2. 恢复上一次未完整收尾的 runtime checkpoint
3. 优先检查 slash 命令
4. 必要时触发 token 压缩
5. 记录显式提到的 skill
6. 通过 `ContextBuilder` 组装系统提示词、历史、运行时元数据和多模态内容
7. 调 `AgentRunner` 跑模型与工具闭环
8. 把新形成的合法消息写回 session

这里最重要的事实是：

- slash 命令是在进模型之前处理的
- session、memory、cron 都在主链路里，不是外围插件
- `ContextBuilder` 只负责组装上下文，不再自己创建 owner

## 5. interrupt 现在怎么收口

当前真实链路是：

```text
CLI 活跃回复期间按 Esc
  ↓
runtime.interrupt_session()
  ↓
AgentLoop.interrupt_session()
  ↓
取消当前会话活跃任务
  ↓
_dispatch() 把 CancelledError 收口成 interrupted
```

这里有几条固定语义：

- `Ctrl+C`
  - 退出当前交互进程
- `Esc`
  - 只在本轮执行中生效
- `/stop`
  - 已删除

## 6. cron 为什么仍然挂在 agent 主链路里

这不是职责混乱，而是执行一致性的要求。

cron 到点后最终还是通过 `AgentLoop.process_direct(...)` 跑一轮完整 agent 链路，所以调度必须挂在主循环 owner 上。

当前 cron 触发链路在 [elebot/agent/loop.py](../elebot/agent/loop.py#L542-L589)：

- `CronService` 到点
- `AgentLoop._run_cron_job()`
- `session_key = cron:<job_id>`
- 最终结果再通过 `Bus` 发回当前通道

## 7. 命令和 agent 现在怎么协作

当前 `AgentLoop` 初始化时会注册内置命令，但命令层只负责协议，不再直接碰私有状态。

例如：

- `/new`
  - 调 `AgentLoop.reset_session()`
- `/status`
  - 调 `AgentLoop.build_status_snapshot()`
- `/dream`
  - 调 `AgentLoop.trigger_dream_background()`

而中断已经完全退出 slash 协议：

- 没有 `/stop`
- 也没有 `/interrupt` 或 `/cancel`

## 8. 当前固定边界

现在这些说法都应该视为代码事实：

- `AgentLoop` 是会话执行 owner
- interrupt 是 runtime 控制动作，不是 slash 命令
- `CronService` 是调度领域 owner
- 模型侧调度协议是 `cron_create / cron_list / cron_delete / cron_update`
- `MemoryStore` 是记忆与 Dream 历史 owner
- `ContextBuilder` 是纯上下文装配器
