# CLI 与运行方式

这篇文档只讲 `elebot` 当前真实支持的终端入口，以及 CLI 怎样把请求交给 `runtime`。

相关源码：

- [elebot/cli/commands/agent.py](../elebot/cli/commands/agent.py#L21-L110)
- [elebot/cli/commands/channels.py](../elebot/cli/commands/channels.py#L1-L79)
- [elebot/cli/commands/serve.py](../elebot/cli/commands/serve.py#L1-L97)
- [elebot/cli/runtime_support.py](../elebot/cli/runtime_support.py#L18-L123)
- [elebot/cli/serve_stdio.py](../elebot/cli/serve_stdio.py#L1-L165)
- [elebot/cli/interactive.py](../elebot/cli/interactive.py#L54-L313)
- [elebot/cli/stream.py](../elebot/cli/stream.py#L22-L199)
- [elebot/cli/keys.py](../elebot/cli/keys.py#L14-L416)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L245-L306)

## 1. CLI 现在保留哪些命令

当前根命令面只保留真实主链路需要的五个命令：

- `elebot onboard`
- `elebot agent`
- `elebot channels`
- `elebot serve`
- `elebot status`

根入口本身很薄，只做三件事：

1. 创建 `Typer` app
2. 注册当前保留的命令
3. 处理 `--version`

## 2. `elebot channels` 现在承担什么角色

`channels` 不是旧版那种大而全的 channel 管理面。

当前只保留一条真实命令：

- `elebot channels login weixin`

它只负责：

- 读取当前配置
- 解析配置里的环境变量
- 用一个最小 runtime stub 跑内置 channel 的登录流程

当前不会通过这条命令：

- 启动 runtime 主循环
- 启动 websocket server
- 管理一整套 channel 生命周期

## 3. `elebot serve` 现在承担什么角色

`serve` 不是新的业务 owner，它只是把现有 runtime 复用给第二入口：

- `elebot serve stdio`
  - 提供一行一个 JSON 的脚本化入口
  - 内部直接复用 `runtime.run_once()`、`interrupt_session()`、`reset_session()`、`get_status_snapshot()`
- `elebot serve channels`
  - 启动 `runtime.start()`
  - 再启动所有 `enabled=true` 的内置 channel
  - 当前内置 channel 只有 `websocket` 和 `weixin`
- `elebot serve websocket`
  - 启动 `runtime.start()`
  - 再把 websocket channel 接到 `runtime.bus`
  - 让 `ChannelManager` 负责 outbound 路由

这里最重要的事实是：

- `stdio` 不是 channel
- `channels` 是“所有已启用内置 channel”的统一入口
- `websocket` 是 channel
- 三者都没有绕过 `ElebotRuntime`

## 4. `elebot agent` 的真实启动链路

`agent` 命令现在不再自己拼 `Bus + provider + AgentLoop`。

真实链路是：

```text
CLI
  ↓
_load_runtime_config()
  ↓
sync_workspace_templates()
  ↓
_make_runtime()
  ↓
ElebotRuntime
```

CLI 自己的职责固定为：

- 解析参数
- 处理 `--config` / `--workspace`
- 刷新 workspace 模板
- 控制终端渲染
- 调 `runtime`

## 5. 单次模式和交互模式怎么分

### 5.1 单次模式

执行：

```bash
elebot agent -m "你好"
```

CLI 会调用 `runtime.run_once(...)`。

### 5.2 交互模式

执行：

```bash
elebot agent
```

CLI 会调用 `runtime.run_interactive(...)`。

这时候 runtime 会：

1. 按需启动 `AgentLoop.run()`
2. 调 `interactive.py` 处理终端输入输出
3. 在退出时统一收尾

## 6. 交互模式里的 `Ctrl+C` 和 `Esc`

当前按键语义已经固定：

- `Ctrl+C`
  - 退出当前交互进程
- `Esc`
  - 只在活跃回复期间生效
  - 会中断当前这一轮回复或工具执行
  - 只有“孤立的 Esc”才会触发中断
  - 终端回复的控制序列会被完整消费，不会把 `[38;1R`、`??` 这类残留带进下一次输入
- 等待输入时按 `Esc`
  - 不会触发中断
  - 仍然交给 `prompt_toolkit` 的普通输入行为

现在的 interrupt 链路是：

```text
CLI 按键
  ↓
EscInterruptWatcher
  ↓
runtime.interrupt_session()
  ↓
AgentLoop.interrupt_session()
```

另外，交互渲染现在还有四条已经固定的事实：

- 所有模型可见文本都会按 assistant 正文显示；`↳` 只保留 tool hint、工具过程提示和本地控制提示
- active turn 期间只有一条输出通道：spinner、正文流、tool hint 都由同一个 renderer 直接写终端，不再混用 `prompt_toolkit` 的临时打印通道
- tool-call 交接现在会先收掉当前正文流，再输出 `↳ tool(...)`，随后继续复用同一个 thinking spinner；不会再因为旧 spinner 引用或 prompt 重绘留下 `You:` 残影
- 如果 cron 或其他后台消息在你正在输入时到达，CLI 会先暂存它们，等你提交当前输入后再按顺序显示

## 7. slash 命令和 CLI 的关系

slash 命令不属于 CLI 根命令系统。

关系是：

```text
CLI 把文本送进主链路
  ↓
AgentLoop 命中 CommandRouter
  ↓
command handler 调 owner API
```

当前中断已经完全退出 slash 命令协议：

- `/stop` 已移除
- 不新增 `/interrupt`
- 不新增 `/cancel`

当前也不再提供：

- `/task`
- `/cron`

调度需求现在通过模型调用 `cron_create / cron_list / cron_delete / cron_update` 完成，而不是通过 CLI slash 命令管理。

## 8. 以后接 Web 或 desktop 时该复用哪里

当前固定原则没有变：

```text
CLI 是一个入口
runtime 是统一底座
```

以后如果接 Web UI、desktop 或其他前端，应该复用 `ElebotRuntime`，而不是重新在入口层复制一套装配逻辑。
