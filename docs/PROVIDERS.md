# EleBot Provider 设计

这篇文档只讲当前主链路里的 provider 层，不讲未来多后端架构，也不展开已经不在主链路里的旧兼容方案。

相关源码：

- [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L82)
- [elebot/providers/base.py](../elebot/providers/base.py#L18-L171)
- [elebot/providers/registry.py](../elebot/providers/registry.py#L11-L365)
- [elebot/providers/openai_compat_provider.py](../elebot/providers/openai_compat_provider.py#L130-L351)

## 1. 先记住 provider 在主链路里的位置

provider 这一层的职责很单纯：

> 把 EleBot 内部统一的请求结构翻译成外部模型服务能接受的请求，  
> 再把外部模型服务返回的内容翻译回 EleBot 自己统一的响应结构。

主链路到这里可以先看成：

```text
ContextBuilder
  ↓
messages + tools
  ↓
AgentRunner
  ↓
provider.chat_with_retry(...)
  ↓
LLMResponse
  ↓
如果有 tool_calls 就继续执行工具
否则返回正文
```

所以：

- `agent` 不直接依赖具体 SDK 格式
- `provider` 负责把外部差异收口

## 2. 为什么要有这一层

EleBot 内部希望只面对一种统一结构：

- 统一的 `messages`
- 统一的 `tool_calls`
- 统一的 `usage`
- 统一的错误和重试行为

但外部服务并不统一：

- OpenAI 兼容接口一类
- Anthropic 一类
- Azure OpenAI 一类
- OAuth 型 provider 又是一类

所以 provider 层本质上就是模型适配层。

## 3. 内部统一响应长什么样

最重要的两个结构都在 [elebot/providers/base.py](../elebot/providers/base.py#L18-L77)。

### 3.1 `ToolCallRequest`

```python
@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]
```

这表示：

- 模型要调用哪个工具
- 这次工具调用的 id 是什么
- 参数是什么

所以无论外部 provider 原始返回长什么样，进到 EleBot 内部后都会尽量被整理成这个结构。

### 3.2 `LLMResponse`

```python
@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    retry_after: float | None = None
    reasoning_content: str | None = None
    thinking_blocks: list[dict] | None = None
```

可以直接理解成：

- `content`：模型正文
- `tool_calls`：模型请求执行的工具
- `usage`：token 用量
- `reasoning_content`：额外思考文本
- 以及一组重试和错误元数据

provider 层最核心的目标之一就是：

> 把外部响应标准化成 `LLMResponse`

## 4. `registry.py` 负责什么

`registry.py` 不是执行 provider 的地方，它负责维护 provider 元数据注册表。

核心结构在 [elebot/providers/registry.py](../elebot/providers/registry.py#L11-L64)：

```python
@dataclass(frozen=True)
class ProviderSpec:
    name: str
    keywords: tuple[str, ...]
    env_key: str
    display_name: str = ""
    backend: str = "openai_compat"
```

它描述的是：

- provider 名称
- 模型名匹配关键字
- 默认环境变量名
- 对应哪个 backend 实现
- 默认 base_url
- 是不是 gateway / local / oauth / direct

下面的 `PROVIDERS` 列表就是全局注册表，在 [elebot/providers/registry.py](../elebot/providers/registry.py#L68-L365)。

当前这里登记了很多 provider，例如：

- `openai`
- `anthropic`
- `dashscope`
- `openrouter`
- `deepseek`
- `gemini`
- `zhipu`
- `moonshot`

所以 `registry.py` 的职责是：

> 告诉系统“当前模型配置应该映射到哪个 provider backend”

## 5. 真正创建 provider 的入口

创建 provider 的入口现在已经收口到 [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L82) 的 `build_provider(config)`。

这层职责是固定的：

- 读取当前默认模型和默认 provider 配置
- 通过 `registry` 解析 `ProviderSpec`
- 在装配前做必要校验
- 按 backend 实例化具体 provider
- 注入默认 `GenerationSettings`

当前 `runtime` 会直接调用这条入口来装配 provider。  
CLI 里的 `_make_provider()` 只保留错误展示包装，不再承载真正的 provider 路由逻辑。

核心逻辑：

```python
model = config.agents.defaults.model
forced_provider = config.agents.defaults.provider
provider_name = config.get_provider_name(model)
provider_config = config.get_provider(model)
spec = find_by_name(provider_name) if provider_name else None
backend = spec.backend if spec else "openai_compat"
```

先决定：

- 显式 provider 配置是否合法
- 本轮应该用哪个 provider name
- 这个 provider 对应哪个 backend
- 这个 backend 需不需要额外凭证校验

然后按 backend 实例化具体类：

```python
if backend == "azure_openai":
    provider = AzureOpenAIProvider(...)
elif backend == "anthropic":
    provider = AnthropicProvider(...)
else:
    provider = OpenAICompatProvider(...)
```

最后再挂上生成参数：

```python
provider.generation = GenerationSettings(
    temperature=defaults.temperature,
    max_tokens=defaults.max_tokens,
    reasoning_effort=defaults.reasoning_effort,
)
```

所以 provider 创建流程可以直接记成：

```text
配置 / 模型名
  ↓
registry 匹配 ProviderSpec
  ↓
决定 backend
  ↓
实例化具体 Provider 类
  ↓
注入 generation 参数
```

## 6. 当前最关键的 provider 实现是谁

当前最值得先看的实现是：

- [elebot/providers/openai_compat_provider.py](../elebot/providers/openai_compat_provider.py#L130-L351)

原因很简单：

当前很多 provider 最终都会落到这套兼容实现，包括：

- OpenAI
- DashScope
- DeepSeek
- Gemini 的兼容端点
- Zhipu
- OpenRouter
- 很多 OpenAI-compatible gateway

所以它其实是当前主链路里的核心 provider 实现。

## 7. `OpenAICompatProvider` 到底做什么

你可以把它拆成 5 个职责。

### 7.1 初始化客户端

见 [elebot/providers/openai_compat_provider.py](../elebot/providers/openai_compat_provider.py#L133-L174)：

```python
self._client = AsyncOpenAI(
    api_key=api_key or "no-key",
    base_url=effective_base,
    default_headers=default_headers,
    max_retries=0,
)
```

这一步决定：

- API Key
- `base_url`
- 默认请求头
- 某些 provider 的额外 header

### 7.2 清洗请求消息

见 [elebot/providers/openai_compat_provider.py](../elebot/providers/openai_compat_provider.py#L233-L267)：

```python
sanitized = LLMProvider._sanitize_request_messages(messages, _ALLOWED_MSG_KEYS)
```

这里会处理很多兼容问题，例如：

- 去掉 provider 不认识的字段
- 标准化 `tool_call_id`
- 处理带 `tool_calls` 的 assistant 消息

所以 provider 层不是直接把内部消息原样丢给 SDK。

### 7.3 组装请求参数

见 [elebot/providers/openai_compat_provider.py](../elebot/providers/openai_compat_provider.py#L286-L351)：

```python
kwargs = {
    "model": model_name,
    "messages": self._sanitize_messages(self._sanitize_empty_content(messages)),
}

if tools:
    kwargs["tools"] = tools
    kwargs["tool_choice"] = tool_choice or "auto"
```

这里会把：

- `messages`
- `tools`
- `temperature`
- `max_tokens`
- `reasoning_effort`

组装成真正发给 SDK 的请求体。

### 7.4 处理兼容行为

例如：

- 某些 provider 需要去掉模型名前缀
- 某些 provider 支持 prompt caching
- 某些 provider 不接受 temperature
- 某些 provider 用 `max_completion_tokens`

这也是为什么 provider 层看起来比你想象的更复杂。

### 7.5 解析外部响应

最后 provider 还要把 SDK 的响应翻译回 EleBot 的统一结构，也就是：

- `LLMResponse`
- `ToolCallRequest`

所以 `OpenAICompatProvider` 本质上是个双向翻译器：

```text
EleBot 内部请求
  ↓
OpenAI-compatible 请求
  ↓
SDK 响应
  ↓
EleBot 内部响应
```

## 8. `base.py` 除了抽象类还做了什么

`LLMProvider` 不只是接口定义，它还承载了很多通用逻辑。

例如：

- 空内容修正
- 去掉 `_meta`
- 工具 schema 边界标记
- 公共重试策略
- 通用错误分类

在 [elebot/providers/base.py](../elebot/providers/base.py#L89-L171) 能看到很多公共重试常量，例如：

- `_CHAT_RETRY_DELAYS`
- `_RETRYABLE_STATUS_CODES`
- `_TRANSIENT_ERROR_MARKERS`

这说明 provider 层除了“发请求”，还负责：

> 统一模型调用失败时的重试和错误判定逻辑

## 9. provider 层和工具系统是什么关系

你前面已经理解了工具系统，所以这里重点就是两者的交点。

provider 层接收到的请求里，不只是 `messages`，还会一起接收 `tools`。

可以理解成：

```text
messages
+ tools schema
→ provider
→ 模型
```

模型再返回：

- 正文
- 或者 `tool_calls`

provider 层要负责把这两类结果都翻译成 EleBot 内部能理解的结构。

所以工具系统和 provider 的关系是：

> 工具系统定义“有哪些能力可以调用”，  
> provider 层负责把这些工具定义随模型请求一起发出去。

## 10. 你可以怎么理解 provider 这一层

最准确的理解方式是：

> provider 不是“模型本身”，  
> 而是 EleBot 和模型服务之间的翻译器与稳定器。

它做的事情包括：

- 路由到正确 backend
- 组装请求
- 传递 `messages + tools`
- 解析 `tool_calls`
- 统一 usage
- 统一错误和重试
- 吃掉 provider 之间的兼容差异

## 11. 当前最值得继续深挖的点

如果你读完这篇还要继续，我建议按这个顺序看：

1. [elebot/providers/factory.py](../elebot/providers/factory.py#L10-L82)
   先看 provider 是怎么从配置路由到具体 backend 的

2. [elebot/providers/registry.py](../elebot/providers/registry.py#L11-L365)
   看 provider spec 和 backend 映射

3. [elebot/providers/base.py](../elebot/providers/base.py#L18-L171)
   看统一数据结构和基类职责

4. [elebot/providers/openai_compat_provider.py](../elebot/providers/openai_compat_provider.py#L130-L351)
   看当前主实现

## 12. 读完这篇后，下一步看什么

推荐继续看：

- [TOOLS](./TOOLS.md)
- [AGENT](./AGENT.md)
