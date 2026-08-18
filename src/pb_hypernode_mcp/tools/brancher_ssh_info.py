"""brancher_ssh_info MCP tool.

Returns SSH connection details (host, user, port) for a Brancher node, so the
exec/put tools have a clean source of connection parameters. This tool does
not open an SSH connection itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.tools._guards import validate_eph_node_name

SSH_PORT = 22


class NodeNotReadyError(Exception):
    """Raised when a Brancher node has no IP assigned yet (not ready for SSH)."""


async def get_ssh_info(client: HypernodeApiClient, node_name: str) -> dict[str, Any]:
    """Return `{host, user, port}` SSH connection details for `node_name`."""
    validate_eph_node_name(node_name)

    detail = await client.get(node_name, '')

    if not detail.get('ip_address'):
        raise NodeNotReadyError(f'Brancher node {node_name!r} is not ready yet (no IP assigned).')

    return {
        'host': f'{node_name}.hypernode.io',
        'user': node_name,
        'port': SSH_PORT,
    }


def register(server: FastMCP, client_factory: Callable[[], HypernodeApiClient]) -> None:
    """Register the `brancher_ssh_info` tool on `server`.

    `client_factory` is called lazily, once per tool invocation, so server
    construction never eagerly requires a configured `HypernodeApiClient`.
    """

    @server.tool(name='brancher_ssh_info')
    async def brancher_ssh_info(node_name: str) -> dict[str, Any]:
        """Return SSH connection details (host, user, port) for a Brancher node."""
        return await get_ssh_info(client_factory(), node_name)
