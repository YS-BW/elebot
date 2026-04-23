# CLI

CLI 是 EleBot 的默认产品入口，负责把用户输入、终端渲染和 Agent 主链路连接起来。

## 当前职责

- 注册 `elebot` 命令入口。
- 启动交互式输入循环。
- 管理终端历史记录和退出行为。
- 渲染流式正文、thinking 状态、工具提示和错误信息。

## 代码边界

- `commands.py` 只负责命令注册和启动装配。
- `interactive.py` 负责 prompt_toolkit 交互循环。
- `render.py` 负责 Rich 普通输出。
- `stream.py` 负责流式渲染和 spinner。
- `history.py` 负责输入历史和终端安全处理。

## 不负责

- 不直接调用底层模型。
- 不持久化业务会话。
- 不执行工具逻辑。
