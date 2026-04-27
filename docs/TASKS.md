# Tasks 设计

这篇文档只讲 EleBot 当前已经落地的定时任务实现，不讨论未来系统级 `cron`、`launchd` 或 daemon 方案。

相关源码：

- [elebot/tasks/store.py](../elebot/tasks/store.py#L13-L146)
- [elebot/tasks/service.py](../elebot/tasks/service.py#L16-L208)
- [elebot/tasks/trigger.py](../elebot/tasks/trigger.py#L1-L42)
- [elebot/agent/tools/task_tools.py](../elebot/agent/tools/task_tools.py#L18-L420)
- [elebot/command/handlers/tasks.py](../elebot/command/handlers/tasks.py#L9-L57)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L241-L245)

## 1. 当前任务系统的真实事实

先把事实说清楚：

- 任务文件在 `~/.elebot/tasks/tasks.json`
- 调度器不是系统服务，而是 `elebot agent` 进程内后台轮询
- 只有 `AgentLoop.run()` 在跑时，任务才会触发
- 任务触发后不会直接调用 runner，而是先转成一条 `InboundMessage`

可以直接记成：

```text
tasks.json
  ↓
TaskService.tick()
  ↓
build_task_inbound_message()
  ↓
Bus
  ↓
AgentLoop
```

## 2. 现在的 owner 边界

### 2.1 `TaskStore`

`TaskStore` 现在只负责文件事实：

- 读 `tasks.json`
- 写 `tasks.json`
- 简单查询和状态更新

它不是命令 owner，也不是工具 owner。

### 2.2 `TaskService`

`TaskService` 现在是任务领域统一对外入口。

它负责：

- 后台轮询
- 到期判断后的触发
- 列表查询
- `get / upsert / remove`
- 标记 `running / finished / deferred`

也就是说，任务领域的共享业务都应该放在 `TaskService`，而不是散在 CLI、command、tool 里。

### 2.3 `task_tools`

任务工具现在直接依赖 `TaskService`。

这层负责的是“给模型用的任务接口”，例如：

- `propose_task`
- `create_task`
- `list_tasks`
- `update_task`
- `remove_task`

### 2.4 `command`

`/task` 命令现在也只调用 `TaskService`。

命令层只做：

- 参数解析
- 文案格式化

不再直接 import `TaskStore`。

## 3. 自然语言创建任务现在怎么工作

当前任务创建仍然是“两步走”，不是模型直接落盘：

```text
用户表达提醒意图
  ↓
模型调用 propose_task
  ↓
session.metadata 保存待确认 proposal
  ↓
用户明确确认
  ↓
create_task
  ↓
TaskService.upsert()
```

这里最重要的约束是：

- 用户未确认前，不得直接创建任务
- 真正写入任务文件的是 `TaskService.upsert()`

## 4. `/task` 命令现在做什么

`/task` 相关逻辑已经从“大而全的 builtin 文件”里拆开，当前 handler 在 [elebot/command/handlers/tasks.py](../elebot/command/handlers/tasks.py#L9-L57)。

它支持三类动作：

- `/task`
  - 只看当前会话任务
- `/task list`
  - 查看全部任务
- `/task remove <task_id>`
  - 删除指定任务

这些动作背后统一调用的是：

- `task_service.list_by_session()`
- `task_service.list_all()`
- `task_service.remove()`

## 5. 任务和 agent 主链路怎么接起来

`AgentLoop` 初始化时会创建 `TaskService`，并在 `run()` 启动时顺带启动任务轮询。

这意味着：

- tasks 是主链路的一部分
- 但它不是一个独立后端进程

当前边界非常明确：

```text
TaskService = 当前任务领域 owner
TaskStore   = 纯持久化仓库
```

后续如果做系统级后台运行，也应该保留这层边界，而不是让命令或工具重新直接写 `tasks.json`。
