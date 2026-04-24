# EleBot

EleBot 是一个终端 AI 助手项目，当前基座来自 nanobot 风格的命令行产品形态：使用 `Typer` 作为命令入口，使用 `prompt_toolkit` 处理交互输入，使用 `Rich` 负责终端输出，并围绕 Agent 主链路组织配置、会话、Provider、工具调用和流式回复。

项目当前阶段的重点不是扩展更多未来能力，而是先把已有核心能力做清楚：能启动、能对话、能流式输出、能保存会话、能通过默认模型完成基础工具闭环。

## Quick Start

```bash
uv sync
uv run python -m elebot --help
uv run python -m elebot
```

如果需要安装成本机命令：

```bash
uv tool install -e .
elebot
```

## Runtime

EleBot 默认使用本地配置与运行目录：

```text
~/.elebot/config.json
~/.elebot/workspace
~/.elebot/sessions
```

默认模型配置以项目当前配置模板为准，当前阶段聚焦 `qwen3_6_plus` 主链路。

## Development Rules

- 不做兼容层、迁移脚本和临时回退方案。
- `__init__.py` 只保留最小导出，不承载主逻辑。
- 代码应保持最小解、清晰命名、中文 docstring 和必要中文注释。
