# Agent Memory

> 这份文件只给接手项目的 agent 看，不属于正式项目文档。

## 项目定位

EleBot 是一个终端 AI 助手项目，当前重构方向不是继续沿用旧的 `Ink + gateway` 架构，而是回到 **nanobot 风格** 的产品形态：

- `Typer` 作为命令入口
- `prompt_toolkit` 负责交互输入
- `Rich` 负责终端输出
- Agent 主链路负责上下文、Provider、Session、Tools 的闭环

## 当前共识

- 不做兼容层。
- 不做迁移脚本。
- 不保留旧方案的过渡实现。
- `__init__.py` 只保留最小导出，不堆主逻辑。
- 文档必须和真实实现同步。
- 代码规范以 `docs/CODE_STYLE.md` 为准。

## 当前主链路范围

当前阶段只关心已有核心能力，不扩未来能力。

Active 模块：

- `cli`
- `agent`
- `providers`
- `session`
- `config`
- `command`
- `bus`
- `utils`
- `templates`
- 最小工具调用链路

Frozen 模块：

- `channels`
- `api`
- `cron`
- `heartbeat`
- `skills`
- `security`
- `bridge`

Frozen 的含义是：

- 保留目录和代码
- 当前不接入默认启动链路
- 当前不作为核心验收目标

## 当前文档约定

- `README.md` 只做项目介绍、快速开始和文档索引。
- `docs/` 只放项目开发文档，不放交接文档。
- 根目录下的 `memory.md` / `handoff.md` / `takeover.md` 只给 agent 交接使用。

## 当前已知风险

- 近期上下文较长，容易把“历史讨论”误当成“当前实现”。
- 接手 agent 必须优先相信代码和文档，不要优先相信旧对话。
- 如果发现文档与代码不一致，以代码现状为准，然后回补文档。

## 当前阻塞提醒

- 某些 Codex 会话里本地 shell 执行器可能失效，表现为无法运行 `pwd`、`ls`、`cat`，并报 `Failed to create unified exec process`。
- 如果再次遇到这个问题，不要盲改代码；先确认执行环境是否可用。

## 接手原则

- 先读 `takeover.md`
- 再读 `AGENTS.md`
- 再读 `docs/CODE_STYLE.md`
- 再看 `handoff.md`
- 最后进入代码和测试
