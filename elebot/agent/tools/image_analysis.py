"""图片理解工具。"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from elebot.agent.messages import build_image_content_blocks, detect_image_mime
from elebot.agent.tools.base import Tool, tool_parameters
from elebot.agent.tools.filesystem import _resolve_path
from elebot.agent.tools.schema import StringSchema, tool_parameters_schema
from elebot.providers.base import LLMProvider


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema("要查看的图片文件路径"),
        prompt=StringSchema("要模型回答的图片问题；默认请描述图片内容"),
        required=["path"],
    )
)
class AnalyzeImageTool(Tool):
    """显式触发一次独立的多模态看图请求。"""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        extra_allowed_dirs: list[Path] | None = None,
    ) -> None:
        """初始化看图工具依赖。"""
        self._provider = provider
        self._model = model
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        self._extra_allowed_dirs = extra_allowed_dirs or []

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "analyze_image"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return (
            "查看一张本地图片并回答问题。"
            "当需要真正理解图片内容时使用，不要只靠 read_file 猜测图片内容。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """返回工具参数 Schema。"""
        return self.__class__.parameters  # type: ignore[return-value]

    @property
    def read_only(self) -> bool:
        """声明该工具为只读。"""
        return True

    async def execute(self, path: str | None = None, prompt: str | None = None, **kwargs: Any) -> Any:
        """执行一次独立的图片理解请求。"""
        del kwargs
        if not path:
            return "Error: missing path"

        try:
            resolved = _resolve_path(
                path,
                workspace=self._workspace,
                allowed_dir=self._allowed_dir,
                extra_allowed_dirs=self._extra_allowed_dirs,
            )
        except PermissionError as exc:
            return f"Error: {exc}"

        if not resolved.exists():
            return f"Error: File not found: {path}"
        if not resolved.is_file():
            return f"Error: Not a file: {path}"

        raw = resolved.read_bytes()
        if not raw:
            return f"Error: Empty image file: {path}"

        mime = detect_image_mime(raw) or mimetypes.guess_type(str(resolved))[0]
        if not mime or not mime.startswith("image/"):
            return f"Error: Not an image file: {path}"

        ask = (prompt or "请直接描述这张图片里有什么，尽量具体。").strip()
        user_content = build_image_content_blocks(raw, mime, str(resolved), ask)
        response = await self._provider.chat_with_retry(
            messages=[{"role": "user", "content": user_content}],
            model=self._model,
        )
        if response.finish_reason == "error":
            return response.content or "Error: image analysis failed"
        return (response.content or "").strip() or "未识别到可用图片描述。"
