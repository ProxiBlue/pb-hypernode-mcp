"""Per-app sanitization config for Magento/Mage-OS Brancher nodes.

Config-driven so a real client's exact table/column shape and configured
third-party integrations can override/extend the Magento-shaped default
below, without this package hardcoding one client's schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class SanitizationConfigError(ValueError):
    """Raised when a per-app `SanitizationConfig` is missing required fields."""


# Single source of truth for the admin login handed back to the caller after
# spin-up — referenced both by the SQL literal below and by
# `spinup_sanitized_brancher_node`'s reported `admin_username`/`admin_email`,
# so the two can never drift apart.
ADMIN_RESET_USERNAME = 'admin'
ADMIN_RESET_EMAIL = 'admin@example.invalid'


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

    # VERIFIED (2026-08-20) against a real Brancher node: a plain
    # `admin_user_reset` UPDATE with no `where` clause hits every row in
    # `admin_user` -- fine for one admin, but a real account had 15 rows,
    # and forcing them all to the SAME literal `username='admin'` violated
    # `admin_user`'s unique index (`ERROR 1062 Duplicate entry`). Applied
    # AFTER `admin_user_reset` (which should itself use a per-row-unique
    # expression, e.g. `CONCAT('admin-', user_id)`, not a bare literal) --
    # this second, `where`-scoped reset then overrides exactly the
    # lowest-`user_id` row back to the literal `admin_reset_username`/
    # `admin_reset_email` below, so there is always exactly one guaranteed,
    # reportable, known-value login.
    admin_primary_user_reset: PiiTableSanitizer | None = None

    gateway_sandbox_settings: tuple[GatewaySandboxSetting, ...] = field(default=())
    api_key_stubs: tuple[GatewaySandboxSetting, ...] = field(default=())

    # Reported back to the caller as `admin_username`/`admin_email` after
    # spin-up — must match whatever `admin_user_reset` actually sets.
    admin_reset_username: str = ADMIN_RESET_USERNAME
    admin_reset_email: str = ADMIN_RESET_EMAIL

    # VERIFIED (2026-08-20) via docs.hypernode.com's own "Brancher Install
    # Hook" documentation: a freshly cloned Brancher node keeps the
    # ORIGINATING app's base URL and has no nginx vhost at all for its own
    # new ephemeral hostname until one is created — browsing a brand new
    # node serves nginx's default catch-all page, not the app. Hypernode's
    # documented fix is exactly the 4 commands `generate_url_setup_commands`
    # below builds: two `config:set` calls for the base URLs, a cache flush,
    # then `hypernode-manage-vhosts`.
    #
    # `/data/web` is a fixed, Hypernode-platform-wide home directory on every
    # node (not client-specific), so `/data/web/public` is a safe default for
    # Hypernode's standard single-app Magento 2 layout. A client using
    # Hypernode's multi-app-per-domain layout (`~/apps/<domain>/current/pub`)
    # must override this field; set it to None to skip vhost/base-URL setup
    # entirely.
    vhost_webroot: str | None = '/data/web/public'
    vhost_type: str = 'magento2'

    # VERIFIED (2026-08-20) against a real Brancher node: `bin/magento` is
    # NOT at `$HOME/bin/magento` -- that path exists but is an unrelated
    # Hypernode tool (`ecomscan`). Both `bin/magento` and `n98-magerun2`
    # need to run from inside the active Hypernode Deploy release, reached
    # via the `current_root` symlink Hypernode Deploy maintains at $HOME.
    # Running `n98-magerun2 db:query` from $HOME fails outright ("DB
    # settings was not found in app/etc/env.php file").
    #
    # Set to `''` (empty string) to skip the `cd` entirely for an app NOT
    # using Hypernode Deploy, where `bin/magento` sits directly at $HOME.
    magento_root: str = 'current_root'

    # VERIFIED (2026-08-20) against a real Brancher node: a fresh vhost
    # created by `hypernode-manage-vhosts` does NOT inherit the parent
    # app's own HTTP Basic Auth. Per docs.hypernode.com's "How to Protect
    # Your Magento Store With a Password in Nginx", `/data/web/nginx/`
    # (app-owned, under $HOME) is Hypernode's own self-service nginx-
    # include directory -- `generate_basic_auth_gate_commands()` writes an
    # `htpasswd` file and a `server.basicauth` snippet there, scoped to
    # exactly this node's own hostname.
    #
    # Set to `None` to disable -- e.g. for a client already comfortable
    # with an unauthenticated preview URL.
    basic_auth_username: str | None = 'preview'

    # A genuinely usable admin login, created fresh on every node via
    # `bin/magento admin:user:create` with a random password -- distinct
    # from `admin_user_reset`/`admin_primary_user_reset` above, which
    # deliberately LOCK the sanitized original admin account rather than
    # leave a real, guessable login. A separate username (not 'admin',
    # which the reset steps already renamed the original account to) avoids
    # any collision with that renamed row. `None` disables -- the caller
    # then falls back to the `admin_password_note` instructions to set one
    # up manually via SSH.
    preview_admin_username: str | None = 'preview'

    # VERIFIED (2026-08-20) against a real Brancher node: setting base_url
    # at the default scope was NOT enough -- the live site still 301-
    # redirected back to the originating app's domain. `app/etc/env.php`
    # had a SEPARATE `websites.base.web.{secure,unsecure}.base_url`
    # override still pointing at the old domain, which wins over the
    # default-scope value for any request resolving through that website.
    # 'base' is Magento's own genuine default website code (every stock
    # install has it, not something a client customizes at that level), so
    # it's a safe default to always also override -- NOT a guess specific
    # to this account. A client with additional non-default website codes
    # must extend this tuple; empty tuple skips website-scope overrides.
    base_url_website_scope_codes: tuple[str, ...] = ('base',)

    # Same override, but for `stores`-scoped `env.php` config -- a
    # DIFFERENT scope type than `base_url_website_scope_codes` above, not a
    # duplicate. VERIFIED (2026-08-20) against a real Brancher node:
    # `env.php` also had a `stores.admin.web.{secure,unsecure}.base_url`
    # override still pointing at the old domain. 'admin' is Magento's own
    # reserved store code for the admin area (present on every install),
    # so overriding it is safe/general, not account-specific. Empty tuple
    # skips this pass.
    base_url_admin_store_scope_codes: tuple[str, ...] = ('admin',)

    # VERIFIED (2026-08-20) against a real Brancher node: THE root cause of
    # an admin login that 404s even though everything else (storefront,
    # vhost, base_url, Basic Auth, the real admin login) is correctly
    # wired. Magento has a SEPARATE, DB-driven admin URL override
    # (`admin/url/use_custom` + `admin/url/custom`, distinct from
    # `backend.frontName`/env.php) -- when enabled, Magento's admin router
    # refuses to serve the admin area on any hostname other than the
    # configured custom one (a real production admin subdomain in this
    # case), which a Brancher node's ephemeral hostname can never match.
    # Always disabled (not a config toggle): a stale custom-admin-domain
    # override is never correct on an ephemeral node, so there's no
    # legitimate reason to keep it enabled here the way, say, ShipperHQ's
    # live API key is deliberately left alone.
    disable_custom_admin_url: bool = True

    # VERIFIED (2026-08-21): the admin path (`backend.frontName` in
    # env.php) is set once at Magento install time and does not change
    # between Brancher clones of the same source app -- it never needed
    # per-spin-up runtime discovery in the first place. Dynamically
    # resolving it via `info:adminuri` right after sanitization (see
    # `_resolve_admin_path`) chases a genuine Hypernode-side async
    # clone-sync race with no reliable upper bound -- three rounds of
    # timing fixes (confirm-twice, settle delay, CLI tool switch, longer
    # settle delay) all failed to fully close it, most recently confirmed
    # live even with a 90s settle delay in place. If the client's admin
    # path is already known (check once via SSH after any spin-up, or from
    # existing documentation), set it here to skip runtime discovery
    # entirely -- eliminates the whole race, not just narrows it. Format
    # matches what `_resolve_admin_path` itself would have returned: a
    # leading-slash path with no scheme/host (e.g. `/admin-uptactics`), not
    # a full URL. `None` (the default) falls back to the existing
    # best-effort dynamic resolution for a first-time/unknown app.
    known_admin_path: str | None = None

    # A client's AI will make code edits over SSH against this node --
    # `generate_git_baseline_commands` initializes (or reuses, if
    # Hypernode Deploy already manages this app via git) a local repo,
    # writes an `AI_INSTRUCTIONS.md` explaining the environment/branch
    # purpose/limits, and commits a clean baseline snapshot on
    # `git_baseline_branch` -- so every edit made afterward is diffable
    # (`git diff`/`git log`) against a known-good starting point, giving
    # the developer a real audit trail of exactly what the AI changed.
    # `False` disables this entirely (e.g. a client that already has their
    # own change-tracking mechanism).
    git_baseline_enabled: bool = True
    git_baseline_branch: str = 'brancher-preview'


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
                # VERIFIED (2026-08-20) against a real Magento schema:
                # `sales_order_payment` has no `cc_cid_enc` column at all
                # (unlike `quote_payment` above) -- CVV/CID is never stored
                # post-order per PCI-DSS, so Magento core never added the
                # column here. Including it broke every sanitization run
                # with "Unknown column 'cc_cid_enc' in 'field list'".
                'cc_number_enc': 'NULL',
                'cc_owner': 'NULL',
                'cc_trans_id': 'NULL',
                'additional_data': 'NULL',
            },
        ),
    ),
    admin_user_reset=PiiTableSanitizer(
        table='admin_user',
        set_columns={
            # Per-row-unique (not a bare literal) -- `admin_user.username`
            # carries a unique index, so a bare 'admin' literal here would
            # violate it on any account with more than one admin row.
            # `admin_primary_user_reset` below then overrides exactly one
            # row back to the literal, reportable `admin`/
            # `admin@example.invalid` identity.
            'username': "CONCAT('admin-', user_id)",
            'email': "CONCAT('admin-', user_id, '-sanitized@example.invalid')",
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
    admin_primary_user_reset=PiiTableSanitizer(
        table='admin_user',
        set_columns={
            'username': f"'{ADMIN_RESET_USERNAME}'",
            'email': f"'{ADMIN_RESET_EMAIL}'",
        },
        # Double-wrapped derived-table subquery: MySQL/MariaDB reject a bare
        # correlated subquery on the SAME table being updated ("can't
        # specify target table for update in FROM clause") -- the extra
        # `(SELECT user_id FROM admin_user) AS t` layer sidesteps that.
        # VERIFIED (2026-08-20) against a real 15-row admin_user table.
        where='user_id = (SELECT MIN(t.user_id) FROM (SELECT user_id FROM admin_user) AS t)',
    ),
    # `paypal/general/sandbox_flag` deliberately NOT included: VERIFIED
    # (2026-08-20) against a real Magento 2.4.9 install that this path does
    # not exist at all -- no `sandbox_flag` field anywhere under
    # `paypal/general/*` on a current Magento version (legacy PayPal
    # Standard/Express convention). PayPal payments on a real account run
    # entirely through Braintree's own `braintree_paypal` integration,
    # already covered by `payment/braintree/environment` below.
    gateway_sandbox_settings=(
        GatewaySandboxSetting(
            config_path='payment/braintree/environment',
            sandbox_value='sandbox',
        ),
    ),
    # ShipperHQ deliberately NOT stubbed here (explicit client decision,
    # 2026-08-20): its API key stays on the live/production setting on every
    # Brancher node. Unlike a payment gateway or tax API, ShipperHQ has no
    # notion of "developer mode" that this plugin needs to force it into.
    api_key_stubs=(
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
