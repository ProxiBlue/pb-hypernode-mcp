# Task 004: brancher_list Tool

**Status**: completed
**Depends on**: 002
**Retry count**: 0

## Description
Implement the `brancher_list` MCP tool: list all active Brancher nodes for a given app, including name, IP, hostname, and minutes used (wall-clock uptime, per this session's confirmed research — not idle-aware).

## Context
- Backing this with `hypernode-systemctl brancher --list --machine-readable` equivalent via REST, or the REST list endpoint directly if available — use whichever the API client (task 002) exposes cleanly.
- `minutes` field is wall-clock uptime since creation — task 013 (cleanup) depends on this being accurate and clearly labeled as such (not "active use time").

## Requirements (Test Descriptions)
- [x] `it lists all active Brancher nodes for an app`
- [x] `it returns each node's name, host, and minutes`
- [x] `it returns an empty list when no Brancher nodes exist for the app`
- [x] `it rejects the call when the app is not in the allowlist`

## Acceptance Criteria
- All requirements have passing tests
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

Implemented `src/pb_hypernode_mcp/tools/brancher_list.py`:

- `list_brancher_nodes(appname, *, client: HypernodeApiClient, settings: Settings) ->
  list[dict[str, Any]]` — the core business-logic function, matching the pattern of the
  parallel task 003 (`create_brancher_node`) and task 006 tools: a plain async function taking
  an already-constructed `HypernodeApiClient` plus the data needed for allowlist enforcement,
  no FastMCP/`server.py` wiring included. Neither sibling in-progress tool (`brancher_create.py`,
  `brancher_ssh_info.py`) registers itself on the server either — `server.py` still only builds
  a bare `FastMCP` instance — so actual tool registration is evidently deferred to a later task
  (likely 010, install-hook-orchestration). Kept `server.py` completely untouched to guarantee
  zero merge-conflict risk with the two tasks running in parallel on the same file.
- `AppNotAllowedError(Exception)` — raised when `appname not in settings.app_allowlist`, checked
  before any API call is made (verified via a test whose mock HTTP handler raises
  `AssertionError` if invoked, proving the guard short-circuits before the request).
- **API response shape assumption (NOT verified against the real Hypernode API — flagged per
  task instructions):** `GET /app/<appname>/brancher/` is assumed to return
  `{"nodes": [{"name": ..., "host": ..., "minutes": ...}, ...]}` — a dict with a top-level
  `nodes` key holding a list of node dicts, each with at least `name`, `host`, `minutes`. If the
  real API returns a bare JSON list instead, or nests it under a different key (e.g. `results`,
  `data`), `list_brancher_nodes` will need a one-line adjustment to `response.get('nodes', [])`.
  `minutes` is documented (module docstring + task Context) as wall-clock uptime since node
  creation, not idle-aware — this label is preserved verbatim in the returned dicts, no
  renaming/derivation applied.
- Requirement 2 (`name`/`host`/`minutes` fields) and requirement 3 (empty list) both passed
  immediately once requirement 1's implementation was written — the list/dict comprehension
  built to satisfy requirement 1 already returns the exact three keys per node and naturally
  produces `[]` for an empty `nodes` array. Noted per TDD process as expected (not
  over-implementation): the comprehension is the minimal correct shape, not scaffolding added
  ahead of need.
- `tests/tools/test_brancher_list.py` — 4 tests, one per requirement, using the same
  `httpx.MockTransport` + `HypernodeApiClient` pattern established in `tests/test_api_client.py`.
- `ruff check`/`ruff format --check` clean. `pyright` clean via
  `.venv/bin/python -m pyright --pythonpath .venv/bin/python src tests` (plain `.venv/bin/pyright`
  fails to resolve the venv's third-party stubs on this box — pre-existing environment quirk
  affecting the whole repo equally, not introduced by this task; worked around via
  `--pythonpath`, not by editing `pyproject.toml`'s `[tool.pyright]` to avoid touching a
  shared config file mid-parallel-work).
- Full suite: 17/17 tests pass in this task's scope (4 new + 13 pre-existing from tasks
  001/002/014). One unrelated failure in `tests/tools/test_brancher_create.py`
  (`test_it_defaults_clear_services_to_cron_when_not_provided`) observed in the full-repo run —
  belongs to task 003, running in parallel, not touched or caused by this task.
