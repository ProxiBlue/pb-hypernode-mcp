"""Tests for the brancher_ssh_info tool."""

from __future__ import annotations

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings
from pb_hypernode_mcp.tools._guards import InvalidNodeNameError
from pb_hypernode_mcp.tools.brancher_ssh_info import NodeNotReadyError, get_ssh_info, register


def make_client(handler, **tokens: str) -> HypernodeApiClient:
    return HypernodeApiClient(
        Settings(hypernode_api_tokens=tokens or {'pps': 'test-token'}),
        transport=httpx.MockTransport(handler),
    )


async def test_it_returns_host_user_and_port_for_a_valid_brancher_node_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'ip_address': '203.0.113.10'})

    client = make_client(handler)

    result = await get_ssh_info(client, 'pps-eph123456')

    assert result == {
        'host': 'pps-eph123456.hypernode.io',
        'user': 'pps-eph123456',
        'port': 22,
    }


async def test_it_rejects_a_node_name_that_does_not_match_the_eph_naming_pattern() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('the API must not be called for an invalid node name')

    client = make_client(handler)

    with pytest.raises(InvalidNodeNameError, match='pps'):
        await get_ssh_info(client, 'pps')


async def test_it_returns_a_clear_error_when_the_node_is_not_yet_ready_no_ip_assigned() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'ip_address': None})

    client = make_client(handler)

    with pytest.raises(NodeNotReadyError, match='pps-eph123456'):
        await get_ssh_info(client, 'pps-eph123456')


async def test_it_derives_the_correct_appname_from_a_node_name_to_resolve_the_right_token() -> None:
    """Only 'pps' (the parent app) has a configured token — never the node's own name.

    Proves `get_ssh_info` resolves the token via the derived parent
    `appname`, not via the full `<appname>-eph<id>` node name (which is
    never a key in `HYPERNODE_API_TOKENS`).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers['authorization'] == 'Token parent-token'

        return httpx.Response(200, json={'ip_address': '203.0.113.10'})

    client = make_client(handler, pps='parent-token')

    result = await get_ssh_info(client, 'pps-eph123456')

    assert result == {
        'host': 'pps-eph123456.hypernode.io',
        'user': 'pps-eph123456',
        'port': 22,
    }


async def test_it_registers_the_brancher_ssh_info_tool_on_the_server_and_it_is_callable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'ip_address': '203.0.113.10'})

    server = FastMCP(name='test-server')
    register(server, lambda: make_client(handler))

    tools = await server.list_tools()
    assert 'brancher_ssh_info' in [tool.name for tool in tools]

    _content, structured_result = await server.call_tool(
        'brancher_ssh_info', {'node_name': 'pps-eph123456'}
    )
    assert structured_result == {
        'host': 'pps-eph123456.hypernode.io',
        'user': 'pps-eph123456',
        'port': 22,
    }
