"""Tests for pb_hypernode_mcp config loading."""

from __future__ import annotations

import pytest

from pb_hypernode_mcp.config import ConfigError, UnknownAppError, load_settings


def test_it_parses_hypernode_api_tokens_as_a_json_appname_to_token_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp":"token1","myapp2":"token2"}')

    settings = load_settings()

    assert settings.token_for('myapp') == 'token1'
    assert settings.token_for('myapp2') == 'token2'


def test_it_raises_a_clear_config_error_when_hypernode_api_tokens_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('HYPERNODE_API_TOKENS', raising=False)

    with pytest.raises(ConfigError, match='HYPERNODE_API_TOKENS'):
        load_settings()


def test_it_raises_a_clear_config_error_when_hypernode_api_tokens_is_not_valid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', 'not-json')

    with pytest.raises(ConfigError, match='HYPERNODE_API_TOKENS'):
        load_settings()


def test_it_raises_a_clear_config_error_when_hypernode_api_tokens_is_not_a_flat_string_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp": 123}')

    with pytest.raises(ConfigError, match='HYPERNODE_API_TOKENS'):
        load_settings()


def test_it_lists_configured_apps_sorted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"zapp":"token1","aapp":"token2"}')

    settings = load_settings()

    assert settings.configured_apps == ('aapp', 'zapp')


def test_it_raises_a_clear_error_listing_configured_apps_when_resolving_an_unconfigured_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp":"token1","myapp2":"token2"}')

    settings = load_settings()

    with pytest.raises(UnknownAppError, match='myapp3') as exc_info:
        settings.token_for('myapp3')

    assert 'myapp' in str(exc_info.value)
    assert 'myapp2' in str(exc_info.value)


def test_it_parses_hypernode_known_admin_paths_as_a_json_appname_to_path_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp":"token1"}')
    monkeypatch.setenv('HYPERNODE_KNOWN_ADMIN_PATHS', '{"myapp":"/admin-custom"}')

    settings = load_settings()

    assert settings.known_admin_path_for('myapp') == '/admin-custom'


def test_known_admin_path_for_returns_none_not_an_error_when_app_has_no_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('HYPERNODE_API_TOKENS', '{"myapp":"token1"}')
    monkeypatch.delenv('HYPERNODE_KNOWN_ADMIN_PATHS', raising=False)

    settings = load_settings()

    assert settings.known_admin_path_for('myapp') is None
