# Task 009: Magento Sanitization + Gateway-Sandbox Module

**Status**: completed
**Depends on**: 007
**Retry count**: 0

## Description
Build the config-driven sanitization module that strips client PII from the database and forces payment gateways and other live third-party API keys (ShipperHQ, AvaTax, etc.) into sandbox/dummy mode. This is the mandatory safety layer — the entire reason `brancher_create` cannot hand back a "ready" node without running this first (wired in by task 010).

## Context
- Runs its commands via `brancher_exec` (task 007) against the target Brancher node — this module generates the command sequence, it doesn't need its own SSH transport.
- Config-driven even though v1 targets Magento only: a per-app config (table/column list for PII, list of gateway/API config paths to stub) since exact schema/integrations differ per client Magento install. Ship a sensible Magento-shaped default config, but don't hardcode one client's exact table names as the only supported shape.
- PII classes to cover at minimum (from this session's scope decision): `customer_entity` (+ address/EAV tables), `sales_order*` (customer name/email/address/payment info), `quote_payment`/`sales_order_payment` (any stored card/token references), admin user credentials (`admin_user` — reset to a known safe default, don't just leave live admin passwords active on a public URL).
- Gateway/API sandboxing: `bin/magento config:set` calls to flip payment gateway (e.g. `payment/braintree/environment` → `sandbox`) and any configured live API keys (ShipperHQ, AvaTax) to sandbox/dummy values, per the per-app config.
- This module produces the list of commands/SQL to run — it should be testable independently of an actual SSH connection (i.e., "given this config, does it generate the correct command sequence" is unit-testable without hitting task 007's exec path).

## Requirements (Test Descriptions)
- [x] `it generates SQL to anonymize customer_entity PII fields per the config`
- [x] `it generates SQL to anonymize sales_order PII fields per the config`
- [x] `it generates a command to reset admin_user credentials to a known safe default`
- [x] `it generates a bin/magento config:set command to force the payment gateway to sandbox per the config`
- [x] `it generates commands to stub each configured third-party API key to a sandbox/dummy value`
- [x] `it raises a clear error when the per-app config is missing required fields`
- [x] `it produces no destructive commands (DROP/TRUNCATE) — anonymization only, never data-structure changes`

## Acceptance Criteria
- All requirements have passing tests
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

- `src/pb_hypernode_mcp/sanitization/config.py`: `PiiTableSanitizer` (table + column->SQL-value-expression `dict` + optional `where`), `GatewaySandboxSetting` (config_path + sandbox_value), and `SanitizationConfig` (frozen dataclasses) — `pii_tables` and `admin_user_reset` are required, `gateway_sandbox_settings`/`api_key_stubs` default to `()` (optional; a client app may have no third-party integrations). `validate_config()` raises `SanitizationConfigError` (a `ValueError` subclass) listing every missing required field by name. `DEFAULT_MAGENTO_SANITIZATION_CONFIG` ships a Magento-shaped default: `customer_entity`, `customer_address_entity`, `sales_order`, `sales_order_address`, `quote_payment`, `sales_order_payment` PII anonymization; `admin_user` reset to a placeholder (deliberately invalid, login-locking) password hash + safe email/username; `braintree`/`paypal` gateway-sandbox settings; `shipperhq`/`avatax` API-key stubs. Real client configs are expected to override/extend this default rather than editing it in place.
- `src/pb_hypernode_mcp/sanitization/commands.py`: `generate_sanitization_commands(config) -> list[str]` — pure function, no I/O/subprocess/SSH. Order: PII table `UPDATE`s (via `n98-magerun2 db:query "<sql>"`, matching the plan's confirmed n98-magerun2-on-node toolchain), then admin_user reset (same mechanism), then gateway sandbox `bin/magento config:set` calls, then API-key stub `bin/magento config:set` calls (values shell-quoted via `shlex.quote`). Calls `validate_config()` first so a caller can never silently get a truncated/no-op command list from a malformed config.
- Requirement 2 (`sales_order` SQL) and requirement 7 (no DROP/TRUNCATE) passed immediately once the generic `_build_update_sql` builder existed for requirement 1/the default config — the builder is inherently config-driven (arbitrary table/column input) and only ever emits `UPDATE ... SET ...;`, so no destructive-statement path exists to test against. Noted per TDD process rather than treated as a gap.
- Test file `tests/sanitization/test_commands.py` covers all 7 requirements 1:1 by name (`test_it_generates_sql_to_anonymize_customer_entity_pii_fields_per_the_config`, etc.). Three long test names exceed ruff's 100-char line length on the `def ... -> (` line; used the existing repo precedent (`tests/test_api_client.py`, `tests/test_server.py`) of a `# noqa: E501` on that line rather than shortening/deviating from the exact requirement-derived test name.
- Verified clean: `uv run pytest -v` (63 passed, up from the pre-existing 49 — 7 new here plus others from concurrently-running task 016), `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pyright src tests` (0 errors).
- Environment note: `uv` was not on `PATH` in this session (`~/.local/bin/uv` exists but isn't exported) — same known sandbox/PATH quirk documented in task 006's notes. Ran all commands with `PATH="$HOME/.local/bin:$PATH"` prefixed rather than editing shell profile.
- Out of scope / left for task 010: actually running the generated commands via `brancher_exec`, and wiring non-bypassable sanitization into `brancher_create`'s ready/URL-return path.
