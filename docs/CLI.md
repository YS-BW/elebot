# CLI 与运行方式

这篇文档只讲 `elebot` 命令现在真实支持的运行方式，以及 CLI 现在怎样通过 `runtime` 进入主链路。

相关源码：

- [elebot/cli/commands.py](../elebot/cli/commands.py#L175-L351)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L23-L220)
- [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L10-L106)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L200)
- [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L82)

## 1. `elebot agent` 现在先做 runtime 装配

当前主入口在 [elebot/cli/commands.py](../elebot/cli/commands.py#L276-L351)。

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

- `--message/-m`
  - 单次执行模式
- `--session/-s`
  - 指定会话 key
- `--workspace/-w`
  - 覆盖工作区目录
- `--config/-c`
  - 指定配置文件
- `--logs`
  - 显示运行日志

但现在更重要的是这条启动顺序：

```python
config = _load_runtime_config(config, workspace)
sync_workspace_templates(config.workspace_path)
runtime = _make_runtime(config)
```

也就是说 CLI 不再自己直接拼 `MessageBus + provider + AgentLoop`，而是先把这些都交给 `runtime`。

## 2. CLI 现在实际有 2 种运行方式

### 2.1 交互终端模式

执行：

```bash
elebot agent
```

对应代码在 [elebot/cli/commands.py](../elebot/cli/commands.py#L350-L351)：

```python
asyncio.run(runtime.run_interactive(session_id=session_id, markdown=markdown))
```

这条链路的入口已经不是 `run_interactive_loop(...)` 直接拿 `agent_loop` 和 `bus` 来跑，而是先经过 `runtime.run_interactive(...)`。

### 2.2 单次命令模式

执行：

```bash
elebot agent -m "你好"
```

对应代码在 [elebot/cli/commands.py](../elebot/cli/commands.py#L322-L349)：

```python
response = await runtime.run_once(
    message,
    session_id=session_id,
    on_progress=_cli_progress,
    on_stream=renderer.on_delta,
    on_stream_end=renderer.on_end,
)
await runtime.close()
```

这条链路不会进入长期 `run()` 主循环，而是通过 runtime 复用 `AgentLoop.process_direct(...)`。

## 3. CLI 现在把哪些事情交给 runtime

runtime 装配逻辑在 [elebot/cli/commands.py](../elebot/cli/commands.py#L229-L246)：

```python
return ElebotRuntime.from_config(
    config,
    provider_builder=_make_provider,
    bus_factory=MessageBus,
    agent_loop_factory=AgentLoop,
)
```

CLI 现在只保留：

- 读取命令参数
- 处理配置路径和工作区覆盖
- 同步工作区模板
- 控制终端渲染
- 调用 runtime

其中 provider 的真实装配逻辑已经收口到 [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L82) 的 `build_provider(config)`。  
CLI 自己的 `_make_provider()` 只负责把 `ValueError` 转成终端里的可读错误提示。

主链路真正的依赖装配已经交给 `ElebotRuntime.from_config(...)`。

## 4. 如果以后接 Web / desktop，该复用哪里

当前仓库已经没有 `facade` 这层程序化包装。

如果以后要接：

- Web
- desktop
- channel

都应该复用 [elebot/runtime/app.py](../elebot/runtime/app.py#L38-L90) 里的 `ElebotRuntime.from_config(...)` 这条链路，让 runtime 继续统一装配：

- `MessageBus`
- provider
- `AgentLoop`

重点不是“补一个新 SDK 包装层”，而是避免重新复制一套平行的运行时装配逻辑。

## 5. 交互模式里到底发生了什么

现在交互模式分成两层理解会更清楚。

### 5.1 CLI 命令层

CLI 只做这一步：

```python
await runtime.run_interactive(session_id=session_id, markdown=markdown)
```

### 5.2 runtime 层

在 [elebot/runtime/app.py](../elebot/runtime/app.py#L145-L176)：

```python
await run_interactive_loop(
    agent_loop=self.agent_loop,
    bus=self.bus,
    session_id=session_id,
    markdown=markdown,
    renderer_factory=renderer_factory,
    manage_agent_loop=False,
)
```

这里最关键的是 `manage_agent_loop=False`。

它表示：

- `AgentLoop.run()` 的长期生命周期已经交给 runtime
- 交互层只负责：
  - 读取用户输入
  - 发布 `InboundMessage`
  - 消费 `OutboundMessage`
  - 渲染回复

### 5.3 交互层真正做了什么

在 [elebot/cli/interactive.py](../elebot/cli/interactive.py#L158-L165)：

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

所以交互模式真正的消息链路是：

```text
终端输入
  ↓
CLI publish_inbound()
  ↓
Bus
  ↓
AgentLoop.run()
  ↓
Bus
  ↓
CLI 渲染
```

## 6. `elebot agent` 放着不动时是不是 loop 还在跑

是的，但要区分两种情况。

### 6.1 交互模式

执行：

```bash
elebot agent
```

这时 `runtime` 已经启动了长期 `AgentLoop.run()`，只是当前可能处于等待消息状态。

`AgentLoop.run()` 的等待逻辑在 [elebot/agent/loop.py](../elebot/agent/loop.py#L498-L503)：

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
- 没有消息时只是 timeout 等待
- 等待周期里会顺带检查空闲压缩

### 6.2 单次模式

执行：

```bash
elebot agent -m "你好"
```

这条链路调用的是 `runtime.run_once(...)`，最终复用 `process_direct(...)`，不是长期 `run()` 主循环。

## 7. `--session`、`--workspace`、当前目录分别是什么关系

### 7.1 `--session`

只影响会话键，不影响工作区。

例如：

```bash
elebot agent --session cli:alt-test
```

会把短期消息写进另一个 `sessions/*.jsonl` 文件。

### 7.2 `--workspace`

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

### 7.3 当前 shell 目录

当前在哪个目录执行命令，不会自动切换 workspace。

工作区路径来自：

- `--workspace`
- 配置文件 `agents.defaults.workspace`
- 默认值 `~/.elebot/workspace`

对应代码：

- [elebot/config/paths.py](../elebot/config/paths.py#L11-L50)
- [elebot/config/schema.py](../elebot/config/schema.py#L28-L50)

## 8. 单次调用和交互模式的最大区别

### 交互模式

- 有长期 `run()` loop
- CLI 和 agent 通过 bus 双向通信
- runtime 托管主循环生命周期
- 空闲时会周期检查过期 session

### 单次模式

- 一次请求，一次返回
- 通过 runtime 直连 `process_direct(...)`
- 不依赖长期 `run()` loop

## 9. 读完这篇后，下一步看什么

推荐继续看：

- [RUNTIME](./RUNTIME.md)
- [BUS](./BUS.md)
- [SESSION](./SESSION.md)
