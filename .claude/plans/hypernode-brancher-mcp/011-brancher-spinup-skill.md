# Task 011: brancher-spinup Skill

**Status**: completed
**Depends on**: 010, 016
**Retry count**: 0

## Description
Build the `brancher-spinup` Claude Code skill: a thin orchestration layer over the MCP tools that creates a node (via the fully-guarded create+sanitize flow), waits for it to be ready, and returns the URL and SSH connection details to the user in a clear, readable format.

## Context
- This is a skill (prompt/markdown instructions for Claude), not more Python — it tells Claude Code how to call the underlying MCP tools in sequence and how to present the result.
- Should surface the guardrail context to the user as it runs (label used, minutes remaining, allowlist check passed) rather than hiding it.
- After spinup succeeds, the skill should also mention `brancher_ssh_info` for getting connection details if the user wants to SSH in directly, not just the URL.

## Requirements (Test Descriptions)
- [x] `it invokes brancher_create with a required label argument` — adapted to the registered MCP tool wrapper: `test_it_invokes_brancher_create_with_a_required_label_argument` (`tests/tools/test_brancher_spinup_flow.py`) verifies `brancher_spinup` rejects an empty `labels` list, propagated from `create_brancher_node`'s existing guardrail through `ToolError`.
- [x] `it reports the node URL and SSH info to the user after creation completes` — `test_it_reports_the_node_url_and_ssh_info_to_the_user_after_creation_completes` verifies the tool's structured result includes `node_name`/`access_url`; the "SSH info" half of this requirement is satisfied in prose (SKILL.md step 4 instructs mentioning `brancher_ssh_info` for direct connection details) since that's a follow-on tool call, not embedded in the spinup result itself.
- [x] `it surfaces the guardrail checks (minutes remaining, allowlist) in its output` — `test_it_surfaces_the_guardrail_checks_minutes_remaining_and_allowlist_in_its_output` verifies `minutes_remaining` is present in a successful result and that an allowlist rejection propagates as a `ToolError` mentioning "allowlist".
- [x] `it surfaces a clear error to the user if creation or sanitization fails` — `test_it_surfaces_a_clear_error_to_the_user_if_creation_or_sanitization_fails` verifies a `SanitizationFailedError` mid-sequence propagates through the registered tool as a `ToolError` with a clear "Sanitization failed" message (access URL withheld, per the underlying flow's guarantee).

## Acceptance Criteria
- All requirements have passing tests (test the new MCP tool wrapper directly — that's the testable surface; the SKILL.md prose itself isn't unit-testable, documented in the split above) — DONE, 78/78 tests pass.
- Code follows code standards — DONE (`ruff check`, `ruff format --check`, `pyright` all clean).

## Implementation Notes

**Split: tool wrapper (tested) vs. skill prose (not tested).** `spinup_sanitized_brancher_node()` (the create -> wait -> sanitize -> report-ready orchestration function) already existed, fully tested, from a prior task — but it was only callable as a Python function, not as something Claude Code could invoke mid-conversation. Went with option (a) from the task brief: added `register()` to `src/pb_hypernode_mcp/tools/brancher_spinup_flow.py`, registering a new `brancher_spinup` MCP tool that wraps the orchestration function, and wired it into `create_server()` in `src/pb_hypernode_mcp/server.py` (now 7 tools). `register()`'s signature mirrors `brancher_create.register()` (`client_factory` returning `(HypernodeApiClient, app_allowlist)`), plus keyword-only pass-throughs (`sanitization_config`, `exec_command`, timing knobs) defaulting to production behaviour so tests can inject fakes without touching real SSH/HTTP.

The four requirements are tested against this new `register()`/`brancher_spinup` tool surface directly (`tests/tools/test_brancher_spinup_flow.py`, plus one server-level smoke test `test_it_exposes_brancher_spinup_as_a_callable_mcp_tool_on_the_server` in `tests/test_server.py`) rather than against the skill's markdown prose, which isn't unit-testable in this project's setup. `skills/brancher-spinup/SKILL.md` was filled in with the actual flow (ask for label -> call `brancher_spinup` -> report node_name/minutes_remaining/access_url/sanitization_commands_run -> mention `brancher_ssh_info` as a follow-on -> error handling per failure mode), following the structure of the existing `brancher-cleanup` skill.

**Type-checking gotcha (pyright):** `FastMCP.call_tool()`'s declared return type (`Sequence[ContentBlock] | dict[str, Any]`) doesn't line up with its actual runtime 2-tuple return, so `_content, result = await server.call_tool(...)` followed by `result['key']` indexing triggers `reportIndexIssue` under pyright (pre-existing project pattern, not introduced here). Followed the existing convention already used throughout `tests/test_server.py`: assert full dict equality (`assert result == {...}`) instead of indexing into individual keys.

Full suite: 78 passed (73 pre-existing + 5 new: 4 in `test_brancher_spinup_flow.py`, 1 in `test_server.py`). `ruff check`, `ruff format --check`, and `pyright` all clean on `src` and `tests`.
