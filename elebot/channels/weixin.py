"""个人微信 HTTP 长轮询 channel。"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from elebot.bus.events import OutboundMessage
from elebot.channels.base import BaseChannel
from elebot.config.paths import get_runtime_subdir
from elebot.runtime.protocol import default_session_id
from elebot.utils.text import split_message

ITEM_TEXT = 1
MESSAGE_TYPE_BOT = 2
WEIXIN_MAX_MESSAGE_LEN = 4000
WEIXIN_CHANNEL_VERSION = "2.1.1"
ILINK_APP_ID = "bot"


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

    @property
    def supports_streaming(self) -> bool:
        """个人微信第一版不启用正文流式输出。"""
        return False

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
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._save_state()

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
        for item in msg.get("item_list", []) or []:
            if item.get("type") != ITEM_TEXT:
                continue
            text = str((item.get("text_item") or {}).get("text", "") or "").strip()
            if text:
                parts.append(text)
        content = "\n".join(parts).strip()
        if not content:
            return

        session_id = default_session_id(self.name, raw_sender)
        await self.publish_input(
            client_id=raw_sender,
            chat_id=raw_sender,
            content=content,
            metadata={
                "message_id": raw_message_id,
                "context_token": context_token,
                "_session_id": session_id,
            },
        )

    async def send_message(self, message: OutboundMessage) -> None:
        """向微信发送最终文本消息。

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

        for chunk in split_message(content, WEIXIN_MAX_MESSAGE_LEN):
            data = await self._api_post(
                "ilink/bot/sendmessage",
                {
                    "msg": {
                        "from_user_id": "",
                        "to_user_id": message.chat_id,
                        "client_id": f"elebot-{uuid.uuid4().hex[:12]}",
                        "message_type": MESSAGE_TYPE_BOT,
                        "message_state": 2,
                        "context_token": context_token,
                        "item_list": [
                            {
                                "type": ITEM_TEXT,
                                "text_item": {"text": chunk},
                            }
                        ],
                    }
                },
            )
            errcode = int(data.get("errcode", 0) or 0)
            if errcode != 0:
                raise RuntimeError(f"Weixin sendmessage failed: errcode={errcode} data={data}")

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
        """微信第一版不透出流式正文增量。

        参数:
            chat_id: 目标聊天标识。
            content: 正文增量。
            metadata: 附加元数据。

        返回:
            无返回值。
        """
        del chat_id, content, metadata
