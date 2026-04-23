# Providers

Providers 模块负责模型调用。当前阶段沿用 nanobot 风格的 Provider 架构，不引入额外兼容层。

## 当前职责

- 根据配置选择默认模型。
- 通过 Provider 调用模型接口。
- 向 Agent 返回统一的流式事件。
- 处理 Provider 失败并返回稳定错误。

## 默认模型

当前默认模型聚焦 `qwen3_6_plus`。其他模型配置可以保留，但第一阶段不要求全部打通。

## 代码边界

- Provider 只负责模型接口调用和响应转换。
- Provider 不执行工具。
- Provider 不管理会话。
- Provider 不渲染终端输出。
