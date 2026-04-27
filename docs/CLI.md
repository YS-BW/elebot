# CLI 与运行方式

这篇文档只讲 `elebot` 当前真实支持的终端入口，以及 CLI 怎样把请求交给 `runtime`。

相关源码：

- [elebot/cli/app.py](../elebot/cli/app.py#L1-L67)
- [elebot/cli/commands/__init__.py](../elebot/cli/commands/__init__.py#L1-L23)
- [elebot/cli/commands/onboard.py](../elebot/cli/commands/onboard.py#L16-L164)
- [elebot/cli/commands/agent.py](../elebot/cli/commands/agent.py#L21-L105)
- [elebot/cli/commands/status.py](../elebot/cli/commands/status.py#L11-L60)
- [elebot/cli/runtime_support.py](../elebot/cli/runtime_support.py#L18-L109)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L40-L340)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L12-L66)

## 1. CLI 现在保留哪些命令

当前根命令面只保留真实主链路需要的三个命令：

- `elebot onboard`
- `elebot agent`
- `elebot status`

`provider login` 已经随 OAuth provider 一起移除，CLI 不再保留那套登录入口。

根入口做的事情很薄：

1. 创建 `Typer` app
2. 注册当前保留的命令
3. 处理 `--version`

这部分现在集中在 [elebot/cli/app.py](../elebot/cli/app.py#L24-L67) 和 [elebot/cli/commands/__init__.py](../elebot/cli/commands/__init__.py#L12-L23)。

## 1.1 `onboard` 当前会做什么

当前 `elebot onboard` 的默认初始化行为已经固定为：

- 创建或刷新 `config.json`
- 默认把 provider 设为 `deepseek`
- 默认把模型设为 `deepseek-v4-flash`
- 补齐 workspace 启动模板和 `memory/history.jsonl`
- 尝试安装两份默认 skill 源
- 输出中文下一步提示，并把 API Key 获取地址指向 DeepSeek 平台

这部分逻辑都在 [elebot/cli/commands/onboard.py](../elebot/cli/commands/onboard.py#L18-L157)。

## 2. `elebot agent` 的真实启动链路

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

对应代码就在 [elebot/cli/commands/agent.py](../elebot/cli/commands/agent.py#L31-L105)：

```python
loaded_config = _load_runtime_config(config, workspace)
sync_workspace_templates(loaded_config.workspace_path)
runtime = _make_runtime(loaded_config)
```

这里可以直接看出 CLI 的边界：

- 解析参数
- 处理 `--config` / `--workspace`
- 刷新 workspace 模板
- 控制终端渲染
- 调 `runtime`

真正的运行时装配在 [elebot/cli/runtime_support.py](../elebot/cli/runtime_support.py#L40-L86)。

## 3. 单次模式和交互模式怎么分

### 3.1 单次模式

执行：

```bash
elebot agent -m "你好"
```

CLI 会调用 `runtime.run_once(...)`，对应 [elebot/runtime/app.py](../elebot/runtime/app.py#L236-L263)。

这条链路直接复用 `AgentLoop.process_direct(...)`，不会进入长期后台循环。

### 3.2 交互模式

执行：

```bash
elebot agent
```

CLI 会调用 `runtime.run_interactive(...)`，对应 [elebot/runtime/app.py](../elebot/runtime/app.py#L265-L297)。

这时候 runtime 会：

1. 按需启动 `AgentLoop.run()`
2. 调用 `interactive.py` 处理终端输入输出
3. 在退出时统一收尾

关键点是 `manage_agent_loop=False`，说明交互层只负责终端体验，不再托管主循环生命周期。

## 4. `runtime_support.py` 现在负责什么

CLI 侧只保留了一个很薄的辅助层：[elebot/cli/runtime_support.py](../elebot/cli/runtime_support.py#L18-L109)。

它只做三件事：

1. `_load_runtime_config()`
   - 读取配置
   - 处理显式配置路径
   - 应用工作区覆盖
   - 提示废弃配置键
2. `_make_provider()`
   - 调 `providers.factory.build_provider()`
   - 把 provider 配置错误翻译成 CLI 友好提示
3. `_make_runtime()`
   - 调 `ElebotRuntime.from_config()`

所以它不是第二套 runtime，也不是第二套 provider owner，只是 CLI 适配层。

## 5. slash 命令和 CLI 的关系

slash 命令不属于 CLI 根命令系统。

关系是：

```text
CLI 把文本送进主链路
  ↓
AgentLoop 命中 CommandRouter
  ↓
command handler 调 owner API
```

也就是说：

- `/stop`
- `/task`
- `/dream`
- `/status`

这些都不是 `Typer` 子命令，而是 agent 主链路里的文本协议，协议定义在 [elebot/command/builtin.py](../elebot/command/builtin.py#L12-L66)。

## 6. 以后接 Web 或 desktop 时该复用哪里

当前固定原则没有变：

```text
CLI 是一个入口
runtime 是统一底座
```

以后如果接 Web UI、desktop 或其他前端，应该复用 [elebot/runtime/app.py](../elebot/runtime/app.py#L40-L340) 的 `ElebotRuntime`，而不是重新在入口层复制一套装配逻辑。
