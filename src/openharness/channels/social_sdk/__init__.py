"""Social platform SDK adapters for OpenHarness."""

from openharness.channels.social_sdk.base import (
    BaseSocialSDK,
    DingtalkConfig,
    FeishuConfig,
    PlatformConfig,
    QQConfig,
    SDKRegistry,
    SocialPlatformsConfig,
    TestResult,
    WechatConfig,
)

__all__ = [
    "BaseSocialSDK",
    "DingtalkConfig",
    "FeishuConfig",
    "PlatformConfig",
    "QQConfig",
    "SDKRegistry",
    "SocialPlatformsConfig",
    "TestResult",
    "WechatConfig",
]

import openharness.channels.social_sdk.feishu
import openharness.channels.social_sdk.qq
import openharness.channels.social_sdk.wechat
