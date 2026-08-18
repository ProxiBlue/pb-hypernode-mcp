"""brancher_list MCP tool.

Lists active Brancher nodes for a Hypernode app.

Assumption on API response shape (not yet verified against the real
Hypernode API): `GET /app/<appname>/brancher/` returns a JSON body shaped
like `{"nodes": [{"name": ..., "host": ..., "minutes": ...}, ...]}` — a dict
with a top-level `nodes` list of node dicts, each carrying at least `name`,
`host`, and `minutes` keys. `minutes` is wall-clock uptime since node
creation, not idle-aware. If the real API instead returns a bare JSON list,
or nests the list under a different key, this will need adjusting.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings

ClientFactory = Callable[[], tuple[HypernodeApiClient, Settings]]


class AppNotAllowedError(Exception):
    """Raised when `appname` is not present in the configured app allowlist."""


async def list_brancher_nodes(
    appname: str,
    *,
    client: HypernodeApiClient,
    settings: Settings,
) -> list[dict[str, Any]]:
    """List active Brancher nodes for `appname`."""
    if appname not in settings.app_allowlist:
        raise AppNotAllowedError(f"App '{appname}' is not in the configured allowlist.")

    response = await client.get(appname, 'brancher/')
    nodes = response.get('nodes', [])

    return [
        {
            'name': node['name'],
            'host': node['host'],
            'minutes': node['minutes'],
        }
        for node in nodes
    ]


def register(server: FastMCP, client_factory: ClientFactory) -> None:
    """Register the `brancher_list` tool on `server`.

    `client_factory` is called lazily, once per tool invocation, returning
    the `(HypernodeApiClient, Settings)` pair used to service the call.
    """

    @server.tool(name='brancher_list')
    async def brancher_list(appname: str) -> list[dict[str, Any]]:
        """List active Brancher nodes for `appname`."""
        client, settings = client_factory()

        return await list_brancher_nodes(appname, client=client, settings=settings)
