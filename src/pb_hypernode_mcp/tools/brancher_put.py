"""brancher_put MCP tool.

Syncs local files/directories to a Brancher node over rsync, for the case
where a client wants to push local code changes onto the node rather than
having changes made in place over SSH. Relies on the caller's local SSH
agent/keys, the same connection model as `brancher_exec`.
"""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Callable, Coroutine
from typing import Any

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.tools._guards import validate_eph_node_name

SSH_PORT = 22

# Signature-compatible with `asyncio.create_subprocess_exec`: accepts the
# program + args plus `stdout`/`stderr` kwargs, returns an awaited process
# object exposing `.returncode` and an async `.communicate()`.
SubprocessRunner = Callable[..., Coroutine[Any, Any, Any]]


class SyncError(Exception):
    """Raised when the rsync subprocess exits with a non-zero status."""


async def put_files(
    node_name: str,
    local_path: str,
    remote_path: str,
    *,
    port: int = SSH_PORT,
    run_subprocess: SubprocessRunner | None = None,
) -> dict[str, Any]:
    """Sync `local_path` to `remote_path` on `node_name` via rsync."""
    validate_eph_node_name(node_name)

    runner = run_subprocess if run_subprocess is not None else asyncio.create_subprocess_exec

    # `remote_path` is interpolated into a single `user@host:path` argv entry
    # that rsync forwards to the remote side, where it is historically prone
    # to being re-split/re-interpreted by a remote shell if it contains shell
    # metacharacters (backticks, `;`, etc). `--protect-args` (`-s`) tells
    # rsync to pass arguments through unmodified instead of constructing a
    # remote command line for a shell to parse; `shlex.quote()` on
    # `remote_path` is defense-in-depth on top of that, in case `--rsh`
    # behaviour or `--protect-args` semantics ever change.
    destination = f'{node_name}@{node_name}.hypernode.io:{shlex.quote(remote_path)}'
    command = [
        'rsync',
        '-az',
        '--protect-args',
        '--rsh',
        f'ssh -p {port}',
        local_path,
        destination,
    ]

    process = await runner(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise SyncError(
            f'rsync to {node_name!r} failed (exit code {process.returncode}): '
            f'{stderr.decode().strip()}'
        )

    return {
        'node_name': node_name,
        'local_path': local_path,
        'remote_path': remote_path,
        'stdout': stdout.decode().strip(),
    }


def register(server: FastMCP) -> None:
    """Register the `brancher_put` tool on `server`.

    No `HypernodeApiClient` is needed — `put_files` talks to the node
    directly over rsync/ssh, the same connection model as `brancher_exec`.
    """

    @server.tool(name='brancher_put')
    async def brancher_put(
        node_name: str,
        local_path: str,
        remote_path: str,
        port: int = SSH_PORT,
    ) -> dict[str, Any]:
        """Sync `local_path` to `remote_path` on a Brancher node via rsync."""
        return await put_files(node_name, local_path, remote_path, port=port)
