# Task 021: Longer Reachability Timeout + Background-Agent Spin-Up

**Status**: completed
**Depends on**: 020
**Retry count**: 0

## Description
Two real spin-up attempts both timed out waiting for SSH-reachability (`NodeUnreachableTimeoutError`) with the node's `ip` still `null` in Hypernode's own API well past our 300s (5 min) internal timeout. Confirmed authoritative source: **Hypernode's own Control Panel UI**, shown when creating a Brancher node manually: "New Brancher node is being created. Setting up can take up to 15 minutes. Once it's ready you will see the IP address next to the Brancher name." Our 300s timeout was simply too short relative to Hypernode's own stated normal range — not a sign of anything broken. Each premature timeout throws away an already-created, already-being-paid-for node.

Separately, the user asked whether progress could be shown during the (now longer) wait, or whether Claude could poll in the background. Email notification was considered and rejected (adds a real SMTP/credential dependency inconsistent with this plugin's minimal, client-owned design, and doesn't solve the underlying "something has to poll" problem anyway). The better fit: run the spin-up via a Claude Code background `Agent` call, which already gives exactly this — the call runs independently, doesn't block the conversation, and the user gets a single notification when it completes (success or failure). No new plugin dependency needed for this part — it's a skill-level change plus the timeout bump.

## Context

**Timeout bump (`src/pb_hypernode_mcp/tools/brancher_spinup_flow.py`):** `spinup_sanitized_brancher_node()`'s `reachability_timeout` parameter currently defaults to `300.0`. Bump the default to `1200.0` (20 minutes) — comfortably above Hypernode's own stated 15-minute worst case, leaving margin rather than cutting it close. Do not just bump it blindly without checking whether `reachability_poll_interval` (currently `5.0`) should also change — at a 20-minute ceiling with a 5-second poll interval that's ~240 polls, each an SSH attempt; consider whether a longer poll interval (e.g. 15-30s) is more appropriate to avoid hammering a node that's still provisioning, but this is a judgment call, not a hard requirement — don't change it if 5s polling for up to 20 minutes isn't actually a problem (each poll is just one `exec_command` call, cheap).

Also bump the `register()`-level default for the `brancher_create` MCP tool in `src/pb_hypernode_mcp/tools/brancher_spinup_flow.py` and wherever `server.py` wires it, if the timeout is threaded through as a keyword default there too — check both call sites, don't just change the innermost function and miss an outer default that shadows it.

**Background-agent skill update (`skills/brancher-spinup/SKILL.md`, and `skills/brancher-preview/SKILL.md` since it wraps spinup):** Add explicit guidance that `brancher_create` can now take up to ~20 minutes, and the skill should default to invoking it via a background `Agent`/Task call rather than inline, so the calling Claude Code session isn't blocked for the full duration. The user gets a single notification when the background agent completes (ready, or a clear failure). Write this as: "Because this call can take up to 20 minutes, run it via a background agent rather than blocking inline — tell the user you're doing so, then report back when the background agent completes." Keep the rest of the skill's flow (label requirement, guardrail reporting, error handling) unchanged — this is additive, not a rewrite.

## Requirements (Test Descriptions)
- [x] `it defaults the reachability timeout to 1200 seconds`
- [x] `it still respects an explicitly-injected shorter timeout for tests (no real 20-minute test run)`

## Acceptance Criteria
- All requirements have passing tests (existing tests that inject a short timeout via the `reachability_timeout` kwarg for fast test runs must keep passing — only the *default* changes, tests should keep injecting their own short value, not actually wait 20 minutes)
- Full suite (`uv run pytest -v`) passes
- `ruff check`/`ruff format --check`/`pyright` clean
- `skills/brancher-spinup/SKILL.md` and `skills/brancher-preview/SKILL.md` updated with the background-agent guidance
- README's Quick Start / relevant sections mention the realistic wait time (up to ~15-20 min) so users aren't surprised, and that Claude will typically run this in the background

## Implementation Notes

- `DEFAULT_REACHABILITY_TIMEOUT_SECONDS` bumped `300.0` -> `1200.0` in `src/pb_hypernode_mcp/tools/brancher_spinup_flow.py`. Both `spinup_sanitized_brancher_node()` and `register()` reference this same module-level constant as their keyword default — no separate/shadowed default to chase, and `server.py`'s `brancher_spinup_flow.register(server, get_client)` call passes no explicit `reachability_timeout`, so it inherits the new default too.
- `DEFAULT_REACHABILITY_POLL_INTERVAL_SECONDS` bumped `5.0` -> `10.0` (judgment call per task context) — halves poll count at the new 20-min ceiling (~120 polls vs ~240) while still being responsive; each poll is a cheap `exec_command` call so this wasn't strictly required, just a minor courtesy to a still-provisioning node.
- Two new tests added to `tests/tools/test_brancher_spinup_flow.py`:
  - `test_it_defaults_the_reachability_timeout_to_1200_seconds` — inspects both `spinup_sanitized_brancher_node` and `register`'s signatures via `inspect.signature(...).parameters['reachability_timeout'].default`. RED confirmed against the old `300.0` default before the bump.
  - `test_it_still_respects_an_explicitly_injected_shorter_timeout_for_tests` — reuses the existing `AlwaysUnreachableExec`/fake-clock pattern with an explicit `reachability_timeout=5.0`, asserting the injected value (not the new 1200s default) is honoured, so no test actually waits 20 minutes. This test already passed before the implementation change (explicit kwargs always override defaults in this design) — noted per TDD rules rather than treated as a bug.
  - All existing tests that inject a short `reachability_timeout` kwarg were left untouched and continue to pass unchanged.
- `skills/brancher-spinup/SKILL.md`: added explicit background-Agent/Task-call guidance in step 3 (the `brancher_create` call), noted the ~20-min realistic ceiling in the "Node never becomes SSH-reachable" error bullet, and added a step 0 to the first worked example showing the "tell user, then background-invoke" pattern.
- `skills/brancher-preview/SKILL.md`: added a paragraph after step 1 pointing back to `brancher-spinup`'s background-agent guidance, since this skill's step 1 is exactly that call.
- `README.md`: Quick Start section now states the realistic ~15-20 min wait (citing Hypernode's own Control Panel wording) and that Claude typically runs this in the background; the `brancher_create` row in the MCP tools table updated from "300s" to "1200s (20 min)" plus a note about the background-agent invocation pattern.
- Full suite: 114 passed (112 baseline + 2 new). `ruff check`, `ruff format --check`, `pyright` all clean (one auto-fixed import-sort issue in the new test file, resolved via `ruff check --fix` / `ruff format`).
