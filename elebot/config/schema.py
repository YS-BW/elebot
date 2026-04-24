"""基于 Pydantic 的配置模型。"""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings


class Base(BaseModel):
    """同时接受 camelCase 和 snake_case 键名的基础模型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DreamConfig(Base):
    """Dream 记忆整理配置。"""

    model_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("modelOverride", "model", "model_override"),
    )
    max_batch_size: int = Field(default=20, ge=1)
    max_iterations: int = Field(default=10, ge=1)


class AgentDefaults(Base):
    """Agent 默认配置。"""

    workspace: str = "~/.elebot/workspace"
    model: str = "qwen3_6_plus"
    provider: str = "dashscope"
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    context_block_limit: int | None = None
    temperature: float = 0.1
    max_tool_iterations: int = 200
    max_tool_result_chars: int = 16_000
    provider_retry_mode: Literal["standard", "persistent"] = "standard"
    reasoning_effort: str | None = None
    timezone: str = "UTC"
    unified_session: bool = False
    session_ttl_minutes: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("idleCompactAfterMinutes", "sessionTtlMinutes"),
        serialization_alias="idleCompactAfterMinutes",
    )
    dream: DreamConfig = Field(default_factory=DreamConfig)


class AgentsConfig(Base):
    """Agent 配置。"""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(Base):
    """单个 LLM provider 配置。"""

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None


class ProvidersConfig(Base):
    """LLM providers 配置集合。"""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)
    ovms: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    mistral: ProviderConfig = Field(default_factory=ProviderConfig)
    stepfun: ProviderConfig = Field(default_factory=ProviderConfig)
    xiaomi_mimo: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)
    volcengine_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)
    byteplus: ProviderConfig = Field(default_factory=ProviderConfig)
    byteplus_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)
    openai_codex: ProviderConfig = Field(default_factory=ProviderConfig, exclude=True)
    github_copilot: ProviderConfig = Field(default_factory=ProviderConfig, exclude=True)
    qianfan: ProviderConfig = Field(default_factory=ProviderConfig)


class WebSearchConfig(Base):
    """Web 搜索工具配置。"""

    provider: str = "duckduckgo"  # 支持 brave、tavily、duckduckgo、searxng、jina、kagi
    api_key: str = ""
    base_url: str = ""  # SearXNG 服务地址
    max_results: int = 5
    timeout: int = 30  # 搜索操作的总超时时间，单位秒。


class WebToolsConfig(Base):
    """Web 工具配置。"""

    enable: bool = True
    proxy: str | None = (
        None  # HTTP 或 SOCKS5 代理地址，例如 "http://127.0.0.1:7890"
    )
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Shell 执行工具配置。"""

    enable: bool = True
    timeout: int = 60
    path_append: str = ""
    sandbox: str = ""  # 沙箱后端，空字符串表示不启用，"bwrap" 表示 bubblewrap。
    allowed_env_keys: list[str] = Field(default_factory=list)  # 允许透传给子进程的环境变量名。

class MCPServerConfig(Base):
    """MCP 服务连接配置。"""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None  # 不填时由运行时自动判断协议。
    command: str = ""  # stdio 模式下要执行的命令。
    args: list[str] = Field(default_factory=list)  # stdio 模式下的命令参数。
    env: dict[str, str] = Field(default_factory=dict)  # stdio 模式下附加环境变量。
    url: str = ""  # HTTP 或 SSE 模式的服务地址。
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP 或 SSE 模式下的自定义请求头。
    tool_timeout: int = 30  # 单次工具调用超时时间，单位秒。
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])  # 用于限制注册到本地的工具白名单。

class ToolsConfig(Base):
    """工具系统配置。"""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # 为 True 时把工具访问范围限制到工作区。
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class Config(BaseSettings):
    """elebot 根配置。"""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @property
    def workspace_path(self) -> Path:
        """返回展开后的工作区路径。"""
        return Path(self.agents.defaults.workspace).expanduser()

    def _match_provider(
        self, model: str | None = None
    ) -> tuple["ProviderConfig | None", str | None]:
        """Match provider config and its registry name. Returns (config, spec_name)."""
        from elebot.providers.registry import PROVIDERS, find_by_name

        model_lower = (model or self.agents.defaults.model).lower()
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        # 显式模型前缀必须优先，避免默认 provider 抢走已声明路由的模型。
        if model_prefix:
            spec = find_by_name(normalized_prefix)
            if spec is not None:
                return getattr(self.providers, spec.name, None), spec.name

        forced = self.agents.defaults.provider
        if forced != "auto":
            spec = find_by_name(forced)
            if spec:
                p = getattr(self.providers, spec.name, None)
                return (p, spec.name) if p else (None, None)
            raise ValueError(f"Unknown provider configured: {forced}")

        model_normalized = model_lower.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # 显式 provider 前缀优先，避免 `github-copilot/...codex` 被误判为 openai_codex。
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                if spec.is_oauth or spec.is_local or p.api_key:
                    return p, spec.name

        # 关键字匹配顺序跟随 PROVIDERS 注册表，保证行为稳定。
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth or spec.is_local or p.api_key:
                    return p, spec.name

        # 本地 provider 常常承载无前缀模型名，因此需要在这里补一层兜底匹配。
        # 如果 api_base 能命中特征关键字，则优先使用该 provider，避免按注册顺序误选。
        local_fallback: tuple[ProviderConfig, str] | None = None
        for spec in PROVIDERS:
            if not spec.is_local:
                continue
            p = getattr(self.providers, spec.name, None)
            if not (p and p.api_base):
                continue
            if spec.detect_by_base_keyword and spec.detect_by_base_keyword in p.api_base:
                return p, spec.name
            if local_fallback is None:
                local_fallback = (p, spec.name)
        if local_fallback:
            return local_fallback

        # 最后按网关优先顺序兜底，但 OAuth provider 不能走兜底分支。
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """返回匹配到的 provider 配置。"""
        p, _ = self._match_provider(model)
        return p

    def get_provider_name(self, model: str | None = None) -> str | None:
        """返回匹配到的 provider 注册名。"""
        _, name = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """返回给定模型对应的 API Key。"""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """返回给定模型对应的 API Base。"""
        from elebot.providers.registry import find_by_name

        p, name = self._match_provider(model)
        if p and p.api_base:
            return p.api_base
        # 这里只给网关和本地 provider 补默认 api_base，标准 provider 由构造器自行解析。
        if name:
            spec = find_by_name(name)
            if spec and (spec.is_gateway or spec.is_local) and spec.default_api_base:
                return spec.default_api_base
        return None

    model_config = ConfigDict(env_prefix="ELEBOT_", env_nested_delimiter="__")
