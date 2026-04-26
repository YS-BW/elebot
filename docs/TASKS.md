# TASKS

这份文档只讲 EleBot 当前已经落地的定时任务实现，不讨论未来的系统级 `cron` / `launchd` / Windows Task Scheduler。

当前事实先说清楚：

- 任务存储在 `~/.elebot/tasks/tasks.json`
- 调度器不是系统服务，而是 `elebot agent` 进程内的后台轮询
- 只有 `elebot agent` 运行时，任务才会触发
- 任务触发后不会直接调用 runner，而是先转成一条标准 `InboundMessage` 投递到 `Bus`

你可以先把整条链路记成下面这一行：

```text
tasks.json → TaskService.tick() → scheduler.collect_due_tasks() → build_task_inbound_message() → Bus → AgentLoop → 正常对话主链路
```

## 目录

1. [入口](#入口)
2. [任务长什么样](#任务长什么样)
3. [任务文件存在哪里](#任务文件存在哪里)
4. [系统如何定时检查](#系统如何定时检查)
5. [系统如何判断到期](#系统如何判断到期)
6. [到期后如何发回主链路](#到期后如何发回主链路)
7. [AgentLoop 如何处理触发消息](#agentloop-如何处理触发消息)
8. [任务状态如何更新](#任务状态如何更新)
9. [当前支持的命令](#当前支持的命令)
10. [当前限制](#当前限制)

## 入口

任务系统是在 `AgentLoop` 初始化时挂进去的，不是按需临时创建。

源码位置：

- [loop.py#L233-L237](../elebot/agent/loop.py#L233-L237)

核心代码：

```python
self.task_service = TaskService(
    self.bus,
    poll_interval_seconds=10,
    default_timezone=timezone or "Asia/Shanghai",
)
```

这段代码说明三件事：

- 任务服务和 `Bus` 绑定在一起
- 默认每 10 秒轮询一次
- 没显式指定时区时，默认用 `Asia/Shanghai`

所以 EleBot 的任务系统本质上是 Agent 主循环的一部分，不是独立守护进程。

## 任务长什么样

任务的数据模型在 [models.py#L9-L69](../elebot/tasks/models.py#L9-L69)。

核心代码：

```python
@dataclass(slots=True)
class ScheduledTask:
    task_id: str
    session_key: str
    content: str
    schedule_type: str
    run_at: str | None
    interval_seconds: int | None
    daily_time: str | None
    timezone: str | None
    enabled: bool
    created_at: str
    updated_at: str
    last_run_at: str | None
    next_run_at: str | None
    source: str
    run_count: int = 0
    last_status: str | None = None
    last_error: str | None = None
    last_finished_at: str | None = None
```

字段可以按四组理解：

**身份字段**

- `task_id`：任务唯一标识
- `session_key`：任务绑定的会话，例如 `cli:direct`
- `source`：任务来源，目前默认是 `agent`

**调度字段**

- `schedule_type`：当前支持 `once` / `interval` / `daily`
- `run_at`：单次任务的触发时间
- `interval_seconds`：间隔任务的秒数
- `daily_time`：每天触发的时刻，例如 `14:30`
- `timezone`：任务自己的时区
- `next_run_at`：下一次真正用于判断是否到期的时间

**运行状态字段**

- `enabled`：是否启用
- `run_count`：已经触发了几次
- `last_status`：最近状态，例如 `triggered`、`running`、`ok`、`error`
- `last_error`：最近一次错误文本
- `last_run_at`：最近一次进入触发阶段的时间
- `last_finished_at`：最近一次执行完成时间

**审计字段**

- `created_at`
- `updated_at`

当前调度真正依赖的是 `enabled + next_run_at`，不是每次都重新从 `run_at` 推导。

## 任务文件存在哪里

任务读写由 [store.py#L13-L146](../elebot/tasks/store.py#L13-L146) 负责。

入口代码：

```python
self.path = path or get_tasks_store_path()
```

默认文件路径来自 `get_tasks_store_path()`，最终是：

```text
~/.elebot/tasks/tasks.json
```

保存时是整个任务列表一次性写回：

```python
serialized = [task.to_dict() for task in tasks]
self.path.write_text(
    json.dumps(serialized, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

所以当前实现不是数据库，也不是一任务一文件，而是一份 JSON 文件保存全部任务。

## 系统如何定时检查

后台轮询逻辑在 [service.py#L16-L153](../elebot/tasks/service.py#L16-L153)。

最核心的循环是：

```python
async def _run(self) -> None:
    while self._running:
        await self.tick()
        await asyncio.sleep(self.poll_interval_seconds)
```

你可以按下面这个流程看：

```text
TaskService.start()
  ↓
create_task(self._run())
  ↓
每轮执行 tick()
  ↓
sleep(10s)
```

真正做事的是 `tick()`：

```python
now = datetime.now().astimezone()
tasks = self.store.load_all()
due_tasks = collect_due_tasks(tasks, now, default_timezone=self.default_timezone)
```

这表示：

- 每轮先拿当前时间
- 再把全部任务读出来
- 然后筛选当前到期的任务

## 系统如何判断到期

判断逻辑在 [scheduler.py#L48-L130](../elebot/tasks/scheduler.py#L48-L130)。

最关键的判断是：

```python
def is_due(task, now, *, default_timezone=None) -> bool:
    if not task.enabled or not task.next_run_at:
        return False
    due_at = _parse_iso_datetime(task.next_run_at, task, default_timezone)
    return due_at is not None and due_at <= now
```

这里的意思很直接：

- 任务没启用，不触发
- 没有 `next_run_at`，不触发
- `next_run_at <= now` 才算到期

不同类型的下一次触发时间是 `compute_next_run()` 算出来的：

```python
if task.schedule_type == "once":
    return None

if task.schedule_type == "interval":
    ...

if task.schedule_type == "daily":
    ...
```

三种类型可以这样理解：

- `once`：只触发一次，之后没有下一次
- `interval`：按秒数持续往后推
- `daily`：每天固定时刻触发

## 到期后如何发回主链路

到期后不会直接调用模型，而是先转成标准 `InboundMessage`。

转换逻辑在 [trigger.py#L9-L42](../elebot/tasks/trigger.py#L9-L42)。

核心代码：

```python
return InboundMessage(
    channel="system",
    sender_id="scheduler",
    chat_id=chat_id or "scheduled",
    content=content,
    session_key_override=task.session_key,
    metadata={
        "task_id": task.task_id,
        "schedule_type": task.schedule_type,
        "scheduled_trigger": True,
        "original_channel": channel or "",
        "task_content": task.content,
        "task_source": task.source,
        "task_run_count": task.run_count + 1,
    },
)
```

这段代码要重点看四件事：

**1. 触发来源不是用户**

```python
channel="system"
sender_id="scheduler"
```

这明确告诉主链路，这是一条系统触发消息。

**2. 任务会绑回原会话**

```python
session_key_override=task.session_key
```

这表示任务不是新开会话，而是回到创建任务时所在的 session。

**3. 消息正文是可读文本**

当前正文格式大概是：

```text
系统定时任务触发：
- 任务 ID：...
- 任务类型：...
- 任务内容：...
- 第 N 次触发
这是一次自动任务触发，不是用户实时输入。
```

**4. 触发元数据会继续往下传**

后面 `AgentLoop` 就靠 `metadata["scheduled_trigger"]` 判断这是不是任务触发。

## AgentLoop 如何处理触发消息

任务消息进入 `Bus` 后，接下来就和普通入站消息一样由 `AgentLoop.run()` 消费。

相关代码在：

- [loop.py#L500-L545](../elebot/agent/loop.py#L500-L545)
- [loop.py#L753-L806](../elebot/agent/loop.py#L753-L806)

### 1. 忙碌会话会先延后

如果原会话正在忙，这条任务不会立刻并发插进去：

```python
if msg.metadata.get("scheduled_trigger") and effective_key in self._pending_queues:
    self.task_service.defer(msg.metadata.get("task_id"), reason="session_busy")
    continue
```

这里的行为是：

- 发现是任务触发
- 发现这个 session 已经在处理中
- 不直接执行
- 把任务状态记成 `deferred:session_busy`

所以当前实现已经避免了“任务突然打断正在进行的对话”。

### 2. 真正执行前标记为 running

```python
if msg.metadata.get("scheduled_trigger"):
    self.task_service.mark_running(msg.metadata.get("task_id"))
```

这一步发生在正式构造上下文并进入 `_run_agent_loop()` 之前。

### 3. 之后完全复用主链路

后续调用没有单独分支，直接走标准流程：

```python
history = session.get_history(max_messages=0)
initial_messages = self.context.build_messages(...)
final_content, tools_used, all_msgs, stop_reason, had_injections = await self._run_agent_loop(...)
```

这表示任务触发后的处理方式和普通消息是同一套：

- 取 session 历史
- 组装 context
- 调用 provider
- 执行工具
- 保存会话

## 任务状态如何更新

状态更新分成三个时刻。

### 1. 刚到期，准备投递

位置在 [service.py#L90-L112](../elebot/tasks/service.py#L90-L112)：

```python
task.last_run_at = now.isoformat()
task.updated_at = timestamp()
task.run_count += 1
task.last_status = "triggered"
task.last_error = None
```

这一层说明：

- 已经进入“触发阶段”
- 运行次数先加一
- 但还没真正执行完

### 2. 主链路开始处理

位置在 [service.py#L134-L142](../elebot/tasks/service.py#L134-L142)：

```python
self.store.update_status(
    str(task_id),
    last_status="running",
    last_error=None,
)
```

### 3. 主链路处理结束

位置在 [loop.py#L802-L806](../elebot/agent/loop.py#L802-L806) 和 [service.py#L144-L153](../elebot/tasks/service.py#L144-L153)：

```python
status = "ok" if stop_reason != "error" else "error"
error_text = final_content if stop_reason == "error" else None
self.task_service.mark_finished(task_id, status=status, error=error_text)
```

最终写回：

```python
self.store.update_status(
    str(task_id),
    last_status=status,
    last_error=error,
    last_finished_at=timestamp(),
)
```

所以你在 `/task` 里看到的 `status`，本质上来自这些字段。

## 当前支持的命令

命令入口在 [builtin.py#L27-L29](../elebot/command/builtin.py#L27-L29) 和 [builtin.py#L375-L443](../elebot/command/builtin.py#L375-L443)。

当前对外暴露的任务命令只有三条：

```text
/task
/task list
/task remove <task_id>
```

行为分别是：

- `/task`：只看当前会话的任务
- `/task list`：看全部任务
- `/task remove <task_id>`：删除一个任务

当前没有：

- `/task add`
- `/task enable`
- `/task disable`
- `/task update`

任务主创建入口仍然是自然语言对话，由 agent 通过工具去创建。

## 当前限制

这部分只写当前真实限制。

### 1. 必须保持 `elebot agent` 进程在线

当前没有系统级调度器。  
`elebot agent` 关掉以后，`TaskService` 也就不存在了，任务不会触发。

### 2. 不是绝对准点

当前是每 10 秒轮询一次，不是精确闹钟。

所以真实触发时间更接近：

```text
到点时间 ≤ 实际触发时间 < 到点时间 + 一个轮询周期
```

### 3. 忙碌会话会延后

如果目标 session 正在处理消息，任务不会强插，而是记成：

```text
deferred:session_busy
```

### 4. 当前只有三种调度类型

- `once`
- `interval`
- `daily`

还不支持 cron 表达式。

### 5. 任务触发后是“系统消息”，不是 UI 通知

当前实现是把任务送回 agent 主链路，不是弹系统通知，也不是桌面提醒框。

如果以后要做桌面通知，那是上层 UI / desktop runtime 的事情，不是当前 `tasks` 模块本身负责的。
