# Workspace 运行目录

这篇文档只讲运行时 workspace，不讲源码仓库目录。

相关源码：

- [elebot/config/paths.py](../elebot/config/paths.py#L11-L50)
- [elebot/config/schema.py](../elebot/config/schema.py#L28-L50)
- [elebot/cli/commands.py](../elebot/cli/commands.py#L337-L364)
- [elebot/agent/context.py](../elebot/agent/context.py#L19-L32)
- [elebot/agent/memory.py](../elebot/agent/memory.py#L41-L60)
- [elebot/session/manager.py](../elebot/session/manager.py#L100-L104)

## 1. workspace 是什么

workspace 是 EleBot 的运行态根目录。

默认路径在 [elebot/config/paths.py](../elebot/config/paths.py#L11-L13)：

```python
ELEBOT_HOME_DIR = Path.home() / ".elebot"
DEFAULT_WORKSPACE_DIR = ELEBOT_HOME_DIR / "workspace"
```

所以默认就是：

```text
~/.elebot/workspace
```

它不是源码目录，也不是你当前 shell 所在目录。

## 2. workspace 从哪里决定

优先级是：

1. `elebot agent --workspace ...`
2. 配置文件 `agents.defaults.workspace`
3. 默认值 `~/.elebot/workspace`

对应代码：

- [elebot/cli/commands.py](../elebot/cli/commands.py#L337-L364)
- [elebot/config/schema.py](../elebot/config/schema.py#L28-L50)
- [elebot/config/paths.py](../elebot/config/paths.py#L37-L40)

## 3. 当前在哪个目录执行命令，会不会自动切 workspace

不会。

`workspace` 不是按当前工作目录自动推导的。  
你在任何目录执行：

```bash
elebot agent
```

如果没传 `--workspace`，它还是用配置里的 workspace。

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

对应代码入口：

- bootstrap 文件读取在 [elebot/agent/context.py](../elebot/agent/context.py#L19-L32)
- memory 文件路径在 [elebot/agent/memory.py](../elebot/agent/memory.py#L41-L60)
- session 文件路径在 [elebot/session/manager.py](../elebot/session/manager.py#L100-L104)

## 5. 这些文件分别干什么

### 5.1 `AGENTS.md`

工作区级的 agent 规则，会进入 system prompt。

### 5.2 `SOUL.md`

助手风格和行为倾向。

### 5.3 `USER.md`

用户画像和长期稳定偏好。

### 5.4 `TOOLS.md`

工具使用规则和约束。

### 5.5 `memory/MEMORY.md`

项目长期记忆。

### 5.6 `memory/history.jsonl`

会话旧消息的归档摘要流。

### 5.7 `sessions/*.jsonl`

不同 session 的短期原始消息记录。

## 6. `--session` 和 `--workspace` 的区别

这个区别一定要分清。

### 换 `--session`

影响的是：

- 当前对话线程
- 当前短期上下文
- `sessions/*.jsonl`

不影响：

- `USER.md`
- `SOUL.md`
- `MEMORY.md`
- `history.jsonl`

### 换 `--workspace`

影响的是整套运行态目录。

换了 workspace，就等于换了一整套：

- sessions
- memory
- bootstrap 文件

所以可以直接记成：

```text
换 session = 换短期对话线程
换 workspace = 换整套运行世界
```

## 7. 为什么 workspace 会进上下文

`ContextBuilder` 在初始化时直接绑定 workspace：

```python
self.workspace = workspace
self.memory = MemoryStore(workspace)
```

对应代码在 [elebot/agent/context.py](../elebot/agent/context.py#L24-L32)。

随后会从这个 workspace 里读取：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`
- `memory/MEMORY.md`
- `memory/history.jsonl`

所以 workspace 不只是“存文件的地方”，它本身就定义了 agent 当前看到的世界。

## 8. 你可以怎么理解 workspace

最准确的理解方式是：

> workspace = EleBot 当前运行态的根目录快照。

它同时承载：

- 短期会话
- 长期记忆
- 启动规则
- 工具工作范围

## 9. 读完这篇后，下一步看什么

推荐继续看：

- [SESSION](./SESSION.md)
- [MEMORY](./MEMORY.md)
