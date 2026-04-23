"""Azure OpenAI 提供方，基于 OpenAI SDK 的 Responses API 实现。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from elebot.providers.base import LLMProvider, LLMResponse
from elebot.providers.openai_responses import (
    consume_sdk_stream,
    convert_messages,
    convert_tools,
    parse_response_output,
)


class AzureOpenAIProvider(LLMProvider):
    """封装 Azure OpenAI 的 Responses API 调用能力。"""

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        default_model: str = "gpt-5.2-chat",
    ):
        """初始化 Azure OpenAI 提供方。

        参数:
            api_key: Azure OpenAI API Key。
            api_base: Azure 终结点地址。
            default_model: 默认部署或模型名称。

        返回:
            无返回值。
        """
        super().__init__(api_key, api_base)
        self.default_model = default_model

        if not api_key:
            raise ValueError("Azure OpenAI api_key is required")
        if not api_base:
            raise ValueError("Azure OpenAI api_base is required")

        # 统一补齐末尾斜杠，避免后续拼接 base_url 时出现双路径分支。
        if not api_base.endswith("/"):
            api_base += "/"
        self.api_base = api_base

        # 这里直接指向 Azure 的 Responses API 前缀，避免上层再做地址推断。
        base_url = f"{api_base.rstrip('/')}/openai/v1/"
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
            max_retries=0,
        )

    # 请求体构造与错误转换统一放在这一层，调用方只关心标准接口。

    @staticmethod
    def _supports_temperature(
        deployment_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        """判断当前部署是否支持 temperature 参数。

        参数:
            deployment_name: Azure 部署名称。
            reasoning_effort: 推理强度配置。

        返回:
            支持时返回 ``True``。
        """
        if reasoning_effort:
            return False
        name = deployment_name.lower()
        return not any(token in name for token in ("gpt-5", "o1", "o3", "o4"))

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        """把统一调用参数转换为 Azure Responses API 请求体。

        参数:
            messages: 消息列表。
            tools: 可选工具定义。
            model: 指定模型或部署名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。
            reasoning_effort: 推理强度配置。
            tool_choice: 工具选择策略。

        返回:
            可直接传给 SDK 的请求体字典。
        """
        deployment = model or self.default_model
        instructions, input_items = convert_messages(self._sanitize_empty_content(messages))

        body: dict[str, Any] = {
            "model": deployment,
            "instructions": instructions or None,
            "input": input_items,
            "max_output_tokens": max(1, max_tokens),
            "store": False,
            "stream": False,
        }

        if self._supports_temperature(deployment, reasoning_effort):
            body["temperature"] = temperature

        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
            body["include"] = ["reasoning.encrypted_content"]

        if tools:
            body["tools"] = convert_tools(tools)
            body["tool_choice"] = tool_choice or "auto"

        return body

    @staticmethod
    def _handle_error(e: Exception) -> LLMResponse:
        response = getattr(e, "response", None)
        body = getattr(e, "body", None) or getattr(response, "text", None)
        body_text = str(body).strip() if body is not None else ""
        msg = f"Error: {body_text[:500]}" if body_text else f"Error calling Azure OpenAI: {e}"
        retry_after = LLMProvider._extract_retry_after_from_headers(getattr(response, "headers", None))
        if retry_after is None:
            retry_after = LLMProvider._extract_retry_after(msg)
        return LLMResponse(content=msg, finish_reason="error", retry_after=retry_after)

    # 对外接口保持与其他提供方一致，便于统一接入主循环。

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """执行一次非流式 Azure OpenAI 请求。

        参数:
            messages: 消息列表。
            tools: 可选工具定义。
            model: 指定模型或部署名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。
            reasoning_effort: 推理强度配置。
            tool_choice: 工具选择策略。

        返回:
            标准化后的模型响应。
        """
        body = self._build_body(
            messages, tools, model, max_tokens, temperature,
            reasoning_effort, tool_choice,
        )
        try:
            response = await self._client.responses.create(**body)
            return parse_response_output(response)
        except Exception as e:
            return self._handle_error(e)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """执行一次流式 Azure OpenAI 请求。

        参数:
            messages: 消息列表。
            tools: 可选工具定义。
            model: 指定模型或部署名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。
            reasoning_effort: 推理强度配置。
            tool_choice: 工具选择策略。
            on_content_delta: 文本流回调。

        返回:
            标准化后的模型响应。
        """
        body = self._build_body(
            messages, tools, model, max_tokens, temperature,
            reasoning_effort, tool_choice,
        )
        body["stream"] = True

        try:
            stream = await self._client.responses.create(**body)
            content, tool_calls, finish_reason, usage, reasoning_content = (
                await consume_sdk_stream(stream, on_content_delta)
            )
            return LLMResponse(
                content=content or None,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                reasoning_content=reasoning_content,
            )
        except Exception as e:
            return self._handle_error(e)

    def get_default_model(self) -> str:
        """返回 Azure OpenAI 的默认模型或部署名。

        返回:
            当前默认模型名称。
        """
        return self.default_model
