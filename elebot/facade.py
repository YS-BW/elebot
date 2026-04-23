"""elebot 的程序化入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from elebot.agent.hook import AgentHook
from elebot.agent.loop import AgentLoop
from elebot.bus.queue import MessageBus


@dataclass(slots=True)
class RunResult:
    """单次运行的结果。"""

    content: str
    tools_used: list[str]
    messages: list[dict[str, Any]]


class Elebot:
    """面向代码调用的 elebot 外观对象。"""

    def __init__(self, loop: AgentLoop) -> None:
        """绑定一条已经装配完成的主循环。

        Facade 本身不重新管理 Provider、Bus 或 Session，
        只负责把程序化调用收口到现有主链路上。
        """
        self._loop = loop

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        workspace: str | Path | None = None,
    ) -> "Elebot":
        """从配置文件创建一个可直接调用的 bot。

        Args:
            config_path: 配置文件路径；为空时读取默认配置。
            workspace: 可选工作区覆盖路径。

        Returns:
            已完成主链路装配的 `Elebot` 实例。
        """
        from elebot.config.loader import load_config, resolve_config_env_vars
        from elebot.config.schema import Config

        resolved: Path | None = None
        if config_path is not None:
            resolved = Path(config_path).expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Config not found: {resolved}")

        config: Config = resolve_config_env_vars(load_config(resolved))
        if workspace is not None:
            config.agents.defaults.workspace = str(
                Path(workspace).expanduser().resolve()
            )

        provider = _make_provider(config)
        bus = MessageBus()
        defaults = config.agents.defaults

        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=config.workspace_path,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=defaults.context_window_tokens,
            context_block_limit=defaults.context_block_limit,
            max_tool_result_chars=defaults.max_tool_result_chars,
            provider_retry_mode=defaults.provider_retry_mode,
            web_config=config.tools.web,
            exec_config=config.tools.exec,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            mcp_servers=config.tools.mcp_servers,
            timezone=defaults.timezone,
            unified_session=defaults.unified_session,
            disabled_skills=defaults.disabled_skills,
            session_ttl_minutes=defaults.session_ttl_minutes,
        )
        return cls(loop)

    async def run(
        self,
        message: str,
        *,
        session_key: str = "sdk:default",
        hooks: list[AgentHook] | None = None,
    ) -> RunResult:
        """运行一次主链路，并返回正文、工具与原始消息。

        Args:
            message: 本轮发送给模型的用户输入。
            session_key: 会话键；同一个键会复用历史上下文。
            hooks: 本轮额外挂载的 hook 列表。

        Returns:
            包含最终正文、工具调用和消息轨迹的结果对象。
        """
        prev = self._loop._extra_hooks
        if hooks is not None:
            self._loop._extra_hooks = list(hooks)
        try:
            result = await self._loop.process_direct_result(
                message, session_key=session_key,
            )
        finally:
            self._loop._extra_hooks = prev

        content = result.final_content or (result.outbound.content if result.outbound else "") or ""
        return RunResult(
            content=content,
            tools_used=list(result.tools_used),
            messages=list(result.messages),
        )


def _make_provider(config: Any) -> Any:
    """按当前模型配置构建 provider。"""
    from elebot.providers.base import GenerationSettings
    from elebot.providers.registry import find_by_name

    model = config.agents.defaults.model
    forced_provider = config.agents.defaults.provider
    if forced_provider != "auto" and find_by_name(forced_provider) is None:
        raise ValueError(f"Unknown provider configured: {forced_provider}")
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    if backend == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (p and p.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    if backend == "openai_codex":
        from elebot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(default_model=model)
    elif backend == "github_copilot":
        from elebot.providers.github_copilot_provider import GitHubCopilotProvider

        provider = GitHubCopilotProvider(default_model=model)
    elif backend == "azure_openai":
        from elebot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=p.api_key, api_base=p.api_base, default_model=model
        )
    elif backend == "anthropic":
        from elebot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    else:
        from elebot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider
