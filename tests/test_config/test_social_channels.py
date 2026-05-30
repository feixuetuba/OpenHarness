from openharness.config.schema import Config


def test_social_platforms_qq_projects_to_runtime_channel() -> None:
    config = Config.model_validate(
        {
            "social_platforms": {
                "qq_enabled": True,
                "qq_app_id": "app-id",
                "qq_app_secret": "secret",
                "qq_allow_from": ["*"],
            }
        }
    )

    assert config.channels.qq.enabled is True
    assert config.channels.qq.app_id == "app-id"
    assert config.channels.qq.app_secret == "secret"
    assert config.channels.qq.allow_from == ["*"]


def test_explicit_qq_channel_config_wins_over_social_platform_defaults() -> None:
    config = Config.model_validate(
        {
            "channels": {
                "qq": {
                    "enabled": False,
                    "app_id": "channel-app-id",
                    "app_secret": "channel-secret",
                    "allow_from": ["user-openid"],
                }
            },
            "social_platforms": {
                "qq_enabled": True,
                "qq_app_id": "social-app-id",
                "qq_app_secret": "social-secret",
                "qq_allow_from": ["*"],
            },
        }
    )

    assert config.channels.qq.enabled is False
    assert config.channels.qq.app_id == "channel-app-id"
    assert config.channels.qq.app_secret == "channel-secret"
    assert config.channels.qq.allow_from == ["user-openid"]
