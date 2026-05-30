import json

import httpx
import pytest

from openharness.channels.social_sdk import QQConfig
from openharness.channels.social_sdk.qq import QQClient, QQSDK


class _FakeAsyncClient:
    requests: list[httpx.Request] = []
    responses: list[httpx.Response] = []

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        **_: object,
    ) -> httpx.Response:
        request = httpx.Request(
            "POST",
            url,
            headers=headers,
            content=json_module.dumps(json or {}).encode(),
        )
        self.requests.append(request)
        return self.responses.pop(0)


json_module = json


@pytest.fixture(autouse=True)
def _reset_fake_client() -> None:
    _FakeAsyncClient.requests = []
    _FakeAsyncClient.responses = []


@pytest.mark.asyncio
async def test_qq_sdk_uses_bot_access_token_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from openharness.channels.social_sdk import qq as qq_module

    _FakeAsyncClient.responses.append(
        httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
    )
    monkeypatch.setattr(qq_module.httpx, "AsyncClient", _FakeAsyncClient)

    sdk = QQSDK(QQConfig(app_id="app-id", app_secret="secret"))
    result = await sdk.test_connection()

    assert result.success is True
    request = _FakeAsyncClient.requests[0]
    assert str(request.url) == "https://bots.qq.com/app/getAppAccessToken"
    assert json.loads(request.content) == {
        "appId": "app-id",
        "clientSecret": "secret",
    }


@pytest.mark.asyncio
async def test_qq_client_sends_user_message_with_qqbot_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openharness.channels.social_sdk import qq as qq_module

    _FakeAsyncClient.responses.extend(
        [
            httpx.Response(200, json={"access_token": "token", "expires_in": 7200}),
            httpx.Response(200, json={"ret": 0}),
        ]
    )
    monkeypatch.setattr(qq_module.httpx, "AsyncClient", _FakeAsyncClient)

    client = QQClient(QQConfig(app_id="app-id", app_secret="secret"))
    assert await client.send_text_message("user-openid", "hello") is True

    request = _FakeAsyncClient.requests[1]
    assert str(request.url) == "https://api.sgroup.qq.com/v2/users/user-openid/messages"
    assert request.headers["authorization"] == "QQBot token"
    assert json.loads(request.content) == {"msg_type": 0, "content": "hello"}
