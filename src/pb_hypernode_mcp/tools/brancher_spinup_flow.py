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
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import load_settings
from pb_hypernode_mcp.sanitization.commands import generate_sanitization_commands
from pb_hypernode_mcp.sanitization.config import (
    DEFAULT_MAGENTO_SANITIZATION_CONFIG,
    SanitizationConfig,
)
from pb_hypernode_mcp.tools.brancher_create import create_brancher_node
from pb_hypernode_mcp.tools.brancher_exec import exec_command as default_exec_command

ExecCommandFn = Callable[..., Awaitable[dict[str, Any]]]
SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]
ClientFactory = Callable[[], HypernodeApiClient]

DEFAULT_READY_PROBE_COMMAND = 'echo ready'
DEFAULT_REACHABILITY_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_REACHABILITY_TIMEOUT_SECONDS = 300.0

ACCESS_URL_TEMPLATE = 'https://{node_name}.hypernode.io/'


class BrancherSpinupError(Exception):
    """Base class for failures during the create -> wait -> sanitize spin-up flow."""


class NodeUnreachableTimeoutError(BrancherSpinupError):
    """Raised when the node never becomes SSH-reachable within the configured timeout."""


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
    sleep: SleepFn = asyncio.sleep,
    clock: ClockFn = time.monotonic,
) -> dict[str, Any]:
    """Create a Brancher node, wait for it, sanitize it, and only then report it ready."""
    created = await create_brancher_node(
        client,
        appname,
        labels,
        clear_services,
    )
    node_name = created['node_name']

    await _wait_until_reachable(
        node_name,
        exec_command=exec_command,
        probe_command=ready_probe_command,
        poll_interval=reachability_poll_interval,
        timeout=reachability_timeout,
        sleep=sleep,
        clock=clock,
    )

    commands = generate_sanitization_commands(sanitization_config)

    for index, command in enumerate(commands):
        result = await exec_command(node_name, command)
        if result.get('exit_code') != 0:
            raise SanitizationFailedError(node_name, command, index)

    return {
        'node_name': node_name,
        'minutes_remaining': created.get('minutes_remaining'),
        'access_url': ACCESS_URL_TEMPLATE.format(node_name=node_name),
        'status': 'ready',
        'sanitization_commands_run': len(commands),
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
            sleep=sleep,
            clock=clock,
        )
