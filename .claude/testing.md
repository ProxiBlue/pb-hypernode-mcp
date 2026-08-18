# Testing Configuration — pb-hypernode-mcp (Python)

## Test Framework

pytest, matching the fleet's other MCP-server plugins (pb-chatroom, pb-graphiti):

- `pytest>=8.3.0` + `pytest-asyncio>=0.24.0` (the MCP SDK is async).
- Tests live under `tests/`, mirroring `src/pb_hypernode_mcp/` layout.
- Mock the HTTP layer (Hypernode REST API) and the SSH/scp/rsync subprocess calls — unit tests never hit a real Hypernode account or a real Brancher node.
- One integration/smoke checkpoint is explicitly allowed and expected: task 007 (`brancher_exec`) requires one manual/documented real-node smoke test to confirm the SSH-key-inheritance assumption. Document this in that task's Implementation Notes, not as an automated pytest case.

## TDD Workflow

RED → GREEN → REFACTOR, same discipline regardless of language:

1. **RED** — write the failing test first under `tests/`, matching the exact requirement text from the task file as the test name (e.g. `it_rejects_the_call_when_no_label_is_provided` → `test_rejects_the_call_when_no_label_is_provided`). Confirm FAIL.
2. **GREEN** — minimum code in `src/pb_hypernode_mcp/` to pass. Constructor/dependency injection via plain Python (no framework needed). Confirm PASS.
3. **REFACTOR** — extract shared fixtures/mocks, one change at a time, re-run after each.

Run scoped:
```bash
cd /home/lucas/pb-hypernode-mcp && uv run pytest tests/{path}::{TestClass}::{test_name} -v
```

Run full suite (task sign-off and plan-close):
```bash
cd /home/lucas/pb-hypernode-mcp && uv run pytest -v
```

## No Browser/UI Tests

This plugin has no browser-rendered UI of its own — it's an MCP tool-call surface + Claude Code skills. There is no Playwright layer. Skills (tasks 011-013) that don't reduce cleanly to a pytest-mockable assertion should document a manual verification procedure in their Implementation Notes instead of forcing a weak/fake automated test.

## Coverage

No hard percentage gate for v1 — prioritize correctness of the safety-critical paths (task 007's `-eph`-only guard, task 009/010's sanitization non-bypassability) over raw line coverage.

## Environment Assumptions

- Package/dependency management via `uv` (matches pb-chatroom/pb-graphiti convention).
- Python >=3.11.
- TDD worker runs directly in this container; every Bash command MUST `cd /home/lucas/pb-hypernode-mcp &&` first — the shell's cwd resets to `/var/www/html` between tool calls in this session, it does NOT persist.
