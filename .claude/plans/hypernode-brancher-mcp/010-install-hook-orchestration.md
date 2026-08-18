# Task 010: Install-Hook Orchestration (Auto-Wires Sanitization Into Create)

**Status**: completed
**Depends on**: 003, 009
**Retry count**: 0

## Description
Wire task 009's sanitization module into the `brancher_create` flow so it runs automatically after the node becomes reachable and BEFORE the tool reports the node as "ready" / returns the access URL to the caller. This must be non-bypassable — no flag, no opt-out.

## Context
- Poll the node until it's reachable over SSH (Hypernode docs note the node takes "a couple of minutes" to become available after create).
- Run task 009's generated command sequence via `brancher_exec` (task 007).
- Only after sanitization completes successfully does `brancher_create`'s overall response report the node as ready and return the URL/access details. If sanitization fails partway, the tool must surface a clear failure state — NOT silently return a "ready" node that's actually still carrying live data.
- This is the closest analog to Hypernode's own `brancher-install-hook` mechanism, but driven from the MCP side via SSH rather than a file dropped in `~/.hypernode`.

## Requirements (Test Descriptions)
- [x] `it does not report the node as ready until sanitization has completed`
- [x] `it runs the sanitization command sequence exactly once per create`
- [x] `it surfaces a clear failure state when sanitization fails partway through`
- [x] `it does not return the node's access URL when sanitization has failed`
- [x] `it times out with a clear error if the node never becomes SSH-reachable`

## Acceptance Criteria
- All requirements have passing tests
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

New module: `src/pb_hypernode_mcp/tools/brancher_spinup_flow.py` (not wired into `server.py` per task scope — that's a follow-up wiring/skill task).

- `spinup_sanitized_brancher_node(client, app_allowlist, appname, labels, clear_services=None, *, sanitization_config=DEFAULT_MAGENTO_SANITIZATION_CONFIG, exec_command=default_exec_command, ready_probe_command='echo ready', reachability_poll_interval=5.0, reachability_timeout=300.0, sleep=asyncio.sleep, clock=time.monotonic) -> dict[str, Any]`
  - Calls `create_brancher_node` (task 003) to create the node.
  - Polls the node via `exec_command(node_name, ready_probe_command)` in a retry loop (`_wait_until_reachable`) until it succeeds or `reachability_timeout` elapses; any exception from `exec_command` (SSH connection refused, timeout, etc.) is treated as "not yet reachable" and retried after `reachability_poll_interval` (via injectable `sleep`)/`clock` — both injectable for deterministic, non-sleeping tests.
  - Runs `generate_sanitization_commands(sanitization_config)` (task 009) via `exec_command` in order; any command returning `exit_code != 0` raises `SanitizationFailedError` immediately (stops the sequence, does not continue running remaining commands).
  - Only after every sanitization command succeeds does it return `{node_name, minutes_remaining, access_url, status: 'ready', sanitization_commands_run}`. There is no code path that returns `access_url`/`status: 'ready'` without having run every command successfully — non-bypassable by construction (no flag/opt-out parameter exists).
- Exceptions: `BrancherSpinupError` (base), `NodeUnreachableTimeoutError` (reachability timeout), `SanitizationFailedError` (carries `node_name`, `command`, `commands_completed`; message deliberately omits the access URL/domain).
- Requirements 2 and 4 passed immediately once requirements 1 and 3's minimal implementations were in place (over-implementation carryover, noted per TDD process — the exception-raising design from req 1/3 structurally guarantees "exactly once" ordering and "no URL on failure").
- Tests: `tests/tools/test_brancher_spinup_flow.py`, 5 tests, all passing. Uses fake `exec_command` callables (`RecordingExec`, `FailingAfterNExec`, `AlwaysUnreachableExec`) and injected `sleep`/`clock` fakes — no real network/SSH/sleep in the timeout test.
- Full suite: 73 passed (63 pre-existing + 5 new... plus pre-existing net growth from earlier tasks in this run). `ruff check`, `ruff format --check`, and `pyright` all clean on `src` and `tests`.
