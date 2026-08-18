"""Config loading for pb-hypernode-mcp.

`HYPERNODE_API_TOKENS` is read from the environment only and is never written
to disk. Hypernode API tokens are scoped per Hypernode/app, not
account-wide, so this holds a JSON object mapping `<appname>` -> token, e.g.
`HYPERNODE_API_TOKENS='{"myapp":"token1","myapp2":"token2"}'`. The map's keys
ARE the allowlist — an app with no entry has no token to authenticate with,
so it cannot be operated on. See `Settings.configured_apps` / `token_for()`.
"""

from __future__ import annotations

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError


class ConfigError(Exception):
    """Raised when required pb-hypernode-mcp configuration is missing or invalid."""


class UnknownAppError(Exception):
    """Raised when a request targets an app with no token configured for it."""


class Settings(BaseSettings):
    """Environment-loaded configuration for the Hypernode MCP server."""

    model_config = SettingsConfigDict(extra='ignore')

    hypernode_api_tokens: dict[str, str] = Field(default_factory=dict)

    @property
    def configured_apps(self) -> tuple[str, ...]:
        """Every `<appname>` with a configured token, sorted."""
        return tuple(sorted(self.hypernode_api_tokens))

    def token_for(self, appname: str) -> str:
        """Return the API token configured for `appname`.

        Raises `UnknownAppError` (listing what IS configured) when `appname`
        has no token in `HYPERNODE_API_TOKENS` — there is nothing to
        authenticate with, so this app cannot be operated on.
        """
        try:
            return self.hypernode_api_tokens[appname]
        except KeyError:
            configured = ', '.join(self.configured_apps) if self.configured_apps else '(none)'

            raise UnknownAppError(
                f"No token configured for '{appname}' — configured apps: {configured}"
            ) from None


def load_settings() -> Settings:
    """Load settings from the environment, raising `ConfigError` if invalid."""
    try:
        settings = Settings()
    except (SettingsError, ValidationError) as exc:
        raise ConfigError(
            'HYPERNODE_API_TOKENS environment variable must be a JSON object mapping '
            'appname to API token, e.g. \'{"myapp":"token1","myapp2":"token2"}\'. '
            f'{exc}'
        ) from exc

    if not settings.hypernode_api_tokens:
        raise ConfigError(
            'HYPERNODE_API_TOKENS environment variable is not set. '
            'Set it to a JSON object mapping each Hypernode <appname> to its API token, '
            'e.g. \'{"myapp":"token1","myapp2":"token2"}\', before starting the server.'
        )

    return settings
