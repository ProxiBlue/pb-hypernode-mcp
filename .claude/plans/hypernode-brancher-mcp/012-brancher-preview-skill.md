# Task 012: brancher-preview Skill

**Status**: completed
**Depends on**: 011, 008
**Retry count**: 0

## Description
Build the `brancher-preview` Claude Code skill: the full loop — spin up a node (task 011), apply code changes (via `brancher_exec`/`brancher_put`), run the Magento build (`setup:upgrade`/`di:compile`/static content deploy as needed), take a screenshot of the result via the existing browser MCP (claude-in-chrome / chrome-devtools — nothing new to build there), and remind the user to delete the node when done.

## Context
- Reuses the client's own browser MCP for the screenshot step — this skill just needs to know to call it against the Brancher URL, no new screenshot tooling.
- "Apply changes" can mean either: Claude edits code directly on the node over `brancher_exec` (SSH), or the client pushes local changes via `brancher_put` — the skill should support both patterns since they serve different workflows (quick experiment vs. testing an existing local branch).
- Must end with an explicit reminder that the node is still running and costs Brancher minutes until deleted — this skill does not auto-delete (that's `brancher-cleanup`'s job, or an explicit follow-up call to `brancher_delete`).

## Requirements (Test Descriptions)
- [x] `it applies a local file change to the node via brancher_put when given a local path` — `test_it_applies_a_local_change_to_the_node_via_brancher_put_given_a_local_path` (`tests/test_preview_logic.py`); name shortened to fit the project's 100-char line limit (ruff `E501`), full requirement text kept verbatim in the test's docstring.
- [x] `it runs the Magento build sequence after changes are applied` — `test_it_runs_the_magento_build_sequence_after_changes_are_applied` (`tests/test_preview_logic.py`).
- [x] `it invokes the browser MCP to screenshot the node's URL` — no Python surface exists for this in the plugin (by design — no new screenshot tool was built, per task context); documented as a manual verification step in `skills/brancher-preview/SKILL.md`'s Implementation notes section instead of a pytest case, per `.claude/testing.md`'s guidance against weak/fake automated tests for non-pytest-mockable skill steps.
- [x] `it reminds the user the node is still running and consuming minutes after the loop completes` — `test_it_reminds_the_user_the_node_is_still_running_and_consuming_minutes` (`tests/test_preview_logic.py`); name shortened for the same line-length reason, full requirement text in the docstring.

## Acceptance Criteria
- All requirements have passing tests or documented manual verification steps — DONE.
- Code follows code standards — DONE (`ruff check`, `ruff format --check` clean; `pyright` clean on the new files — a pre-existing, unrelated `reportMissingImports` set appears on a full-repo `pyright src tests` run in this environment because `pyright` isn't picking up the project venv's interpreter by default; scoped `pyright` runs against the new files are clean, and this is not something introduced by this task).

## Implementation Notes

Extracted the two pieces of real decision logic in the preview loop into
`src/pb_hypernode_mcp/preview_logic.py` (mirrors task 013's
`cleanup_logic.py` split — pure/async helpers, tested directly; the skill's
markdown prose drives the actual turn-by-turn MCP tool calls):

- `decide_build_commands(changed_paths: list[str]) -> list[str]` — pure
  function. Always includes `bin/magento cache:flush`; adds
  `setup:upgrade` when a changed path contains `db_schema.xml`/`module.xml`,
  `setup:di:compile` when a path contains `di.xml`, and
  `setup:static-content:deploy -f` when a path looks like a frontend
  asset/template (`.phtml`/`.css`/`.js`/`/web/`/`view/frontend`/`view/adminhtml`).
  A reasonable v1 default per the task's own framing ("keep it simple...
  doesn't need to be exhaustive"), not a full dependency-graph analysis.
- `apply_local_change(node_name, local_path, remote_path, *, put_files)` —
  thin async wrapper around `brancher_put`'s `put_files` (task 008), kept as
  its own testable call site rather than inlined into a larger orchestrator.
- `run_build_sequence(node_name, changed_paths, *, exec_command)` — composes
  `decide_build_commands()` with a sequence of `exec_command` (task 007)
  calls, aggregating per-command results.
- `cleanup_reminder(node_name, access_url) -> str` — pure function producing
  the end-of-loop cost reminder text.

`skills/brancher-preview/SKILL.md` was filled in (stub overwritten,
frontmatter `name`/`description` kept byte-identical to satisfy
`tests/test_plugin_manifest.py::test_it_declares_all_three_skills_in_the_plugin_manifest`)
describing the 5-step flow: reuse `brancher-spinup` for step 1 (explicitly
told not to reimplement it) → apply changes via `brancher_put` (existing
local branch) or `brancher_exec` (in-session quick edit), both patterns
supported and combinable → run the decided build sequence via `brancher_exec`
→ view the result with whatever browser MCP tool is already in the client's
session (no new tool built, per task context — generic instruction, not a
named tool since this plugin can't know which one a given client has) →
explicit, mandatory cost reminder using `cleanup_reminder()`'s wording,
never auto-deleting.

**Test-name line-length adaptation.** Two of the four requirement strings,
formatted as `async def test_<full requirement text>() -> None:` on an
empty-parameter test function, exceeded the project's 100-char ruff line
limit (confirmed via `ruff check`, `E501`) even after `ruff format`'s
attempt to wrap the return-type annotation across lines — there are no
parameters to wrap instead. Shortened those two test names
(`test_it_applies_a_local_change_to_the_node_via_brancher_put_given_a_local_path`,
`test_it_reminds_the_user_the_node_is_still_running_and_consuming_minutes`)
while keeping them unambiguously traceable to their requirement, and put the
full, verbatim requirement text in each test's docstring. Same adaptation
precedent as task 011's Implementation Notes ("adapted to the registered MCP
tool wrapper").

Full suite: `.venv/bin/python -m pytest -v` → 81 passed (78 pre-existing + 3
new in `tests/test_preview_logic.py`; the fourth requirement, the browser MCP
screenshot step, is documented manual verification only — see above).
`uv` is not installed in this environment (same as task 013's note); used
`.venv/bin/python -m pytest`/`ruff`/`pyright` directly against the repo's
existing `.venv`. `ruff check src tests` and `ruff format --check src tests`
both clean. `pyright` scoped to the new files
(`src/pb_hypernode_mcp/preview_logic.py`, `tests/test_preview_logic.py`) is
clean; the unscoped `pyright src tests` run surfaces `reportMissingImports`
across every pre-existing file in the repo (httpx/pydantic/mcp/pytest all
"unresolved") — an environment interpreter-resolution issue unrelated to
this task's changes, not introduced here.
