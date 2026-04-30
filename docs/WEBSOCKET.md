# WebSocket Channel

这篇文档只讲当前第一版 `websocket` channel。

相关源码：

- [elebot/cli/commands/serve.py](../elebot/cli/commands/serve.py#L1-L97)
- [elebot/channels/websocket.py](../elebot/channels/websocket.py#L1-L298)
- [elebot/channels/manager.py](../elebot/channels/manager.py#L1-L113)
- [elebot/runtime/protocol.py](../elebot/runtime/protocol.py#L1-L99)
- [tests/channels/test_websocket.py](../tests/channels/test_websocket.py#L1-L168)

## 1. 边界

当前 websocket v1 的边界已经固定：

- 只做本机入口
- 默认绑定 `127.0.0.1`
- 不做 token issuance
- 不做 TLS
- 不做外网部署
- 不做离线消息队列

所以它现在是：

> 一个接在 runtime.bus 前后的本机 channel

启动方式有两条：

- `elebot serve websocket`
  - 强制只启动 websocket
- `elebot serve channels`
  - 当 `channels.websocket.enabled=true` 时一并启动

## 2. 连接规则

当前连接 URL 至少需要：

```text
ws://127.0.0.1:{port}{path}?client_id={id}
```

可选参数：

- `chat_id`
  - 不传时默认等于 `client_id`
- `session_id`
  - 不传时默认等于 `websocket:{chat_id}`

固定事实：

- `client_id` 必填
- `chat_id` 决定 outbound 路由目标
- `session_id` 只负责会话键覆盖

## 3. 入站和出站

### 3.1 客户端发什么

可以直接发纯文本：

```text
你好
```

也可以发 JSON 对象：

- `input`
- `interrupt`
- `reset_session`
- `status`

### 3.2 服务端回什么

当前 websocket 和 stdio 共用同一组事件名：

- `ready`
- `progress`
- `delta`
- `stream_end`
- `message`
- `error`
- `interrupt_result`
- `reset_done`
- `status_result`

## 4. 当前为什么不用随机 `chat_id`

当前 EleBot 没照搬 nanobot 的“每连接随机 chat_id”。

原因很简单：

- EleBot 现在需要稳定 session key
- cron job 也需要稳定的 `channel + chat_id` 回推目标

所以 websocket v1 固定采用：

```text
chat_id = 显式传入值 或 client_id
```
