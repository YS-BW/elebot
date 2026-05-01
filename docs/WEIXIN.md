# Weixin Channel

这篇文档只讲当前第一版个人微信 `weixin` channel。

相关源码：

- [elebot/config/schema.py](../elebot/config/schema.py#L157-L199)
- [elebot/cli/commands/weixin.py](../elebot/cli/commands/weixin.py#L1-L286)
- [elebot/channels/weixin.py](../elebot/channels/weixin.py#L66-L755)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L47-L221)
- [elebot/providers/transcription.py](../elebot/providers/transcription.py#L19-L177)
- [tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L1-L260)

## 1. 边界

当前 `weixin` channel 的范围已经固定：

- 基于 `https://ilinkai.weixin.qq.com` 的 HTTP 长轮询协议
- 做个人微信私聊文本收发
- 入站消息会区分文本、图片、语音
- 微信图片会先下载到本地媒体目录，再作为附件送进模型
- 微信语音会优先使用微信返回的转写文本；没有转写文本时，会下载语音并通过 `qwen3-asr-flash` 转写
- 不做群聊
- 默认不做微信侧图片/文件/视频的出站发送
- 不做流式正文
- 不做 typing indicator
- 不透出 tool hint 和后台 progress

所以微信侧用户默认只会收到最终 assistant 文本，不会看到 `↳ tool(...)` 这类中间过程；但用户发给机器人的图片已经会被当成模型可见附件处理。

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

语音转写不挂在 `channels.weixin` 下，而是统一走顶层 `transcription` 配置：

- `api_key`
- `api_base`

当前只支持一个转写模型：`qwen3-asr-flash`。没有配置 `transcription.api_key` 时，微信语音只能使用微信原生自带的 `voice_item.text`；如果微信侧也没给文本，就只能回退成“无法完成转写”。

## 3. 登录与状态文件

当前登录命令只有一条：

```bash
elebot weixin login
```

如果需要强制重新扫码：

```bash
elebot weixin login --force
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
3. 否则直接报错，提示先执行 `elebot weixin login`

当前不会在 `start()` 里自动弹扫码登录。

## 4. 运行入口

微信 channel 不通过 `elebot agent` 启动。

正式前台入口是：

```bash
elebot weixin run
```

后台入口是：

```bash
elebot weixin start
elebot weixin log
elebot weixin stop
elebot weixin restart
```

其中 `elebot weixin log` 只负责实时输出后台日志；按 `Ctrl+C` 退出后，不会影响已经运行中的后台 service。

当且仅当 `channels.weixin.enabled=true` 时，`ChannelManager` 才会初始化并启动 `WeixinChannel`。

## 5. 入站与会话语义

微信入站消息当前固定映射为：

- `sender_id = from_user_id`
- `chat_id = from_user_id`
- `session_key = weixin:{from_user_id}`
- 文本 item 进入 `content`
- 图片 item 下载到 `~/.elebot/media/weixin/` 后进入 `media`
- 语音 item 优先转成文本；转写时下载到 `~/.elebot/media/weixin/` 后送入 runtime 级转写 provider

同时会把下面这些运行期事实放进 metadata：

- `message_id`
- `context_token`
- `_session_id`

这意味着第一版个人微信是“每个联系人一条稳定私聊会话”。

## 6. 出站与限制

当前 `send_message()` 默认发送最终文本消息，并且必须复用该联系人的 `context_token`。

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
