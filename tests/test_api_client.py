"""Tests for the Hypernode REST API client wrapper."""

from __future__ import annotations

import httpx
import pytest

from pb_hypernode_mcp.api_client import (
    HypernodeApiClient,
    HypernodeApiError,
    HypernodeApiTimeoutError,
)
from pb_hypernode_mcp.config import Settings


def make_settings(token: str = 'test-token') -> Settings:
    return Settings(hypernode_api_token=token)


async def test_it_sends_the_authorization_token_header_on_every_request() -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)

        return httpx.Response(200, json={})

    client = HypernodeApiClient(
        make_settings('abc123'),
        transport=httpx.MockTransport(handler),
    )

    await client.get('myapp', 'brancher/')

    assert captured_headers['authorization'] == 'Token abc123'


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
        make_settings(),
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
        make_settings(),
        transport=httpx.MockTransport(handler),
    )

    result = await client.delete('myapp-eph1', '')

    assert captured['method'] == 'DELETE'
    assert captured['url'] == 'https://api.hypernode.com/v2/app/myapp-eph1/'
    assert result == {}
