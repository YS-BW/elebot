# Agent 主循环

这篇文档只讲 `AgentLoop` 这条执行主链路，不讨论已经删除的旧子代理体系。

相关源码：

- [elebot/agent/loop.py](../elebot/agent/loop.py#L161-L1137)
- [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L25-L126)
- [elebot/agent/context.py](../elebot/agent/context.py#L16-L239)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L12-L66)
- [elebot/command/handlers/session.py](../elebot/command/handlers/session.py#L9-L43)
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

## 2. 初始化时会装哪些东西

`AgentLoop.__init__()` 现在主要做四件事：

1. 绑定外部依赖
2. 创建 owner
3. 注册默认工具
4. 注册 slash 命令

这一层已经不再把默认工具注册逻辑直接塞在 `loop.py` 里，而是交给 [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L25-L126)。

这意味着当前边界已经变成：

- `AgentLoop`
  - 负责装配和调度
- `default_tools.py`
  - 负责默认工具集合

## 3. 运行时主循环怎么工作

`run()` 会长期消费 `Bus` 里的入站消息。

简化后的链路是：

```text
Bus.consume_inbound()
  ↓
优先级 slash 命令检查
  ↓
为每个会话创建 dispatch task
  ↓
_dispatch()
```

同时它也会顺带做：

- 启动 `TaskService`
- 定期检查空闲压缩
- 维护会话级活跃任务映射

## 4. 一条普通消息怎么处理

真正的消息处理入口在 `_process_message_result()`。

这一步的顺序大致是：

1. 读取或创建 session
2. 恢复未完成 checkpoint
3. 检查 slash 命令
4. 检查任务确认语义
5. 必要时做 token 压缩
6. 构造 prompt 消息
7. 调 `AgentRunner`
8. 把结果写回 session
9. 通过 `Bus` 或 `process_direct()` 返回结果

这里最重要的结构事实是：

- slash 命令是在进入模型前处理的
- task 确认语义也是主链路的一部分
- session、memory、tasks 都不是外围模块，而是 agent 执行链路的一部分

## 5. 命令和 agent 现在怎么协作

当前 `AgentLoop` 会在初始化时注册内置命令。

命中 slash 时，handler 调用的是 `AgentLoop` 暴露的公开 owner API，例如：

- `cancel_session_tasks()`
- `reset_session()`
- `build_status_snapshot()`
- `trigger_dream_background()`

这和旧的“命令直接碰私有状态”已经不同。

例如 `/stop` 现在的路径是：

```text
/stop
  ↓
command/handlers/session.py
  ↓
AgentLoop.cancel_session_tasks()
```

而不是命令层自己去动 `_active_tasks`。

## 6. 任务和记忆为什么也挂在这里

原因不是“什么都往 agent 里塞”，而是这两类能力都要跟会话执行链路保持一致。

### 6.1 tasks

任务触发后最终还是一条 `InboundMessage`，所以要交回 `AgentLoop` 统一处理。

### 6.2 memory

记忆要参与：

- prompt 组装
- 会话归档
- token 压缩
- Dream 后台整理

所以它天然和 agent 主循环绑定。

## 7. 当前 `/stop` 的真实能力

当前 `/stop` 已经走公开 API，但能力边界还很清楚：

- 它能取消当前会话下的活跃任务
- 它还不是完整的 provider 级 interrupt

也就是说：

```text
当前 /stop = 会话级任务取消
不是完整中断体系
```

这部分留给后续“真正的中断能力”模块继续做。
