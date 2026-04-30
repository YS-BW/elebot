# EleBot 文档索引

这套文档按“先理解主链路，再看各个 owner”的顺序组织，不按源码目录机械展开。

建议按下面顺序阅读：

1. [ARCHITECTURE](./ARCHITECTURE.md)
2. [RUNTIME](./RUNTIME.md)
3. [CLI](./CLI.md)
4. [STDIO](./STDIO.md)
5. [CHANNELS](./CHANNELS.md)
6. [WEBSOCKET](./WEBSOCKET.md)
7. [WEIXIN](./WEIXIN.md)
8. [COMMAND](./COMMAND.md)
9. [AGENT](./AGENT.md)
10. [CONTEXT](./CONTEXT.md)
11. [SESSION](./SESSION.md)
12. [MEMORY](./MEMORY.md)
13. [CRON](./CRON.md)
14. [PROVIDERS](./PROVIDERS.md)
15. [TOOLS](./TOOLS.md)
16. [BUS](./BUS.md)
17. [WORKSPACE](./WORKSPACE.md)
18. [SKILLS](./SKILLS.md)

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
- CLI 当前根命令包括 `onboard`、`agent`、`channels`、`serve`、`status`
- slash 命令由 `command` 模块负责协议和 handler 组织，但底层业务 owner 仍在 `AgentLoop`、`CronService`、`MemoryStore`
- provider 解析入口在 `providers/resolution.py`
- provider 实例化入口在 `providers/factory.py`
- 模型建议与推荐上下文窗口入口在 `providers/model_catalog.py`
- `history.jsonl` 是当前唯一历史文件，`HISTORY.md` 已不属于当前实现
- 旧 `tasks` 模块已经移除，当前唯一调度 owner 是 `CronService`
- `serve stdio` 是第二入口最小验证；`websocket` 和 `weixin` 是当前两种内置 channel

源码总入口：

- [README.md](../README.md#L1-L38)
- [elebot/cli/app.py](../elebot/cli/app.py#L1-L67)
- [elebot/cli/commands/__init__.py](../elebot/cli/commands/__init__.py#L1-L25)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L31-L350)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L222-L1458)
- [elebot/providers/resolution.py](../elebot/providers/resolution.py#L11-L150)
- [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L72)
- [elebot/providers/model_catalog.py](../elebot/providers/model_catalog.py#L10-L257)
