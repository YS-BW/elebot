# EleBot 文档索引

这套文档按“先理解主链路，再看各个 owner”的顺序组织，不按源码目录机械展开。

建议按下面顺序阅读：

1. [ARCHITECTURE](./ARCHITECTURE.md)
2. [RUNTIME](./RUNTIME.md)
3. [CLI](./CLI.md)
4. [COMMAND](./COMMAND.md)
5. [AGENT](./AGENT.md)
6. [CONTEXT](./CONTEXT.md)
7. [SESSION](./SESSION.md)
8. [MEMORY](./MEMORY.md)
9. [CRON](./CRON.md)
10. [PROVIDERS](./PROVIDERS.md)
11. [TOOLS](./TOOLS.md)
12. [BUS](./BUS.md)
13. [WORKSPACE](./WORKSPACE.md)
14. [SKILLS](./SKILLS.md)

如果你只想先抓住当前真实主链路，可以先记这一条：

```text
用户输入
  ↓
CLI
  ↓
Runtime
  ↓
Bus
  ↓
AgentLoop
  ↓
ContextBuilder + Session + Memory
  ↓
Provider / Tools
  ↓
OutboundMessage
  ↓
CLI 渲染
```

当前代码里的几个关键事实：

- `runtime` 是多入口复用底座，不再经过 `facade`
- CLI 只保留 `onboard`、`agent`、`status` 三个根命令
- slash 命令由 `command` 模块负责协议和 handler 组织，但底层业务 owner 仍在 `AgentLoop`、`CronService`、`MemoryStore`
- provider 解析入口在 `providers/resolution.py`
- provider 实例化入口在 `providers/factory.py`
- 模型建议与推荐上下文窗口入口在 `providers/model_catalog.py`
- `history.jsonl` 是当前唯一历史文件，`HISTORY.md` 已不属于当前实现
- 旧 `tasks` 模块已经移除，当前唯一调度 owner 是 `CronService`

源码总入口：

- [README.md](../README.md#L1-L38)
- [elebot/cli/app.py](../elebot/cli/app.py#L1-L67)
- [elebot/cli/commands/__init__.py](../elebot/cli/commands/__init__.py#L1-L23)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L25-L340)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L222-L920)
- [elebot/providers/resolution.py](../elebot/providers/resolution.py#L11-L150)
- [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L72)
- [elebot/providers/model_catalog.py](../elebot/providers/model_catalog.py#L10-L257)
