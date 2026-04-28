# Session 设计

这篇文档只讲当前真实实现下的 session 层，不讲未来多用户系统，也不讲外部数据库方案。

相关源码：

- [elebot/session/manager.py](../elebot/session/manager.py#L15-L219)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L424-L440)
- [elebot/command/handlers/session.py](../elebot/command/handlers/session.py#L9-L24)
- [tests/agent/test_loop_save_turn.py](../tests/agent/test_loop_save_turn.py#L14-L203)
- [tests/agent/test_unified_session.py](../tests/agent/test_unified_session.py#L210-L319)

## 1. 先记一句话

`session` 的职责是：

> 保存单条会话线程的短期消息状态。

它不是：

- 全局长期记忆
- workspace 目录
- 用户账号系统

## 2. Session 对象长什么样

`Session` 里当前最重要的字段有：

- `key`
  - 会话键，例如 `cli:direct`
- `messages`
  - 当前会话保存的原始消息流水
- `metadata`
  - 运行期附加状态
- `last_consolidated`
  - 已归档边界

这里最容易误解的是 `last_consolidated`。

它表示：

```text
messages[0:last_consolidated]     已经归档
messages[last_consolidated:]      仍属于短期上下文
```

## 3. session 文件怎么落盘

session 文件固定放在：

```text
<workspace>/sessions/
```

每个文件是一个 `jsonl`：

- 第一行是 metadata
- 后面每一行才是消息

例如：

```jsonl
{"_type":"metadata","key":"cli:direct","metadata":{},"last_consolidated":0}
{"role":"user","content":"你好"}
{"role":"assistant","content":"你好，我在。"}
```

## 4. 为什么模型看到的历史不是文件原样

`Session.get_history()` 会先做一层“合法短期视图”整理：

1. 只取未归档部分
2. 尽量从一条用户消息开始
3. 剥掉不合法的孤儿工具结果

所以 session 文件更像执行流水，而模型真正看到的是经过清洗后的上下文视图。

## 5. agent 主链路里 session 怎么参与

当前顺序是：

1. `AgentLoop` 读取或创建 session
2. 必要时恢复 runtime checkpoint
3. 必要时做 token 压缩
4. 用 `get_history()` 拿短期视图
5. 把当前一轮新消息写回 session

也就是说，session 不是一个被动仓库，而是 agent 每轮执行都要参与的状态 owner。

## 6. `metadata` 当前最重要的用途

当前 `metadata` 最重要的用途是运行中 checkpoint。

如果一轮执行在中途停掉，系统会把尚未完整写回的状态先放进 `metadata`。  
下一轮进来时，再由 `AgentLoop` 把这些内容恢复成合法历史。

当前 checkpoint 会明确记录：

- `phase`
- `interrupted`
- `interrupt_reason`

所以现在可以把 session 分成两层理解：

- `messages`
  - 已经稳定落盘的消息流水
- `metadata`
  - 运行中附加状态

## 7. interrupted turn 现在怎么落盘

模块五完成后，interrupt 已经固定了恢复策略：

- 半截自然语言回复不落进 session
- 已形成的 assistant tool-call 会保留
- 已完成工具结果会保留
- 未完成工具调用会补一条 interrupted 标记
- interrupted 不再写成 `Error: ...`

未完成工具的补位文本固定为：

```text
Interrupted: tool execution stopped before completion.
```

这样做的目的只有一个：

```text
让下一轮还能继续原 session
但不把半截正文伪装成完整回复
```

## 8. `/new` 现在做了什么

`/new` 不再在命令层自己清理 session。

当前路径是：

```text
/new
  ↓
command/handlers/session.py
  ↓
AgentLoop.reset_session()
```

`reset_session()` 的行为是：

- 取出当前未归档消息
- 清空 session
- 清空 `session.metadata` 里的运行态附加状态
- 立即保存
- 后台把旧消息送去归档

所以 `/new` 不是简单“删聊天记录”，而是：

```text
清空当前短期会话
  +
清空当前运行态 metadata
  +
把旧内容转进长期归档链路
```
