# Task 018: Multi-Hypernode Token Support

**Status**: completed
**Depends on**: 017
**Retry count**: 0

## Description
Fix an architectural gap found post-release: Hypernode API tokens are scoped **per Hypernode/app**, not account-wide. The current config model (`HYPERNODE_API_TOKEN` — one token, `HYPERNODE_APP_ALLOWLIST` — an optional restriction on top of that one token) is wrong: it assumes one token can authenticate against multiple apps. It cannot. A user managing more than one Hypernode needs a distinct token per app, and every REST-API-calling tool call needs to pick the right one based on which app it's targeting.

## Context

**New config model:**
- Replace `HYPERNODE_API_TOKEN` (singular) and `HYPERNODE_APP_ALLOWLIST` with a single env var: `HYPERNODE_API_TOKENS`, holding a JSON object mapping appname -> token, e.g. `HYPERNODE_API_TOKENS='{"myapp":"token1","myapp2":"token2"}'`. pydantic-settings parses JSON automatically for a `dict[str, str]`-typed field sourced from an env var — use that, don't hand-roll JSON parsing.
- The map's keys ARE the allowlist now — there is no separate allowlist concept. An app not in `HYPERNODE_API_TOKENS` cannot be operated on because there is no token to authenticate with. Remove `app_allowlist`/`AppNotAllowedError` as a distinct concept and fold its behavior into "no token configured for this app" (still a clear, distinct error — rename appropriately, e.g. `UnknownAppError`/`AppNotConfiguredError`, your call, but the message must make clear it's about missing token configuration, not an arbitrary allowlist policy).
- `config.py` needs a way to list configured apps (`Settings.configured_apps -> tuple[str, ...]`, sorted) and resolve a token by appname (`Settings.token_for(appname: str) -> str`, raising a clear error listing what IS configured when the app isn't found — the error itself should help the user fix it, e.g. "no token configured for 'myapp3' — configured apps: myapp, myapp2").
- `load_settings()` should still raise a clear config error if `HYPERNODE_API_TOKENS` is unset or is not valid JSON / not a flat string->string map.

**API client changes (`api_client.py`):**
- `HypernodeApiClient` currently resolves a single token once (from `Settings.hypernode_api_token`) at construction and reuses it for every request regardless of which app the request targets. Every request method (`get`/`post`/`delete`) already takes `appname` as its first argument — change the client to look up the token per-request via `settings.token_for(appname)` instead of caching one token at construction. Keep the `Settings` object as the constructor dependency (no other shape change needed).

**Tool changes — REST-API-calling tools only** (`brancher_create.py`, `brancher_list.py`, `brancher_delete.py`, `brancher_ssh_info.py` — these all reach the Hypernode API and need the right token):
- Replace any "app not in allowlist" check with the natural consequence of `Settings.token_for()` raising when the app isn't configured — don't keep two parallel mechanisms.
- `brancher_delete.py` and `brancher_ssh_info.py` already derive an `appname` from `node_name` by stripping the `-eph<id>` suffix (check the existing regex/helper — reuse it, don't duplicate) — that derived appname is what gets passed to `token_for()`.

**`brancher_exec.py`/`brancher_put.py` do NOT need changes** — they shell out to the system `ssh`/`rsync` binaries using your local SSH agent, never the Hypernode REST API or its token. Confirm this is true by reading both files before assuming — if either secretly does hit the API, it needs the same fix.

**New tool — "which apps are configured" (needed for the skill-level "ask if ambiguous" behavior):**
- Add a new MCP tool, `brancher_apps`, that takes no arguments and returns `Settings.configured_apps` (just the list of appnames with a token configured — no API call, this is pure local config introspection). Register it in `server.py` alongside the other six.

**Skill changes — all three `SKILL.md` files:**
- Add an explicit step near the top of each skill's flow: if the user's request doesn't specify which Hypernode/app to operate on, call `brancher_apps` first, show the user the list, and ask them to pick one before calling any other tool. Never guess an appname. If `brancher_apps` returns exactly one configured app, it's reasonable to note that and proceed with it rather than asking (your call on exact wording, but don't force a confirmation click for a single-option case — asking "which of these 1 option do you want" is silly).

**README changes:**
- Update the `Setup` section's env var instructions: `HYPERNODE_API_TOKENS` (JSON map) replaces `HYPERNODE_API_TOKEN`/`HYPERNODE_APP_ALLOWLIST` entirely. Show a concrete example with two apps.
- Update the `MCP tools` table to add `brancher_apps` and correct any tool descriptions that reference the old allowlist/single-token model.
- Add a short "Multiple Hypernodes" note explaining that each Hypernode needs its own token in the map, and that skills will ask which one to use if you don't say.

## Requirements (Test Descriptions)
- [x] `it parses HYPERNODE_API_TOKENS as a JSON appname-to-token map` — `tests/test_config.py::test_it_parses_hypernode_api_tokens_as_a_json_appname_to_token_map`
- [x] `it raises a clear config error when HYPERNODE_API_TOKENS is missing` — `tests/test_config.py::test_it_raises_a_clear_config_error_when_hypernode_api_tokens_is_missing`
- [x] `it raises a clear config error when HYPERNODE_API_TOKENS is not valid JSON` — `tests/test_config.py::test_it_raises_a_clear_config_error_when_hypernode_api_tokens_is_not_valid_json` (also covers the not-a-flat-string-map case, `..._is_not_a_flat_string_map`)
- [x] `it resolves the correct token for a given appname on each API request` — `tests/test_api_client.py::test_it_resolves_the_correct_token_for_a_given_appname_on_each_api_request`
- [x] `it raises a clear error listing configured apps when a request targets an app with no configured token` — `tests/test_api_client.py::test_it_raises_a_clear_error_when_a_request_targets_an_app_with_no_configured_token` + `tests/test_config.py::test_it_raises_a_clear_error_listing_configured_apps_when_resolving_an_unconfigured_app`
- [x] `it lists configured app names via the brancher_apps tool with no arguments` — `tests/tools/test_brancher_apps.py::test_it_lists_configured_app_names_via_the_brancher_apps_tool_with_no_arguments`
- [x] `it derives the correct appname from a node_name to resolve the right token for brancher_delete and brancher_ssh_info` — `tests/tools/test_brancher_delete.py::test_it_derives_the_correct_appname_from_a_node_name_to_resolve_the_right_token`, `tests/tools/test_brancher_ssh_info.py::test_it_derives_the_correct_appname_from_a_node_name_to_resolve_the_right_token`

## Acceptance Criteria
- All requirements have passing tests
- Full suite (`uv run pytest -v`) passes, including every pre-existing test updated for the new config model (there will be many — `HYPERNODE_API_TOKEN`/`HYPERNODE_APP_ALLOWLIST`/`app_allowlist`/`AppNotAllowedError` references across `tests/` all need updating to the new model, not left stale)
- `ruff check`/`ruff format --check`/`pyright` clean
- README, all three SKILL.md files, and any docstrings referencing the old single-token/allowlist model are updated — no stale references anywhere in the repo (grep for `HYPERNODE_API_TOKEN\b`, `HYPERNODE_APP_ALLOWLIST`, `app_allowlist`, `AppNotAllowedError` before declaring done; every hit must be either updated or a deliberate historical reference you can justify)

## Implementation Notes

- `config.py`: `Settings.hypernode_api_tokens: dict[str, str]` (default `{}`), sourced automatically from `HYPERNODE_API_TOKENS` by pydantic-settings' built-in JSON parsing for env-sourced complex types — no hand-rolled `json.loads`. Added `Settings.configured_apps` (sorted tuple of keys) and `Settings.token_for(appname)`, which raises the new `UnknownAppError` with a message listing configured apps. `load_settings()` wraps `Settings()` construction, catching both `pydantic_settings.exceptions.SettingsError` (malformed JSON) and `pydantic.ValidationError` (valid JSON but wrong shape, e.g. non-dict or non-string values) into `ConfigError`, and also raises `ConfigError` when the map is empty (env var unset). `app_allowlist`/`AppNotAllowedError` removed entirely.
- `api_client.py`: `HypernodeApiClient` no longer caches a token at construction. `_headers()` now takes a `token_appname` and calls `settings.token_for(token_appname)` per request. `get`/`post`/`delete` gained an optional keyword-only `token_appname` param (defaults to the URL-path `appname` when omitted) — needed because a Brancher node's own URL segment (`<appname>-eph<id>`) is never itself a key in `HYPERNODE_API_TOKENS`; only its parent app is.
- `tools/_guards.py`: added public `appname_from_node_name(node_name)` (validated `-eph<id>` stripping), promoted out of `brancher_delete.py`'s former private `_appname_from_node_name` so `brancher_ssh_info.py` can reuse the same logic instead of duplicating it.
- `brancher_delete.py`: uses `appname_from_node_name`; the final `client.delete(node_name, '', token_appname=appname)` call now passes the derived parent appname explicitly so token resolution doesn't try (and fail) to look up the full node name.
- `brancher_ssh_info.py`: same pattern — `client.get(node_name, '', token_appname=appname_from_node_name(node_name))`.
- `brancher_create.py` / `brancher_spinup_flow.py`: dropped the `app_allowlist` parameter chain entirely (`create_brancher_node(client, appname, labels, clear_services=None)`, `spinup_sanitized_brancher_node(client, appname, labels, ...)`); the pre-create Falcons/label guardrails are unchanged, but the allowlist check is gone — `client.get(appname, '')` now raises `UnknownAppError` naturally when unconfigured. `brancher_spinup_flow.register()`'s `ClientFactory` simplified from `Callable[[], tuple[HypernodeApiClient, tuple[str, ...]]]` to `Callable[[], HypernodeApiClient]`.
- `brancher_list.py`: dropped `AppNotAllowedError` and the manual `appname not in settings.app_allowlist` check; `settings` param kept on `list_brancher_nodes()`'s signature for call-site consistency with `brancher_delete.py`/`cleanup_logic.py` even though the function body no longer reads it directly (token resolution now lives entirely in the client).
- New `tools/brancher_apps.py`: `list_configured_apps(settings) -> tuple[str, ...]` (pure) + `register(server, settings_factory)` exposing the `brancher_apps` MCP tool (no args, no API call). Wired in `server.py` as the 7th tool via `brancher_apps.register(server, get_settings)`.
- `server.py`: `brancher_spinup_flow.register(server, get_client)` (client-only factory, no more `app_allowlist` tuple threaded through).
- All three `SKILL.md` files got a new first-or-near-first flow step: call `brancher_apps` and ask which app if the request is ambiguous; proceed silently-but-noted if exactly one app is configured. `brancher-preview`'s step 1 explicitly defers to `brancher-spinup`'s own app-identification step rather than duplicating the instruction.
- `README.md`, `.claude-plugin/plugin.json`, `.mcp.json` updated: `HYPERNODE_API_TOKENS` (JSON map) replaces `HYPERNODE_API_TOKEN`/`HYPERNODE_APP_ALLOWLIST` throughout — Setup section, MCP tools table (7 tools now), Safety guardrails bullet, Skills section (`Multiple Hypernodes` note), Limitations/Development/troubleshooting mentions. `tests/test_plugin_manifest.py` updated to assert the new var is documented and the old one is fully gone (regex-checked, not just substring, to catch `HYPERNODE_API_TOKEN` without the trailing `S`).
- Every pre-existing test file touching `Settings`/`HypernodeApiClient`/allowlist behavior was updated to the new `hypernode_api_tokens={...}` construction and `UnknownAppError`: `tests/test_api_client.py`, `tests/test_config.py`, `tests/test_cleanup_logic.py`, `tests/test_server.py` (incl. `FakeApiClient` gaining `token_appname` kwargs), `tests/tools/test_brancher_create.py`, `tests/tools/test_brancher_list.py`, `tests/tools/test_brancher_delete.py`, `tests/tools/test_brancher_ssh_info.py`, `tests/tools/test_brancher_spinup_flow.py`, `tests/tools/test_guards.py`. New `tests/tools/test_brancher_apps.py`.
- Verified `brancher_exec.py`/`brancher_put.py` never touch the REST API (shell out to `ssh`/`rsync` only) — left unchanged per the task's own note.
- Full suite: 97 passed (`uv run pytest -v`). `ruff check`/`ruff format --check`/`pyright basic` all clean.
- Historical plan docs under `.claude/plans/hypernode-brancher-mcp/00*.md`–`016-*.md` intentionally left untouched (they describe what was true at the time those tasks shipped); only `.claude/code-standards.md` (a living reference doc, not a historical record) was updated alongside the source/README/skills changes.
