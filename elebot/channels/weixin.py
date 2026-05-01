"""个人微信 HTTP 长轮询 channel。"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import random
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

from elebot.agent.messages import detect_image_mime
from elebot.bus.events import OutboundMessage
from elebot.channels.base import BaseChannel
from elebot.config.paths import get_media_dir, get_runtime_subdir
from elebot.runtime.protocol import default_session_id

ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5
MESSAGE_TYPE_BOT = 2
MESSAGE_STATE_FINISH = 2
WEIXIN_MAX_MESSAGE_LEN = 4000
WEIXIN_CHANNEL_VERSION = "2.1.1"
ILINK_APP_ID = "bot"
WEIXIN_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
WEIXIN_STREAM_PART_MARKER = "<part>"
_WEIXIN_INBOUND_TEXT = {
    "image_ok": "用户发送了一张图片，请结合附件理解。",
    "image_failed": "用户发送了一张图片，但当前未能下载图片内容。",
    "file_ok": "用户发送了文件，请结合附件处理。",
    "file_failed": "用户发送了一个文件，但当前未能下载文件内容。",
    "voice_transcribe_failed": "用户发送了一段语音，但当前无法完成转写。",
    "voice_download_failed": "用户发送了一段语音，但当前未能下载语音内容。",
    "video": "用户发送了一个视频。",
    "media_only_fallback": "用户发送了图片，请结合附件理解并回答。",
}


def _build_client_version(version: str) -> int:
    """把语义化版本编码成接口要求的 uint32 数值。

    参数:
        version: 语义化版本字符串。

    返回:
        编码后的版本整数。
    """

    parts = version.split(".")

    def _as_int(index: int) -> int:
        try:
            return int(parts[index])
        except Exception:
            return 0

    major = _as_int(0)
    minor = _as_int(1)
    patch = _as_int(2)
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


ILINK_APP_CLIENT_VERSION = _build_client_version(WEIXIN_CHANNEL_VERSION)
BASE_INFO: dict[str, str] = {"channel_version": WEIXIN_CHANNEL_VERSION}


def _pkcs7_unpad_safe(data: bytes, block_size: int = 16) -> bytes:
    """安全去除 PKCS7 padding；非法 padding 时直接返回原字节。"""
    if not data or len(data) % block_size != 0:
        return data
    pad_len = data[-1]
    if pad_len < 1 or pad_len > block_size:
        return data
    if data[-pad_len:] != bytes([pad_len]) * pad_len:
        return data
    return data[:-pad_len]


def _parse_aes_key(aes_key_b64: str) -> bytes:
    """解析微信媒体里出现的 AES key 编码。"""
    decoded = base64.b64decode(aes_key_b64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        return bytes.fromhex(decoded.decode("ascii"))
    raise ValueError(f"unexpected aes key length: {len(decoded)}")


def _decrypt_aes_ecb(data: bytes, aes_key_b64: str) -> bytes:
    """按微信媒体协议解密 AES-128-ECB 内容。"""
    try:
        key = _parse_aes_key(aes_key_b64)
    except Exception as exc:
        logger.warning("Failed to parse weixin AES key: {}", exc)
        return data

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        logger.warning("Cannot decrypt weixin media because cryptography is unavailable.")
        return data

    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    decrypted = decryptor.update(data) + decryptor.finalize()
    return _pkcs7_unpad_safe(decrypted)


def _detect_voice_suffix(raw: bytes) -> str:
    """根据语音字节头推断文件后缀。"""
    if raw.startswith(b"#!AMR"):
        return ".amr"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WAVE":
        return ".wav"
    if raw.startswith(b"OggS"):
        return ".ogg"
    if raw.startswith(b"ID3") or (len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0):
        return ".mp3"
    if raw.startswith(b"fLaC"):
        return ".flac"
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return ".m4a"
    return ".silk"


class WeixinChannel(BaseChannel):
    """基于 ilink HTTP 协议的个人微信 channel。"""

    name = "weixin"

    def __init__(self, config: Any, runtime) -> None:
        """初始化微信 channel 的运行时状态。

        参数:
            config: 当前 channel 配置。
            runtime: runtime 控制面。

        返回:
            无返回值。
        """
        super().__init__(config, runtime)
        self._client: httpx.AsyncClient | None = None
        self._token = ""
        self._get_updates_buf = ""
        self._context_tokens: dict[str, str] = {}
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._state_dir: Path | None = None
        self._stream_buffers: dict[str, str] = {}
        self._stream_has_delta: dict[str, bool] = {}
        self._completed_streams: set[str] = set()

    @property
    def supports_streaming(self) -> bool:
        """个人微信启用基于真实换行的流式分段输出。"""
        return True

    @staticmethod
    def _build_download_candidates(media: dict[str, Any]) -> list[str]:
        """根据微信媒体字段生成候选下载地址。"""
        encrypt_query_param = str(media.get("encrypt_query_param", "") or "")
        full_url = str(media.get("full_url", "") or "").strip()
        download_candidates: list[str] = []
        if full_url:
            download_candidates.append(full_url)
        if encrypt_query_param:
            fallback_url = (
                f"{WEIXIN_CDN_BASE_URL}/download"
                f"?encrypted_query_param={quote(encrypt_query_param)}"
            )
            if fallback_url not in download_candidates:
                download_candidates.append(fallback_url)
        return download_candidates

    async def _download_media_bytes(self, media: dict[str, Any], *, kind: str) -> bytes:
        """按候选地址顺序下载一份微信媒体原始字节。"""
        assert self._client is not None
        data = b""
        for url in self._build_download_candidates(media):
            try:
                response = await self._client.get(url)
                response.raise_for_status()
                data = response.content
                break
            except Exception as exc:
                logger.warning("Weixin {} download failed via {}: {}", kind, url, exc)
        return data

    def _get_state_dir(self) -> Path:
        """返回微信状态目录。

        参数:
            无。

        返回:
            当前实例的微信状态目录。
        """
        if self._state_dir is not None:
            return self._state_dir
        if getattr(self.config, "state_dir", ""):
            state_dir = Path(self.config.state_dir).expanduser()
        else:
            state_dir = get_runtime_subdir("weixin")
        state_dir.mkdir(parents=True, exist_ok=True)
        self._state_dir = state_dir
        return state_dir

    def _get_state_path(self) -> Path:
        """返回微信状态文件路径。

        参数:
            无。

        返回:
            `account.json` 路径。
        """
        return self._get_state_dir() / "account.json"

    def _load_state(self) -> bool:
        """加载已保存的登录状态。

        参数:
            无。

        返回:
            找到有效 token 时返回 `True`。
        """
        state_path = self._get_state_path()
        if not state_path.exists():
            return False
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return False

        self._token = str(data.get("token", "") or "")
        self._get_updates_buf = str(data.get("get_updates_buf", "") or "")
        self._context_tokens = {
            str(user_id): str(token)
            for user_id, token in (data.get("context_tokens") or {}).items()
            if str(user_id).strip() and str(token).strip()
        }
        base_url = str(data.get("base_url", "") or "").strip()
        if base_url:
            self.config.base_url = base_url
        return bool(self._token)

    def _save_state(self) -> None:
        """保存当前登录态和轮询游标。

        参数:
            无。

        返回:
            无返回值。
        """
        state_path = self._get_state_path()
        try:
            state_path.write_text(
                json.dumps(
                    {
                        "token": self._token,
                        "get_updates_buf": self._get_updates_buf,
                        "context_tokens": self._context_tokens,
                        "base_url": self.config.base_url,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save weixin state: {}", exc)

    def _clear_state(self) -> None:
        """清空保存的微信状态。

        参数:
            无。

        返回:
            无返回值。
        """
        self._token = ""
        self._get_updates_buf = ""
        self._context_tokens.clear()
        state_path = self._get_state_path()
        if state_path.exists():
            state_path.unlink()

    @staticmethod
    def _random_wechat_uin() -> str:
        """生成接口要求的随机 UIN 头。

        参数:
            无。

        返回:
            base64 编码后的随机 UIN 字符串。
        """
        uint32 = int.from_bytes(os.urandom(4), "big")
        return base64.b64encode(str(uint32).encode()).decode()

    def _make_headers(self, *, auth: bool = True) -> dict[str, str]:
        """构造微信接口请求头。

        参数:
            auth: 是否附带授权头。

        返回:
            当前请求的 HTTP 头字典。
        """
        headers: dict[str, str] = {
            "X-WECHAT-UIN": self._random_wechat_uin(),
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
        }
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        route_tag = getattr(self.config, "route_tag", None)
        if route_tag is not None and str(route_tag).strip():
            headers["SKRouteTag"] = str(route_tag).strip()
        return headers

    async def _api_get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        """执行一条微信 GET 请求。

        参数:
            endpoint: 接口路径。
            params: 查询参数。
            auth: 是否附带授权头。

        返回:
            解析后的 JSON 响应。
        """
        assert self._client is not None
        response = await self._client.get(
            f"{self.config.base_url}/{endpoint}",
            params=params,
            headers=self._make_headers(auth=auth),
        )
        response.raise_for_status()
        return response.json()

    async def _api_post(
        self,
        endpoint: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> dict[str, Any]:
        """执行一条微信 POST 请求。

        参数:
            endpoint: 接口路径。
            body: JSON 请求体。
            auth: 是否附带授权头。

        返回:
            解析后的 JSON 响应。
        """
        assert self._client is not None
        payload = dict(body or {})
        if "base_info" not in payload:
            payload["base_info"] = BASE_INFO
        response = await self._client.post(
            f"{self.config.base_url}/{endpoint}",
            json=payload,
            headers=self._make_headers(auth=auth),
        )
        response.raise_for_status()
        return response.json()

    async def _fetch_qr_code(self) -> tuple[str, str]:
        """获取一张新的登录二维码。

        参数:
            无。

        返回:
            `(qrcode_id, login_url)` 元组。
        """
        data = await self._api_get(
            "ilink/bot/get_bot_qrcode",
            params={"bot_type": "3"},
            auth=False,
        )
        qrcode_id = str(data.get("qrcode", "") or "")
        login_url = str(data.get("qrcode_img_content", "") or qrcode_id)
        if not qrcode_id:
            raise RuntimeError(f"Failed to fetch weixin QR code: {data}")
        return qrcode_id, login_url

    @staticmethod
    def _print_qr_code(url: str) -> None:
        """尽量把二维码打印到终端，否则回退成 URL。

        参数:
            url: 二维码内容或登录 URL。

        返回:
            无返回值。
        """
        try:
            import qrcode

            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            print(f"\nLogin URL: {url}\n")

    async def _qr_login(self) -> bool:
        """执行二维码登录流程。

        参数:
            无。

        返回:
            登录成功时返回 `True`。
        """
        qrcode_id, login_url = await self._fetch_qr_code()
        self._print_qr_code(login_url)
        logger.info("Scan the QR code in WeChat to finish login.")

        while self._running:
            data = await self._api_get(
                "ilink/bot/get_qrcode_status",
                params={"qrcode": qrcode_id},
                auth=False,
            )
            status = str(data.get("status", "") or "")
            if status == "confirmed":
                token = str(data.get("bot_token", "") or "")
                if not token:
                    raise RuntimeError("Weixin login confirmed but token is missing")
                self._token = token
                base_url = str(data.get("baseurl", "") or "").strip()
                if base_url:
                    self.config.base_url = base_url
                self._save_state()
                logger.info("Weixin login successful.")
                return True
            if status == "expired":
                logger.warning("Weixin QR code expired before confirmation.")
                return False
            await asyncio.sleep(1)

        return False

    async def login(self, force: bool = False) -> bool:
        """执行交互式二维码登录。

        参数:
            force: 是否强制清状态后重新登录。

        返回:
            登录成功或已存在可用登录态时返回 `True`。
        """
        if force:
            self._clear_state()
        if self._token or self._load_state():
            return True

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=30),
            follow_redirects=True,
        )
        self._running = True
        try:
            return await self._qr_login()
        finally:
            self._running = False
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    async def start(self) -> None:
        """启动微信长轮询。

        参数:
            无。

        返回:
            无返回值。
        """
        self._running = True
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.poll_timeout + 10, connect=30),
            follow_redirects=True,
        )

        state_loaded = self._load_state()
        if getattr(self.config, "token", ""):
            self._token = str(self.config.token).strip()
        elif not state_loaded:
            logger.error(
                "Weixin channel has no authentication state. Run 'elebot channels login weixin' first."
            )
            self._running = False
            await self._client.aclose()
            self._client = None
            return

        logger.info("Weixin channel started.")
        while self._running:
            try:
                await self._poll_once()
            except httpx.TimeoutException:
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("Weixin poll failed: {}", exc)
                await asyncio.sleep(2)

    async def stop(self) -> None:
        """停止微信长轮询并保存状态。

        参数:
            无。

        返回:
            无返回值。
        """
        self._running = False
        self._stream_buffers.clear()
        self._stream_has_delta.clear()
        self._stream_sent_any.clear()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._save_state()

    @staticmethod
    def _stream_state_key(chat_id: str, metadata: dict[str, Any] | None = None) -> str:
        """返回当前流式轮次的状态键。"""
        meta = dict(metadata or {})
        session_id = str(meta.get("_session_id", "") or "").strip()
        message_id = str(meta.get("message_id", "") or "").strip()
        if session_id and message_id:
            return f"{session_id}:{message_id}"
        if message_id:
            return f"{chat_id}:{message_id}"
        return session_id or chat_id

    @staticmethod
    def _send_delay_seconds(text: str) -> float:
        """根据文本长度返回发送前延迟，模拟 IM 节奏。"""
        length = len(text.strip())
        if length <= 20:
            return random.uniform(0.2, 0.3)
        if length <= 40:
            return random.uniform(0.25, 0.4)
        return random.uniform(0.35, 0.5)

    async def _sleep_before_send(self, text: str) -> None:
        """发送前等待一小段时间，模拟真人输入节奏。"""
        await asyncio.sleep(self._send_delay_seconds(text))

    async def _send_text_message(self, chat_id: str, context_token: str, text: str) -> None:
        """发送一条微信文本消息。"""
        await self._sleep_before_send(text)
        data = await self._api_post(
            "ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": chat_id,
                    "client_id": f"elebot-{uuid.uuid4().hex[:12]}",
                    "message_type": MESSAGE_TYPE_BOT,
                    "message_state": MESSAGE_STATE_FINISH,
                    "context_token": context_token,
                    "item_list": [
                        {
                            "type": ITEM_TEXT,
                            "text_item": {"text": text},
                        }
                    ],
                }
            },
        )
        errcode = int(data.get("errcode", 0) or 0)
        if errcode != 0:
            raise RuntimeError(f"Weixin sendmessage failed: errcode={errcode} data={data}")

    def _clear_stream_state(self, state_key: str) -> None:
        """清理指定流式轮次的全部状态。"""
        self._stream_buffers.pop(state_key, None)
        self._stream_has_delta.pop(state_key, None)

    @staticmethod
    def _normalize_stream_segment(text: str) -> str:
        """规范化一条待发送的微信短消息。"""
        return text.strip()

    @staticmethod
    def _split_buffer_on_part_marker(buffer: str) -> tuple[str | None, str]:
        """按 `<part>` 分隔符切出下一条完整段落。"""
        if WEIXIN_STREAM_PART_MARKER not in buffer:
            return None, buffer
        segment, rest = buffer.split(WEIXIN_STREAM_PART_MARKER, 1)
        return segment, rest

    def _is_allowed(self, sender_id: str) -> bool:
        """判断发送者是否允许访问。

        参数:
            sender_id: 微信发送者标识。

        返回:
            允许访问时返回 `True`。
        """
        allow_from = list(getattr(self.config, "allow_from", []) or [])
        if not allow_from:
            return False
        if "*" in allow_from:
            return True
        return str(sender_id) in {str(item) for item in allow_from}

    async def _poll_once(self) -> None:
        """执行一次微信轮询请求。

        参数:
            无。

        返回:
            无返回值。
        """
        assert self._client is not None
        self._client.timeout = httpx.Timeout(self.config.poll_timeout + 10, connect=30)
        data = await self._api_post(
            "ilink/bot/getupdates",
            {"get_updates_buf": self._get_updates_buf},
        )
        ret = int(data.get("ret", 0) or 0)
        errcode = int(data.get("errcode", 0) or 0)
        if ret != 0 or errcode != 0:
            raise RuntimeError(f"Weixin getupdates failed: ret={ret} errcode={errcode} data={data}")

        new_cursor = str(data.get("get_updates_buf", "") or "")
        if new_cursor:
            self._get_updates_buf = new_cursor
            self._save_state()

        for message in data.get("msgs", []) or []:
            await self._process_message(message)

    async def _process_message(self, msg: dict[str, Any]) -> None:
        """把一条微信消息转成入站消息。

        参数:
            msg: 微信接口返回的原始消息对象。

        返回:
            无返回值。
        """
        if msg.get("message_type") == MESSAGE_TYPE_BOT:
            return

        raw_sender = str(msg.get("from_user_id", "") or "")
        if not raw_sender:
            return
        if not self._is_allowed(raw_sender):
            logger.warning("Weixin sender {} is not allowed.", raw_sender)
            return

        raw_message_id = str(msg.get("message_id", "") or msg.get("seq", "") or "")
        if not raw_message_id:
            raw_message_id = f"{raw_sender}:{msg.get('create_time_ms', '')}"
        if raw_message_id in self._processed_ids:
            return
        self._processed_ids[raw_message_id] = None
        while len(self._processed_ids) > 1000:
            self._processed_ids.popitem(last=False)

        context_token = str(msg.get("context_token", "") or "")
        if context_token:
            self._context_tokens[raw_sender] = context_token
            self._save_state()

        parts: list[str] = []
        media_paths: list[str] = []
        attachments: list[dict[str, Any]] = []
        for item in msg.get("item_list", []) or []:
            item_type = int(item.get("type", 0) or 0)
            if item_type == ITEM_TEXT:
                text = str((item.get("text_item") or {}).get("text", "") or "").strip()
                if text:
                    parts.append(text)
                continue
            if item_type == ITEM_IMAGE:
                file_path = await self._download_image_item(item.get("image_item") or {})
                if file_path:
                    media_paths.append(file_path)
                    parts.append(_WEIXIN_INBOUND_TEXT["image_ok"])
                else:
                    parts.append(_WEIXIN_INBOUND_TEXT["image_failed"])
                continue
            if item_type == ITEM_FILE:
                file_result = await self._download_file_item(item.get("file_item") or {})
                if file_result is not None:
                    media_paths.append(file_result["path"])
                    attachments.append(file_result)
                    parts.append(_WEIXIN_INBOUND_TEXT["file_ok"])
                else:
                    file_item = item.get("file_item") or {}
                    filename = str(
                        file_item.get("file_name", "")
                        or file_item.get("name", "")
                        or ""
                    ).strip()
                    if filename:
                        parts.append(f"用户发送了一个文件（{filename}），但当前未能下载文件内容。")
                    else:
                        parts.append(_WEIXIN_INBOUND_TEXT["file_failed"])
                continue
            if item_type == ITEM_VOICE:
                voice_item = item.get("voice_item") or {}
                voice_text = str(voice_item.get("text", "") or "").strip()
                if voice_text:
                    parts.append(voice_text)
                    continue

                file_path = await self._download_voice_item(voice_item)
                if file_path:
                    media_paths.append(file_path)
                    transcript = (await self.transcribe_audio(file_path)).strip()
                    if transcript:
                        parts.append(transcript)
                    else:
                        parts.append(_WEIXIN_INBOUND_TEXT["voice_transcribe_failed"])
                else:
                    parts.append(_WEIXIN_INBOUND_TEXT["voice_download_failed"])
                continue
            if item_type == ITEM_VIDEO:
                parts.append(_WEIXIN_INBOUND_TEXT["video"])
                continue

        content = "\n".join(parts).strip()
        if not content and media_paths:
            content = _WEIXIN_INBOUND_TEXT["media_only_fallback"]
        if not content:
            return

        session_id = default_session_id(self.name, raw_sender)
        await self.publish_input(
            client_id=raw_sender,
            chat_id=raw_sender,
            content=content,
            media=media_paths or None,
            metadata={
                "attachments": attachments,
                "message_id": raw_message_id,
                "context_token": context_token,
                "_session_id": session_id,
            },
        )

    async def _download_image_item(self, image_item: dict[str, Any]) -> str | None:
        """下载一张微信图片到本地媒体目录。

        参数:
            image_item: 微信原始图片项。

        返回:
            成功时返回本地文件路径；失败时返回 `None`。
        """
        media = image_item.get("media") or {}
        if not self._build_download_candidates(media):
            return None

        assert self._client is not None
        data = await self._download_media_bytes(media, kind="image")
        if not data:
            return None

        raw_aeskey_hex = str(image_item.get("aeskey", "") or "")
        media_aes_key_b64 = str(media.get("aes_key", "") or "")
        aes_key_b64 = ""
        if raw_aeskey_hex:
            try:
                aes_key_b64 = base64.b64encode(bytes.fromhex(raw_aeskey_hex)).decode()
            except Exception as exc:
                logger.warning("Invalid weixin image aeskey hex: {}", exc)
        elif media_aes_key_b64:
            aes_key_b64 = media_aes_key_b64

        if aes_key_b64:
            data = _decrypt_aes_ecb(data, aes_key_b64)

        mime = detect_image_mime(data)
        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(mime, ".bin")
        filename = f"weixin_image_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"
        file_path = get_media_dir("weixin") / filename
        file_path.write_bytes(data)
        return str(file_path)

    async def _download_voice_item(self, voice_item: dict[str, Any]) -> str | None:
        """下载一段微信语音到本地媒体目录。

        参数:
            voice_item: 微信原始语音项。

        返回:
            成功时返回本地文件路径；失败时返回 `None`。
        """
        media = voice_item.get("media") or {}
        if not self._build_download_candidates(media):
            return None

        media_aes_key_b64 = str(media.get("aes_key", "") or "")
        if not media_aes_key_b64:
            logger.warning("Weixin voice item missing aes_key; cannot decrypt voice payload.")
            return None

        assert self._client is not None
        data = await self._download_media_bytes(media, kind="voice")
        if not data:
            return None

        raw = _decrypt_aes_ecb(data, media_aes_key_b64)
        suffix = _detect_voice_suffix(raw)
        filename = f"weixin_voice_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"
        file_path = get_media_dir("weixin") / filename
        file_path.write_bytes(raw)
        return str(file_path)

    async def _download_file_item(self, file_item: dict[str, Any]) -> dict[str, Any] | None:
        """下载一个微信文件并返回附件元数据。"""
        media = file_item.get("media") or {}
        if not self._build_download_candidates(media):
            return None

        assert self._client is not None
        data = await self._download_media_bytes(media, kind="file")
        if not data:
            return None

        media_aes_key_b64 = str(media.get("aes_key", "") or "")
        if media_aes_key_b64:
            data = _decrypt_aes_ecb(data, media_aes_key_b64)

        raw_name = str(
            file_item.get("file_name", "")
            or file_item.get("name", "")
            or file_item.get("title", "")
            or ""
        ).strip()
        raw_mime = str(file_item.get("mime_type", "") or file_item.get("mime", "") or "").strip()
        mime = raw_mime or mimetypes.guess_type(raw_name)[0] or "application/octet-stream"
        suffix = Path(raw_name).suffix if raw_name else ""
        if not suffix:
            suffix = mimetypes.guess_extension(mime) or ".bin"
        if not suffix.startswith("."):
            suffix = f".{suffix}"

        filename = f"weixin_file_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"
        file_path = get_media_dir("weixin") / filename
        file_path.write_bytes(data)
        return {
            "kind": "file",
            "path": str(file_path),
            "filename": raw_name or filename,
            "mime": mime,
            "size": len(data),
        }

    async def send_message(self, message: OutboundMessage) -> None:
        """向微信发送最终消息。

        参数:
            message: 要发送的出站消息。

        返回:
            无返回值。
        """
        if self._client is None or not self._token:
            logger.warning("Weixin client is not authenticated; skip outbound message.")
            return

        context_token = self._context_tokens.get(message.chat_id, "")
        if not context_token:
            logger.warning("No weixin context token for {}; drop outbound message.", message.chat_id)
            return

        content = str(message.content or "").strip()
        if not content:
            return
        state_key = self._stream_state_key(message.chat_id, message.metadata)
        if state_key in self._completed_streams:
            self._completed_streams.discard(state_key)
            return
        if message.metadata.get("_cron_job_id"):
            for segment in self._iter_part_segments(content):
                await self._send_text_message(message.chat_id, context_token, segment)
                preview = segment[:80] + "..." if len(segment) > 80 else segment
                logger.info("Weixin cron message sent to {}: {}", message.chat_id, preview)
            self._clear_stream_state(state_key)
            return
        if not self._stream_has_delta.get(state_key):
            logger.warning("Weixin stream missing delta; no message sent to {}", message.chat_id)
            self._clear_stream_state(state_key)
            return
        self._clear_stream_state(state_key)

    def _iter_part_segments(self, content: str) -> list[str]:
        """把 `<part>` 协议正文拆成可发送的多个纯文本分段。"""
        parts = [self._normalize_stream_segment(item) for item in content.split(WEIXIN_STREAM_PART_MARKER)]
        return [item for item in parts if item]

    async def send_progress(
        self,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        *,
        tool_hint: bool = False,
    ) -> None:
        """微信第一版不透出进度事件。

        参数:
            chat_id: 目标聊天标识。
            content: 进度文本。
            metadata: 附加元数据。
            tool_hint: 是否为工具提示。

        返回:
            无返回值。
        """
        del chat_id, content, metadata, tool_hint

    async def send_delta(
        self,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """微信流式正文按 `<part>` 协议增量发送。

        参数:
            chat_id: 目标聊天标识。
            content: 正文增量。
            metadata: 附加元数据。

        返回:
            无返回值。
        """
        if self._client is None or not self._token:
            return

        meta = dict(metadata or {})
        state_key = self._stream_state_key(chat_id, meta)
        context_token = self._context_tokens.get(chat_id, "")
        if not context_token:
            logger.warning("No weixin context token for {}; drop stream delta.", chat_id)
            self._clear_stream_state(state_key)
            return

        if meta.get("_stream_end"):
            tail = self._normalize_stream_segment(self._stream_buffers.get(state_key, ""))
            if tail:
                await self._send_text_message(chat_id, context_token, tail)
                preview = tail[:80] + "..." if len(tail) > 80 else tail
                logger.info("Weixin stream tail sent to {}: {}", chat_id, preview)
            if self._stream_has_delta.get(state_key):
                self._completed_streams.add(state_key)
            self._clear_stream_state(state_key)
            return

        if not meta.get("_stream_delta"):
            return
        if not self._stream_has_delta.get(state_key):
            logger.info("Weixin stream started for {}", chat_id)
        self._stream_has_delta[state_key] = True

        buffer = self._stream_buffers.get(state_key, "") + str(content or "")
        while True:
            segment, rest = self._split_buffer_on_part_marker(buffer)
            if segment is not None:
                normalized = self._normalize_stream_segment(segment)
                buffer = rest
                if not normalized:
                    continue
                await self._send_text_message(chat_id, context_token, normalized)
                preview = normalized[:80] + "..." if len(normalized) > 80 else normalized
                logger.info("Weixin stream chunk sent to {}: {}", chat_id, preview)
                continue

            break

        self._stream_buffers[state_key] = buffer
