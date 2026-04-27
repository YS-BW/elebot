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
- tasks 的自然语言创建、确认后落盘、后台轮询、系统消息触发
- 最小工具调用闭环

### 2.2 当前还没有

- 真正完整的中断能力
- 系统级调度后端
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

后续所有新入口都必须复用这条链路，不能再绕回：

- `facade`
- 入口层自己拼 `Bus + provider + AgentLoop`
- 入口层直接维护一套平行生命周期

### 2.4 当前结构边界

当前已经收口成下面这组 owner 分工：

```text
config      = 只保存配置事实
providers   = provider 元数据、解析、装配、model catalog
runtime     = 统一对外复用入口与生命周期
agent       = 执行循环、上下文装配、会话内控制
command     = slash 命令协议与 handler 组织
tasks       = 任务领域服务与持久化
agent/memory= 记忆存储、压缩与 Dream
utils       = 低层通用小工具
```

### 2.5 当前必须固定下来的事实

- provider 解析入口在 `elebot/providers/resolution.py`
- provider 实例化入口在 `elebot/providers/factory.py`
- 模型目录 owner 在 `elebot/providers/model_catalog.py`
- `runtime` 是未来多入口唯一可复用底座
- `TaskService` 是任务领域统一对外入口
- `MemoryStore` 是 Dream 历史 owner
- 历史唯一来源固定为 `memory/history.jsonl`
- `HISTORY.md` 已不是当前实现的一部分
- skill 管理 owner 在 `agent/skills`
- 裸 `/skill` 已移除，只保留 `/skill list|install|uninstall`
- 首次 `onboard` 默认 provider 是 `deepseek`
- 首次 `onboard` 默认模型是 `deepseek-v4-flash`
- `onboard` 当前会尝试预装两份本地默认 skill 源
- DeepSeek 的 tool-call transcript 协议修复已经固定收口在 provider 层

## 3. 模块完成定义

`PLAN.md` 里的一个模块，只有同时满足下面四项才算完成：

1. 代码已经实现
2. 对应局部测试已经新增或更新，并且实际跑过
3. `docs/` 中对应模块文档已经新增或更新
4. 本文件已经回写当前状态、剩余事项和风险

如果只完成了代码和测试，没有完成文档与计划回写，那么该模块只能标记为：

- `代码实现完成，项目回写未完成`

## 4. 当前优先级

从现在开始，后续优先级固定为：

- `P0`：模块五，真正的中断能力
- `P1`：模块六，多端入口
- `P2`：模块七，多通道能力
- `P3`：模块八，子代理

另外还有两条边界必须固定下来：

- 模块一到模块四已经完成，后续默认只接受缺陷修复、文档同步和必要的小范围事实回写
- 不应把 `status` 面板增强、model catalog 动态化、skill marketplace、WebUI 包装之类事项插到模块五之前

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

后续边界：

- 不重新引入 `facade`
- 不在 CLI / Web / desktop 里复制装配逻辑
- 不让入口层直接 new 一整串底层对象

### 5.2 模块二：结构收口

当前状态：`已完成`

已经落地的事实：

- `config` 退回纯配置模型
- provider 解析移动到 `providers/resolution.py`
- `runtime` 暴露统一复用的薄控制 API
- `command` 拆成协议层和 handlers
- `AgentLoop` 暴露公开 owner API
- `TaskService` 成为任务领域统一对外入口
- `TaskStore` 退回纯持久化仓库
- `agent/memory` 从单文件拆成 package
- 默认工具注册从 `AgentLoop` 内部初始化流程抽离

后续边界：

- slash 命令不再直接碰底层私有状态
- 未来 Web / desktop / channel 不应绕过 runtime 直接拼 `AgentLoop`

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

后续边界：

- 不恢复 Codex / Copilot provider
- 不恢复 CLI 登录入口
- 不恢复 `HISTORY.md` 兼容路径

### 5.4 模块四：全局 Skill 管理收口

当前状态：`已完成`

已经落地的事实：

- `SkillRegistry` 退回只读 owner
- `SkillManager` 成为 skill 文件系统写操作 owner
- skill 安装支持本地目录、直接下载链接、Git 链接、GitHub `tree` 子目录链接
- skill 协议固定为 `/skill list|install|uninstall`
- 裸 `/skill` 已移除

后续边界：

- 当前不做 marketplace
- 当前不做默认技能集系统
- 当前不做远端搜索
- 动态感知仍然依赖每轮 `SkillRegistry.scan()`，不是热重载守护进程

## 6. 模块五：真正的中断能力

当前状态：`P0 / 下一优先级`

### 6.1 为什么现在先做它

模块一到模块四已经把主链路和结构边界收干净了，当前最大的缺口已经不是“职责混乱”，而是“交互不可真正中断”。

如果这一步不先做，后面的多端入口、多通道、子代理都会直接继承同一个问题：

- 用户无法明确打断当前长回复
- 工具执行取消语义不清晰
- 中断和失败容易混在一起
- session 恢复语义会继续模糊

### 6.2 目标

这一步只解决单 runtime、单会话下的真实 interrupt，不扩未来能力。

必须达成的结果：

- 用户在流式回复中途可以打断
- 工具执行过程中可以打断
- 中断状态和失败状态明确区分
- 中断后 session 不损坏
- 中断后还能继续原会话

### 6.3 当前基础

当前已经具备的前置条件：

- `runtime` 已统一装配主链路
- `AgentLoop` 已经有会话级活跃任务映射
- `AgentLoop.cancel_session_tasks()` 已成为公开 owner API
- session 已经有运行中 checkpoint 恢复逻辑

### 6.4 本模块固定边界

这一步不做：

- 多人协作式中断
- 子代理级联中断
- 跨端同步中断状态
- 系统级后台调度
- Web / desktop 入口扩展

### 6.5 实现重点

建议统一三类中断语义：

```text
user_interrupt
tool_interrupt
runtime_interrupt
```

实现重点固定为：

- `CLI`
  - 把用户中途停止动作送进统一 interrupt 链路
- `runtime`
  - 暴露统一中断入口，不让入口层自己拼取消逻辑
- `AgentLoop`
  - 接受显式 interrupt 信号
  - 把中断分发到当前推理与工具执行
- `AgentRunner`
  - 区分普通错误和取消错误
- `session`
  - checkpoint 明确记录“本轮被中断”
  - 恢复时不把中断误判成失败

### 6.6 验收标准

- 用户能明确中断当前长回复
- 中断不会把 session 历史打坏
- 工具执行被中断时能给出明确状态
- 中断后可以继续在原 session 聊下去
- 中断状态不会被显示成普通失败

### 6.7 完成前必须补齐的回写

- 更新 `docs/RUNTIME.md`
- 更新 `docs/CLI.md`
- 更新 `docs/SESSION.md`
- 如有必要，补一份专门讲 interrupt 的模块文档
- 回写本文件中的状态、风险和剩余事项

## 7. 模块六：多端入口

当前状态：`P1 / 未开始`

### 7.1 目标

在模块五稳定后，把 EleBot 从“只有终端入口”推进成“多入口共享同一个 runtime”。

### 7.2 固定原则

未来如果接：

- Web
- desktop
- 其它本地入口

都应该复用 `ElebotRuntime` 暴露的统一入口，而不是：

- 直接拼 `MessageBus`
- 直接拼 `AgentLoop`
- 再造一层新的 facade

### 7.3 验收标准

- CLI 不再是唯一入口形态
- 新入口可以接入统一 runtime
- 不同入口不会各自维护一套 agent 运行逻辑
- 模块五的中断语义在新入口下保持一致

## 8. 模块七：多通道能力

当前状态：`P2 / 未开始`

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

通道层只负责：

- 外部协议转 `InboundMessage`
- `OutboundMessage` 转外部协议

通道层不负责：

- 主执行逻辑
- session 内状态修改
- provider 选择

### 8.3 验收标准

- 通道层只做协议适配
- 主链路仍然是 `Bus -> AgentLoop`
- 不同通道不会分叉出不同 agent 逻辑
- 模块五的中断语义在通道侧仍然成立

## 9. 模块八：子代理

当前状态：`P3 / 未开始`

### 9.1 目标

最后才考虑重新设计子代理，不恢复旧实现，也不把它做成当前主链路依赖。

### 9.2 固定原则

只有在前面几层稳定后，才开始讨论：

- 子代理是否共享主 session
- 子代理是否拥有独立工具权限
- 结果如何结构化返回主代理
- 中断如何传播

### 9.3 验收标准

- 子代理不是默认主链路依赖
- 权限、上下文、结果归并边界清楚
- 中断和失败语义与主代理一致

## 10. 当前风险

当前最明确的风险只有这些：

1. 中断语义还没有统一，`/stop` 目前本质上仍然是粗粒度取消。
2. `runtime` 目前是进程内统一入口，不是独立后台服务。
3. `status` 现在只是 CLI 侧状态查看，不是统一运行面板。
4. model catalog 采用静态目录，模型事实变化需要显式更新仓库。
5. 脏工作区下继续推进时，最容易把历史讨论误当成当前代码事实。

## 11. 实际执行顺序

后续实际开工顺序固定为：

1. 先完成模块五 interrupt
2. 跑通 interrupt 对 CLI 主链路的完整验证
3. 再做一个最小多端入口验证 runtime 复用
4. 然后才考虑通道
5. 最后才考虑子代理

## 12. 一句话原则

下一阶段不要急着继续扩入口或加高级能力，而是先把 EleBot 做成：

```text
一个结构边界清楚、可中断、可复用的统一 runtime
```
