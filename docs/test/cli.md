# CLI 测试

CLI 测试验证终端入口是否稳定可用。

## 覆盖内容

- `elebot --help` 可运行。
- `elebot` 能进入交互模式。
- 输入历史可读写。
- `exit`、`quit`、EOF 和 Ctrl+C 能安全退出。
- 流式内容可以被正确渲染。

## 边界

CLI 测试不直接验证模型质量，只验证 CLI 是否正确消费 Agent 事件。
