# 上下文构建

这篇文档只讲当前代码怎样把 `workspace`、`memory`、`session` 和本轮消息拼成一轮完整 prompt。

相关源码：

- [elebot/agent/context.py](../elebot/agent/context.py#L16-L239)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L222-L229)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L816-L837)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L899-L920)
- [elebot/templates/agent/task_rules.md](../elebot/templates/agent/task_rules.md#L1-L7)
- [elebot/agent/memory/store.py](../elebot/agent/memory/store.py#L199-L254)
- [elebot/session/manager.py](../elebot/session/manager.py#L37-L63)

## 1. 入口在哪里

当前真正的上下文构建入口仍然在 `AgentLoop`：

```text
session.get_history()
  ↓
ContextBuilder.build_messages()
  ↓
AgentRunner
```

对应调用链在 [elebot/agent/loop.py](../elebot/agent/loop.py#L816-L837)。

所以 `ContextBuilder` 的职责已经固定成“纯上下文装配器”，不再承担 owner 创建和额外副作用。

## 2. `ContextBuilder` 现在依赖什么

`ContextBuilder` 的构造参数已经改成显式注入，见 [elebot/agent/context.py](../elebot/agent/context.py#L24-L39)。

它只接收：

- `workspace`
- `memory_store`
- `skill_registry`
- `timezone`

创建这些 owner 的地方在 [elebot/agent/loop.py](../elebot/agent/loop.py#L222-L229)，也就是 `AgentLoop`。

这意味着：

- `ContextBuilder` 不再自己 new `MemoryStore`
- `ContextBuilder` 不再自己 new `SkillRegistry`

## 3. system prompt 现在由哪些块组成

`build_system_prompt()` 在 [elebot/agent/context.py](../elebot/agent/context.py#L41-L81)。

当前顺序固定是：

1. identity 模板
2. workspace 启动文件
3. 长期记忆
4. skills 摘要
5. 最近未被 Dream 吸收的历史
6. 定时任务规则

其中定时任务规则不再硬编码在 Python 字符串里，而是来自 [elebot/templates/agent/task_rules.md](../elebot/templates/agent/task_rules.md#L1-L7)。

## 4. `ContextBuilder` 不再记录 skill 使用

显式 skill 使用记录已经从 `ContextBuilder` 挪到了 `AgentLoop`。

对应逻辑在 [elebot/agent/loop.py](../elebot/agent/loop.py#L899-L920)。

真实顺序是：

1. `AgentLoop` 在进入 `build_messages()` 前记录显式 skill 提及
2. `ContextBuilder` 只负责读取 `skill_registry.build_prompt_summary()`
3. 把 skills 摘要放进 system prompt

这条边界现在必须固定：

```text
skill 使用记录 = AgentLoop
skills 摘要注入 = ContextBuilder
```

## 5. 记忆和最近历史从哪里来

这部分现在统一来自 `MemoryStore`，见 [elebot/agent/memory/store.py](../elebot/agent/memory/store.py#L199-L254)：

- `get_memory_context()`
  - 读取 `MEMORY.md`
- `read_unprocessed_history()`
  - 读取 `history.jsonl`

`ContextBuilder` 不再关心旧版 `HISTORY.md`，因为当前实现里唯一历史来源已经是 `history.jsonl`。

## 6. 为什么运行时元数据塞进 user message

当前实现会在用户正文前加一段运行时元数据块，相关逻辑在 [elebot/agent/context.py](../elebot/agent/context.py#L97-L180)。

它包含的主要是：

- 当前时间
- channel
- chat_id
- 可选的恢复摘要

这样做的原因是：

- 它只对本轮有效
- 不污染长期 system 主干
- 写回 session 前可以集中剥离

## 7. session 为什么还能保持干净

因为 `SessionManager.get_history()` 本来就只返回适合再送进模型的合法短期视图，见 [elebot/session/manager.py](../elebot/session/manager.py#L37-L63)。

再加上 `AgentLoop` 会在写回 session 前剥掉运行时元数据和不适合长期保存的临时块，所以当前链路可以直接记成：

```text
ContextBuilder 负责把事实送进模型
AgentLoop 负责把临时内容从会话持久化里剥掉
```
