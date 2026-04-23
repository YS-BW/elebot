# EleBot 文档总览

这个目录只记录项目真实存在的模块和约束，不写未来计划，不写未落地能力。模块实现变化时，对应文档必须同步更新。

## 必读文档

- [代码规范](CODE_STYLE.md)：代码、注释、docstring、测试和文档同步规则。
- [核心模块索引](elebot/README.md)：`elebot/` 下每个模块的职责说明。
- [测试文档](test/README.md)：测试分层、覆盖范围和执行方式。
- [Bridge 文档](bridge/README.md)：Bridge 目录的当前职责与边界。

## 核心模块文档

- [CLI](elebot/cli.md)：命令入口、交互循环、终端渲染。
- [Facade](elebot/facade.md)：对外装配入口与调用边界。
- [Agent](elebot/agent.md)：对话主循环、Runner、上下文和工具闭环。
- [Tools](elebot/tools.md)：工具注册、执行和结果回传。
- [Config](elebot/config.md)：配置加载、默认配置和运行目录。
- [Session](elebot/session.md)：会话、历史和持久化。
- [Providers](elebot/providers.md)：模型 Provider 与默认模型链路。
- [Command](elebot/command.md)：内部命令路由与 slash 行为。
- [Bus](elebot/bus.md)：事件总线与模块间消息。
- [Utils](elebot/utils.md)：通用工具函数。
- [Templates](elebot/templates.md)：提示词与配置模板。

## 冻结模块文档

这些目录保留源码，但当前阶段不进入默认主链路。

- [Skills](elebot/skills.md)
- [Channels](elebot/channels.md)
- [API](elebot/api.md)
- [Cron](elebot/cron.md)
- [Heartbeat](elebot/heartbeat.md)
- [Security](elebot/security.md)

## 测试文档

- [测试总览](test/README.md)
- [代码规范测试](test/code_style.md)
- [CLI 测试](test/cli.md)
- [Config 测试](test/config.md)
- [Agent 测试](test/agent.md)
- [Providers 测试](test/providers.md)
- [集成测试](test/integration.md)

## 历史文档

根目录下仍可能保留从基座继承的历史说明文档。后续只有在对应模块真实启用或改造完成后，才把内容迁移到上面的模块文档中。
