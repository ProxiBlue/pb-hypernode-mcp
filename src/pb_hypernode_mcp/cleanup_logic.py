"""Pure/async helpers backing the `brancher-cleanup` skill.

The skill itself (`skills/brancher-cleanup/SKILL.md`) is markdown instructions
telling Claude which MCP tools to call, and in what order, to review and
remove stale Brancher preview nodes. The one piece of real decision logic in
that flow — which nodes are old enough (wall-clock minutes-alive) to flag for
cleanup — is extracted here as a plain, unit-testable function rather than
left as prose for Claude to interpret at runtime.

`cleanup_stale_nodes` composes the existing `list_brancher_nodes` and
`delete_brancher_node` tool functions (tasks 004/005) with `flag_stale_nodes`
to provide the bulk confirm-before-delete flow described in the skill.
"""

from __future__ import annotations

from typing import Any

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings
from pb_hypernode_mcp.tools.brancher_delete import delete_brancher_node
from pb_hypernode_mcp.tools.brancher_list import list_brancher_nodes

# Hypernode's own Brancher docs use 4 hours (240 minutes) as a sample
# cleanup-age threshold; kept as this module's default, overridable per call.
DEFAULT_AGE_THRESHOLD_MINUTES = 240


def flag_stale_nodes(
    nodes: list[dict[str, Any]],
    threshold_minutes: int = DEFAULT_AGE_THRESHOLD_MINUTES,
) -> list[dict[str, Any]]:
    """Return the subset of `nodes` whose wall-clock `minutes` meets/exceeds the threshold."""
    return [node for node in nodes if node['minutes'] >= threshold_minutes]


async def cleanup_stale_nodes(
    appname: str,
    *,
    client: HypernodeApiClient,
    settings: Settings,
    threshold_minutes: int = DEFAULT_AGE_THRESHOLD_MINUTES,
    confirm: bool = False,
) -> dict[str, Any]:
    """List `appname`'s Brancher nodes, flag stale ones, and (if confirmed) delete them all.

    Mirrors `delete_brancher_node`'s confirm-before-delete gate at the bulk level: the
    first call (`confirm=False`, the default) returns the flagged nodes without deleting
    anything; only a `confirm=True` re-call issues the deletes. When nothing is flagged,
    reports that there is nothing to clean up regardless of `confirm`.
    """
    nodes = await list_brancher_nodes(appname, client=client, settings=settings)
    flagged = flag_stale_nodes(nodes, threshold_minutes)

    if not flagged:
        return {
            'flagged': [],
            'deleted': [],
            'message': (
                f'Nothing to clean up — no nodes past the {threshold_minutes}-minute threshold.'
            ),
        }

    if not confirm:
        return {
            'confirm_required': True,
            'flagged': flagged,
            'message': (
                f'{len(flagged)} node(s) past the {threshold_minutes}-minute threshold. '
                'Re-call with confirm=True to delete them all.'
            ),
        }

    deleted: list[str] = []

    for node in flagged:
        await delete_brancher_node(client, settings, node['name'], confirm=True)
        deleted.append(node['name'])

    return {'flagged': flagged, 'deleted': deleted}
