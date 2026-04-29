# Command 设计

这篇文档只讲 slash 命令系统当前怎么工作，不讨论未来 Web UI 按钮、右键菜单或其他交互入口。

相关源码：

- [elebot/command/__init__.py](../elebot/command/__init__.py#L1-L6)
- [elebot/command/router.py](../elebot/command/router.py#L15-L82)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L11-L58)
- [elebot/command/handlers/session.py](../elebot/command/handlers/session.py#L9-L24)
- [elebot/command/handlers/runtime.py](../elebot/command/handlers/runtime.py#L15-L83)
- [elebot/command/handlers/dream.py](../elebot/command/handlers/dream.py#L10-L200)
- [elebot/command/handlers/skills.py](../elebot/command/handlers/skills.py#L10-L97)

## 1. `command` 现在负责什么

`command` 当前只负责 slash 命令协议层。

它的职责固定是：

- 定义命令路由规则
- 组织内置命令注册
- 提供各命令的 handler

它不再负责：

- 直接管理 cron 存储
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
    └── skills.py
```

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

### 4.4 skills 类命令

- `/skill list`
  - 调 `SkillRegistry.list_status()`
- `/skill install <source>`
  - 调 `SkillManager.install()`
- `/skill uninstall <name>`
  - 调 `SkillManager.uninstall()`

## 5. 当前已经固定不做什么

当前命令协议已经明确不再提供：

- `/task`
- `/cron`
- `/stop`
- `/interrupt`
- `/cancel`

中断现在是 runtime 控制动作，不是命令协议。

调度现在通过模型调用 `cron` 工具完成，而不是通过 slash 命令管理。

## 6. 当前固定边界

现在这些做法都不应该再出现：

- handler 直接访问 `loop._active_tasks`
- handler 穿透到 `consolidator.store.git`
- handler 自己实现 skill 安装落盘逻辑

当前固定原则是：

```text
command 只做协议和 handler
handler 只调公开 owner API
```
