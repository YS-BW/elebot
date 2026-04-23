# 测试总览

测试文档说明当前项目应该验证什么，以及每类测试保护的模块边界。

## 测试分层

- [代码规范测试](code_style.md)：检查注释、docstring、命名和文档同步要求。
- [CLI 测试](cli.md)：验证命令入口、交互循环和终端渲染。
- [Config 测试](config.md)：验证配置加载、默认配置和运行目录。
- [Agent 测试](agent.md)：验证对话主链路和工具闭环。
- [Providers 测试](providers.md)：验证模型调用抽象和错误包络。
- [集成测试](integration.md)：验证 CLI 到 Agent 的真实链路。

## 执行方式

```bash
uv run python -m unittest discover -s tests -q
```

## 当前原则

- 测试只覆盖项目已有能力。
- 不为 Frozen 模块补未来测试。
- 新增主链路能力时，必须同步增加对应测试文档。
