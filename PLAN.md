# EleBot 后续实现计划

> 这份文件是项目内部的后续实现计划，不放进 `docs/`，也不当成用户文档。

## 1. 计划目标

当前 EleBot 已经具备终端主链路、skills、tasks 和基础工具闭环。  
下一阶段不再优先扩展“更多小功能”，而是把产品形态从“终端内运行的 agent”推进到“可常驻、可中断、可接多入口的 runtime”。

这份计划只覆盖下面 5 个方向：

1. 系统级后台运行
2. 真正的中断能力
3. 多端入口
4. 多通道能力
5. 子代理

已经明确暂缓的方向：

- 系统级调度后端
- 主动唤醒
- `cron` / `launchd` / Windows Task Scheduler 适配

## 1.1 模块完成定义

从现在开始，`PLAN.md` 中每个模块的“完成”都按统一标准判断：

1. 代码已经实现
2. 对应局部测试已经新增或更新，并且实际跑过
3. `docs/` 中对应模块文档已经新增或更新
4. 本文件已经回写：
   - 当前完成状态
   - 剩余事项
   - 新风险

如果只完成了代码和测试，没有完成文档与计划回写，那么该模块只能标记为：

- `代码实现完成，项目回写未完成`

不能直接标记成“完成”。

## 2. 总优先级

当前建议的推进顺序固定为：

```text
后台 runtime
  ↓
中断能力
  ↓
多端入口
  ↓
多通道能力
  ↓
子代理
```

原因不是“功能想象空间”，而是依赖关系：

- 没有独立 runtime，后面所有入口都只是壳
- 没有稳定 interrupt，多端交互体验会很差
- 多通道本质上比 Web / desktop 更复杂
- 子代理会把上下文和控制流复杂度推到最高，必须最后做

---

## 3. 模块一：系统级后台运行

### 3.0 当前状态

当前状态：`已完成`

本次已完成：

- 新增 `elebot/runtime/`
- CLI 改为通过 runtime 装配并启动 `AgentLoop`
- runtime 生命周期被单独抽出
- 交互模式的 `AgentLoop` 生命周期也已回收到 runtime，CLI 交互层不再重复 stop / close 主循环
- provider 装配入口已收口到 `elebot/providers/factory.py`
- runtime 已直接依赖 provider factory，不再通过 `facade` 复用装配逻辑
- `elebot/facade.py` 与顶层 `Elebot` / `RunResult` 导出已移除
- 对应 CLI / runtime 测试已新增并通过
- `docs/RUNTIME.md` 已补齐当前实现教程
- `docs/CLI.md`、`docs/ARCHITECTURE.md`、`docs/README.md` 已同步到当前启动链路

第一阶段完成定义已经满足：

1. 代码已经实现
2. 局部测试已经新增并实际跑过
3. `docs/` 已新增对应模块文档
4. 本文件已经回写当前状态、剩余事项和风险

模块一现在可以按项目定义标记为完成。

### 3.0.1 当前代码事实补充

围绕模块一的主链路收口，当前又有三条必须记住的事实：

- provider 装配入口现在在 `elebot/providers/factory.py`，不再挂在 `facade` 下
- `runtime` 直接复用 provider factory，后续入口不应该再复制一套装配逻辑
- 以后如果做 Web / desktop / channel，也应该基于 `runtime`，不要重新引入 `facade` 形态

这里的“完成”含义是：

- 当前计划要求的进程内 runtime 分层已经落地
- CLI 已经通过统一 runtime 入口启动主链路
- 生命周期入口已经从 CLI 逻辑里抽出

下面这些不是当前模块未完成项，而是明确留给后续模块或后续阶段的边界：

- 独立 daemon 入口
- runtime 与前台交互入口的进一步解耦
- 系统级守护接入

### 3.1 目标

把当前只依赖 `elebot agent` 前台进程的实现，收口成一个可独立运行的后台 runtime。

目标不是一上来就做系统级服务管理，而是先把代码结构调整到：

```text
CLI 只是入口
核心 agent/runtime 可以独立常驻
```

### 3.2 当前问题

当前代码事实：

- 已经有 `elebot/runtime/` 负责装配 `Bus`、provider 和 `AgentLoop`
- CLI 已经不再直接 new 出所有运行时对象
- 但 runtime 仍然只能通过当前 CLI 进程启动

这会导致：

- 任务系统仍然不能脱离当前终端进程存在
- 后面 Web / desktop 入口还没有独立 runtime 可挂接
- 当前 runtime 仍然只是进程内分层，不是系统级守护进程

### 3.3 本阶段要做什么

第一阶段只做 runtime 分层，不做系统守护进程注册。

建议拆出下面这层：

```text
elebot/runtime/
  __init__.py
  app.py
  lifecycle.py
  state.py
```

职责建议：

- `app.py`
  - 组装 `Bus`、provider、`AgentLoop`
  - 暴露统一启动 / 停止入口
- `lifecycle.py`
  - 管理后台任务、关闭流程、异常传播
- `state.py`
  - 保存 runtime 级共享状态，例如运行标记、活跃会话映射、后台服务句柄

当前代码事实对应关系已经落地为：

- `app.py`
  - 已负责装配 `Bus`、provider、`AgentLoop`
  - 已暴露 `run_once()`、`run_interactive()`、`start()`、`wait()`、`stop()`、`close()`
- `lifecycle.py`
  - 已负责后台主循环的启动、等待、关闭与状态回收
- `state.py`
  - 已保存 `config`、`bus`、`provider`、`agent_loop`、`serve_task`、`started`

也就是说，这一阶段不再是“建议结构”，而是已经按当前实现落地。

### 3.4 当前边界

这一步不要做：

- `launchd`
- Windows Service
- `systemd`
- 托盘
- 菜单栏

这里只把“进程内结构”整理对。

### 3.5 验收标准

- `elebot agent` 不再自己直接拼所有运行时对象
- CLI 可以调用统一 runtime 启动入口
- runtime 可以在不依赖交互输入循环的情况下独立启动和停止
- `tasks`、`skills`、`Bus`、`AgentLoop` 生命周期归一

当前验收结论：

- 已满足

这里的“生命周期归一”按当前模块定义理解为：

- CLI 不再直接管理主链路装配
- runtime 统一承接启动 / 等待 / 停止 / 关闭入口

它不要求本轮就落到 daemon 或系统服务。

### 3.6 后续边界

模块一完成后，后续仍然有几条明显边界，但它们不阻塞当前模块结项：

1. 第二阶段
  - 增加独立 runtime 常驻入口，例如 `elebot daemon`
  - 让 runtime 不再依赖 CLI 交互循环才有存在意义
2. 第三阶段
   - 再评估是否接系统级守护
   - 这里才进入 `launchd` / `systemd` / Windows Service 的范围

### 3.7 当前风险

当前模块虽然可以结项，但还留着几个代码层风险：

1. `run_interactive()` 目前仍然把 `agent_loop` 和 `bus` 交给 `interactive.py`，说明终端交互生命周期还没有完全收口到 runtime。
2. 现在的 runtime 只有进程内抽象，没有独立命令入口，因此“系统级后台运行”仍然只是完成了分层准备，不是产品能力完成。
3. `RuntimeState` 当前只保存最小状态，没有显式的错误态、关闭原因或更细粒度运行指标，后续做 daemon 时大概率还要补。

---

## 4. 模块二：真正的中断能力

### 4.1 目标

把当前 `/stop` 这种粗粒度“取消活跃任务”，推进成真正的交互级 interrupt。

当前要解决的是：

- 用户在回复流中途打断
- 工具执行过程中打断
- 中断后状态不乱
- 中断后还能继续同一会话

### 4.2 当前问题

当前已有：

- `/stop` 能取消当前会话活跃任务
- `AgentLoop` 里有活跃任务映射
- session 有 checkpoint 恢复能力

但仍然缺：

- 正在流式输出时的细粒度中断语义
- 工具调用中的取消传播
- 中断后的统一状态落盘
- “中断”和“失败”之间的明确区分

### 4.3 本阶段要做什么

建议先定义统一的中断语义：

```text
user_interrupt
tool_interrupt
runtime_interrupt
```

实现重点：

- `AgentLoop`
  - 接受显式 interrupt 信号
  - 能把中断分发到当前活跃推理 / 工具执行任务
- `AgentRunner`
  - 区分正常错误和取消错误
  - 中断时保留最小可恢复上下文
- `Session`
  - checkpoint 明确记录“本轮被中断”
- `CLI`
  - 后续可以接键盘级中断或 UI 按钮中断

### 4.4 当前边界

这一阶段不追求：

- 多人协作式中断
- 子代理级联中断
- 跨端同步中断状态

先把单 runtime、单会话的中断打实。

### 4.5 验收标准

- 用户能明确中断当前长回复
- 中断不会把 session 历史打坏
- 工具执行被中断时能给出明确状态
- 中断后可以继续在原 session 聊下去

---

## 5. 模块三：多端入口

### 5.1 目标

在 runtime 稳定后，把 EleBot 从“只有终端入口”推进成“多入口共享同一个 runtime”。

### 5.2 当前问题

现在的入口事实是：

- 主要入口仍然是 `elebot agent`
- 终端 UI 与 runtime 生命周期耦合
- 没有正式的 UI 进程 / API 进程 / desktop 壳分层

### 5.3 本阶段要做什么

这一步不先做复杂前端，而是先定义入口边界。

建议的结构方向：

```text
elebot/
  runtime/
  cli/
  desktop/   # 以后接 Electron 或其他桌面壳
  web/       # 以后接 Web UI 或本地 API
```

核心原则：

- `runtime` 只提供能力
- `cli` / `desktop` / `web` 只提供入口与展示

CLI 后续应该成为：

```text
CLI Frontend → Runtime API / Runtime Facade → AgentLoop
```

而不是继续直接手搓全部主链路依赖。

### 5.4 当前边界

这一步不要直接：

- 大做 Electron UI
- 上复杂前端框架
- 恢复旧 API 模块

先把“入口与 runtime 解耦”做出来。

### 5.5 验收标准

- CLI 不再是唯一形态
- 新入口可以接入统一 runtime
- 不同入口不会各自维护一套 agent 运行逻辑

---

## 6. 模块四：多通道能力

### 6.1 目标

在 runtime 稳定后，把外部消息入口重新设计成“消息适配层”，而不是恢复旧 frozen 代码。

### 6.2 当前问题

旧的 `channels` / `gateway` 方向已经被删出默认主链路。  
当前真实情况是：

- `Bus` 还在
- `InboundMessage` / `OutboundMessage` 还在
- 但没有正式的多通道接入层

### 6.3 本阶段要做什么

后续多通道应该按“适配器”而不是“主架构中心”来设计。

建议结构方向：

```text
elebot/channels/
  base.py
  telegram.py
  discord.py
  ...
```

但重新接回时必须满足：

- 渠道只负责协议转换
- 不持有 agent 主逻辑
- 最终统一转成 `InboundMessage`
- 输出统一转成 `OutboundMessage`

核心原则是：

```text
Channel Adapter → Bus → AgentLoop
```

而不是：

```text
Channel 自己直接调一堆 agent 内部方法
```

### 6.4 当前边界

这一步不要：

- 恢复旧通道代码当兼容层
- 先铺很多平台再慢慢清理

应该一次只接一个通道，验证抽象再扩。

### 6.5 验收标准

- 通道层只做消息协议适配
- 主链路仍然是 `Bus → AgentLoop`
- 不同通道不会分叉出不同 agent 逻辑

---

## 7. 模块五：子代理

### 7.1 目标

最后才考虑重新设计子代理，不恢复旧实现，不把它做成当前主链路依赖。

### 7.2 当前问题

子代理之前已经明确移除。  
这说明旧实现不适合当前阶段，也不应该按“功能缺失”心态去快速补回。

真正难点在于：

- 上下文切分
- 资源配额
- 工具权限
- 输出合并
- 中断传播
- session 一致性

### 7.3 本阶段要做什么

只有在前面 1 到 4 都稳定后，才开始讨论：

- 子代理是后台 worker，还是会话内并发执行器
- 子代理是否共享主 session
- 子代理是否拥有独立工具权限
- 主代理如何接收结果

建议方向是：

```text
主代理负责任务拆分
子代理只处理有边界的小任务
结果通过结构化消息返回主代理
```

### 7.4 当前边界

这一步不要：

- 恢复旧版子代理代码
- 先做多代理 UI
- 一开始就做复杂树状代理拓扑

### 7.5 验收标准

- 子代理不是默认主链路依赖
- 权限、上下文、结果归并边界清楚
- 中断和失败语义与主代理一致

---

## 8. 分阶段建议

### Phase 1

- 系统级后台运行
- 中断能力第一版

### Phase 2

- 多端入口分层

### Phase 3

- 多通道能力重建

### Phase 4

- 子代理重新设计

---

## 9. 一句话原则

下一阶段不要急着“加入口”或“加高级能力”，而是先把 EleBot 做成：

```text
一个可常驻、可中断、可复用的统一 runtime
```

只有这个底座稳定，多端、多通道、子代理才不会重新把项目带回旧的复杂状态。
