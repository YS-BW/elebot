# CLI 与运行方式

这篇文档只讲 `elebot` 命令现在真实支持的运行方式，以及每种方式实际走到哪条代码链路。

相关源码：

- [elebot/cli/commands.py](../elebot/cli/commands.py#L313-L414)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L180)
- [elebot/facade.py](../elebot/facade.py#L23-L121)

## 1. `elebot agent` 是当前主入口

当前主入口在 [elebot/cli/commands.py](../elebot/cli/commands.py#L313-L414)。

入口代码：

```python
@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show elebot runtime logs during chat"),
):
```

先记住这几个参数：

- `--message/-m`：单次执行模式
- `--session/-s`：指定 session key
- `--workspace/-w`：覆盖工作区目录
- `--config/-c`：指定配置文件
- `--logs`：显示运行日志

## 2. 实际有 3 种运行方式

### 2.1 交互终端模式

执行：

```bash
elebot agent
```

对应代码在 [elebot/cli/commands.py](../elebot/cli/commands.py#L405-L414)：

```python
asyncio.run(
    run_interactive_loop(
        agent_loop=agent_loop,
        bus=bus,
        session_id=session_id,
        markdown=markdown,
    )
)
```

这条链路会进入 [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L180) 的 `run_interactive_loop()`。

### 2.2 单次命令模式

执行：

```bash
elebot agent -m "你好"
```

对应代码在 [elebot/cli/commands.py](../elebot/cli/commands.py#L378-L405)：

```python
response = await agent_loop.process_direct(
    message,
    session_id,
    on_progress=_cli_progress,
    on_stream=renderer.on_delta,
    on_stream_end=renderer.on_end,
)
```

这条链路不会启动长期消息循环，而是直接单次执行。

### 2.3 程序化调用模式

入口在 [elebot/facade.py](../elebot/facade.py#L34-L121)：

```python
bot = Elebot.from_config()
result = await bot.run("你好", session_key="sdk:default")
```

这条链路适合你以后自己包成：

- Web API
- 桌面应用后端
- 测试脚本

## 3. 交互模式里到底发生了什么

看 [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L180)：

```python
bus_task = asyncio.create_task(agent_loop.run())
outbound_task = asyncio.create_task(_consume_outbound())
```

这两行说明：

- 一个后台协程负责跑 `AgentLoop.run()`
- 一个后台协程负责收 `bus` 的输出并渲染到终端

用户输入时：

```python
await bus.publish_inbound(
    InboundMessage(
        channel=cli_channel,
        sender_id="user",
        chat_id=cli_chat_id,
        content=user_input,
        metadata={"_wants_stream": True},
    )
)
```

所以交互模式不是“CLI 直接调 agent 函数”，而是：

```text
终端输入
  ↓
publish_inbound()
  ↓
AgentLoop.run()
  ↓
publish_outbound()
  ↓
终端渲染
```

## 4. `elebot agent` 放着不动时是不是 loop 还在跑

是的，但要区分两种情况。

### 4.1 交互模式

执行：

```bash
elebot agent
```

这时 `AgentLoop.run()` 已经启动，只是可能处于等待消息状态。

对应代码在 [elebot/agent/loop.py](../elebot/agent/loop.py#L430-L448)：

```python
while self._running:
    try:
        msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
    except asyncio.TimeoutError:
        self.auto_compact.check_expired(self._schedule_background)
        continue
```

这意味着：

- loop 在运行
- 但没有消息时只是 timeout 等待
- 同时会在等待周期里检查空闲压缩

### 4.2 单次模式

执行：

```bash
elebot agent -m "你好"
```

这条链路调用的是 `process_direct(...)`，不是长期 `run()` 主循环。

## 5. `--session`、`--workspace`、当前目录分别是什么关系

### 5.1 `--session`

只影响会话键，不影响工作区。

例如：

```bash
elebot agent --session cli:alt-test
```

会把短期消息写进另一个 `sessions/*.jsonl` 文件。

### 5.2 `--workspace`

影响整套运行目录。

例如：

```bash
elebot agent --workspace ~/my-elebot-workspace
```

这会切换：

- `sessions/`
- `memory/`
- `USER.md`
- `SOUL.md`
- `AGENTS.md`

### 5.3 当前 shell 目录

当前在哪个目录执行命令，不会自动切换 workspace。

工作区路径来自：

- `--workspace`
- 配置文件 `agents.defaults.workspace`
- 默认值 `~/.elebot/workspace`

对应代码：

- [elebot/config/paths.py](../elebot/config/paths.py#L11-L50)
- [elebot/config/schema.py](../elebot/config/schema.py#L28-L50)

## 6. 单次调用和交互模式的最大区别

### 交互模式

- 有长期 `run()` loop
- CLI 和 agent 通过 bus 双向通信
- 空闲时会周期检查过期 session

### 单次模式

- 一次请求，一次返回
- 直接 `process_direct(...)`
- 不依赖长期 `run()` loop

## 7. 读完这篇后，下一步看什么

推荐继续看：

- [Bus 与消息流转](./bus-and-events.md)
- [Session 设计](./session-design.md)
- [Workspace 运行目录](./workspace-design.md)
