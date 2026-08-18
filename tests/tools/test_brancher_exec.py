"""Tests for the brancher_exec tool."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pb_hypernode_mcp.tools._guards import InvalidNodeNameError
from pb_hypernode_mcp.tools.brancher_exec import (
    SshCommandTimeoutError,
    SshConnectionError,
    exec_command,
)


class FakeProcess:
    """Stand-in for `asyncio.subprocess.Process` used to mock ssh subprocess calls."""

    def __init__(
        self,
        stdout: bytes = b'',
        stderr: bytes = b'',
        returncode: int = 0,
        communicate_delay: float | None = None,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self._communicate_delay = communicate_delay
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._communicate_delay is not None:
            await asyncio.sleep(self._communicate_delay)
        return self.stdout, self.stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> None:
        self.waited = True


def patch_subprocess_exec(process: FakeProcess, **kwargs: Any):
    mock_create = AsyncMock(return_value=process, **kwargs)
    return patch(
        'pb_hypernode_mcp.tools.brancher_exec.asyncio.create_subprocess_exec',
        mock_create,
    )


async def test_it_executes_a_command_on_a_valid_eph_node_and_returns_stdout_stderr_exit_code() -> (
    None
):
    process = FakeProcess(stdout=b'lucas\n', stderr=b'', returncode=0)

    with patch_subprocess_exec(process) as mock_create:
        result = await exec_command('pps-eph123456', 'whoami')

    mock_create.assert_awaited_once_with(
        'ssh',
        'pps-eph123456@pps-eph123456.hypernode.io',
        'whoami',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert result == {
        'stdout': 'lucas\n',
        'stderr': '',
        'exit_code': 0,
    }


@pytest.mark.parametrize(
    'node_name',
    [
        'pps',
        'pps.hypernode.io',
        'pps-staging',
        'pps-staging.hypernode.io',
    ],
)
async def test_it_rejects_execution_against_a_hostname_not_matching_the_eph_pattern(
    node_name: str,
) -> None:
    process = FakeProcess()

    with patch_subprocess_exec(process) as mock_create:
        with pytest.raises(InvalidNodeNameError, match='eph'):
            await exec_command(node_name, 'whoami')

    mock_create.assert_not_awaited()


async def test_it_propagates_ssh_connection_failures_as_a_clear_error_rather_than_swallowing_them():
    process = FakeProcess(
        stdout=b'',
        stderr=b'ssh: connect to host pps-eph123456.hypernode.io port 22: Connection refused',
        returncode=255,
    )

    with patch_subprocess_exec(process):
        with pytest.raises(SshConnectionError, match='Connection refused'):
            await exec_command('pps-eph123456', 'whoami')


async def test_it_rejects_execution_against_a_bare_appname_with_no_eph_suffix() -> None:
    process = FakeProcess()

    with patch_subprocess_exec(process) as mock_create:
        with pytest.raises(InvalidNodeNameError, match='pps'):
            await exec_command('pps', 'whoami')

    mock_create.assert_not_awaited()


async def test_it_respects_a_configurable_command_timeout() -> None:
    process = FakeProcess(communicate_delay=10.0)

    with patch_subprocess_exec(process):
        with pytest.raises(SshCommandTimeoutError, match='0.05'):
            await exec_command('pps-eph123456', 'sleep 100', timeout=0.05)

    assert process.killed is True
    assert process.waited is True
