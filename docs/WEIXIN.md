# Weixin Channel

这篇文档只讲当前第一版个人微信 `weixin` channel。

相关源码：

- [elebot/config/schema.py](../elebot/config/schema.py#L166-L182)
- [elebot/cli/commands/channels.py](../elebot/cli/commands/channels.py#L47-L79)
- [elebot/cli/commands/serve.py](../elebot/cli/commands/serve.py#L62-L97)
- [elebot/channels/weixin.py](../elebot/channels/weixin.py#L57-L620)
- [elebot/runtime/protocol.py](../elebot/runtime/protocol.py#L12-L15)
- [tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L1-L217)

## 1. 边界

当前 `weixin` channel 的范围已经固定：

- 基于 `https://ilinkai.weixin.qq.com` 的 HTTP 长轮询协议
- 只做个人微信私聊文本收发
- 不做群聊
- 不做图片、文件、语音、视频
- 不做流式正文
- 不做 typing indicator
- 不透出 tool hint 和后台 progress

所以微信侧用户只会收到最终 assistant 文本，不会看到 `↳ tool(...)` 这类中间过程。

## 2. 配置

当前配置在 `channels.weixin` 下，字段只有这一组：

- `enabled`
- `allow_from`
- `base_url`
- `route_tag`
- `token`
- `state_dir`
- `poll_timeout`

默认 `allow_from=["*"]`，表示第一版默认放行全部联系人。

## 3. 登录与状态文件

当前登录命令只有一条：

```bash
elebot channels login weixin
```

如果需要强制重新扫码：

```bash
elebot channels login weixin --force
```

登录成功后，状态默认持久化到：

```text
~/.elebot/weixin/account.json
```

当前状态文件固定保存：

- `token`
- `get_updates_buf`
- `context_tokens`
- `base_url`

启动时固定优先级是：

1. `channels.weixin.token`
2. 已保存的 `account.json`
3. 否则直接报错，提示先执行 `elebot channels login weixin`

当前不会在 `start()` 里自动弹扫码登录。

## 4. 运行入口

微信 channel 不通过 `elebot agent` 启动。

正式入口是：

```bash
elebot serve channels
```

当且仅当 `channels.weixin.enabled=true` 时，`ChannelManager` 才会初始化并启动 `WeixinChannel`。

## 5. 入站与会话语义

微信入站消息当前固定映射为：

- `sender_id = from_user_id`
- `chat_id = from_user_id`
- `session_key = weixin:{from_user_id}`

同时会把下面这些运行期事实放进 metadata：

- `message_id`
- `context_token`
- `_session_id`

这意味着第一版个人微信是“每个联系人一条稳定私聊会话”。

## 6. 出站与限制

当前 `send_message()` 只发送最终文本消息，并且必须复用该联系人的 `context_token`。

固定行为：

- 没有 `context_token`
  - 直接记录 warning 并丢弃消息
- 文本过长
  - 按微信上限切块发送
- `send_progress()`
  - no-op
- `send_delta()`
  - no-op

所以如果你希望微信用户也看到流式正文或工具提示，那不是当前 V1 的实现范围。
