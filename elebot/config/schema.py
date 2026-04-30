"""基于 Pydantic 的配置模型。"""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings


class Base(BaseModel):
    """同时接受 camelCase 和 snake_case 键名的基础模型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class StrictBase(BaseModel):
    """同时接受 camelCase 和 snake_case，并拒绝未知字段的基础模型。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


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
    model: str = "deepseek-v4-flash"
    provider: str = "deepseek"
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


class WebSocketChannelConfig(StrictBase):
    """WebSocket channel 的最小配置。"""

    enabled: bool = False
    port: int = Field(default=8765, ge=1, le=65535)
    path: str = "/"
    streaming: bool = True


class WeixinChannelConfig(StrictBase):
    """个人微信 channel 的最小配置。"""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    base_url: str = "https://ilinkai.weixin.qq.com"
    route_tag: str | int | None = None
    token: str = ""
    state_dir: str = ""
    poll_timeout: int = Field(default=35, ge=1)


class ChannelsConfig(StrictBase):
    """多通道入口配置。"""

    websocket: WebSocketChannelConfig = Field(default_factory=WebSocketChannelConfig)
    weixin: WeixinChannelConfig = Field(default_factory=WeixinChannelConfig)


class Config(BaseSettings):
    """elebot 根配置。"""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)

    @property
    def workspace_path(self) -> Path:
        """返回展开后的工作区路径。"""
        return Path(self.agents.defaults.workspace).expanduser()

    model_config = ConfigDict(env_prefix="ELEBOT_", env_nested_delimiter="__")
