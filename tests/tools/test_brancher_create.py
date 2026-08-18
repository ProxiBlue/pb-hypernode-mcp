"""Tests for `create_brancher_node` and its pre-create guardrails.

`create_brancher_node` is an internal-only primitive — it is never
independently registered as an MCP tool (see task 017's security
remediation: the only externally-callable node-creation entry point is the
`brancher_create` MCP tool wired to the fully-gated
`spinup_sanitized_brancher_node` flow, registered by
`tools/brancher_spinup_flow.py::register()` and tested in
`tests/tools/test_brancher_spinup_flow.py` / `tests/test_server.py`).
"""

from __future__ import annotations

import httpx
import pytest

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings, UnknownAppError
from pb_hypernode_mcp.tools.brancher_create import (
    BrancherCreateError,
    create_brancher_node,
)


def make_client(handler, **tokens: str) -> HypernodeApiClient:
    return HypernodeApiClient(
        Settings(hypernode_api_tokens=tokens or {'myapp': 'test-token'}),
        transport=httpx.MockTransport(handler),
    )


async def test_it_creates_a_brancher_node_and_returns_the_node_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'GET':
            return httpx.Response(
                200,
                json={'plan_type': 'falcons', 'brancher_minutes_remaining': 42},
            )

        return httpx.Response(201, json={'appname': 'myapp-eph123456'})

    client = make_client(handler)

    result = await create_brancher_node(
        client,
        appname='myapp',
        labels=['ticket-123'],
    )

    assert result['node_name'] == 'myapp-eph123456'


async def test_it_rejects_the_call_when_no_label_is_provided() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail(f'unexpected HTTP call: {request.method} {request.url}')

    client = make_client(handler)

    with pytest.raises(BrancherCreateError, match='label'):
        await create_brancher_node(
            client,
            appname='myapp',
            labels=[],
        )


async def test_it_rejects_the_call_when_the_app_has_no_configured_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail(f'unexpected HTTP call: {request.method} {request.url}')

    client = make_client(handler, otherapp='test-token')

    with pytest.raises(UnknownAppError, match='myapp'):
        await create_brancher_node(
            client,
            appname='myapp',
            labels=['ticket-123'],
        )


async def test_it_rejects_the_call_when_the_app_is_not_on_a_falcons_eligible_plan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'GET':
            return httpx.Response(200, json={'plan_type': 'griffin'})

        pytest.fail(f'unexpected HTTP call: {request.method} {request.url}')

    client = make_client(handler)

    with pytest.raises(BrancherCreateError, match='Falcons'):
        await create_brancher_node(
            client,
            appname='myapp',
            labels=['ticket-123'],
        )


async def test_it_includes_remaining_free_minutes_in_the_response_before_alongside_creation() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'GET':
            return httpx.Response(
                200,
                json={'plan_type': 'falcons', 'brancher_minutes_remaining': 17},
            )

        return httpx.Response(201, json={'appname': 'myapp-eph999'})

    client = make_client(handler)

    result = await create_brancher_node(
        client,
        appname='myapp',
        labels=['ticket-123'],
    )

    assert result['minutes_remaining'] == 17


async def test_it_passes_clear_services_through_to_the_api_request_when_provided() -> None:
    captured_bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'GET':
            return httpx.Response(200, json={'plan_type': 'falcons'})

        captured_bodies.append(request.content)

        return httpx.Response(201, json={'appname': 'myapp-eph1'})

    client = make_client(handler)

    await create_brancher_node(
        client,
        appname='myapp',
        labels=['ticket-123'],
        clear_services=['mysql', 'elasticsearch'],
    )

    assert captured_bodies == [
        b'{"labels":["ticket-123"],"clear_services":["mysql","elasticsearch"]}'
    ]


async def test_it_defaults_clear_services_to_cron_when_not_provided() -> None:
    captured_bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'GET':
            return httpx.Response(200, json={'plan_type': 'falcons'})

        captured_bodies.append(request.content)

        return httpx.Response(201, json={'appname': 'myapp-eph1'})

    client = make_client(handler)

    await create_brancher_node(
        client,
        appname='myapp',
        labels=['ticket-123'],
    )

    assert captured_bodies == [b'{"labels":["ticket-123"],"clear_services":["cron"]}']
