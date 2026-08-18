# Task 001: Python Project Scaffold + MCP Server Skeleton

**Status**: completed
**Depends on**: none
**Retry count**: 0

## Description
Set up the Python project structure (packaging, dependencies, config loading) and a minimal MCP server skeleton using stdio transport that can register and dispatch tools. This is the bootstrap all other tasks build on.

## Context
- New repo, currently only `LICENSE` + `README.md`.
- Language: Python (matches pb-graphiti/pb-chatroom sibling plugins).
- Use the official `mcp` Python SDK (`modelcontextprotocol/python-sdk`) for the server/stdio transport rather than hand-rolling the protocol.
- Config: `HYPERNODE_API_TOKEN` read from env var only, never written to disk. An app allowlist (list of permitted `<appname>` values) should also be config-loadable (env var or config file — pick one and document it), since task 003/005 depend on it existing.
- Package layout convention to establish: `pb_hypernode/` (or `hypernode_mcp/`) package dir, `server.py` entrypoint, `tools/` dir for individual tool modules (one file per tool, mirroring the pb-graphiti/pb-codegraph pattern of small focused modules).

## Requirements (Test Descriptions)
- [x] `it starts the MCP server over stdio transport without error`
- [x] `it raises a clear config error when HYPERNODE_API_TOKEN is not set`
- [x] `it loads the app allowlist from config`
- [x] `it registers a tool via the tool registry and the server reports it in its tool list`
- [x] `it rejects a tool call for an unregistered tool name with a clear error`

## Acceptance Criteria
- All requirements have passing tests
- `pip install -e .` (or equivalent) installs cleanly
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

- Toolchain: `uv` was not preinstalled on this machine — installed to `~/.local/bin` via the official astral.sh installer (`curl -LsSf https://astral.sh/uv/install.sh | sh`) so `uv sync` / `uv run` work per the testing config. Not a deviation from the plan, just an environment-setup step worth flagging.
- Package layout: `src/pb_hypernode_mcp/` with `server.py`, `config.py`, and empty `tools/`/`sanitization/` package dirs (populated by later tasks). `pyproject.toml` matches the pb-chatroom shape specified in code standards exactly (dependency list, dev extras, hatchling wheel target `src/pb_hypernode_mcp`), plus `[project.scripts] pb-hypernode-mcp = "pb_hypernode_mcp.server:main"` and ruff/pyright/pytest tool config (line-length 100, single-quote strings, pyright basic mode, `asyncio_mode = "auto"`).
- Server: `create_server()` builds a `mcp.server.fastmcp.FastMCP` instance (official SDK, no hand-rolled protocol). `run_async()`/`main()` wire it to `run_stdio_async()` for the stdio entrypoint. Tool registration/dispatch (`@server.tool(...)`, `server.list_tools()`, `server.call_tool()`) and the "unknown tool" error (`mcp.server.fastmcp.exceptions.ToolError: Unknown tool: <name>`) are FastMCP's built-in `ToolManager` behavior — requirements 4 and 5 passed against the plain `create_server()` skeleton with no extra code needed; noted per TDD discipline rather than adding redundant wrapping code.
- Config: `config.py` uses `pydantic_settings.BaseSettings` (per the pinned `pydantic-settings` dependency) with two env-var-backed fields — `hypernode_api_token` (`HYPERNODE_API_TOKEN`) and `hypernode_app_allowlist` (`HYPERNODE_APP_ALLOWLIST`, comma-separated `<appname>` list, exposed via the `Settings.app_allowlist` tuple property, e.g. `HYPERNODE_APP_ALLOWLIST=appone,apptwo`). Chose env var (not a config file) per the task's "pick one and document it" instruction — documented in the module docstring here and should be echoed in the eventual project README (task 015). `load_settings()` raises `ConfigError` with an actionable message when the token is missing; the token is never written to disk anywhere in this module.
- Test for stdio startup (`test_it_starts_the_mcp_server_over_stdio_transport_without_error`) drives the real `FastMCP.run_stdio_async()` codepath end-to-end: it monkeypatches only the innermost `mcp.server.fastmcp.server.stdio_server` OS-pipe adapter (owned by the SDK, not us) with in-memory anyio streams, then runs a real `mcp.client.session.ClientSession` against it and performs the actual `initialize()` handshake — this is the SDK's own recommended in-process testing pattern (mirrors `mcp.shared.memory.create_connected_server_and_client_session`), adapted to go through `run_stdio_async()` specifically rather than the lower-level `server.run()`.
- Verification: `uv sync --extra dev` installs cleanly; `uv run pytest -v` — 5/5 pass; `uv run ruff check`/`ruff format --check` — clean; `uv run pyright src tests` — 0 errors/warnings. One pre-existing `IncompleteFieldDefinitionWarning` surfaces from the `mcp` SDK's own `FastMCP.Settings.lifespan` field (pydantic-settings resolving a forward ref under `from __future__ import annotations`) — upstream library warning, not actionable in this codebase.
- No deviations from the task's acceptance criteria.
