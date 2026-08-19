"""create_brancher_node: internal-only Brancher node creation primitive.

Enforces pre-create guardrails (mandatory label, Falcons-plan eligibility,
minutes-remaining display) before issuing the create request. There is no
separate app-allowlist check — `client.get(appname, ...)` naturally raises
`UnknownAppError` (via `Settings.token_for`) when `appname` has no
configured Hypernode API token.

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
# Verified 2026-08-19 against a real Hypernode account (GET /v2/app/<appname>/):
# plan eligibility lives at `product.code` (e.g. "FALCON_S_202603DEV" -- match on
# a "FALCON" substring, not an exact/enum value; Hypernode has multiple Falcon
# SKUs). The earlier assumption of a top-level `plan_type` field was wrong.
#
# There is no minutes-remaining field anywhere on this endpoint -- the earlier
# assumption of a top-level `brancher_minutes_remaining` field was also wrong
# and has been dropped entirely (see `minutes_remaining` below, now always
# `None`). Hypernode's own `--list` CLI reports per-node minutes USED (not an
# account-wide remaining balance) via the node-list endpoint, which itself
# requires `allow_api_token_usage` enabled on the app in the Control Panel
# (Configuration -> Settings) -- financial/Brancher API calls 403 without it.
# No verified source for a "remaining minutes" figure exists yet.
FALCONS_PLAN_SUBSTRING = 'FALCON'


class BrancherCreateError(ValueError):
    """Raised when a brancher_create pre-create guardrail rejects the call."""


async def create_brancher_node(
    client: HypernodeApiClient,
    appname: str,
    labels: list[str],
    clear_services: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Brancher node for `appname` and return its node name."""
    if not labels:
        raise BrancherCreateError('At least one label is required to create a Brancher node.')

    app_info = await client.get(appname, '')

    product = app_info.get('product') or {}
    plan_code = str(product.get('code', ''))
    if FALCONS_PLAN_SUBSTRING not in plan_code.upper():
        raise BrancherCreateError(
            f"App '{appname}' is not on a Falcons-eligible plan (Brancher requires Falcons). "
            f'Current plan: {plan_code or "unknown"}.'
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
        # No verified API source for a "minutes remaining" figure -- see the
        # module-level comment above. Always None until one is found.
        'minutes_remaining': None,
    }
