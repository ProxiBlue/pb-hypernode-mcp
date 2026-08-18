"""Tests for the `brancher_apps` MCP tool."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.config import Settings
from pb_hypernode_mcp.tools.brancher_apps import list_configured_apps, register


def make_settings(**tokens: str) -> Settings:
    return Settings(hypernode_api_tokens=tokens or {'myapp': 'test-token'})


def test_it_lists_configured_app_names() -> None:
    settings = make_settings(zapp='token1', aapp='token2')

    assert list_configured_apps(settings) == ('aapp', 'zapp')


async def test_it_lists_configured_app_names_via_the_brancher_apps_tool_with_no_arguments() -> None:
    settings = make_settings(myapp='token1', myapp2='token2')

    server = FastMCP(name='test-server')
    register(server, lambda: settings)

    tools = await server.list_tools()
    assert 'brancher_apps' in [tool.name for tool in tools]

    _content, result = await server.call_tool('brancher_apps', {})

    assert result == {'result': ['myapp', 'myapp2']}
