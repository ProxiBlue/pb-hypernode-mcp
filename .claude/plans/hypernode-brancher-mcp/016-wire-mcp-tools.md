# Task 016: Wire All MCP Tools Onto the FastMCP Server

**Status**: completed
**Depends on**: 003, 004, 005, 006, 007, 008
**Retry count**: 0

## Description
Register all six Brancher MCP tools (`brancher_create`, `brancher_list`, `brancher_delete`, `brancher_ssh_info`, `brancher_exec`, `brancher_put`) onto the FastMCP server instance in `src/pb_hypernode_mcp/server.py`, so they are actually callable as MCP tools rather than existing only as unregistered business-logic functions.

## Context
- Tasks 003/004/005/006/007/008 were built in parallel and each deliberately avoided touching `server.py` to prevent merge conflicts — confirmed by task 004's Implementation Notes ("Neither sibling in-progress tool registers itself on the server either... actual tool registration is evidently deferred to a later task"). This IS that later task.
- Each tool module exposes a plain async business-logic function (constructor-injected with `HypernodeApiClient`/`Settings` rather than reading global state) — inspect each of the six `src/pb_hypernode_mcp/tools/*.py` files to see the exact function signatures actually implemented (they may differ slightly from what was originally sketched in each task's Context section — trust the code, not the task descriptions, since implementers may have deviated for good reasons documented in their own Implementation Notes).
- Use FastMCP's `@server.tool(...)` decorator (or `server.add_tool(...)`, whichever `src/pb_hypernode_mcp/server.py`'s `create_server()` pattern established in task 001 supports) to expose each function under its MCP tool name (`brancher_create`, `brancher_list`, etc. — exact snake_case names per the plan's tool list).
- Each registered tool needs access to a `HypernodeApiClient` instance built from `Settings` — wire this via whatever DI/closure pattern fits FastMCP's tool-registration style (e.g. a factory that builds the client once at server startup and closes over it in each tool wrapper).
- If any tool module turns out to already register itself (double-check — don't assume based on the plan's notes alone), avoid double-registration.

## Requirements (Test Descriptions)
- [x] `it exposes brancher_create as a callable MCP tool on the server`
- [x] `it exposes brancher_list as a callable MCP tool on the server`
- [x] `it exposes brancher_delete as a callable MCP tool on the server`
- [x] `it exposes brancher_ssh_info as a callable MCP tool on the server`
- [x] `it exposes brancher_exec as a callable MCP tool on the server`
- [x] `it exposes brancher_put as a callable MCP tool on the server`
- [x] `it constructs a single shared HypernodeApiClient reused across tool calls rather than one per call`

## Acceptance Criteria
- All requirements have passing tests
- `uv run pytest -v` passes for the full suite (no regressions in any of the six tools' own test files)
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

**Signatures found (verified against code, not the plan sketch):**
- `brancher_list.list_brancher_nodes(appname, *, client, settings) -> list[dict]` — no pre-existing `register()`.
- `brancher_delete.delete_brancher_node(client, settings, node_name, *, confirm=False) -> dict` — no pre-existing `register()`.
- `brancher_exec` already had `register(server) -> None` implemented (no client needed — shells out to `ssh` directly); reused as-is, just wired into `server.py`.
- `brancher_put.put_files(node_name, local_path, remote_path, *, port=SSH_PORT, run_subprocess=None) -> dict` — no pre-existing `register()`, no client needed (rsync/ssh only).

**Two pre-existing registration patterns (`brancher_create` vs `brancher_ssh_info`) — left both as-is, did not standardize:**
- `brancher_create.register(server, client_factory=None)` — optional factory, `ClientFactory = Callable[[], tuple[HypernodeApiClient, tuple[str,...]]]`, defaults internally to `load_settings()`.
- `brancher_ssh_info.register(server, client_factory)` — required factory, `Callable[[], HypernodeApiClient]`.
Both already had their own passing test suites pinned to these exact signatures (`tests/tools/test_brancher_create.py`, `tests/tools/test_brancher_ssh_info.py`); refactoring either risked breaking tests outside this task's scope for no functional gain. New `register()` functions on `brancher_list`/`brancher_delete` follow the `brancher_ssh_info` style (required factory, no default) since they need a `(client, settings)` pair with no sensible parameterless default. `brancher_put`/`brancher_exec` follow a third minimal `register(server)` — no factory at all — since neither needs `HypernodeApiClient`.

**Shared client wiring (`server.py`):** `create_server()` now builds `get_settings()`/`get_client()` closures using `nonlocal`-cached values, memoizing `Settings`/`HypernodeApiClient` on first access and reusing them across all tool calls. Construction stays lazy (not performed at `create_server()` call time) so building the server never requires `HYPERNODE_API_TOKEN` to be set — this preserves the two existing `test_server.py` tests that call `create_server()` with no env token configured. Verified via `test_it_constructs_a_single_shared_hypernode_api_client_reused_across_tool_calls`, which patches `HypernodeApiClient` with an instance-counting fake and asserts exactly one instantiation across three different tool calls (`brancher_ssh_info`, `brancher_list`, `brancher_create`).

**Files changed:**
- `src/pb_hypernode_mcp/server.py` — wires all six tools via `get_settings()`/`get_client()` closures.
- `src/pb_hypernode_mcp/tools/brancher_list.py` — added `register(server, client_factory)`.
- `src/pb_hypernode_mcp/tools/brancher_delete.py` — added `register(server, client_factory)`.
- `src/pb_hypernode_mcp/tools/brancher_put.py` — added `register(server)`.
- `tests/test_server.py` — added `FakeApiClient`/`FakeSubprocess` test doubles and 7 new tests, one per requirement.

**Verification:** `uv run pytest -v` — 60 passed (49 pre-existing + 10 in `test_server.py`, one net-new since 3 pre-existing tests already lived there), 1 failure in `tests/sanitization/test_commands.py` — unrelated to this task, belongs to the parallel task 009 (sanitization module) and touches files this task never touched. `ruff check`, `ruff format --check`, `pyright` all clean on every file this task touched.
