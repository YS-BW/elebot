"""提供方注册表，集中维护 LLM 提供方元数据。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic.alias_generators import to_snake


@dataclass(frozen=True)
class ProviderSpec:
    """描述单个 LLM 提供方的注册元数据。

    ``env_extras`` 中支持的占位符：
    - ``{api_key}``：用户配置的 API Key
    - ``{api_base}``：配置中的 api_base，或当前条目的默认地址
    """

    # 标识信息
    name: str  # 配置中的字段名，例如 "dashscope"。
    keywords: tuple[str, ...]  # 用于模型名匹配的关键词，需为小写。
    env_key: str  # 默认 API Key 环境变量名，例如 "DASHSCOPE_API_KEY"。
    display_name: str = ""  # 在 `elebot status` 中展示的名称。

    # 选择哪种提供方实现
    # 可选值包括 "openai_compat"、"anthropic"、"azure_openai"、"openai_codex"、"github_copilot"
    backend: str = "openai_compat"

    # 需要额外注入的环境变量，例如 (("ZHIPUAI_API_KEY", "{api_key}"),)
    env_extras: tuple[tuple[str, str], ...] = ()

    # 网关或本地部署识别
    is_gateway: bool = False  # 是否可路由任意模型，例如 OpenRouter、AiHubMix。
    is_local: bool = False  # 是否属于本地部署，例如 vLLM、Ollama。
    detect_by_key_prefix: str = ""  # 通过 API Key 前缀识别，例如 "sk-or-"。
    detect_by_base_keyword: str = ""  # 通过 api_base 里的关键字识别。
    default_api_base: str = ""  # 提供方默认的 OpenAI 兼容基础地址。

    # 网关行为控制
    strip_model_prefix: bool = False  # 发送前是否去掉 "provider/" 这类模型前缀。
    supports_max_completion_tokens: bool = False

    # 针对特定模型的参数覆盖，例如 (("kimi-k2.5", {"temperature": 1.0}),)
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()

    # OAuth 提供方通常不使用 API Key，例如 OpenAI Codex。
    is_oauth: bool = False

    # 直连提供方跳过 API Key 校验，由用户自行提供全部连接信息。
    is_direct: bool = False

    # 是否支持在内容块上使用 cache_control，例如 Anthropic prompt caching。
    supports_prompt_caching: bool = False

    @property
    def label(self) -> str:
        """返回展示给用户的提供方名称。

        返回:
            优先使用 ``display_name``，否则回退到 title 化后的 ``name``。
        """
        return self.display_name or self.name.title()


# PROVIDERS 是唯一注册表，顺序会直接影响匹配优先级，网关类条目需排在前面。

PROVIDERS: tuple[ProviderSpec, ...] = (
    # 自定义直连 OpenAI 兼容端点。
    ProviderSpec(
        name="custom",
        keywords=(),
        env_key="",
        display_name="Custom",
        backend="openai_compat",
        is_direct=True,
    ),

    # Azure OpenAI，直接调用新版 Responses API。
    ProviderSpec(
        name="azure_openai",
        keywords=("azure", "azure-openai"),
        env_key="",
        display_name="Azure OpenAI",
        backend="azure_openai",
        is_direct=True,
    ),
    # 网关类提供方通过 api_key 或 api_base 识别，而不是靠模型名匹配。
    # 网关可以承载任意模型，因此回退匹配时优先级更高。
    # OpenRouter 的 key 通常以 "sk-or-" 开头。
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        backend="openai_compat",
        is_gateway=True,
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        default_api_base="https://openrouter.ai/api/v1",
        supports_prompt_caching=True,
    ),
    # AiHubMix 是 OpenAI 兼容网关。
    # 这里去掉模型前缀，是为了兼容不接受 "anthropic/claude-3" 这类写法的网关。
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        env_key="OPENAI_API_KEY",
        display_name="AiHubMix",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="aihubmix",
        default_api_base="https://aihubmix.com/v1",
        strip_model_prefix=True,
    ),
    # SiliconFlow（硅基流动）是 OpenAI 兼容网关，模型名保留组织前缀。
    ProviderSpec(
        name="siliconflow",
        keywords=("siliconflow",),
        env_key="OPENAI_API_KEY",
        display_name="SiliconFlow",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="siliconflow",
        default_api_base="https://api.siliconflow.cn/v1",
    ),

    # VolcEngine（火山引擎）是按量计费的 OpenAI 兼容网关。
    ProviderSpec(
        name="volcengine",
        keywords=("volcengine", "volces", "ark"),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="volces",
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
    ),

    # VolcEngine Coding Plan 与 volcengine 复用同一套密钥。
    ProviderSpec(
        name="volcengine_coding_plan",
        keywords=("volcengine-plan",),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine Coding Plan",
        backend="openai_compat",
        is_gateway=True,
        default_api_base="https://ark.cn-beijing.volces.com/api/coding/v3",
        strip_model_prefix=True,
    ),

    # BytePlus 是 VolcEngine 国际版，同样按量计费。
    ProviderSpec(
        name="byteplus",
        keywords=("byteplus",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="bytepluses",
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/v3",
        strip_model_prefix=True,
    ),

    # BytePlus Coding Plan 与 byteplus 复用同一套密钥。
    ProviderSpec(
        name="byteplus_coding_plan",
        keywords=("byteplus-plan",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus Coding Plan",
        backend="openai_compat",
        is_gateway=True,
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/coding/v3",
        strip_model_prefix=True,
    ),
    # 标准提供方按模型关键字匹配。
    # Anthropic 使用原生 Anthropic SDK。
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        backend="anthropic",
        supports_prompt_caching=True,
    ),
    # OpenAI 走 SDK 默认地址，无需额外覆盖。
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend="openai_compat",
        supports_max_completion_tokens=True,
    ),
    # OpenAI Codex 使用独立 OAuth 提供方实现。
    ProviderSpec(
        name="openai_codex",
        keywords=("openai-codex",),
        env_key="",
        display_name="OpenAI Codex",
        backend="openai_codex",
        detect_by_base_keyword="codex",
        default_api_base="https://chatgpt.com/backend-api",
        is_oauth=True,
    ),
    # GitHub Copilot 使用 OAuth 登录。
    ProviderSpec(
        name="github_copilot",
        keywords=("github_copilot", "copilot"),
        env_key="",
        display_name="Github Copilot",
        backend="github_copilot",
        default_api_base="https://api.githubcopilot.com",
        strip_model_prefix=True,
        is_oauth=True,
    ),
    # DeepSeek 提供 OpenAI 兼容接口。
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        backend="openai_compat",
        default_api_base="https://api.deepseek.com",
    ),
    # Gemini 使用 Google 提供的 OpenAI 兼容端点。
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        backend="openai_compat",
        default_api_base="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    # Zhipu（智谱）提供 OpenAI 兼容接口。
    ProviderSpec(
        name="zhipu",
        keywords=("zhipu", "glm", "zai"),
        env_key="ZAI_API_KEY",
        display_name="Zhipu AI",
        backend="openai_compat",
        env_extras=(("ZHIPUAI_API_KEY", "{api_key}"),),
        default_api_base="https://open.bigmodel.cn/api/paas/v4",
    ),
    # DashScope（通义）承载 Qwen 系列模型。
    ProviderSpec(
        name="dashscope",
        keywords=("qwen", "dashscope"),
        env_key="DASHSCOPE_API_KEY",
        display_name="DashScope",
        backend="openai_compat",
        default_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    # Moonshot（月之暗面）承载 Kimi 模型，K2.5 要求 temperature 不低于 1.0。
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot",
        backend="openai_compat",
        default_api_base="https://api.moonshot.ai/v1",
        model_overrides=(("kimi-k2.5", {"temperature": 1.0}),),
    ),
    # MiniMax 提供 OpenAI 兼容接口。
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        backend="openai_compat",
        default_api_base="https://api.minimax.io/v1",
    ),
    # Mistral AI 提供 OpenAI 兼容接口。
    ProviderSpec(
        name="mistral",
        keywords=("mistral",),
        env_key="MISTRAL_API_KEY",
        display_name="Mistral",
        backend="openai_compat",
        default_api_base="https://api.mistral.ai/v1",
    ),
    # Step Fun（阶跃星辰）提供 OpenAI 兼容接口。
    ProviderSpec(
        name="stepfun",
        keywords=("stepfun", "step"),
        env_key="STEPFUN_API_KEY",
        display_name="Step Fun",
        backend="openai_compat",
        default_api_base="https://api.stepfun.com/v1",
    ),
    # Xiaomi MIMO（小米）提供 OpenAI 兼容接口。
    ProviderSpec(
        name="xiaomi_mimo",
        keywords=("xiaomi_mimo", "mimo"),
        env_key="XIAOMIMIMO_API_KEY",
        display_name="Xiaomi MIMO",
        backend="openai_compat",
        default_api_base="https://api.xiaomimimo.com/v1",
    ),
    # 本地部署优先靠配置字段识别，而不是 api_base。
    # vLLM 或任意本地 OpenAI 兼容服务。
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        env_key="HOSTED_VLLM_API_KEY",
        display_name="vLLM/Local",
        backend="openai_compat",
        is_local=True,
    ),
    # Ollama，本地 OpenAI 兼容服务。
    ProviderSpec(
        name="ollama",
        keywords=("ollama", "nemotron"),
        env_key="OLLAMA_API_KEY",
        display_name="Ollama",
        backend="openai_compat",
        is_local=True,
        detect_by_base_keyword="11434",
        default_api_base="http://localhost:11434/v1",
    ),
    # OpenVINO Model Server，本地直连，接口兼容 OpenAI /v3。
    ProviderSpec(
        name="ovms",
        keywords=("openvino", "ovms"),
        env_key="",
        display_name="OpenVINO Model Server",
        backend="openai_compat",
        is_direct=True,
        is_local=True,
        default_api_base="http://localhost:8000/v3",
    ),
    # 辅助型提供方，不是主链路默认 LLM 首选。
    # Groq 主要用于语音转写，也可以承载 LLM。
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        backend="openai_compat",
        default_api_base="https://api.groq.com/openai/v1",
    ),
    # Qianfan（百度千帆）提供 OpenAI 兼容接口。
    ProviderSpec(
        name="qianfan",
        keywords=("qianfan", "ernie"),
        env_key="QIANFAN_API_KEY",
        display_name="Qianfan",
        backend="openai_compat",
        default_api_base="https://qianfan.baidubce.com/v2"
    ),
)
def find_by_name(name: str) -> ProviderSpec | None:
    """按配置字段名查找提供方定义。

    参数:
        name: 配置中的提供方名称，可包含中划线或下划线。

    返回:
        匹配到的提供方定义，未找到时返回 ``None``。
    """
    normalized = to_snake(name.replace("-", "_"))
    for spec in PROVIDERS:
        if spec.name == normalized:
            return spec
    return None
