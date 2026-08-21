"""Tests for the pb_hypernode_mcp MCP server entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.message import SessionMessage

from pb_hypernode_mcp.server import create_server


class FakeApiClient:
    """Stand-in for `HypernodeApiClient`, counting how many times it is built."""

    instances = 0

    def __init__(self, settings: Any) -> None:  # noqa: ANN401 - mirrors HypernodeApiClient
        FakeApiClient.instances += 1
        self._settings = settings

    async def get(
        self, appname: str, path: str, *, token_appname: str | None = None
    ) -> dict[str, Any]:
        return {
            'product': {'code': 'FALCON_S_202603DEV'},
            'ip': '203.0.113.10',
        }

    async def post(
        self,
        appname: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        token_appname: str | None = None,
    ) -> dict[str, Any]:
        return {'name': 'myapp-eph1'}

    async def delete(
        self, appname: str, path: str, *, token_appname: str | None = None
    ) -> dict[str, Any]:
        return {}

    async def get_path(self, path: str, *, token_appname: str) -> dict[str, Any]:
        return {
            'branchers': [
                {'name': 'myapp-eph1', 'elapsed_time': 300, 'ip': '203.0.113.10'},
            ],
        }

    async def post_path(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        token_appname: str,
    ) -> dict[str, Any]:
        return {'name': 'myapp-eph1'}

    async def delete_path(self, path: str, *, token_appname: str) -> dict[str, Any]:
        return {}


class FakeSubprocess:
    """Stand-in for a subprocess used by brancher_exec / brancher_put."""

    def __init__(self, stdout: bytes = b'ok\n', stderr: bytes = b'', returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.stdout, self.stderr


async def test_it_starts_the_mcp_server_over_stdio_transport_without_error() -> None:
    server = create_server()

    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](1)

    @asynccontextmanager
    async def fake_stdio_server():
        async with client_to_server_receive, server_to_client_send:
            yield client_to_server_receive, server_to_client_send

    server_errors: list[BaseException] = []

    async def run_server() -> None:
        try:
            await server.run_stdio_async()
        except anyio.get_cancelled_exc_class():
            raise  # expected shutdown once the test cancels the task group
        except BaseException as exc:  # noqa: BLE001 - captured for assertion, never swallowed silently
            server_errors.append(exc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr('mcp.server.fastmcp.server.stdio_server', fake_stdio_server)

        async with anyio.create_task_group() as tg:
            tg.start_soon(run_server)

            async with ClientSession(
                read_stream=server_to_client_receive,
                write_stream=client_to_server_send,
            ) as client:
                await client.initialize()

            tg.cancel_scope.cancel()

    assert server_errors == []


async def test_it_registers_a_tool_via_the_tool_registry_and_the_server_reports_it_in_its_tool_list() -> (  # noqa: E501
    None
):
    server = create_server()

    @server.tool(name='ping')
    def ping() -> str:
        return 'pong'

    tools = await server.list_tools()

    assert 'ping' in [tool.name for tool in tools]


async def test_it_rejects_a_tool_call_for_an_unregistered_tool_name_with_a_clear_error() -> None:
    server = create_server()

    with pytest.raises(ToolError, match='nonexistent_tool'):
        await server.call_tool('nonexistent_tool', {})


async def test_it_exposes_brancher_create_as_a_callable_mcp_tool_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`brancher_create` is wired to the fully-gated create->wait->sanitize->ready flow.

    There is no separate, unsanitized creation tool (task 017 security
    remediation) — calling `brancher_create` always runs the full sequence,
    which requires an SSH-reachable node, hence the subprocess mock below.
    """
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')
    monkeypatch.setattr('pb_hypernode_mcp.server.HypernodeApiClient', FakeApiClient)

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeSubprocess:
        # `_resolve_admin_path` retries on unparseable stdout (not just a
        # raised exception) -- the default 'ok\n' stdout never parses for
        # `n98-magerun2 info:adminuri`, which would otherwise exhaust every
        # retry with a REAL asyncio.sleep() in tests that don't inject a
        # fake `sleep`, silently costing tens of seconds per test.
        if any('info:adminuri' in str(arg) for arg in args):
            return FakeSubprocess(stdout=b'Admin URI: /admin\n')

        return FakeSubprocess()

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_exec.asyncio.create_subprocess_exec',
        fake_create_subprocess_exec,
    )

    async def fake_sleep(seconds: float) -> None:
        # `_resolve_admin_path` sleeps a settle delay before its first read
        # (reinstated 2026-08-21 -- see its docstring) -- even the happy
        # path needs that wait, which would otherwise be a REAL
        # asyncio.sleep() in tests that don't inject a fake `sleep`.
        return None

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_spinup_flow.asyncio.sleep',
        fake_sleep,
    )

    server = create_server()

    tools = await server.list_tools()
    assert 'brancher_create' in [tool.name for tool in tools]

    _content, result = await server.call_tool(
        'brancher_create', {'appname': 'myapp', 'labels': ['ticket-123']}
    )

    assert isinstance(result, dict)
    assert result.pop('ip_assigned_after_seconds') >= 0
    assert result.pop('ssh_reachable_after_seconds') >= 0
    assert result.pop('preview_basic_auth_password')
    assert result.pop('preview_admin_password')
    assert result == {
        'node_name': 'myapp-eph1',
        'minutes_remaining': None,
        'access_url': 'https://myapp-eph1.hypernode.io/',
        'admin_url': 'https://myapp-eph1.hypernode.io/admin',
        'admin_username': 'admin',
        'admin_email': 'admin@example.invalid',
        'admin_password_note': (
            "Password deliberately invalidated during sanitization -- this account "
            "(the sanitized original) is intentionally locked out; use "
            "preview_admin_username/preview_admin_password below to log in instead."
        ),
        'preview_basic_auth_username': 'preview',
        'preview_admin_username': 'preview',
        'status': 'ready',
        'sanitization_commands_run': 36,
        'sales_and_customer_data_sanitized': True,
    }


async def test_it_does_not_expose_a_way_to_create_a_brancher_node_that_skips_sanitization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')
    monkeypatch.setattr('pb_hypernode_mcp.server.HypernodeApiClient', FakeApiClient)

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeSubprocess:
        # `_resolve_admin_path` retries on unparseable stdout (not just a
        # raised exception) -- the default 'ok\n' stdout never parses for
        # `n98-magerun2 info:adminuri`, which would otherwise exhaust every
        # retry with a REAL asyncio.sleep() in tests that don't inject a
        # fake `sleep`, silently costing tens of seconds per test.
        if any('info:adminuri' in str(arg) for arg in args):
            return FakeSubprocess(stdout=b'Admin URI: /admin\n')

        return FakeSubprocess()

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_exec.asyncio.create_subprocess_exec',
        fake_create_subprocess_exec,
    )

    async def fake_sleep(seconds: float) -> None:
        # `_resolve_admin_path` sleeps a settle delay before its first read
        # (reinstated 2026-08-21 -- see its docstring) -- even the happy
        # path needs that wait, which would otherwise be a REAL
        # asyncio.sleep() in tests that don't inject a fake `sleep`.
        return None

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_spinup_flow.asyncio.sleep',
        fake_sleep,
    )

    server = create_server()

    tools = await server.list_tools()
    tool_names = [tool.name for tool in tools]

    # No independently-registered tool can create a node while bypassing the
    # sanitize-before-ready flow.
    assert 'brancher_spinup' not in tool_names

    _content, result = await server.call_tool(
        'brancher_create', {'appname': 'myapp', 'labels': ['ticket-123']}
    )

    # A result missing sanitization proof would mean an unsanitized node was
    # reported back to the caller.
    assert isinstance(result, dict)
    assert result.pop('ip_assigned_after_seconds') >= 0
    assert result.pop('ssh_reachable_after_seconds') >= 0
    assert result.pop('preview_basic_auth_password')
    assert result.pop('preview_admin_password')
    assert result == {
        'node_name': 'myapp-eph1',
        'minutes_remaining': None,
        'access_url': 'https://myapp-eph1.hypernode.io/',
        'admin_url': 'https://myapp-eph1.hypernode.io/admin',
        'admin_username': 'admin',
        'admin_email': 'admin@example.invalid',
        'admin_password_note': (
            "Password deliberately invalidated during sanitization -- this account "
            "(the sanitized original) is intentionally locked out; use "
            "preview_admin_username/preview_admin_password below to log in instead."
        ),
        'preview_basic_auth_username': 'preview',
        'preview_admin_username': 'preview',
        'status': 'ready',
        'sanitization_commands_run': 36,
        'sales_and_customer_data_sanitized': True,
    }


async def test_it_exposes_exactly_one_node_creation_mcp_tool_and_that_tool_always_runs_the_full_sanitize_before_ready_flow(  # noqa: E501
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')
    monkeypatch.setattr('pb_hypernode_mcp.server.HypernodeApiClient', FakeApiClient)

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeSubprocess:
        # `_resolve_admin_path` retries on unparseable stdout (not just a
        # raised exception) -- the default 'ok\n' stdout never parses for
        # `n98-magerun2 info:adminuri`, which would otherwise exhaust every
        # retry with a REAL asyncio.sleep() in tests that don't inject a
        # fake `sleep`, silently costing tens of seconds per test.
        if any('info:adminuri' in str(arg) for arg in args):
            return FakeSubprocess(stdout=b'Admin URI: /admin\n')

        return FakeSubprocess()

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_exec.asyncio.create_subprocess_exec',
        fake_create_subprocess_exec,
    )

    async def fake_sleep(seconds: float) -> None:
        # `_resolve_admin_path` sleeps a settle delay before its first read
        # (reinstated 2026-08-21 -- see its docstring) -- even the happy
        # path needs that wait, which would otherwise be a REAL
        # asyncio.sleep() in tests that don't inject a fake `sleep`.
        return None

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_spinup_flow.asyncio.sleep',
        fake_sleep,
    )

    server = create_server()

    tools = await server.list_tools()
    tool_names = [tool.name for tool in tools]

    creation_capable_tool_names = [
        name for name in tool_names if name in ('brancher_create', 'brancher_spinup')
    ]
    assert creation_capable_tool_names == ['brancher_create']

    _content, result = await server.call_tool(
        'brancher_create', {'appname': 'myapp', 'labels': ['ticket-123']}
    )

    assert isinstance(result, dict)
    assert result.pop('ip_assigned_after_seconds') >= 0
    assert result.pop('ssh_reachable_after_seconds') >= 0
    assert result.pop('preview_basic_auth_password')
    assert result.pop('preview_admin_password')
    assert result == {
        'node_name': 'myapp-eph1',
        'minutes_remaining': None,
        'access_url': 'https://myapp-eph1.hypernode.io/',
        'admin_url': 'https://myapp-eph1.hypernode.io/admin',
        'admin_username': 'admin',
        'admin_email': 'admin@example.invalid',
        'admin_password_note': (
            "Password deliberately invalidated during sanitization -- this account "
            "(the sanitized original) is intentionally locked out; use "
            "preview_admin_username/preview_admin_password below to log in instead."
        ),
        'preview_basic_auth_username': 'preview',
        'preview_admin_username': 'preview',
        'status': 'ready',
        'sanitization_commands_run': 36,
        'sales_and_customer_data_sanitized': True,
    }


async def test_it_exposes_brancher_list_as_a_callable_mcp_tool_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')
    monkeypatch.setattr('pb_hypernode_mcp.server.HypernodeApiClient', FakeApiClient)

    server = create_server()

    tools = await server.list_tools()
    assert 'brancher_list' in [tool.name for tool in tools]

    _content, result = await server.call_tool('brancher_list', {'appname': 'myapp'})

    assert result == {
        'result': [
            {
                'name': 'myapp-eph1',
                'host': 'myapp-eph1.hypernode.io',
                'minutes': 5,
                'ip': '203.0.113.10',
            },
        ],
    }


async def test_it_exposes_brancher_delete_as_a_callable_mcp_tool_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')
    monkeypatch.setattr('pb_hypernode_mcp.server.HypernodeApiClient', FakeApiClient)

    server = create_server()

    tools = await server.list_tools()
    assert 'brancher_delete' in [tool.name for tool in tools]

    _content, result = await server.call_tool(
        'brancher_delete', {'node_name': 'myapp-eph1', 'confirm': True}
    )

    assert result == {'deleted': True, 'node_name': 'myapp-eph1'}


async def test_it_exposes_brancher_ssh_info_as_a_callable_mcp_tool_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')
    monkeypatch.setattr('pb_hypernode_mcp.server.HypernodeApiClient', FakeApiClient)

    server = create_server()

    tools = await server.list_tools()
    assert 'brancher_ssh_info' in [tool.name for tool in tools]

    _content, result = await server.call_tool('brancher_ssh_info', {'node_name': 'myapp-eph1'})

    assert result == {
        'host': 'myapp-eph1.hypernode.io',
        'user': 'app',
        'port': 22,
    }


async def test_it_exposes_brancher_exec_as_a_callable_mcp_tool_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeSubprocess:
        # `_resolve_admin_path` retries on unparseable stdout (not just a
        # raised exception) -- the default 'ok\n' stdout never parses for
        # `n98-magerun2 info:adminuri`, which would otherwise exhaust every
        # retry with a REAL asyncio.sleep() in tests that don't inject a
        # fake `sleep`, silently costing tens of seconds per test.
        if any('info:adminuri' in str(arg) for arg in args):
            return FakeSubprocess(stdout=b'Admin URI: /admin\n')

        return FakeSubprocess()

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_exec.asyncio.create_subprocess_exec',
        fake_create_subprocess_exec,
    )

    async def fake_sleep(seconds: float) -> None:
        # `_resolve_admin_path` sleeps a settle delay before its first read
        # (reinstated 2026-08-21 -- see its docstring) -- even the happy
        # path needs that wait, which would otherwise be a REAL
        # asyncio.sleep() in tests that don't inject a fake `sleep`.
        return None

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_spinup_flow.asyncio.sleep',
        fake_sleep,
    )

    server = create_server()

    tools = await server.list_tools()
    assert 'brancher_exec' in [tool.name for tool in tools]

    _content, result = await server.call_tool(
        'brancher_exec', {'node_name': 'myapp-eph1', 'command': 'whoami'}
    )

    assert result == {'stdout': 'ok\n', 'stderr': '', 'exit_code': 0}


async def test_it_exposes_brancher_put_as_a_callable_mcp_tool_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeSubprocess:
        return FakeSubprocess(stdout=b'sent 1 file\n')

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_put.asyncio.create_subprocess_exec',
        fake_create_subprocess_exec,
    )

    server = create_server()

    tools = await server.list_tools()
    assert 'brancher_put' in [tool.name for tool in tools]

    _content, result = await server.call_tool(
        'brancher_put',
        {'node_name': 'myapp-eph1', 'local_path': '/local/f', 'remote_path': '/remote/f'},
    )

    assert result == {
        'node_name': 'myapp-eph1',
        'local_path': '/local/f',
        'remote_path': '/remote/f',
        'stdout': 'sent 1 file',
    }


async def test_it_constructs_a_single_shared_hypernode_api_client_reused_across_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token"}')
    monkeypatch.setattr('pb_hypernode_mcp.server.HypernodeApiClient', FakeApiClient)
    FakeApiClient.instances = 0

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeSubprocess:
        # `_resolve_admin_path` retries on unparseable stdout (not just a
        # raised exception) -- the default 'ok\n' stdout never parses for
        # `n98-magerun2 info:adminuri`, which would otherwise exhaust every
        # retry with a REAL asyncio.sleep() in tests that don't inject a
        # fake `sleep`, silently costing tens of seconds per test.
        if any('info:adminuri' in str(arg) for arg in args):
            return FakeSubprocess(stdout=b'Admin URI: /admin\n')

        return FakeSubprocess()

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_exec.asyncio.create_subprocess_exec',
        fake_create_subprocess_exec,
    )

    async def fake_sleep(seconds: float) -> None:
        # `_resolve_admin_path` sleeps a settle delay before its first read
        # (reinstated 2026-08-21 -- see its docstring) -- even the happy
        # path needs that wait, which would otherwise be a REAL
        # asyncio.sleep() in tests that don't inject a fake `sleep`.
        return None

    monkeypatch.setattr(
        'pb_hypernode_mcp.tools.brancher_spinup_flow.asyncio.sleep',
        fake_sleep,
    )

    server = create_server()

    await server.call_tool('brancher_ssh_info', {'node_name': 'myapp-eph1'})
    await server.call_tool('brancher_list', {'appname': 'myapp'})
    await server.call_tool('brancher_create', {'appname': 'myapp', 'labels': ['ticket-123']})

    assert FakeApiClient.instances == 1


async def test_it_exposes_brancher_apps_as_a_callable_mcp_tool_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": "test-token", "myapp2": "test-token2"}')

    server = create_server()

    tools = await server.list_tools()
    assert 'brancher_apps' in [tool.name for tool in tools]

    _content, result = await server.call_tool('brancher_apps', {})

    assert result == {'result': ['myapp', 'myapp2']}
