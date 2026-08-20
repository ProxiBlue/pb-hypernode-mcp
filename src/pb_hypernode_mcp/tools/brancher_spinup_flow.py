"""Orchestrates the full Brancher spin-up flow: create -> wait -> sanitize -> report ready.

This is the non-bypassable glue between `create_brancher_node` (internal-only,
`tools/brancher_create.py`), the SSH-reachability wait, and task 009's
sanitization command generation. A caller of `spinup_sanitized_brancher_node`
can never observe a node as "ready" (nor obtain its access URL) until every
sanitization command has run successfully against it — there is no flag or
opt-out.

`register()` below exposes this flow as the `brancher_create` MCP tool name.
This is the ONLY node-creation tool registered on the server (task 017,
security remediation) — `create_brancher_node` itself is never
independently registered, so there is no way for an external caller to
create a Brancher node that skips sanitization.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import load_settings
from pb_hypernode_mcp.sanitization.commands import (
    generate_sanitization_commands,
    generate_url_setup_commands,
)
from pb_hypernode_mcp.sanitization.config import (
    DEFAULT_MAGENTO_SANITIZATION_CONFIG,
    SanitizationConfig,
)
from pb_hypernode_mcp.tools.brancher_create import create_brancher_node
from pb_hypernode_mcp.tools.brancher_exec import exec_command as default_exec_command
from pb_hypernode_mcp.tools.brancher_list import list_brancher_nodes

ExecCommandFn = Callable[..., Awaitable[dict[str, Any]]]
SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]
ClientFactory = Callable[[], HypernodeApiClient]

DEFAULT_READY_PROBE_COMMAND = 'echo ready'
DEFAULT_REACHABILITY_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_REACHABILITY_TIMEOUT_SECONDS = 1200.0

# VERIFIED (2026-08-20) against a real Brancher node: `hypernode-manage-vhosts
# --https` does a live Let's Encrypt ACME challenge/cert-issuance round trip
# against an external CA -- a cold run (fresh account registration, fresh
# per-domain authorization) exceeded 20s; `exec_command`'s own default (30s)
# leaves too little margin. This is well within the overall ~20min spin-up
# budget, so a generous per-command timeout costs little.
DEFAULT_SANITIZATION_COMMAND_TIMEOUT_SECONDS = 120.0

ACCESS_URL_TEMPLATE = 'https://{node_name}.hypernode.io/'

# Real Magento CLI command (`Magento\Backend\Console\Command\InfoAdminUriCommand`)
# that prints the app's current admin path — used only for reporting, never
# a sanitization-critical step, so a failure/unexpected-output here falls
# back to Magento's own out-of-the-box default rather than blocking spin-up.
ADMIN_URI_COMMAND = 'bin/magento info:adminuri'
DEFAULT_ADMIN_PATH = '/admin'
_ADMIN_PATH_PATTERN = re.compile(r'(/\S+)')


class BrancherSpinupError(Exception):
    """Base class for failures during the create -> wait -> sanitize spin-up flow."""


class NodeIpNeverAssignedError(BrancherSpinupError):
    """Raised when Hypernode never assigns the node an ip within the configured timeout.

    This is phase 1 of the reachability wait (task 022) — a plain REST poll
    against the Brancher list endpoint, no SSH involved. Timing out here
    means Hypernode's own provisioning stalled; it is deliberately a
    different exception than `NodeUnreachableTimeoutError` so a caller can
    tell "their infra never gave us a host" apart from "we had a host but
    SSH never answered" without inspecting message text.
    """

    def __init__(self, node_name: str, timeout: float) -> None:
        self.node_name = node_name
        self.timeout = timeout
        super().__init__(
            f'Brancher node {node_name!r} was never assigned an IP address within '
            f'{timeout}s -- this is '
            "Hypernode's own provisioning, not an SSH/config issue on this plugin's side."
        )


class NodeUnreachableTimeoutError(BrancherSpinupError):
    """Raised when the node never becomes SSH-reachable within the configured timeout.

    Phase 2 of the reachability wait (task 022) — only reached once
    `NodeIpNeverAssignedError` could no longer apply (the node already has an
    ip). A timeout here means the ip was assigned but SSH itself never
    answered — possibly our SSH config, or sshd still starting on the node.
    """


class SanitizationFailedError(BrancherSpinupError):
    """Raised when a sanitization command fails partway through the sequence.

    Carries the failing command and how many commands completed successfully
    before it, so callers can report a precise failure state rather than a
    generic error. Deliberately does NOT carry the node's access URL — a
    caller catching this exception has no way to accidentally surface it.
    """

    def __init__(self, node_name: str, command: str, commands_completed: int) -> None:
        self.node_name = node_name
        self.command = command
        self.commands_completed = commands_completed
        super().__init__(
            f'Sanitization failed on Brancher node {node_name!r} while running '
            f'{command!r} ({commands_completed} prior command(s) succeeded). '
            'The node is NOT ready and its access URL is being withheld.'
        )


async def _wait_for_ip_assignment(
    node_name: str,
    appname: str,
    *,
    client: HypernodeApiClient,
    poll_interval: float,
    timeout: float,
    sleep: SleepFn,
    clock: ClockFn,
) -> float:
    """Poll the Brancher list endpoint until `node_name` has a non-null `ip`.

    Phase 1 of the reachability wait (task 022): a plain REST call, no SSH
    involved, so it can run from the moment the node is created rather than
    hammering SSH against a host that doesn't exist yet. Returns the number
    of seconds elapsed before the ip was assigned, for reporting.
    """
    start = clock()
    deadline = start + timeout

    while True:
        nodes = await list_brancher_nodes(appname, client=client)
        node = next((candidate for candidate in nodes if candidate['name'] == node_name), None)

        if node is not None and node.get('ip'):
            return clock() - start

        if clock() >= deadline:
            raise NodeIpNeverAssignedError(node_name, timeout)

        await sleep(poll_interval)


async def _wait_until_reachable(
    node_name: str,
    *,
    exec_command: ExecCommandFn,
    probe_command: str,
    poll_interval: float,
    timeout: float,
    sleep: SleepFn,
    clock: ClockFn,
) -> None:
    """Poll `node_name` with `probe_command` until it succeeds or `timeout` elapses."""
    deadline = clock() + timeout

    while True:
        try:
            await exec_command(node_name, probe_command)

            return
        except Exception:
            if clock() >= deadline:
                raise NodeUnreachableTimeoutError(
                    f'Brancher node {node_name!r} did not become SSH-reachable within {timeout}s.'
                ) from None

            await sleep(poll_interval)


async def _resolve_admin_path(node_name: str, *, exec_command: ExecCommandFn) -> str:
    """Best-effort: parse the app's actual admin path via `bin/magento info:adminuri`.

    Purely informational (never blocks or fails spin-up) — this runs after
    sanitization has already fully succeeded, so a wrong/missing admin path
    only means a slightly-off `admin_url` in the report, never a withheld
    access URL or an unsanitized node.
    """
    try:
        result = await exec_command(node_name, ADMIN_URI_COMMAND)
    except Exception:
        return DEFAULT_ADMIN_PATH

    match = _ADMIN_PATH_PATTERN.search(result.get('stdout', ''))

    return match.group(1) if match else DEFAULT_ADMIN_PATH


async def spinup_sanitized_brancher_node(
    client: HypernodeApiClient,
    appname: str,
    labels: list[str],
    clear_services: list[str] | None = None,
    *,
    sanitization_config: SanitizationConfig = DEFAULT_MAGENTO_SANITIZATION_CONFIG,
    exec_command: ExecCommandFn = default_exec_command,
    ready_probe_command: str = DEFAULT_READY_PROBE_COMMAND,
    reachability_poll_interval: float = DEFAULT_REACHABILITY_POLL_INTERVAL_SECONDS,
    reachability_timeout: float = DEFAULT_REACHABILITY_TIMEOUT_SECONDS,
    sanitization_command_timeout: float = DEFAULT_SANITIZATION_COMMAND_TIMEOUT_SECONDS,
    sleep: SleepFn = asyncio.sleep,
    clock: ClockFn = time.monotonic,
) -> dict[str, Any]:
    """Create a Brancher node, wait for it, sanitize it, and only then report it ready.

    The wait itself is two explicit, separately-timed phases (task 022):
    phase 1 polls the Brancher list endpoint (no SSH) until Hypernode
    assigns the node a real `ip`; phase 2 then polls SSH reachability, using
    whatever's left of `reachability_timeout` after phase 1 -- the two
    phases together never exceed that one configured ceiling. Both
    durations are surfaced in the returned dict on success so a caller can
    report exactly where the time went, not just a bare "ready".
    """
    created = await create_brancher_node(
        client,
        appname,
        labels,
        clear_services,
    )
    node_name = created['node_name']

    ip_assigned_after_seconds = await _wait_for_ip_assignment(
        node_name,
        appname,
        client=client,
        poll_interval=reachability_poll_interval,
        timeout=reachability_timeout,
        sleep=sleep,
        clock=clock,
    )

    remaining_timeout = reachability_timeout - ip_assigned_after_seconds
    ssh_wait_start = clock()

    await _wait_until_reachable(
        node_name,
        exec_command=exec_command,
        probe_command=ready_probe_command,
        poll_interval=reachability_poll_interval,
        timeout=remaining_timeout,
        sleep=sleep,
        clock=clock,
    )
    ssh_reachable_after_seconds = clock() - ssh_wait_start

    access_url = ACCESS_URL_TEMPLATE.format(node_name=node_name)
    hostname = f'{node_name}.hypernode.io'

    # URL/vhost setup commands run FIRST and share the exact same
    # all-must-succeed-or-nothing-is-reported-ready discipline as the PII
    # sanitization commands below (same loop, same SanitizationFailedError) —
    # a node whose base URL/vhost never got wired is just as unfit to hand
    # back as one whose PII was never anonymized.
    commands = generate_url_setup_commands(
        hostname, sanitization_config
    ) + generate_sanitization_commands(sanitization_config)

    for index, command in enumerate(commands):
        result = await exec_command(node_name, command, timeout=sanitization_command_timeout)
        if result.get('exit_code') != 0:
            raise SanitizationFailedError(node_name, command, index)

    admin_path = await _resolve_admin_path(node_name, exec_command=exec_command)

    return {
        'node_name': node_name,
        'minutes_remaining': created.get('minutes_remaining'),
        'access_url': access_url,
        'admin_url': f'{access_url.rstrip("/")}{admin_path}',
        'admin_username': sanitization_config.admin_reset_username,
        'admin_email': sanitization_config.admin_reset_email,
        'admin_password_note': (
            'Password deliberately invalidated during sanitization -- set a real '
            'one with `bin/magento admin:user:create` before logging in.'
        ),
        'status': 'ready',
        'sanitization_commands_run': len(commands),
        'sales_and_customer_data_sanitized': True,
        'ip_assigned_after_seconds': ip_assigned_after_seconds,
        'ssh_reachable_after_seconds': ssh_reachable_after_seconds,
    }


def register(
    server: FastMCP,
    client_factory: ClientFactory | None = None,
    *,
    sanitization_config: SanitizationConfig = DEFAULT_MAGENTO_SANITIZATION_CONFIG,
    exec_command: ExecCommandFn = default_exec_command,
    ready_probe_command: str = DEFAULT_READY_PROBE_COMMAND,
    reachability_poll_interval: float = DEFAULT_REACHABILITY_POLL_INTERVAL_SECONDS,
    reachability_timeout: float = DEFAULT_REACHABILITY_TIMEOUT_SECONDS,
    sanitization_command_timeout: float = DEFAULT_SANITIZATION_COMMAND_TIMEOUT_SECONDS,
    sleep: SleepFn = asyncio.sleep,
    clock: ClockFn = time.monotonic,
) -> None:
    """Register the `brancher_create` tool on `server`.

    Wraps `spinup_sanitized_brancher_node` as a single callable MCP tool,
    exposed under the `brancher_create` name so this is the ONE and ONLY
    externally-callable node-creation entry point — there is no separate,
    unsanitized `brancher_create` tool anywhere else in this codebase (see
    `tools/brancher_create.py`'s `create_brancher_node`, which stays an
    internal-only function, never independently registered as an MCP tool).
    Every call therefore runs create -> wait -> sanitize -> report-ready in
    one non-bypassable sequence; `client_factory` mirrors
    `create_brancher_node`'s dependency shape, and the remaining
    keyword-only params default to production behaviour and exist so tests
    can inject fakes.
    """

    def default_factory() -> HypernodeApiClient:
        return HypernodeApiClient(load_settings())

    factory = client_factory if client_factory is not None else default_factory

    @server.tool(name='brancher_create')
    async def brancher_create(
        appname: str,
        labels: list[str],
        clear_services: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a Brancher node, wait for it, sanitize it, and report it ready."""
        client = factory()

        return await spinup_sanitized_brancher_node(
            client,
            appname,
            labels,
            clear_services,
            sanitization_config=sanitization_config,
            exec_command=exec_command,
            ready_probe_command=ready_probe_command,
            reachability_poll_interval=reachability_poll_interval,
            reachability_timeout=reachability_timeout,
            sanitization_command_timeout=sanitization_command_timeout,
            sleep=sleep,
            clock=clock,
        )
