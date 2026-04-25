# EleBot 整体架构总览

这篇文档只讲主链路，不讲已经删除或不在当前默认链路里的旧模块。

相关源码：

- [README.md](../README.md#L1-L38)
- [elebot/cli/commands.py](../elebot/cli/commands.py#L313-L414)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L51-L180)
- [elebot/bus/queue.py](../elebot/bus/queue.py#L8-L40)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L430-L979)
- [elebot/agent/context.py](../elebot/agent/context.py#L16-L217)
- [elebot/session/manager.py](../elebot/session/manager.py#L14-L209)
- [elebot/agent/memory.py](../elebot/agent/memory.py#L31-L866)

## 1. 先记住主链路

```text
用户输入
  ↓
elebot CLI
  ↓
MessageBus
  ↓
AgentLoop.run()
  ↓
_dispatch()
  ↓
_process_message_result()
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

- `cli`：命令入口、交互输入、终端渲染
- `bus`：入站和出站消息中介
- `agent`：调度、上下文、工具循环、记忆整理
- `session`：单个会话的短期状态
- `config`：配置解析和运行目录路径
- `providers`：模型调用适配层
- `command`：`/new`、`/stop`、`/dream` 这类本地命令
- `utils`：路径、模板、token 估算、git store 等基础能力

## 2. 现在有几种运行方式

### 2.1 交互终端模式

入口在 [elebot/cli/commands.py](../elebot/cli/commands.py#L378-L414)：

```python
if message:
    asyncio.run(run_once())
else:
    asyncio.run(
        run_interactive_loop(
            agent_loop=agent_loop,
            bus=bus,
            session_id=session_id,
            markdown=markdown,
        )
    )
```

执行命令：

```bash
elebot agent
```

这条链路会：

- 启动 `AgentLoop.run()`
- 启动 CLI 输入循环
- 通过 `bus` 双向收发消息

### 2.2 单次命令模式

同样在 [elebot/cli/commands.py](../elebot/cli/commands.py#L378-L405)：

```python
response = await agent_loop.process_direct(
    message,
    session_id,
    on_progress=_cli_progress,
    on_stream=renderer.on_delta,
    on_stream_end=renderer.on_end,
)
```

执行命令：

```bash
elebot agent -m "你好"
```

这条链路不会进入长期 `run()` 主循环，而是直接单次处理。

### 2.3 程序化调用模式

入口在 [elebot/facade.py](../elebot/facade.py#L23-L121)：

```python
bot = Elebot.from_config()
result = await bot.run("你好", session_key="sdk:default")
```

适合：

- SDK 调用
- 自己包一层服务
- 测试和脚本

## 3. 当前项目的几个核心边界

### 3.1 `workspace` 不是源码目录

源码目录是项目仓库。  
workspace 是运行时目录，默认是 `~/.elebot/workspace`。

路径逻辑在：

- [elebot/config/paths.py](../elebot/config/paths.py#L11-L50)
- [elebot/config/schema.py](../elebot/config/schema.py#L28-L50)

### 3.2 `session` 不是长期记忆

`session` 保存的是单个会话线程的短期消息状态，文件在：

- [elebot/session/manager.py](../elebot/session/manager.py#L14-L209)

### 3.3 `memory` 不是单一文件

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

## 4. 现在 bus 为什么重要

`bus` 代码很短，但它是主链路中介层。

看 [elebot/bus/queue.py](../elebot/bus/queue.py#L8-L40)：

```python
class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
```

CLI 负责：

- 发布 `InboundMessage`
- 消费 `OutboundMessage`

AgentLoop 负责：

- 消费 `InboundMessage`
- 发布 `OutboundMessage`

所以 bus 的作用就是把输入层和 agent 执行层拆开。

## 5. 你可以怎么理解这个项目

最简单的理解方式是：

```text
EleBot = 一个终端前端
       + 一个消息总线
       + 一条 agent 主循环
       + 一套 session / memory 状态层
       + 一组 provider / tool 执行器
```

下一步建议阅读：

- [CLI](./CLI.md)
- [BUS](./BUS.md)
- [SESSION](./SESSION.md)
