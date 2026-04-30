# STDIO 入口协议

这篇文档只讲 `elebot serve stdio` 的 JSONL 协议，不讨论 websocket channel。

相关源码：

- [elebot/cli/commands/serve.py](../elebot/cli/commands/serve.py#L1-L68)
- [elebot/cli/serve_stdio.py](../elebot/cli/serve_stdio.py#L1-L165)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L124-L272)
- [elebot/runtime/protocol.py](../elebot/runtime/protocol.py#L1-L99)
- [tests/cli/test_serve_stdio.py](../tests/cli/test_serve_stdio.py#L1-L188)

## 1. 入口定位

`serve stdio` 是模块七的最小第二入口验证。

它的定位固定为：

- 不是假 channel
- 不启动 HTTP 服务
- 不自己拼 `MessageBus + AgentLoop`
- 直接复用 `ElebotRuntime`

## 2. 请求格式

每行都是一个 JSON 对象。

当前只接受四类请求：

- `{"type":"input","session_id":"cli:s1","content":"你好"}`
- `{"type":"interrupt","session_id":"cli:s1"}`
- `{"type":"reset_session","session_id":"cli:s1"}`
- `{"type":"status","session_id":"cli:s1"}`

固定事实：

- `input` 必须同时带 `session_id` 和 `content`
- 不接受 `message`、`prompt`、`text` 这些兼容别名
- 非法 JSON 或未知 `type` 会直接返回 `error`

## 3. 事件格式

服务端同样一行一个 JSON 事件。

当前事件类型固定为：

- `ready`
- `progress`
- `delta`
- `stream_end`
- `message`
- `error`
- `interrupt_result`
- `reset_done`
- `status_result`

这里最重要的行为是：

- `progress`
  - 承载 tool hint 和其它进度提示
- `delta` / `stream_end`
  - 直接映射 `runtime.run_once()` 的流式回调
- `message`
  - 始终承载本轮最终标准结果

## 4. 为什么它能被 `interrupt_session()` 命中

`serve stdio` 虽然走的是 `run_once()`，但当前实现已经把直连请求挂到了 `AgentLoop` 的活跃任务表里。

所以现在这条链路成立：

```text
stdio interrupt request
  ↓
runtime.interrupt_session()
  ↓
AgentLoop.interrupt_session()
  ↓
取消当前直连 run_once 任务
```
