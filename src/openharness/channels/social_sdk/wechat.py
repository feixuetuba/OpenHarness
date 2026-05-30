"""WeChat SDK adapter for OpenHarness."""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import time
from typing import Any

import httpx

from openharness.channels.social_sdk.base import (
    BaseSocialSDK,
    SDKRegistry,
    TestResult,
    WechatConfig,
)

logger = logging.getLogger(__name__)

WECHAT_API_URL = "https://api.weixin.qq.com"


class WechatSDK(BaseSocialSDK):
    """WeChat platform SDK adapter using WeChat Official API."""

    platform_name = "wechat"

    def __init__(self, config: WechatConfig):
        super().__init__(config)
        self.config: WechatConfig = config
        self._access_token: str | None = None
        self._token_expires_at: float = 0

    def is_sdk_available(self) -> bool:
        return True

    def validate_config(self) -> list[str]:
        errors = []
        if not self.config.app_id:
            errors.append("App ID is required")
        if not self.config.app_secret:
            errors.append("App Secret is required")
        return errors

    async def test_connection(self) -> TestResult:
        config_errors = self.validate_config()
        if config_errors:
            return TestResult(
                success=False,
                message="Configuration validation failed",
                error="; ".join(config_errors),
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{WECHAT_API_URL}/cgi-bin/token"
                params = {
                    "grant_type": "client_credential",
                    "appid": self.config.app_id,
                    "secret": self.config.app_secret,
                }
                response = await client.get(url, params=params)
                data = response.json()

                if "access_token" in data:
                    self._access_token = data["access_token"]
                    self._token_expires_at = time.time() + data.get("expires_in", 7200) - 300
                    return TestResult(
                        success=True,
                        message="Successfully connected to WeChat API",
                        details={
                            "app_id": self.config.app_id,
                            "expires_in": data.get("expires_in", 7200),
                        },
                    )
                else:
                    errcode = data.get("errcode", "unknown")
                    errmsg = data.get("errmsg", "Unknown error")
                    return TestResult(
                        success=False,
                        message=f"WeChat API returned error: {errcode}",
                        error=errmsg,
                        details={"errcode": errcode},
                    )
        except httpx.TimeoutException:
            return TestResult(
                success=False,
                message="Connection to WeChat API timed out",
                error="Request timeout after 10 seconds",
            )
        except httpx.RequestError as e:
            return TestResult(
                success=False,
                message="Failed to connect to WeChat API",
                error=str(e),
            )
        except Exception as e:
            return TestResult(
                success=False,
                message="Unexpected error during connection test",
                error=str(e),
            )

    async def get_access_token(self) -> str | None:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        result = await self.test_connection()
        if result.success:
            return self._access_token
        return None

    def verify_signature(self, timestamp: str, nonce: str, signature: str, echo_str: str = "") -> bool:
        token = self.config.token
        if not token:
            return False

        tmp_list = [token, timestamp, nonce]
        tmp_list.sort()
        tmp_str = "".join(tmp_list)
        tmp_str = hashlib.sha1(tmp_str.encode("utf-8")).hexdigest()

        return tmp_str == signature

    def create_client(self) -> Any:
        return WechatClient(self.config)


class WechatClient:
    """Simple WeChat API client wrapper."""

    def __init__(self, config: WechatConfig):
        self.config = config
        self._access_token: str | None = None
        self._token_expires_at: float = 0

    async def get_access_token(self) -> str | None:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{WECHAT_API_URL}/cgi-bin/token"
            params = {
                "grant_type": "client_credential",
                "appid": self.config.app_id,
                "secret": self.config.app_secret,
            }
            response = await client.get(url, params=params)
            data = response.json()

            if "access_token" in data:
                self._access_token = data["access_token"]
                self._token_expires_at = time.time() + data.get("expires_in", 7200) - 300
                return self._access_token
        return None

    async def send_text_message(self, openid: str, content: str) -> bool:
        token = await self.get_access_token()
        if not token:
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{WECHAT_API_URL}/cgi-bin/message/custom/send"
            params = {"access_token": token}
            data = {
                "touser": openid,
                "msgtype": "text",
                "text": {"content": content},
            }
            response = await client.post(url, params=params, json=data)
            result = response.json()
            return result.get("errcode") == 0


SDKRegistry.register(WechatSDK.platform_name, WechatSDK)
