# EleBot 整体架构

这篇文档只讲当前默认主链路，不讨论已经删除或不在默认入口里的旧模块。

相关源码：

- [elebot/cli/app.py](../elebot/cli/app.py#L1-L67)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L31-L323)
- [elebot/runtime/models.py](../elebot/runtime/models.py#L8-L43)
- [elebot/bus/queue.py](../elebot/bus/queue.py#L8-L40)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L241-L958)
- [elebot/command/router.py](../elebot/command/router.py#L15-L82)
- [elebot/command/builtin.py](../elebot/command/builtin.py#L11-L58)
- [elebot/cron/service.py](../elebot/cron/service.py#L25-L320)
- [elebot/agent/memory/store.py](../elebot/agent/memory/store.py#L18-L320)
- [elebot/providers/resolution.py](../elebot/providers/resolution.py#L11-L150)
- [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L72)

## 1. 当前主链路

先记住当前真实链路：

```text
用户输入
  ↓
CLI
  ↓
Runtime
  ↓
MessageBus
  ↓
AgentLoop.run() / process_direct()
  ↓
ContextBuilder + Session + Memory
  ↓
AgentRunner
  ↓
Provider / Tools
  ↓
OutboundMessage
  ↓
CLI 渲染
```

如果是 cron 触发，则链路是：

```text
workspace/cron/jobs.json
  ↓
CronService
  ↓
AgentLoop._run_cron_job()
  ↓
agent.process_direct(...)
```

## 2. 当前 owner 边界

### 2.1 `config`

`config` 只保存配置事实：

- 默认模型
- 默认 provider
- provider 凭证
- workspace
- tools 配置

它不再负责 provider 解析。

### 2.2 `providers`

`providers` 现在拆成两层：

- `resolution.py`
  - 负责 provider 选择
- `factory.py`
  - 负责 provider 实例化

### 2.3 `runtime`

`runtime` 是对外复用底座。

它负责：

- 装配 `Bus`
- 装配 provider
- 装配 `AgentLoop`
- 承接生命周期
- 暴露薄控制 API

但它不承载领域业务实现。

### 2.4 `agent`

`AgentLoop` 仍然是主执行 owner。

它负责：

- 消费入站消息
- 串起 session、memory、command、cron、tools
- 调用 `AgentRunner`
- 回写 `OutboundMessage`

### 2.5 `command`

`command` 现在只负责：

- slash 协议
- 路由规则
- handler 组织

### 2.6 `cron`

当前调度 owner 已经固定为：

- `CronSchedule`
- `CronJob`
- `CronService`

模型只通过 `cron` 工具与它交互。

### 2.7 `agent/memory`

记忆系统现在是 package，而不是单文件：

- `store.py`
  - 文件事实和 Dream 历史 owner
- `consolidator.py`
  - token 压缩
- `dream.py`
  - Dream 整理流程

## 3. runtime 为什么存在

当前 runtime 的意义不是再造一个产品入口，而是把入口层共有的装配动作收口。

现在的关系应该理解成：

```text
CLI / Web / desktop
  ↓
ElebotRuntime
  ↓
Bus + provider + AgentLoop
```

## 4. runtime 暴露什么能力

`ElebotRuntime` 现在对外暴露的是一层薄控制 API，例如：

- `interrupt_session()`
- `reset_session()`
- `get_status_snapshot()`
- `trigger_dream()`
- `list_cron_jobs()`
- `remove_cron_job()`
- `get_dream_log()`
- `restore_dream_version()`

真实 owner 仍然在：

- `AgentLoop`
- `CronService`
- `MemoryStore`

## 5. command 为什么还独立存在

`command` 并不是多余的一层。

它解决的是 slash 协议问题：

- 文本命令如何分发
- 不同命令 handler 如何组织
- 帮助文本如何维护

但它不再是业务 owner。

所以当前分层是：

```text
command = 协议层
runtime / agent / cron / memory = 业务 owner
```

## 6. 当前项目最重要的结构事实

当前项目有三条必须记住的事实：

1. 未来多入口统一复用 runtime，而不是重新引入 facade。
2. 调度领域统一从 `CronService` 对外，模型工具只保留 `cron`。
3. Dream 历史统一从 `MemoryStore` 对外，命令层不再知道 `GitStore` 细节。
