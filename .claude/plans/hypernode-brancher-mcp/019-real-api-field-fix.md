# Task 019: Fix Plan-Eligibility Field + Drop Unverified Minutes-Remaining

**Status**: completed
**Depends on**: 018
**Retry count**: 0

## Description
First real spin-up attempt against a live Hypernode account (`ppsdev`) failed: the plan-eligibility guardrail checked a top-level `plan_type` field that does not exist in the real API response. Confirmed via a live `GET /v2/app/ppsdev/` call — the real field is `product.code` (e.g. `"FALCON_S_202603DEV"`, a "FALCON" substring match, not an exact enum value — Hypernode has multiple Falcon SKUs). Also confirmed: there is no `brancher_minutes_remaining` field or any other minutes-remaining figure anywhere on this endpoint — that assumption was wrong too and has been dropped (`minutes_remaining` is now always `None` from `create_brancher_node`).

Separately, real accounts default to `allow_api_token_usage: false` — Hypernode 403s any Brancher/financial API call until an owner/admin explicitly enables "API token usage" for the app in the Control Panel (Configuration -> Settings). This is a real account-level prerequisite, not a code bug — document it clearly so a future user hitting the same 403 doesn't waste time debugging code that's already correct.

## Context

`src/pb_hypernode_mcp/tools/brancher_create.py` has already been fixed (this session, live) to:
- Read `app_info['product']['code']`, match `FALCONS_PLAN_SUBSTRING = 'FALCON'` (uppercased substring check) instead of an exact `plan_type == 'falcons'` match.
- Always return `minutes_remaining: None` (dropped `MINUTES_REMAINING_FIELD`/`brancher_minutes_remaining` entirely — no verified source exists).

This task is the cleanup pass: bring every test, skill doc, and README reference in line with the fixed source, verify the full suite, and add the `allow_api_token_usage` prerequisite to the README/skill docs.

**Tests to fix** (all currently mock the OLD `plan_type`/`brancher_minutes_remaining` shape):
- `tests/tools/test_brancher_create.py` — every mock GET response needs `{'product': {'code': 'FALCON_S_202603DEV'}}` (or similar) instead of `{'plan_type': 'falcons'}`; the "not eligible" test needs a non-FALCON `product.code` (e.g. `'GRIFFIN_M'`); the "includes minutes remaining" test (`test_it_includes_remaining_free_minutes_in_the_response_before_alongside_creation`) no longer makes sense as a positive-value assertion since the field doesn't exist — rewrite it to assert `minutes_remaining` is always `None`, and rename the test to reflect that (e.g. `test_it_returns_none_for_minutes_remaining_since_no_verified_api_source_exists`), updating the corresponding line in `_plan.md`/this task's own Requirements section is NOT needed (that's fine to leave as historical record) but the actual `.claude/plans/.../003-*.md` file doesn't need touching either — only live test/src/doc files matter here.
- `tests/tools/test_brancher_spinup_flow.py` — same mock-shape fix; any assertion on a specific non-null `minutes_remaining` value needs updating to `None`.
- `tests/test_server.py` — same mock-shape fix; same `minutes_remaining` assertions to `None`.

**Docs to fix:**
- `README.md`: update the Quick Start example output (currently shows `minutes_remaining: 387`) to show `None`/omit it, or add a one-line note that this field is not yet populated pending a verified API source. Update the "Unverified API response shapes" Limitations bullet to reflect what's now VERIFIED (`product.code` for plan check) vs what's STILL unverified (minutes-remaining has no known source at all, not just an unverified field name). Add a new bullet or expand an existing one: Brancher/financial API calls require `allow_api_token_usage: true` on the app (Hypernode Control Panel -> Configuration -> Settings, owner/admin only) — a 403 with a message about "financial nature of the command" means this setting is off, not a bug in this plugin.
- `skills/brancher-spinup/SKILL.md`, `skills/brancher-preview/SKILL.md`: both reference `minutes_remaining` as if it's always a populated number ("tell the user this so they know their remaining budget", example output `"minutes_remaining": 118`). Update both to reflect that this field is currently always `None` — the skill should stop telling Claude to "report minutes remaining" as if it's meaningful data, and instead either omit mentioning it or note plainly that Brancher minute tracking isn't available via this plugin yet.

## Requirements (Test Descriptions)
- [x] `it accepts a Falcon-family plan code as Falcons-eligible (substring match, not exact)`
- [x] `it rejects a non-Falcon plan code as not Falcons-eligible`
- [x] `it returns None for minutes_remaining since no verified API source exists`
- [x] `it surfaces the real plan code in the rejection error message when not Falcons-eligible`

## Acceptance Criteria
- All requirements have passing tests
- Full suite (`uv run pytest -v`) passes — every stale `plan_type`/`brancher_minutes_remaining` mock across the test suite updated to the real `product.code` shape
- `ruff check`/`ruff format --check`/`pyright` clean
- README and both affected SKILL.md files updated: no remaining references implying `minutes_remaining` is populated data; `allow_api_token_usage` prerequisite documented
- No source files other than `brancher_create.py` (already fixed) need changing — this task is tests + docs only, unless fixing a test reveals a second real bug in the source, in which case fix it and note why in Implementation Notes

## Implementation Notes

`src/pb_hypernode_mcp/tools/brancher_create.py` was already correct on disk (per task description) — confirmed via `git diff`/read, made no source changes. Ran `uv sync --extra dev` first (pytest/ruff/pyright not installed under base `uv run`).

Baseline: `uv run pytest -v` showed 16 failing tests, all from the stale `plan_type`/`brancher_minutes_remaining` mock shape tripping the (correct) new `product.code` guardrail — confirmed this was the RED state before any test edits.

**`tests/tools/test_brancher_create.py`** — rewrote the plan-eligibility/minutes-remaining tests to match the 4 requirement descriptions exactly:
- Added `test_it_accepts_a_falcon_family_plan_code_as_falcons_eligible_substring_match_not_exact` (new — proves substring match against a real-shaped SKU code, not an exact-value comparison).
- Renamed `test_it_rejects_the_call_when_the_app_is_not_on_a_falcons_eligible_plan` -> `test_it_rejects_a_non_falcon_plan_code_as_not_falcons_eligible`, mock changed to `{'product': {'code': 'GRIFFIN_M'}}`.
- Added `test_it_surfaces_the_real_plan_code_in_the_rejection_error_message_when_not_falcons_eligible` (new — asserts the raised error message contains the literal rejected plan code, not just the word "Falcons").
- Renamed `test_it_includes_remaining_free_minutes_in_the_response_before_alongside_creation` -> `test_it_returns_none_for_minutes_remaining_since_no_verified_api_source_exists`, assertion changed from `== 17` to `is None`.
- Fixed remaining mocks (`test_it_creates_a_brancher_node_and_returns_the_node_name`, `test_it_passes_clear_services_through_to_the_api_request_when_provided`, `test_it_defaults_clear_services_to_cron_when_not_provided`) from `{'plan_type': 'falcons', ...}`/`{'plan_type': 'falcons'}` to `{'product': {'code': 'FALCON_S_202603DEV'}}`.

**`tests/tools/test_brancher_spinup_flow.py`** — `make_client()`'s shared GET mock updated to the `product.code` shape; both `'minutes_remaining': 42` result-dict assertions changed to `None`.

**`tests/test_server.py`** — `FakeApiClient.get()` updated to the `product.code` shape (dropped the fake `brancher_minutes_remaining` key entirely); all three `'minutes_remaining': 5` result-dict assertions changed to `None`.

**Docs:**
- `README.md`: Quick Start example output — dropped the `minutes_remaining: 387` line, added a one-line note pointing at Limitations. Requirements section — added an `allow_api_token_usage` prerequisite bullet (the 403/"financial nature of the command" gotcha). Limitations section — rewrote the "Unverified API response shapes" bullet to state what's now verified (`product.code`, substring match) vs what remains genuinely unknown (no minutes-remaining source exists at all, not just an unverified field name); `brancher_list`'s shape is still called out as unverified separately. Added a new Limitations bullet cross-referencing the `allow_api_token_usage` prerequisite.
- `skills/brancher-spinup/SKILL.md`: step-4 field list — `minutes_remaining` now documented as always `None`, explicit instruction not to report it to the user as meaningful data (dropped the old "tell the user this so they know their remaining budget" framing). Example JSON output updated to `None`. Errors section — added a new bullet for the `allow_api_token_usage` 403 case, telling Claude to treat it as an account-setting gap, not a transient failure to retry.
- `skills/brancher-preview/SKILL.md`: step-1 field list and the example JSON output both updated to reflect `minutes_remaining: None`.

No second real source bug surfaced — the pre-fixed `brancher_create.py` behaved exactly as documented once mocks matched the real shape; every test failure was purely stale-mock, not a source defect.

Verification: `uv run pytest -v` -> 99 passed, 0 failed. `uv run ruff check src tests` -> all checks passed. `uv run ruff format --check src tests` -> 39 files already formatted. `uv run pyright src tests` -> 0 errors, 0 warnings, 0 informations.
