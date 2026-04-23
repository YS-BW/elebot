# Channels

Channels 模块当前为 Frozen 状态：代码保留，但不接入默认终端助手链路。

## 当前状态

- 不随 `elebot` 默认启动。
- 不暴露默认命令。
- 不影响 CLI、Agent、Provider 的核心测试。

## 边界

Channels 以后可以用于接入外部消息通道，但当前阶段只保证它不会阻塞核心 CLI。
