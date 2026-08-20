"""Generates the ordered list of sanitization command strings for a Magento app.

Pure command/SQL generation — no I/O, no subprocess, no DB/SSH connection.
Task 010 is responsible for actually running the returned commands (via
`brancher_exec`) against a Brancher node.
"""

from __future__ import annotations

import shlex

from pb_hypernode_mcp.sanitization.config import (
    GatewaySandboxSetting,
    PiiTableSanitizer,
    SanitizationConfig,
    validate_config,
)

DB_QUERY_COMMAND = 'n98-magerun2 db:query'
CONFIG_SET_COMMAND = 'bin/magento config:set'
CACHE_FLUSH_COMMAND = 'bin/magento cache:flush'
VHOST_COMMAND = 'hypernode-manage-vhosts'
BASE_URL_UNSECURE_PATH = 'web/unsecure/base_url'
BASE_URL_SECURE_PATH = 'web/secure/base_url'


def _build_update_sql(sanitizer: PiiTableSanitizer) -> str:
    """Build a single anonymizing `UPDATE` statement, wrapped for shell execution.

    SECURITY: `sanitizer.table`, `set_columns` (both column names and SQL
    value literals), and `where` are interpolated into this SQL/shell string
    with no escaping beyond the surrounding double quotes. Not currently
    reachable by external/untrusted input — the only wired config is the
    hardcoded `DEFAULT_MAGENTO_SANITIZATION_CONFIG` (task 017 security
    review, flagged as a landmine). If a per-client/loaded `SanitizationConfig`
    is ever introduced (vs. hand-authored-in-code), every field here needs
    proper escaping (or an allowlist of table/column identifiers) before it
    can safely accept anything other than trusted, hardcoded config.
    """
    assignments = ', '.join(
        f'{column} = {value}' for column, value in sanitizer.set_columns.items()
    )
    sql = f'UPDATE {sanitizer.table} SET {assignments}'
    if sanitizer.where:
        sql += f' WHERE {sanitizer.where}'
    sql += ';'

    return f'{DB_QUERY_COMMAND} "{sql}"'


def _build_config_set_command(setting: GatewaySandboxSetting) -> str:
    """Build a raw `core_config_data` UPSERT that forces one config path to a sandbox value.

    VERIFIED (2026-08-20) against a real Braintree install: `bin/magento
    config:set` validates the path against system.xml-declared admin-UI
    fields and refused a genuinely real, actively-used config path
    (`payment/braintree/environment`) with "doesn't exist" -- even though
    that exact path already had a real row in `core_config_data` written by
    the app's own admin panel. Magento's runtime config reader
    (`ScopeConfigInterface`) reads raw DB rows directly and has no
    knowledge of system.xml at all, so a raw UPSERT achieves the actual
    sanitization goal (the live value a payment/tax integration will
    actually read) without fighting the CLI's unrelated admin-UI validation
    layer. `bin/magento config:set` is still used for `base_url` in
    `generate_url_setup_commands` above, since that needs its special
    `--lock-env` env.php-writing behavior, not just a plain DB write.

    SECURITY: `setting.config_path` is interpolated unescaped. Same
    landmine/caveat as `_build_update_sql` above — safe only because it
    currently only ever comes from the hardcoded default config, never
    external input. `sandbox_value` gets SQL-escaped (`'` doubled), which is
    NOT shell-escaping — this value is embedded inside a SQL string
    literal, not a shell argument.
    """
    escaped_value = setting.sandbox_value.replace("'", "''")
    sql = (
        f"INSERT INTO core_config_data (scope, scope_id, path, value) "
        f"VALUES ('default', 0, '{setting.config_path}', '{escaped_value}') "
        f"ON DUPLICATE KEY UPDATE value = '{escaped_value}';"
    )

    return f'{DB_QUERY_COMMAND} "{sql}"'


def _with_magento_root(config: SanitizationConfig, command: str) -> str:
    """Prefix a `bin/magento`/`n98-magerun2` command with `cd <magento_root> &&`.

    See `SanitizationConfig.magento_root`'s docstring for why this is
    necessary — the CLI binaries are not reachable from $HOME on a Hypernode
    Deploy-managed app. A falsy `magento_root` (empty string) means "run as
    given, no `cd`" for apps not using Hypernode Deploy.
    """
    if not config.magento_root:
        return command

    return f'cd {shlex.quote(config.magento_root)} && {command}'


def generate_url_setup_commands(hostname: str, config: SanitizationConfig) -> list[str]:
    """Return commands that point the node's base URL + nginx vhost at its own hostname.

    VERIFIED (2026-08-20) via docs.hypernode.com's "Brancher Install Hook"
    documentation: a freshly cloned Brancher node keeps the *originating*
    app's base URL, and no nginx vhost exists at all for the node's own new
    ephemeral hostname until one is created — browsing it serves nginx's
    default catch-all page, not the app. Also VERIFIED live: the default-
    scope base URL alone isn't enough — a real site kept 301-redirecting
    back to the old domain via a website-scoped `env.php` override that
    takes precedence (see `base_url_website_scope_codes`). Mirrors
    Hypernode's own documented example install hook (set base URLs, flush
    cache, then create the vhost), extended with the website-scope pass.

    `hostname` is always `<node_name>.hypernode.io` — trusted, not user
    input (`node_name` is already `-eph`-pattern-validated by the time this
    is called) — but still `shlex.quote()`-d as defense in depth alongside
    the rest of this module's commands.
    """
    base_url = f'https://{hostname}/'
    # --lock-env: VERIFIED (2026-08-20) against a real Brancher node --
    # base_url is a "locked" config value there (common on Hypernode
    # Deploy/CI-managed apps, to keep app/etc/env.php authoritative and
    # prevent DB drift). A plain `config:set` on a locked path fails with
    # "The value you set has already been locked." -- `--lock-env` both
    # writes AND (re-)locks it, and is a harmless no-op flag against a path
    # that was never locked in the first place.
    commands = [
        _with_magento_root(
            config,
            f'{CONFIG_SET_COMMAND} --lock-env {BASE_URL_UNSECURE_PATH} {shlex.quote(base_url)}',
        ),
        _with_magento_root(
            config,
            f'{CONFIG_SET_COMMAND} --lock-env {BASE_URL_SECURE_PATH} {shlex.quote(base_url)}',
        ),
    ]

    # VERIFIED (2026-08-20): the default-scope writes above are NOT enough
    # on their own -- a live site kept 301-redirecting back to the
    # originating domain because app/etc/env.php had a SEPARATE
    # website-scoped base_url override that wins over the default-scope
    # value for any request resolving through that website.
    for scope_code in config.base_url_website_scope_codes:
        for path in (BASE_URL_UNSECURE_PATH, BASE_URL_SECURE_PATH):
            commands.append(
                _with_magento_root(
                    config,
                    f'{CONFIG_SET_COMMAND} --lock-env --scope=websites '
                    f'--scope-code={shlex.quote(scope_code)} {path} {shlex.quote(base_url)}',
                )
            )

    commands.append(_with_magento_root(config, CACHE_FLUSH_COMMAND))

    if config.vhost_webroot:
        # NOT wrapped in `_with_magento_root` -- `hypernode-manage-vhosts` is
        # a system-wide Hypernode CLI tool, not a Magento binary, and takes
        # an absolute `--webroot` path already, so it is cwd-independent.
        commands.append(
            f'{VHOST_COMMAND} {shlex.quote(hostname)} --https --force-https '
            f'--type {shlex.quote(config.vhost_type)} --webroot {shlex.quote(config.vhost_webroot)}'
        )

    return commands


def generate_sanitization_commands(config: SanitizationConfig) -> list[str]:
    """Return the ordered list of shell command strings to sanitize an app.

    Ordering: PII table anonymization first, then admin user credential
    reset, then payment gateway sandbox-forcing, then third-party API key
    stubbing.
    """
    validate_config(config)

    commands: list[str] = []

    for table in config.pii_tables:
        commands.append(_with_magento_root(config, _build_update_sql(table)))

    if config.admin_user_reset is not None:
        commands.append(_with_magento_root(config, _build_update_sql(config.admin_user_reset)))

    if config.admin_primary_user_reset is not None:
        commands.append(
            _with_magento_root(config, _build_update_sql(config.admin_primary_user_reset))
        )

    for setting in config.gateway_sandbox_settings:
        commands.append(_with_magento_root(config, _build_config_set_command(setting)))

    for stub in config.api_key_stubs:
        commands.append(_with_magento_root(config, _build_config_set_command(stub)))

    # The gateway/api-key commands above write config directly to
    # core_config_data (see `_build_config_set_command`'s docstring) rather
    # than through `bin/magento config:set`, which would normally trigger
    # its own cache invalidation. A trailing flush guarantees the sandboxed
    # values are actually served, not a stale cached config.
    if config.gateway_sandbox_settings or config.api_key_stubs:
        commands.append(_with_magento_root(config, CACHE_FLUSH_COMMAND))

    return commands
