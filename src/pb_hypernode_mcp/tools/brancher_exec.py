"""brancher_exec MCP tool.

Executes a shell command on a Brancher node over SSH by shelling out to the
system `ssh` binary. Relies on the caller's already-configured local SSH
agent/keys — this module never handles key material itself.

This is the single safety-critical chokepoint of the "change-it" layer: the
`-eph` node-name guard from `_guards` is enforced before any subprocess is
spawned, so it is structurally impossible to point this tool at a
production host.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.tools._guards import HYPERNODE_SSH_USER, validate_eph_node_name

DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0

SSH_PORT = 22

# Connect-phase timeout distinct from the overall command timeout below — caps
# how long the TCP+SSH handshake itself may take before ssh gives up.
SSH_CONNECT_TIMEOUT_SECONDS = 10

# ssh(1) reserves exit code 255 for its own connection/authentication
# failures, distinct from the remote command's exit code (0-254). Surface it
# as a clear `SshConnectionError` instead of a normal `exit_code: 255` result.
SSH_CONNECTION_FAILURE_EXIT_CODE = 255


class SshConnectionError(Exception):
    """Raised when the ssh subprocess itself fails to connect/authenticate."""


class SshCommandTimeoutError(Exception):
    """Raised when a command does not complete within the configured timeout."""


async def exec_command(
    node_name: str,
    command: str,
    *,
    timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run `command` on Brancher node `node_name` over SSH and return its result.

    Returns `{stdout, stderr, exit_code}`. `node_name` must match the `-eph`
    Brancher naming pattern — this is validated BEFORE any SSH connection is
    attempted.
    """
    validate_eph_node_name(node_name)

    host = f'{node_name}.hypernode.io'
    user = HYPERNODE_SSH_USER

    # BatchMode=yes + stdin=DEVNULL: without these, a host-key prompt on a
    # never-before-seen node would block reading from this process's stdin —
    # which, under the MCP server's stdio transport, is the live JSON-RPC
    # pipe and never reaches EOF, so the prompt would hang until the
    # asyncio.wait_for timeout below kills it. StrictHostKeyChecking=accept-new
    # auto-trusts a first-seen host key (expected for a freshly created
    # Brancher node) without silently ignoring a *changed* key on a reused
    # hostname.
    process = await asyncio.create_subprocess_exec(
        'ssh',
        '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=accept-new',
        '-o', f'ConnectTimeout={SSH_CONNECT_TIMEOUT_SECONDS}',
        f'{user}@{host}',
        command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise SshCommandTimeoutError(
            f'Command on Brancher node {node_name!r} exceeded the {timeout}s timeout.'
        ) from exc

    stdout = stdout_bytes.decode()
    stderr = stderr_bytes.decode()

    if process.returncode == SSH_CONNECTION_FAILURE_EXIT_CODE:
        raise SshConnectionError(
            f'ssh failed to connect to Brancher node {node_name!r}: {stderr.strip()}'
        )

    return {
        'stdout': stdout,
        'stderr': stderr,
        'exit_code': process.returncode,
    }


def register(server: FastMCP) -> None:
    """Register the `brancher_exec` tool on `server`."""

    @server.tool(name='brancher_exec')
    async def brancher_exec(
        node_name: str,
        command: str,
        timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Execute `command` on a Brancher node over SSH; return stdout/stderr/exit_code."""
        return await exec_command(node_name, command, timeout=timeout)
