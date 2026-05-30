"""Social platform SDK adapter system for OpenHarness.

This module provides a unified interface for different social platform SDKs,
allowing platform-specific configuration and connection testing.
"""

from __future__ import annotations

import importlib.util
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a connection test."""
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class PlatformConfig(BaseModel):
    """Base configuration for a social platform."""
    enabled: bool = False
    api_url: str = ""
    extra_config: dict[str, str] = Field(default_factory=dict)

    def get_api_url(self, default: str) -> str:
        return self.api_url.strip() or default


class WechatConfig(PlatformConfig):
    """WeChat platform configuration."""
    token: str = ""
    aes_key: str = ""
    app_id: str = ""
    app_secret: str = ""


class QQConfig(PlatformConfig):
    """QQ platform configuration."""
    app_id: str = ""
    app_secret: str = ""
    redirect_uri: str = ""


class FeishuConfig(PlatformConfig):
    """Feishu/Lark platform configuration."""
    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    domain: str = "https://open.feishu.cn"
    bot_names: list[str] = Field(default_factory=lambda: ["ohmo"])
    bot_open_id: str = ""
    group_policy: str = "managed_or_mention"


class DingtalkConfig(PlatformConfig):
    """DingTalk platform configuration."""
    app_key: str = ""
    app_secret: str = ""
    robot_code: str = ""


class SocialPlatformsConfig(BaseModel):
    """Unified social platforms configuration."""
    enabled: bool = False
    wechat: WechatConfig = Field(default_factory=WechatConfig)
    qq: QQConfig = Field(default_factory=QQConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    dingtalk: DingtalkConfig = Field(default_factory=DingtalkConfig)


class BaseSocialSDK(ABC):
    """Abstract base class for social platform SDK adapters."""

    platform_name: str = "base"

    def __init__(self, config: PlatformConfig):
        self.config = config
        self._client: Any = None

    @abstractmethod
    def is_sdk_available(self) -> bool:
        """Check if the required SDK package is installed."""
        pass

    @abstractmethod
    def validate_config(self) -> list[str]:
        """Validate configuration and return list of error messages."""
        pass

    @abstractmethod
    async def test_connection(self) -> TestResult:
        """Test the connection to the platform API."""
        pass

    @abstractmethod
    def create_client(self) -> Any:
        """Create and return the platform SDK client."""
        pass

    def get_client(self) -> Any:
        """Get or create the platform SDK client."""
        if self._client is None:
            self._client = self.create_client()
        return self._client

    def reset_client(self) -> None:
        """Reset the client instance."""
        self._client = None


class SDKRegistry:
    """Registry for social platform SDK adapters."""

    _adapters: dict[str, type[BaseSocialSDK]] = {}

    @classmethod
    def register(cls, platform_name: str, adapter_class: type[BaseSocialSDK]) -> None:
        cls._adapters[platform_name] = adapter_class

    @classmethod
    def get(cls, platform_name: str) -> type[BaseSocialSDK] | None:
        return cls._adapters.get(platform_name)

    @classmethod
    def list_platforms(cls) -> list[str]:
        return list(cls._adapters.keys())

    @classmethod
    def create_sdk(cls, platform_name: str, config: PlatformConfig) -> BaseSocialSDK | None:
        adapter_class = cls.get(platform_name)
        if adapter_class is None:
            logger.warning("No SDK adapter registered for platform: %s", platform_name)
            return None
        return adapter_class(config)
