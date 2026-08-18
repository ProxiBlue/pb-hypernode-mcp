"""Tests for the `brancher_delete` tool."""

from __future__ import annotations

import httpx
import pytest

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings
from pb_hypernode_mcp.tools._guards import InvalidNodeNameError
from pb_hypernode_mcp.tools.brancher_delete import NodeNotFoundError, delete_brancher_node
from pb_hypernode_mcp.tools.brancher_list import AppNotAllowedError

NODES_RESPONSE = {
    'nodes': [
        {'name': 'myapp-eph1', 'host': 'myapp-eph1.hypernode.io', 'minutes': 12},
    ],
}


def make_settings(allowlist: str = 'myapp') -> Settings:
    return Settings(hypernode_api_token='test-token', hypernode_app_allowlist=allowlist)


def make_client(handler) -> HypernodeApiClient:
    return HypernodeApiClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )


async def test_it_deletes_a_brancher_node_given_its_exact_node_name() -> None:
    delete_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delete_called

        if request.method == 'DELETE':
            delete_called = True

            return httpx.Response(200, json={})

        return httpx.Response(200, json=NODES_RESPONSE)

    client = make_client(handler)
    settings = make_settings()

    result = await delete_brancher_node(client, settings, 'myapp-eph1', confirm=True)

    assert delete_called is True
    assert result == {'deleted': True, 'node_name': 'myapp-eph1'}


async def test_it_surfaces_the_target_nodes_details_before_deletion_completes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'DELETE':
            raise AssertionError('delete must not be called before confirmation')

        return httpx.Response(200, json=NODES_RESPONSE)

    client = make_client(handler)
    settings = make_settings()

    result = await delete_brancher_node(client, settings, 'myapp-eph1')

    assert result['confirm_required'] is True
    assert result['node'] == {
        'name': 'myapp-eph1',
        'host': 'myapp-eph1.hypernode.io',
        'minutes': 12,
    }


async def test_it_rejects_deletion_when_the_app_is_not_in_the_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('API must not be called for a disallowed app')

    client = make_client(handler)
    settings = make_settings(allowlist='otherapp')

    with pytest.raises(AppNotAllowedError, match='myapp'):
        await delete_brancher_node(client, settings, 'myapp-eph1', confirm=True)


async def test_it_rejects_deletion_of_a_node_name_that_does_not_match_the_eph_naming_pattern() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('the API must not be called for an invalid node name')

    client = make_client(handler)
    settings = make_settings()

    with pytest.raises(InvalidNodeNameError, match='myapp'):
        await delete_brancher_node(client, settings, 'myapp', confirm=True)


async def test_it_returns_a_clear_error_when_the_target_node_does_not_exist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'nodes': []})

    client = make_client(handler)
    settings = make_settings()

    with pytest.raises(NodeNotFoundError, match='myapp-eph1'):
        await delete_brancher_node(client, settings, 'myapp-eph1', confirm=True)
