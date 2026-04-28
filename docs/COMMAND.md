# Command 设计

这篇文档只讲 slash 命令系统当前怎么工作，不讨论未来 Web UI 按钮、右键菜单或其他交互入口。

相关源码：

- [elebot/command/__init__.py](../elebot/command/__init__.py#L1-L6)
- [elebot/command/router.py](../elebot/command/router.py#L15-L82)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L12-L64)
- [elebot/command/handlers/session.py](../elebot/command/handlers/session.py#L9-L24)
- [elebot/command/handlers/runtime.py](../elebot/command/handlers/runtime.py#L15-L83)
- [elebot/command/handlers/dream.py](../elebot/command/handlers/dream.py#L10-L200)
- [elebot/command/handlers/tasks.py](../elebot/command/handlers/tasks.py#L9-L57)
- [elebot/command/handlers/skills.py](../elebot/command/handlers/skills.py#L10-L97)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L902-L1042)

## 1. `command` 现在负责什么

`command` 当前只负责 slash 命令协议层。

它的职责固定是：

- 定义命令路由规则
- 组织内置命令注册
- 提供各命令的 handler

它不再负责：

- 直接管理任务存储
- 直接管理 Dream Git 历史
- 直接操作 `loop._active_tasks`
- 解释 interrupt 语义

## 2. 当前文件结构

现在的结构是：

```text
command/
├── __init__.py
├── router.py
├── builtin.py
└── handlers/
    ├── session.py
    ├── runtime.py
    ├── dream.py
    ├── tasks.py
    └── skills.py
```

分工是：

- `router.py`
  - 路由规则和 `CommandContext`
- `builtin.py`
  - `SLASH_COMMAND_SPECS`
  - `build_help_text()`
  - `register_builtin_commands()`
- `handlers/*.py`
  - 具体命令逻辑

## 3. 命令是怎么分发的

当前 `CommandRouter` 的分发顺序是：

1. priority
2. exact
3. prefix
4. interceptors

这意味着像 `/status`、`/restart` 这种命令，可以在进入模型之前直接被主链路拦住处理。

`/skill` 现在只注册了前缀命令，没有裸命令注册。  
所以合法形式是：

- `/skill list`
- `/skill install <source>`
- `/skill uninstall <name>`

## 4. handler 现在分别委托给谁

### 4.1 session 类命令

- `/new`
  - 调 `ctx.loop.reset_session(ctx.key)`

### 4.2 runtime 类命令

- `/status`
  - 调 `ctx.loop.build_status_snapshot(ctx.key)`
- `/restart`
  - 负责进程原地重启
- `/help`
  - 复用 `build_help_text()`

### 4.3 dream 类命令

- `/dream`
  - 调 `ctx.loop.trigger_dream_background(...)`
- `/dream-log`
  - 调 `ctx.loop.memory_store.show_dream_version(...)`
- `/dream-restore`
  - 调 `ctx.loop.memory_store.restore_dream_version(...)`

### 4.4 tasks 类命令

- `/task`
  - 调 `ctx.loop.task_service.list_by_session()`
  - 或 `list_all()`
  - 或 `remove()`

### 4.5 skills 类命令

- `/skill list`
  - 调 `SkillRegistry.list_status()`
- `/skill install <source>`
  - 调 `SkillManager.install()`
- `/skill uninstall <name>`
  - 调 `SkillManager.uninstall()`

这里的边界是固定的：

- `SkillRegistry`
  - 只读扫描与状态展示
- `SkillManager`
  - 安装与卸载
- `skills.py` handler
  - 参数解析与文案格式化

## 5. 为什么 `command` 还留在单独模块里

原因很简单：

- slash 命令本身是一种协议
- 协议层和业务 owner 不是一回事

如果以后接 Web UI，这一层仍然有价值：

- CLI 继续复用 slash 协议
- Web UI 可以不走 slash 文本，直接调 runtime 或 owner API

也就是说：

```text
command 保留在 command 模块
  = 保留一套文本命令协议

不是
  = 把业务锁死在 CLI 里
```

## 6. interrupt 为什么不再属于 command

现在已经固定下来的事实是：

- interrupt 不再属于 slash 命令
- `/stop` 已移除
- CLI 的 `Esc` 会直接走 `runtime.interrupt_session()`

因此 `command` 当前不会再提供：

- `/stop`
- `/interrupt`
- `/cancel`

中断现在是 runtime 控制动作，不是命令协议。

## 7. 当前固定边界

这一轮之后，下面这些做法都不应该再出现：

- handler 直接访问 `loop._active_tasks`
- handler 直接 new `TaskStore()`
- handler 穿透到 `consolidator.store.git`
- handler 自己实现 skill 安装落盘逻辑

当前固定原则是：

```text
command 只做协议和 handler
handler 只调公开 owner API
```
