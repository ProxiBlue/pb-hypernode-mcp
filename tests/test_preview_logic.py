"""Tests for `preview_logic` — the pure/async helpers backing the brancher-preview skill."""

from __future__ import annotations

from typing import Any

from pb_hypernode_mcp.preview_logic import (
    apply_local_change,
    cleanup_reminder,
    run_build_sequence,
)


async def test_it_applies_a_local_change_to_the_node_via_brancher_put_given_a_local_path() -> None:
    """Requirement: it applies a local file change to the node via brancher_put when given a
    local path."""
    calls: list[tuple[str, str, str]] = []

    async def fake_put_files(node_name: str, local_path: str, remote_path: str) -> dict[str, Any]:
        calls.append((node_name, local_path, remote_path))

        return {'node_name': node_name, 'local_path': local_path, 'remote_path': remote_path}

    result = await apply_local_change(
        'myapp-eph1',
        '/local/app/code/Uptactics/Foo/Model/Bar.php',
        '/data/web/public/app/code/Uptactics/Foo/Model/Bar.php',
        put_files=fake_put_files,
    )

    assert calls == [
        (
            'myapp-eph1',
            '/local/app/code/Uptactics/Foo/Model/Bar.php',
            '/data/web/public/app/code/Uptactics/Foo/Model/Bar.php',
        ),
    ]
    assert result['node_name'] == 'myapp-eph1'


async def test_it_runs_the_magento_build_sequence_after_changes_are_applied() -> None:
    executed: list[str] = []

    async def fake_exec_command(node_name: str, command: str) -> dict[str, Any]:
        executed.append(command)

        return {'stdout': '', 'stderr': '', 'exit_code': 0}

    result = await run_build_sequence(
        'myapp-eph1',
        ['app/code/Uptactics/Foo/etc/db_schema.xml'],
        exec_command=fake_exec_command,
    )

    assert executed == ['bin/magento cache:flush', 'bin/magento setup:upgrade']
    assert result['commands'] == executed
    assert all(entry['exit_code'] == 0 for entry in result['results'])


def test_it_reminds_the_user_the_node_is_still_running_and_consuming_minutes() -> None:
    """Requirement: it reminds the user the node is still running and consuming minutes after
    the loop completes."""
    message = cleanup_reminder('myapp-eph1', 'https://myapp-eph1.hypernode.io/')

    assert 'myapp-eph1' in message
    assert 'still running' in message
    assert 'minutes' in message
