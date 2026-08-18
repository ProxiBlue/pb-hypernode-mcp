"""brancher_delete MCP tool: delete a Hypernode Brancher preview node.

Enforces the `-eph<id>` node-name pattern and the app allowlist (derived from
the node name's appname prefix) before doing anything else, then requires an
explicit `confirm=True` re-call — surfacing the target node's details on the
first (unconfirmed) call — before issuing the DELETE request. See the
`confirm-before-delete` note in Implementation Notes (plan doc) for the
rationale behind picking a `confirm` flag over a separate two-step tool pair.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings
from pb_hypernode_mcp.tools._guards import validate_eph_node_name
from pb_hypernode_mcp.tools.brancher_list import list_brancher_nodes

_APPNAME_FROM_NODE_NAME_PATTERN = re.compile(r'^(?P<appname>.+)-eph[0-9]+$')

ClientFactory = Callable[[], tuple[HypernodeApiClient, Settings]]


class NodeNotFoundError(Exception):
    """Raised when the target Brancher node does not exist for its app."""


def _appname_from_node_name(node_name: str) -> str:
    """Derive the app's `<appname>` prefix from a validated `-eph<id>` node name."""
    match = _APPNAME_FROM_NODE_NAME_PATTERN.match(node_name)
    assert match is not None  # validated by validate_eph_node_name before this is called

    return match.group('appname')


async def delete_brancher_node(
    client: HypernodeApiClient,
    settings: Settings,
    node_name: str,
    *,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete the Brancher node `node_name`, gated behind a `confirm=True` re-call.

    On the first call (`confirm=False`, the default) this looks up the node's
    details (via `list_brancher_nodes`) and returns them along with a message
    asking the caller to re-call with `confirm=True` — it does not delete
    anything. Only when `confirm=True` is passed does the DELETE request fire.
    """
    validate_eph_node_name(node_name)

    appname = _appname_from_node_name(node_name)
    nodes = await list_brancher_nodes(appname, client=client, settings=settings)
    target = next((node for node in nodes if node['name'] == node_name), None)

    if target is None:
        raise NodeNotFoundError(f"Brancher node '{node_name}' does not exist.")

    if not confirm:
        return {
            'confirm_required': True,
            'node': target,
            'message': (
                f"About to delete Brancher node '{node_name}' "
                f'(host={target["host"]}, minutes={target["minutes"]}). '
                'Re-call with confirm=True to proceed with deletion.'
            ),
        }

    await client.delete(node_name, '')

    return {
        'deleted': True,
        'node_name': node_name,
    }


def register(server: FastMCP, client_factory: ClientFactory) -> None:
    """Register the `brancher_delete` tool on `server`.

    `client_factory` is called lazily, once per tool invocation, returning
    the `(HypernodeApiClient, Settings)` pair used to service the call.
    """

    @server.tool(name='brancher_delete')
    async def brancher_delete(node_name: str, confirm: bool = False) -> dict[str, Any]:
        """Delete a Brancher node, gated behind a `confirm=True` re-call."""
        client, settings = client_factory()

        return await delete_brancher_node(client, settings, node_name, confirm=confirm)
