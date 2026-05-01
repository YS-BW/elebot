"""语音转写 provider，当前只接入 DashScope `qwen3-asr-flash`。"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from elebot.config.schema import Config

_DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
def _detect_audio_format(raw: bytes, path: Path) -> str | None:
    """根据文件头和扩展名识别 `qwen3-asr-flash` 所需的音频格式名。

    参数:
        raw: 音频原始字节。
        path: 原始文件路径。

    返回:
        识别出的格式名；无法识别或模型不支持时返回 `None`。
    """
    if raw.startswith(b"#!AMR"):
        return "amr"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WAVE":
        return "wav"
    if raw.startswith(b"OggS"):
        return "ogg"
    if raw.startswith(b"ID3") or (len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0):
        return "mp3"
    if raw.startswith(b"fLaC"):
        return "flac"
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return "m4a"

    ext = path.suffix.lower().lstrip(".")
    if ext in {"aac", "amr", "flac", "m4a", "mp3", "ogg", "opus", "wav", "webm"}:
        return ext
    return None


def _extract_text_from_response(data: dict[str, Any]) -> str:
    """从 OpenAI 兼容响应里提取转写文本。

    参数:
        data: 接口返回的 JSON 对象。

    返回:
        解析出的文本；不存在时返回空字符串。
    """
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = str(item.get("text", "") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _audio_format_to_mime(audio_format: str) -> str | None:
    """把识别出的音频格式映射成 Data URL 所需 MIME 类型。

    参数:
        audio_format: 识别出的音频格式名。

    返回:
        对应 MIME 类型；未知格式返回 `None`。
    """
    return {
        "aac": "audio/aac",
        "amr": "audio/amr",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "opus": "audio/ogg",
        "wav": "audio/wav",
        "webm": "audio/webm",
    }.get(audio_format)


class QwenAsrTranscriptionProvider:
    """基于 DashScope `qwen3-asr-flash` 的语音转写 provider。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        """初始化语音转写 provider。

        参数:
            api_key: DashScope API Key；未传时回退 `DASHSCOPE_API_KEY`。
            api_base: DashScope OpenAI 兼容地址。

        返回:
            无返回值。
        """
        self.api_key = (api_key or os.environ.get("DASHSCOPE_API_KEY") or "").strip()
        self.api_base = (api_base or _DEFAULT_API_BASE).rstrip("/")
        self.model = "qwen3-asr-flash"

    async def transcribe(self, file_path: str | Path) -> str:
        """转写一段本地音频文件。

        参数:
            file_path: 本地音频路径。

        返回:
            转写文本；失败时返回空字符串。
        """
        if not self.api_key:
            logger.warning("DashScope API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.warning("Audio file not found for transcription: {}", file_path)
            return ""

        raw = path.read_bytes()
        audio_format = _detect_audio_format(raw, path)
        if not audio_format:
            logger.warning("Unsupported audio format for qwen3-asr-flash: {}", path.name)
            return ""
        mime = _audio_format_to_mime(audio_format)
        if not mime:
            logger.warning("Unsupported audio mime for qwen3-asr-flash: {}", audio_format)
            return ""
        data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode()}"

        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": data_uri,
                            },
                        },
                    ],
                }
            ],
            "stream": False,
            "asr_options": {"enable_itn": False},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self.api_base}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(endpoint, headers=headers, json=body)
                response.raise_for_status()
        except Exception as exc:
            logger.warning("qwen3-asr-flash transcription failed: {}", exc)
            return ""

        return _extract_text_from_response(response.json())


def build_transcription_provider(config: Config) -> QwenAsrTranscriptionProvider | None:
    """按当前配置构建语音转写 provider。

    参数:
        config: 已解析后的完整配置对象。

    返回:
        可用的转写 provider；未配置 API Key 时返回 `None`。
    """
    transcription = config.transcription
    api_key = (transcription.api_key or os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        return None
    return QwenAsrTranscriptionProvider(
        api_key=api_key,
        api_base=transcription.api_base or _DEFAULT_API_BASE,
    )
