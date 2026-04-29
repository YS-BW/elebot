# CRON

这篇文档只讲 EleBot 当前已经落地的 `cron` 调度实现，不讨论未来的 `heartbeat`、系统 daemon 或多进程调度器。

相关源码：

- [elebot/cron/types.py](../elebot/cron/types.py#L9-L138)
- [elebot/cron/service.py](../elebot/cron/service.py#L25-L320)
- [elebot/agent/tools/cron.py](../elebot/agent/tools/cron.py#L14-L250)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L256-L298)
- [elebot/agent/loop.py](../elebot/agent/loop.py#L520-L589)
- [elebot/config/paths.py](../elebot/config/paths.py#L38-L45)
- [elebot/runtime/app.py](../elebot/runtime/app.py#L184-L204)

## 1. 当前已经没有旧 `tasks`

当前 `main` 分支已经彻底放弃旧任务体系：

- 没有 `TaskService`
- 没有 `ScheduledTask`
- 没有 `/task`
- 没有 `propose_task / create_task / list_tasks / update_task / remove_task`
- 不再读取 `~/.elebot/tasks/tasks.json`

当前唯一的调度 owner 是：

```text
CronSchedule / CronJob / CronService
```

## 2. 存储路径

当前 cron 存储固定在工作区内：

```text
~/.elebot/workspace/cron/jobs.json
```

路径 helper 在 [elebot/config/paths.py](../elebot/config/paths.py#L38-L45)。

这意味着：

- cron 状态和当前 workspace 绑定
- 不再使用 `~/.elebot/tasks/tasks.json`
- 不做旧任务文件迁移

## 3. 核心对象

### 3.1 `CronSchedule`

定义在 [elebot/cron/types.py](../elebot/cron/types.py#L9-L26)。

当前固定支持三种调度方式：

- `kind="at"`
- `kind="every"`
- `kind="cron"`

### 3.2 `CronJob`

定义在 [elebot/cron/types.py](../elebot/cron/types.py#L97-L138)。

当前 job 会固定记录：

- `id`
- `name`
- `enabled`
- `schedule`
- `payload`
- `state`
- `created_at_ms`
- `updated_at_ms`
- `delete_after_run`

### 3.3 `CronService`

定义在 [elebot/cron/service.py](../elebot/cron/service.py#L25-L320)。

它当前负责：

- 读写 `jobs.json`
- 校验调度参数
- 计算 `next_run_at_ms`
- 后台唤醒
- 执行 due jobs
- 维护最近运行状态
- `add / list / remove`

## 4. 模型侧现在只剩一个工具：`cron`

工具定义在 [elebot/agent/tools/cron.py](../elebot/agent/tools/cron.py#L120-L250)。

当前固定协议是：

- `cron(action="add", ...)`
- `cron(action="list")`
- `cron(action="remove", job_id="...")`

`add` 当前只支持三种调度参数：

- `instruction`
- `every_seconds`
- `cron_expr`
- `at`

并且还有三条固定规则：

- `instruction` 是实际执行内容，`name` 只是可选展示标题
- `tz` 只能和 `cron_expr` 一起使用
- `at` 接收 ISO 时间；没有 offset 时使用 agent 默认时区
- 一次性 `at` job 默认 `delete_after_run=True`

## 5. 运行时闭环现在怎么走

当前真实链路是：

```text
模型调用 cron(action="add")
  ↓
CronTool
  ↓
CronService.add_job()
  ↓
workspace/cron/jobs.json
  ↓
CronService 到点唤醒
  ↓
AgentLoop._run_cron_job()
  ↓
agent.process_direct(...)
  ↓
session_key = cron:<job_id>
```

这里最重要的事实在 [elebot/agent/loop.py](../elebot/agent/loop.py#L542-L589)：

- `CronService` 只负责调度
- 真正执行仍然走 `AgentLoop.process_direct(...)`
- cron 触发时会告诉模型“这是已到点的 scheduled instruction，不是实时用户输入”

## 6. Runtime 现在怎么管 cron

`ElebotRuntime` 当前只暴露薄委托 API：

- `list_cron_jobs(include_disabled=False)`
- `remove_cron_job(job_id)`

对应实现见 [elebot/runtime/app.py](../elebot/runtime/app.py#L184-L204)。

这层只做 owner 委托，不在 runtime 内承载调度逻辑。

## 7. 当前明确不做什么

这一轮固定不做：

- `heartbeat`
- `/cron` slash 命令
- `/task` 兼容命令
- 旧 `tasks.json` 迁移
- `update / enable / disable / run-now` 的模型工具协议

当前用户侧人工管理 cron，还不是通过 slash 命令，而是通过模型调用 `cron` 工具。
