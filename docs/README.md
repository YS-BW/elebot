# EleBot 文档索引

这套文档不是按源码目录机械展开，而是按“理解主链路”的阅读顺序组织。

建议按下面顺序阅读：

1. [ARCHITECTURE](./ARCHITECTURE.md)
2. [CLI](./CLI.md)
3. [BUS](./BUS.md)
4. [SESSION](./SESSION.md)
5. [TOOLS](./TOOLS.md)
6. [PROVIDERS](./PROVIDERS.md)
7. [CONTEXT](./CONTEXT.md)
8. [MEMORY](./MEMORY.md)
9. [AGENT](./AGENT.md)
10. [WORKSPACE](./WORKSPACE.md)
11. [SKILLS](./SKILLS.md)

如果你只想先抓住主链路，可以先看这一条：

```text
用户输入
  ↓
CLI
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

源码总入口：

- [README.md](../README.md#L1-L38)
- [elebot/cli/commands.py](../elebot/cli/commands.py#L313-L414)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L180)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L430-L979)
