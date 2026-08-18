# Task 006: brancher_ssh_info Tool

**Status**: completed
**Depends on**: 002
**Retry count**: 0

## Description
Implement the `brancher_ssh_info` MCP tool that returns SSH connection details (host, user, port) for a given Brancher node, so tasks 007/008 have a clean source of connection parameters.

## Context
- Host is the node's `<app>-eph<id>.hypernode.io` hostname.
- Hypernode's default SSH user convention needs confirming against docs/API response (the app-level SSH user, e.g. the app name itself, per standard Hypernode SSH conventions) — verify against the API response fields rather than assuming.
- This tool does NOT open an SSH connection itself — it only returns the info tasks 007/008 use to do so via the client's local SSH agent.

## Requirements (Test Descriptions)
- [x] `it returns host, user, and port for a valid Brancher node name`
- [x] `it rejects a node name that does not match the -eph naming pattern`
- [x] `it returns a clear error when the node is not yet ready (no IP assigned)`

## Acceptance Criteria
- All requirements have passing tests
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

- New files: `src/pb_hypernode_mcp/tools/brancher_ssh_info.py` (tool logic + `register()`),
  `src/pb_hypernode_mcp/tools/_guards.py` (shared `-eph` node-name validation), `src/pb_hypernode_mcp/tools/__init__.py`.
- Tests: `tests/tools/test_brancher_ssh_info.py` (4 tests: the 3 required requirement tests plus one
  extra registration/integration test verifying `register()` wires the tool onto a `FastMCP` instance
  and it's callable end-to-end via `server.call_tool`).
- **API-response-shape assumption (flagged per task instructions):** modeled the node-detail GET
  response (`client.get(node_name, '')`) as a flat dict with an `ip_address` key. Readiness = truthy
  `ip_address` (falsy/missing/`None` => `NodeNotReadyError`). No live Hypernode Brancher node-detail
  API response was available to confirm the exact field name/shape — this is a best-guess based on
  the task's own wording ("no IP assigned"). If the real API uses a different key (e.g. `ip`,
  `primary_ip`, or a nested `network.ip_address`), `get_ssh_info()` needs a one-line field-name fix.
- **SSH user assumption:** used the *entire ephemeral node name* (e.g. `pps-eph123456`) as the SSH
  user, not just the base appname (`pps`). Rationale: per the task's own context and Hypernode docs
  cited in the task, once a Brancher node exists it "acts as its own regular Hypernode" reachable via
  `/v2/app/<appname>-eph123456/...` — i.e. the node *is* its own app for API purposes, so by the
  standard Hypernode convention (SSH user == appname) the SSH user is the full node name. Did NOT add
  a branch to prefer an explicit `ssh_user` field from the API response because no such field is
  confirmed to exist and none of the 3 required tests exercise it — adding untested branching would
  have been over-implementation per TDD rules. If task 007/008 (or real API testing) reveals an
  explicit SSH-user field, add it as a `detail.get('ssh_user') or node_name` fallback in
  `get_ssh_info()` (single line change) with a new test.
- **Host construction:** always `<node_name>.hypernode.io` (string interpolation, not sourced from
  the API response), since the task explicitly states this is a fixed hostname convention. Not
  dependent on the flagged assumptions above.
- **Port:** hardcoded `22` (module constant `SSH_PORT`) — task says "standard SSH port 22 unless the
  API says otherwise," and no port field was found/assumed in the mocked response shape.
- **Reusable `-eph` validator location:** placed in `src/pb_hypernode_mcp/tools/_guards.py` (leading
  underscore = internal-to-package, not part of the public tool surface, but importable by sibling
  tool modules). Exposes `is_eph_node_name(name: str) -> bool` (pure predicate) and
  `validate_eph_node_name(name: str) -> None` (raises `InvalidNodeNameError`, a `ValueError`
  subclass, with a clear message including the offending name and expected pattern). Task 007
  (`brancher_exec`) should `from pb_hypernode_mcp.tools._guards import validate_eph_node_name` (or
  `is_eph_node_name`) rather than reimplementing the regex.
- **Pattern:** `^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?-eph[0-9]+$` — requires a non-empty appname segment
  (no leading/trailing hyphen) followed by `-eph` and one or more digits. Matches `pps-eph123456`,
  rejects bare `pps` (no `-eph<id>` suffix), and rejects `-eph123` (no appname).
- **`register()` design:** `register(server: FastMCP, client_factory: Callable[[], HypernodeApiClient]) -> None`.
  `client_factory` is called lazily inside the tool closure (once per invocation), not at
  registration/server-construction time — this matters because `server.py`'s `create_server()` wires
  it as `lambda: HypernodeApiClient(load_settings())`, and `load_settings()` raises `ConfigError` if
  `HYPERNODE_API_TOKEN` is unset. Existing `tests/test_server.py` tests call `create_server()` without
  that env var set (they never invoke the ssh_info tool), so eager construction would have broken
  them; lazy construction keeps `create_server()` side-effect-free until a tool is actually called.
- **`server.py` wiring:** added a minimal, localized edit — 3 new imports (`HypernodeApiClient`,
  `load_settings`, `tools.brancher_ssh_info`) plus a 2-line body change in `create_server()`. Verified
  after the edit that tasks 003/004 (`brancher_create`, `brancher_list`) had already landed
  concurrently in `server.py`/`tools/` with no merge conflict — full suite (32 tests) passes together.
- Quality gates run and passing on all files touched by this task: `ruff check`, `ruff format --check`,
  `pyright` (all 0 errors). Two pre-existing lint/format issues in `tools/brancher_create.py` and
  `tests/tools/test_brancher_create.py` (from task 003, not this task) were left untouched —
  out of scope for this task, not introduced by it.
- **Environment note (not a code issue):** `uv` is not on PATH in this sandbox; used
  `.venv/bin/pytest`/`.venv/bin/ruff` directly. `pyright` additionally needed
  `--pythonpath .venv/bin/python` to resolve `httpx`/`mcp`/`anyio` imports — without it, pyright falls
  back to a system interpreter that doesn't have the project's deps installed. This is a sandbox/PATH
  quirk, not a project config defect; flagging for whoever runs the "before declaring done" gate
  command verbatim from `uv run pyright ...`.
