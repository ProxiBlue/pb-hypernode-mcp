"""Tests for sanitization command/SQL generation."""

from __future__ import annotations

import pytest

from pb_hypernode_mcp.sanitization.commands import generate_sanitization_commands
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


def test_it_generates_a_bin_magento_config_set_command_to_force_the_payment_gateway_to_sandbox_per_the_config() -> (  # noqa: E501
    None
):
    config = _minimal_config(
        gateway_sandbox_settings=(
            GatewaySandboxSetting(
                config_path='payment/braintree/environment',
                sandbox_value='sandbox',
            ),
        ),
    )

    commands = generate_sanitization_commands(config)

    assert 'bin/magento config:set payment/braintree/environment sandbox' in commands


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

    assert 'bin/magento config:set carriers/shipperhq/api_key sandbox-dummy-key' in commands
    assert 'bin/magento config:set tax/avatax/license_key dummy-license-key' in commands


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
