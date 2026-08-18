"""Per-app sanitization config for Magento/Mage-OS Brancher nodes.

Config-driven so a real client's exact table/column shape and configured
third-party integrations can override/extend the Magento-shaped default
below, without this package hardcoding one client's schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class SanitizationConfigError(ValueError):
    """Raised when a per-app `SanitizationConfig` is missing required fields."""


@dataclass(frozen=True)
class PiiTableSanitizer:
    """Describes an anonymizing `UPDATE` for a single database table.

    `set_columns` maps column name -> a raw SQL value expression (already
    quoted/escaped by the caller, e.g. `"'Anonymized'"` or
    `"CONCAT('customer-', entity_id, '@example.invalid')"`).
    """

    table: str
    set_columns: dict[str, str]
    where: str | None = None


@dataclass(frozen=True)
class GatewaySandboxSetting:
    """A single `bin/magento config:set <config_path> <value>` call."""

    config_path: str
    sandbox_value: str


@dataclass(frozen=True)
class SanitizationConfig:
    """Per-app sanitization config: PII tables to anonymize + gateways/API keys to sandbox."""

    pii_tables: tuple[PiiTableSanitizer, ...] = ()
    admin_user_reset: PiiTableSanitizer | None = None
    gateway_sandbox_settings: tuple[GatewaySandboxSetting, ...] = field(default=())
    api_key_stubs: tuple[GatewaySandboxSetting, ...] = field(default=())


def validate_config(config: SanitizationConfig) -> None:
    """Raise `SanitizationConfigError` if `config` is missing required fields.

    `pii_tables` and `admin_user_reset` are required — without them
    sanitization would silently no-op and leave live customer/admin data on
    a public `-eph` URL. `gateway_sandbox_settings`/`api_key_stubs` are
    optional (a client app may have no third-party integrations to stub).
    """
    missing: list[str] = []

    if not config.pii_tables:
        missing.append('pii_tables')

    if config.admin_user_reset is None:
        missing.append('admin_user_reset')

    if missing:
        raise SanitizationConfigError(
            f'SanitizationConfig is missing required field(s): {", ".join(missing)}.'
        )


# Sensible Magento-shaped default. A real client app's config should override/extend
# this (different table shapes, different installed gateways/integrations) rather than
# relying on these exact values in production — this default exists so v1 has a
# working, safe-by-default config out of the box.
_ANONYMIZED_EMAIL = "CONCAT(entity_id, '-sanitized@example.invalid')"
_ANONYMIZED_NAME = "'Anonymized'"
_ANONYMIZED_PHONE = "'555-0100'"
_ANONYMIZED_STREET = "'123 Example St'"

DEFAULT_MAGENTO_SANITIZATION_CONFIG = SanitizationConfig(
    pii_tables=(
        PiiTableSanitizer(
            table='customer_entity',
            set_columns={
                'email': _ANONYMIZED_EMAIL,
                'firstname': _ANONYMIZED_NAME,
                'lastname': _ANONYMIZED_NAME,
                'dob': 'NULL',
                'taxvat': 'NULL',
            },
        ),
        PiiTableSanitizer(
            table='customer_address_entity',
            set_columns={
                'firstname': _ANONYMIZED_NAME,
                'lastname': _ANONYMIZED_NAME,
                'street': _ANONYMIZED_STREET,
                'telephone': _ANONYMIZED_PHONE,
                'company': 'NULL',
            },
        ),
        PiiTableSanitizer(
            table='sales_order',
            set_columns={
                'customer_email': _ANONYMIZED_EMAIL,
                'customer_firstname': _ANONYMIZED_NAME,
                'customer_lastname': _ANONYMIZED_NAME,
            },
        ),
        PiiTableSanitizer(
            table='sales_order_address',
            set_columns={
                'firstname': _ANONYMIZED_NAME,
                'lastname': _ANONYMIZED_NAME,
                'street': _ANONYMIZED_STREET,
                'telephone': _ANONYMIZED_PHONE,
                'email': _ANONYMIZED_EMAIL,
            },
        ),
        PiiTableSanitizer(
            table='quote_payment',
            set_columns={
                'cc_number_enc': 'NULL',
                'cc_cid_enc': 'NULL',
                'cc_owner': 'NULL',
                'additional_data': 'NULL',
            },
        ),
        PiiTableSanitizer(
            table='sales_order_payment',
            set_columns={
                'cc_number_enc': 'NULL',
                'cc_cid_enc': 'NULL',
                'cc_owner': 'NULL',
                'cc_trans_id': 'NULL',
                'additional_data': 'NULL',
            },
        ),
    ),
    admin_user_reset=PiiTableSanitizer(
        table='admin_user',
        set_columns={
            'username': "'admin'",
            'email': "'admin@example.invalid'",
            # Magento password hashes use the `<sha256-hash>:<salt>:1` format
            # (version 1, SHA-256) — this placeholder is NOT a valid hash for any
            # real password; it deliberately locks form-based admin login until a
            # real operator generates a proper hash for the target Magento version
            # (e.g. via `bin/magento admin:user:create`). The goal here is only to
            # guarantee the live production admin password can never be reached on
            # a public `-eph` URL.
            'password': "'0000000000000000000000000000000000000000000000000000000000000000:na:1'",
            'failures_num': '0',
            'lock_expires': 'NULL',
        },
    ),
    gateway_sandbox_settings=(
        GatewaySandboxSetting(
            config_path='payment/braintree/environment',
            sandbox_value='sandbox',
        ),
        GatewaySandboxSetting(
            config_path='paypal/general/sandbox_flag',
            sandbox_value='1',
        ),
    ),
    api_key_stubs=(
        GatewaySandboxSetting(
            config_path='carriers/shipperhq/api_key',
            sandbox_value='sandbox-dummy-key',
        ),
        GatewaySandboxSetting(
            config_path='tax/avatax/account_number',
            sandbox_value='sandbox-dummy-account',
        ),
        GatewaySandboxSetting(
            config_path='tax/avatax/license_key',
            sandbox_value='sandbox-dummy-license-key',
        ),
    ),
)
