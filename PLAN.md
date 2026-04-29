# EleBot 后续实现计划

> 这份文件是项目内部计划，不放进 `docs/`，也不当成用户文档。

## 1. 计划目标

EleBot 当前阶段的目标不变：

- 做成 nanobot 风格的终端 AI 助手
- 先把已有核心能力做清楚
- 不扩未来能力
- 不做兼容层
- 不做迁移脚本
- 不保留过渡实现

项目推进时，优先遵守这三条：

- 先相信代码事实，不按历史讨论想象当前实现
- 代码、测试、文档、计划必须保持一致
- 一次只推进一个模块，不跨方向混做

## 2. 当前代码事实

### 2.1 当前已经具备

- 终端主链路闭环
- 进程内 `runtime` 装配与生命周期管理
- 基础多轮对话
- 流式输出
- session 持久化
- workspace 模板初始化
- 全局 skills 扫描与 prompt 注入
- skill 的安装、卸载、列表管理
- `cron` 调度的 `add / list / remove`
- 最小工具调用闭环
- DeepSeek tool-call transcript 的 `reasoning_content` 协议修复
- 单 runtime、单会话下的真实 interrupt

### 2.2 当前还没有

- 系统级调度后端
- `heartbeat`
- 正式的 Web / desktop 多端入口
- 多通道能力
- 重新设计后的子代理体系

### 2.3 当前主链路

当前真实启动链路已经固定为：

```text
CLI
  ↓
runtime
  ↓
Bus
  ↓
AgentLoop
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

### 2.4 当前结构边界

当前已经收口成下面这组 owner 分工：

```text
config        = 只保存配置事实
providers     = provider 元数据、解析、装配、model catalog
runtime       = 统一对外复用入口与生命周期
agent         = 执行循环、上下文装配、会话内控制
command       = slash 命令协议与 handler 组织
cron          = 调度模型、持久化、定时唤醒、执行状态
agent/memory  = 记忆存储、压缩与 Dream
utils         = 低层通用小工具
```

### 2.5 当前必须固定下来的事实

- provider 解析入口在 `elebot/providers/resolution.py`
- provider 实例化入口在 `elebot/providers/factory.py`
- 模型目录 owner 在 `elebot/providers/model_catalog.py`
- `runtime` 是未来多入口唯一可复用底座
- `runtime` 对外不再暴露 `cancel_session_tasks()`，用户级中断入口固定为 `interrupt_session()`
- 当前唯一调度 owner 是 `CronService`
- 调度存储路径固定为 `workspace/cron/jobs.json`
- 模型侧唯一调度工具固定为 `cron`
- `/task` 已彻底移除，也不新增 `/cron` slash 命令
- `MemoryStore` 是 Dream 历史 owner
- 历史唯一来源固定为 `memory/history.jsonl`
- `HISTORY.md` 已不是当前实现的一部分
- skill 管理 owner 在 `agent/skills`
- 裸 `/skill` 已移除，只保留 `/skill list|install|uninstall`
- agent 默认工具现在已经包含 `list_skills` / `install_skill` / `uninstall_skill` / `cron`
- 首次 `onboard` 默认 provider 是 `deepseek`
- 首次 `onboard` 默认模型是 `deepseek-v4-flash`
- `main` 分支的 `onboard` 不再预装任何业务 skill
- DeepSeek 的 tool-call transcript 协议修复固定收口在 provider 层
- `Ctrl+C` 仍然退出交互进程
- `Esc` 现在是当前交互轮次的真实中断键
- `Esc` 的监听已固定为“孤立按键判定”，不会把终端控制序列残留到下一次输入
- `/stop` 已彻底移除，不再属于命令协议
- interrupted 历史只保留结构化事实，不保留半截自然语言
- `/new` 现在会清空短期消息和运行态 `metadata`

## 3. 模块完成定义

`PLAN.md` 里的一个模块，只有同时满足下面四项才算完成：

1. 代码已经实现
2. 对应局部测试已经新增或更新，并且实际跑过
3. `docs/` 中对应模块文档已经新增或更新
4. 本文件已经回写当前状态、剩余事项和风险

## 4. 当前优先级

从现在开始，后续优先级固定为：

- `P0`：模块七，多端入口
- `P1`：模块八，多通道能力
- `P2`：模块九，子代理

另外还有两条边界必须固定下来：

- 模块一到模块六已经完成，后续默认只接受缺陷修复、文档同步和必要的小范围事实回写
- 不应把 status 面板增强、model catalog 动态化、skill marketplace、WebUI 包装之类事项插到模块七之前

## 5. 已完成模块回顾

### 5.1 模块一：进程内 Runtime 收口

当前状态：`已完成`

已经落地的事实：

- 新增 `elebot/runtime/`
- CLI 通过 `ElebotRuntime.from_config()` 统一装配主链路
- `RuntimeLifecycle` 统一承接 `start / wait / stop / close`
- 交互模式里，`AgentLoop` 生命周期已经回收到 runtime
- `elebot/facade.py` 已移除
- provider 装配入口已收口到 `elebot/providers/factory.py`

### 5.2 模块二：结构收口

当前状态：`已完成`

已经落地的事实：

- `config` 退回纯配置模型
- provider 解析移动到 `providers/resolution.py`
- `runtime` 暴露统一复用的薄控制 API
- `command` 拆成协议层和 handlers
- `AgentLoop` 暴露公开 owner API
- `agent/memory` 从单文件拆成 package
- 默认工具注册从 `AgentLoop` 内部初始化流程抽离

### 5.3 模块三：结构续收口

当前状态：`已完成`

已经落地的事实：

- `providers` 收口了 model catalog
- OAuth provider 整套移除
- CLI 拆成真实入口层
- `ContextBuilder` 退回纯上下文装配器
- `utils/helpers.py` 已删除并按 owner 分流
- `MemoryStore` 不再保留 `HISTORY.md` 兼容逻辑
- `pyproject.toml` 与 `uv.lock` 已同步到当前依赖状态

### 5.4 模块四：全局 Skill 管理收口

当前状态：`已完成`

已经落地的事实：

- `SkillRegistry` 退回只读 owner
- `SkillManager` 成为 skill 文件系统写操作 owner
- skill 安装支持本地目录、直接下载链接、Git 链接、GitHub `tree` 子目录链接
- skill 协议固定为 `/skill list|install|uninstall`
- 裸 `/skill` 已移除
- 本地 skill 安装在类 Unix 平台默认使用符号链接，在 Windows 平台使用复制目录
- agent 已可直接通过内置 tools 调用 skill 的安装、卸载和列表能力

### 5.5 模块五：真正的中断能力

当前状态：`已完成`

已经落地的事实：

- `Ctrl+C` 保持退出当前交互进程
- `Esc` 只在活跃回复期间生效
- `runtime` 新增统一控制面：`interrupt_session(session_id, reason="user_interrupt")`
- `AgentLoop.interrupt_session()` 已成为统一会话级中断入口
- `_dispatch()` 已把显式取消收口成 interrupted，而不是普通 error
- 中断终态固定为 `已中断当前回复。`
- session checkpoint 已固定 interrupted 语义
- `/stop` 已删除，不新增 `/interrupt` 或 `/cancel`

### 5.6 模块六：用 `cron` 整体替换 `task` 模块

当前状态：`已完成`

已经落地的事实：

- 旧 `tasks` 模块已经从主链路删除
- 新增 `elebot/cron/types.py`
- 新增 `elebot/cron/service.py`
- 新增统一调度工具 `elebot/agent/tools/cron.py`
- `AgentLoop` 改为持有 `CronService`
- `ElebotRuntime` 删除 `list_tasks/remove_task`，改成 `list_cron_jobs/remove_cron_job`
- `/task` 已彻底移除，也不新增 `/cron`
- `templates/agent/task_rules.md` 已替换为 `templates/agent/cron_rules.md`
- `workspace/cron/jobs.json` 成为唯一调度状态文件
- 这轮只做 `cron`，不引入 `heartbeat`

### 5.7 模块六后的缺陷修复：CLI 输入污染与 `/new` 状态清理

当前状态：`已完成`

已经落地的事实：

- `EscInterruptWatcher` 不再把首个 `ESC` 字节直接当成中断
- `ESC [ 38 ; 1 R` 这类 CPR/ANSI 回复会被完整消费，不再把 `[38;1R` 残留到下一次输入
- `PromptSession` 的 output 已显式禁用 CPR，避免普通对话轮次把 `[23;1R` 漏成伪输入
- `/new` 现在会显式清空：
  - `messages`
  - `last_consolidated`
  - `session.metadata`
- `/new` 清理后仍然沿用原 session key 和会话文件，不额外创建新文件
- tool-call 前的短前缀文本现在会按进度行显示，不再单独展开成短 assistant 回复块
- cron 等后台消息在用户正在输入时会先暂存，等当前输入提交后再顺序显示

## 6. 当前风险

当前最明确的风险只有这些：

1. interrupt 现在只保证 TTY 交互下的 `Esc`，还没有扩到未来多端入口
2. `runtime` 目前是进程内统一入口，不是独立后台服务
3. `cron` 仍然是应用内调度，不是系统级调度
4. model catalog 采用静态目录，模型事实变化需要显式更新仓库
5. 脏工作区下继续推进时，最容易把历史讨论误当成当前代码事实

## 7. 模块七：多端入口

当前状态：`P0 / 未开始`

### 7.1 目标

把 EleBot 从“只有终端入口”推进成“多入口共享同一个 runtime”。

### 7.2 固定原则

未来如果接：

- Web
- desktop
- 其它本地入口

都应该复用 `ElebotRuntime` 暴露的统一入口，而不是：

- 直接拼 `MessageBus`
- 直接拼 `AgentLoop`
- 再造一层新的 facade

## 8. 模块八：多通道能力

当前状态：`P1 / 未开始`

### 8.1 目标

把外部消息入口重新设计成协议适配层，而不是恢复旧 frozen 代码。

### 8.2 固定原则

后续多通道应该按下面的主链路接入：

```text
Channel Adapter
  ↓
Bus
  ↓
AgentLoop
```

## 9. 模块九：子代理

当前状态：`P2 / 未开始`

### 9.1 目标

最后才考虑重新设计子代理，不恢复旧实现，也不把它做成当前主链路依赖。

## 10. 实际执行顺序

后续实际开工顺序固定为：

1. 先做模块七，多端入口的最小 runtime 复用验证
2. 再做模块八，多通道协议适配
3. 最后才考虑模块九，子代理
4. 模块一到模块六只做缺陷修复、测试补齐、文档同步

## 11. 一句话原则

下一阶段不要急着继续扩高级能力，而是先把 EleBot 做成：

```text
一个可中断、可复用、可接多入口的统一 runtime
```
