"""brancher_list MCP tool.

Lists active Brancher nodes for a Hypernode app.

VERIFIED (2026-08-19) against a live curl on a real Hypernode account's
Brancher list endpoint (`GET /v2/app/<appname>/brancher/`, the deprecated but
still-working endpoint — same response shape as the real, non-deprecated
`GET /v2/brancher/app/<appname>/`, confirmed via the official
`ByteInternet/hypernode-api-python` client's `client.py`
(`HYPERNODE_API_BRANCHER_APP_ENDPOINT = "/v2/brancher/app/{}/"`)):

```json
{"monthly_total_time": 332, "branchers": [
    {"id": 33358, "name": "ppsdev-ephp8b5c2", "cost": 6,
     "created": "2026-08-19T12:27:14.791544Z", "ip": null, "end_time": null,
     "elapsed_time": 332, "labels": {"test1": null}}
]}
```

The node list is under a top-level `branchers` key, not `nodes`. Each entry
has no `host` field (derived here as `f"{name}.hypernode.io"`) and no
`minutes` field (derived here as `elapsed_time // 60` — `elapsed_time` is
wall-clock **seconds** since creation, not minutes).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings

ClientFactory = Callable[[], tuple[HypernodeApiClient, Settings]]


async def list_brancher_nodes(
    appname: str,
    *,
    client: HypernodeApiClient,
) -> list[dict[str, Any]]:
    """List active Brancher nodes for `appname`.

    Raises `UnknownAppError` (via `client.get` -> `Settings.token_for`) when
    `appname` has no configured token — there is nothing to authenticate
    the request with.

    `ip` is the node's real, non-null-once-provisioned IP address (`None`
    until Hypernode's own infra finishes assigning one) — task 022 added
    this field to the returned dict so the Brancher spin-up flow's
    IP-assignment poll phase can reuse this same function/endpoint rather
    than duplicating the HTTP call.
    """
    response = await client.get_path(f'brancher/app/{appname}/', token_appname=appname)
    nodes = response.get('branchers', [])

    return [
        {
            'name': node['name'],
            'host': f'{node["name"]}.hypernode.io',
            'minutes': node['elapsed_time'] // 60,
            'ip': node.get('ip'),
        }
        for node in nodes
    ]


def register(server: FastMCP, client_factory: ClientFactory) -> None:
    """Register the `brancher_list` tool on `server`.

    `client_factory` is called lazily, once per tool invocation, returning
    the `(HypernodeApiClient, Settings)` pair used to service the call.
    `settings` itself is unused here — kept in the factory's return shape
    only because other tools sharing this `client_factory` pattern
    (`brancher_delete`) still need it.
    """

    @server.tool(name='brancher_list')
    async def brancher_list(appname: str) -> list[dict[str, Any]]:
        """List active Brancher nodes for `appname`."""
        client, _settings = client_factory()

        return await list_brancher_nodes(appname, client=client)
