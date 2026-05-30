"""WeChat Official Account channel for web_config callbacks."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from openharness.channels.bus.events import OutboundMessage
from openharness.channels.impl.base import BaseChannel, resolve_channel_media_dir
from openharness.channels.bus.queue import MessageBus
from openharness.config.schema import WechatConfig
from openharness.utils.helpers import safe_filename

logger = logging.getLogger(__name__)

WECHAT_API_URL = "https://api.weixin.qq.com"


class WeChatChannel(BaseChannel):
    """Receive WeChat webhook XML and send replies via customer service API."""

    name = "wechat"

    def __init__(self, config: WechatConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WechatConfig = config
        self._http: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    async def start(self) -> None:
        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        logger.info("WeChat channel ready for web callbacks")

    async def stop(self) -> None:
        self._running = False
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        token = await self._get_access_token()
        if not token or self._http is None:
            logger.warning("WeChat access token unavailable; cannot send reply")
            return
        for media_path in msg.media or []:
            ok = await self._send_media(msg.chat_id, media_path, msg, token)
            if not ok:
                await self._send_text(token, msg.chat_id, f"[文件发送失败: {Path(media_path).name}]")
        if not msg.content.strip():
            return
        await self._send_text(token, msg.chat_id, msg.content)

    async def _send_text(self, token: str, openid: str, content: str) -> bool:
        url = f"{self._api_base()}/cgi-bin/message/custom/send"
        response = await self._http.post(
            url,
            params={"access_token": token},
            json={
                "touser": openid,
                "msgtype": "text",
                "text": {"content": content},
            },
        )
        return self._is_wechat_ok(response, "send text")

    async def _send_media(self, openid: str, media_path: str, msg: OutboundMessage, token: str) -> bool:
        path = Path(media_path).expanduser()
        if not path.is_file():
            logger.warning("WeChat media file not found: %s", media_path)
            return False
        media_type = self._wechat_media_type(path, msg)
        media_id = await self._upload_temp_media(token, path, media_type)
        if not media_id:
            return False
        payload: dict[str, Any] = {"touser": openid, "msgtype": media_type}
        if media_type == "video":
            payload["video"] = {
                "media_id": media_id,
                "thumb_media_id": media_id,
                "title": path.name,
                "description": "",
            }
        else:
            payload[media_type] = {"media_id": media_id}
        response = await self._http.post(
            f"{self._api_base()}/cgi-bin/message/custom/send",
            params={"access_token": token},
            json=payload,
        )
        return self._is_wechat_ok(response, f"send {media_type}")

    async def _upload_temp_media(self, token: str, path: Path, media_type: str) -> str | None:
        if self._http is None:
            return None
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        try:
            with path.open("rb") as handle:
                response = await self._http.post(
                    f"{self._api_base()}/cgi-bin/media/upload",
                    params={"access_token": token, "type": media_type},
                    files={"media": (path.name, handle, mime)},
                )
            try:
                data = response.json()
            except Exception:
                data = {}
            media_id = data.get("media_id")
            if not media_id:
                logger.warning("WeChat media upload failed: %s", data or response.text[:200])
                return None
            return str(media_id)
        except Exception as exc:
            logger.warning("WeChat media upload failed: %s", exc)
            return None

    @staticmethod
    def _is_wechat_ok(response: httpx.Response, action: str) -> bool:
        try:
            data = response.json()
        except Exception:
            data = {}
        if data.get("errcode", 0) not in (0, "0"):
            logger.warning("WeChat %s failed: %s", action, data or response.text[:200])
            return False
        return True

    @staticmethod
    def _wechat_media_type(path: Path, msg: OutboundMessage) -> str:
        modes = msg.metadata.get("_media_modes") if isinstance(msg.metadata, dict) else None
        raw = str(modes.get(str(path)) or modes.get(path.as_posix()) or "") if isinstance(modes, dict) else ""
        if raw == "voice":
            return "voice"
        if raw == "image":
            return "image"
        if raw == "video":
            return "video"
        if raw == "file":
            return "file"
        mime, _ = mimetypes.guess_type(str(path))
        if mime and mime.startswith("image/"):
            return "image"
        if mime and mime.startswith("audio/"):
            return "voice"
        if mime and mime.startswith("video/"):
            return "video"
        return "file"

    def verify_signature(self, signature: str, timestamp: str, nonce: str) -> bool:
        if not self.config.token:
            return False
        pieces = [self.config.token, timestamp, nonce]
        pieces.sort()
        digest = hashlib.sha1("".join(pieces).encode("utf-8")).hexdigest()
        return digest == signature

    async def handle_callback_xml(self, body: bytes, query: dict[str, str]) -> str:
        if query.get("encrypt_type"):
            logger.warning("Encrypted WeChat callbacks are not supported yet; use plaintext or compatibility mode")
            return "success"
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            logger.warning("Invalid WeChat callback XML")
            return "success"

        payload = {child.tag: child.text or "" for child in root}
        from_user = payload.get("FromUserName", "").strip()
        to_user = payload.get("ToUserName", "").strip()
        msg_type = payload.get("MsgType", "").strip().lower()
        message_id = payload.get("MsgId", "").strip()
        if not from_user:
            return "success"

        content, media_paths = await self._extract_content_and_media(payload, msg_type, message_id)
        if not content and not media_paths:
            return "success"

        await self._handle_message(
            sender_id=from_user,
            chat_id=from_user,
            content=content or "[empty message]",
            media=media_paths,
            metadata={
                "message_id": message_id,
                "msg_type": msg_type,
                "wechat_to_user": to_user,
            },
        )
        return "success"

    async def _extract_content_and_media(
        self,
        payload: dict[str, str],
        msg_type: str,
        message_id: str,
    ) -> tuple[str, list[str]]:
        if msg_type == "text":
            return payload.get("Content", "").strip(), []
        if msg_type in {"image", "voice", "video", "shortvideo", "file"}:
            media_id = payload.get("MediaId", "").strip()
            file_path = await self._download_media(media_id, msg_type, message_id)
            label = f"[{msg_type}: {Path(file_path).name}]" if file_path else f"[{msg_type}: download failed]"
            return label, [file_path] if file_path else []
        if msg_type == "link":
            title = payload.get("Title", "").strip()
            description = payload.get("Description", "").strip()
            url = payload.get("Url", "").strip()
            return "\n".join(part for part in (title, description, url) if part), []
        if msg_type == "location":
            return (
                f"[location] {payload.get('Label', '')} "
                f"({payload.get('Location_X', '')}, {payload.get('Location_Y', '')})"
            ).strip(), []
        return f"[{msg_type}]", []

    async def _download_media(self, media_id: str, msg_type: str, message_id: str) -> str | None:
        if not media_id or self._http is None:
            return None
        token = await self._get_access_token()
        if not token:
            return None
        try:
            response = await self._http.get(
                f"{self._api_base()}/cgi-bin/media/get",
                params={"access_token": token, "media_id": media_id},
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                logger.warning("WeChat media download failed: %s", response.text[:200])
                return None
            filename = self._filename_from_response(response, msg_type, media_id, message_id)
            media_dir = resolve_channel_media_dir(self.name)
            root = media_dir.resolve()
            target = (root / filename).resolve()
            if not target.is_relative_to(root):
                return None
            target.write_bytes(response.content)
            return str(target)
        except Exception as exc:
            logger.warning("WeChat media download failed: %s", exc)
            return None

    async def _get_access_token(self) -> str | None:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        if not self.config.app_id or not self.config.app_secret or self._http is None:
            return None
        try:
            response = await self._http.get(
                f"{self._api_base()}/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.config.app_id,
                    "secret": self.config.app_secret,
                },
            )
            data = response.json()
            token = data.get("access_token")
            if not token:
                logger.warning("WeChat token request failed: %s", data)
                return None
            self._access_token = str(token)
            self._token_expires_at = time.time() + int(data.get("expires_in", 7200)) - 300
            return self._access_token
        except Exception as exc:
            logger.warning("WeChat token request failed: %s", exc)
            return None

    def _api_base(self) -> str:
        return (self.config.api_url or WECHAT_API_URL).strip().rstrip("/")

    @staticmethod
    def _filename_from_response(
        response: httpx.Response,
        msg_type: str,
        media_id: str,
        message_id: str,
    ) -> str:
        disposition = response.headers.get("content-disposition", "")
        filename = ""
        if "filename=" in disposition:
            filename = disposition.rsplit("filename=", 1)[-1].strip().strip('"')
        if not filename:
            ext = {
                "image": ".jpg",
                "voice": ".amr",
                "video": ".mp4",
                "shortvideo": ".mp4",
                "file": "",
            }.get(msg_type, "")
            filename = f"{message_id or media_id[:16] or 'wechat-media'}{ext}"
        return safe_filename(filename) or "wechat-media"
