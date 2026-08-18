# Task 008: brancher_put Tool

**Status**: completed
**Depends on**: 006
**Retry count**: 0

## Description
Implement the `brancher_put` MCP tool: sync local files/directories to a Brancher node over scp/rsync, for the case where a client wants to push local code changes up to the node rather than having Claude edit in place over SSH.

## Context
- Shells out to `rsync` (preferred, for incremental syncs) or `scp`, using the same local-SSH-agent model as task 007.
- Same `-eph`-only guard as task 007 — reject any target not matching the Brancher naming pattern before syncing.

## Requirements (Test Descriptions)
- [x] `it syncs a local file to the target path on a valid -eph node`
- [x] `it syncs a local directory recursively to a valid -eph node`
- [x] `it rejects the sync when the target hostname does not match the -eph pattern`
- [x] `it propagates sync failures as a clear error`

## Acceptance Criteria
- All requirements have passing tests (unit tests mock the subprocess call)
- Code follows code standards
- No decrease in test coverage

## Implementation Notes
- Implemented `put_files()` in `src/pb_hypernode_mcp/tools/brancher_put.py`. Uses `rsync -az --rsh 'ssh -p <port>'` for both file and directory syncs (archive mode `-a` is inherently recursive, so no directory-specific branch was needed).
- Reused `_guards.validate_eph_node_name` — guard runs before the subprocess is ever invoked (verified via `assert_not_awaited()` in the rejection test).
- `run_subprocess` is an injectable async callable (`SubprocessRunner = Callable[..., Coroutine[Any, Any, Any]]`), defaulting to `asyncio.create_subprocess_exec`. Unit tests inject an `AsyncMock` + `FakeProcess` stub (`.returncode` + async `.communicate()`), so no real subprocess is ever shelled out in the test suite.
- Non-zero `returncode` raises `SyncError` with the decoded stderr, satisfying the "propagate sync failures as a clear error" requirement.
- Per task instructions, `server.py` was NOT touched — no `register()` function was added to this module; wiring is deferred to task 016.
- Requirement 2 ("syncs a local directory recursively") passed immediately once requirement 1's implementation existed — noted per TDD process as expected (not over-implementation): `-az` already covers recursion for both files and directories, so no extra code branch was required.
- Host/port targeting mirrors the `brancher_ssh_info` convention: `user@host` = `<node_name>@<node_name>.hypernode.io`, default port 22.
- Full suite: `uv run pytest -v` → 49 passed (37 pre-existing + 4 new in `test_brancher_put.py`; the other 8 delta came from parallel tasks 005/007 running concurrently in this shared repo — no failures introduced by this task).
- `uv run ruff check`, `uv run ruff format --check`, and `uv run pyright` all clean on `src/pb_hypernode_mcp/tools/brancher_put.py` and `tests/tools/test_brancher_put.py`. A pre-existing line-length lint issue in `tests/tools/test_brancher_exec.py` (from parallel task 007) is out of scope for this task and was left untouched.
