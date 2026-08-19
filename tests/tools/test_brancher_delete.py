"""Tests for the `brancher_delete` tool."""

from __future__ import annotations

import httpx
import pytest

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings, UnknownAppError
from pb_hypernode_mcp.tools._guards import InvalidNodeNameError
from pb_hypernode_mcp.tools.brancher_delete import NodeNotFoundError, delete_brancher_node

NODES_RESPONSE = {
    'branchers': [
        {'name': 'myapp-eph1', 'elapsed_time': 720},
    ],
}


def make_settings(**tokens: str) -> Settings:
    return Settings(hypernode_api_tokens=tokens or {'myapp': 'test-token'})


def make_client(handler, settings: Settings | None = None) -> HypernodeApiClient:
    return HypernodeApiClient(
        settings if settings is not None else make_settings(),
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
        'ip': None,
    }


async def test_it_rejects_deletion_when_the_app_has_no_configured_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('API must not be called for an app with no configured token')

    settings = make_settings(otherapp='test-token')
    client = make_client(handler, settings)

    with pytest.raises(UnknownAppError, match='myapp'):
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
        return httpx.Response(200, json={'branchers': []})

    client = make_client(handler)
    settings = make_settings()

    with pytest.raises(NodeNotFoundError, match='myapp-eph1'):
        await delete_brancher_node(client, settings, 'myapp-eph1', confirm=True)


async def test_it_deletes_a_brancher_node_via_the_brancher_name_endpoint_not_nested_under_app() -> (
    None
):
    """Real destroy endpoint is `DELETE /v2/brancher/<name>/` — a *different* top-level
    path than list/create (`HYPERNODE_API_BRANCHER_ENDPOINT` in the official
    `ByteInternet/hypernode-api-python` client's `client.py`), not nested under
    `/v2/app/<appname>/...` at all.
    """
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'DELETE':
            captured_urls.append(str(request.url))

            return httpx.Response(200, json={})

        return httpx.Response(200, json=NODES_RESPONSE)

    client = make_client(handler)
    settings = make_settings()

    await delete_brancher_node(client, settings, 'myapp-eph1', confirm=True)

    assert captured_urls == ['https://api.hypernode.com/v2/brancher/myapp-eph1/']


async def test_it_derives_the_correct_appname_from_a_node_name_to_resolve_the_right_token() -> None:
    """Only 'myapp' (the parent app) has a configured token — never the node's own name.

    Proves `delete_brancher_node` resolves the token via the derived parent
    `appname`, not via the full `<appname>-eph<id>` node name (which is
    never a key in `HYPERNODE_API_TOKENS`).
    """
    delete_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delete_called

        assert request.headers['authorization'] == 'Token parent-token'

        if request.method == 'DELETE':
            delete_called = True

            return httpx.Response(200, json={})

        return httpx.Response(200, json=NODES_RESPONSE)

    settings = make_settings(myapp='parent-token')
    client = make_client(handler, settings)

    result = await delete_brancher_node(client, settings, 'myapp-eph1', confirm=True)

    assert delete_called is True
    assert result == {'deleted': True, 'node_name': 'myapp-eph1'}
