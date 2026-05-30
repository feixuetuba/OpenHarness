"""Compatibility channel config models.

These models keep the synced channel adapters importable while the main
OpenHarness settings system evolves independently.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _CompatModel(BaseModel):
    """Base model that tolerates adapter-specific extra fields."""

    model_config = ConfigDict(extra="allow")


class ProviderApiKeyConfig(_CompatModel):
    api_key: str = ""


class ProviderConfigs(_CompatModel):
    groq: ProviderApiKeyConfig = Field(default_factory=ProviderApiKeyConfig)


class BaseChannelConfig(_CompatModel):
    enabled: bool = False
    # Secure default: enabling a channel does not automatically trust every
    # remote sender. Operators must explicitly allow specific identities, or
    # intentionally set ["*"] when they want open access.
    allow_from: list[str] = Field(default_factory=list)


class TelegramConfig(BaseChannelConfig):
    token: str = ""
    chat_id: str | None = None
    proxy: str | None = None
    reply_to_message: bool = True
    bot_name: str = "ohmo"


class SlackConfig(BaseChannelConfig):
    bot_token: str = ""
    app_token: str = ""
    signing_secret: str = ""


class DiscordConfig(BaseChannelConfig):
    token: str = ""


class FeishuConfig(BaseChannelConfig):
    app_id: str = ""
    app_secret: str = ""
    encrypt_key: str = ""
    verification_token: str = ""
    # Group reply policy is enforced by ohmo gateway because managed-group
    # metadata lives outside the generic Feishu channel adapter.
    group_policy: str = "managed_or_mention"
    bot_open_id: str = ""
    bot_names: list[str] = Field(default_factory=lambda: ["ohmo", "openclaw", "openharness"])
    domain: str = "https://open.feishu.cn"  # use https://open.larksuite.com for Lark international


class DingTalkConfig(BaseChannelConfig):
    client_id: str = ""
    client_secret: str = ""
    robot_code: str = ""


class EmailConfig(BaseChannelConfig):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    from_address: str = ""


class QQConfig(BaseChannelConfig):
    token: str = ""
    app_id: str = ""
    app_secret: str = ""
    sandbox: bool = False


class MatrixConfig(BaseChannelConfig):
    homeserver: str = ""
    access_token: str = ""
    user_id: str = ""


class WhatsAppConfig(BaseChannelConfig):
    access_token: str = ""
    phone_number_id: str = ""
    verify_token: str = ""


class MochatConfig(BaseChannelConfig):
    endpoint: str = ""
    token: str = ""


class ChannelConfigs(_CompatModel):
    send_progress: bool = True
    send_tool_hints: bool = True
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    dingtalk: DingTalkConfig = Field(default_factory=DingTalkConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    qq: QQConfig = Field(default_factory=QQConfig)
    matrix: MatrixConfig = Field(default_factory=MatrixConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    mochat: MochatConfig = Field(default_factory=MochatConfig)


class Config(_CompatModel):
    channels: ChannelConfigs = Field(default_factory=ChannelConfigs)
    providers: ProviderConfigs = Field(default_factory=ProviderConfigs)

    @model_validator(mode="before")
    @classmethod
    def _project_social_platforms(cls, value: Any) -> Any:
        """Project web-config social settings into runtime channel config.

        ``web_config`` is an OpenHarness app and stores social integration
        settings under ``social_platforms``. The channel runtime consumes the
        compatibility ``channels`` tree, so bridge those fields here without
        making ``web_config`` depend on any gateway-specific package.
        """
        if not isinstance(value, dict):
            return value

        social = value.get("social_platforms")
        if not isinstance(social, dict):
            return value

        channels = dict(value.get("channels") or {})
        qq_enabled = bool(social.get("qq_enabled"))
        if qq_enabled or social.get("qq_app_id") or social.get("qq_app_secret"):
            qq_config = dict(channels.get("qq") or {})
            qq_config.setdefault("enabled", qq_enabled)
            if social.get("qq_app_id"):
                qq_config.setdefault("app_id", social.get("qq_app_id"))
            if social.get("qq_app_secret"):
                qq_config.setdefault("app_secret", social.get("qq_app_secret"))
            if "qq_allow_from" in social and "allow_from" not in qq_config:
                qq_config["allow_from"] = social.get("qq_allow_from") or []
            if "qq_sandbox" in social and "sandbox" not in qq_config:
                qq_config["sandbox"] = bool(social.get("qq_sandbox"))
            channels["qq"] = qq_config

        updated = dict(value)
        updated["channels"] = channels
        return updated
