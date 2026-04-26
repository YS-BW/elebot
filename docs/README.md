# EleBot 文档索引

这套文档不是按源码目录机械展开，而是按“理解主链路”的阅读顺序组织。

建议按下面顺序阅读：

1. [ARCHITECTURE](./ARCHITECTURE.md)
2. [RUNTIME](./RUNTIME.md)
3. [CLI](./CLI.md)
4. [BUS](./BUS.md)
5. [SESSION](./SESSION.md)
6. [TOOLS](./TOOLS.md)
7. [PROVIDERS](./PROVIDERS.md)
8. [CONTEXT](./CONTEXT.md)
9. [MEMORY](./MEMORY.md)
10. [AGENT](./AGENT.md)
11. [TASKS](./TASKS.md)
12. [WORKSPACE](./WORKSPACE.md)
13. [SKILLS](./SKILLS.md)

如果你只想先抓住主链路，可以先看这一条：

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

当前代码里，provider 装配入口已经收口到 `providers/factory.py`，而多入口复用底座是 `runtime`。

如果你现在是在理解 runtime 主链路，建议先看：

1. [RUNTIME](./RUNTIME.md)
2. [CLI](./CLI.md)
3. [AGENT](./AGENT.md)

源码总入口：

- [README.md](../README.md#L1-L38)
- [elebot/cli/commands.py](../elebot/cli/commands.py#L175-L351)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L23-L220)
- [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L82)
- [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L10-L106)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L200)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L154-L1073)
