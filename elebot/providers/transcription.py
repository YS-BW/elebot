"""语音转写提供方，当前包含 OpenAI Whisper 与 Groq。"""

import os
from pathlib import Path

import httpx
from loguru import logger


class OpenAITranscriptionProvider:
    """基于 OpenAI Whisper API 的语音转写提供方。"""

    def __init__(self, api_key: str | None = None):
        """初始化 OpenAI 语音转写提供方。

        参数:
            api_key: OpenAI API Key，未传时从环境变量读取。

        返回:
            无返回值。
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.api_url = "https://api.openai.com/v1/audio/transcriptions"

    async def transcribe(self, file_path: str | Path) -> str:
        """转写音频文件。

        参数:
            file_path: 待转写音频文件路径。

        返回:
            转写得到的文本；失败时返回空字符串。
        """
        if not self.api_key:
            logger.warning("OpenAI API key not configured for transcription")
            return ""
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""
        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {"file": (path.name, f), "model": (None, "whisper-1")}
                    headers = {"Authorization": f"Bearer {self.api_key}"}
                    response = await client.post(
                        self.api_url, headers=headers, files=files, timeout=60.0,
                    )
                    response.raise_for_status()
                    return response.json().get("text", "")
        except Exception as e:
            logger.error("OpenAI transcription error: {}", e)
            return ""


class GroqTranscriptionProvider:
    """基于 Groq Whisper API 的语音转写提供方。"""

    def __init__(self, api_key: str | None = None):
        """初始化 Groq 语音转写提供方。

        参数:
            api_key: Groq API Key，未传时从环境变量读取。

        返回:
            无返回值。
        """
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"

    async def transcribe(self, file_path: str | Path) -> str:
        """转写音频文件。

        参数:
            file_path: 待转写音频文件路径。

        返回:
            转写得到的文本；失败时返回空字符串。
        """
        if not self.api_key:
            logger.warning("Groq API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f),
                        "model": (None, "whisper-large-v3"),
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        timeout=60.0
                    )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")

        except Exception as e:
            logger.error("Groq transcription error: {}", e)
            return ""
