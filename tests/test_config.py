"""Tests for pb_hypernode_mcp config loading."""

from __future__ import annotations

import pytest

from pb_hypernode_mcp.config import ConfigError, load_settings


def test_it_raises_a_clear_config_error_when_hypernode_api_token_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('HYPERNODE_API_TOKEN', raising=False)

    with pytest.raises(ConfigError, match='HYPERNODE_API_TOKEN'):
        load_settings()


def test_it_loads_the_app_allowlist_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKEN', 'test-token')
    monkeypatch.setenv('HYPERNODE_APP_ALLOWLIST', 'appone, apptwo,appthree')

    settings = load_settings()

    assert settings.app_allowlist == ('appone', 'apptwo', 'appthree')
