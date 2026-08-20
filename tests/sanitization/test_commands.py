"""Tests for sanitization command/SQL generation."""

from __future__ import annotations

import pytest

from pb_hypernode_mcp.sanitization.commands import (
    generate_sanitization_commands,
    generate_url_setup_commands,
)
from pb_hypernode_mcp.sanitization.config import (
    DEFAULT_MAGENTO_SANITIZATION_CONFIG,
    GatewaySandboxSetting,
    PiiTableSanitizer,
    SanitizationConfig,
    SanitizationConfigError,
)


def _minimal_config(**overrides: object) -> SanitizationConfig:
    defaults: dict[str, object] = {
        'pii_tables': (
            PiiTableSanitizer(
                table='customer_entity',
                set_columns={'email': "'anon@example.invalid'"},
            ),
        ),
        'admin_user_reset': PiiTableSanitizer(
            table='admin_user',
            set_columns={'password': "'unused-in-this-test'"},
        ),
    }
    defaults.update(overrides)
    return SanitizationConfig(**defaults)  # type: ignore[arg-type]


def test_it_generates_sql_to_anonymize_customer_entity_pii_fields_per_the_config() -> None:
    config = _minimal_config(
        pii_tables=(
            PiiTableSanitizer(
                table='customer_entity',
                set_columns={
                    'email': "CONCAT('customer-', entity_id, '@example.invalid')",
                    'firstname': "'Anonymized'",
                    'lastname': "'Customer'",
                },
            ),
        ),
    )

    commands = generate_sanitization_commands(config)

    assert any(
        'UPDATE customer_entity SET' in cmd
        and "email = CONCAT('customer-', entity_id, '@example.invalid')" in cmd
        and "firstname = 'Anonymized'" in cmd
        and "lastname = 'Customer'" in cmd
        for cmd in commands
    )


def test_it_generates_sql_to_anonymize_sales_order_pii_fields_per_the_config() -> None:
    config = _minimal_config(
        pii_tables=(
            PiiTableSanitizer(
                table='sales_order',
                set_columns={
                    'customer_email': "CONCAT('order-', entity_id, '@example.invalid')",
                    'customer_firstname': "'Anonymized'",
                    'customer_lastname': "'Customer'",
                },
            ),
        ),
    )

    commands = generate_sanitization_commands(config)

    assert any(
        'UPDATE sales_order SET' in cmd
        and "customer_email = CONCAT('order-', entity_id, '@example.invalid')" in cmd
        and "customer_firstname = 'Anonymized'" in cmd
        and "customer_lastname = 'Customer'" in cmd
        for cmd in commands
    )


def test_it_generates_a_command_to_reset_admin_user_credentials_to_a_known_safe_default() -> None:
    config = _minimal_config(
        admin_user_reset=PiiTableSanitizer(
            table='admin_user',
            set_columns={
                'username': "'admin'",
                'email': "'admin@example.invalid'",
                'password': "'$2y$10$known.safe.default.hash'",
            },
        ),
    )

    commands = generate_sanitization_commands(config)

    assert any(
        'UPDATE admin_user SET' in cmd
        and "username = 'admin'" in cmd
        and "email = 'admin@example.invalid'" in cmd
        and "password = '$2y$10$known.safe.default.hash'" in cmd
        for cmd in commands
    )


def test_it_applies_a_second_where_scoped_admin_reset_after_the_bulk_one_when_configured() -> (
    None
):
    """VERIFIED (2026-08-20) against a real 15-row admin_user table: a bare
    literal username on a bulk (no-`where`) UPDATE violates admin_user's
    unique index the moment there's more than one admin row. The bulk pass
    must use a per-row-unique expression; `admin_primary_user_reset` then
    overrides exactly one row back to a literal, reportable identity."""
    config = _minimal_config(
        admin_user_reset=PiiTableSanitizer(
            table='admin_user',
            set_columns={'username': "CONCAT('admin-', user_id)"},
        ),
        admin_primary_user_reset=PiiTableSanitizer(
            table='admin_user',
            set_columns={'username': "'admin'"},
            where='user_id = (SELECT MIN(t.user_id) FROM (SELECT user_id FROM admin_user) AS t)',
        ),
    )

    commands = generate_sanitization_commands(config)

    bulk_index = next(i for i, cmd in enumerate(commands) if "CONCAT('admin-', user_id)" in cmd)
    primary_index = next(i for i, cmd in enumerate(commands) if "username = 'admin'" in cmd)

    # Bulk pass must run BEFORE the primary override, or the override would
    # be immediately clobbered back to a CONCAT value.
    assert bulk_index < primary_index
    assert 'WHERE user_id = (SELECT MIN(t.user_id)' in commands[primary_index]


def test_it_omits_the_primary_admin_reset_command_when_not_configured() -> None:
    config = _minimal_config()  # admin_primary_user_reset defaults to None

    commands = generate_sanitization_commands(config)

    assert not any('SELECT MIN(t.user_id)' in cmd for cmd in commands)


def test_it_generates_a_core_config_data_upsert_to_force_the_payment_gateway_to_sandbox_per_the_config() -> (  # noqa: E501
    None
):
    """VERIFIED (2026-08-20) against a real Braintree install:
    `bin/magento config:set` refused a genuinely real, actively-used config
    path with "doesn't exist" (it validates against system.xml-declared
    admin-UI fields, which don't always match reality). A raw
    `core_config_data` UPSERT writes the exact same underlying value
    Magento's runtime config reader actually consults, without that
    unrelated validation layer in the way."""
    config = _minimal_config(
        gateway_sandbox_settings=(
            GatewaySandboxSetting(
                config_path='payment/braintree/environment',
                sandbox_value='sandbox',
            ),
        ),
    )

    commands = generate_sanitization_commands(config)

    assert any(
        'INSERT INTO core_config_data' in cmd
        and "'default', 0, 'payment/braintree/environment', 'sandbox'" in cmd
        and 'ON DUPLICATE KEY UPDATE' in cmd
        for cmd in commands
    )


def test_it_generates_commands_to_stub_each_configured_third_party_api_key_to_a_sandbox_dummy_value() -> (  # noqa: E501
    None
):
    config = _minimal_config(
        api_key_stubs=(
            GatewaySandboxSetting(
                config_path='carriers/shipperhq/api_key',
                sandbox_value='sandbox-dummy-key',
            ),
            GatewaySandboxSetting(
                config_path='tax/avatax/license_key',
                sandbox_value='dummy-license-key',
            ),
        ),
    )

    commands = generate_sanitization_commands(config)

    assert any(
        "'default', 0, 'carriers/shipperhq/api_key', 'sandbox-dummy-key'" in cmd
        for cmd in commands
    )
    assert any(
        "'default', 0, 'tax/avatax/license_key', 'dummy-license-key'" in cmd for cmd in commands
    )


def test_it_sql_escapes_a_single_quote_in_a_sandbox_value_not_shell_escapes_it() -> None:
    config = _minimal_config(
        gateway_sandbox_settings=(
            GatewaySandboxSetting(config_path='some/config/path', sandbox_value="o'brien"),
        ),
    )

    commands = generate_sanitization_commands(config)

    assert any("'o''brien'" in cmd for cmd in commands)


def test_it_flushes_cache_once_after_gateway_and_api_key_upserts_so_they_actually_take_effect() -> (  # noqa: E501
    None
):
    config = _minimal_config(
        gateway_sandbox_settings=(
            GatewaySandboxSetting(
                config_path='payment/braintree/environment', sandbox_value='sandbox'
            ),
        ),
    )

    commands = generate_sanitization_commands(config)

    assert commands[-1] == 'cd current_root && bin/magento cache:flush'


def test_it_omits_the_trailing_cache_flush_when_there_are_no_gateway_or_api_key_settings() -> None:
    config = _minimal_config()  # no gateway_sandbox_settings, no api_key_stubs

    commands = generate_sanitization_commands(config)

    assert 'cd current_root && bin/magento cache:flush' not in commands


def test_it_skips_the_cd_current_root_prefix_when_magento_root_is_empty() -> None:
    config = _minimal_config(magento_root='')

    commands = generate_sanitization_commands(config)

    assert not any('current_root' in cmd for cmd in commands)
    assert any('UPDATE customer_entity SET' in cmd for cmd in commands)


def test_it_generates_commands_to_point_the_nodes_base_url_at_its_own_hostname() -> None:
    config = _minimal_config()

    commands = generate_url_setup_commands('myapp-eph123456.hypernode.io', config)

    assert (
        'cd current_root && bin/magento config:set --lock-env web/unsecure/base_url '
        'https://myapp-eph123456.hypernode.io/' in commands
    )
    assert (
        'cd current_root && bin/magento config:set --lock-env web/secure/base_url '
        'https://myapp-eph123456.hypernode.io/' in commands
    )
    assert 'cd current_root && bin/magento cache:flush' in commands


def test_it_also_overrides_base_url_at_each_configured_website_scope() -> None:
    """VERIFIED (2026-08-20) against a real Brancher node: the default-scope
    base_url alone wasn't enough -- the live site kept 301-redirecting back
    to the originating domain via a website-scoped env.php override that
    takes precedence for any request resolving through that website."""
    config = _minimal_config(base_url_website_scope_codes=('base',))

    commands = generate_url_setup_commands('myapp-eph123456.hypernode.io', config)

    assert (
        'cd current_root && bin/magento config:set --lock-env --scope=websites '
        '--scope-code=base web/unsecure/base_url https://myapp-eph123456.hypernode.io/'
        in commands
    )
    assert (
        'cd current_root && bin/magento config:set --lock-env --scope=websites '
        '--scope-code=base web/secure/base_url https://myapp-eph123456.hypernode.io/' in commands
    )


def test_it_skips_website_scope_base_url_overrides_when_no_scope_codes_are_configured() -> None:
    config = _minimal_config(base_url_website_scope_codes=())

    commands = generate_url_setup_commands('myapp-eph123456.hypernode.io', config)

    assert not any('--scope=websites' in cmd for cmd in commands)


def test_it_creates_a_vhost_for_the_node_when_vhost_webroot_is_configured() -> None:
    config = _minimal_config(vhost_webroot='/data/web/public', vhost_type='magento2')

    commands = generate_url_setup_commands('myapp-eph123456.hypernode.io', config)

    assert (
        "hypernode-manage-vhosts myapp-eph123456.hypernode.io --https --force-https "
        "--type magento2 --webroot /data/web/public" in commands
    )


def test_it_skips_vhost_creation_when_vhost_webroot_is_not_configured() -> None:
    config = _minimal_config(vhost_webroot=None)

    commands = generate_url_setup_commands('myapp-eph123456.hypernode.io', config)

    assert not any('hypernode-manage-vhosts' in cmd for cmd in commands)


def test_it_raises_a_clear_error_when_the_per_app_config_is_missing_required_fields() -> None:
    config = SanitizationConfig()

    with pytest.raises(SanitizationConfigError, match='pii_tables'):
        generate_sanitization_commands(config)


def test_it_produces_no_destructive_commands_drop_truncate_anonymization_only_never_data_structure_changes() -> (  # noqa: E501
    None
):
    config = DEFAULT_MAGENTO_SANITIZATION_CONFIG

    commands = generate_sanitization_commands(config)

    assert commands, 'expected the default Magento config to generate at least one command'

    for cmd in commands:
        upper_cmd = cmd.upper()
        assert 'DROP' not in upper_cmd
        assert 'TRUNCATE' not in upper_cmd
        assert 'DELETE' not in upper_cmd
        assert 'ALTER' not in upper_cmd
