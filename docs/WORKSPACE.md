# Workspace 运行目录

这篇文档只讲运行时 workspace，不讲源码仓库目录。

相关源码：

- [elebot/config/paths.py](../elebot/config/paths.py#L11-L40)
- [elebot/config/schema.py](../elebot/config/schema.py#L147-L159)
- [elebot/cli/commands/onboard.py](../elebot/cli/commands/onboard.py#L52-L164)
- [elebot/utils/workspace.py](../elebot/utils/workspace.py#L10-L61)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L222-L230)
- [elebot/agent/context.py](../elebot/agent/context.py#L24-L39)
- [elebot/agent/memory/store.py](../elebot/agent/memory/store.py#L67-L90)
- [elebot/session/manager.py](../elebot/session/manager.py#L98-L110)

## 1. workspace 是什么

workspace 是 EleBot 的运行态根目录。

默认路径是：

```text
~/.elebot/workspace
```

它不是源码仓库目录，也不是当前 shell 所在目录。

## 2. workspace 从哪里决定

当前优先级是：

1. `elebot agent --workspace ...`
2. 配置文件里的 `agents.defaults.workspace`
3. 默认值 `~/.elebot/workspace`

展开后的路径由 [elebot/config/schema.py](../elebot/config/schema.py#L154-L157) 的 `workspace_path` 提供。

## 3. 初始化时会生成哪些文件

`onboard` 和 `agent` 启动前都会复用 [elebot/utils/workspace.py](../elebot/utils/workspace.py#L10-L61) 的 `sync_workspace_templates()`。

当前默认会补齐：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`
- `memory/MEMORY.md`
- `memory/history.jsonl`

也就是说，`history.jsonl` 从初始化开始就是当前主链路的一部分，不再存在 `HISTORY.md` 这条旧路径。

## 4. workspace 里通常会有什么

当前主链路下，常见结构是：

```text
~/.elebot/workspace/
├── AGENTS.md
├── SOUL.md
├── USER.md
├── TOOLS.md
├── memory/
│   ├── MEMORY.md
│   ├── history.jsonl
│   ├── .cursor
│   └── .dream_cursor
└── sessions/
    └── *.jsonl
```

这些文件会直接进入主链路：

- bootstrap 文件
  - 进入 `ContextBuilder`
- `memory/`
  - 由 `MemoryStore` 维护
- `sessions/`
  - 由 `SessionManager` 维护

## 5. `ContextBuilder` 和 workspace 现在怎么连起来

当前是 `AgentLoop` 先基于 workspace 创建 owner，再把它们注入给 `ContextBuilder`。

对应代码在：

- [elebot/agent/loop.py](../elebot/agent/loop.py#L222-L230)
- [elebot/agent/context.py](../elebot/agent/context.py#L24-L39)

这和旧的“`ContextBuilder` 内部自己创建 `MemoryStore`”已经不同。

现在固定链路是：

```text
workspace
  ↓
AgentLoop 创建 MemoryStore / SessionManager
  ↓
ContextBuilder 只接收注入
```

## 6. `--session` 和 `--workspace` 的区别

换 `--session` 影响的是：

- 当前对话线程
- `sessions/*.jsonl`
- 当前短期上下文

不影响：

- `SOUL.md`
- `USER.md`
- `MEMORY.md`
- `history.jsonl`

换 `--workspace` 则等于换整套运行世界：

- bootstrap 文件
- memory
- sessions

所以可以直接记成：

```text
换 session = 换短期对话线程
换 workspace = 换整套运行世界
```
