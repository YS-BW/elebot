# Tools

Tools 模块负责工具注册、参数校验、执行和结果返回。

## 当前职责

- 提供最小可用工具集。
- 根据模型 tool call 找到对应工具。
- 校验工具参数。
- 执行工具并返回 tool result。
- 将失败包装成稳定结果，避免中断主链路。

## 代码边界

- 工具不直接调用模型。
- 工具不直接写终端 UI。
- 工具结果由 Agent 回传给 Provider。

## 验收重点

- tool call -> execute -> tool result -> final answer 链路闭合。
- 工具参数错误必须可解释。
- 工具异常不能导致整个交互进程崩溃。
