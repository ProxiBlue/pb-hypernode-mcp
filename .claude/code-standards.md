# Code Standards — pb-hypernode-mcp (Python)

Matches the fleet convention established by pb-chatroom and pb-graphiti (both `mcp` subpackages).

## Style Guide

- `ruff` for lint + format. Line length 100. Single-quote strings.
- `pyright` for static type checking, `basic` mode.
- Full type hints on all function signatures (params + return types).

## Linting

```bash
cd /home/lucas/pb-hypernode-mcp && uv run ruff check src tests
cd /home/lucas/pb-hypernode-mcp && uv run ruff format src tests
cd /home/lucas/pb-hypernode-mcp && uv run pyright src tests
```

## Pre-commit Checks

- `ruff check` clean
- `pyright` clean (basic mode)
- All pytest tests passing

## Project Layout

```
src/pb_hypernode_mcp/
├── server.py          # MCP server entrypoint, stdio transport
├── config.py          # env/config loading (HYPERNODE_API_TOKENS: per-app token map)
├── api_client.py       # Hypernode REST API wrapper, resolves token per-app (task 002/018)
├── tools/               # one module per MCP tool
│   ├── brancher_create.py
│   ├── brancher_list.py
│   ├── brancher_delete.py
│   ├── brancher_ssh_info.py
│   ├── brancher_exec.py
│   ├── brancher_put.py
│   └── brancher_apps.py
└── sanitization/        # task 009 — config-driven PII/gateway sanitization
    ├── config.py
    └── commands.py
tests/                    # mirrors src/ layout
skills/                    # brancher-spinup, brancher-preview, brancher-cleanup (markdown)
```

## Naming Conventions

- Modules/files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `SCREAMING_SNAKE_CASE`
- MCP tool names (as exposed to Claude): flat `verb_noun`, e.g. `brancher_create` — matches the pb-chatroom tool-naming precedent (`chat_send`, `chat_ack`).

## Python Requirements

- Python >=3.11.
- Type hints on all parameters and return types — no bare `Any` where a real type is knowable.
- `async`/`await` throughout the MCP tool layer (SDK is async); synchronous helpers (e.g. command-string generation in task 009) are fine to stay sync.
- Build backend: `hatchling`, packaged via `uv`/`pyproject.toml` (matches pb-chatroom/pb-graphiti).

## Project-Specific Rules

- No key material (SSH keys, tokens) ever written to disk by this plugin. `HYPERNODE_API_TOKENS` (per-app JSON token map) read from env only.
- `brancher_exec`/`brancher_put` shell out to system `ssh`/`scp`/`rsync` — never hand-roll SSH protocol handling, never accept/store a private key path as a first-class config option in v1 (client's local SSH agent only, per plan Architecture Notes).
- Any code path that can reach `brancher_exec` or `brancher_delete` against a non-`-eph` hostname is a bug, not an edge case — treat guard-rail tests for these as blocking, never optional/skippable.
