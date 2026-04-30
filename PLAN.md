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
- `cron` 调度的 CRUD 四工具协议
- 最小工具调用闭环
- DeepSeek tool-call transcript 的 `reasoning_content` 协议修复
- 单 runtime、单会话下的真实 interrupt
- `serve stdio` 第二入口
- `channels/` 适配层与 `websocket / weixin` 两种内置 channel

### 2.2 当前还没有

- 系统级调度后端
- `heartbeat`
- 正式的 Web / desktop 多端入口
- 面向公网的 channel 安全方案
- 多平台 channel 生态
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

如果是 `serve stdio`，则链路是：

```text
stdin JSONL
  ↓
runtime.run_once()
  ↓
AgentLoop.process_direct()
```

如果是 websocket channel，则链路是：

```text
WebSocketChannel
  ↓
Bus
  ↓
AgentLoop.run()
  ↓
Bus
  ↓
ChannelManager
  ↓
WebSocketChannel
```

如果是个人微信 channel，则链路是：

```text
Weixin HTTP long-poll
  ↓
WeixinChannel
  ↓
Bus
  ↓
AgentLoop
  ↓
Bus
  ↓
ChannelManager
  ↓
WeixinChannel
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
- 当前第二入口验证固定为 `serve stdio`
- `runtime` 对外不再暴露 `cancel_session_tasks()`，用户级中断入口固定为 `interrupt_session()`
- 当前 `serve websocket` 也直接复用同一份 `ElebotRuntime`
- 当前 `serve channels` 也直接复用同一份 `ElebotRuntime`
- channel owner 固定在 `elebot/channels`
- 当前内置 channel 固定为 `websocket` 和 `weixin`
- 当前唯一调度 owner 是 `CronService`
- 调度存储路径固定为 `workspace/cron/jobs.json`
- 模型侧调度工具固定为 `cron_create / cron_list / cron_delete / cron_update`
- `/task` 已彻底移除，也不新增 `/cron` slash 命令
- `MemoryStore` 是 Dream 历史 owner
- 历史唯一来源固定为 `memory/history.jsonl`
- `HISTORY.md` 已不是当前实现的一部分
- skill 管理 owner 在 `agent/skills`
- 裸 `/skill` 已移除，只保留 `/skill list|install|uninstall`
- agent 默认工具现在已经包含 `list_skills` / `install_skill` / `uninstall_skill` / `cron_create` / `cron_list` / `cron_delete` / `cron_update`
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
- active turn 的 CLI 渲染现在已收口为单写入器；tool hint 不再走 prompt 重绘通道
- `serve stdio` 和 `websocket` 共用一套外部事件名：`ready / progress / delta / stream_end / message / error`
- CLI 根命令当前固定为：`onboard / agent / channels / serve / status`
- 当前已经有 `elebot channels login weixin`
- 微信 channel 第一版固定为个人微信私聊文本入口，不做流式、不做群聊、不做媒体

## 3. 模块完成定义

`PLAN.md` 里的一个模块，只有同时满足下面四项才算完成：

1. 代码已经实现
2. 对应局部测试已经新增或更新，并且实际跑过
3. `docs/` 中对应模块文档已经新增或更新
4. 本文件已经回写当前状态、剩余事项和风险

## 4. 当前优先级

从现在开始，后续优先级固定为：

- `P0`：模块九，子代理
- `P1`：模块七/八后的缺陷修复和文档同步
- `P2`：系统级调度与 `heartbeat`

另外还有两条边界必须固定下来：

- 模块一到模块八已经完成，后续默认只接受缺陷修复、文档同步和必要的小范围事实回写
- 不应把 status 面板增强、model catalog 动态化、skill marketplace、WebUI 包装之类事项插到模块九之前

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
- 新增调度工具文件 `elebot/agent/tools/cron.py`
- `AgentLoop` 改为持有 `CronService`
- `ElebotRuntime` 删除 `list_tasks/remove_task`，改成 `list_cron_jobs/remove_cron_job`
- `/task` 已彻底移除，也不新增 `/cron`
- `templates/agent/task_rules.md` 已替换为 `templates/agent/cron_rules.md`
- `workspace/cron/jobs.json` 成为唯一调度状态文件
- 这轮只做 `cron`，不引入 `heartbeat`
- 当前模型侧协议已经进一步收口为四个 CRUD 工具：
  - `cron_create`
  - `cron_list`
  - `cron_delete`
  - `cron_update`
- 模型侧不再暴露：
  - `action`
  - `name`
  - `cron_expr`
  - `tz`
  - `message / prompt / command`

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
- 所有模型可见文本现在都走 assistant 正文通道；`↳` 只保留 tool hint、工具过程提示和本地控制提示
- cron 等后台消息在用户正在输入时会先暂存，等当前输入提交后再顺序显示

### 5.8 模块六后的缺陷修复：CLI 渲染状态机收口

当前状态：`已完成`

已经落地的事实：

- active turn 期间的 spinner、正文流、tool hint 现在统一交给同一个 `StreamRenderer` 输出
- 当前轮次的 `↳` 提示不再走 `prompt_toolkit.run_in_terminal()`，只在等待输入时保留 prompt-safe 打印
- `tool hint` 在 bus 中已经改成独立的 `_tool_transition` 事件，不再和普通 `_progress` 混在一起
- `StreamRenderer` 的 spinner 生命周期已改成“单实例、按 phase 切换”，不再在一次工具轮里反复创建新 spinner 对象
- 工具轮现在会先结束当前正文流，再输出 `↳ tool(...)`，然后连续进入下一段 thinking，不再出现第一段 spinner 收尾后的可见空窗
- 当前轮次里的中断提示 `正在中断当前回复...` 也已经走 renderer 通道，避免 active turn 内再触发 prompt 重绘

## 6. 当前风险

当前最明确的风险只有这些：

1. interrupt 现在只保证 TTY 交互下的 `Esc`，还没有扩到未来多端入口
2. `runtime` 目前是进程内统一入口，不是独立后台服务
3. `cron` 仍然是应用内调度，不是系统级调度
4. model catalog 采用静态目录，模型事实变化需要显式更新仓库
5. 脏工作区下继续推进时，最容易把历史讨论误当成当前代码事实

## 7. 模块七：多端入口

当前状态：`已完成`

### 7.1 目标

把 EleBot 从“只有终端入口”推进成“多入口共享同一个 runtime”。

### 7.2 固定原则

这一轮已经落地的事实：

- 新增 `elebot serve stdio`
- `stdio` 入口只做 transport 包装
- `stdio` 入口直接复用：
  - `ElebotRuntime.run_once()`
  - `interrupt_session()`
  - `reset_session()`
  - `get_status_snapshot()`
- 这条入口没有重新装配 `MessageBus + AgentLoop + provider`

## 8. 模块八：多通道能力

当前状态：`已完成（第一版）`

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

这一轮已经落地的事实：

- 新增 `elebot/channels/base.py`
- 新增 `elebot/channels/manager.py`
- 新增 `elebot/channels/websocket.py`
- 新增 `elebot/channels/weixin.py`
- 新增 `elebot channels login weixin`
- 新增 `elebot serve channels`
- `serve websocket` 通过 `runtime.start() + ChannelManager` 闭环
- 第一版 `websocket` 没有照搬 nanobot 的随机 `chat_id`
- 第一版 `websocket` 使用稳定 `chat_id`，默认等于 `client_id`
- 第一版 `weixin` 使用稳定会话键 `weixin:{from_user_id}`
- 第一版 `weixin` 只做个人微信私聊文本收发
- 当前不做 TLS、token issuance、离线消息队列

## 9. 模块九：子代理

当前状态：`P0 / 未开始`

### 9.1 目标

最后才考虑重新设计子代理，不恢复旧实现，也不把它做成当前主链路依赖。

## 10. 实际执行顺序

后续实际开工顺序固定为：

1. 先做模块九，子代理
2. 模块七和模块八只做缺陷修复、测试补齐、文档同步
3. 系统级调度与 `heartbeat` 另开模块，不回退到旧 task 体系
4. 模块一到模块八默认不再做结构性返工

## 11. 一句话原则

下一阶段不要急着继续扩高级能力，而是先把 EleBot 做成：

```text
一个可中断、可复用、可接多入口的统一 runtime
```
