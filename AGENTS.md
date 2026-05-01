# EleBot Project Guide

> 这份文件是 EleBot 项目的统一项目指导文件，给后续接手的 agent 使用，不属于正式用户文档。

## Project Overview

EleBot 当前是一个 nanobot 风格的终端 AI 助手项目。

当前产品形态：

- 终端交互入口
- `Typer` 负责命令入口
- `prompt_toolkit` 负责输入体验
- `Rich` 负责输出渲染
- `AgentLoop` 负责主链路执行
- `Bus` 负责消息总线
- `Session` 负责会话持久化
- `providers` 负责 LLM 抽象
- `tools` 负责工具调用闭环
- `skills` 负责 prompt 驱动的全局技能
- `cron` 负责应用内调度

当前阶段的核心目标不是扩新功能，而是把已有主链路做清楚、做扎实、做成可维护的基座。

## Product Direction

当前项目方向固定如下：

- 做成 nanobot 风格的终端 AI 助手
- 先完成已有核心能力
- 不扩未来能力
- 不做兼容层
- 不做迁移脚本
- 不保留过渡实现

当前第一优先级不是“设计更多东西”，而是：

- 保持代码事实、文档事实、测试事实一致
- 保持主链路清晰
- 保持项目可验证、可维护

## Current Scope

### Active Modules

这些模块属于当前默认主链路：

- `cli`
- `agent`
- `providers`
- `session`
- `config`
- `command`
- `bus`
- `utils`
- `templates`
- `cron`
- `agent/skills`
- 最小工具调用闭环

### Removed Or Non-default Capabilities

这些能力当前不在默认主链路里，不要按“差一点恢复”的心态处理：

- `api`
- `heartbeat`
- `security`
- `bridge`
- 旧版子代理实现

如果将来要重新做，应该按当前架构重新设计，而不是恢复旧代码当兼容层。

## Current Status

按当前代码事实，项目已经具备：

- 终端主链路闭环
- 进程内 `runtime` 装配与生命周期管理
- 基础多轮对话
- 流式输出
- 会话持久化
- 工作区启动模板加载
- 全局 `skills` 扫描与 prompt 注入
- `cron_create / cron_list / cron_delete / cron_update` 工具驱动的应用内调度、后台轮询、到点执行
- 文档化的模块教程

按当前代码事实，项目还没有：

- 系统级调度后端
- 完整的中断能力
- 正式的 Web / desktop 多端入口
- 多通道能力
- 重新设计后的子代理体系

## Repo Layout

### Core Code

- `elebot/cli/`
  - 命令入口、交互循环、终端 UI
- `elebot/runtime/`
  - 运行时装配、主循环生命周期管理
- `elebot/agent/`
  - Agent 主循环、上下文构建、记忆、skills、tools
- `elebot/providers/`
  - LLM provider 抽象与各家适配
- `elebot/session/`
  - 会话模型、jsonl 持久化、checkpoint 恢复
- `elebot/bus/`
  - `InboundMessage` / `OutboundMessage` 与队列总线
- `elebot/command/`
  - slash 命令路由与内置命令
- `elebot/config/`
  - 配置模型、路径和加载逻辑
- `elebot/cron/`
  - 应用内调度模型、存储、调度、触发
- `elebot/utils/`
  - 通用工具函数、消息辅助、模板辅助
- `elebot/templates/`
  - prompt 模板和工作区启动模板

### Project Docs

- `README.md`
  - 项目入口说明
- `docs/`
  - 正式项目文档
- `CLAUDE.md`
  - 给 Claude 这类讲解型 agent 的项目阅读提示词
- `PLAN.md`
  - 后续实现计划，不属于正式文档

### Tests

- `tests/`
  - 当前主链路、provider、tools、cron、session 等测试

## Reading Order

进入任务前，建议按下面顺序建立上下文：

1. `AGENTS.md`
2. `README.md`
3. `docs/README.md`
4. 对应模块文档
5. 代码
6. 测试

不要跳过 `AGENTS.md` 后直接改代码。

## Environment Setup

推荐环境：

- Python `>=3.11`
- 包管理使用 `uv`

初始化：

```bash
uv sync
```

如果你只想安装开发依赖：

```bash
uv sync --extra dev
```

## Runtime Paths

EleBot 默认运行目录：

```text
~/.elebot/config.json
~/.elebot/workspace
~/.elebot/sessions
~/.elebot/skills
```

这些目录是当前主链路的重要状态来源：

- `config.json`
  - provider、模型、工具、MCP 等配置
- `workspace`
  - agent 运行工作区
- `sessions`
  - 会话历史
- `workspace/cron/jobs.json`
  - cron 调度状态
- `skills`
  - 全局 skills

### Branch Switch Cleanup Rule

每次切换 Git 分支后，都要先清理运行态目录，再继续测试或开发。

固定清理范围：

- `~/.elebot/workspace`
- `~/.elebot/skills`

固定保留范围：

- `~/.elebot/config.json`
- `~/.elebot/site-auth`
- 其它未明确要求删除的认证或配置文件

目的：

- 避免不同分支复用旧工作区、旧 cron 状态、旧 skills 状态
- 避免把上一个分支的运行结果误判成当前代码事实

### Historical Session Rule

如果确认问题来自旧 session / 旧 workspace 的历史污染，不要加兼容旧会话的代码。

固定处理方式：

- 直接删除 `~/.elebot/workspace`
- 从干净状态重新 `onboard` 或重新启动 agent
- 优先把问题当成运行态污染处理，而不是主链路兼容需求

### Post-change Cleanup Rule

每次修改代码后，在收尾阶段都要清理 `~/.elebot` 下除 `config.json` 外的运行态目录和文件。

固定保留范围：

- `~/.elebot/config.json`
- `~/.elebot/weixin`

固定清理范围：

- `~/.elebot/workspace`
- `~/.elebot/sessions`
- `~/.elebot/skills`
- `~/.elebot/logs`
- `~/.elebot/site-auth` 之外，且不包含 `~/.elebot/weixin` 的其它运行态缓存和临时文件

如果本轮代码修改涉及 `config` 结构、默认值、字段名或配置加载逻辑，则需要同步重写当前本机 `~/.elebot/config.json`，并保留用户当前实际在用的配置值，不要重置成模板默认值。


## Build

项目没有复杂构建步骤，主要检查是语法编译：

```bash
uv run python -m compileall elebot tests -q
```

## Run

### 查看 CLI 帮助

```bash
uv run python -m elebot --help
```

### 启动主交互入口

```bash
uv run python -m elebot
```

或者安装成本机命令后运行：

```bash
uv tool install -e .
elebot
```

### 主要运行方式

当前真实可用的运行方式以 CLI 为主：

- `elebot`
- `elebot agent`

其中当前启动链路已经是：

```text
CLI
  ↓
runtime
  ↓
Bus
  ↓
AgentLoop
```

当前没有正式的：

- desktop runtime
- web UI
- API server 产品入口

## Test

### 运行全部 pytest

```bash
uv run python -m pytest -q
```

### 运行局部测试

```bash
uv run python -m pytest tests/agent -q
uv run python -m pytest tests/providers -q
uv run python -m pytest tests/cron -q
uv run python -m pytest tests/tools -q
uv run python -m pytest tests/command -q
```

### 运行 unittest 扫描

```bash
uv run python -m unittest discover -s tests -q
```

注意：

- 当前这个命令可能发现 `0` 个 unittest 测试
- 主测试体系是 `pytest`

### 代码风格 / 静态检查

```bash
uv run ruff check elebot tests
```

如果只看常见未使用导入 / 变量：

```bash
uv run ruff check elebot tests --select F401,F841
```

## Main Runtime Flow

当前主链路可以先记成这一条：

```text
用户输入
  ↓
CLI
  ↓
Bus
  ↓
AgentLoop
  ↓
ContextBuilder + Session + Memory
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

如果是 skill，则当前实现是：

```text
~/.elebot/skills
  ↓
SkillRegistry 扫描
  ↓
ContextBuilder 注入 metadata
  ↓
模型自行决定是否读取 skill 内容
```

## Skills

当前 skill 机制已经接入主链路，但属于最小实现。

当前事实：

- 全局 skill 根目录只有一个：`~/.elebot/skills`
- 每个 skill 至少需要 `SKILL.md`
- frontmatter 当前只认：
  - `name`
  - `description`
- system prompt 里只注入 metadata，不自动注入 skill 正文

当前没有：

- marketplace
- `/skills` 命令体系
- 启用 / 禁用开关体系
- 热重载
- skill 自动沉淀机制

## Cron

当前 `cron` 机制已经接入主链路，但仍然是应用内调度，不是系统级调度。

当前事实：

- 调度文件在 `~/.elebot/workspace/cron/jobs.json`
- `CronService` 负责后台轮询和到点执行
- 只有 `elebot agent` 运行时，cron job 才会触发
- 模型侧暴露四个调度工具：
  - `cron_create`
  - `cron_list`
  - `cron_delete`
  - `cron_update`
- cron 到点后会回到 `AgentLoop.process_direct(...)` 跑一次独立执行

当前没有：

- `heartbeat`
- `launchd`
- Windows Task Scheduler
- 系统通知中心
- 后台 daemon

## Code Style

当前项目代码规范以仓库内现有实现约束为准：

- 所有函数和方法必须有清晰中文 docstring
- docstring 说明参数和返回值
- 变量命名清晰易懂
- 禁止无意义缩写
- 注释使用中文
- 注释只解释“为什么”，不要解释显而易见的“做了什么”
- 不添加不必要的类、封装和中间层
- `__init__.py` 只保留最小导出，不堆主逻辑
- 改动以最小解、最优解为准

## Documentation Rules

- `README.md` 只做项目介绍、快速开始和索引
- `docs/` 只放正式项目文档
- `PLAN.md` 是内部计划，不是正式文档
- 文档必须反映真实代码，不写未落地能力
- 改代码后，要同步相关文档

### Docs Source Links

`docs/` 下的文档引用源码时必须满足：

- 路径以 `../` 开头
- 精确到具体代码范围
- 格式必须是 `#Lstart-Lend`

标准格式：

```md
[描述](../path/to/file.py#Lstart-Lend)
```

### Module Completion Rules

一个“模块级”任务只有同时满足下面四项，才可以在项目层面称为“完成”：

1. 代码实现完成
2. 对应测试已新增或更新，并且实际跑过
3. `docs/` 中对应模块文档已新增或更新
4. `PLAN.md` 已回写当前状态、剩余事项和风险

如果只完成了代码和测试，但没有完成文档或 `PLAN.md` 回写，那么这个模块最多只能描述为：

- `代码实现完成，项目回写未完成`

## Testing Rules

- 测试只覆盖当前已有功能
- 不接受只有 happy path 的测试
- 主链路变更后要跑对应局部测试
- 测试失败时先判断是环境问题还是代码问题
- 默认不强制执行真实 `elebot agent` 多轮交互测试；只有用户明确要求时，才需要额外执行这条真实链路验证
- 如果用户明确要求真实链路测试，这条测试不能只用 `--help` 代替，必须实际进入 CLI → runtime → AgentLoop 的启动链路
- 如果真实测试因为 API Key、网络、TTY 或 provider 环境失败，必须在汇报里明确区分是“启动链路失败”还是“启动成功但运行环境失败”

建议策略：

- 改 provider，先跑 `tests/providers`
- 改 agent，先跑 `tests/agent`
- 改 cron，先跑 `tests/cron`、`tests/tools/test_cron_tool.py`、`tests/cli/test_runtime.py`
- 改命令，先跑 `tests/command`

## Working Rules

### Allowed

- 清理结构冗余
- 修正文档和代码不同步
- 统一已有实现风格
- 补齐已有能力缺少的测试
- 基于真实运行结果解释系统行为

### Not Allowed

- 擅自改产品方向
- 恢复已移除模块到默认链路
- 增加兼容层
- 增加迁移脚本
- 为未来能力提前铺大框架
- 没确认边界就跨模块大改
- 用历史对话替代代码事实

### Sub-agent Rules

如果使用子 agent，主 agent 不能只转述子 agent 的自述，必须自己复核：

- 实际改了哪些文件
- 是否越过本轮模块边界
- 测试是否真的跑过且通过
- 是否完成了 `docs/` 回写
- 是否完成了 `PLAN.md` 回写

对子 agent 的验收必须以代码事实为准，不以子 agent 自己的总结为准。

## Decision Priority

遇到冲突或不确定时，按下面顺序判断：

1. 当前代码事实
2. 本文件中的项目边界和规则
3. `docs/` 模块文档
4. 测试
5. 历史对话

历史对话优先级最低。

## Current Risks

当前项目最容易出现的问题：

- 文档落后于代码
- 旧讨论被误当成当前实现
- 想当然恢复已经删除的能力
- 把最小主链路重新扩成复杂架构
- 任务、skills、provider 这些已接入模块被当成“边缘功能”处理

## Near-term Roadmap

### `PLAN.md` 使用规则

- `PLAN.md` 是后续实现计划，不是归档文件。
- 每次开始做一个较大模块前，先读 `PLAN.md`，确认当前优先级、边界和剩余事项。
- 每次做完一个模块后，必须回写 `PLAN.md`：
  - 更新当前模块的完成情况
  - 更新剩余模块顺序
  - 记录新发现的风险、依赖和边界变化
- 如果实现过程中发现原计划不符合代码事实，可以改 `PLAN.md`，但必须基于真实代码和真实运行结果。
- 不要让 `PLAN.md` 漂成历史遗留清单。

### 新 agent 的实际开工顺序

如果新 agent 接手后要立刻开始干活，实际建议顺序是：

1. 先读本文件和 `README.md`
2. 再读 `docs/README.md` 和相关模块文档
3. 确认当前工作区是否有未提交改动
4. 明确本轮是在做：
   - `PLAN.md` 中当前排在前面的模块
5. 先检查 `PLAN.md` 是否需要根据当前代码事实调整
6. 一次只推进一个方向，不混做
7. 先做最小可运行收口，再考虑继续展开
8. 做完一个模块后，必须同步两件事：
   - 更新 `PLAN.md`
   - 在 `docs/` 中新增或更新对应模块文档

### 模块文档回写规则

- 每次开始做一个较大模块前，先确认 `docs/` 中是否已经有对应文档。
- 如果没有，对应实现完成后要补一份。
- 如果已有，对应实现完成后要更新到和代码一致。
- 文档必须讲“当前实现怎么工作”，不要把未来设想写成现状。
- 文档优先覆盖：
  - 入口
  - 主流程
  - 关键文件
  - 关键数据结构
  - 真实代码链接

## Permissions And Safety

- 允许修改的核心目录：
  - `elebot/`
  - `tests/`
  - `docs/`
  - 根目录项目说明文件
- 不要做破坏性 shell 操作
- 不要回滚别人未明确授权你回滚的改动
- 不要访问未声明的秘密存储
- 推送或网络失败时，要区分是认证问题、Git 凭证问题，还是网络 / 代理问题

## One-line Principle

EleBot 当前阶段只有一句话：

**先相信代码事实，按规范做最小修改，把已有核心能力做清楚，不扩、不绕、不兼容。**
