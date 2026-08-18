"""brancher_apps MCP tool.

Pure local config introspection — lists every Hypernode `<appname>` that has
a configured API token in `HYPERNODE_API_TOKENS`. No REST API call, no
`HypernodeApiClient` dependency. Skills call this first whenever a user's
request doesn't say which Hypernode/app to target, so they never have to
guess an appname.
"""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from pb_hypernode_mcp.config import Settings

SettingsFactory = Callable[[], Settings]


def list_configured_apps(settings: Settings) -> tuple[str, ...]:
    """Return every Hypernode `<appname>` with a configured API token, sorted."""
    return settings.configured_apps


def register(server: FastMCP, settings_factory: SettingsFactory) -> None:
    """Register the `brancher_apps` tool on `server`.

    `settings_factory` is called lazily, once per tool invocation, so server
    construction never eagerly requires `HYPERNODE_API_TOKENS` to already be
    configured.
    """

    @server.tool(name='brancher_apps')
    async def brancher_apps() -> tuple[str, ...]:
        """List every Hypernode `<appname>` with a configured API token."""
        return list_configured_apps(settings_factory())
