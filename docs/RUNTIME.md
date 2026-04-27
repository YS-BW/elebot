# RUNTIME

这篇文档只讲 EleBot 当前已经落地的进程内 runtime，不讨论还没做的系统级后台服务、桌面壳或 Web 入口。

相关源码：

- [elebot/cli/runtime_support.py](../elebot/cli/runtime_support.py#L18-L109)
- [elebot/cli/commands/agent.py](../elebot/cli/commands/agent.py#L31-L105)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L25-L340)
- [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L10-L106)
- [elebot/runtime/state.py](../elebot/runtime/state.py#L14-L35)
- [tests/cli/test_runtime.py](../tests/cli/test_runtime.py#L13-L165)

## 1. runtime 解决的是什么问题

当前 runtime 解决的不是“系统后台常驻”这个最终产品问题，而是先把这件事收口：

```text
入口层不再自己拼 MessageBus + Provider + AgentLoop
```

所以现在可以把它理解成：

```text
runtime = 进程内统一装配入口 + 生命周期管理层
```

## 2. `ElebotRuntime.from_config()` 现在装配什么

装配入口在 [elebot/runtime/app.py](../elebot/runtime/app.py#L40-L92)。

它会统一创建：

- `MessageBus`
- provider
- `AgentLoop`
- `RuntimeState`

简化后的结构就是：

```python
bus = resolved_bus_factory()
provider = resolved_provider_builder(config)
agent_loop = resolved_agent_loop_factory(...)
return ElebotRuntime(RuntimeState(...))
```

这里最重要的事实是：

- provider 默认来自 `providers.factory.build_provider()`
- 入口层只需要把 `Config` 交给 runtime

## 3. CLI 怎么复用 runtime

CLI 侧现在通过 [elebot/cli/runtime_support.py](../elebot/cli/runtime_support.py#L40-L86) 做很薄的一层适配：

1. `_load_runtime_config()`
2. `_make_provider()`
3. `_make_runtime()`

`agent` 命令只负责：

```python
loaded_config = _load_runtime_config(config, workspace)
runtime = _make_runtime(loaded_config)
```

然后把后续执行交给 runtime，见 [elebot/cli/commands/agent.py](../elebot/cli/commands/agent.py#L53-L105)。

## 4. runtime 对外提供哪些入口

当前 `ElebotRuntime` 已经固定提供三类能力。

### 4.1 生命周期

对应 [elebot/runtime/app.py](../elebot/runtime/app.py#L298-L340) 和 [elebot/runtime/lifecycle.py](../elebot/runtime/lifecycle.py#L24-L106)：

- `start()`
- `wait()`
- `stop()`
- `close()`

### 4.2 对话入口

对应 [elebot/runtime/app.py](../elebot/runtime/app.py#L236-L297)：

- `run_once()`
- `run_interactive()`

### 4.3 薄控制 API

对应 [elebot/runtime/app.py](../elebot/runtime/app.py#L118-L234)：

- `cancel_session_tasks()`
- `reset_session()`
- `get_status_snapshot()`
- `trigger_dream()`
- `list_tasks()`
- `remove_task()`
- `get_dream_log()`
- `restore_dream_version()`

这些方法都只做委托，不在 runtime 自己实现业务 owner。

## 5. runtime 为什么说是“统一底座”

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

都应该复用 `ElebotRuntime`，而不是再造一个 `facade` 或平行装配链。

## 6. 当前还不应该把 runtime 误解成什么

当前 runtime 还不是：

- 系统级 daemon
- 调度后端
- 完整 interrupt 体系
- 独立 SDK 产品层

它现在只是已经落地的进程内复用底座。
