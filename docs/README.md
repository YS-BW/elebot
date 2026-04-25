# EleBot 文档索引

这套文档不是按源码目录机械展开，而是按“理解主链路”的阅读顺序组织。

建议按下面顺序阅读：

1. [整体架构总览](./architecture-overview.md)
2. [CLI 与运行方式](./cli-runtime.md)
3. [Bus 与消息流转](./bus-and-events.md)
4. [Session 设计](./session-design.md)
5. [工具系统设计](./tools-design.md)
6. [上下文构建](./context-construction.md)
7. [记忆系统设计](./memory-design.md)
8. [Agent 主循环](./agent-loop.md)
9. [Workspace 运行目录](./workspace-design.md)

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
