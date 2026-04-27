# Memory 设计

这篇文档只讲当前已经落地的记忆系统，不讨论未来外部数据库，也不讨论已经删除的 `HISTORY.md` 兼容层。

相关源码：

- [elebot/agent/memory/__init__.py](../elebot/agent/memory/__init__.py#L1-L7)
- [elebot/agent/memory/store.py](../elebot/agent/memory/store.py#L18-L320)
- [elebot/agent/memory/consolidator.py](../elebot/agent/memory/consolidator.py#L20-L260)
- [elebot/agent/memory/dream.py](../elebot/agent/memory/dream.py#L16-L202)
- [elebot/agent/context.py](../elebot/agent/context.py#L41-L81)
- [elebot/command/handlers/dream.py](../elebot/command/handlers/dream.py#L118-L200)

## 1. `agent/memory` 现在是 package

当前结构是：

```text
elebot/agent/memory/
├── __init__.py
├── store.py
├── consolidator.py
└── dream.py
```

这不是为了加层，而是把 owner 分清楚：

- `MemoryStore`
  - 文件事实和 Dream 历史
- `Consolidator`
  - token 压缩
- `Dream`
  - 长期记忆整理

## 2. `MemoryStore` 现在维护哪些文件

[elebot/agent/memory/store.py](../elebot/agent/memory/store.py#L62-L90) 里已经固定了当前记忆目录结构：

- `memory/MEMORY.md`
- `memory/history.jsonl`
- `memory/.cursor`
- `memory/.dream_cursor`
- `SOUL.md`
- `USER.md`

其中 `history.jsonl` 是当前唯一历史文件。

## 3. 旧 `HISTORY.md` 现在怎么处理

旧版兼容逻辑已经删除，不迁移也不保留。

[elebot/agent/memory/store.py](../elebot/agent/memory/store.py#L119-L131) 的启动清理会直接删除：

- `memory/HISTORY.md`
- `memory/HISTORY.md.bak`
- `memory/HISTORY.md.bak.*`

当前固定行为是：

```text
发现旧文件
  ↓
直接删除
```

不会迁移、不会提示、不会回退读取。

## 4. `Consolidator` 现在做什么

[elebot/agent/memory/consolidator.py](../elebot/agent/memory/consolidator.py#L20-L260) 负责的是轻量压缩，而不是长期记忆编辑。

它的链路可以记成：

```text
session 历史过长
  ↓
estimate_session_prompt_tokens()
  ↓
archive()
  ↓
MemoryStore.append_history()
```

所以它写进历史的目标文件已经固定是 `history.jsonl`。

## 5. Dream 历史现在由谁对外暴露

Dream 历史 owner 已经固定是 `MemoryStore`。

当前公开能力包括：

- `list_dream_versions()`
- `show_dream_version()`
- `restore_dream_version()`

slash 命令只是复用它，见 [elebot/command/handlers/dream.py](../elebot/command/handlers/dream.py#L118-L200)。

命令层现在只负责：

- 参数解析
- 展示文案

不再直接操作底层 Git 细节。

## 6. 记忆怎么进入 prompt

[elebot/agent/context.py](../elebot/agent/context.py#L41-L81) 每轮都会从 `MemoryStore` 读取：

- 长期记忆 `MEMORY.md`
- 最近未被 Dream 吸收的 `history.jsonl`

也就是说，memory 不只是后台文件，它本身就是 prompt 的输入事实。

## 7. 当前固定边界

这轮之后，记忆层可以直接记成：

```text
MemoryStore = 文件事实 owner
Consolidator = token 压缩 owner
Dream = 长期记忆整理 owner
history.jsonl = 唯一历史来源
```
