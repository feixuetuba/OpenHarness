"""QQ channel implementation using botpy SDK."""

import asyncio
import base64
import json
import logging
import mimetypes
import os
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode, unquote, urlparse

import httpx

from openharness.channels.bus.events import OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.base import BaseChannel, allocate_social_file, resolve_channel_media_dir
from openharness.config.paths import get_data_dir
from openharness.config.schema import QQConfig
from openharness.utils.helpers import safe_filename

logger = logging.getLogger(__name__)

try:
    import botpy
    from botpy.message import C2CMessage

    QQ_AVAILABLE = True
    QQ_IMPORT_ERROR: Exception | None = None
except ImportError as exc:
    QQ_AVAILABLE = False
    QQ_IMPORT_ERROR = exc
    botpy = None
    C2CMessage = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage


def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            # Disable botpy's file log — not using loguru; default "botpy.log" fails on read-only fs
            super().__init__(
                intents=intents,
                ext_handlers=False,
                is_sandbox=bool(getattr(channel.config, "sandbox", False)),
            )

        async def on_ready(self):
            channel.online = True
            channel.last_error = None
            logger.info("QQ bot ready: %s", self.robot.name)

        async def on_c2c_message_create(self, message: "C2CMessage"):
            logger.info("QQ c2c message event received: id=%s", getattr(message, "id", None))
            await channel._on_message(message)

        async def on_direct_message_create(self, message):
            logger.info("QQ direct message event received: id=%s", getattr(message, "id", None))
            await channel._on_message(message)

    return _Bot


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._msg_seq: int = 1  # 消息序列号，避免被 QQ API 去重
        self._http: httpx.AsyncClient | None = None
        self.online: bool = False
        self.last_error: str | None = None

    async def start(self) -> None:
        """Start the QQ bot."""
        if not QQ_AVAILABLE:
            self.last_error = f"QQ SDK import failed: {QQ_IMPORT_ERROR}"
            logger.error(
                "QQ SDK not installed or failed to import. Run: pip install qq-botpy. error=%s",
                QQ_IMPORT_ERROR,
            )
            return

        if not self.config.app_id or not self.config.app_secret:
            self.last_error = "QQ app_id and secret not configured"
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        BotClass = _make_bot_class(self)
        self._client = BotClass()

        logger.info("QQ bot started (C2C private message)")
        await self._run_bot()

    async def _run_bot(self) -> None:
        """Run the bot connection with auto-reconnect."""
        while self._running:
            try:
                self.online = False
                logger.info(
                    "QQ bot connecting: app_id=%s, sandbox=%s",
                    self.config.app_id,
                    getattr(self.config, "sandbox", False),
                )
                await self._client.start(appid=self.config.app_id, secret=self.config.app_secret)
            except AttributeError as e:
                self.online = False
                self.last_error = str(e)
                logger.error(
                    "QQ bot login failed: API returned invalid robot info. "
                    "Please check app_id and app_secret configuration. Error: %s",
                    e,
                    exc_info=True,
                )
                # 如果是认证失败，不要频繁重试
                if self._running:
                    logger.info("Waiting 30 seconds before reconnecting QQ bot...")
                    await asyncio.sleep(30)
            except Exception as e:
                self.online = False
                self.last_error = str(e)
                logger.warning("QQ bot error: %s", e, exc_info=True)
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the QQ bot."""
        self._running = False
        self.online = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        if self._http:
            try:
                await self._http.aclose()
            except Exception:
                pass
            self._http = None
        logger.info("QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return
        try:
            msg_id = msg.metadata.get("message_id")
            if msg.content and msg.content.strip():
                await self._send_text(msg.chat_id, msg.content, msg_id)
            for media_path in msg.media or []:
                ok, reason = await self._send_media(msg.chat_id, media_path, msg)
                if not ok:
                    suffix = f"：{reason}" if reason else ""
                    await self._send_text(
                        msg.chat_id,
                        f"[文件发送失败: {Path(media_path).name}]{suffix}",
                        msg_id,
                    )
        except Exception as e:
            logger.error("Error sending QQ message: %s", e)

    async def _send_text(self, openid: str, content: str, msg_id: str | None = None) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            self._msg_seq += 1
            try:
                self._debug_send_event(
                    "text_send_start",
                    openid=openid,
                    attempt=attempt,
                    msg_seq=self._msg_seq,
                    content_length=len(content),
                )
                await self._client.api.post_c2c_message(
                    openid=openid,
                    msg_type=0,
                    content=content,
                    msg_id=msg_id,
                    msg_seq=self._msg_seq,
                )
                self._debug_send_event(
                    "text_send_done",
                    openid=openid,
                    attempt=attempt,
                    msg_seq=self._msg_seq,
                    content_length=len(content),
                )
                return
            except Exception as exc:
                last_exc = exc
                detail = str(exc) or exc.__class__.__name__
                logger.warning("QQ text send failed attempt=%s openid=%s error=%s", attempt, openid, detail)
                self._debug_send_event(
                    "text_send_failed",
                    openid=openid,
                    attempt=attempt,
                    msg_seq=self._msg_seq,
                    content_length=len(content),
                    error=detail,
                )
                if attempt < 3:
                    await asyncio.sleep(1.5 * attempt)
        if last_exc is not None:
            raise last_exc

    async def _send_media(self, openid: str, media_path: str, msg: OutboundMessage) -> tuple[bool, str]:
        api = getattr(self._client, "api", None)
        path = Path(media_path).expanduser()
        if not api or not path.is_file():
            logger.warning("QQ media file not found: %s", media_path)
            self._debug_media_event("file_not_found", media_path=media_path)
            return False, "本地文件不存在"

        file_size = path.stat().st_size
        if file_size == 0:
            logger.warning("QQ media file is empty: %s", media_path)
            self._debug_media_event("file_empty", media_path=media_path)
            return False, "文件内容为空"

        is_group = self._is_group_chat(msg)
        mode = self._media_mode(media_path, msg)
        kind = self._media_kind(media_path, msg)
        file_type = self._qq_file_type(path, mode, kind)
        
        if is_group and file_type == 4:
            reason = "QQ 群聊暂不开放文件类型发送，请改用单聊或发送图片/视频/语音"
            logger.warning("%s: %s", reason, media_path)
            self._debug_media_event(
                "blocked_group_file",
                media_path=str(path),
                kind=kind,
                file_type=file_type,
            )
            return False, reason
        
        use_base64 = not is_group
        
        try:
            self._debug_media_event(
                "send_start",
                openid=openid,
                media_path=str(path),
                mode=mode,
                kind=kind,
                file_type=file_type,
                file_name=path.name,
                file_size=file_size,
                is_group=is_group,
                use_base64=use_base64,
            )

            await self._upload_and_send_media(
                api=api,
                openid=openid,
                path=path,
                file_type=file_type,
                use_base64=use_base64,
                msg=msg,
            )
            self._debug_media_event("send_done", media_path=str(path))
            return True, ""
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            if file_type == 4:
                detail = f"{detail}；QQ C2C 普通文件(file_type=4)接口可能未开放"
            if not is_group and file_type == 4 and kind == "audio":
                await self._send_text(
                    openid,
                    f"音频文件按普通文件发送失败：{detail}\n正在尝试改用音频/语音方式发送。",
                    msg.metadata.get("message_id"),
                )
                try:
                    fallback_file_type = 3
                    self._debug_media_event(
                        "fallback_audio_send_start",
                        media_path=str(path),
                        original_file_type=file_type,
                        fallback_file_type=fallback_file_type,
                        reason=detail,
                    )
                    await self._upload_and_send_media(
                        api=api,
                        openid=openid,
                        path=path,
                        file_type=fallback_file_type,
                        use_base64=use_base64,
                        msg=msg,
                    )
                    self._debug_media_event(
                        "fallback_audio_send_done",
                        media_path=str(path),
                        fallback_file_type=fallback_file_type,
                    )
                    return True, ""
                except Exception as fallback_exc:
                    fallback_detail = str(fallback_exc) or fallback_exc.__class__.__name__
                    detail = f"{detail}；改用音频/语音发送也失败：{fallback_detail}"
            logger.warning("QQ media send failed: %s", detail)
            self._debug_media_event(
                "send_failed",
                media_path=str(path),
                mode=mode,
                kind=kind,
                file_type=file_type,
                file_name=path.name,
                file_size=file_size,
                is_group=is_group,
                use_base64=use_base64,
                error=detail,
            )
            return False, detail

    async def _upload_and_send_media(
        self,
        *,
        api,
        openid: str,
        path: Path,
        file_type: int,
        use_base64: bool,
        msg: OutboundMessage,
    ) -> None:
        if use_base64:
            file_data = base64.b64encode(path.read_bytes()).decode("ascii")
            media = await self._upload_base64_file(api, openid, file_type, file_data, path.name)
        else:
            url = self._public_media_url(path)
            if not url:
                reason = "QQ 群聊文件接口需要公网可访问的下载 URL，请配置 OPENHARNESS_SOCIAL_FILE_BASE_URL"
                logger.warning("%s: %s", reason, path)
                self._debug_media_event("missing_public_url", media_path=str(path))
                raise RuntimeError(reason)
            media = await api.post_c2c_file(
                openid=openid,
                file_type=file_type,
                url=url,
                srv_send_msg=False,
            )

        self._debug_media_event("upload_done", file_type=file_type, media=self._jsonable(media))
        self._msg_seq += 1
        await api.post_c2c_message(
            openid=openid,
            msg_type=7,
            media=media,
            msg_id=msg.metadata.get("message_id"),
            msg_seq=self._msg_seq,
        )

    async def _upload_base64_file(self, api, openid: str, file_type: int, file_data: str, file_name: str) -> dict:
        http_client = getattr(api, "_http", None)
        if not http_client:
            raise RuntimeError("BotAPI HTTP client not available")
        
        payload = {
            "file_type": file_type,
            "file_data": file_data,
            "file_name": file_name,
            "srv_send_msg": False,
        }
        
        from botpy.http import Route
        route = Route("POST", "/v2/users/{openid}/files", openid=openid)
        
        logger.info(
            "Uploading file via base64: file_type=%s file_name=%s data_size=%d",
            file_type,
            file_name,
            len(file_data),
        )
        return await http_client.request(route, json=payload)

    async def _on_message(self, data: "C2CMessage") -> None:
        """Handle incoming message from QQ."""
        try:
            logger.info("QQChannel._on_message called: id=%s", getattr(data, "id", None))
            # Dedup by message ID
            if data.id in self._processed_ids:
                logger.info("QQChannel ignored duplicate message: id=%s", data.id)
                return
            self._processed_ids.append(data.id)

            author = data.author
            user_id = str(getattr(author, "id", None) or getattr(author, "user_openid", "unknown"))
            user_name = (
                getattr(author, "username", None)
                or getattr(author, "nick", None)
                or f"QQ用户 {user_id[:8]}"
            )
            content = (data.content or "").strip()
            media_paths, media_labels = await self._extract_inbound_media(data)
            if media_labels:
                content = "\n".join([p for p in [content, *media_labels] if p])
            if not content and not media_paths:
                logger.info("QQChannel ignored empty message: id=%s sender=%s", data.id, user_id)
                return

            logger.info(
                "QQChannel forwarding message: id=%s sender=%s content=%s",
                data.id,
                user_id,
                content[:100],
            )

            await self._handle_message(
                sender_id=user_id,
                chat_id=user_id,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": data.id,
                    "sender_name": user_name,
                    "reply_to": self._extract_reply_to(data),
                    "msg_type": self._guess_message_type(data, media_paths),
                },
            )
        except Exception:
            logger.exception("Error handling QQ message")

    async def _extract_inbound_media(self, data: "C2CMessage") -> tuple[list[str], list[str]]:
        media_paths: list[str] = []
        labels: list[str] = []
        for idx, item in enumerate(self._iter_media_items(data), start=1):
            url = self._first_attr(item, "url", "download_url", "file_url", "image_url", "src")
            name = (
                self._first_attr(item, "filename", "file_name", "name")
                or self._filename_from_url(url)
                or f"qq-attachment-{idx}"
            )
            if not url:
                labels.append(f"[attachment: {name} - download url missing]")
                continue
            path = await self._download_media(url, name, idx)
            if path:
                media_paths.append(path)
                labels.append(f"[attachment: {path}]")
            else:
                labels.append(f"[attachment: {name} - download failed]")
        return media_paths, labels

    def _iter_media_items(self, data: "C2CMessage") -> list[object]:
        items: list[object] = []
        for field in ("attachments", "attachment", "files", "file", "images", "image"):
            value = getattr(data, field, None)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                items.extend(value)
            else:
                items.append(value)
        return items

    async def _download_media(self, url: str, filename: str, idx: int) -> str | None:
        if not self._http:
            return None
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            safe_name = safe_filename(filename) or f"qq-attachment-{idx}"
            media_root = resolve_channel_media_dir(self.name).resolve()
            target = allocate_social_file(self.name, safe_name, default_ext=".bin").resolve()
            if not target.is_relative_to(media_root):
                return None
            target.write_bytes(response.content)
            return str(target)
        except Exception as exc:
            logger.warning("QQ attachment download failed: %s", exc)
            return None

    @staticmethod
    def _first_attr(item: object, *names: str) -> str:
        if isinstance(item, dict):
            for name in names:
                value = item.get(name)
                if value:
                    return str(value)
            return ""
        for name in names:
            value = getattr(item, name, None)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _filename_from_url(url: str | None) -> str:
        if not url:
            return ""
        parsed = urlparse(url)
        name = Path(unquote(parsed.path)).name
        return name or ""

    @staticmethod
    def _extract_reply_to(data: "C2CMessage") -> str | None:
        for field in ("reply_to", "reply_to_message_id", "source_msg_id", "referenced_message_id"):
            value = getattr(data, field, None)
            if value:
                return str(value)
        return None

    @staticmethod
    def _guess_message_type(data: "C2CMessage", media_paths: list[str]) -> str:
        value = getattr(data, "msg_type", None) or getattr(data, "message_type", None)
        if value:
            return str(value)
        return "media" if media_paths else "text"

    @staticmethod
    def _media_mode(media_path: str, msg: OutboundMessage) -> str:
        modes = msg.metadata.get("_media_modes") if isinstance(msg.metadata, dict) else None
        if isinstance(modes, dict) and media_path in modes:
            return str(modes[media_path])
        mime, _ = mimetypes.guess_type(media_path)
        if mime and mime.startswith("image/"):
            return "image"
        if mime and mime.startswith("audio/"):
            return "audio"
        if mime and mime.startswith("video/"):
            return "video"
        return "file"

    @staticmethod
    def _media_kind(media_path: str, msg: OutboundMessage) -> str:
        """获取媒体类型：image/video/audio/document。优先从 _media_kinds 读取，否则根据扩展名推断。"""
        kinds = msg.metadata.get("_media_kinds") if isinstance(msg.metadata, dict) else None
        if isinstance(kinds, dict) and media_path in kinds:
            return str(kinds[media_path])
        
        mime, _ = mimetypes.guess_type(media_path)
        suffix = Path(media_path).suffix.lower()
        
        if mime and mime.startswith("image/") or suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            return "image"
        if mime and mime.startswith("video/") or suffix in {".mp4", ".mov", ".avi"}:
            return "video"
        if mime and mime.startswith("audio/") or suffix in {".mp3", ".ogg", ".wav", ".flac", ".aac", ".m4a", ".opus", ".amr", ".silk"}:
            return "audio"
        return "document"

    @staticmethod
    def _is_group_chat(msg: OutboundMessage) -> bool:
        """判断是否是群聊。从 metadata 中读取 is_group 或 chat_type。"""
        if not isinstance(msg.metadata, dict):
            return False
        if msg.metadata.get("is_group") is True:
            return True
        chat_type = str(msg.metadata.get("chat_type") or "").lower()
        return chat_type == "group"

    @staticmethod
    def _qq_msg_type_for_media(path: Path, mode: str) -> int:
        if mode == "image" or path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            return 7
        return 0

    @staticmethod
    def _qq_file_type(path: Path, mode: str, kind: str = None) -> int:
        """根据发送意图优先决定 file_type，再按媒体类型兜底。
        
        mode=file/document → file_type=4 (普通文件)
        mode=voice/audio → file_type=3 (语音)
        mode=video → file_type=2 (视频)
        mode=image → file_type=1 (图片)
        kind=document → file_type=4 (普通文件)
        kind=audio → file_type=3 (语音)
        kind=video → file_type=2 (视频)
        kind=image → file_type=1 (图片)
        """
        if mode in {"file", "document", "attachment"}:
            return 4
        if mode in {"voice", "audio"}:
            return 3
        if mode == "video":
            return 2
        if mode == "image":
            return 1

        if kind == "document":
            return 4
        if kind == "audio":
            return 3
        if kind == "video":
            return 2
        if kind == "image":
            return 1
        
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png"}:
            return 1
        if suffix == ".mp4":
            return 2
        if suffix in {".silk", ".slk", ".mp3", ".ogg", ".wav", ".amr", ".flac", ".aac", ".m4a", ".opus"}:
            return 3
        return 4

    def _public_media_url(self, path: Path) -> str:
        base_url = (
            os.environ.get("OPENHARNESS_SOCIAL_FILE_BASE_URL")
            or str(getattr(self.config, "public_file_base_url", "") or "")
            or str(getattr(self.config, "file_base_url", "") or "")
        ).strip().rstrip("/")
        if not base_url:
            return ""
        encoded = base64.urlsafe_b64encode(str(path.resolve()).encode("utf-8")).decode("ascii").rstrip("=")
        url = f"{base_url}/api/social/files/{encoded}"
        token = (
            os.environ.get("OPENHARNESS_SOCIAL_FILE_TOKEN")
            or str(getattr(self.config, "public_file_token", "") or "")
        ).strip()
        if token:
            url = f"{url}?{urlencode({'token': token})}"
        return url

    @staticmethod
    def _jsonable(value):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(k): QQChannel._jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [QQChannel._jsonable(v) for v in value]
        if hasattr(value, "__dict__"):
            return QQChannel._jsonable(vars(value))
        return repr(value)

    @staticmethod
    def _debug_media_event(event: str, **payload) -> None:
        try:
            log_path = get_data_dir() / "qq_media_debug.log"
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "event": event,
                **payload,
            }
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.debug("Failed to write QQ media debug log", exc_info=True)

    @staticmethod
    def _debug_send_event(event: str, **payload) -> None:
        try:
            log_path = get_data_dir() / "qq_send_debug.log"
            record = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "event": event,
                **payload,
            }
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.debug("Failed to write QQ send debug log", exc_info=True)
