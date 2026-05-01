# Provider 设计

这篇文档只讲当前主链路里的 provider 层，不讨论已经删除的 OAuth provider，也不讨论未来动态发现模型。

相关源码：

- [elebot/config/schema.py](../elebot/config/schema.py#L157-L208)
- [elebot/providers/registry.py](../elebot/providers/registry.py#L11-L340)
- [elebot/providers/resolution.py](../elebot/providers/resolution.py#L11-L150)
- [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L72)
- [elebot/providers/model_catalog.py](../elebot/providers/model_catalog.py#L10-L257)
- [elebot/providers/transcription.py](../elebot/providers/transcription.py#L1-L199)
- [elebot/cli/onboard.py](../elebot/cli/onboard.py#L19-L23)
- [elebot/cli/onboard.py](../elebot/cli/onboard.py#L639-L668)

## 1. 当前 provider 层分成哪三块

当前主链路里，provider 模块有三层固定边界：

1. `registry.py`
   - 保存静态 provider 元数据
2. `resolution.py`
   - 做 provider 解析和路由
3. `factory.py`
   - 实例化真正的 provider 对象

主链路可以记成：

```text
Config
  ↓
resolve_provider()
  ↓
build_provider()
  ↓
LLMProvider
```

`config` 现在只保存配置事实，不再承担 provider 解析方法。

## 2. OAuth provider 已经被整套移除

当前已经不再支持：

- `openai_codex`
- `github_copilot`

这不是“默认隐藏”，而是已经从当前实现中删掉：

- 没有对应 provider 文件
- 注册表里没有对应 `ProviderSpec`
- CLI 里没有 `provider login`
- 配置模型里也没有对应字段

所以当前 provider 层只讨论稳定主链路和现有兼容 provider，不再保留 OAuth 分支。

## 3. `registry.py` 保存什么事实

[elebot/providers/registry.py](../elebot/providers/registry.py#L11-L340) 里定义的是 `ProviderSpec`。

这里保存的都是静态元数据，例如：

- provider 名称
- 关键字
- backend 类型
- 是否 gateway / local / direct
- 默认 `api_base`

这一层不做运行时选择，只回答“有哪些 provider、它们各自是什么类型”。

## 4. `resolution.py` 怎么决定选谁

当前唯一的解析入口是 [elebot/providers/resolution.py](../elebot/providers/resolution.py#L23-L150) 的 `resolve_provider()`。

返回值固定是 `ProviderResolution`，包含：

- `model`
- `provider_name`
- `provider_config`
- `spec`
- `backend`
- `api_base`

解析顺序固定为：

1. 显式模型前缀优先
2. 强制 provider 配置优先
3. 注册表关键字匹配
4. 本地 provider `api_base` 识别
5. 网关 provider 兜底
6. 默认 `api_base` 推断

所以现在的 provider 选择策略已经从 `Config` 里彻底挪回 `providers`。

## 5. `factory.py` 只负责装配

[elebot/providers/factory.py](../elebot/providers/factory.py#L10-L72) 的 `build_provider(config)` 现在只做装配：

1. 调 `resolve_provider()`
2. 做必要校验
3. 按 backend 实例化具体 provider
4. 注入 `GenerationSettings`

也就是说：

- 解析规则在 `resolution.py`
- 实例化规则在 `factory.py`

不要再把这两层混回 `runtime` 或 `config`。

## 6. 模型目录现在也归 `providers`

模型建议和推荐上下文窗口现在统一收口到 [elebot/providers/model_catalog.py](../elebot/providers/model_catalog.py#L10-L257)。

当前对外提供的是：

- `ModelSpec`
- `list_models()`
- `find_model()`
- `suggest_models()`
- `get_recommended_context_window()`

CLI 向导在 [elebot/cli/onboard.py](../elebot/cli/onboard.py#L19-L23) 和 [elebot/cli/onboard.py](../elebot/cli/onboard.py#L639-L668) 里直接复用它，不再经过 `elebot/cli/models.py` 这层空壳。

## 7. model catalog 的覆盖范围是什么

当前静态目录只覆盖稳定 provider：

- `openai`
- `anthropic`
- `dashscope`
- `deepseek`
- `gemini`
- `moonshot`

这意味着：

- `azure_openai`
- `custom`
- 本地 provider
- 各类 gateway provider

在模型建议上允许返回空列表，在推荐上下文窗口上允许返回 `None`。这不是缺陷，而是当前固定行为。

## 8. 当前固定原则

现在 provider 层有两条必须固定的事实：

```text
provider 解析归 providers
model catalog 也归 providers
```

runtime 和 CLI 只复用这些能力，不再各自保留第二套 provider 知识。

另外还有一个当前已经落地的入口事实：

- 首次 `onboard` 生成的默认 provider 是 `deepseek`
- 首次 `onboard` 生成的默认模型是 `deepseek-v4-flash`

## 9. runtime 级辅助音频 provider

除主 LLM provider 之外，当前还有一条已经落地、但不参与 `resolve_provider()` 的辅助音频链路：

- 顶层 `transcription`
  - 只负责语音转写
  - 当前固定模型是 `qwen3-asr-flash`

这两条链路的固定边界是：

- 配置仍然只放在 [elebot/config/schema.py](../elebot/config/schema.py#L157-L199)
- 具体协议 owner 在 [elebot/providers/transcription.py](../elebot/providers/transcription.py#L1-L199)
- `runtime` 只负责装配和委托，不把它混进主 LLM provider 解析层

这意味着：

- `providers.registry` / `resolution` / `factory` 仍然只讨论主聊天模型
- 语音输入能力由 runtime 级辅助 provider 单独承接

## 10. DeepSeek 的 assistant transcript 为什么要补 `reasoning_content`

当前 DeepSeek 还有一个已经坐实的协议事实：在 thinking mode 下，下一轮重放 assistant transcript 时，消息里必须继续带回 `reasoning_content`。最容易出问题的是两类历史：

- 带 `tool_calls` 的 assistant 消息
- 工具调用后因为模型报错而落盘的 assistant 占位消息

EleBot 现在把这层修补固定放在 [OpenAICompatProvider._sanitize_messages()](../elebot/providers/openai_compat_provider.py#L277-L313) 和 [OpenAICompatProvider._normalize_reasoning_response()](../elebot/providers/openai_compat_provider.py#L219-L232) 里：

- 出站时，如果当前 provider 是 DeepSeek，且任意 assistant 历史消息缺少 `reasoning_content`，会补成空字符串 `""`
- 入站时，如果 DeepSeek 返回了工具调用，但解析后的 `reasoning_content` 仍然缺失，也会归一化成 `""`

这样做的边界是固定的：

- 不修改 session 文件
- 不跑迁移脚本
- 不把兼容逻辑散到 `runner`、`session` 或 `runtime`

对应请求入口仍然只走 [OpenAICompatProvider.chat()](../elebot/providers/openai_compat_provider.py#L889-L935) 和 [OpenAICompatProvider.chat_stream()](../elebot/providers/openai_compat_provider.py#L937-L1025)，只是 provider 在内部把 DeepSeek 的 transcript 协议收口了。
