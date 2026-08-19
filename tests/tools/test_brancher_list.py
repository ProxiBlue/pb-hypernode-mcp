"""Tests for the `brancher_list` MCP tool."""

from __future__ import annotations

import httpx
import pytest

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings, UnknownAppError
from pb_hypernode_mcp.tools.brancher_list import list_brancher_nodes


def make_settings(**tokens: str) -> Settings:
    return Settings(hypernode_api_tokens=tokens or {'myapp': 'test-token'})


def make_client(handler) -> HypernodeApiClient:
    return HypernodeApiClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )


async def test_it_lists_all_active_brancher_nodes_for_an_app() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                'branchers': [
                    {'name': 'myapp-eph1', 'elapsed_time': 720},
                    {'name': 'myapp-eph2', 'elapsed_time': 2040},
                ],
            },
        )

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert len(nodes) == 2


async def test_it_lists_brancher_nodes_via_the_non_deprecated_brancher_app_appname_endpoint() -> (
    None
):
    """Real accounts get a deprecation warning off `GET /app/<appname>/brancher/`; the
    real, non-deprecated endpoint is `GET /brancher/app/<appname>/`
    (`HYPERNODE_API_BRANCHER_APP_ENDPOINT` in the official
    `ByteInternet/hypernode-api-python` client's `client.py`).
    """
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))

        return httpx.Response(200, json={'branchers': []})

    client = make_client(handler)
    settings = make_settings()

    await list_brancher_nodes('myapp', client=client, settings=settings)

    assert captured_urls == ['https://api.hypernode.com/v2/brancher/app/myapp/']


async def test_it_returns_each_nodes_name_host_and_minutes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                'branchers': [
                    {'name': 'myapp-eph1', 'elapsed_time': 720},
                ],
            },
        )

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert nodes == [
        {'name': 'myapp-eph1', 'host': 'myapp-eph1.hypernode.io', 'minutes': 12},
    ]


async def test_it_parses_the_branchers_key_from_the_list_response_not_nodes() -> None:
    """Live curl on a real account's Brancher list returns the node array under a top-level
    `branchers` key — `nodes` does not exist in the real response at all, so a response
    shaped with only a `nodes` key (the old, wrong assumption) must parse as empty."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={'nodes': [{'name': 'myapp-eph1', 'elapsed_time': 720}]},
        )

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert nodes == []


async def test_it_derives_host_from_the_node_name_since_the_api_does_not_return_one_directly() -> (
    None
):
    """The real Brancher list response has no `host` field at all — only `name`, `ip`
    (null until ready), `created`, `elapsed_time`, `cost`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={'branchers': [{'name': 'ppsdev-ephp8b5c2', 'elapsed_time': 332}]},
        )

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert nodes[0]['host'] == 'ppsdev-ephp8b5c2.hypernode.io'


async def test_it_returns_an_empty_list_when_no_brancher_nodes_exist_for_the_app() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'branchers': []})

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert nodes == []


async def test_it_rejects_the_call_when_the_app_has_no_configured_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('API must not be called for an app with no configured token')

    settings = make_settings(otherapp='test-token')
    client = HypernodeApiClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(UnknownAppError, match='myapp'):
        await list_brancher_nodes('myapp', client=client, settings=settings)
