"""Tests for the Hypernode REST API client wrapper."""

from __future__ import annotations

import httpx
import pytest

from pb_hypernode_mcp.api_client import (
    HypernodeApiClient,
    HypernodeApiError,
    HypernodeApiTimeoutError,
)
from pb_hypernode_mcp.config import Settings, UnknownAppError


def make_settings(**tokens: str) -> Settings:
    return Settings(hypernode_api_tokens=tokens or {'myapp': 'test-token'})


async def test_it_sends_the_authorization_token_header_on_every_request() -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)

        return httpx.Response(200, json={})

    client = HypernodeApiClient(
        make_settings(myapp='abc123'),
        transport=httpx.MockTransport(handler),
    )

    await client.get('myapp', 'brancher/')

    assert captured_headers['authorization'] == 'Token abc123'


async def test_it_resolves_the_correct_token_for_a_given_appname_on_each_api_request() -> None:
    captured_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers['authorization'])

        return httpx.Response(200, json={})

    client = HypernodeApiClient(
        make_settings(myapp='token1', myapp2='token2'),
        transport=httpx.MockTransport(handler),
    )

    await client.get('myapp', 'brancher/')
    await client.get('myapp2', 'brancher/')

    assert captured_headers == ['Token token1', 'Token token2']


async def test_it_raises_a_clear_error_when_a_request_targets_an_app_with_no_configured_token() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('the API must not be called for an app with no configured token')

    client = HypernodeApiClient(
        make_settings(myapp='token1'),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(UnknownAppError, match='myapp'):
        await client.get('otherapp', 'brancher/')


async def test_it_raises_a_typed_hypernode_api_error_with_status_code_and_body_on_a_4xx_response() -> (  # noqa: E501
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text='{"detail": "Not found"}')

    client = HypernodeApiClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(HypernodeApiError) as exc_info:
        await client.get('myapp', 'brancher/')

    assert exc_info.value.status_code == 404
    assert exc_info.value.body == '{"detail": "Not found"}'


async def test_it_raises_a_typed_hypernode_api_error_on_a_5xx_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text='{"detail": "Service unavailable"}')

    client = HypernodeApiClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(HypernodeApiError) as exc_info:
        await client.get('myapp', 'brancher/')

    assert exc_info.value.status_code == 503
    assert exc_info.value.body == '{"detail": "Service unavailable"}'


async def test_it_raises_a_timeout_error_when_the_request_exceeds_the_configured_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException('timed out', request=request)

    client = HypernodeApiClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
        timeout=1.0,
    )

    with pytest.raises(HypernodeApiTimeoutError):
        await client.get('myapp', 'brancher/')


async def test_it_parses_a_successful_json_response_into_a_plain_dict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'appname': 'myapp-eph1', 'status': 'active'})

    client = HypernodeApiClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    result = await client.get('myapp', 'brancher/')

    assert result == {'appname': 'myapp-eph1', 'status': 'active'}
    assert isinstance(result, dict)


async def test_it_constructs_the_correct_url_for_a_given_appname_and_sub_resource_path() -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))

        return httpx.Response(200, json={})

    client = HypernodeApiClient(
        make_settings(myapp='test-token', **{'myapp-eph42': 'test-token'}),
        transport=httpx.MockTransport(handler),
    )

    await client.get('myapp', 'brancher/')
    await client.get('myapp-eph42', 'ssh/')

    assert captured_urls == [
        'https://api.hypernode.com/v2/app/myapp/brancher/',
        'https://api.hypernode.com/v2/app/myapp-eph42/ssh/',
    ]


async def test_it_sends_a_post_request_with_a_json_body_to_create_a_resource() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['method'] = request.method
        captured['url'] = str(request.url)
        captured['body'] = request.content

        return httpx.Response(201, json={'appname': 'myapp-eph1'})

    client = HypernodeApiClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    result = await client.post('myapp', 'brancher/', json={'branch': 'feature/x'})

    assert captured['method'] == 'POST'
    assert captured['url'] == 'https://api.hypernode.com/v2/app/myapp/brancher/'
    assert captured['body'] == b'{"branch":"feature/x"}'
    assert result == {'appname': 'myapp-eph1'}


async def test_it_sends_a_delete_request_to_remove_a_resource() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['method'] = request.method
        captured['url'] = str(request.url)

        return httpx.Response(204, json={})

    client = HypernodeApiClient(
        make_settings(**{'myapp-eph1': 'test-token'}),
        transport=httpx.MockTransport(handler),
    )

    result = await client.delete('myapp-eph1', '')

    assert captured['method'] == 'DELETE'
    assert captured['url'] == 'https://api.hypernode.com/v2/app/myapp-eph1/'
    assert result == {}


async def test_it_resolves_the_token_via_an_explicit_token_appname_when_the_url_appname_differs() -> (  # noqa: E501
    None
):
    captured_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers['authorization'])

        return httpx.Response(200, json={})

    client = HypernodeApiClient(
        make_settings(myapp='parent-token'),
        transport=httpx.MockTransport(handler),
    )

    # 'myapp-eph1' is a Brancher node URL segment, but the token that
    # authenticates it is the parent app's ('myapp'), not 'myapp-eph1'.
    await client.get('myapp-eph1', '', token_appname='myapp')

    assert captured_headers == ['Token parent-token']


async def test_it_sends_a_get_path_request_against_a_raw_path_with_no_app_prefix() -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))

        return httpx.Response(200, json={'branchers': []})

    client = HypernodeApiClient(
        make_settings(myapp='test-token'),
        transport=httpx.MockTransport(handler),
    )

    result = await client.get_path('brancher/app/myapp/', token_appname='myapp')

    assert captured_urls == ['https://api.hypernode.com/v2/brancher/app/myapp/']
    assert result == {'branchers': []}


async def test_it_sends_a_post_path_request_against_a_raw_path_with_no_app_prefix() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['method'] = request.method
        captured['url'] = str(request.url)
        captured['body'] = request.content

        return httpx.Response(201, json={'name': 'myapp-eph1'})

    client = HypernodeApiClient(
        make_settings(myapp='test-token'),
        transport=httpx.MockTransport(handler),
    )

    result = await client.post_path(
        'brancher/app/myapp/', json={'labels': ['x']}, token_appname='myapp'
    )

    assert captured['method'] == 'POST'
    assert captured['url'] == 'https://api.hypernode.com/v2/brancher/app/myapp/'
    assert captured['body'] == b'{"labels":["x"]}'
    assert result == {'name': 'myapp-eph1'}


async def test_it_sends_a_delete_path_request_against_a_raw_path_with_no_app_prefix() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['method'] = request.method
        captured['url'] = str(request.url)

        return httpx.Response(204, json={})

    client = HypernodeApiClient(
        make_settings(myapp='test-token'),
        transport=httpx.MockTransport(handler),
    )

    result = await client.delete_path('brancher/myapp-eph1/', token_appname='myapp')

    assert captured['method'] == 'DELETE'
    assert captured['url'] == 'https://api.hypernode.com/v2/brancher/myapp-eph1/'
    assert result == {}
