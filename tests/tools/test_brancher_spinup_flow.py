"""Tests for the create -> wait -> sanitize -> report-ready orchestration flow."""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings
from pb_hypernode_mcp.sanitization.commands import generate_sanitization_commands
from pb_hypernode_mcp.sanitization.config import (
    PiiTableSanitizer,
    SanitizationConfig,
)
from pb_hypernode_mcp.tools.brancher_spinup_flow import (
    NodeUnreachableTimeoutError,
    SanitizationFailedError,
    register,
    spinup_sanitized_brancher_node,
)


def make_client(**tokens: str) -> HypernodeApiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'GET':
            return httpx.Response(
                200,
                json={'product': {'code': 'FALCON_S_202603DEV'}},
            )

        return httpx.Response(201, json={'name': 'myapp-eph123456'})

    return HypernodeApiClient(
        Settings(hypernode_api_tokens=tokens or {'myapp': 'test-token'}),
        transport=httpx.MockTransport(handler),
    )


def make_sanitization_config() -> SanitizationConfig:
    return SanitizationConfig(
        pii_tables=(
            PiiTableSanitizer(
                table='customer_entity',
                set_columns={'email': "'anon@example.invalid'"},
            ),
        ),
        admin_user_reset=PiiTableSanitizer(
            table='admin_user',
            set_columns={'password': "'unused-in-this-test'"},
        ),
    )


class RecordingExec:
    """Fake `exec_command` that records every call and always succeeds."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, node_name: str, command: str, **_: Any) -> dict[str, Any]:
        self.calls.append((node_name, command))

        return {'stdout': '', 'stderr': '', 'exit_code': 0}


async def test_it_does_not_report_the_node_as_ready_until_sanitization_has_completed() -> None:
    exec_fn = RecordingExec()

    result = await spinup_sanitized_brancher_node(
        make_client(),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
    )

    # Reachability probe + exactly 2 sanitization commands must have already
    # completed by the time a 'ready' result is produced.
    assert len(exec_fn.calls) == 3
    assert result['status'] == 'ready'


async def test_it_runs_the_sanitization_command_sequence_exactly_once_per_create() -> None:
    exec_fn = RecordingExec()
    config = make_sanitization_config()
    expected_commands = generate_sanitization_commands(config)

    await spinup_sanitized_brancher_node(
        make_client(),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=config,
        exec_command=exec_fn,
    )

    sanitization_calls = [command for _node_name, command in exec_fn.calls[1:]]
    assert sanitization_calls == expected_commands


class FailingAfterNExec:
    """Fake `exec_command` that fails a specific sanitization command by index."""

    def __init__(self, fail_at_call_index: int) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail_at_call_index = fail_at_call_index

    async def __call__(self, node_name: str, command: str, **_: Any) -> dict[str, Any]:
        call_index = len(self.calls)
        self.calls.append((node_name, command))

        if call_index == self._fail_at_call_index:
            return {'stdout': '', 'stderr': 'ERROR 1064', 'exit_code': 1}

        return {'stdout': '', 'stderr': '', 'exit_code': 0}


async def test_it_surfaces_a_clear_failure_state_when_sanitization_fails_partway_through() -> None:
    # call index 0 = reachability probe, index 2 = the 2nd sanitization command
    exec_fn = FailingAfterNExec(fail_at_call_index=2)
    config = make_sanitization_config()

    with pytest.raises(SanitizationFailedError) as exc_info:
        await spinup_sanitized_brancher_node(
            make_client(),
            appname='myapp',
            labels=['ticket-123'],
            sanitization_config=config,
            exec_command=exec_fn,
        )

    assert exc_info.value.node_name == 'myapp-eph123456'
    assert exc_info.value.commands_completed == 1


async def test_it_does_not_return_the_nodes_access_url_when_sanitization_has_failed() -> None:
    exec_fn = FailingAfterNExec(fail_at_call_index=1)
    config = make_sanitization_config()

    with pytest.raises(SanitizationFailedError) as exc_info:
        await spinup_sanitized_brancher_node(
            make_client(),
            appname='myapp',
            labels=['ticket-123'],
            sanitization_config=config,
            exec_command=exec_fn,
        )

    assert not hasattr(exc_info.value, 'access_url')
    assert 'hypernode.io' not in str(exc_info.value)


class AlwaysUnreachableExec:
    """Fake `exec_command` that never succeeds — simulates an unreachable node."""

    def __init__(self) -> None:
        self.call_count = 0

    async def __call__(self, node_name: str, command: str, **_: Any) -> dict[str, Any]:
        self.call_count += 1
        raise ConnectionError('ssh: connect to host ... Connection refused')


async def test_it_times_out_with_a_clear_error_if_the_node_never_becomes_ssh_reachable() -> None:
    exec_fn = AlwaysUnreachableExec()
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    with pytest.raises(NodeUnreachableTimeoutError):
        await spinup_sanitized_brancher_node(
            make_client(),
            appname='myapp',
            labels=['ticket-123'],
            sanitization_config=make_sanitization_config(),
            exec_command=exec_fn,
            reachability_poll_interval=1.0,
            reachability_timeout=5.0,
            sleep=fake_sleep,
            clock=fake_clock,
        )

    assert exec_fn.call_count >= 2


def test_it_defaults_the_reachability_timeout_to_1200_seconds() -> None:
    signature = inspect.signature(spinup_sanitized_brancher_node)
    assert signature.parameters['reachability_timeout'].default == 1200.0

    register_signature = inspect.signature(register)
    assert register_signature.parameters['reachability_timeout'].default == 1200.0


async def test_it_still_respects_an_explicitly_injected_shorter_timeout_for_tests() -> None:
    # No real 20-minute test run: injects a short timeout explicitly and
    # asserts it is honoured rather than the (now much longer) default.
    exec_fn = AlwaysUnreachableExec()
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    with pytest.raises(NodeUnreachableTimeoutError):
        await spinup_sanitized_brancher_node(
            make_client(),
            appname='myapp',
            labels=['ticket-123'],
            sanitization_config=make_sanitization_config(),
            exec_command=exec_fn,
            reachability_poll_interval=1.0,
            reachability_timeout=5.0,
            sleep=fake_sleep,
            clock=fake_clock,
        )

    assert fake_time['now'] < 1200.0


# --- tests for the `brancher_create` MCP tool (`register()`), the sole
# node-creation surface the `brancher-spinup` skill actually calls ---


async def test_it_invokes_brancher_create_with_a_required_label_argument() -> None:
    """The registered brancher_spinup tool rejects an empty/missing labels argument.

    Guardrail is enforced deep in `create_brancher_node`; this verifies the
    `register()` wrapper doesn't accidentally make `labels` optional.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail(f'unexpected HTTP call: {request.method} {request.url}')

    server = FastMCP(name='test-server')
    register(
        server,
        client_factory=lambda: make_client(),
        exec_command=RecordingExec(),
    )

    with pytest.raises(ToolError, match='label'):
        await server.call_tool('brancher_create', {'appname': 'myapp', 'labels': []})


async def test_it_reports_the_node_url_and_ssh_info_to_the_user_after_creation_completes() -> None:
    exec_fn = RecordingExec()
    server = FastMCP(name='test-server')
    register(
        server,
        client_factory=lambda: make_client(),
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
    )

    _content, result = await server.call_tool(
        'brancher_create', {'appname': 'myapp', 'labels': ['ticket-123']}
    )

    assert result == {
        'node_name': 'myapp-eph123456',
        'minutes_remaining': None,
        'access_url': 'https://myapp-eph123456.hypernode.io/',
        'status': 'ready',
        'sanitization_commands_run': 2,
    }


async def test_it_surfaces_the_guardrail_checks_minutes_remaining_and_configured_app_in_its_output() -> (  # noqa: E501
    None
):
    exec_fn = RecordingExec()
    server = FastMCP(name='test-server')
    register(
        server,
        client_factory=lambda: make_client(),
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
    )

    _content, result = await server.call_tool(
        'brancher_create', {'appname': 'myapp', 'labels': ['ticket-123']}
    )

    assert result == {
        'node_name': 'myapp-eph123456',
        'minutes_remaining': None,
        'access_url': 'https://myapp-eph123456.hypernode.io/',
        'status': 'ready',
        'sanitization_commands_run': 2,
    }

    def reject_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('API must not be called for an app with no configured token')

    disallowed_client = HypernodeApiClient(
        Settings(hypernode_api_tokens={'otherapp': 'test-token'}),
        transport=httpx.MockTransport(reject_handler),
    )
    disallowed_server = FastMCP(name='test-server-disallowed')
    register(
        disallowed_server,
        client_factory=lambda: disallowed_client,
        sanitization_config=make_sanitization_config(),
        exec_command=RecordingExec(),
    )

    with pytest.raises(ToolError, match='configured apps'):
        await disallowed_server.call_tool(
            'brancher_create', {'appname': 'myapp', 'labels': ['ticket-123']}
        )


async def test_it_surfaces_a_clear_error_to_the_user_if_creation_or_sanitization_fails() -> None:
    exec_fn = FailingAfterNExec(fail_at_call_index=2)
    server = FastMCP(name='test-server')
    register(
        server,
        client_factory=lambda: make_client(),
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
    )

    with pytest.raises(ToolError, match='Sanitization failed'):
        await server.call_tool('brancher_create', {'appname': 'myapp', 'labels': ['ticket-123']})
