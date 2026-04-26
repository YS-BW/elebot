# EleBot 整体架构总览

这篇文档只讲当前默认主链路，不讲已经删除或不在默认入口里的旧模块。

相关源码：

- [README.md](../README.md#L1-L38)
- [elebot/cli/commands.py](../elebot/cli/commands.py#L175-L351)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L23-L220)
- [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L10-L106)
- [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L82)
- [elebot/bus/queue.py](../elebot/bus/queue.py#L8-L40)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L154-L1073)
- [elebot/agent/context.py](../elebot/agent/context.py#L17-L267)
- [elebot/session/manager.py](../elebot/session/manager.py#L14-L209)
- [elebot/agent/memory.py](../elebot/agent/memory.py#L31-L866)

## 1. 先记住当前主链路

```text
用户输入
  ↓
CLI
  ↓
Runtime
  ↓
MessageBus
  ↓
AgentLoop.run() / process_direct()
  ↓
ContextBuilder.build_messages()
  ↓
AgentRunner.run()
  ↓
Provider / Tools
  ↓
OutboundMessage
  ↓
CLI 渲染输出
```

当前主链路模块可以直接记成：

- `cli`
  - 命令入口、交互输入、终端渲染
- `runtime`
  - 运行时装配、长期主循环生命周期管理
- `bus`
  - 入站和出站消息中介
- `agent`
  - 调度、上下文、工具循环、记忆整理
- `session`
  - 单个会话的短期状态
- `config`
  - 配置解析和运行目录路径
- `providers`
  - 模型调用适配层
- `command`
  - `/new`、`/stop`、`/dream` 这类本地命令
- `utils`
  - 路径、模板、token 估算、git store 等基础能力

## 2. 为什么现在多了一个 runtime 层

现在的 `runtime` 层不是新产品入口，而是把原来散在 CLI 里的运行时装配动作收口了。

对应代码在 [elebot/runtime/app.py](../elebot/runtime/app.py#L38-L90)：

```python
bus = resolved_bus_factory()
provider = resolved_provider_builder(config)
agent_loop = resolved_agent_loop_factory(
    bus=bus,
    provider=provider,
    workspace=config.workspace_path,
    model=defaults.model,
    ...
)
```

它做的事很明确：

- 统一创建 `MessageBus`
- 统一创建 provider
- 统一创建 `AgentLoop`
- 把运行态对象塞进 `RuntimeState`

所以现在的结构已经从：

```text
CLI 直接拼所有主链路对象
```

变成：

```text
CLI 调 runtime
runtime 装配主链路
agent 继续执行主逻辑
```

## 3. 现在有哪些入口与复用方式

### 3.1 交互终端模式

入口在 [elebot/cli/commands.py](../elebot/cli/commands.py#L350-L351)：

```python
asyncio.run(runtime.run_interactive(session_id=session_id, markdown=markdown))
```

执行命令：

```bash
elebot agent
```

这条链路会：

- 先由 CLI 装配 runtime
- 由 runtime 托管 `AgentLoop.run()` 的生命周期
- 再由交互层通过 bus 收发消息

### 3.2 单次命令模式

同样在 [elebot/cli/commands.py](../elebot/cli/commands.py#L322-L349)：

```python
response = await runtime.run_once(
    message,
    session_id=session_id,
    on_progress=_cli_progress,
    on_stream=renderer.on_delta,
    on_stream_end=renderer.on_end,
)
```

执行命令：

```bash
elebot agent -m "你好"
```

这条链路不会进入长期 `run()` 主循环，而是通过 runtime 复用 `AgentLoop.process_direct(...)`。

### 3.3 如果以后接新入口，应该怎么复用

当前仓库已经没有 `facade` 这层程序化包装。

```python
runtime = ElebotRuntime.from_config(config)
```

这意味着以后如果要接：

- Web
- desktop
- channel

都应该直接复用 [elebot/runtime/app.py](../elebot/runtime/app.py#L38-L90) 里的装配入口，让 runtime 继续统一创建：

- `MessageBus`
- provider
- `AgentLoop`

而 provider 的具体路由和实例化则统一收口在 [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L82)。

这条复用原则的重点不是“补回一个 SDK 层”，而是避免后续入口再复制一套平行的运行时装配逻辑。

## 4. 交互模式实际怎么流动

当前交互模式不要再按“CLI 直接起 agent_loop.run()”去理解，而要按下面这条链路看：

```text
commands.agent()
  ↓
_make_runtime(config)
  ↓
runtime.run_interactive()
interactive.run_interactive_loop(manage_agent_loop=False)
  ↓
bus.publish_inbound()
  ↓
AgentLoop.run()
  ↓
bus.publish_outbound()
  ↓
CLI 渲染
```

其中最关键的代码在 [elebot/runtime/app.py](../elebot/runtime/app.py#L145-L176)：

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

`manage_agent_loop=False` 的意思是：

- 主循环已经由 runtime 生命周期托管
- 交互层只负责输入输出

更准确地说，`runtime.start()` 和 `runtime.close()` 现在是包在 `runtime.run_interactive()` 内部按需处理的，不再由 CLI 显式控制。

## 5. 当前项目的几个核心边界

### 5.1 `workspace` 不是源码目录

源码目录是项目仓库。  
workspace 是运行时目录，默认是 `~/.elebot/workspace`。

路径逻辑在：

- [elebot/config/paths.py](../elebot/config/paths.py#L11-L50)
- [elebot/config/schema.py](../elebot/config/schema.py#L28-L50)

### 5.2 `session` 不是长期记忆

`session` 保存的是单个会话线程的短期消息状态，文件在：

- [elebot/session/manager.py](../elebot/session/manager.py#L14-L209)

### 5.3 `memory` 不是单一文件

记忆系统由这些文件组成：

```text
workspace/
├── USER.md
├── SOUL.md
├── memory/
│   ├── MEMORY.md
│   ├── history.jsonl
│   ├── .cursor
│   └── .dream_cursor
└── sessions/
    └── *.jsonl
```

对应实现：

- [elebot/agent/memory.py](../elebot/agent/memory.py#L31-L866)
- [elebot/session/manager.py](../elebot/session/manager.py#L14-L209)

## 6. 现在 bus 为什么重要

`bus` 代码很短，但它仍然是主链路中介层。

看 [elebot/bus/queue.py](../elebot/bus/queue.py#L8-L40)：

```python
class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
```

在当前实现里：

- CLI 负责发布 `InboundMessage`
- `AgentLoop` 负责消费 `InboundMessage`
- `AgentLoop` 负责发布 `OutboundMessage`
- CLI 负责消费 `OutboundMessage`

runtime 不替代 bus，它只是把 bus 和主循环的装配关系固定下来。

## 7. 你可以怎么理解这个项目

最简单的理解方式是：

```text
EleBot = 一个终端前端
       + 一个 runtime 装配层
       + 一个消息总线
       + 一条 agent 主循环
       + 一套 session / memory 状态层
       + 一组 provider / tool 执行器
```

下一步建议阅读：

- [RUNTIME](./RUNTIME.md)
- [CLI](./CLI.md)
- [BUS](./BUS.md)
