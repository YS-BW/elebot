# EleBot 记忆系统设计

这篇文档只讲当前真实实现下的记忆系统，不讲未来设计，不讲兼容层。

相关源码：

- [elebot/session/manager.py](../elebot/session/manager.py#L14-L209)
- [elebot/agent/memory.py](../elebot/agent/memory.py#L31-L866)
- [elebot/agent/autocompact.py](../elebot/agent/autocompact.py#L15-L148)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L101-L144)
- [elebot/agent/context.py](../elebot/agent/context.py#L34-L66)

## 1. 先记住三层结构

EleBot 的记忆不是一个文件，而是三层结构：

```text
session 原始消息
  ↓
history 归档摘要
  ↓
长期记忆文件
```

完整流转是：

```text
用户对话
  ↓
sessions/*.jsonl
  ↓
Consolidator.archive(...)
  ↓
memory/history.jsonl
  ↓
Dream.run()
  ↓
USER.md / SOUL.md / memory/MEMORY.md
```

## 2. 相关文件有哪些

默认 workspace 里，相关文件通常是：

```text
workspace/
├── SOUL.md
├── USER.md
├── memory/
│   ├── MEMORY.md
│   ├── history.jsonl
│   ├── .cursor
│   └── .dream_cursor
└── sessions/
    └── *.jsonl
```

每个文件的职责不同：

- `sessions/*.jsonl`：原始会话消息
- `memory/history.jsonl`：归档摘要流
- `memory/.cursor`：history 当前生产游标
- `memory/.dream_cursor`：Dream 当前消费游标
- `USER.md`：用户长期画像
- `SOUL.md`：助手长期风格
- `memory/MEMORY.md`：项目长期背景

## 3. 第一层：session 原始消息

实现见 [elebot/session/manager.py](../elebot/session/manager.py#L14-L209)。

这层保存的是：

- 用户消息
- 助手消息
- tool call
- tool result
- reasoning 内容

所以它是原始执行流水层，不是最终长期记忆。

## 4. 第二层：`history.jsonl`

真正的追加写入逻辑在 [elebot/agent/memory.py](../elebot/agent/memory.py#L288-L303)：

```python
def append_history(self, entry: str) -> int:
    cursor = self._next_cursor()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    record = {"cursor": cursor, "timestamp": ts, "content": strip_think(entry.rstrip()) or entry.rstrip()}
    with open(self.history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    self._cursor_file.write_text(str(cursor), encoding="utf-8")
    return cursor
```

每条记录固定有 3 个字段：

- `cursor`
- `timestamp`
- `content`

一个典型条目长这样：

```json
{"cursor":1,"timestamp":"2026-04-25 10:12","content":"用户最近在询问 workspace、session 和 memory 的区别。"}
```

## 5. `history.jsonl` 的触发时机

只有在旧消息被归档时，才会写进 `history.jsonl`。

主要有 3 种触发场景。

### 5.1 `/new`

见 [elebot/command/builtin.py](../elebot/command/builtin.py#L101-L115)：

```python
snapshot = session.messages[session.last_consolidated:]
session.clear()
if snapshot:
    loop._schedule_background(loop.consolidator.archive(snapshot))
```

### 5.2 token 压缩

见 [elebot/agent/memory.py](../elebot/agent/memory.py#L608-L690)。

当 session prompt 过长时，会取旧前缀归档到 `history.jsonl`。

### 5.3 空闲压缩

见 [elebot/agent/autocompact.py](../elebot/agent/autocompact.py#L91-L123)。

当 session 闲置超过 TTL 时，会把旧前缀归档到 `history.jsonl`。

## 6. `.cursor` 是什么

它是 `history.jsonl` 的生产游标。

逻辑在 [elebot/agent/memory.py](../elebot/agent/memory.py#L305-L316)：

```python
if self._cursor_file.exists():
    return int(self._cursor_file.read_text(...).strip()) + 1
```

每往 `history.jsonl` 追加一条记录，就会同步更新 `.cursor`。

所以：

- `.cursor = 7`
  表示目前 history 已经写到了第 7 条

## 7. `.dream_cursor` 是什么

它是 Dream 的消费游标。

读取在 [elebot/agent/memory.py](../elebot/agent/memory.py#L390-L404)：

```python
def get_last_dream_cursor(self) -> int:
    if self._dream_cursor_file.exists():
        return int(self._dream_cursor_file.read_text(...).strip())
    return 0
```

写入在 [elebot/agent/memory.py](../elebot/agent/memory.py#L406-L415)。

所以：

- `.cursor`：history 已生产到哪里
- `.dream_cursor`：Dream 已消费到哪里

两者相同，只说明“Dream 已经追平当前 history”，不代表它们是同一个东西。

## 8. Consolidator 和 Dream 的边界

看 [elebot/agent/memory.py](../elebot/agent/memory.py#L474-L478) 与 [elebot/agent/memory.py](../elebot/agent/memory.py#L710-L715)。

可以直接记成：

### Consolidator

- 目标：让当前会话继续跑下去
- 输入：旧 session 消息
- 输出：`history.jsonl`

### Dream

- 目标：沉淀长期记忆文件
- 输入：`history.jsonl` 未消费条目
- 输出：`USER.md`、`SOUL.md`、`MEMORY.md`

## 9. Dream 是怎么跑的

主入口在 [elebot/agent/memory.py](../elebot/agent/memory.py#L742-L866)。

核心步骤：

```python
last_cursor = self.store.get_last_dream_cursor()
entries = self.store.read_unprocessed_history(since_cursor=last_cursor)
batch = entries[: self.max_batch_size]
```

先读未处理历史，再分批处理。

然后分两阶段：

### 9.1 第一阶段：分析

```python
phase1_response = await self.provider.chat_with_retry(...)
analysis = phase1_response.content or ""
```

### 9.2 第二阶段：增量修改记忆文件

```python
result = await self._runner.run(AgentRunSpec(...))
```

这个阶段会通过文件工具去改：

- `SOUL.md`
- `USER.md`
- `memory/MEMORY.md`

最后推进 `.dream_cursor`：

```python
new_cursor = batch[-1]["cursor"]
self.store.set_last_dream_cursor(new_cursor)
```

## 10. 哪些记忆文件会进上下文

这个问题很关键。

### 会直接进上下文的

看 [elebot/agent/context.py](../elebot/agent/context.py#L34-L66)：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`
- `memory/MEMORY.md`
- `history.jsonl` 中尚未被 Dream 处理的条目

### 不会直接整文件进上下文的

- `sessions/*.jsonl` 不会整文件直塞，只会先走 `session.get_history()`
- `.cursor` 不会进 prompt
- `.dream_cursor` 不会进 prompt

所以要这样理解：

```text
cursor 文件负责状态推进
memory / soul / user 负责长期注入
history.jsonl 只把未处理部分作为最近历史注入
session 只把当前短期合法历史注入
```

## 11. 自然聊天为什么有时不会立刻进入 `history.jsonl`

因为自然聊天默认先进入的是：

```text
sessions/*.jsonl
```

只有满足归档条件之一，才会进 `history.jsonl`：

- `/new`
- token 超预算
- 空闲压缩

所以：

> `history.jsonl` 是归档层，不是实时聊天流水层。

## 12. 空闲压缩怎么影响记忆层

实现见 [elebot/agent/autocompact.py](../elebot/agent/autocompact.py#L75-L148)。

流程可以直接记成：

```text
session 闲置超过 TTL
  ↓
拆出未归档旧前缀
  ↓
archive(...) 写入 history.jsonl
  ↓
只保留最近合法尾部
  ↓
把摘要暂存到 _last_summary
  ↓
下一轮回来时作为恢复摘要进入上下文
```

## 13. 记忆层现在的真实设计结论

最重要的结论只有三条：

1. 现在是多 session，不是单 session
2. session 层隔离，memory 层共享
3. 长期记忆不是直接从聊天记录生成，而是经过 `Consolidator -> history -> Dream` 两段式沉淀

## 14. 读完这篇后，下一步看什么

推荐继续看：

- [CONTEXT](./CONTEXT.md)
- [AGENT](./AGENT.md)
