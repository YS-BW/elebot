# Channel 适配层

这篇文档只讲当前已经落地的 `channels/` 子系统，不讨论未来更多平台接入。

相关源码：

- [elebot/channels/base.py](../elebot/channels/base.py#L1-L108)
- [elebot/channels/manager.py](../elebot/channels/manager.py#L1-L113)
- [elebot/channels/weixin.py](../elebot/channels/weixin.py#L57-L620)
- [elebot/bus/events.py](../elebot/bus/events.py#L1-L34)
- [tests/channels/test_manager.py](../tests/channels/test_manager.py#L1-L118)

## 1. 当前 owner 分工

`channels/` 当前只有三层：

- `BaseChannel`
  - 负责把外部输入标准化成 `InboundMessage`
  - 负责定义发送最终消息、进度和正文增量的协议接口
- `ChannelManager`
  - 负责初始化已启用 channel
  - 负责启动、停止
  - 负责消费 `runtime.bus.outbound` 并路由回 channel
- concrete channel
  - `WeixinChannel`

当前唯一 concrete channel 的边界是：

- `WeixinChannel`
  - 个人微信 HTTP 长轮询入口
  - 第一版只发最终文本消息
  - `progress` 和 `delta` 固定 no-op

更具体的平台协议见：

- [WEIXIN](./WEIXIN.md)

## 2. 为什么说 channel 不是 runtime

当前固定主链路是：

```text
Channel Adapter
  ↓
Bus
  ↓
AgentLoop
```

所以 channel 解决的是：

- 外部平台怎么接入
- outbound 怎么按平台协议发回去

而不是：

- provider 怎么装
- session 怎么跑
- cron 怎么调度

这些 owner 仍然在 runtime、agent、cron。

## 3. 当前有哪些正式入口

当前 channel 相关入口只有一条：

- `elebot serve channels`
  - 启动所有 `enabled=true` 的内置 channel

## 4. `ChannelManager` 现在识别哪些 outbound metadata

当前 manager 固定会识别：

- `_tool_transition`
- `_progress`
- `_stream_delta`
- `_stream_end`

然后分别路由成：

- progress 事件
- delta 事件
- stream_end 事件
- 最终 message 事件

这里不做业务翻译，只做最小协议映射。

## 5. 当前 channel 的默认会话键

`BaseChannel.publish_input()` 的默认规则没有特殊分支：

```text
session_key = channel + ":" + chat_id
```

所以：

- weixin 默认是 `weixin:{from_user_id}`

这也是为什么个人微信 channel 第一版可以直接把私聊发送者稳定映射到独立会话。
