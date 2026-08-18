"""Config loading for pb-hypernode-mcp.

`HYPERNODE_API_TOKEN` is read from the environment only and is never written to
disk. The app allowlist (permitted `<appname>` values) is also env-var
configurable — see `Settings.app_allowlist`.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised when required pb-hypernode-mcp configuration is missing or invalid."""


class Settings(BaseSettings):
    """Environment-loaded configuration for the Hypernode MCP server."""

    model_config = SettingsConfigDict(extra='ignore')

    hypernode_api_token: str = Field(default='')
    hypernode_app_allowlist: str = Field(default='')

    @property
    def app_allowlist(self) -> tuple[str, ...]:
        """Permitted `<appname>` values, parsed from the comma-separated env var."""
        return tuple(app.strip() for app in self.hypernode_app_allowlist.split(',') if app.strip())


def load_settings() -> Settings:
    """Load settings from the environment, raising `ConfigError` if invalid."""
    settings = Settings()

    if not settings.hypernode_api_token:
        raise ConfigError(
            'HYPERNODE_API_TOKEN environment variable is not set. '
            'Set it to your Hypernode API token before starting the server.'
        )

    return settings
