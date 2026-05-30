"""QQ platform SDK adapter for OpenHarness."""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

import httpx

from openharness.channels.social_sdk.base import (
    BaseSocialSDK,
    QQConfig,
    SDKRegistry,
    TestResult,
)

logger = logging.getLogger(__name__)

QQ_TOKEN_API_URL = "https://bots.qq.com"
QQ_MESSAGE_API_URL = "https://api.sgroup.qq.com"


class QQSDK(BaseSocialSDK):
    """QQ platform SDK adapter using QQ Open Platform API."""

    platform_name = "qq"

    def __init__(self, config: QQConfig):
        super().__init__(config)
        self.config: QQConfig = config

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
                url = f"{self.config.get_api_url(QQ_TOKEN_API_URL).rstrip('/')}/app/getAppAccessToken"
                data = {
                    "appId": self.config.app_id,
                    "clientSecret": self.config.app_secret,
                }
                response = await client.post(url, json=data)
                result = response.json()

                if "access_token" in result:
                    return TestResult(
                        success=True,
                        message="Successfully connected to QQ Open Platform API",
                        details={
                            "app_id": self.config.app_id,
                            "expires_in": result.get("expires_in", 7200),
                        },
                    )
                else:
                    errcode = result.get("ret", result.get("errcode", "unknown"))
                    errmsg = result.get("msg", result.get("errmsg", "Unknown error"))
                    return TestResult(
                        success=False,
                        message=f"QQ API returned error: {errcode}",
                        error=errmsg,
                        details={"errcode": errcode},
                    )
        except httpx.TimeoutException:
            return TestResult(
                success=False,
                message="Connection to QQ API timed out",
                error="Request timeout after 10 seconds",
            )
        except httpx.RequestError as e:
            return TestResult(
                success=False,
                message="Failed to connect to QQ API",
                error=str(e),
            )
        except Exception as e:
            return TestResult(
                success=False,
                message="Unexpected error during connection test",
                error=str(e),
            )

    def create_client(self) -> Any:
        return QQClient(self.config)


class QQClient:
    """Simple QQ Open Platform API client wrapper."""

    def __init__(self, config: QQConfig):
        self.config = config
        self._access_token: str | None = None

    async def get_access_token(self) -> str | None:
        if self._access_token:
            return self._access_token

        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{self.config.get_api_url(QQ_TOKEN_API_URL).rstrip('/')}/app/getAppAccessToken"
            data = {
                "appId": self.config.app_id,
                "clientSecret": self.config.app_secret,
            }
            response = await client.post(url, json=data)
            result = response.json()

            if "access_token" in result:
                self._access_token = result["access_token"]
                return self._access_token
        return None

    async def send_text_message(self, openid: str, content: str) -> bool:
        token = await self.get_access_token()
        if not token:
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{QQ_MESSAGE_API_URL}/v2/users/{openid}/messages"
            headers = {"Authorization": f"QQBot {token}"}
            data = {
                "msg_type": 0,
                "content": content,
            }
            response = await client.post(url, headers=headers, json=data)
            result = response.json()
            return result.get("ret") == 0


SDKRegistry.register(QQSDK.platform_name, QQSDK)
