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
from pb_hypernode_mcp.sanitization.commands import (
    generate_sanitization_commands,
    generate_url_setup_commands,
)
from pb_hypernode_mcp.sanitization.config import (
    PiiTableSanitizer,
    SanitizationConfig,
)
from pb_hypernode_mcp.tools.brancher_spinup_flow import (
    DEFAULT_READY_PROBE_COMMAND,
    NodeIpNeverAssignedError,
    NodeUnreachableTimeoutError,
    SanitizationFailedError,
    register,
    spinup_sanitized_brancher_node,
)

CREATED_NODE_NAME = 'myapp-eph123456'
CREATED_NODE_HOSTNAME = f'{CREATED_NODE_NAME}.hypernode.io'


def make_client(**tokens: str) -> HypernodeApiClient:
    """A client whose Brancher list endpoint reports the created node's ip as
    already assigned, so tests that only care about the sanitization/ssh
    phases aren't slowed down or broken by the new ip-assignment poll phase.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        if request.method == 'GET' and 'brancher/app/' in url:
            return httpx.Response(
                200,
                json={
                    'branchers': [
                        {
                            'name': CREATED_NODE_NAME,
                            'ip': '203.0.113.10',
                            'elapsed_time': 60,
                        },
                    ],
                },
            )

        if request.method == 'GET':
            return httpx.Response(
                200,
                json={'product': {'code': 'FALCON_S_202603DEV'}},
            )

        return httpx.Response(201, json={'name': CREATED_NODE_NAME})

    return HypernodeApiClient(
        Settings(hypernode_api_tokens=tokens or {'myapp': 'test-token'}),
        transport=httpx.MockTransport(handler),
    )


def make_client_ip_never_assigned(**tokens: str) -> HypernodeApiClient:
    """A client whose Brancher list endpoint always reports a null ip."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        if request.method == 'GET' and 'brancher/app/' in url:
            return httpx.Response(
                200,
                json={
                    'branchers': [
                        {'name': CREATED_NODE_NAME, 'ip': None, 'elapsed_time': 60},
                    ],
                },
            )

        if request.method == 'GET':
            return httpx.Response(
                200,
                json={'product': {'code': 'FALCON_S_202603DEV'}},
            )

        return httpx.Response(201, json={'name': CREATED_NODE_NAME})

    return HypernodeApiClient(
        Settings(hypernode_api_tokens=tokens or {'myapp': 'test-token'}),
        transport=httpx.MockTransport(handler),
    )


def make_client_ip_assigned_after_polls(
    assign_after_polls: int, **tokens: str
) -> HypernodeApiClient:
    """A client whose Brancher list endpoint reports a null ip for the first
    `assign_after_polls` GET calls to the list endpoint, then a real ip from then on.
    """
    poll_count = {'value': 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        if request.method == 'GET' and 'brancher/app/' in url:
            poll_count['value'] += 1
            ip = '203.0.113.10' if poll_count['value'] > assign_after_polls else None

            return httpx.Response(
                200,
                json={
                    'branchers': [
                        {'name': CREATED_NODE_NAME, 'ip': ip, 'elapsed_time': 60},
                    ],
                },
            )

        if request.method == 'GET':
            return httpx.Response(
                200,
                json={'product': {'code': 'FALCON_S_202603DEV'}},
            )

        return httpx.Response(201, json={'name': CREATED_NODE_NAME})

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
        # Keeps tests unrelated to the vhost/base-URL feature itself focused
        # on sanitization-command counting — dedicated tests below cover the
        # vhost command explicitly with `vhost_webroot` set.
        vhost_webroot=None,
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

    # Reachability probe (1) + 3 url-setup commands (2x base_url config:set +
    # cache:flush, vhost_webroot=None so no vhost command) + 2 sanitization
    # commands + 1 best-effort admin-path resolve call must have already
    # completed by the time a 'ready' result is produced.
    assert len(exec_fn.calls) == 7
    assert result['status'] == 'ready'


async def test_it_runs_the_sanitization_command_sequence_exactly_once_per_create() -> None:
    exec_fn = RecordingExec()
    config = make_sanitization_config()
    expected_commands = generate_url_setup_commands(
        CREATED_NODE_HOSTNAME, config
    ) + generate_sanitization_commands(config)

    await spinup_sanitized_brancher_node(
        make_client(),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=config,
        exec_command=exec_fn,
    )

    # calls[0] is the reachability probe, calls[-1] the best-effort
    # admin-path resolve call -- everything in between is the url-setup +
    # sanitization command sequence.
    sanitization_calls = [command for _node_name, command in exec_fn.calls[1:-1]]
    assert sanitization_calls == expected_commands


async def test_it_creates_a_vhost_for_the_node_when_the_config_has_a_vhost_webroot() -> None:
    exec_fn = RecordingExec()
    config = SanitizationConfig(
        pii_tables=make_sanitization_config().pii_tables,
        admin_user_reset=make_sanitization_config().admin_user_reset,
        vhost_webroot='/data/web/public',
        vhost_type='magento2',
    )

    await spinup_sanitized_brancher_node(
        make_client(),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=config,
        exec_command=exec_fn,
    )

    commands_run = [command for _node_name, command in exec_fn.calls]
    assert any(
        'hypernode-manage-vhosts' in command and CREATED_NODE_HOSTNAME in command
        for command in commands_run
    )


class TimeoutRecordingExec:
    """Fake `exec_command` that records the `timeout` kwarg passed to each call."""

    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    async def __call__(
        self, node_name: str, command: str, *, timeout: float | None = None, **_: Any
    ) -> dict[str, Any]:
        self.timeouts.append(timeout)

        return {'stdout': '', 'stderr': '', 'exit_code': 0}


async def test_it_passes_the_configured_sanitization_command_timeout_to_each_command() -> None:
    exec_fn = TimeoutRecordingExec()
    config = make_sanitization_config()

    await spinup_sanitized_brancher_node(
        make_client(),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=config,
        exec_command=exec_fn,
        sanitization_command_timeout=180.0,
    )

    # calls[0] is the reachability probe (no explicit timeout override),
    # calls[-1] the admin-path resolve (also no override) -- every command
    # in between is a url-setup/sanitization command and must have received
    # the configured timeout, e.g. so a slow real-world command (like
    # hypernode-manage-vhosts' live ACME cert issuance) isn't cut short by
    # exec_command's much shorter 30s default.
    assert exec_fn.timeouts[1:-1] == [180.0] * (len(exec_fn.timeouts) - 2)


class RespondingExec:
    """Fake `exec_command` that returns a configured stdout for one specific command."""

    def __init__(self, *, command: str, stdout: str) -> None:
        self._command = command
        self._stdout = stdout

    async def __call__(self, node_name: str, command: str, **_: Any) -> dict[str, Any]:
        if command == self._command:
            return {'stdout': self._stdout, 'stderr': '', 'exit_code': 0}

        return {'stdout': '', 'stderr': '', 'exit_code': 0}


async def test_it_reports_the_admin_url_parsed_from_info_adminuri_output() -> None:
    exec_fn = RespondingExec(
        command='bin/magento info:adminuri',
        stdout='Admin Panel is accessible with /backend-custom\n',
    )

    result = await spinup_sanitized_brancher_node(
        make_client(),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
    )

    assert result['admin_url'] == 'https://myapp-eph123456.hypernode.io/backend-custom'


async def test_it_falls_back_to_the_default_admin_path_when_info_adminuri_output_is_unparseable() -> (  # noqa: E501
    None
):
    exec_fn = RespondingExec(command='bin/magento info:adminuri', stdout='ok\n')

    result = await spinup_sanitized_brancher_node(
        make_client(),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
    )

    assert result['admin_url'] == 'https://myapp-eph123456.hypernode.io/admin'


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
    # call index 0 = reachability probe, index 2 = the 2nd url-setup command
    # (base_url secure) -- commands_completed counts within that commands
    # loop only, so 1 (the 1st url-setup command) succeeded before this fails.
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

    # The structural guarantee is no `access_url` attribute on the exception
    # -- NOT that the message never contains the substring "hypernode.io" at
    # all, since a failing url-setup command (e.g. the base_url config:set)
    # legitimately echoes the hostname it was trying to set as part of
    # naming which command failed.
    assert not hasattr(exc_info.value, 'access_url')


class AlwaysUnreachableExec:
    """Fake `exec_command` that never succeeds — simulates an unreachable node."""

    def __init__(self) -> None:
        self.call_count = 0

    async def __call__(self, node_name: str, command: str, **_: Any) -> dict[str, Any]:
        self.call_count += 1
        raise ConnectionError('ssh: connect to host ... Connection refused')


# --- tests for the two-phase (ip-poll then ssh-poll) reachability wait (task 022) ---


async def test_it_polls_the_list_endpoint_until_the_node_has_a_non_null_ip_before_attempting_ssh() -> (  # noqa: E501
    None
):
    exec_fn = RecordingExec()
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    result = await spinup_sanitized_brancher_node(
        make_client_ip_assigned_after_polls(assign_after_polls=3),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
        reachability_poll_interval=1.0,
        reachability_timeout=120.0,
        sleep=fake_sleep,
        clock=fake_clock,
    )

    assert result['status'] == 'ready'
    # 3 polls came back null before the 4th reported the real ip -> at least
    # 3 sleeps of the poll interval were spent waiting on ip assignment alone.
    assert result['ip_assigned_after_seconds'] >= 3.0


async def test_it_raises_node_ip_never_assigned_error_when_ip_is_never_assigned_within_the_timeout() -> (  # noqa: E501
    None
):
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    with pytest.raises(NodeIpNeverAssignedError, match=CREATED_NODE_NAME):
        await spinup_sanitized_brancher_node(
            make_client_ip_never_assigned(),
            appname='myapp',
            labels=['ticket-123'],
            sanitization_config=make_sanitization_config(),
            exec_command=RecordingExec(),
            reachability_poll_interval=1.0,
            reachability_timeout=5.0,
            sleep=fake_sleep,
            clock=fake_clock,
        )


async def test_it_does_not_attempt_any_ssh_exec_command_call_while_ip_is_still_null() -> None:
    exec_fn = RecordingExec()
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    with pytest.raises(NodeIpNeverAssignedError):
        await spinup_sanitized_brancher_node(
            make_client_ip_never_assigned(),
            appname='myapp',
            labels=['ticket-123'],
            sanitization_config=make_sanitization_config(),
            exec_command=exec_fn,
            reachability_poll_interval=1.0,
            reachability_timeout=5.0,
            sleep=fake_sleep,
            clock=fake_clock,
        )

    assert exec_fn.calls == []


async def test_it_starts_the_ssh_reachability_phase_only_after_ip_is_assigned() -> None:
    exec_fn = RecordingExec()
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    await spinup_sanitized_brancher_node(
        make_client_ip_assigned_after_polls(assign_after_polls=2),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
        reachability_poll_interval=1.0,
        reachability_timeout=120.0,
        sleep=fake_sleep,
        clock=fake_clock,
    )

    # The first exec_command call is the reachability probe -- it must only
    # have happened once fake_time already reflects the ip-poll delay.
    assert fake_time['now'] >= 2.0
    assert exec_fn.calls[0][1] == DEFAULT_READY_PROBE_COMMAND


async def test_it_raises_node_unreachable_timeout_error_when_ip_is_assigned_but_ssh_never_becomes_reachable() -> (  # noqa: E501
    None
):
    exec_fn = AlwaysUnreachableExec()
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    with pytest.raises(NodeUnreachableTimeoutError, match=CREATED_NODE_NAME):
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


async def test_it_reports_how_long_ip_assignment_and_ssh_reachability_each_took_on_success() -> (
    None
):
    exec_fn = RecordingExec()
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    result = await spinup_sanitized_brancher_node(
        make_client_ip_assigned_after_polls(assign_after_polls=2),
        appname='myapp',
        labels=['ticket-123'],
        sanitization_config=make_sanitization_config(),
        exec_command=exec_fn,
        reachability_poll_interval=1.0,
        reachability_timeout=120.0,
        sleep=fake_sleep,
        clock=fake_clock,
    )

    assert result['ip_assigned_after_seconds'] >= 2.0
    assert result['ssh_reachable_after_seconds'] >= 0.0


async def test_it_splits_the_overall_timeout_across_both_phases_rather_than_giving_each_phase_a_full_fresh_timeout() -> (  # noqa: E501
    None
):
    # ip assignment eats 4s of a 5s overall budget; ssh then never responds, so
    # phase 2 must fail almost immediately (only ~1s of budget left) rather than
    # getting a fresh 5s of its own on top.
    exec_fn = AlwaysUnreachableExec()
    fake_time = {'now': 0.0}

    async def fake_sleep(seconds: float) -> None:
        fake_time['now'] += seconds

    def fake_clock() -> float:
        return fake_time['now']

    with pytest.raises(NodeUnreachableTimeoutError):
        await spinup_sanitized_brancher_node(
            make_client_ip_assigned_after_polls(assign_after_polls=4),
            appname='myapp',
            labels=['ticket-123'],
            sanitization_config=make_sanitization_config(),
            exec_command=exec_fn,
            reachability_poll_interval=1.0,
            reachability_timeout=5.0,
            sleep=fake_sleep,
            clock=fake_clock,
        )

    # Total time spent across both phases must stay within the configured
    # overall timeout, not (ip phase) + (a fresh ssh phase timeout) = ~10s.
    assert fake_time['now'] < 6.0


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

    assert isinstance(result, dict)
    assert result.pop('ip_assigned_after_seconds') >= 0
    assert result.pop('ssh_reachable_after_seconds') >= 0
    assert result == {
        'node_name': 'myapp-eph123456',
        'minutes_remaining': None,
        'access_url': 'https://myapp-eph123456.hypernode.io/',
        'admin_url': 'https://myapp-eph123456.hypernode.io/admin',
        'admin_username': 'admin',
        'admin_email': 'admin@example.invalid',
        'admin_password_note': (
            'Password deliberately invalidated during sanitization -- set a real '
            'one with `bin/magento admin:user:create` before logging in.'
        ),
        'status': 'ready',
        'sanitization_commands_run': 5,
        'sales_and_customer_data_sanitized': True,
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

    assert isinstance(result, dict)
    assert result.pop('ip_assigned_after_seconds') >= 0
    assert result.pop('ssh_reachable_after_seconds') >= 0
    assert result == {
        'node_name': 'myapp-eph123456',
        'minutes_remaining': None,
        'access_url': 'https://myapp-eph123456.hypernode.io/',
        'admin_url': 'https://myapp-eph123456.hypernode.io/admin',
        'admin_username': 'admin',
        'admin_email': 'admin@example.invalid',
        'admin_password_note': (
            'Password deliberately invalidated during sanitization -- set a real '
            'one with `bin/magento admin:user:create` before logging in.'
        ),
        'status': 'ready',
        'sanitization_commands_run': 5,
        'sales_and_customer_data_sanitized': True,
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
