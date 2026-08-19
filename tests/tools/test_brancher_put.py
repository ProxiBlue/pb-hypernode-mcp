"""Tests for the brancher_put tool."""

from __future__ import annotations

import asyncio
import shlex
from unittest.mock import AsyncMock

import pytest

from pb_hypernode_mcp.tools._guards import InvalidNodeNameError
from pb_hypernode_mcp.tools.brancher_put import SyncError, put_files


class FakeProcess:
    def __init__(self, returncode: int, stdout: bytes = b'', stderr: bytes = b'') -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def make_runner(process: FakeProcess) -> AsyncMock:
    return AsyncMock(return_value=process)


async def test_it_syncs_a_local_file_to_the_target_path_on_a_valid_eph_node() -> None:
    runner = make_runner(FakeProcess(returncode=0, stdout=b'sent 100 bytes'))

    result = await put_files(
        'pps-eph123456',
        '/local/file.txt',
        '/remote/file.txt',
        run_subprocess=runner,
    )

    runner.assert_awaited_once()
    assert runner.await_args is not None
    args = runner.await_args.args
    assert args[0] == 'rsync'
    assert '/local/file.txt' in args
    assert 'pps-eph123456@pps-eph123456.hypernode.io:/remote/file.txt' in args

    assert result == {
        'node_name': 'pps-eph123456',
        'local_path': '/local/file.txt',
        'remote_path': '/remote/file.txt',
        'stdout': 'sent 100 bytes',
    }


async def test_it_syncs_a_local_directory_recursively_to_a_valid_eph_node() -> None:
    runner = make_runner(FakeProcess(returncode=0, stdout=b'sent 4 files'))

    result = await put_files(
        'pps-eph123456',
        '/local/app/',
        '/remote/app/',
        run_subprocess=runner,
    )

    runner.assert_awaited_once()
    assert runner.await_args is not None
    args = runner.await_args.args
    assert args[0] == 'rsync'
    assert '-az' in args
    assert '/local/app/' in args
    assert 'pps-eph123456@pps-eph123456.hypernode.io:/remote/app/' in args
    assert result['stdout'] == 'sent 4 files'


async def test_it_rejects_the_sync_when_the_target_hostname_does_not_match_the_eph_pattern() -> (
    None
):
    runner = AsyncMock()

    with pytest.raises(InvalidNodeNameError, match='pps'):
        await put_files('pps', '/local/file.txt', '/remote/file.txt', run_subprocess=runner)

    runner.assert_not_awaited()


async def test_it_rejects_a_remote_path_containing_shell_metacharacters_from_reaching_an_unescaped_rsync_destination_string() -> (  # noqa: E501
    None
):
    runner = make_runner(FakeProcess(returncode=0, stdout=b'sent 1 file'))
    malicious_remote_path = '/remote/`rm -rf /`; touch /tmp/pwned'

    await put_files(
        'pps-eph123456',
        '/local/file.txt',
        malicious_remote_path,
        run_subprocess=runner,
    )

    runner.assert_awaited_once()
    assert runner.await_args is not None
    args = runner.await_args.args

    expected_destination = (
        f'pps-eph123456@pps-eph123456.hypernode.io:{shlex.quote(malicious_remote_path)}'
    )
    assert expected_destination in args

    # The raw, unescaped metacharacters must never appear as their own argv
    # entry (i.e. never unescaped-concatenated into the destination string).
    raw_destination = f'pps-eph123456@pps-eph123456.hypernode.io:{malicious_remote_path}'
    assert raw_destination not in args


async def test_it_passes_protect_args_to_rsync_so_the_remote_shell_never_re_parses_the_path_argument() -> (  # noqa: E501
    None
):
    runner = make_runner(FakeProcess(returncode=0, stdout=b'sent 1 file'))

    await put_files(
        'pps-eph123456',
        '/local/file.txt',
        '/remote/file.txt',
        run_subprocess=runner,
    )

    runner.assert_awaited_once()
    assert runner.await_args is not None
    args = runner.await_args.args
    assert '--protect-args' in args


async def test_it_hardens_the_rsh_ssh_invocation_against_a_hanging_host_key_prompt() -> None:
    runner = make_runner(FakeProcess(returncode=0, stdout=b'sent 1 file'))

    await put_files(
        'pps-eph123456',
        '/local/file.txt',
        '/remote/file.txt',
        run_subprocess=runner,
    )

    runner.assert_awaited_once()
    assert runner.await_args is not None
    args = runner.await_args.args
    rsh_index = args.index('--rsh') + 1
    rsh_value = args[rsh_index]
    assert 'BatchMode=yes' in rsh_value
    assert 'StrictHostKeyChecking=accept-new' in rsh_value
    assert 'ConnectTimeout=' in rsh_value

    kwargs = runner.await_args.kwargs
    assert kwargs['stdin'] == asyncio.subprocess.DEVNULL


async def test_it_propagates_sync_failures_as_a_clear_error() -> None:
    runner = make_runner(
        FakeProcess(returncode=23, stderr=b'rsync: connection unexpectedly closed')
    )

    with pytest.raises(SyncError, match='rsync: connection unexpectedly closed'):
        await put_files(
            'pps-eph123456',
            '/local/file.txt',
            '/remote/file.txt',
            run_subprocess=runner,
        )
