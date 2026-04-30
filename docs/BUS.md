# Bus 与消息流转

这篇文档只讲一件事：

- EleBot 为什么需要 `bus`
- `InboundMessage` 和 `OutboundMessage` 里到底是什么
- CLI、channel 和 agent 是怎么通过 bus 接起来的

相关源码：

- [elebot/bus/events.py](../elebot/bus/events.py#L8-L36)
- [elebot/bus/queue.py](../elebot/bus/queue.py#L8-L40)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L54-L313)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L430-L753)

## 1. bus 在项目里的位置

当前最基础的主链路可以先画成这样：

```text
用户输入
  ↓
CLI
  ↓
MessageBus.inbound
  ↓
AgentLoop.run()
  ↓
MessageBus.outbound
  ↓
CLI 渲染
```

如果是 websocket channel，则会变成：

```text
WebSocket client
  ↓
WebSocketChannel
  ↓
MessageBus.inbound
  ↓
AgentLoop.run()
  ↓
MessageBus.outbound
  ↓
ChannelManager
  ↓
WebSocketChannel
```

bus 的定位不是“复杂事件系统”，而是：

> 一个很轻的异步消息中介层。

## 2. bus 本身很简单

看 [elebot/bus/queue.py](../elebot/bus/queue.py#L8-L40)：

```python
class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        return await self.outbound.get()
```

bus 只有两条队列：

- `inbound`
- `outbound`

没有：

- 路由规则
- 订阅机制
- 持久化
- 网络传输

所以它就是进程内异步队列。

## 3. `InboundMessage` 长什么样

定义在 [elebot/bus/events.py](../elebot/bus/events.py#L8-L25)：

```python
@dataclass
class InboundMessage:
    channel: str
    sender_id: str
    chat_id: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    session_key_override: str | None = None
```

字段可以这样理解：

- `channel`：消息来源渠道，CLI 下通常是 `cli`
- `sender_id`：发送者标识，CLI 下通常是 `user`
- `chat_id`：会话 id，CLI 下通常来自 `session_id`
- `content`：用户正文
- `media`：媒体文件路径
- `metadata`：运行时控制信息
- `session_key_override`：当某条消息需要强制改写 session key 时使用

### 3.1 `session_key` 是怎么来的

同一个类里还有一个属性，在 [elebot/bus/events.py](../elebot/bus/events.py#L21-L24)：

```python
@property
def session_key(self) -> str:
    return self.session_key_override or f"{self.channel}:{self.chat_id}"
```

这说明默认情况下：

```text
session_key = channel + ":" + chat_id
```

例如 CLI 默认就是：

```text
cli:direct
```

## 4. `OutboundMessage` 长什么样

定义在 [elebot/bus/events.py](../elebot/bus/events.py#L27-L36)：

```python
@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

可以直接理解成：

- `content`：要显示给用户的文本
- `media`：要发出的文件
- `metadata`：渲染控制信息

当前 CLI 最关键的不是 `reply_to`，而是 `metadata`。

## 5. CLI 是怎么向 bus 发消息的

交互模式入口在 [elebot/cli/interactive.py](../elebot/cli/interactive.py#L197-L230)：

```python
user_input = await read_interactive_input_async()

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

这里做了两件事：

1. 读取终端输入
2. 打包成 `InboundMessage` 发进 `inbound queue`

所以 CLI 不直接调 agent 内部方法，而是统一走 bus。

## 6. AgentLoop 是怎么从 bus 取消息的

看 [elebot/agent/loop.py](../elebot/agent/loop.py#L430-L495)：

```python
while self._running:
    try:
        msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
    except asyncio.TimeoutError:
        self.auto_compact.check_expired(self._schedule_background)
        continue

    task = asyncio.create_task(self._dispatch(msg))
```

可以把这段理解成：

- loop 一直等新消息
- 没消息时做一些空闲检查
- 有消息时交给 `_dispatch()` 处理

## 7. Agent 是怎么把结果再发回 bus 的

在 [elebot/agent/loop.py](../elebot/agent/loop.py#L521-L579) 和 [elebot/agent/loop.py](../elebot/agent/loop.py#L681-L725) 里，有几类出站消息。

### 7.1 流式文本增量

```python
meta["_stream_delta"] = True
await self.bus.publish_outbound(OutboundMessage(...))
```

### 7.2 一个流片段结束

```python
meta["_stream_end"] = True
meta["_resuming"] = resuming
await self.bus.publish_outbound(OutboundMessage(...))
```

### 7.3 进度提示

```python
meta["_progress"] = True
meta["_tool_hint"] = tool_hint
await self.bus.publish_outbound(OutboundMessage(...))
```

### 7.4 最终回答

```python
outbound = OutboundMessage(
    channel=msg.channel,
    chat_id=msg.chat_id,
    content=final_content,
    metadata=meta,
)
```

所以 bus 上传的不是单一“回复文本”，而是一组运行时事件。

## 8. outbound 现在会被谁消费

当前 `outbound` 有两种真实消费者：

- CLI 交互层
- `ChannelManager`

二者共享同一份 `OutboundMessage`，只是呈现方式不同。

`ChannelManager` 会识别当前已经固定下来的 metadata：

- `_progress`
- `_tool_transition`
- `_stream_delta`
- `_stream_end`
- `_streamed`

然后把它们翻译成各个 channel 协议自己的事件。

## 9. CLI 是怎么消费这些出站事件的

看 [elebot/cli/interactive.py](../elebot/cli/interactive.py#L132-L188)：

```python
message = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

if message.metadata.get("_stream_delta"):
    await renderer.on_delta(message.content)

if message.metadata.get("_stream_end"):
    await renderer.on_end(...)

if message.metadata.get("_progress"):
    await print_interactive_progress_line(message.content, thinking)
```

这意味着：

- CLI 渲染层并不知道 agent 内部细节
- 它只看 `OutboundMessage.metadata`
- 然后决定怎么显示

## 9. 为什么 bus 不是多余的一层

如果没有 bus，CLI 就需要直接知道：

- agent 的处理入口
- 流式事件怎么拆
- 中间进度怎么传
- 多轮追问怎么注入

加上 bus 以后，角色清楚很多：

- CLI：负责输入和输出
- bus：负责转发
- agent：负责处理

所以 bus 的真实作用不是“高级架构”，而是：

> 把交互层和执行层解耦。

## 10. 读完这篇后，下一步看什么

建议继续看：

- [SESSION](./SESSION.md)
- [AGENT](./AGENT.md)
