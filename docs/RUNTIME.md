# RUNTIME

这篇文档只讲 EleBot 当前已经落地的进程内 runtime，不讨论系统级后台服务、桌面壳或 Web 入口。

相关源码：

- [elebot/cli/runtime_support.py](../elebot/cli/runtime_support.py#L18-L123)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L31-L350)
- [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L10-L106)
- [elebot/runtime/models.py](../elebot/runtime/models.py#L8-L57)
- [elebot/runtime/protocol.py](../elebot/runtime/protocol.py#L1-L99)
- [tests/cli/test_runtime.py](../tests/cli/test_runtime.py#L1-L196)

## 1. runtime 解决什么问题

当前 runtime 解决的不是“系统后台常驻”这个最终产品问题，而是先把这件事收口：

```text
入口层不再自己拼 MessageBus + Provider + AgentLoop
```

所以现在可以把它理解成：

```text
runtime = 进程内统一装配入口 + 生命周期管理层
```

## 2. `ElebotRuntime.from_config()` 现在装配什么

装配入口在 [elebot/runtime/app.py](../elebot/runtime/app.py#L46-L98)。

它会统一创建：

- `MessageBus`
- provider
- `AgentLoop`
- `RuntimeState`

这里最重要的事实是：

- provider 默认来自 `providers.factory.build_provider()`
- 入口层只需要把 `Config` 交给 runtime

## 3. CLI 怎么复用 runtime

CLI 侧现在通过 [elebot/cli/runtime_support.py](../elebot/cli/runtime_support.py#L43-L123) 做很薄的一层适配：

1. `_load_runtime_config()`
2. `_make_provider()`
3. `_make_runtime()`

`agent` 命令只负责读取配置、同步 workspace 模板、再把执行交给 runtime。

## 4. runtime 对外提供哪些能力

### 4.1 生命周期

对应 [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L24-L106)：

- `start()`
- `wait()`
- `stop()`
- `close()`

### 4.2 对话入口

对应 [elebot/runtime/app.py](../elebot/runtime/app.py#L245-L323)：

- `run_once()`
- `run_interactive()`

### 4.3 第二入口怎么复用 runtime

当前已经落地三条非 TTY 或非直接终端输入的复用路径：

- `serve stdio`
  - 不启动 `AgentLoop.run()`
  - 直接循环调用 `runtime.run_once()`
- `serve channels`
  - 先 `runtime.start()`
  - 再由 `ChannelManager.start_all()` 启动所有已启用的内置 channel
- `serve websocket`
  - 先 `runtime.start()`
  - 再让 channel 把入站消息写进 `runtime.bus`
  - 由 `AgentLoop.run()` 和 `ChannelManager` 一起闭环

这说明 runtime 现在不只是“给 CLI 用的一层包装”，而是已经能承接：

- 直连型入口
- bus 驱动型入口

### 4.4 薄控制 API

对应 [elebot/runtime/app.py](../elebot/runtime/app.py#L124-L243)：

- `interrupt_session()`
- `reset_session()`
- `get_status_snapshot()`
- `trigger_dream()`
- `list_cron_jobs()`
- `remove_cron_job()`
- `get_dream_log()`
- `restore_dream_version()`

这些方法都只做委托，不在 runtime 自己实现业务 owner。

## 5. `interrupt_session()` 现在是什么语义

模块五完成后，runtime 已经有统一 interrupt 控制面。

`interrupt_session()` 的输入和输出固定为：

- 输入
  - `session_id`
  - `reason`
- 输出
  - `InterruptResult`

当前还有三条固定事实：

- CLI 的 `Esc` 不再走 slash 命令
- 它会直接调用 `runtime.interrupt_session()`
- runtime 再把这次中断委托给 `AgentLoop.interrupt_session()`

## 6. runtime 为什么说是“统一底座”

因为它已经把入口层最容易重复复制的那段东西收掉了：

```text
配置读取之后
  ↓
provider 装配
  ↓
bus 装配
  ↓
AgentLoop 装配
  ↓
生命周期托管
```

以后如果接：

- Web UI
- desktop
- 其他前端

都应该复用 `ElebotRuntime`，而不是再造一个平行装配链。

## 7. runtime 现在还不是什么

当前 runtime 还不是：

- 系统级 daemon
- 调度后端
- 独立 SDK 产品层

它现在是已经落地的进程内复用底座，并且已经具备：

- 单 runtime、单会话下的 interrupt 控制面
- 对 `CronService` 的薄委托 API
