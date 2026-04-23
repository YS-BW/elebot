# Agent 模块教程

## 文档索引

- [agent/loop.py](../../elebot/agent/loop.py)
- [agent/context.py](../../elebot/agent/context.py)
- [agent/runner.py](../../elebot/agent/runner.py)
- [agent/hook.py](../../elebot/agent/hook.py)
- [agent/memory.py](../../elebot/agent/memory.py)
- [agent/autocompact.py](../../elebot/agent/autocompact.py)
- [agent/skills.py](../../elebot/agent/skills.py)
- [agent/subagent.py](../../elebot/agent/subagent.py)
- [facade.py](../../elebot/facade.py)
- [cli/commands.py](../../elebot/cli/commands.py)
- [bus/queue.py](../../elebot/bus/queue.py)

---

## Agent 运行流程

整体链路可以先记成这一句：

```text
用户消息 -> Bus -> AgentLoop -> _dispatch -> _process_message_result -> AgentRunner.run -> LLM -> 工具执行 -> 响应
```

如果拆成阶段，当前主链路基本是：

```text
InboundMessage
    ↓
AgentLoop.run()
    ↓
AgentLoop._dispatch()
    ↓
AutoCompact.prepare_session()
    ↓
ContextBuilder.build_messages()
    ↓
AgentLoop._run_agent_loop()
    ↓
AgentRunner.run()
    ↓
LLM / tool_calls / tool_results
    ↓
AgentLoop._save_turn()
    ↓
OutboundMessage
```

---

## 1. 入口：AgentLoop.run()

文件索引：

- [loop.py](../../elebot/agent/loop.py)

实现位置：

- `elebot/agent/loop.py:455-520`

示例代码：

```python
async def run(self) -> None:
    # 标记主循环进入运行态
    self._running = True

    # 先连接 MCP，后续每条消息就可以直接复用
    await self._connect_mcp()
    logger.info("Agent loop started")

    while self._running:
        try:
            # 从消息总线拉取一条入站消息
            msg = await asyncio.wait_for(
                self.bus.consume_inbound(),
                timeout=1.0,
            )
        except asyncio.TimeoutError:
            # 没有新消息时顺手检查是否有会话已经空闲过久
            self.auto_compact.check_expired(self._schedule_background)
            continue

        raw = msg.content.strip()

        # 优先命令先处理，不进入正常模型链路
        if self.commands.is_priority(raw):
            ctx = CommandContext(
                msg=msg,
                session=None,
                key=msg.session_key,
                raw=raw,
                loop=self,
            )
            result = await self.commands.dispatch_priority(ctx)
            if result:
                await self.bus.publish_outbound(result)
            continue

        # 根据统一会话模式等规则计算真实 session key
        effective_key = self._effective_session_key(msg)

        # 同会话已有活跃任务时，新消息先进待注入队列
        if effective_key in self._pending_queues:
            self._pending_queues[effective_key].put_nowait(pending_msg)
            continue

        # 为本条消息创建一个异步任务
        task = asyncio.create_task(self._dispatch(msg))
        self._active_tasks.setdefault(effective_key, []).append(task)
```

代码讲解：

- `run()` 是整个 Agent 的常驻入口，它持续从 `MessageBus` 消费 `InboundMessage`。
- `_connect_mcp()` 只在启动时处理一次，后续消息直接复用已有连接。
- 如果 1 秒内没有拿到消息，就不会空转等待，而是顺带执行一次空闲会话检查。
- `self.commands.is_priority(raw)` 这层专门用来拦截 `/stop`、`/restart` 一类高优先级命令。
- `effective_key` 不是简单等于 `msg.session_key`，它还会受统一会话模式等规则影响。
- `_pending_queues` 表示某个会话已经有主任务在运行，新消息先排队，不会直接起第二条竞争任务。
- 真正处理消息的任务由 `_dispatch()` 负责，`run()` 自己只做总线消费和调度。

---

## 2. 消息分发：_dispatch()

文件索引：

- [loop.py](../../elebot/agent/loop.py)

实现位置：

- `elebot/agent/loop.py:522-623`

示例代码：

```python
async def _dispatch(self, msg: InboundMessage) -> None:
    # 先把消息映射到真实会话键
    session_key = self._effective_session_key(msg)
    if session_key != msg.session_key:
        msg = dataclasses.replace(msg, session_key_override=session_key)

    # 每个会话各自有锁，保证同会话串行
    lock = self._session_locks.setdefault(session_key, asyncio.Lock())
    gate = self._concurrency_gate or nullcontext()

    # 为当前会话注册待注入队列
    pending = asyncio.Queue(maxsize=20)
    self._pending_queues[session_key] = pending

    try:
        async with lock, gate:
            response = await self._process_message(
                msg,
                on_stream=on_stream,
                on_stream_end=on_stream_end,
                pending_queue=pending,
            )

            # 把最终回复重新发布到出站总线
            if response is not None:
                await self.bus.publish_outbound(response)
    finally:
        # 如果本轮异常退出，把残留待注入消息重新塞回总线
        queue = self._pending_queues.pop(session_key, None)
        if queue is not None:
            while True:
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                await self.bus.publish_inbound(item)
```

代码讲解：

- `_dispatch()` 是“每条消息真正开始处理”的地方。
- `session_key` 会被重新计算一次，确保后续锁、队列、会话读写都落在正确的会话上。
- `_session_locks` 保证同一个会话内部严格串行，不会同时改同一份 history。
- `_concurrency_gate` 是跨会话的并发闸门，它控制系统整体并发上限。
- `_pending_queues` 用来临时存放同会话的后续追问，供当前主任务在内部继续吸收。
- 真正的消息处理会继续进入 `_process_message()`，`_dispatch()` 自己主要负责并发和收尾。
- `finally` 里的重新投递逻辑用于兜底，避免待注入消息在异常路径里丢失。

---

## 3. 单条消息处理：_process_message_result()

文件索引：

- [loop.py](../../elebot/agent/loop.py)
- [context.py](../../elebot/agent/context.py)
- [session.md](session.md)

实现位置：

- `elebot/agent/loop.py:660-821`

示例代码：

```python
async def _process_message_result(
    self,
    msg: InboundMessage,
    session_key: str | None = None,
    ...,
) -> DirectProcessResult:
    # 先获取或创建当前会话
    key = session_key or msg.session_key
    session = self.sessions.get_or_create(key)

    # 如有上轮未完成的 checkpoint，先恢复到会话历史
    if self._restore_runtime_checkpoint(session):
        self.sessions.save(session)

    # 处理自动压缩，并取出可注入的恢复摘要
    session, pending = self.auto_compact.prepare_session(session, key)

    # 先尝试处理普通斜杠命令
    raw = msg.content.strip()
    ctx = CommandContext(msg=msg, session=session, key=key, raw=raw, loop=self)
    if result := await self.commands.dispatch(ctx):
        return DirectProcessResult(
            outbound=result,
            final_content=result.content,
            stop_reason="command",
            session_key=key,
        )

    # 视情况做一次 token 压缩
    await self.consolidator.maybe_consolidate_by_tokens(session)

    # 读取历史并构造完整消息
    history = session.get_history(max_messages=0)
    initial_messages = self.context.build_messages(
        history=history,
        current_message=msg.content,
        session_summary=pending,
        media=msg.media if msg.media else None,
        channel=msg.channel,
        chat_id=msg.chat_id,
    )

    # 进入真正的 agent 循环
    final_content, tools_used, all_msgs, stop_reason, had_injections = \
        await self._run_agent_loop(initial_messages, ...)

    # 保存新增消息到 session
    self._save_turn(session, all_msgs, 1 + len(history))
    self._clear_runtime_checkpoint(session)
    self.sessions.save(session)
```

代码讲解：

- `_process_message_result()` 是单条消息进入模型链路前的总收口入口。
- 它会先拿到当前会话，并尝试把上轮未完成的 checkpoint 恢复进历史。
- `auto_compact.prepare_session()` 会决定是否重载会话，并返回一段一次性 summary。
- 普通斜杠命令会在进入模型前被拦截处理，所以不是所有输入都会走 LLM。
- `maybe_consolidate_by_tokens()` 用来在上下文过长时先做历史压缩。
- `history + current_message + session_summary + media` 会统一交给 `ContextBuilder.build_messages()`。
- `_run_agent_loop()` 返回的是整轮执行结果，不只是最终文本，还包含工具和消息轨迹。
- `_save_turn()` 最后只保存本轮新增部分，不会重复写入旧历史。

---

## 4. AgentRunner.run()：核心循环

文件索引：

- [runner.py](../../elebot/agent/runner.py)
- [hook.py](../../elebot/agent/hook.py)

实现位置：

- `elebot/agent/runner.py:183-480`

示例代码：

```python
async def run(self, spec: AgentRunSpec) -> AgentRunResult:
    # 初始消息通常已经包含 system、history、user
    messages = list(spec.initial_messages)
    final_content = None
    tools_used = []

    for iteration in range(spec.max_iterations):
        # 每次调模型前，都会先对上下文做治理
        messages_for_model = self._drop_orphan_tool_results(messages)
        messages_for_model = self._backfill_missing_tool_results(messages_for_model)
        messages_for_model = self._microcompact(messages_for_model)
        messages_for_model = self._apply_tool_result_budget(spec, messages_for_model)
        messages_for_model = self._snip_history(spec, messages_for_model)

        context = AgentHookContext(iteration=iteration, messages=messages)
        await hook.before_iteration(context)

        # 真正调用模型
        response = await self._request_model(spec, messages_for_model, hook, context)

        # 有工具调用时，先执行工具，再继续下一轮
        if response.has_tool_calls:
            assistant_message = build_assistant_message(...)
            messages.append(assistant_message)
            tools_used.extend(tc.name for tc in response.tool_calls)

            await hook.before_execute_tools(context)
            results, events, fatal_error = await self._execute_tools(
                spec,
                response.tool_calls,
                external_lookup_counts,
            )

            for tool_call, result in zip(response.tool_calls, results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": self._normalize_tool_result(...),
                })

            injections = await self._drain_injections(spec)
            if injections:
                self._append_injected_messages(messages, injections)

            continue

        # 没有工具调用时，进入最终文本收口
        clean = hook.finalize_content(context, response.content)
        final_content = clean
        break
```

代码讲解：

- `messages` 是当前整轮执行中不断增长的消息列表。
- 每轮开始都会先生成一个 `messages_for_model`，这个副本会做协议修补、压缩、截断。
- `hook.before_iteration()`、`hook.before_execute_tools()` 等调用把生命周期事件暴露给外层。
- `_request_model()` 返回的 `response` 里可能只有正文，也可能包含 `tool_calls`。
- 一旦模型发起工具调用，就先把 assistant 的工具请求写进消息链路。
- `_execute_tools()` 会执行工具，并返回结果、事件和致命错误。
- 每条工具结果会以 `role="tool"` 的消息继续追加到 `messages` 里。
- `_drain_injections()` 负责吸收同会话中途插入的新消息。
- 当本轮没有工具调用时，`finalize_content()` 会产出最终对外正文。

---

## 5. 工具执行：_execute_tools()

文件索引：

- [runner.py](../../elebot/agent/runner.py)

实现位置：

- `elebot/agent/runner.py:568-636`

示例代码：

```python
async def _execute_tools(
    self,
    spec: AgentRunSpec,
    tool_calls: list[ToolCallRequest],
    external_lookup_counts: dict[str, int],
) -> tuple[list[Any], list[dict[str, str]], BaseException | None]:
    # 先把工具调用划分成可以并发和必须串行的批次
    batches = self._partition_tool_batches(spec, tool_calls)
    tool_results = []

    for batch in batches:
        if spec.concurrent_tools and len(batch) > 1:
            # 可并发批次直接 gather
            tool_results.extend(await asyncio.gather(*(
                self._run_tool(spec, tool_call, external_lookup_counts)
                for tool_call in batch
            )))
        else:
            # 不安全或需要保序时按顺序执行
            for tool_call in batch:
                tool_results.append(
                    await self._run_tool(spec, tool_call, external_lookup_counts)
                )

    results = []
    events = []
    fatal_error = None
    for result, event, error in tool_results:
        results.append(result)
        events.append(event)
        if error is not None and fatal_error is None:
            fatal_error = error

    return results, events, fatal_error
```

代码讲解：

- `_partition_tool_batches()` 先决定哪些工具可以并发、哪些必须串行。
- `spec.concurrent_tools` 是总开关，不开时所有工具都走顺序执行。
- 并发批次通过 `asyncio.gather()` 一次执行整组工具。
- 串行批次会逐个执行 `_run_tool()`，保持顺序和副作用可控。
- `_run_tool()` 的返回值不是单纯的结果，还包含事件信息和错误对象。
- `results` 用于继续回填到消息链路，`events` 用于记录执行过程，`fatal_error` 用于决定是否终止本轮。

---

## 6. 上下文治理（每次 LLM 调用前）

文件索引：

- [runner.py](../../elebot/agent/runner.py)

实现位置：

- `elebot/agent/runner.py:204-231`
- `elebot/agent/runner.py:727-840`

示例代码：

```python
# 1. 丢弃没有配对 assistant tool_call 的 tool 结果
messages_for_model = self._drop_orphan_tool_results(messages)

# 2. 给缺失的 tool 结果补一条错误消息
messages_for_model = self._backfill_missing_tool_results(messages_for_model)

# 3. 把旧的长工具结果替换成简短摘要
messages_for_model = self._microcompact(messages_for_model)

# 4. 对单条工具结果应用长度预算
messages_for_model = self._apply_tool_result_budget(spec, messages_for_model)

# 5. 按 context window 截断历史
messages_for_model = self._snip_history(spec, messages_for_model)
```

代码讲解：

- `_drop_orphan_tool_results()` 清掉那些没有前置 assistant tool_call 的工具结果。
- `_backfill_missing_tool_results()` 会给缺失结果的工具调用补一条合成错误消息。
- `_microcompact()` 会把旧的长工具结果压成一句短摘要。
- `_apply_tool_result_budget()` 会限制每条工具结果的长度。
- `_snip_history()` 按上下文窗口裁掉较旧消息。
- 这些治理只作用于发给模型的副本，不直接改动持久化历史。

---

## 7. ContextBuilder：构建完整消息

文件索引：

- [context.py](../../elebot/agent/context.py)

实现位置：

- `elebot/agent/context.py:36-200`

示例代码：

```python
def build_system_prompt(self, skill_names=None, channel=None) -> str:
    # 身份模板是 system prompt 的开头
    parts = [self._get_identity(channel=channel)]

    # 启动文件、长期记忆、技能、近期历史按顺序拼接
    bootstrap = self._load_bootstrap_files()
    memory = self.memory.get_memory_context()
    always_skills = self.skills.get_always_skills()
    skills_summary = self.skills.build_skills_summary()
    entries = self.memory.read_unprocessed_history(...)

    return "\n\n---\n\n".join(parts)
```

```python
def build_messages(...):
    runtime_ctx = self._build_runtime_context(...)
    user_content = self._build_user_content(current_message, media)

    # 把运行时上下文和本轮输入合成一条 user 消息
    if isinstance(user_content, str):
        merged = f"{runtime_ctx}\n\n{user_content}"
    else:
        merged = [{"type": "text", "text": runtime_ctx}] + user_content

    messages = [
        {"role": "system", "content": self.build_system_prompt(...)},
        *history,
    ]
    messages.append({"role": current_role, "content": merged})
    return messages
```

代码讲解：

- `build_system_prompt()` 负责把身份、启动文件、记忆、技能和近期历史拼成 system 内容。
- `_build_runtime_context()` 负责构造当前时间、channel、chat_id 这类运行时信息。
- `_build_user_content()` 会把文本和图片统一成 Provider 可接受的内容结构。
- `build_messages()` 最终产出的是完整消息数组，不是单独一条用户消息。
- 当前实现会把 runtime context 和本轮输入合并到同一条 user 消息里。

---

## 8. Session 保存与 Checkpoint 恢复

文件索引：

- [loop.py](../../elebot/agent/loop.py)
- [session.md](session.md)

实现位置：

- `elebot/agent/loop.py:842-1009`

示例代码：

```python
def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
    for m in messages[skip:]:
        entry = dict(m)

        # 空 assistant 消息不保存
        if role == "assistant" and not content and not entry.get("tool_calls"):
            continue

        # tool 结果过长时先截断
        if role == "tool" and isinstance(content, str):
            entry["content"] = truncate_text_fn(content, self.max_tool_result_chars)

        # user 消息里的 runtime context 会在落盘前剥掉
        if role == "user" and isinstance(content, str):
            ...

        session.messages.append(entry)
```

```python
def _restore_runtime_checkpoint(self, session: Session) -> bool:
    checkpoint = session.metadata.get(self._RUNTIME_CHECKPOINT_KEY)

    # 恢复 assistant 的 tool_calls 消息
    restored_messages.append(assistant_message)

    # 恢复已经完成的 tool 结果
    restored_messages.extend(completed_tool_results)

    # 给未完成工具补一条中断错误
    restored_messages.append({
        "role": "tool",
        "tool_call_id": tool_id,
        "name": name,
        "content": "Error: Task interrupted before this tool finished.",
    })
```

代码讲解：

- `_save_turn()` 不会把整轮消息原样全部落盘，而是只保存当前新增部分。
- 用户消息里的 runtime context 只用于本轮提示词构造，落盘前会被去掉。
- 工具结果如果过长，会先裁剪再写入会话历史。
- `_set_runtime_checkpoint()` 会把运行中的工具阶段状态写进 `session.metadata`。
- `_restore_runtime_checkpoint()` 会把中断前的 tool_call、已完成工具结果和未完成工具错误一起补回历史。
- `_clear_runtime_checkpoint()` 会在本轮收尾时把 checkpoint 清掉。

---

## 9. Hook、Memory、AutoCompact、Skills、Subagent

这一组模块不是主循环本身，但都会影响主链路行为。

### 9.1 Hook

文件索引：

- [hook.py](../../elebot/agent/hook.py)

示例代码：

```python
class AgentHook:
    async def before_iteration(self, context): ...
    async def on_stream(self, context, delta): ...
    async def on_stream_end(self, context, *, resuming): ...
    async def before_execute_tools(self, context): ...
    async def after_iteration(self, context): ...
    def finalize_content(self, context, content): ...
```

代码讲解：

- `Hook` 定义了主循环暴露给外层的生命周期接口。
- `_LoopHook` 是主链路内部使用的 hook，负责流式输出、工具提示和内容清洗。
- `CompositeHook` 会把多组 hook 串成一条执行管线。

### 9.2 Memory / Consolidator / Dream

文件索引：

- [memory.py](../../elebot/agent/memory.py)

示例代码：

```python
estimated, source = self.estimate_session_prompt_tokens(session)
if estimated < budget:
    return

boundary = self.pick_consolidation_boundary(session, max(1, estimated - target))
chunk = session.messages[session.last_consolidated:end_idx]
if not await self.archive(chunk):
    return
```

代码讲解：

- `MemoryStore` 负责管理 `MEMORY.md`、`SOUL.md`、`USER.md` 和历史文件。
- `Consolidator` 负责在上下文过长时把旧消息压成摘要。
- `Dream` 负责更长期的记忆整理和文件更新。

### 9.3 AutoCompact

文件索引：

- [autocompact.py](../../elebot/agent/autocompact.py)

示例代码：

```python
def check_expired(self, schedule_background):
    for info in self.sessions.list_sessions():
        if key and key not in self._archiving and self._is_expired(info.get("updated_at")):
            self._archiving.add(key)
            schedule_background(self._archive(key))
```

代码讲解：

- `AutoCompact` 按空闲时间检查会话，而不是按 token 大小。
- 过期会话会进入后台归档流程。
- `prepare_session()` 会在新消息进入前决定是否重载会话，并返回一次性 summary。

### 9.4 Skills

文件索引：

- [skills.py](../../elebot/agent/skills.py)

示例代码：

```python
skills = self._skill_entries_from_dir(self.workspace_skills, "workspace")
workspace_names = {entry["name"] for entry in skills}
skills.extend(
    self._skill_entries_from_dir(
        self.builtin_skills,
        "builtin",
        skip_names=workspace_names,
    )
)
```

代码讲解：

- 技能来源分为工作区技能和内置技能。
- 工作区同名技能会覆盖内置技能。
- `build_skills_summary()` 负责生成技能摘要，`get_always_skills()` 负责找出总是自动注入的技能。

### 9.5 Subagent

文件索引：

- [subagent.py](../../elebot/agent/subagent.py)

示例代码：

```python
async def spawn(...):
    bg_task = asyncio.create_task(
        self._run_subagent(task_id, task, display_label, origin)
    )
    self._running_tasks[task_id] = bg_task
```

```python
msg = InboundMessage(
    channel="system",
    sender_id="subagent",
    chat_id=f"{origin['channel']}:{origin['chat_id']}",
    content=announce_content,
)
await self.bus.publish_inbound(msg)
```

代码讲解：

- `SubagentManager` 负责后台子任务的创建、跟踪和回流。
- 子 Agent 运行结束后，不直接改主会话，而是重新发一条 `system` 消息回到主链路。
- `cancel_by_session()` 可以取消某个会话下的后台子任务。

---

## 10. 关键组件关系

```text
AgentLoop
├── context: ContextBuilder       # 构建 prompt 和 messages
├── sessions: SessionManager      # 会话读写
├── tools: ToolRegistry           # 工具注册表
├── runner: AgentRunner           # 模型与工具循环执行器
├── consolidator: Consolidator    # token 压力下的历史摘要
├── auto_compact: AutoCompact     # 空闲会话自动压缩
├── dream: Dream                  # 长期记忆整理
└── subagents: SubagentManager    # 后台子 Agent 管理
```

---

## 11. 消息流程图

```text
用户输入
    ↓
InboundMessage -> AgentLoop._dispatch()
    ↓
auto_compact.prepare_session() -> 检查是否需要压缩
    ↓
context.build_messages() -> 构建完整消息列表
    ↓
AgentRunner.run() -> 循环直到最终响应或达到最大迭代
    ↓
┌─────────────────────────────────────────┐
│  while iteration < max_iterations:      │
│    1. 上下文治理                        │
│    2. 调用 LLM                          │
│    3. 有 tool_calls -> 执行工具 -> 继续 │
│    4. 无 tool_calls -> 返回响应         │
└─────────────────────────────────────────┘
    ↓
_save_turn() -> 保存到 session
    ↓
OutboundMessage -> bus.publish_outbound()
```
