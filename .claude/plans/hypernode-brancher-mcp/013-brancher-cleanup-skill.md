# Task 013: brancher-cleanup Skill

**Status**: completed
**Depends on**: 004, 005, 016
**Retry count**: 0

## Description
Build the `brancher-cleanup` Claude Code skill: lists all active Brancher nodes for an app (task 004), flags nodes past a configurable wall-clock age threshold, and deletes them (task 005's confirm-before-delete flow) — either interactively per-node or in bulk.

## Context
- Age threshold is wall-clock minutes-alive, per this session's confirmed research (Brancher bills uptime regardless of idle) — default threshold should be documented and configurable (Hypernode's own docs example uses 4 hours as a sample threshold).
- Must show minutes-used per node so the user understands the cost being avoided by cleanup.

## Requirements (Test Descriptions)
- [x] `it lists all active nodes with their minutes-used`
- [x] `it flags nodes past the configured age threshold`
- [x] `it deletes a flagged node only after confirmation`
- [x] `it supports bulk-deleting all flagged nodes in one pass`
- [x] `it reports nothing to clean up when no nodes exceed the threshold`

## Acceptance Criteria
- All requirements have passing tests or documented manual verification steps
- Code follows code standards

## Implementation Notes

- Extracted the one piece of real decision logic in this skill — the
  age-threshold filtering — into `src/pb_hypernode_mcp/cleanup_logic.py`:
  - `flag_stale_nodes(nodes, threshold_minutes=DEFAULT_AGE_THRESHOLD_MINUTES)`
    — pure function, `minutes >= threshold_minutes`.
  - `DEFAULT_AGE_THRESHOLD_MINUTES = 240` (Hypernode's own docs sample: 4
    hours), overridable per call.
  - `cleanup_stale_nodes(appname, *, client, settings, threshold_minutes,
    confirm)` — async orchestrator composing the existing
    `list_brancher_nodes` (task 004) and `delete_brancher_node` (task 005)
    tool functions with `flag_stale_nodes`. `confirm=False` returns the
    flagged set without deleting anything (bulk-level mirror of
    `brancher_delete`'s own confirm gate); `confirm=True` deletes every
    flagged node and returns the deleted names; returns a "nothing to clean
    up" message when nothing is flagged, regardless of `confirm`.
  - This function is a tested reference implementation of the bulk flow —
    the skill itself still drives the actual turn-by-turn MCP tool calls
    (`brancher_list` / `brancher_delete`), per the task's framing that this
    is primarily a SKILL.md, not new business logic wired into the MCP
    server. `cleanup_stale_nodes` was not registered as its own MCP tool.
- All 5 requirement tests added in `tests/test_cleanup_logic.py`, named to
  match the requirement text exactly (`test_it_lists_all_active_nodes...`
  etc.). Ran RED (ModuleNotFoundError before `cleanup_logic.py` existed)
  then GREEN (all 5 passing) per TDD discipline.
- `skills/brancher-cleanup/SKILL.md` rewritten (stub overwritten, frontmatter
  `name`/`description` kept identical to satisfy
  `tests/test_plugin_manifest.py::test_it_declares_all_three_skills_in_the_plugin_manifest`)
  describing: list via `brancher_list` → report full list with minutes →
  flag via the same `>=` threshold rule as `flag_stale_nodes` → single-node
  vs. bulk choice → single-node confirm-before-delete flow (unconfirmed
  `brancher_delete` call to preview, then `confirm=True` re-call) → bulk
  confirm-before-delete-all flow (present full flagged plan, confirm once,
  then `confirm=True` per flagged node) → explicit "never skip confirmation"
  rule → worked example.
- Full suite: 68 passed (63 pre-existing + 5 new), verified via
  `.venv/bin/python -m pytest -v --ignore=tests/tools/test_brancher_spinup_flow.py`.
  `uv` is not installed in this environment; used `.venv/bin/python -m
  pytest`/`ruff` directly against the repo's existing `.venv` instead (same
  installed deps `uv run` would use).
  `ruff check`/`ruff format --check` clean on both new files.
- Pre-existing, out-of-scope issue (NOT caused by this task, left
  untouched): `tests/tools/test_brancher_spinup_flow.py` is an untracked
  file (git status: fully untracked repo, "Initial commit" only) that
  appeared mid-session — it imports
  `pb_hypernode_mcp.tools.brancher_spinup_flow`, a module that does not
  exist in this repo, and fails collection when running the unscoped
  `pytest -v`/`uv run pytest -v`. This looks like a concurrently-running,
  unrelated task's in-progress artifact (not part of task 013's dependency
  set — 004/005/016 — and not referenced anywhere in the plan doc for this
  task). Flagging for whoever owns that other task/file; not fixed or
  deleted here since it's outside this task's file ownership.
