# Task 017: Security Remediation (Sanitization Bypass + rsync Injection)

**Status**: completed
**Depends on**: 016
**Retry count**: 0

## Description
Fix two findings from a post-implementation security review (2-of-3 FAIL from static-analyst + adversarial-tester, independently confirmed with file:line evidence and PoCs):

1. **CRITICAL — sanitization gate bypass.** `brancher_create` and `brancher_ssh_info` are registered as standalone MCP tools (`server.py`) with zero sanitization-state checking. Any MCP caller can call `brancher_create` directly (skipping `brancher_spinup` entirely), get a `node_name`, then call `brancher_ssh_info`/`brancher_exec` directly against it — full SSH access to a live, unsanitized production clone (real customer PII, real payment credentials, real admin password) on a publicly guessable URL (`https://{node_name}.hypernode.io/`, pure string interpolation, no secret). This directly violates `_plan.md`'s Success Criteria: "Every `brancher_create` automatically sanitizes PII... this cannot be skipped via a flag" — true in letter (no flag exists) but false in practice (a whole alternate tool-call path skips it). The "non-bypassable" claim in README/SKILL.md is advisory prompt text aimed at the calling LLM, not a structural code-level control.

2. **HIGH — rsync argument/shell injection in `brancher_put`.** `remote_path`/`local_path` are interpolated unescaped into the rsync destination string (`brancher_put.py`), and rsync is invoked without `--protect-args`. rsync's default (non-protect-args) transport passes the trailing path argument to be interpreted by the remote shell `ssh` invokes on the Brancher node — shell metacharacters in `remote_path` (backticks, `;`, `$()`) reach a shell-interpreting sink on the remote node even though the local subprocess call itself uses argv (no `shell=True`).

## Context
- Root cause of finding 1: task 010/011 built the sanitized orchestration as a NEW parallel tool (`brancher_spinup`) instead of gating the EXISTING `brancher_create` tool itself. The original plan's intent (`_plan.md` Architecture Notes, task 010's own description) was for sanitization to be wired INTO `brancher_create`'s flow, not offered as an alternative path alongside an still-exposed raw one.
- Fix for finding 1 (do NOT just patch symptoms — fix the exposed surface): `src/pb_hypernode_mcp/server.py` currently registers `brancher_create` (raw, unsanitized) as its own tool. Stop registering the raw `create_brancher_node` as a standalone MCP tool. The only externally-callable node-creation tool should be the fully-gated flow currently implemented as `brancher_spinup` — expose it AS `brancher_create` (rename the registered tool name, not the internal function) so there is exactly one node-creation entry point and it is always sanitized. Keep `create_brancher_node` (the raw function) as an internal building block used by the flow — just remove its standalone `register()` call / stop wiring it into `create_server()`. Decide whether to keep a `brancher_spinup` alias tool name too (for backward-compat with the three skills that already reference it) or update all three `SKILL.md` files + README to use the single `brancher_create` name — your call, but there must be exactly ONE way to create a node from outside this codebase, and it must always be the sanitized path. Update tests accordingly (`tests/tools/test_brancher_create.py`'s "registers on server" test, `tests/test_server.py`'s tool-count/tool-list assertions, `tests/tools/test_brancher_spinup_flow.py`'s registration test) to reflect whichever naming decision you make.
- `brancher_ssh_info` itself is fine to keep exposed (it doesn't create anything) — the bypass risk goes away once there's no way to create an unsanitized node to point it at in the first place.
- Fix for finding 2: pass `--protect-args` (or `-s`) to rsync so the remote-side shell never re-parses the path argument, AND `shlex.quote()` `local_path`/`remote_path` as defense-in-depth even with `--protect-args` set. Add a regression test with a path containing shell metacharacters (e.g. `` `touch /tmp/pwned` `` or `; rm -rf /`) asserting the injected payload never reaches a shell-interpretable position.
- Two LOW/lower-priority findings from the review, fix if time allows (not blocking):
  - `tools/_guards.py`'s `-eph` regex uses `$` instead of `\Z`/`.fullmatch()`, so a trailing `\n` passes validation (confirmed PoC, low practical impact given the restrictive character class, but violates the guard's own "single source of truth" contract). One-line fix: switch to `.fullmatch()` or anchor with `\Z`.
  - `sanitization/commands.py`'s `_build_update_sql`/`_build_config_set_command` interpolate table/column/value/where/config_path with no escaping beyond a single `shlex.quote()` on `sandbox_value` only — currently not reachable (only the hardcoded `DEFAULT_MAGENTO_SANITIZATION_CONFIG` is wired, no per-client config loader exists yet), but flagged by two independent reviewers as a landmine for whenever that loader ships. Add basic escaping/validation now while the surface is small, or add an explicit `# SECURITY` comment + tracking note if deferring — your call given time, but do not silently ignore it.

## Requirements (Test Descriptions)
- [x] `it does not expose a way to create a Brancher node that skips sanitization`
- [x] `it exposes exactly one node-creation MCP tool and that tool always runs the full sanitize-before-ready flow`
- [x] `it rejects a remote_path containing shell metacharacters from reaching an unescaped rsync destination string`
- [x] `it passes --protect-args to rsync so the remote shell never re-parses the path argument`
- [x] `it rejects a node name with a trailing newline (regex fullmatch, not partial match)`

## Acceptance Criteria
- All requirements have passing tests
- Full suite (`uv run pytest -v`) passes, including all pre-existing tests updated for the tool-registration change
- `ruff check`/`ruff format --check`/`pyright` clean
- README.md and all three SKILL.md files updated to match whatever tool-naming decision is made for finding 1 — no stale references to a bypassable raw `brancher_create`

## Implementation Notes

**Tool-naming decision (finding 1):** Single-name approach — the gated flow
is now exposed as `brancher_create`, and `brancher_spinup` as a tool name no
longer exists anywhere. Rationale: keeping two names for the same operation
(`brancher_create` == `brancher_spinup`) would have been a permanent source
of confusion/doc drift and an easy place for a future change to accidentally
reintroduce an unsanitized alias; a single unambiguous name is safer and
simpler to reason about. Concretely:
- `tools/brancher_spinup_flow.py::register()` now registers its MCP tool
  under `name='brancher_create'` (was `'brancher_spinup'`); the internal
  function/module names (`spinup_sanitized_brancher_node`,
  `brancher_spinup_flow.py`, `tests/tools/test_brancher_spinup_flow.py`)
  were deliberately left unchanged — only the MCP-level tool name moved, per
  the task's recommended approach.
- `tools/brancher_create.py::create_brancher_node()` is now internal-only:
  its `register()` function was deleted outright (not kept dormant), and a
  `SECURITY:` module-docstring note explains why it must never be
  independently registered again. `server.py` no longer imports the
  `brancher_create` module at all (only `brancher_spinup_flow`), and its
  `create_server()` docstring documents the "six tools, one creation entry
  point" invariant.
- Test changes: `tests/tools/test_brancher_create.py` dropped its
  "registers on server" test and `FastMCP`/`register` imports (per the
  task's second suggested option — `create_brancher_node` is exercised only
  as an internal function now). `tests/tools/test_brancher_spinup_flow.py`
  had its `call_tool('brancher_spinup', ...)` call sites renamed to
  `'brancher_create'` (5 call sites) — test function names were left as-is
  since they describe behavior, not the tool name. `tests/test_server.py`
  gained two new regression tests
  (`test_it_does_not_expose_a_way_to_create_a_brancher_node_that_skips_sanitization`,
  `test_it_exposes_exactly_one_node_creation_mcp_tool_and_that_tool_always_runs_the_full_sanitize_before_ready_flow`),
  had its old `test_it_exposes_brancher_create_as_a_callable_mcp_tool_on_the_server`
  updated to assert the full gated-flow result shape (was asserting the old
  raw `{node_name, minutes_remaining}` shape), and had the now-redundant
  `test_it_exposes_brancher_spinup_as_a_callable_mcp_tool_on_the_server`
  removed (it duplicated the updated `brancher_create` test once the tool
  was renamed). `test_it_constructs_a_single_shared_hypernode_api_client_reused_across_tool_calls`
  gained an ssh-subprocess mock since `brancher_create` now requires one.
- Docs updated to match: `README.md` (tool count 7→6, merged the two-row
  `brancher_create`/`brancher_spinup` table into one row, safety-guardrails
  section, limitations section), `skills/brancher-spinup/SKILL.md` and
  `skills/brancher-preview/SKILL.md` (all `brancher_spinup(...)` call-site
  references and prose renamed to `brancher_create`). Skill directory names
  (`brancher-spinup`, `brancher-preview`) were left unchanged — those name
  the *workflow*, not the MCP tool, and are unaffected by the rename.

**Finding 2 (rsync injection):** `tools/brancher_put.py::put_files()` now
passes `--protect-args` to rsync and wraps `remote_path` in `shlex.quote()`
before interpolating it into the `user@host:path` destination string.
`local_path` was deliberately NOT `shlex.quote()`-wrapped, despite the
task's "local_path/remote_path" phrasing — `local_path` is its own,
separate argv entry passed directly to `create_subprocess_exec` (no local
shell ever parses it), so quoting it would corrupt legitimate local paths
(the quote characters would become part of the literal filename passed to
rsync, since there is no shell to strip them). `remote_path` is the actual
injection vector: it is concatenated into a single string that rsync
forwards to a remote-side shell context, which is exactly what
`--protect-args` + `shlex.quote()` jointly harden. Regression tests added:
`test_it_rejects_a_remote_path_containing_shell_metacharacters_...` and
`test_it_passes_protect_args_to_rsync_...` in `tests/tools/test_brancher_put.py`.

**Lower-priority items, both taken:**
- `tools/_guards.py::is_eph_node_name()` switched from `.match()` to
  `.fullmatch()` — one-line fix, closes the trailing-`\n` gap. New test file
  `tests/tools/test_guards.py` added (didn't exist before) with the
  regression test.
- `sanitization/commands.py`: left the interpolation behavior unchanged (not
  reachable by external input today — only the hardcoded
  `DEFAULT_MAGENTO_SANITIZATION_CONFIG` is wired) but added explicit
  `SECURITY:` docstring notes on `_build_update_sql`/`_build_config_set_command`
  documenting the escaping gap for whenever a per-client config loader ships,
  per the task's "leave a clear comment" fallback option.

**Verification:** Full suite `84 passed` (was 81 before this task; net +3:
guards test, 2 rsync regression tests — several other tests were
edited/merged/removed rather than added, since they tested behavior that no
longer exists). `ruff check src tests` and `ruff format --check src tests`
both clean. `pyright` clean via
`.venv/bin/pyright --pythonpath .venv/bin/python src tests` (the plain
`uv run pyright` invocation from the task description was unavailable in
this environment — no `uv` binary on PATH — so the project's own `.venv`
`pyright` was invoked directly against the same interpreter `uv` would have
used).
