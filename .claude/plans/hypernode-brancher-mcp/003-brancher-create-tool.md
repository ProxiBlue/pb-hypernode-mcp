# Task 003: brancher_create Tool + Pre-Create Guardrails

**Status**: completed
**Depends on**: 002
**Retry count**: 0

## Description
Implement the `brancher_create` MCP tool: POST to `/v2/app/<app>/brancher/` with labels and optional `clear_services`, enforced by the pre-create guardrails from the original design (mandatory label, app allowlist, Falcons-plan eligibility, minutes-remaining display).

## Context
- Request body per Hypernode docs: `{"labels": ["..."], "clear_services": ["cron", "elasticsearch", "mysql", "supervisor"]}`.
- Response: node name in the format `<appname>-eph123456`.
- Guardrails (all from the original #409 design, non-negotiable):
  - `--label`/`label` argument is mandatory — reject calls without at least one label (traceability requirement).
  - App must be in the configured allowlist (from task 001's config) — reject calls for apps not on the list, so a typo can't hit an unintended node.
  - Before creating, check the app is Falcons-plan eligible (Brancher is Falcons-only) — fail with a clear message if not, rather than letting the API call fail opaquely.
  - Before creating, surface remaining free Brancher minutes for the month so the caller sees cost context before committing.

## Requirements (Test Descriptions)
- [x] `it creates a Brancher node and returns the node name`
- [x] `it rejects the call when no label is provided`
- [x] `it rejects the call when the app is not in the allowlist`
- [x] `it rejects the call when the app is not on a Falcons-eligible plan`
- [x] `it includes remaining free minutes in the response before/alongside creation` — passed immediately on write (over-implementation carried forward from requirement 1, since `minutes_remaining` wiring was needed to satisfy the return-shape design already established by the first test); noted per TDD process, no extra code required.
- [x] `it passes clear_services through to the API request when provided`
- [x] `it defaults clear_services to cron when not provided`

## Acceptance Criteria
- All requirements have passing tests
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

**Files:**
- `src/pb_hypernode_mcp/tools/brancher_create.py` — `create_brancher_node()` core guardrail+create logic, `BrancherCreateError` (subclass of `ValueError`), `register(server, client_factory=None)` MCP tool wiring.
- `src/pb_hypernode_mcp/tools/__init__.py` — new package init (was empty dir).
- `tests/tools/test_brancher_create.py` — 8 tests (7 required + 1 registration/wiring smoke test).
- `src/pb_hypernode_mcp/server.py` — minimal edit: added `brancher_create` import + `brancher_create.register(server)` call in `create_server()`. Kept to two lines per the parallel-task merge-conflict-avoidance instruction; task 006's `brancher_ssh_info.register(...)` call (landed first) was left untouched.

**API-response-shape assumptions (UNVERIFIED — flagged per task instructions):**
There is no documented dedicated "plan info" endpoint for Hypernode Brancher at the time of writing. Both guardrails that need account/plan context are modeled as reading extra fields off the existing app-info response, fetched via `client.get(appname, '')`:
- Falcons-plan eligibility: response field `plan_type` (compared case-insensitively against `'falcons'`). Constant: `PLAN_TYPE_FIELD = 'plan_type'`, `FALCONS_PLAN_VALUE = 'falcons'`.
- Remaining free Brancher minutes: response field `brancher_minutes_remaining` (passed through as-is, `None` if absent). Constant: `MINUTES_REMAINING_FIELD = 'brancher_minutes_remaining'`.
- Both are named constants at the top of `brancher_create.py` specifically so they're a one-line fix once the real Hypernode API contract is confirmed (e.g. against real account response or updated docs).
- Create-response node name assumed to be under `response['appname']` (matches the shape already used in `tests/test_api_client.py`'s fixtures, e.g. `{'appname': 'myapp-eph1'}'`). If the real API nests this differently (e.g. under a `name` key or a wrapper object), only `create_brancher_node`'s `response.get('appname')` line needs to change.

**Guardrail order (label → allowlist → Falcons-plan) is deliberate:** cheapest/local checks first, no HTTP calls until both pass, avoiding wasted round-trips to the API when the call is going to be rejected locally anyway.

**`register()` design:** takes an optional `client_factory: Callable[[], tuple[HypernodeApiClient, tuple[str, ...]]]` so the actual server wiring builds a fresh client + reads `Settings.app_allowlist` from `load_settings()` per tool invocation, while tests can inject a fixed `(mock_client, allowlist)` pair without touching real env vars. This factory shape (returns a 2-tuple) is local to this tool module — task 006's `brancher_ssh_info.register()` uses a different (single-client) factory signature; each tool module owns its own factory contract, no shared type was assumed across parallel tasks.

**Verification:** `uv run pytest -v` — 32 passed (7 required + 1 wiring test from this task, plus tests 001/002/004/006 landed by other parallel agents). `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pyright src tests` all clean.
