# Agent 模块教程

`elebot/agent` 是 EleBot 当前主链路里最核心的一层。  
它的职责不是“展示 UI”，也不是“保存配置”，而是把一条消息变成一次完整执行：

1. 读取会话历史
2. 组装上下文
3. 调模型
4. 执行工具
5. 把工具结果继续回给模型
6. 保存最终结果

如果你只想抓住一句话，可以先记住：

> `AgentLoop` 负责编排，`AgentRunner` 负责执行，`ContextBuilder` 负责组装上下文。

---

## 文档索引

- [1. 先建立整体心智模型](#1-先建立整体心智模型)
- [2. 目录和文件怎么读](#2-目录和文件怎么读)
- [3. 两种入口：总线模式与直连模式](#3-两种入口总线模式与直连模式)
- [4. AgentLoop：主链路编排器](#4-agentloop主链路编排器)
- [5. ContextBuilder：上下文是怎么拼出来的](#5-contextbuilder上下文是怎么拼出来的)
- [6. AgentRunner：模型和工具怎么闭环](#6-agentrunner模型和工具怎么闭环)
- [7. Hook：为什么流式输出和工具提示能插进主循环](#7-hook为什么流式输出和工具提示能插进主循环)
- [8. Session、Checkpoint 和中断恢复](#8-sessioncheckpoint-和中断恢复)
- [9. 中途追问为什么不会把会话打裂](#9-中途追问为什么不会把会话打裂)
- [10. 记忆系统：Memory / Consolidator / Dream](#10-记忆系统memory--consolidator--dream)
- [11. AutoCompact：空闲会话如何自动压缩](#11-autocompact空闲会话如何自动压缩)
- [12. Skills：技能是怎么被发现和注入的](#12-skills技能是怎么被发现和注入的)
- [13. Subagent：后台子 Agent 是怎么工作的](#13-subagent后台子-agent-是怎么工作的)
- [14. 相关文档跳转](#14-相关文档跳转)

---

## 1. 先建立整体心智模型

先不要急着读细节。先把 Agent 理解成下面这条流水线：

```text
用户输入
  ↓
AgentLoop
  ↓
ContextBuilder
  ↓
AgentRunner
  ↓
ToolRegistry（如有工具调用）
  ↓
AgentRunner
  ↓
AgentLoop 保存会话并返回结果
```

换一种更接近代码的写法：

```python
msg -> _process_message_result() -> build_messages() -> runner.run() -> save_turn()
```

主入口源码：

- [loop.py#L50-L1047](../../elebot/agent/loop.py#L50-L1047)
- [runner.py:52-899](../elebot/agent/runner.py#L52-L899)
- [context.py:17-214](../elebot/agent/context.py#L17-L214)

---

## 2. 目录和文件怎么读

`elebot/agent/` 里最关键的文件如下：

| 文件 | 作用 |
| --- | --- |
| [loop.py:50-1047](../elebot/agent/loop.py#L50-L1047) | 主链路编排器，负责接消息、调命令、调 Runner、保存会话。 |
| [runner.py:52-899](../elebot/agent/runner.py#L52-L899) | 单轮模型执行循环，负责“模型 -> 工具 -> 模型”。 |
| [context.py:17-214](../elebot/agent/context.py#L17-L214) | system prompt、历史、runtime context、媒体内容拼装。 |
| [hook.py:14-169](../elebot/agent/hook.py#L14-L169) | 生命周期 Hook 抽象。 |
| [memory.py:31-778](../elebot/agent/memory.py#L31-L778) | 长期记忆、历史归档、Dream。 |
| [autocompact.py:15-125](../elebot/agent/autocompact.py#L15-L125) | 空闲会话自动压缩。 |
| [skills.py:23-219](../elebot/agent/skills.py#L23-L219) | 技能发现、过滤、摘要、always 技能注入。 |
| [subagent.py:26-280](../elebot/agent/subagent.py#L26-L280) | 后台子 Agent 管理。 |
| `tools/` | 真正能被模型调用的工具。 |

如果你第一次读代码，建议顺序是：

1. [loop.py:50-1047](../elebot/agent/loop.py#L50-L1047)
2. [context.py:17-214](../elebot/agent/context.py#L17-L214)
3. [runner.py:52-899](../elebot/agent/runner.py#L52-L899)
4. [hook.py:14-169](../elebot/agent/hook.py#L14-L169)
5. [memory.py:31-778](../elebot/agent/memory.py#L31-L778)
6. [skills.py:23-219](../elebot/agent/skills.py#L23-L219)
7. [subagent.py:26-280](../elebot/agent/subagent.py#L26-L280)

原因很简单：

- `loop.py` 决定“谁先调用谁”
- `context.py` 决定“模型看到什么”
- `runner.py` 决定“模型和工具怎么形成闭环”

---

## 3. 两种入口：总线模式与直连模式

Agent 目前有两种主要调用方式。

### 3.1 总线模式

交互式 CLI 和 channels 走总线模式。

```text
CLI / Channel
  -> MessageBus.publish_inbound()
  -> AgentLoop.run()
  -> AgentLoop._dispatch()
  -> AgentLoop._process_message_result()
  -> MessageBus.publish_outbound()
  -> CLI / Channel 消费结果
```

关键代码：

- [AgentLoop.run](../elebot/agent/loop.py#L455)
- [AgentLoop._dispatch](../elebot/agent/loop.py#L522)

一个非常简化的理解版本：

```python
async def run(self):
    while self._running:
        msg = await self.bus.consume_inbound()
        task = asyncio.create_task(self._dispatch(msg))
```

这个模式适合：

- CLI 交互
- 多通道入口
- 需要 `/stop` 这类控制命令的场景

### 3.2 直连模式

`facade` 和单次调用更适合走直连模式：

```text
调用方
  -> AgentLoop.process_direct_result()
  -> AgentLoop._process_message_result()
  -> AgentRunner.run()
```

关键代码：

- [AgentLoop.process_direct](../elebot/agent/loop.py#L1025)
- [AgentLoop.process_direct_result](../elebot/agent/loop.py#L1047)

极简代码：

```python
async def process_direct_result(self, content: str, ...):
    msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
    return await self._process_message_result(msg, ...)
```

这个模式的好处是：

- 不必启动常驻 `run()` 循环
- 不必依赖全局总线
- 将来如果做桌面 runtime，本地后端服务更适合走这条路

---

## 4. AgentLoop：主链路编排器

`AgentLoop` 是 Agent 模块的总调度器。  
初始化时，它会一次性装配几乎所有主链路依赖。

源码位置：

- [AgentLoop.__init__](../elebot/agent/loop.py#L155)

你可以把它理解成：

```python
self.context = ContextBuilder(...)
self.sessions = SessionManager(...)
self.tools = ToolRegistry()
self.runner = AgentRunner(provider)
self.subagents = SubagentManager(...)
self.consolidator = Consolidator(...)
self.auto_compact = AutoCompact(...)
self.dream = Dream(...)
register_builtin_commands(self.commands)
self._register_default_tools()
```

也就是说，`AgentLoop` 自己不做所有事情，但它知道：

- 什么时候该读 session
- 什么时候该处理 slash 命令
- 什么时候该构造上下文
- 什么时候该调用 Runner
- 什么时候该保存结果

### 4.1 AgentLoop 主要管什么

可以把职责拆成 4 段：

```text
1. 接收与路由
2. 会话准备
3. 调用 Runner
4. 收尾保存
```

再展开一点：

```text
收到消息
  -> 判断是否是优先级命令
  -> 计算 effective session key
  -> 同 session 串行调度
  -> 读取 session / 恢复 checkpoint
  -> 执行普通命令或进入模型链路
  -> 保存消息与结果
  -> 发布 OutboundMessage
```

关键代码入口：

- [AgentLoop.run](../elebot/agent/loop.py#L455)
- [AgentLoop._process_message_result](../elebot/agent/loop.py#L660)
- [AgentLoop._save_turn](../elebot/agent/loop.py#L891)

### 4.2 为什么有两个命令入口

这里最容易看漏。

`AgentLoop` 里其实有两层命令处理：

1. `run()` 里的优先级命令
2. `_process_message_result()` 里的普通命令

相关代码：

- [run() 中的 priority command 处理](../elebot/agent/loop.py#L476)
- [_process_message_result() 中的普通命令处理](../elebot/agent/loop.py#L709)

这样做的原因是：

- `/stop`、`/restart` 这类命令必须尽量早处理，不能等当前任务完整跑完
- `/status`、`/new`、`/dream` 这类命令则属于正常会话语义，可以在进入模型前统一分流

### 4.3 默认工具是在哪里注册的

所有主链路默认工具在 `_register_default_tools()` 中注册。

源码：

- [AgentLoop._register_default_tools](../elebot/agent/loop.py#L274)

简化后的结构大概是：

```python
self.tools.register(ReadFileTool(...))
self.tools.register(WriteFileTool(...))
self.tools.register(EditFileTool(...))
self.tools.register(ListDirTool(...))
self.tools.register(GlobTool(...))
self.tools.register(GrepTool(...))
self.tools.register(NotebookEditTool(...))

if self.exec_config.enable:
    self.tools.register(ExecTool(...))

if self.web_config.enable:
    self.tools.register(WebSearchTool(...))
    self.tools.register(WebFetchTool(...))

self.tools.register(MessageTool(...))
self.tools.register(SpawnTool(...))
```

所以工具面不是散落在 CLI 或 Provider 里，而是由 `AgentLoop` 统一装配。

---

## 5. ContextBuilder：上下文是怎么拼出来的

模型看到的不是“纯用户输入”，而是完整的 `messages` 数组。  
这个数组由 `ContextBuilder` 负责构造。

源码：

- [ContextBuilder](../elebot/agent/context.py#L17)
- [ContextBuilder.build_system_prompt](../elebot/agent/context.py#L36)
- [ContextBuilder.build_messages](../elebot/agent/context.py#L135)

### 5.1 它会拼哪些东西

`build_system_prompt()` 会按顺序拼这些内容：

1. 身份模板
2. 工作区启动文件
3. 长期记忆
4. always 技能
5. 技能摘要
6. 最近未被 Dream 吸收的历史

代码中最值得看的几行：

```python
parts = [self._get_identity(channel=channel)]

bootstrap = self._load_bootstrap_files()
memory = self.memory.get_memory_context()
always_skills = self.skills.get_always_skills()
skills_summary = self.skills.build_skills_summary()
entries = self.memory.read_unprocessed_history(...)
```

对应源码：

- [ContextBuilder._get_identity](../elebot/agent/context.py#L82)
- [ContextBuilder._load_bootstrap_files](../elebot/agent/context.py#L123)

### 5.2 什么是 runtime context

每轮消息前还会拼一小段运行时元信息：

源码：

- [ContextBuilder._build_runtime_context](../elebot/agent/context.py#L96)

它长这样：

```text
[Runtime Context — metadata only, not instructions]
Current Time: ...
Channel: cli
Chat ID: direct
[/Runtime Context]
```

它的作用是：

- 给模型提供当前时间
- 告诉模型当前消息来自哪个 channel / chat
- 在恢复会话时带上 session summary

但这不是长期历史，所以保存会话时会被剥掉。

### 5.3 为什么要把 runtime context 和用户正文合成一条消息

关键逻辑：

- [ContextBuilder.build_messages](../elebot/agent/context.py#L135)
- [ContextBuilder._merge_message_content](../elebot/agent/context.py#L109)

核心代码：

```python
if isinstance(user_content, str):
    merged = f"{runtime_ctx}\n\n{user_content}"
else:
    merged = [{"type": "text", "text": runtime_ctx}] + user_content
```

原因在注释里也写得很清楚：

> 避免部分 Provider 拒绝连续出现相同 role 的消息。

也就是说，这不是文档技巧，而是 Provider 协议兼容问题。

### 5.4 图片消息怎么进模型

如果 `media` 里有图片路径，`ContextBuilder._build_user_content()` 会：

1. 读取本地文件
2. 判断 MIME
3. 转成 base64 data URL
4. 生成 `image_url` 内容块

源码：

- [ContextBuilder._build_user_content](../elebot/agent/context.py#L177)

简化代码：

```python
raw = p.read_bytes()
mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
images.append({
    "type": "image_url",
    "image_url": {"url": f"data:{mime};base64,{b64}"},
})
```

---

## 6. AgentRunner：模型和工具怎么闭环

如果说 `AgentLoop` 是调度器，那么 `AgentRunner` 就是“真正跑一轮模型循环的人”。

源码：

- [AgentRunSpec](../elebot/agent/runner.py#L51)
- [AgentRunResult](../elebot/agent/runner.py#L78)
- [AgentRunner.run](../elebot/agent/runner.py#L183)

### 6.1 先看输入和输出

Runner 的输入是 `AgentRunSpec`：

```python
AgentRunSpec(
    initial_messages=...,
    tools=...,
    model=...,
    max_iterations=...,
    hook=...,
    checkpoint_callback=...,
    injection_callback=...,
)
```

Runner 的输出是 `AgentRunResult`：

```python
AgentRunResult(
    final_content=...,
    messages=...,
    tools_used=...,
    usage=...,
    stop_reason=...,
)
```

你可以把它理解成：

> 给我上下文和工具，我帮你跑完；最后把最终文本、完整消息轨迹和停止原因还给你。

### 6.2 一轮循环内部到底做什么

`AgentRunner.run()` 的结构其实很清晰，可以压缩成下面这段伪代码：

```python
for iteration in range(max_iterations):
    messages_for_model = 治理后的消息副本
    response = 请求模型

    if response.has_tool_calls:
        记录 assistant tool call 消息
        执行工具
        追加 tool 消息
        如有中途追问则注入
        continue

    clean = finalize_content(response.content)

    if 空回复:
        重试或走最终收口补救

    if 被截断:
        追加恢复提示并继续

    if 最终阶段又注入了新消息:
        continue

    结束并返回最终结果
```

### 6.3 每轮调模型前，为什么要先“治理上下文”

源码：

- [run() 中的消息治理逻辑](../elebot/agent/runner.py#L209)

相关函数：

- [AgentRunner._drop_orphan_tool_results](../elebot/agent/runner.py#L727)
- [AgentRunner._backfill_missing_tool_results](../elebot/agent/runner.py#L753)
- [AgentRunner._microcompact](../elebot/agent/runner.py#L794)
- [AgentRunner._apply_tool_result_budget](../elebot/agent/runner.py#L819)
- [AgentRunner._snip_history](../elebot/agent/runner.py#L840)

这一步的核心目的不是“美化消息”，而是：

- 保证协议合法
- 控制上下文长度
- 防止 tool 结果太大把 prompt 撑爆
- 尽量保住最近的重要消息

文档上要特别注意这一点：

> 持久化历史保持原样，发给模型的是治理后的副本。

这是当前实现里一个很重要的边界。

### 6.4 工具调用是怎么闭环的

最关键的一段逻辑在：

- [response.has_tool_calls 分支](../elebot/agent/runner.py#L241)

核心代码可以浓缩成：

```python
assistant_message = build_assistant_message(...tool_calls...)
messages.append(assistant_message)

results, new_events, fatal_error = await self._execute_tools(...)

for tool_call, result in zip(response.tool_calls, results):
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": normalized_result,
    })
```

然后下一轮再把 `messages + tool results` 发给模型。

这就是“工具闭环”的真实含义：

```text
模型请求工具
  -> Agent 执行工具
  -> Agent 把工具结果回填成 role=tool 消息
  -> 模型继续生成
```

### 6.5 空回复、截断和错误怎么收口

这一块是很多人读代码时会跳过的，但其实很重要。

相关代码：

- [空回复重试](../elebot/agent/runner.py#L285)
- [长度截断恢复](../elebot/agent/runner.py#L317)
- [模型错误收口](../elebot/agent/runner.py#L425)

当前策略不是“模型给什么就信什么”，而是：

- 如果文本空了，先重试
- 如果还是空，再尝试 finalization retry
- 如果输出被截断，追加恢复消息继续生成
- 如果模型报错，返回统一错误文案并落 placeholder

这说明 `AgentRunner` 不只是“转发 Provider”，而是在做运行时收口。

---

## 7. Hook：为什么流式输出和工具提示能插进主循环

Hook 的作用是：

> 在不改动 `AgentRunner.run()` 主流程的前提下，把一些“额外观察和回调能力”接进去。

源码：

- [AgentHookContext](../elebot/agent/hook.py#L13)
- [AgentHook](../elebot/agent/hook.py#L29)
- [CompositeHook](../elebot/agent/hook.py#L69)

### 7.1 Hook 生命周期很简单

```text
before_iteration
  -> on_stream
  -> on_stream_end
  -> before_execute_tools
  -> after_iteration
  -> finalize_content
```

### 7.2 主链路里真正使用的是 _LoopHook

源码：

- [_LoopHook](../elebot/agent/loop.py#L61)
- [AgentLoop._run_agent_loop](../elebot/agent/loop.py#L364)

`_LoopHook` 干了几件关键事情：

1. 把流式正文转发到外层 UI
2. 把工具提示转成 progress 输出
3. 设置路由相关工具上下文
4. 记录 token usage
5. 去掉 `<think>...</think>` 再落盘

其中一个非常关键的细节在这里：

- [_LoopHook.on_stream](../elebot/agent/loop.py#L94)

核心代码：

```python
prev_clean = strip_think(self._stream_buf)
self._stream_buf += delta
new_clean = strip_think(self._stream_buf)
incremental = new_clean[len(prev_clean):]
```

也就是说：

> 流式回调给 UI 的不是原始 delta，而是剥掉 think 后的可见增量。

### 7.3 CompositeHook 为什么要存在

因为主链路可能有多个 Hook：

- 内置 `_LoopHook`
- 外部通过 facade 传进来的 hooks

相关代码：

- [CompositeHook](../elebot/agent/hook.py#L69)
- [_run_agent_loop 中组合 hook](../elebot/agent/loop.py#L385)

它的策略是：

- 异步阶段：尽量异常隔离
- `finalize_content`：按顺序串行处理

---

## 8. Session、Checkpoint 和中断恢复

Agent 并不是每次都只处理内存态消息。  
它会持续把本轮结果写回 `SessionManager`。

关键代码：

- [_save_turn](../elebot/agent/loop.py#L891)
- [AgentLoop._set_runtime_checkpoint](../elebot/agent/loop.py#L935)
- [AgentLoop._restore_runtime_checkpoint](../elebot/agent/loop.py#L972)

### 8.1 为什么要有 checkpoint

一轮工具调用不一定能原子完成。

比如：

```text
模型先返回 tool_calls
  -> agent 还没来得及执行完全部工具
  -> 进程中断
```

如果没有 checkpoint，会话历史就会残缺：

- 有 assistant 的 tool call
- 没有对应 tool result

所以 AgentLoop 会把运行中的阶段状态写进：

```python
session.metadata["runtime_checkpoint"] = payload
```

源码：

- [AgentLoop._set_runtime_checkpoint](../elebot/agent/loop.py#L935)

### 8.2 恢复时会怎么做

恢复逻辑在：

- [AgentLoop._restore_runtime_checkpoint](../elebot/agent/loop.py#L972)

它会：

1. 恢复 assistant tool call 消息
2. 恢复已完成工具结果
3. 给未完成工具补一条中断错误消息
4. 做 overlap 去重，避免重复写入
5. 清掉 checkpoint

补未完成工具结果的关键代码：

```python
restored_messages.append(
    {
        "role": "tool",
        "tool_call_id": tool_id,
        "name": name,
        "content": "Error: Task interrupted before this tool finished.",
    }
)
```

这就是为什么中断后再次进入同一会话时，历史仍能保持协议完整。

### 8.3 保存历史时会做哪些清理

`_save_turn()` 不是原样把所有消息 dump 进 session。

它会做这些事情：

- 丢掉空 assistant 消息
- 截断过长工具结果
- 清洗不适合持久化的多模态块
- 去掉 runtime context

源码：

- [_sanitize_persisted_blocks](../elebot/agent/loop.py#L842)
- [_save_turn](../elebot/agent/loop.py#L891)

所以这里要建立一个正确认知：

> 会话历史不是“原始请求日志”，而是“适合后续继续对话的持久化版本”。

---

## 9. 中途追问为什么不会把会话打裂

这是当前 Agent 设计里一个很重要但不太显眼的点。

相关代码：

- [AgentLoop._effective_session_key](../elebot/agent/loop.py#L358)
- [run() 中 pending queue 逻辑](../elebot/agent/loop.py#L455)
- [_run_agent_loop() 中的 _drain_pending](../elebot/agent/loop.py#L404)
- [AgentRunner._drain_injections](../elebot/agent/runner.py#L138)

### 9.1 核心结构

`AgentLoop` 维护两组结构：

- `_session_locks`
- `_pending_queues`

意思是：

- 同一个 session 同时只跑一个主任务
- 新消息先进入 pending queue，而不是立即并发跑第二个任务

### 9.2 整体流程

```text
第一条消息进入
  -> 创建当前 session 的 pending queue
  -> 开始跑 AgentRunner

同 session 第二条消息进入
  -> 不新建竞争任务
  -> 放进 pending queue

AgentRunner 在工具后或最终回复前
  -> drain 注入消息
  -> 合并进当前 messages
  -> 继续下一轮模型调用
```

### 9.3 为什么这很重要

如果没有这层机制，会出现两个问题：

1. 同一份 session history 被两个任务并发修改
2. 用户追问被拆成完全独立的另一轮，语义断裂

当前实现选择的是：

> 优先把追问吸收到当前执行链路里。

不过要注意：

- Agent 内核已经支持这种注入
- 但 CLI 交互层目前还没有把“生成中继续输入”做成可用体验

这两件事不是一回事。

---

## 10. 记忆系统：Memory / Consolidator / Dream

`agent/memory.py` 里其实是三块能力叠在一起：

1. `MemoryStore`
2. `Consolidator`
3. `Dream`

源码：

- [MemoryStore](../elebot/agent/memory.py#L31)
- [Consolidator](../elebot/agent/memory.py#L463)
- [Dream](../elebot/agent/memory.py#L701)

### 10.1 MemoryStore：纯文件存储层

它的定位很明确：

> 维护记忆目录里的文件事实，不承担模型决策逻辑。

它负责的文件包括：

- `memory/MEMORY.md`
- `memory/history.jsonl`
- `SOUL.md`
- `USER.md`

关键代码：

- [MemoryStore.__init__](../elebot/agent/memory.py#L41)

你可以把它理解成“记忆文件仓库”。

### 10.2 Consolidator：旧消息归档

`Consolidator` 的职责是：

- 估算 prompt token
- 决定是否需要压缩
- 把旧消息归档到长期历史或摘要

相关入口：

- [estimate_session_prompt_tokens](../elebot/agent/memory.py#L548)
- [MemoryStore.archive](../elebot/agent/memory.py#L572)
- [Consolidator.maybe_consolidate_by_tokens](../elebot/agent/memory.py#L608)

所以 AgentLoop 在处理消息前后都会调用它：

- 处理前：判断是否需要先压缩
- 处理后：后台调度一次 `maybe_consolidate_by_tokens`

### 10.3 Dream：长期记忆整理器

`Dream` 不是普通会话摘要，它更接近：

> 定期用模型整理长期记忆文件，并通过 GitStore 留版本。

入口：

- [Dream.__init__](../elebot/agent/memory.py#L701)
- [Dream.run](../elebot/agent/memory.py#L778)

从主链路角度看：

- `ContextBuilder` 会消费 Dream 整理后的结果
- `Dream` 本身不直接参与每一轮普通对话

---

## 11. AutoCompact：空闲会话如何自动压缩

`AutoCompact` 不是按 token 压缩，而是按“空闲时间”压缩。

源码：

- [AutoCompact](../elebot/agent/autocompact.py#L15)
- [AutoCompact.check_expired](../elebot/agent/autocompact.py#L75)
- [AutoCompact.prepare_session](../elebot/agent/autocompact.py#L125)

### 11.1 它在干嘛

逻辑可以简单理解成：

```text
如果一个会话长时间没动
  -> 后台归档旧前缀
  -> 只保留最近合法后缀
  -> 如有摘要，下次恢复会话时注入 summary
```

### 11.2 它和 Consolidator 的区别

不要把它和 `Consolidator` 混在一起。

- `Consolidator`：按上下文压力压缩
- `AutoCompact`：按空闲时间压缩

一个解决“当前 prompt 太大”，一个解决“旧会话长期堆积”。

---

## 12. Skills：技能是怎么被发现和注入的

`SkillsLoader` 负责两类技能来源：

1. 工作区技能
2. 内置技能

源码：

- [SkillsLoader](../elebot/agent/skills.py#L23)
- [SkillsLoader.list_skills](../elebot/agent/skills.py#L58)
- [SkillsLoader.build_skills_summary](../elebot/agent/skills.py#L115)
- [SkillsLoader.get_always_skills](../elebot/agent/skills.py#L200)

### 12.1 发现规则

技能目录约定是：

```text
<workspace>/skills/<name>/SKILL.md
elebot/skills/<name>/SKILL.md
```

工作区技能优先，同名时覆盖内置技能。

对应代码：

- [SkillsLoader._skill_entries_from_dir](../elebot/agent/skills.py#L42)
- [SkillsLoader.list_skills](../elebot/agent/skills.py#L58)

### 12.2 为什么不是所有技能都完整注入

因为太大。

当前策略是：

- `always` 技能：完整注入
- 其他技能：只进摘要

摘要构造入口：

- [SkillsLoader.build_skills_summary](../elebot/agent/skills.py#L115)

always 技能入口：

- [SkillsLoader.get_always_skills](../elebot/agent/skills.py#L200)

### 12.3 依赖检查怎么做

技能可以声明：

- 需要某个 CLI 命令
- 需要某个环境变量

依赖检查逻辑：

- [SkillsLoader._check_requirements](../elebot/agent/skills.py#L186)
- [SkillsLoader._get_missing_requirements](../elebot/agent/skills.py#L149)

所以技能不是简单的“目录里有就可用”，而是会做环境过滤。

---

## 13. Subagent：后台子 Agent 是怎么工作的

当主 Agent 调用 `spawn` 工具时，真正负责后台任务的是 `SubagentManager`。

源码：

- [SubagentManager](../elebot/agent/subagent.py#L44)
- [SubagentManager.spawn](../elebot/agent/subagent.py#L79)
- [SubagentManager._run_subagent](../elebot/agent/subagent.py#L118)
- [SubagentManager._announce_result](../elebot/agent/subagent.py#L197)

### 13.1 它的设计目标

核心目标不是“复制一个主 Agent”，而是：

> 起一个聚焦、受限、后台运行的子任务执行器。

所以它不会复用主 Agent 的整套工具面。

从代码能看出来，子 Agent 只注册了受限工具集：

```python
tools.register(ReadFileTool(...))
tools.register(WriteFileTool(...))
tools.register(EditFileTool(...))
tools.register(ListDirTool(...))
tools.register(GlobTool(...))
tools.register(GrepTool(...))
```

有条件时再注册：

- `ExecTool`
- `WebSearchTool`
- `WebFetchTool`

但它不会注册 `message` 和 `spawn`，这是有意为之。

原因在源码注释里写得很清楚：

> 避免后台链路再次递归发消息或再次拉起子 Agent。

### 13.2 子 Agent 结果怎么回到主链路

子 Agent 完成后不会直接写 session，也不会直接去改主 Agent 的 messages。

它走的是：

```text
SubagentManager
  -> 构造一条 system 通道的 InboundMessage
  -> publish_inbound()
  -> 主 Agent 再按 system 消息路径统一处理
```

相关代码：

- [SubagentManager._announce_result](../elebot/agent/subagent.py#L197)
- [system 消息分支](../elebot/agent/loop.py#L670)

也就是说，后台结果注入没有新造一套旁路，而是复用了主链路。

### 13.3 `/stop` 为什么能取消子 Agent

因为 `SubagentManager` 自己维护了：

- `_running_tasks`
- `_session_tasks`

并提供：

- [SubagentManager.cancel_by_session](../elebot/agent/subagent.py#L266)

所以主链路的 `/stop` 不只是取消主任务，也能顺便取消同会话下的后台子任务。

---

## 14. 相关文档跳转

如果你继续顺着 Agent 读，建议配合这些文档：

- [文档总览](../README.md)
- [Tools 模块文档](./tools.md)
- [Session 模块文档](./session.md)
- [Providers 模块文档](./providers.md)
- [Command 模块文档](./command.md)
- [Bus 模块文档](./bus.md)
- [CLI 模块文档](./cli.md)
- [Facade 模块文档](./facade.md)
- [Agent 测试文档](../test/agent.md)

---

## 最后再压缩成一句话

你读完整个 `agent` 目录后，应该建立起这样一个判断：

```text
AgentLoop 负责编排整个运行时，
ContextBuilder 负责告诉模型“现在有什么上下文”，
AgentRunner 负责把“模型回复”和“工具执行”闭成一条链，
Memory / Skills / Subagent 则分别负责长期记忆、能力扩展和后台任务。
```

如果你以后要继续追代码，最值得反复看的 5 个入口是：

- [AgentLoop.__init__](../elebot/agent/loop.py#L155)
- [AgentLoop._process_message_result](../elebot/agent/loop.py#L660)
- [AgentLoop._run_agent_loop](../elebot/agent/loop.py#L364)
- [ContextBuilder.build_messages](../elebot/agent/context.py#L135)
- [AgentRunner.run](../elebot/agent/runner.py#L183)
