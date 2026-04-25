# Session 设计

这篇文档只讲当前真实实现下的 session 层，不讲未来多用户系统，不讲外部数据库方案。

相关源码：

- [elebot/session/manager.py](../elebot/session/manager.py#L14-L209)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L497-L979)
- [elebot/agent/autocompact.py](../elebot/agent/autocompact.py#L15-L148)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L101-L144)

## 1. 先记一句话

`session` 的职责是：

> 保存单条会话线程的短期消息状态。

它不是：

- 全局长期记忆
- 工作区目录
- 用户账号系统

## 2. Session 对象长什么样

定义在 [elebot/session/manager.py](../elebot/session/manager.py#L14-L24)：

```python
@dataclass
class Session:
    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0
```

关键字段解释：

- `key`：会话键，例如 `cli:direct`
- `messages`：这条会话当前保存的原始消息序列
- `metadata`：运行中附加状态，例如检查点
- `last_consolidated`：已经被归档过的边界

## 3. 一个 session 文件如何落盘

文件目录固定在：

```text
<workspace>/sessions/
```

路径逻辑在 [elebot/session/manager.py](../elebot/session/manager.py#L106-L109)：

```python
safe_key = safe_filename(key.replace(":", "_"))
return self.sessions_dir / f"{safe_key}.jsonl"
```

例如：

- `cli:direct` -> `sessions/cli_direct.jsonl`
- `cli:alt-test` -> `sessions/cli_alt-test.jsonl`

保存逻辑在 [elebot/session/manager.py](../elebot/session/manager.py#L164-L181)：

```python
metadata_line = {
    "_type": "metadata",
    "key": session.key,
    "created_at": session.created_at.isoformat(),
    "updated_at": session.updated_at.isoformat(),
    "metadata": session.metadata,
    "last_consolidated": session.last_consolidated
}
f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
for msg in session.messages:
    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
```

所以文件格式是：

```jsonl
{"_type":"metadata","key":"cli:direct","created_at":"...","updated_at":"...","metadata":{},"last_consolidated":0}
{"role":"user","content":"你好","timestamp":"..."}
{"role":"assistant","content":"你好，我在。","timestamp":"..."}
```

第一行是 session 元数据，后面每行才是消息。

## 4. `last_consolidated` 到底是什么意思

它是 session 和归档层之间的边界线。

例如：

```text
messages 一共有 10 条
last_consolidated = 6
```

那就表示：

```text
messages[0:6]   已经归档过
messages[6:10]  仍属于当前短期上下文
```

所以 session 并不是“全量历史都重新送给模型”，而是只取未归档部分。

## 5. 模型看到的 session 历史不是原样全量

看 [elebot/session/manager.py](../elebot/session/manager.py#L36-L62)：

```python
unconsolidated = self.messages[self.last_consolidated:]
```

先只拿未归档部分。

然后还会做两层清洗。

### 5.1 尽量从一个用户消息开始

```python
for i, message in enumerate(sliced):
    if message.get("role") == "user":
        sliced = sliced[i:]
        break
```

### 5.2 剥掉不合法的孤儿工具结果

```python
start = find_legal_message_start(sliced)
if start:
    sliced = sliced[start:]
```

所以 session history 是“合法短期上下文视图”，不是文件原样直通。

## 6. Agent 主链路里 session 在哪里参与

主入口在 [elebot/agent/loop.py](../elebot/agent/loop.py#L635-L712)：

```python
key = session_key or msg.session_key
session = self.sessions.get_or_create(key)

if self._restore_runtime_checkpoint(session):
    self.sessions.save(session)

session, pending = self.auto_compact.prepare_session(session, key)
await self.consolidator.maybe_consolidate_by_tokens(session)

history = session.get_history(max_messages=0)

initial_messages = self.context.build_messages(
    history=history,
    current_message=msg.content,
    session_summary=pending,
    ...
)
```

顺序可以直接记成：

1. 读取 session
2. 恢复未完成回合
3. 处理空闲压缩回来的摘要
4. 必要时做 token 压缩
5. 取短期 history
6. 拼进当前 prompt

## 7. 一轮结束后，session 怎么写回去

在 [elebot/agent/loop.py](../elebot/agent/loop.py#L709-L712)：

```python
self._save_turn(session, all_msgs, 1 + len(history))
self._clear_runtime_checkpoint(session)
self.sessions.save(session)
```

真正写入细节在 [elebot/agent/loop.py](../elebot/agent/loop.py#L804-L846)。

这说明 session 保存的不是只有“最终聊天文本”，还可能包含：

- assistant tool call
- tool result
- reasoning_content
- 经清洗后的多模态内容

所以 session 更接近“agent 执行流水”，不是简化聊天记录。

## 8. `metadata` 是干什么的

当前最重要的用途是运行中检查点。

相关代码：

- [elebot/agent/loop.py](../elebot/agent/loop.py#L848-L851)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L885-L936)

如果一轮执行中断，系统会先把中间状态写进 `session.metadata`。  
下一轮进来时，再把这些未完成状态恢复成合法历史。

所以：

- `messages`：已持久化的消息流水
- `metadata`：运行期附加状态

## 9. `/new` 对 session 做了什么

看 [elebot/command/builtin.py](../elebot/command/builtin.py#L101-L115)：

```python
snapshot = session.messages[session.last_consolidated:]
session.clear()
loop.sessions.save(session)
loop.sessions.invalidate(session.key)
if snapshot:
    loop._schedule_background(loop.consolidator.archive(snapshot))
```

含义是：

- 取出未归档的当前会话消息
- 立刻清空 session
- 后台把这些消息归档到 `history.jsonl`

所以 `/new` 不是简单“删聊天记录”，而是：

- 清空短期会话
- 把旧内容送去归档

## 10. 空闲压缩对 session 做了什么

看 [elebot/agent/autocompact.py](../elebot/agent/autocompact.py#L54-L73)：

```python
tail = list(session.messages[session.last_consolidated:])
probe.retain_recent_legal_suffix(self._RECENT_SUFFIX_MESSAGES)
kept = probe.messages
cut = len(tail) - len(kept)
return tail[:cut], kept
```

它不会粗暴清空整个 session，而是：

- 把旧前缀归档
- 只保留最近一段合法尾部

归档后：

```python
session.messages = kept_msgs
session.last_consolidated = 0
```

因为旧前缀已经不在当前 session 数组里了，所以边界要重置。

## 11. 多 session 现在是怎么隔离的

CLI 入口在 [elebot/cli/commands.py](../elebot/cli/commands.py#L313-L317)：

```python
session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID")
```

这意味着你可以显式指定不同 session：

```bash
elebot agent --session cli:direct
elebot agent --session cli:alt-test
```

它们会生成不同的 `sessions/*.jsonl` 文件。

当前项目的结构是：

- session 层隔离
- memory 层共享

共享的长期记忆包括：

- `USER.md`
- `SOUL.md`
- `memory/MEMORY.md`
- `memory/history.jsonl`

## 12. 读完这篇后，下一步看什么

推荐继续看：

- [上下文构建](./context-construction.md)
- [记忆系统设计](./memory-design.md)
- [Agent 主循环](./agent-loop.md)
