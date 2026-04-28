# Agent 主循环

这篇文档只讲 `AgentLoop` 当前真实落地的执行链路，不讨论已经删除的旧子代理体系，也不把中断能力写成未来设想。

相关源码：

- [elebot/agent/loop.py](../elebot/agent/loop.py#L169-L1392)
- [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L25-L126)
- [elebot/agent/context.py](../elebot/agent/context.py#L16-L239)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L12-L64)
- [elebot/command/handlers/session.py](../elebot/command/handlers/session.py#L9-L24)
- [elebot/tasks/service.py](../elebot/tasks/service.py#L16-L208)

## 1. `AgentLoop` 现在是什么 owner

`AgentLoop` 仍然是主链路执行 owner。

它负责把下面这些东西串起来：

- `Bus`
- `SessionManager`
- `ContextBuilder`
- `MemoryStore / Consolidator / Dream`
- `TaskService`
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

1. 绑定外部依赖，例如 `Bus`、provider、workspace。
2. 创建执行 owner，例如 `MemoryStore`、`TaskService`、`CommandRouter`。
3. 通过 [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L25-L126) 注册默认工具。
4. 注册当前保留的 slash 命令。

这里要注意两条已经固定下来的边界：

- 工具集合的定义在 `default_tools.py`，不再塞回 `loop.py`
- 命令系统只是协议层，真正的业务 owner 还是 `AgentLoop`、`TaskService`、`MemoryStore`

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

1. 读取或创建 session。
2. 恢复上一次未完整收尾的 runtime checkpoint。
3. 优先检查 slash 命令。
4. 检查任务确认语义。
5. 必要时触发 token 压缩。
6. 记录显式提到的 skill。
7. 通过 `ContextBuilder` 组装系统提示词、历史、运行时元数据和多模态内容。
8. 调 `AgentRunner` 跑模型与工具闭环。
9. 把新形成的合法消息写回 session。

这里最重要的事实是：

- slash 命令是在进模型之前处理的
- session、memory、tasks 都在主链路里，不是外围插件
- `ContextBuilder` 只负责组装上下文，不再自己创建 owner

## 5. interrupt 现在怎么收口

模块五完成后，中断已经不再是 slash 命令。

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
  - 等待输入时不会抢普通键盘行为
- `/stop`
  - 已删除

`AgentLoop.interrupt_session()` 当前会做两件事：

- 先登记 session 级 interrupt 状态
- 再对该 session 的活跃任务发取消

重复按 `Esc` 不会叠加多份请求，而是返回“已经在中断中”。

## 6. 中断后的 session 为什么还能继续

原因是中断最终不是按 error 收尾，而是按 interrupted 收尾。

`_dispatch()` 捕获到 `CancelledError` 后，如果确认这是显式 interrupt，就会：

1. 读取并消费本会话的 interrupt 状态。
2. 调 `_finalize_interrupted_turn()` 把 runtime checkpoint 收口成合法历史。
3. 发布一条用户可见的终态消息：`已中断当前回复。`

这一步不会保留半截自然语言正文，只保留结构化事实：

- 已形成的 assistant tool-call
- 已完成的 tool result
- 未完成 tool 的 interrupted 标记

对应的未完成工具补位文本固定是：

```text
Interrupted: tool execution stopped before completion.
```

它不再伪装成 `Error: ...`。

## 7. 任务和记忆为什么仍然挂在 agent 主链路里

这不是职责混乱，而是执行一致性的要求。

### 7.1 tasks

任务触发后最终还是一条 `InboundMessage`，所以必须交回 `AgentLoop` 按普通对话链路处理。

### 7.2 memory

记忆会参与：

- system prompt 组装
- session checkpoint 恢复
- token 压缩
- Dream 后台整理

所以记忆天然要和 agent 主循环绑定，而不是放到 CLI 或 command 去直接操作。

## 8. 命令和 agent 现在怎么协作

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

## 9. 当前固定边界

现在这些说法都应该视为代码事实：

- `AgentLoop` 是会话执行 owner
- interrupt 是 runtime 控制动作，不是 slash 命令
- `TaskService` 是任务领域 owner
- `MemoryStore` 是记忆与 Dream 历史 owner
- `ContextBuilder` 是纯上下文装配器

现在这些做法都不应该再出现：

- 命令层直接访问 `loop._active_tasks`
- 命令层自己实现中断协议
- CLI 直接拼 `Bus + AgentLoop + provider`
- session 恢复把 interrupted 写成 error
