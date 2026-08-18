"""MCP server entrypoint for pb-hypernode-mcp, stdio transport."""

from __future__ import annotations

import anyio
from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.api_client import HypernodeApiClient
from pb_hypernode_mcp.config import Settings, load_settings
from pb_hypernode_mcp.tools import (
    brancher_apps,
    brancher_delete,
    brancher_exec,
    brancher_list,
    brancher_put,
    brancher_spinup_flow,
    brancher_ssh_info,
)

SERVER_NAME = 'pb-hypernode-mcp'


def create_server() -> FastMCP:
    """Build the FastMCP server instance with all seven Brancher tools registered.

    `Settings` and `HypernodeApiClient` are each built lazily, on first use,
    and cached so every tool call after the first reuses the same client
    instance rather than constructing a new one per call. Construction stays
    lazy (not done here at `create_server()` time) so building the server
    never requires `HYPERNODE_API_TOKENS` to already be configured.

    SECURITY (task 017): `brancher_create` is the ONLY node-creation tool
    registered here, and it is wired to `brancher_spinup_flow.register()` —
    the fully-gated create -> wait -> sanitize -> report-ready flow. The raw,
    unsanitized `create_brancher_node()` primitive
    (`tools/brancher_create.py`) is intentionally never registered as its
    own MCP tool; do not add it back.

    Hypernode API tokens are scoped per Hypernode/app (task 018), so every
    REST-API-calling tool resolves its token per-request via
    `Settings.token_for(appname)` inside `HypernodeApiClient` — there is no
    single account-wide token or separate allowlist to wire up here.
    `brancher_apps` (pure local config introspection, no API call) lets a
    caller list which apps actually have a token configured.
    """
    server = FastMCP(name=SERVER_NAME)

    cached_settings: Settings | None = None
    cached_client: HypernodeApiClient | None = None

    def get_settings() -> Settings:
        nonlocal cached_settings
        if cached_settings is None:
            cached_settings = load_settings()

        return cached_settings

    def get_client() -> HypernodeApiClient:
        nonlocal cached_client
        if cached_client is None:
            cached_client = HypernodeApiClient(get_settings())

        return cached_client

    brancher_ssh_info.register(server, get_client)
    brancher_list.register(server, lambda: (get_client(), get_settings()))
    brancher_delete.register(server, lambda: (get_client(), get_settings()))
    brancher_exec.register(server)
    brancher_put.register(server)
    brancher_spinup_flow.register(server, get_client)
    brancher_apps.register(server, get_settings)

    return server


async def run_async() -> None:
    """Run the MCP server over stdio transport until the client disconnects."""
    server = create_server()
    await server.run_stdio_async()


def main() -> None:
    """Synchronous entrypoint used by the `pb-hypernode-mcp` console script."""
    anyio.run(run_async)


if __name__ == '__main__':
    main()
