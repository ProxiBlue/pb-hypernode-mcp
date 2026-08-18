"""create_brancher_node: internal-only Brancher node creation primitive.

Enforces pre-create guardrails (mandatory label, app allowlist, Falcons-plan
eligibility, minutes-remaining display) before issuing the create request.

SECURITY (task 017): `create_brancher_node` is deliberately NEVER registered
as a standalone MCP tool. It performs zero sanitization — a node created via
this function alone would still carry live production PII, admin
credentials, and payment gateway config. The only externally-callable
node-creation entry point is the `brancher_create` MCP tool registered by
`tools/brancher_spinup_flow.py::register()`, which wraps this function
inside the non-bypassable create -> wait -> sanitize -> report-ready flow.
Do not add a `register()` function back to this module, and do not call
`create_brancher_node` directly from `server.py`.
"""

from __future__ import annotations

from typing import Any

from pb_hypernode_mcp.api_client import HypernodeApiClient

DEFAULT_CLEAR_SERVICES: tuple[str, ...] = ('cron',)

# Field names read from the app-info response (`client.get(appname, '')`).
#
# ASSUMPTION (unverified against the real Hypernode API contract — there is no
# documented "plan info" endpoint at the time of writing): plan eligibility and
# Brancher minutes usage are both surfaced on the app-info response under these
# keys. Correct these field names once the real response shape is confirmed.
PLAN_TYPE_FIELD = 'plan_type'
FALCONS_PLAN_VALUE = 'falcons'
MINUTES_REMAINING_FIELD = 'brancher_minutes_remaining'


class BrancherCreateError(ValueError):
    """Raised when a brancher_create pre-create guardrail rejects the call."""


async def create_brancher_node(
    client: HypernodeApiClient,
    app_allowlist: tuple[str, ...],
    appname: str,
    labels: list[str],
    clear_services: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Brancher node for `appname` and return its node name."""
    if not labels:
        raise BrancherCreateError('At least one label is required to create a Brancher node.')

    if appname not in app_allowlist:
        raise BrancherCreateError(
            f"App '{appname}' is not in the configured allowlist. "
            'Add it to HYPERNODE_APP_ALLOWLIST to permit Brancher operations on it.'
        )

    app_info = await client.get(appname, '')

    plan_type = str(app_info.get(PLAN_TYPE_FIELD, '')).lower()
    if plan_type != FALCONS_PLAN_VALUE:
        raise BrancherCreateError(
            f"App '{appname}' is not on a Falcons-eligible plan (Brancher requires Falcons). "
            f'Current plan: {app_info.get(PLAN_TYPE_FIELD, "unknown")}.'
        )

    body: dict[str, Any] = {
        'labels': labels,
        'clear_services': (
            clear_services if clear_services is not None else [*DEFAULT_CLEAR_SERVICES]
        ),
    }

    response = await client.post(appname, 'brancher/', json=body)

    return {
        'node_name': response.get('appname'),
        'minutes_remaining': app_info.get(MINUTES_REMAINING_FIELD),
    }
