# EleBot 上下文构建

这篇文档只讲一件事：

- agent 在真正调用模型前，当前代码是如何把 `workspace`、`memory`、`session`、本轮消息拼成一轮完整 prompt 的

相关源码：

- [elebot/agent/loop.py](../elebot/agent/loop.py#L635-L712)
- [elebot/agent/context.py](../elebot/agent/context.py#L16-L217)
- [elebot/agent/memory.py](../elebot/agent/memory.py#L274-L327)
- [elebot/agent/autocompact.py](../elebot/agent/autocompact.py#L125-L148)

## 1. 上下文构建入口

真正入口在 [elebot/agent/loop.py](../elebot/agent/loop.py#L648-L679)：

```python
key = session_key or msg.session_key
session = self.sessions.get_or_create(key)

session, pending = self.auto_compact.prepare_session(session, key)
await self.consolidator.maybe_consolidate_by_tokens(session)

history = session.get_history(max_messages=0)

initial_messages = self.context.build_messages(
    history=history,
    current_message=msg.content,
    session_summary=pending,
    media=msg.media if msg.media else None,
    channel=msg.channel,
    chat_id=msg.chat_id,
)
```

可以把这段理解成：

1. 先拿到当前 session
2. 处理空闲压缩带回来的摘要
3. 必要时先做一次 token 压缩
4. 读取当前短期历史
5. 交给 `ContextBuilder` 真正拼装消息

## 2. `build_messages()` 最终返回什么

核心逻辑在 [elebot/agent/context.py](../elebot/agent/context.py#L121-L160)：

```python
messages = [
    {"role": "system", "content": self.build_system_prompt(channel=channel)},
    *history,
]
messages.append({"role": current_role, "content": merged})
```

所以当前真正发给模型的消息结构只有三层：

```text
1. system
2. history
3. current user
```

## 3. system 层是怎么构造的

实现见 [elebot/agent/context.py](../elebot/agent/context.py#L34-L66)：

```python
parts = [self._get_identity(channel=channel)]

bootstrap = self._load_bootstrap_files()
if bootstrap:
    parts.append(bootstrap)

memory = self.memory.get_memory_context()
if memory:
    parts.append(f"# 记忆\n\n{memory}")

entries = self.memory.read_unprocessed_history(
    since_cursor=self.memory.get_last_dream_cursor()
)
if entries:
    capped = entries[-self._MAX_RECENT_HISTORY:]
    parts.append("# 最近历史\n\n" + "\n".join(
        f"- [{e['timestamp']}] {e['content']}" for e in capped
    ))

return "\n\n---\n\n".join(parts)
```

system 层固定由 4 块组成：

1. 身份与运行环境
2. bootstrap 文件
3. 长期记忆
4. 最近未被 Dream 吸收的归档历史

## 4. 第一块：身份与运行环境

实现见 [elebot/agent/context.py](../elebot/agent/context.py#L68-L80)：

```python
return render_template(
    "agent/identity.md",
    workspace_path=workspace_path,
    runtime=runtime,
    platform_policy=render_template("agent/platform_policy.md", system=system),
    channel=channel or "",
)
```

它会注入：

- workspace 绝对路径
- 当前运行平台
- Python 版本
- 平台规则
- 当前 channel

这一块的作用是先告诉模型：

> 你现在在哪里、你正在什么环境里运行、你要遵守哪些基本工作规则。

## 5. 第二块：bootstrap 文件

实现见 [elebot/agent/context.py](../elebot/agent/context.py#L109-L119)：

```python
BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]

for filename in self.BOOTSTRAP_FILES:
    file_path = self.workspace / filename
    if file_path.exists():
        content = file_path.read_text(encoding="utf-8")
        parts.append(f"## {filename}\n\n{content}")
```

只要 workspace 里存在这些文件，就会直接进入 system：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`

所以 workspace 里的这些文件，不是仅仅“放在那里备用”，而是 prompt 的一部分。

## 6. 第三块：长期记忆

长期记忆入口在 [elebot/agent/memory.py](../elebot/agent/memory.py#L274-L284)：

```python
def get_memory_context(self) -> str:
    long_term = self.read_memory()
    return f"## 长期记忆\n{long_term}" if long_term else ""
```

这里读取的是：

```text
workspace/memory/MEMORY.md
```

然后拼到 system 里。

## 7. 第四块：最近历史

这里读的不是 session 文件，而是 `history.jsonl` 里 Dream 还没处理掉的归档条目。

代码在 [elebot/agent/context.py](../elebot/agent/context.py#L59-L64)：

```python
entries = self.memory.read_unprocessed_history(
    since_cursor=self.memory.get_last_dream_cursor()
)
```

所以：

- 已经进了 `history.jsonl`
- 但 Dream 还没消费完的内容

会以“最近历史”的形式出现在 system prompt 里。

## 8. 当前 user 消息里为什么会有“运行时上下文”

看 [elebot/agent/context.py](../elebot/agent/context.py#L82-L93)：

```python
lines = [f"当前时间：{current_time_str(timezone)}"]
if channel and chat_id:
    lines += [f"通道：{channel}", f"会话 ID：{chat_id}"]
if session_summary:
    lines += ["", "[恢复的会话]", session_summary]
return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines) + "\n" + ContextBuilder._RUNTIME_CONTEXT_END
```

这一块不是系统提示词，而是会被塞到当前用户消息前面。

它包含：

- 当前时间
- channel
- chat_id
- 空闲压缩恢复摘要

## 9. 为什么这块要塞进 user message，而不是 system

看 [elebot/agent/context.py](../elebot/agent/context.py#L141-L149)：

```python
runtime_ctx = self._build_runtime_context(...)
user_content = self._build_user_content(current_message, media)

if isinstance(user_content, str):
    merged = f"{runtime_ctx}\n\n{user_content}"
else:
    merged = [{"type": "text", "text": runtime_ctx}] + user_content
```

这样做的效果是：

- 运行时元信息只对本轮有效
- 不会污染长期 system 主干
- 也方便在持久化 session 时剥离掉

## 10. 多模态内容怎么进上下文

看 [elebot/agent/context.py](../elebot/agent/context.py#L162-L186)：

```python
if not media:
    return text

images.append({
    "type": "image_url",
    "image_url": {"url": f"data:{mime};base64,{b64}"},
    "_meta": {"path": str(p)},
})

return images + [{"type": "text", "text": text}]
```

也就是说：

- 图片文件会被转成 base64 data URL
- 文字仍然作为文本块附在后面
- 最终形成 provider 可接受的多模态内容数组

## 11. 为什么 session 持久化时还要专门清洗内容

当一轮结束写回 session 时，代码会专门清理运行时上下文和不适合持久化的多模态块。

相关代码：

- [elebot/agent/loop.py](../elebot/agent/loop.py#L755-L802)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L804-L846)

例如会把：

- 运行时上下文标签
- base64 图片块

从 session 持久化内容里剥离或替换。

所以：

> prompt 构建时会临时加一些元数据，  
> 但这些元数据不会原样污染 session 历史。

## 12. 当前上下文各层分别来自哪里

可以直接记这个对照表：

```text
system.identity          ← 模板 + 平台信息 + workspace 路径
system.bootstrap         ← AGENTS.md / SOUL.md / USER.md / TOOLS.md
system.memory            ← memory/MEMORY.md
system.recent_history    ← history.jsonl 中 Dream 未消费部分
history                  ← sessions/*.jsonl 的未归档部分
current user             ← 本轮输入 + 运行时上下文 + 可选媒体
```

## 13. 读完这篇后，下一步看什么

推荐继续看：

- [MEMORY](./MEMORY.md)
- [SESSION](./SESSION.md)
