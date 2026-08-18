# Task 007: brancher_exec Tool + -eph-Only Guard

**Status**: completed
**Depends on**: 006
**Retry count**: 0

## Description
Implement the `brancher_exec` MCP tool: run a shell command on a Brancher node over SSH, using the client's local SSH agent/key (no key material handled by the MCP process). This is the single safety-critical chokepoint of the "change-it" layer — it must be structurally impossible to point it at a production host.

## Context
- Shells out to the system `ssh` binary (e.g. `subprocess` invoking `ssh <user>@<host> <command>`), relying on the caller's already-configured SSH agent/keys — do not implement custom SSH key handling.
- **Hard guard**: reject any target hostname that does not match the `*-eph*` Brancher naming pattern, BEFORE opening any SSH connection. This check must not be bypassable via a flag or alternate code path — test it explicitly against production-shaped hostnames (e.g. `pps.hypernode.io`, `pps-staging.hypernode.io`) to confirm they're rejected.
- Include this task's first real integration checkpoint: a smoke test against an actual Brancher node (create one, exec a trivial command like `whoami`, confirm SSH auth works without extra key provisioning) to validate the assumption that SSH keys inherit via the backup clone. If this assumption is wrong, this task's scope grows to include key provisioning — flag back to the plan if so.

## Requirements (Test Descriptions)
- [x] `it executes a command on a valid -eph node and returns stdout/stderr/exit code`
- [x] `it rejects execution against a hostname not matching the -eph pattern`
- [x] `it rejects execution against a bare appname with no -eph suffix`
- [x] `it propagates SSH connection failures as a clear error rather than swallowing them`
- [x] `it respects a configurable command timeout`

## Acceptance Criteria
- All requirements have passing tests (unit tests mock the SSH subprocess call)
- At least one manual/integration smoke-test run against a real Brancher node is documented in Implementation Notes, confirming or refuting the SSH-key-inheritance assumption
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

**Files**:
- `src/pb_hypernode_mcp/tools/brancher_exec.py` — `exec_command(node_name, command, *, timeout=30.0)` business-logic function + `register(server)` (unused/unwired per task instructions — wiring deferred to task 016, `server.py` was NOT touched).
- `tests/tools/test_brancher_exec.py` — 8 tests (5 requirements, one parametrized x4 for the -eph-pattern rejection cases).

**Design**:
- Shells out via `asyncio.create_subprocess_exec('ssh', f'{user}@{host}', command, stdout=PIPE, stderr=PIPE)`. No custom SSH key handling — relies entirely on the caller's local SSH agent/keys, exactly as scoped.
- `host`/`user` are derived directly from `node_name` (`f'{node_name}.hypernode.io'` / `node_name`), mirroring the convention already established in `brancher_ssh_info.get_ssh_info`. `exec_command` does not call the Hypernode API at all — it is pure-SSH, no `HypernodeApiClient` dependency.
- **Hard guard**: `validate_eph_node_name(node_name)` (imported from `_guards`, not reimplemented) is the very first line of `exec_command`, before any subprocess is spawned. Verified structurally unbypassable — the parametrized rejection test asserts `mock_create.assert_not_awaited()` for `pps`, `pps.hypernode.io`, `pps-staging`, `pps-staging.hypernode.io`.
- ssh(1) reserves exit code 255 for its own connection/auth failures (distinct from the remote command's 0-254 range). `exec_command` detects `returncode == 255` and raises `SshConnectionError(stderr)` instead of silently returning `exit_code: 255` in the result dict — this satisfies "propagates... rather than swallowing them".
- Timeout: `asyncio.wait_for(process.communicate(), timeout=timeout)`; on `TimeoutError` the process is `.kill()`'d and `.wait()`'d before raising `SshCommandTimeoutError`, so no orphaned subprocess is left running. Timeout is a keyword-only param defaulting to `DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0`, fully caller-configurable.
- TDD note: requirements 2 and 3 (both `-eph` pattern rejection variants) passed immediately once written, because the guard was already wired in during requirement 1's implementation (reusing the existing `_guards` module, not reimplementing it — no behavior was added for these two, only new test coverage of already-present behavior). Flagged per the over-implementation-detection rule; not a violation since the guard is shared, pre-existing, safety-critical code that requirement 1 necessarily had to invoke.

**Manual smoke-test procedure (NOT run — no real Hypernode account in this sandbox, per task instructions)**:
1. Use `brancher_create` (task 003) to spin up a real Brancher node for an allowlisted app, e.g. `pps-eph<id>`.
2. Wait for the node to report ready (poll `brancher_ssh_info` / `ip_address` non-null, per task 006).
3. Call `exec_command('pps-eph<id>', 'whoami')` directly (or via the not-yet-wired MCP tool once task 016 lands) and confirm:
   - It returns exit_code 0 with the expected remote username in stdout, with NO extra SSH key provisioning performed beyond what the operator's local machine/agent already has configured.
   - `ssh <user>@<node>-eph<id>.hypernode.io whoami` also works directly from a plain shell, to isolate MCP-layer issues from SSH/key issues.
4. Assumption under test: SSH keys inherit via the Brancher's backup-clone mechanism (i.e., the same keys authorized on the parent production Hypernode app already work against the `-eph` clone), so no extra key provisioning step is needed. **This assumption is unverified in this session** — it is carried over from earlier research in the plan, not lab-confirmed against a real account.
5. If the assumption is wrong (SSH auth fails against the `-eph` node with keys that work on the parent app), this task's scope grows to include a key-provisioning step (e.g. copying the operator's public key to the Brancher node's `authorized_keys` on creation) — flag back to the plan (`_plan.md`) if that smoke test fails.

**Verification**: `uv run pytest -v` → 49 passed (8 new for `brancher_exec`, 41 pre-existing incl. `brancher_put` from the concurrently-run task 008). `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` all clean on the files touched by this task (`brancher_exec.py` and `test_brancher_exec.py`).
