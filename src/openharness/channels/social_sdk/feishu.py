"""Feishu/Lark SDK adapter for OpenHarness."""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

from openharness.channels.social_sdk.base import (
    BaseSocialSDK,
    FeishuConfig,
    SDKRegistry,
    TestResult,
)

logger = logging.getLogger(__name__)


class FeishuSDK(BaseSocialSDK):
    """Feishu/Lark platform SDK adapter using lark-oapi SDK."""

    platform_name = "feishu"

    def __init__(self, config: FeishuConfig):
        super().__init__(config)
        self.config: FeishuConfig = config

    def is_sdk_available(self) -> bool:
        return importlib.util.find_spec("lark_oapi") is not None

    def validate_config(self) -> list[str]:
        errors = []
        if not self.config.app_id:
            errors.append("App ID is required")
        if not self.config.app_secret:
            errors.append("App Secret is required")
        if not self.config.domain:
            errors.append("API domain is required")
        return errors

    async def test_connection(self) -> TestResult:
        if not self.is_sdk_available():
            return TestResult(
                success=False,
                message="Feishu SDK (lark-oapi) not installed",
                error="Run: pip install lark-oapi",
            )

        config_errors = self.validate_config()
        if config_errors:
            return TestResult(
                success=False,
                message="Configuration validation failed",
                error="; ".join(config_errors),
            )

        try:
            import lark_oapi as lark

            client = lark.Client.builder().app_id(self.config.app_id).app_secret(
                self.config.app_secret
            ).domain(self.config.domain).log_level(lark.LogLevel.WARNING).build()

            try:
                from lark_oapi.api.contact.v3 import GetContactScopeConfigRequest

                request = GetContactScopeConfigRequest.builder().user_id_type(
                    "open_id"
                ).build()
                response = client.contact.v3.contact_scope_config.get(request)

                if response.success():
                    return TestResult(
                        success=True,
                        message="Successfully connected to Feishu API",
                        details={
                            "app_id": self.config.app_id,
                            "domain": self.config.domain,
                            "sdk_version": lark.__version__ if hasattr(lark, "__version__") else "unknown",
                        },
                    )
                else:
                    return TestResult(
                        success=False,
                        message=f"Feishu API returned error: code={response.code}",
                        error=response.msg or "Unknown error",
                        details={"code": response.code, "log_id": getattr(response, "log_id", None)},
                    )
            except Exception:
                try:
                    from lark_oapi.api.authen.v1 import GetAccessTokenRequest

                    request = (
                        GetAccessTokenRequest.builder()
                        .request_body(
                            lark.api.authen.v1.CreateAccessTokenRequestBody.builder()
                            .app_id(self.config.app_id)
                            .app_secret(self.config.app_secret)
                            .grant_type("client_credentials")
                            .build()
                        )
                        .build()
                    )
                    response = client.authen.v1.access_token.create(request)

                    if response.success():
                        return TestResult(
                            success=True,
                            message="Successfully authenticated with Feishu API",
                            details={
                                "app_id": self.config.app_id,
                                "domain": self.config.domain,
                            },
                        )
                    else:
                        return TestResult(
                            success=False,
                            message=f"Authentication failed: code={response.code}",
                            error=response.msg or "Authentication error",
                            details={"code": response.code},
                        )
                except Exception as e:
                    return TestResult(
                        success=False,
                        message="Failed to test Feishu connection",
                        error=str(e),
                    )
        except ImportError as e:
            return TestResult(
                success=False,
                message="Failed to import lark-oapi SDK",
                error=str(e),
            )
        except Exception as e:
            return TestResult(
                success=False,
                message="Unexpected error during connection test",
                error=str(e),
            )

    def create_client(self) -> Any:
        import lark_oapi as lark

        return (
            lark.Client.builder()
            .app_id(self.config.app_id)
            .app_secret(self.config.app_secret)
            .domain(self.config.domain)
            .log_level(lark.LogLevel.INFO)
            .build()
        )


SDKRegistry.register(FeishuSDK.platform_name, FeishuSDK)
