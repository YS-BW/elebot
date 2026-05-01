# Windows 环境下 EleBot 启动 / 连接链路异常排查

## 背景

EleBot 当前主运行链路是：

```text
CLI
  ↓
runtime
  ↓
Bus
  ↓
AgentLoop
  ↓
Provider / Tools
  ↓
OutboundMessage
  ↓
CLI 渲染
```

在 Windows 环境中运行 EleBot 时，出现连接相关异常。该问题可能影响本地终端入口、provider 调用、channel 连接链路，或者 PowerShell 启动环境本身。

当前项目阶段不希望为了兼容旧实现增加临时兼容层，因此这个 issue 的目标是确认 Windows 下当前主链路的真实失败点，并修复现有实现中的路径、编码、进程、网络或配置加载问题。

## 环境信息

- OS: Windows
- Shell: PowerShell
- Project path: `D:\elebot`
- Python: `>=3.11`
- Package manager: `uv`
- EleBot run mode:
  - `uv run python -m elebot --help`
  - `uv run python -m elebot`
  - `uv run python -m elebot agent`
  - 如果涉及 channel：
    - `elebot channel login`
    - `elebot channel run`
    - `elebot channel start`

## 已观察到的现象

在 Windows PowerShell 中执行命令时，终端会出现 PowerShell profile 加载失败：

```text
无法加载文件 C:\Users\<user>\Documents\WindowsPowerShell\profile.ps1。
未对文件 ...\profile.ps1 进行数字签名。
无法在当前系统上运行该脚本。
FullyQualifiedErrorId : UnauthorizedAccess
```

同时，部分 Markdown / 中文输出在 PowerShell 中出现乱码，类似：

```text
# é¦ƒå´’ EleBot
```

这说明当前 Windows 环境至少存在以下风险：

1. PowerShell 执行策略阻止 profile 加载，可能污染启动输出。
2. 终端编码可能不是 UTF-8，导致中文文档或 CLI 输出乱码。
3. 如果 EleBot 的连接链路依赖子进程、stdio、channel login、provider 请求或日志解析，前置 shell 异常可能会干扰判断。
4. Windows 下路径、进程生命周期、后台 channel 启停、日志读取、session/workspace 状态目录可能存在平台差异。

## 期望行为

在 Windows 环境中：

1. `uv run python -m elebot --help` 应稳定输出 CLI 帮助。
2. `uv run python -m elebot` 或 `uv run python -m elebot agent` 应能进入终端交互入口。
3. 如果配置了 provider，基础对话应能完成：
   - CLI 接收用户输入
   - runtime 正常装配
   - Bus 正常转发消息
   - AgentLoop 正常调用 provider
   - Rich / prompt_toolkit 正常渲染输出
4. 如果使用 channel，登录和连接命令应能明确区分：
   - 配置错误
   - 网络错误
   - 认证错误
   - 进程启动错误
   - Windows shell / 编码 / 路径问题

## 实际行为

Windows 连接链路目前不稳定，表现为启动或连接阶段异常。

需要进一步确认具体失败点属于以下哪一类：

- CLI 启动前 PowerShell 环境异常
- `uv` / Python 虚拟环境异常
- EleBot 配置加载异常
- provider 网络请求失败
- channel login / run / start 连接失败
- stdio / 子进程通信失败
- Windows 路径或编码问题
- workspace / session / skills / cron 旧运行态污染

## 复现步骤

建议从干净运行态开始复现。

### 1. 清理运行态目录

保留：

```text
~/.elebot/config.json
~/.elebot/weixin
```

清理：

```text
~/.elebot/workspace
~/.elebot/sessions
~/.elebot/skills
~/.elebot/logs
```

### 2. 确认基础环境

```powershell
python --version
uv --version
```

### 3. 同步依赖

```powershell
uv sync
```

### 4. 检查 CLI 是否可启动

```powershell
uv run python -m elebot --help
```

### 5. 检查主交互入口

```powershell
uv run python -m elebot
```

或者：

```powershell
uv run python -m elebot agent
```

### 6. 如果问题发生在 channel 连接

继续执行：

```powershell
uv run python -m elebot channel login
uv run python -m elebot channel run
```

或安装本地命令后：

```powershell
elebot channel login
elebot channel run
```

## 建议收集的诊断信息

```powershell
$PSVersionTable
[Console]::OutputEncoding
python --version
uv --version
uv run python -m elebot --help
uv run python -m compileall elebot tests -q
uv run python -m pytest -q
```

如果涉及 channel：

```powershell
uv run python -m elebot channel login
uv run python -m elebot channel run
uv run python -m elebot channel log
```

## 疑似排查方向

### 1. PowerShell Execution Policy

当前 PowerShell profile 加载失败：

```text
profile.ps1 未签名，无法运行
```

虽然这不一定是 EleBot 代码问题，但它会污染命令输出，并可能影响连接链路排查。

需要确认 EleBot 是否在启动、子进程、channel 或 stdio 过程中依赖 PowerShell profile 行为。

### 2. Windows Console Encoding

README / docs 输出出现中文乱码，说明终端编码可能不是 UTF-8。

需要确认：

- Rich 输出是否正确处理 Windows console 编码
- prompt_toolkit 输入输出是否受影响
- 日志文件是否以 UTF-8 写入
- 错误信息是否在 Windows 上被错误解码

### 3. Path Handling

EleBot 默认运行态路径包括：

```text
~/.elebot/config.json
~/.elebot/workspace
~/.elebot/sessions
~/.elebot/skills
~/.elebot/workspace/cron/jobs.json
```

需要确认 Windows 下：

- `~` 展开是否稳定
- `Path.home()` 是否符合预期
- `workspace` / `sessions` / `skills` / `logs` 是否自动创建
- 路径分隔符是否被硬编码为 `/`
- jsonl / json 文件读写是否正常

### 4. Channel / Stdio / Subprocess

如果连接问题发生在 channel：

- `channel login`
- `channel run`
- `channel start`
- `channel stop`
- `channel restart`

需要重点确认 Windows 下：

- 子进程是否正确启动
- 后台进程是否正确保存 PID / 状态
- 日志路径是否正确
- stop / restart 是否能找到并终止目标进程
- stdio 管道是否阻塞
- Windows shell quoting 是否导致命令参数丢失

### 5. Provider Network Connection

如果连接问题发生在模型调用阶段，需要区分：

- API key 未配置
- provider base URL 错误
- 网络 / 代理问题
- TLS / 证书问题
- timeout 设置问题
- provider 错误没有被清晰渲染到 CLI

## 验收标准

这个 issue 修复完成后，至少应满足：

1. Windows 下 `uv run python -m elebot --help` 正常。
2. Windows 下 `uv run python -m elebot` 或 `uv run python -m elebot agent` 可以进入主交互入口。
3. 如果 provider 配置正确，基础一轮对话可完成。
4. 如果连接失败，错误信息能明确说明是：
   - 配置问题
   - 网络问题
   - 认证问题
   - channel 进程问题
   - Windows shell / 编码 / 路径问题
5. Windows 下中文 CLI 输出和日志不应出现乱码。
6. 相关修复需要补充或更新测试。
7. 若修改了主链路，需要同步更新对应 docs。
8. 若这是模块级修复，需要回写 `PLAN.md`。

## 建议测试范围

优先运行：

```powershell
uv run python -m compileall elebot tests -q
uv run python -m pytest tests/cli -q
uv run python -m pytest tests/providers -q
uv run python -m pytest tests/command -q
```

如果涉及 channel：

```powershell
uv run python -m pytest tests -q
```

如果涉及 runtime / agent 主链路：

```powershell
uv run python -m pytest tests/agent -q
uv run python -m pytest tests/cli/test_runtime.py -q
```

## 非目标

本 issue 不建议：

- 恢复旧 channel / bridge / heartbeat 实现
- 增加临时兼容层
- 增加迁移脚本
- 为未来多端入口提前铺架构

## 项目原则

当前项目原则是：

> 先相信代码事实，按规范做最小修改，把已有核心能力做清楚，不扩、不绕、不兼容。

建议先定位 Windows 当前主链路的真实失败点，再做最小修复。
