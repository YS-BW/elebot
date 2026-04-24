# EleBot 上下文构建设计

这份文档只讲一件事：

- Agent 在真正调用模型前，如何把当前代码里的各种信息拼成一轮完整上下文

对应代码入口：

- [elebot/agent/context.py](../elebot/agent/context.py) — `ContextBuilder` 类，prompt 构造核心
- [elebot/agent/loop.py](../elebot/agent/loop.py) — `AgentLoop._process_message_result()`，上下文准备入口
- [elebot/agent/autocompact.py](../elebot/agent/autocompact.py) — `AutoCompact`，自动压缩与会话摘要
- [elebot/agent/memory.py](../elebot/agent/memory.py) — `MemoryStore`，记忆存储

## 1. 整体入口

当前主入口在 [elebot/agent/loop.py#L635-L733](../elebot/agent/loop.py#L635-L733) 的 `AgentLoop._process_message_result()`。

简化后的调用链路：

```python
key = session_key or msg.session_key
session = self.sessions.get_or_create(key)

session, pending = self.auto_compact.prepare_session(session, key)
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

这里已经把上下文构建拆成了两层：

- `AgentLoop` 负责准备“这轮有哪些状态要参与”
- `ContextBuilder` 负责把这些状态拼成真正发给模型的 `messages`

## 2. 最终会发给模型什么

`ContextBuilder.build_messages()` 的输出结构很稳定：

```text
1. system
2. 历史消息 history
3. 当前 user 消息
```

简化代码：

```python
messages = [
    {"role": "system", "content": self.build_system_prompt(channel=channel)},
    *history,
]

messages.append({"role": current_role, "content": merged})
```

所以当前上下文不是“只有一个大 prompt”，而是三层消息共同构成：

- `system`：全局规则、工作区记忆、近期历史
- `history`：当前 session 已保存的对话历史
- `current user`：本轮输入，以及本轮运行时元数据

## 3. system 层怎么构造

真正的 system prompt 在 [elebot/agent/context.py#L34-L66](../elebot/agent/context.py#L34-L66) 的 `ContextBuilder.build_system_prompt()`：

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
    parts.append("# 最近历史\n\n" + "\n".join(...))

return "\n\n---\n\n".join(parts)
```

system 层固定由 4 段组成：

1. 身份与运行环境
2. bootstrap 文件
3. 长期记忆
4. 最近历史

中间统一用 `---` 分隔。

## 4. 第一段：身份与运行环境

这部分来自 `_get_identity()`，代码在 [elebot/agent/context.py#L68-L80](../elebot/agent/context.py#L68-L80)，模板文件是：

- [elebot/templates/agent/identity.md](../elebot/templates/agent/identity.md)
- [elebot/templates/agent/platform_policy.md](../elebot/templates/agent/platform_policy.md)

代码（[context.py#L68-L80](../elebot/agent/context.py#L68-L80)）：

```python
return render_template(
    "agent/identity.md",
    workspace_path=workspace_path,
    runtime=runtime,
    platform_policy=render_template("agent/platform_policy.md", system=system),
    channel=channel or "",
)
```

它会注入这些运行时事实：

- 工作区绝对路径
- 当前系统和 Python 版本
- 平台规则
- 当前渠道

这段的职责不是保存用户数据，而是给模型说明：

- 你是谁
- 你现在在哪个工作区里
- 你当前跑在什么平台上
- 你输出时应该遵守什么格式规则
- 你执行任务时应该遵守什么工作规则

### 4.1 `identity.md` 负责什么

当前模板内容主要分成几块：

- 助手身份
- 运行环境
- 工作区路径
- 渠道格式提示
- 执行规则
- 搜索与发现规则

简化后的真实内容：

```md
# elebot 🍌

你是 elebot，一个乐于助人的 AI 助手。

## 运行环境
{{ runtime }}

## 工作区
你的工作区位于：{{ workspace_path }}

## 执行规则
- 能做就直接做
- 先读后写
- 工具失败先诊断再报告
- 信息不足时优先用工具查证
- 修改后要验证结果
```

这部分决定的是 agent 的基础工作方式。

### 4.2 `platform_policy.md` 负责什么

这部分是平台差异规则。

例如在 POSIX 系统上，会注入：

```md
## 平台规则（POSIX）
- 你当前运行在 POSIX 系统上。优先使用 UTF-8 和标准 shell 工具。
- 当文件工具比 shell 命令更简单或更可靠时，优先使用文件工具。
```

这段不是产品逻辑，而是运行环境约束。  
它的作用是减少模型对系统命令能力的错误假设。

## 5. 第二段：bootstrap 文件

这部分来自 `_load_bootstrap_files()`，代码在 [elebot/agent/context.py#L109-L119](../elebot/agent/context.py#L109-L119)：

```python
BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]

for filename in self.BOOTSTRAP_FILES:
    file_path = self.workspace / filename
    if file_path.exists():
        content = file_path.read_text(encoding="utf-8")
        parts.append(f"## {filename}\n\n{content}")
```

也就是说，当前工作区下只要存在下面这些文件，就会被直接拼进 system：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`

### 5.1 `AGENTS.md`

作用：

- 放工作区级别的 agent 规则
- 用来覆盖或补充默认行为

### 5.2 `SOUL.md`

作用：

- 定义助手的人格、语气、表达倾向

当前模板在 [elebot/templates/SOUL.md](../elebot/templates/SOUL.md)。

### 5.3 `USER.md`

作用：

- 存放用户画像和长期稳定偏好

当前模板在 [elebot/templates/USER.md](../elebot/templates/USER.md)。

### 5.4 `TOOLS.md`

作用：

- 记录工具使用限制和经验性规则
- 不重复描述工具 schema，只补充”不直观的限制”

当前模板在 [elebot/templates/TOOLS.md](../elebot/templates/TOOLS.md)。

## 6. 第三段：长期记忆

这部分来自 `MemoryStore.get_memory_context()`，实现位于 [elebot/agent/memory.py#L274-L284](../elebot/agent/memory.py#L274-L284)：

```python
def get_memory_context(self) -> str:
    long_term = self.read_memory()
    return f"## 长期记忆\n{long_term}" if long_term else ""
```

数据来源：

- `workspace/memory/MEMORY.md`

然后在 system 层里会被再包一层：

```python
parts.append(f"# 记忆\n\n{memory}")
```

所以最终效果大致是：

```md
# 记忆

## 长期记忆
<MEMORY.md 内容>
```

这部分的职责是提供跨会话保留的稳定事实，例如：

- 用户长期偏好
- 项目背景
- 需要持续记住的关键信息

## 7. 第四段：最近历史

这部分来自 `build_system_prompt()` 内部对 `read_unprocessed_history()` 的调用，代码在 [elebot/agent/context.py#L59-L64](../elebot/agent/context.py#L59-L64)：

```python
entries = self.memory.read_unprocessed_history(
    since_cursor=self.memory.get_last_dream_cursor()
)
```

也就是从 `history.jsonl` 里取出”Dream 还没有处理过”的历史。

关键点有两个：

- 它不是当前 session 的历史消息
- 它只取尚未被 Dream 吸收进长期记忆的那一部分

真正拼接时最多只保留最近 50 条：

```python
_MAX_RECENT_HISTORY = 50
```

格式大致是：

```md
# 最近历史

- [2026-04-24 16:00] 用户说了什么
- [2026-04-24 16:02] 助手做了什么
```

这一段的作用是作为“长期记忆和当前会话之间的缓冲层”：

- 太新的内容，还没沉淀进 `MEMORY.md`
- 但又不应该完全丢掉

## 8. user 层前面的运行时上下文

运行时上下文不在 system 里，而是在当前 `user` 消息前面注入。

代码在 [elebot/agent/context.py#L82-L93](../elebot/agent/context.py#L82-L93) 的 `ContextBuilder._build_runtime_context()`：

```python
lines = [f"当前时间：{current_time_str(timezone)}"]
if channel and chat_id:
    lines += [f"通道：{channel}", f"会话 ID：{chat_id}"]
if session_summary:
    lines += ["", "[恢复的会话]", session_summary]
```

生成结果类似：

```text
[运行时上下文——仅元数据，不是指令]
当前时间：2026-04-24 17:00:00
通道：cli
会话 ID：direct

[恢复的会话]
<自动压缩后的恢复摘要>
[/运行时上下文]
```

这里要特别区分：

- `system` 放的是相对稳定的全局规则和背景
- 运行时上下文放的是当前这一轮才有意义的瞬时元数据

## 9. `history` 层是什么

`history` 来自 session：

```python
history = session.get_history(max_messages=0)
```

所以当前一轮真正发给模型的不是：

```text
只有 system + 当前提问
```

而是：

```text
system
+ session history
+ 当前 user
```

## 10. `auto_compact` 在上下文构造里起什么作用

在真正构建 `messages` 前，会先调用：

```python
session, pending = self.auto_compact.prepare_session(session, key)
```

这个 `pending` 是一个一次性的恢复摘要。  
如果会话之前做过自动压缩，它会把被压缩掉的旧上下文，先以摘要形式补回这一轮。

代码位置：[elebot/agent/autocompact.py#L16-L31](../elebot/agent/autocompact.py#L16-L31)（`AutoCompact.prepare_session()`）

简化逻辑：

```python
entry = self._summaries.pop(key, None)
if entry:
    return session, self._format_summary(entry[0], entry[1])
```

所以完整链路里，`auto_compact` 的作用是：

- 不让 session 一直无限膨胀
- 但又给下一轮留一个“恢复摘要”

## 11. 图片消息如何进入上下文

如果当前消息带图片，`_build_user_content()` 会把图片转成多模态块，代码在 [elebot/agent/context.py#L162-L186](../elebot/agent/context.py#L162-L186)：

```python
images.append({
    "type": "image_url",
    "image_url": {"url": f"data:{mime};base64,{b64}"},
    "_meta": {"path": str(p)},
})
```

最后 user 消息会变成：

```python
[
    {"type": "image_url", ...},
    {"type": "text", "text": text},
]
```

如果没有媒体，就是普通字符串文本。

## 12. 为什么运行时上下文不直接长期保存

保存会话时，代码会主动把运行时上下文剥掉。

实现位于 [elebot/agent/loop.py#L804-L846](../elebot/agent/loop.py#L804-L846) 的 `AgentLoop._save_turn()`：

```python
if role == "user":
    if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
        ...
        entry["content"] = after
```

这表示：

- 当前时间
- 通道
- 会话 ID
- 恢复摘要

这些都只是本轮推理辅助信息，不应该长期污染 session history。

## 13. 一轮完整上下文的结构图

```text
用户消息进入 AgentLoop
    ↓
取出 session
    ↓
auto_compact.prepare_session()
    ↓
得到：
- history
- 可选 session_summary
    ↓
ContextBuilder.build_system_prompt()
    ↓
system =
- identity
- bootstrap files
- 长期记忆
- 最近历史
    ↓
ContextBuilder._build_runtime_context()
    ↓
当前 user =
- 运行时元数据
- 用户文本 / 图片
    ↓
最终 messages =
- system
- history
- current user
```

## 14. 一句话总结

当前上下文构建不是单一 prompt 拼接，而是明确分层的：

- `system` 负责全局规则、工作区规则、长期背景、近期缓冲历史
- `history` 负责当前 session 的对话链路
- `current user` 负责本轮输入和瞬时运行时信息

这套设计的核心目标只有一个：

- 让模型每一轮既能拿到稳定规则，也能拿到当前会话真实状态，同时避免把瞬时元数据和原始历史无限制堆进长期上下文
