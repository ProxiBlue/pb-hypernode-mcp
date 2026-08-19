"""Tests for `cleanup_logic` — the pure/async helpers backing the brancher-cleanup skill."""

from __future__ import annotations

import httpx

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.cleanup_logic import cleanup_stale_nodes, flag_stale_nodes
from pb_hypernode_mcp.config import Settings
from pb_hypernode_mcp.tools.brancher_list import list_brancher_nodes

NODES_RESPONSE = {
    'branchers': [
        {'name': 'myapp-eph1', 'elapsed_time': 720},
        {'name': 'myapp-eph2', 'elapsed_time': 18000},
    ],
}


def make_settings() -> Settings:
    return Settings(hypernode_api_tokens={'myapp': 'test-token'})


def make_client(handler) -> HypernodeApiClient:
    return HypernodeApiClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )


async def test_it_lists_all_active_nodes_with_their_minutes_used() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=NODES_RESPONSE)

    client = make_client(handler)
    settings = make_settings()

    nodes = await list_brancher_nodes('myapp', client=client, settings=settings)

    assert nodes == [
        {'name': 'myapp-eph1', 'host': 'myapp-eph1.hypernode.io', 'minutes': 12},
        {'name': 'myapp-eph2', 'host': 'myapp-eph2.hypernode.io', 'minutes': 300},
    ]


def test_it_flags_nodes_past_the_configured_age_threshold() -> None:
    nodes = [
        {'name': 'myapp-eph1', 'host': 'myapp-eph1.hypernode.io', 'minutes': 12},
        {'name': 'myapp-eph2', 'host': 'myapp-eph2.hypernode.io', 'minutes': 300},
    ]

    flagged = flag_stale_nodes(nodes, threshold_minutes=240)

    assert flagged == [
        {'name': 'myapp-eph2', 'host': 'myapp-eph2.hypernode.io', 'minutes': 300},
    ]


async def test_it_deletes_a_flagged_node_only_after_confirmation() -> None:
    delete_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delete_called

        if request.method == 'DELETE':
            delete_called = True

            return httpx.Response(200, json={})

        return httpx.Response(
            200,
            json={
                'branchers': [
                    {'name': 'myapp-eph2', 'elapsed_time': 18000},
                ],
            },
        )

    client = make_client(handler)
    settings = make_settings()

    preview = await cleanup_stale_nodes(
        'myapp',
        client=client,
        settings=settings,
        threshold_minutes=240,
        confirm=False,
    )

    assert delete_called is False
    assert preview['confirm_required'] is True
    assert preview['flagged'] == [
        {'name': 'myapp-eph2', 'host': 'myapp-eph2.hypernode.io', 'minutes': 300},
    ]

    result = await cleanup_stale_nodes(
        'myapp',
        client=client,
        settings=settings,
        threshold_minutes=240,
        confirm=True,
    )

    assert delete_called is True
    assert result['deleted'] == ['myapp-eph2']


async def test_it_supports_bulk_deleting_all_flagged_nodes_in_one_pass() -> None:
    deleted_names: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'DELETE':
            deleted_names.append(request.url.path.split('/')[-2])

            return httpx.Response(200, json={})

        return httpx.Response(200, json=NODES_RESPONSE)

    client = make_client(handler)
    settings = make_settings()

    result = await cleanup_stale_nodes(
        'myapp',
        client=client,
        settings=settings,
        threshold_minutes=0,
        confirm=True,
    )

    assert sorted(deleted_names) == ['myapp-eph1', 'myapp-eph2']
    assert sorted(result['deleted']) == ['myapp-eph1', 'myapp-eph2']


async def test_it_reports_nothing_to_clean_up_when_no_nodes_exceed_the_threshold() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == 'DELETE':
            raise AssertionError('delete must not be called when nothing is flagged')

        return httpx.Response(200, json=NODES_RESPONSE)

    client = make_client(handler)
    settings = make_settings()

    result = await cleanup_stale_nodes(
        'myapp',
        client=client,
        settings=settings,
        threshold_minutes=1000,
        confirm=False,
    )

    assert result['flagged'] == []
    assert result['deleted'] == []
    assert 'Nothing to clean up' in result['message']
