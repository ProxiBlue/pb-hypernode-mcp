# Task 022: Two-Phase Reachability Wait (IP-Poll Then SSH-Poll)

**Status**: completed
**Depends on**: 021
**Retry count**: 0

## Description
Across several real spin-up attempts, at least one node reportedly had a real `ip` assigned around the 16-minute mark, but this was never surfaced anywhere — the final result was just a generic `NodeUnreachableTimeoutError` after the full timeout, with no indication of whether the bottleneck was "Hypernode never assigned an IP" (their infra) or "IP was assigned but SSH never responded" (possibly our SSH config, or sshd still starting). These are genuinely different failure classes and the current design can't tell them apart because `_wait_until_reachable` (`src/pb_hypernode_mcp/tools/brancher_spinup_flow.py`) only has access to `exec_command` (SSH) — it starts trying SSH immediately, even while the node has no IP at all, which is guaranteed to fail every single poll until an IP eventually shows up. There's no cheaper, non-SSH check happening in parallel or first.

Fix: split the wait into two explicit, separately-timed, separately-reported phases.

## Context

**Phase 1 — wait for IP assignment (new).** Add a helper that polls the Brancher list endpoint (reuse `list_brancher_nodes` from `tools/brancher_list.py` — no need to hit a different endpoint) and checks the target node's `ip` field, looping until it's non-null or a timeout elapses. This is a plain REST call, no SSH involved, so it can run immediately and cheaply from the moment the node is created.

- `list_brancher_nodes(appname, *, client, settings)` currently returns `{'name', 'host', 'minutes'}` per node — it does NOT currently expose the raw `ip` field even though the underlying API response has it (`node.get('ip')`, per task 020's verified shape). Add `'ip': node.get('ip')` to the dict it returns — this is generally useful (not just for this internal use) and doesn't change any existing field, so it's an additive, non-breaking change to `brancher_list`'s output shape. Update `tests/tools/test_brancher_list.py` accordingly.
- Note: `list_brancher_nodes`'s `settings` parameter is provably unused inside the function body (confirmed by reading the current source — token resolution happens entirely inside `client.get_path`/`Settings.token_for`, not by referencing the `settings` param directly). Your call whether to clean this up (drop the unused param, update all call sites) as part of this task, or leave it alone and just thread through whatever's easiest for the new IP-wait phase — don't feel obligated to fix this if it adds risk, but flag your choice in Implementation Notes either way.
- New exception: `NodeIpNeverAssignedError(BrancherSpinupError)` — raised when Phase 1 times out. Message should be unambiguous that this is Hypernode's own provisioning that stalled, not an SSH/config problem on our side, e.g. `"Brancher node {node_name!r} was never assigned an IP address within {timeout}s -- this is Hypernode's own provisioning, not an SSH/config issue on this plugin's side."`

**Phase 2 — wait for SSH reachability (existing `_wait_until_reachable`, mostly unchanged).** Only starts once Phase 1 succeeds (IP is present). Use the REMAINING time budget (`overall_timeout - time_spent_in_phase_1`) so the two phases together never exceed the configured `reachability_timeout` ceiling — don't let Phase 2 get its own full fresh timeout on top of Phase 1's.

**Reporting the split (this is the actual ask — surface what happened, don't just silently succeed/fail).** On success, `spinup_sanitized_brancher_node`'s returned dict should include how long each phase took (e.g. `ip_assigned_after_seconds`, `ssh_reachable_after_seconds` — exact key names your call, but both numbers should be present so a caller/skill can report "IP assigned after Xs, SSH reachable after an additional Ys" rather than just a bare success). On failure, the two distinct exceptions (`NodeIpNeverAssignedError` vs the existing `NodeUnreachableTimeoutError`, now meaning specifically "IP was assigned at Xs but SSH still never responded by the deadline") make the failure mode unambiguous from the exception type and message alone.

**Skill updates (`skills/brancher-spinup/SKILL.md`, `skills/brancher-preview/SKILL.md`):** Update the error-handling section to describe both failure modes distinctly, and update the success-reporting guidance to mention the phase timings when present (e.g. "IP assigned after 6 min, SSH reachable 40s after that" gives the user real signal about where time went, useful if they need to report this to Hypernode support again).

**README:** update the Limitations/timeout section to reflect the two-phase design and what each failure type means.

## Requirements (Test Descriptions)
- [x] `it polls the list endpoint until the node has a non-null ip before attempting ssh`
- [x] `it raises NodeIpNeverAssignedError when ip is never assigned within the timeout`
- [x] `it does not attempt any ssh exec_command call while ip is still null`
- [x] `it starts the ssh-reachability phase only after ip is assigned`
- [x] `it raises NodeUnreachableTimeoutError when ip is assigned but ssh never becomes reachable`
- [x] `it reports how long ip-assignment and ssh-reachability each took on success`
- [x] `it splits the overall timeout across both phases rather than giving each phase a full fresh timeout`

## Acceptance Criteria
- [x] All requirements have passing tests (mock the list-endpoint response sequence to simulate ip transitioning from null to assigned after N polls, and mock `exec_command` for the SSH phase — no real network/SSH in tests)
- [x] Full suite (`uv run pytest -v`) passes
- [x] `ruff check`/`ruff format --check`/`pyright` clean
- [x] `skills/brancher-spinup/SKILL.md`, `skills/brancher-preview/SKILL.md`, and README updated to describe the two-phase wait and both distinct failure modes
- [x] `brancher_list`'s new `ip` field is covered by its own test, independent of the spinup-flow changes

## Implementation Notes

- **`list_brancher_nodes`'s `ip` field**: added `'ip': node.get('ip')` to the dict returned per node in `src/pb_hypernode_mcp/tools/brancher_list.py`. Covered by two new dedicated tests in `tests/tools/test_brancher_list.py` (`test_it_returns_the_nodes_ip_field_null_until_provisioning_assigns_one`, `test_it_returns_the_nodes_assigned_ip_once_provisioning_completes`), independent of the spinup-flow changes. All existing exact-dict-equality assertions across `tests/tools/test_brancher_list.py`, `tests/test_cleanup_logic.py`, `tests/tools/test_brancher_delete.py`, and `tests/test_server.py` were updated to include the new `ip` key.

- **Unused `settings` param on `list_brancher_nodes`: dropped, not left alone.** Per the task's "your call" note, I removed the provably-unused `settings` keyword-only param from `list_brancher_nodes` (token resolution happens entirely inside `client.get_path`/`Settings.token_for`, never by referencing `settings` directly). This was the lower-risk option overall: it avoided having to thread a new required `settings` argument through `spinup_sanitized_brancher_node`'s public signature (which only ever received a bare `client`, not a `(client, settings)` pair) just to satisfy the new phase-1 ip-poll call. Updated the 3 call sites that passed `settings=settings` (`cleanup_logic.py::cleanup_stale_nodes`, `tools/brancher_delete.py::delete_brancher_node`, `tools/brancher_list.py::register()`'s inner closure — those functions themselves keep their own `settings` param since it's still needed for other purposes there) and the corresponding test call sites. `brancher_delete.py`'s and `cleanup_logic.py`'s own public function signatures are unchanged (`settings` still required there) — only the internal `list_brancher_nodes(...)` call sites dropped the now-nonexistent kwarg.

- **Two-phase wait implementation** (`src/pb_hypernode_mcp/tools/brancher_spinup_flow.py`):
  - New `_wait_for_ip_assignment(node_name, appname, *, client, poll_interval, timeout, sleep, clock)` polls `list_brancher_nodes(appname, client=client)`, finds the node by name, and loops until `ip` is truthy or `timeout` elapses; returns elapsed seconds. Raises new `NodeIpNeverAssignedError(BrancherSpinupError)` on timeout, whose message matches the task's specified wording exactly (`"Brancher node {node_name!r} was never assigned an IP address within {timeout}s -- this is Hypernode's own provisioning, not an SSH/config issue on this plugin's side."`).
  - `_wait_until_reachable` (phase 2, SSH) is otherwise unchanged in shape; `spinup_sanitized_brancher_node` now calls it with `timeout=reachability_timeout - ip_assigned_after_seconds` (the remaining budget), so the two phases together never exceed the one configured `reachability_timeout` ceiling — phase 2 does not get a fresh timeout of its own.
  - On success, the returned dict gained two new keys: `ip_assigned_after_seconds` and `ssh_reachable_after_seconds`.
  - `register()`'s signature and defaults (`reachability_timeout` default 1200s, etc.) are unchanged; the new phase-1 poll reuses `reachability_poll_interval` rather than introducing a separate interval knob, since the task only asked for the overall timeout to be split, not a distinct polling cadence per phase.

- **Test-fixture fallout from making phase 1 real (task 022's actual behavioural change):** every existing test/fixture in `tests/tools/test_brancher_spinup_flow.py` and `tests/test_server.py` that previously mocked only the app-info GET (`/v2/app/<appname>/`) and the create POST now also needed to mock the Brancher list GET (`/v2/brancher/app/<appname>/`) with a non-null `ip` for the created node — otherwise phase 1 would poll forever using the real default `sleep=asyncio.sleep`/`clock=time.monotonic` (this is exactly what caused `tests/test_server.py` to hang for the full 1200s default timeout during a full-suite run before the fixtures were fixed; caught by running the full suite with a timeout wrapper after per-file runs looked fine in isolation). Fixed by branching the shared mock `handler`s on request URL/method and updating `FakeApiClient.get_path` in `tests/test_server.py` to include `'ip': '203.0.113.10'`.

- **Skill/README updates**: `skills/brancher-spinup/SKILL.md`'s Errors section now documents both `NodeIpNeverAssignedError` and `NodeUnreachableTimeoutError` as distinct failure modes (was previously just the latter), its success-reporting section and Example were updated to mention/show `ip_assigned_after_seconds`/`ssh_reachable_after_seconds`, and its Implementation Notes section documents the phase split for maintainers. `skills/brancher-preview/SKILL.md`'s step 1 now points at the same distinction and shows the new fields in its own worked example. `README.md`'s intro wait-time note, the `brancher_create`/`brancher_list` tool-table rows, and a new Limitations (v1) bullet all describe the two-phase design, the shared timeout ceiling, and what each exception type means.
