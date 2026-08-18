# Task 005: brancher_delete Tool + Confirm-Before-Delete

**Status**: completed
**Depends on**: 002, 004
**Retry count**: 0

## Description
Implement the `brancher_delete` MCP tool with a confirm-before-delete guardrail that shows the target node's details before deletion proceeds.

## Context
- DELETE against the Brancher node's API endpoint.
- Confirm-before-delete: the tool must surface the target node name/label/minutes-used (via task 004's list capability) as part of its response/flow so a caller can't blind-delete by node name alone without seeing what they're deleting. Exact confirmation mechanism (two-step tool call vs. a `confirm=true` flag) is an implementation choice — document whichever is chosen.
- Must also enforce the app allowlist (same as create/list).

## Requirements (Test Descriptions)
- [x] `it deletes a Brancher node given its exact node name`
- [x] `it surfaces the target node's details before deletion completes`
- [x] `it rejects deletion when the app is not in the allowlist`
- [x] `it rejects deletion of a node name that does not match the -eph naming pattern`
- [x] `it returns a clear error when the target node does not exist`

## Acceptance Criteria
- All requirements have passing tests
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

Built `delete_brancher_node(client, settings, node_name, *, confirm=False)` in
`src/pb_hypernode_mcp/tools/brancher_delete.py` — a plain async function, no
`register()`/server wiring (per task instructions, tool registration for all
pending tools is consolidated in task 016 to avoid clashing with tasks 007/008
running in parallel).

**Confirm-before-delete mechanism chosen: `confirm: bool = False` flag on the
same function**, not a separate two-step tool pair. Rationale:
- Single function keeps the guardrail (name pattern -> allowlist -> existence
  check) shared between the "preview" and "actually delete" paths — no
  duplicated lookup logic across two tools.
- On `confirm=False` (default) the function does the full guard chain, looks
  up the target node via `list_brancher_nodes` (reusing task 004's tool
  directly rather than re-implementing the GET), and returns
  `{'confirm_required': True, 'node': {...}, 'message': '...'}` without
  calling DELETE. The `node` dict is exactly what `list_brancher_nodes`
  returns for that node (`name`, `host`, `minutes` — the list endpoint has no
  separate `label` field, so those three are what's surfaced).
- On `confirm=True` the same lookup runs first (so allowlist/existence checks
  are never skipped just because the caller passed `confirm=True` up front),
  then `client.delete(node_name, '')` fires and the function returns
  `{'deleted': True, 'node_name': node_name}`.

App allowlist enforcement: node name's appname prefix is derived by stripping
the `-eph<id>` suffix (regex `^(?P<appname>.+)-eph[0-9]+$`, applied only after
`validate_eph_node_name` already confirmed the pattern matches) and passed
into `list_brancher_nodes(appname, ...)`, which already raises
`AppNotAllowedError` from `brancher_list.py` when the app isn't allowlisted —
no separate allowlist check was reimplemented.

Node-not-found: `NodeNotFoundError` (new, defined in `brancher_delete.py`)
raised when no node in the `list_brancher_nodes` result matches `node_name`
exactly.

Order of guards, all before any network call for invalid input: (1)
`validate_eph_node_name` (raises `InvalidNodeNameError` from `_guards.py`),
(2) allowlist check via `list_brancher_nodes` (raises `AppNotAllowedError`),
(3) existence check against the returned node list (raises
`NodeNotFoundError`), (4) confirm gate, (5) DELETE call.

Tests: `tests/tools/test_brancher_delete.py`, 5 tests, all passing, call
`delete_brancher_node` directly (not through the server) per task
instructions. Full suite: 37 passed (pre-existing collection errors in
`tests/tools/test_brancher_exec.py` / `test_brancher_put.py` are from
concurrent tasks 007/008 in flight, unrelated to this change — confirmed by
running the suite with those two files ignored, same 37 pass).

`ruff check`/`ruff format --check` clean for all files touched by this task.
`pyright` reports only pre-existing `reportMissingImports` for `httpx`,
`pydantic`, `mcp`, etc. across the whole repo (venv not being picked up by the
pyright invocation) — same errors present on every existing file, not
introduced by this change.
