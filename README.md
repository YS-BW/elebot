# 🍌 EleBot

> 终端 AI 助手 —— 在命令行里拥有一个能读代码、写文件、搜网页、管定时任务的 AI 搭档。

---

## ✨ 核心特性

- 🗣️ **终端原生交互** — 流式输出、Markdown 渲染、Ctrl+C 中断、命令历史
- 💬 **微信接入** — 通过 ilink 协议接入个人微信，支持文本/图片/语音/文件消息
- 🤖 **多模型支持** — 默认使用小米 Mimo，也可以切换到 OpenAI、Ollama 等 provider
- 📂 **文件与命令能力** — 能读写文件、执行 shell、搜索代码和网页
- ⏰ **定时任务** — AI 自主创建提醒、周期任务和 cron 调度
- 🧠 **长期记忆** — 跨会话记忆和 Dream 自动整理

---

## 🚀 快速开始

### 环境要求

- Python >= 3.11

### 安装 uv

EleBot 使用 [uv](https://docs.astral.sh/uv/) 作为包管理器。如果还没有安装 uv：

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 或者通过 pip 安装
pip install uv
```

安装完成后验证：

```bash
uv --version
```

### 安装 EleBot

```bash
# 克隆项目
git clone <repo-url> elebot
cd elebot

# 同步依赖
uv sync
```

### 首次运行

```bash
# 查看帮助
uv run python -m elebot --help

# 首次配置引导
uv run python -m elebot onboard

# 启动交互
uv run python -m elebot
```

### 安装为全局命令

```bash
uv tool install -e .
elebot
```

---

## 💬 微信 Channel

EleBot 支持通过 ilink 协议接入个人微信，在微信里直接和 AI 对话。

### 快速启动

先在 `~/.elebot/config.json` 中启用微信 channel：

```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "allowFrom": ["*"]
    }
  }
}
```

```bash
# 首次初始化
elebot onboard

# 交互式二维码登录
elebot channel login

# 前台运行
elebot channel run

# 后台运行
elebot channel start

# 查看后台日志
elebot channel log

# 停止后台服务
elebot channel stop

# 重启后台服务
elebot channel restart
```

---

## 💬 终端交互模式

```bash
elebot
# 或
elebot agent
```

进入后直接输入消息即可对话。

### Slash 命令

| 命令 | 说明 |
|------|------|
| `/new` | 开始新会话 |
| `/status` | 查看运行状态（版本、模型、token 用量） |
| `/dream` | 手动触发记忆整理 |
| `/dream-log` | 查看最近一次 Dream 变更 |
| `/dream-restore` | 回滚到之前的 Dream 版本 |
| `/skill list` | 查看已安装 skills |
| `/skill install <source>` | 安装 skill |
| `/skill uninstall <name>` | 卸载 skill |
| `/restart` | 重启 elebot |
| `/help` | 查看帮助 |
| `exit` / `quit` / `:q` | 退出 |

---

## 📚 文档

如果需要更细的实现说明，直接看 `docs/`：

- `docs/README.md`：文档索引
- `docs/CLI.md`：CLI 入口与命令行为
- `docs/WEIXIN.md`：微信 channel 说明
- `docs/PROVIDERS.md`：模型 provider 说明
- `docs/CHANNELS.md`：channel 子系统说明

---

## 🧪 开发

### 运行测试

```bash
# 全部测试
uv run python -m pytest -q

# 按模块
uv run python -m pytest tests/agent -q
uv run python -m pytest tests/providers -q
uv run python -m pytest tests/tools -q
uv run python -m pytest tests/cron -q
uv run python -m pytest tests/command -q
```

### 代码检查

```bash
uv run ruff check elebot tests
```

### 语法编译

```bash
uv run python -m compileall elebot tests -q
```

---

## 📁 项目结构

```
elebot/
├── cli/                 # 命令入口、交互循环、终端渲染
├── runtime/             # 运行时装配与生命周期管理
├── agent/               # Agent 主循环、上下文、记忆、工具
│   ├── loop.py          # 主循环（消息消费、分发、会话管理）
│   ├── runner.py        # 工具调用执行循环
│   ├── context.py       # Prompt 构造
│   ├── memory/          # 记忆存储、压缩、Dream
│   ├── skills/          # Skill 扫描与注册
│   └── tools/           # 所有内置工具实现
├── channels/            # Channel 接入（当前为微信）
├── providers/           # LLM Provider 抽象与各家适配
├── session/             # 会话模型与 JSONL 持久化
├── bus/                 # 消息总线（InboundMessage/OutboundMessage）
├── command/             # Slash 命令路由与处理
├── config/              # 配置模型、路径、加载
├── cron/                # 应用内调度服务
├── templates/           # Prompt 模板
└── utils/               # 工具函数
```

---

## 📜 许可证

[LICENSE](./LICENSE)
