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
ADMIN_USER_CREATE_COMMAND = 'bin/magento admin:user:create'
BASE_URL_UNSECURE_PATH = 'web/unsecure/base_url'
BASE_URL_SECURE_PATH = 'web/secure/base_url'
ADMIN_URL_USE_CUSTOM_PATH = 'admin/url/use_custom'

# VERIFIED (2026-08-20) via docs.hypernode.com's "How to Protect Your
# Magento Store With a Password in Nginx": app-owned (under $HOME),
# Hypernode's own nginx generation automatically includes files placed
# here for every vhost -- unlike `/etc/nginx/app/<hostname>/`, which is
# root-owned and has no self-service write path at all.
NGINX_INCLUDE_DIR = '/data/web/nginx'

AI_INSTRUCTIONS_FILENAME = 'AI_INSTRUCTIONS.md'
GIT_BASELINE_COMMIT_MESSAGE = 'Baseline snapshot before AI-assisted edits'
# Build artifacts, not source -- excluded from the baseline commit so `git
# add -A` stays fast and the repo stays small, regardless of whether this
# app's own `.gitignore` (if any) already covers them. Paths are relative to
# `config.magento_root`, matching every other command in this module.
GIT_EXCLUDED_PATHS = ('vendor', 'generated', 'var', 'pub/static', 'pub/media', 'node_modules')


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


def _build_htpasswd_command(username: str, password: str) -> str:
    """Create/overwrite the node's htpasswd file via `htpasswd -cb`.

    VERIFIED (2026-08-20) via docs.hypernode.com's "How to Protect Your
    Magento Store With a Password in Nginx": `/data/web/nginx/` is
    Hypernode's own documented self-service nginx-include directory --
    app-owned (it's under $HOME, unlike `/etc/nginx/app/<hostname>/`,
    which this session confirmed is root-owned and has no self-service
    write path at all). `-b` supplies the password non-interactively
    (`htpasswd` normally prompts); `-c` creates/overwrites the file, which
    is correct here since each Brancher node gets a freshly generated
    password and this file should never carry a stale one forward.
    """
    return (
        f'htpasswd -cb {NGINX_INCLUDE_DIR}/htpasswd '
        f'{shlex.quote(username)} {shlex.quote(password)}'
    )


def _build_basic_auth_nginx_snippet(hostname: str) -> str:
    """Nginx snippet restricting Basic Auth to exactly this node's own hostname.

    Mirrors docs.hypernode.com's "Restricting Access to a Specific Domain"
    example: keys off `$http_host` so it protects only THIS Brancher node's
    ephemeral hostname, not any other vhost that might exist on the same
    underlying filesystem (e.g. a stale leftover vhost from a prior
    Brancher run on the same box, seen earlier this session).
    """
    return (
        f'if ($http_host = "{hostname}") {{ set $pb_auth_basic "Restricted preview"; }}\n'
        f'if ($http_host != "{hostname}") {{ set $pb_auth_basic off; }}\n'
        'auth_basic $pb_auth_basic;\n'
        f'auth_basic_user_file {NGINX_INCLUDE_DIR}/htpasswd;\n'
    )


def generate_basic_auth_gate_commands(
    hostname: str, config: SanitizationConfig, password: str
) -> list[str]:
    """Build the commands that install HTTP Basic Auth for this node's hostname.

    VERIFIED (2026-08-20) against a real Brancher node: the parent app's
    own vhost has Basic Auth active, but a vhost freshly created by
    `hypernode-manage-vhosts` does NOT inherit it. `hypernode-manage-vhosts
    --help` has no such flag, `hypernode-systemctl settings` has no
    basic-auth key, and `/etc/nginx/app/<hostname>/` is root-owned -- see
    `SanitizationConfig.basic_auth_username`'s docstring. This is NOT a
    workaround, it's Hypernode's own documented self-service mechanism for
    exactly this (see `_build_htpasswd_command`'s docstring for the source).

    Runs BEFORE `hypernode-manage-vhosts` creates the vhost in
    `generate_url_setup_commands` below, so nginx's config generation for
    the new vhost picks up the include from its very first write rather
    than needing a second regeneration pass.

    Uses a quoted heredoc terminator (`'PBHTPASSWDEOF'`) to write
    `server.basicauth` -- required so the shell does NOT try to expand
    `$http_host`/`$pb_auth_basic` as its OWN variables (they're nginx
    variables, meaningless to the shell, and would silently expand to
    empty strings otherwise, corrupting the auth rule).

    Returns `[]` if `config.basic_auth_username` is unset (feature
    disabled).
    """
    if not config.basic_auth_username:
        return []

    snippet = _build_basic_auth_nginx_snippet(hostname)
    write_snippet_command = (
        f'cat > {NGINX_INCLUDE_DIR}/server.basicauth << \'PBHTPASSWDEOF\'\n'
        f'{snippet}'
        'PBHTPASSWDEOF'
    )

    return [
        _build_htpasswd_command(config.basic_auth_username, password),
        write_snippet_command,
    ]


def generate_url_setup_commands(
    hostname: str, config: SanitizationConfig, basic_auth_password: str | None = None
) -> list[str]:
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

    # Same fix, different scope TYPE (`stores`, not `websites`) -- env.php
    # can carry an independent stale override for the admin store scope.
    #
    # VERIFIED (2026-08-20) against a real Brancher node: `base_url` alone
    # was NOT enough here either -- the admin login rendered completely
    # unstyled. Unlike the default/website scopes (where base_link_url/
    # base_static_url/base_media_url are `{{secure_base_url}}...`
    # TEMPLATES that auto-resolve once base_url is correct), this
    # account's `stores.admin` scope had all three MATERIALIZED as literal
    # hardcoded URLs pointing at the old domain -- so each needs its own
    # explicit override; fixing base_url alone left the template-free
    # siblings stale.
    admin_store_scope_web_paths = (
        ('unsecure', 'base_url', base_url),
        ('secure', 'base_url', base_url),
        ('unsecure', 'base_link_url', base_url),
        ('secure', 'base_link_url', base_url),
        ('unsecure', 'base_static_url', f'{base_url}static/'),
        ('secure', 'base_static_url', f'{base_url}static/'),
        ('unsecure', 'base_media_url', f'{base_url}media/'),
        ('secure', 'base_media_url', f'{base_url}media/'),
    )
    for scope_code in config.base_url_admin_store_scope_codes:
        for area, suffix, value in admin_store_scope_web_paths:
            commands.append(
                _with_magento_root(
                    config,
                    f'{CONFIG_SET_COMMAND} --lock-env --scope=stores '
                    f'--scope-code={shlex.quote(scope_code)} web/{area}/{suffix} '
                    f'{shlex.quote(value)}',
                )
            )

    # VERIFIED (2026-08-20): THE actual cause of an admin login that 404s
    # on an otherwise-fully-working node -- see
    # `SanitizationConfig.disable_custom_admin_url`'s docstring. Raw SQL
    # UPSERT (same reasoning as `_build_config_set_command`): this needs to
    # take effect regardless of whether `admin/url/use_custom` is declared
    # in an enabled module's system.xml.
    if config.disable_custom_admin_url:
        sql = (
            f"INSERT INTO core_config_data (scope, scope_id, path, value) "
            f"VALUES ('default', 0, '{ADMIN_URL_USE_CUSTOM_PATH}', '0') "
            f"ON DUPLICATE KEY UPDATE value = '0';"
        )
        commands.append(_with_magento_root(config, f'{DB_QUERY_COMMAND} "{sql}"'))

    commands.append(_with_magento_root(config, CACHE_FLUSH_COMMAND))

    # Runs BEFORE the vhost is created below, so nginx's config generation
    # for the new vhost picks up the Basic Auth include from its very first
    # write. See `generate_basic_auth_gate_commands`'s docstring for why
    # this exists at all (Hypernode's own documented self-service
    # mechanism -- not something `hypernode-manage-vhosts` sets up itself).
    if config.basic_auth_username and basic_auth_password:
        commands.extend(
            generate_basic_auth_gate_commands(hostname, config, basic_auth_password)
        )

    if config.vhost_webroot:
        # NOT wrapped in `_with_magento_root` -- `hypernode-manage-vhosts` is
        # a system-wide Hypernode CLI tool, not a Magento binary, and takes
        # an absolute `--webroot` path already, so it is cwd-independent.
        commands.append(
            f'{VHOST_COMMAND} {shlex.quote(hostname)} --https --force-https '
            f'--type {shlex.quote(config.vhost_type)} --webroot {shlex.quote(config.vhost_webroot)}'
        )

    return commands


def generate_admin_user_command(config: SanitizationConfig, password: str) -> str | None:
    """Build the `bin/magento admin:user:create` call that provisions a real,
    usable admin login for this node.

    Deliberately a DIFFERENT username than `admin_user_reset`/
    `admin_primary_user_reset` produce (which rename+lock the ORIGINAL
    account) -- creating a brand new row avoids any collision with that
    renamed one, and keeps "the account we deliberately locked" and "the
    account we deliberately handed out" unambiguous.

    Returns `None` if `config.preview_admin_username` is unset (feature
    disabled).
    """
    if not config.preview_admin_username:
        return None

    username = config.preview_admin_username
    email = f'{username}@example.invalid'
    command = (
        f'{ADMIN_USER_CREATE_COMMAND} --admin-user={shlex.quote(username)} '
        f'--admin-password={shlex.quote(password)} --admin-email={shlex.quote(email)} '
        '--admin-firstname=Preview --admin-lastname=Admin'
    )

    return _with_magento_root(config, command)


def _build_ai_instructions_content(hostname: str, config: SanitizationConfig) -> str:
    """Build the `AI_INSTRUCTIONS.md` content committed alongside the git baseline.

    Written for the AI making SSH-driven edits on this node, not the human
    operator -- explains what this environment is, why the git branch
    exists, and what NOT to do, so an AI unfamiliar with this specific
    setup doesn't need to rediscover any of it by trial and error.
    """
    access_url = f'https://{hostname}/'
    excluded = ', '.join(f'`{path}`' for path in GIT_EXCLUDED_PATHS)

    return (
        '# AI Instructions -- Brancher Preview Environment\n'
        '\n'
        '## What this is\n'
        f'This is a disposable Hypernode Brancher preview node ({hostname}), cloned from '
        'production and automatically sanitized (customer/sales PII anonymized, payment '
        'gateways sandboxed where configured, admin credentials reset) before you were given '
        'access. It is NOT production and NOT permanent.\n'
        '\n'
        '## Purpose of this git branch\n'
        f'Every file in this checkout was committed to the `{config.git_baseline_branch}` '
        'branch as a baseline snapshot immediately after sanitization completed. Make your '
        'edits normally on this branch -- `git diff`/`git log` against this baseline is how '
        'the developer will review exactly what you changed during this preview session. Do '
        'not create or switch to a different branch for this work.\n'
        '\n'
        '## Limits\n'
        '- This node is EPHEMERAL and will be deleted -- do not treat any state here as '
        'persistent.\n'
        '- Sales/customer data has already been anonymized -- do not attempt to restore or '
        'reference real customer data.\n'
        '- Payment gateways and tax APIs run in SANDBOX mode where configured -- expect '
        'sandbox behaviour, not live transactions.\n'
        '- Some third-party integrations may intentionally still use live production '
        'credentials (a deliberate operator decision, not an oversight) -- be mindful of '
        'real API usage/cost before assuming everything here is a sandbox.\n'
        f'- {excluded} are NOT tracked on this branch (excluded from the baseline commit) -- '
        'they are build artifacts, not source. Editing inside them will not show up in `git '
        'diff`.\n'
        '- Do NOT push this branch anywhere -- it is local-only, for diff/audit purposes on '
        'this node.\n'
        f'- This site is served at {access_url}, specific to THIS node -- do not hardcode the '
        'original production domain into any config you change.\n'
    )


def generate_git_baseline_commands(hostname: str, config: SanitizationConfig) -> list[str]:
    """Write `AI_INSTRUCTIONS.md` and commit a clean git baseline snapshot.

    Initializes a git repo at `config.magento_root` if one doesn't already
    exist (a Hypernode Deploy-managed app may already have one, in which
    case this reuses it rather than destroying its history), strips any
    configured remote (defense against an AI later accidentally pushing to
    a real origin), then checks out `config.git_baseline_branch` and commits
    every file EXCEPT `GIT_EXCLUDED_PATHS` -- giving a client's AI a known-
    good starting point to diff its own SSH-driven edits against.

    Runs LAST in the overall sanitization sequence (after every other
    command has already succeeded), so the baseline snapshot reflects the
    node's genuinely final, fully-sanitized state -- not an intermediate one.

    `--allow-empty` on the commit guarantees this never fails with "nothing
    to commit" (e.g. a from-scratch `git init` with no exclusions matching
    anything unusual) -- every other command here is similarly written to
    always exit 0, since a non-zero exit from ANY sanitization command
    raises `SanitizationFailedError` and withholds the node.

    Returns `[]` if `config.git_baseline_enabled` is `False`.
    """
    if not config.git_baseline_enabled:
        return []

    instructions = _build_ai_instructions_content(hostname, config)
    write_instructions_command = _with_magento_root(
        config,
        f"cat > {shlex.quote(AI_INSTRUCTIONS_FILENAME)} << 'PBAIINSTRUCTIONSEOF'\n"
        f'{instructions}'
        'PBAIINSTRUCTIONSEOF',
    )

    exclude_pathspecs = ' '.join(f"':!{path}'" for path in GIT_EXCLUDED_PATHS)
    branch = shlex.quote(config.git_baseline_branch)

    return [
        write_instructions_command,
        _with_magento_root(
            config,
            'git rev-parse --is-inside-work-tree > /dev/null 2>&1 || git init',
        ),
        _with_magento_root(
            config,
            'git remote | xargs -r -n1 git remote remove > /dev/null 2>&1 || true',
        ),
        _with_magento_root(config, f'git checkout -B {branch}'),
        _with_magento_root(config, f'git add -A -- . {exclude_pathspecs}'),
        _with_magento_root(
            config,
            "git -c user.email='brancher-preview@localhost' -c user.name='Brancher Preview' "
            f"commit --allow-empty -m {shlex.quote(GIT_BASELINE_COMMIT_MESSAGE)}",
        ),
    ]


def generate_sanitization_commands(
    config: SanitizationConfig, admin_password: str | None = None
) -> list[str]:
    """Return the ordered list of shell command strings to sanitize an app.

    Ordering: PII table anonymization first, then admin user credential
    reset (lock the original account, then provision a real usable one),
    then payment gateway sandbox-forcing, then third-party API key
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

    if config.preview_admin_username and admin_password:
        admin_user_command = generate_admin_user_command(config, admin_password)
        if admin_user_command is not None:
            commands.append(admin_user_command)

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
