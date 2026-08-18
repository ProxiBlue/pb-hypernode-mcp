"""Tests for the `brancher_list` MCP tool."""

from __future__ import annotations

import httpx
import pytest

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings
from pb_hypernode_mcp.tools.brancher_list import AppNotAllowedError, list_brancher_nodes


def make_settings(allowlist: str = 'myapp') -> Settings:
    return Settings(hypernode_api_token='test-token', hypernode_app_allowlist=allowlist)


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
                'nodes': [
                    {'name': 'myapp-eph1', 'host': 'myapp-eph1.hypernode.io', 'minutes': 12},
                    {'name': 'myapp-eph2', 'host': 'myapp-eph2.hypernode.io', 'minutes': 34},
                ],
            },
        )

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert len(nodes) == 2


async def test_it_returns_each_nodes_name_host_and_minutes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                'nodes': [
                    {'name': 'myapp-eph1', 'host': 'myapp-eph1.hypernode.io', 'minutes': 12},
                ],
            },
        )

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert nodes == [
        {'name': 'myapp-eph1', 'host': 'myapp-eph1.hypernode.io', 'minutes': 12},
    ]


async def test_it_returns_an_empty_list_when_no_brancher_nodes_exist_for_the_app() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'nodes': []})

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert nodes == []


async def test_it_rejects_the_call_when_the_app_is_not_in_the_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('API must not be called for a disallowed app')

    client = make_client(handler)
    settings = make_settings(allowlist='otherapp')

    with pytest.raises(AppNotAllowedError, match='myapp'):
        await list_brancher_nodes('myapp', client=client, settings=settings)
