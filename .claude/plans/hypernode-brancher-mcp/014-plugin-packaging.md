# Task 014: Plugin Packaging + Marketplace Registration

**Status**: completed
**Depends on**: 001
**Retry count**: 0

## Description
Package the project as an installable Claude Code plugin (skills + MCP server manifest) following the pb-graphiti seed-mount distribution convention, so it can be registered as a marketplace entry and installed the same way the author's other pb-* plugins are.

## Context
- Follow pb-graphiti's established pattern: marketplace registration via `known_marketplaces.json`, seed-mount at `.claude/plugins-seed/marketplaces/`, `claude plugin install/update pb-hypernode-mcp@pb-hypernode-mcp` re-reading the local seed.
- LICENSE (Apache-2.0) already present from repo creation; add a NOTICE file per the original ticket's stated licensing intent.
- Plugin manifest needs to declare: the MCP server entrypoint, the three skills (spinup/preview/cleanup), and required config (`HYPERNODE_API_TOKEN` env var, app allowlist).

## Requirements (Test Descriptions)
- [x] `it declares the MCP server entrypoint correctly in the plugin manifest`
- [x] `it declares all three skills in the plugin manifest`
- [x] `it documents required environment variables in the manifest or install docs`
- [x] `it installs cleanly via the marketplace seed-mount pattern in a test environment` (documented manual verification — no `claude` CLI available in this sandbox)

## Acceptance Criteria
- All requirements have passing tests or documented manual verification steps
- NOTICE file present alongside existing LICENSE
- Code follows code standards

## Implementation Notes

**Manifest shape**: fetched pb-graphiti's and pb-chatroom's actual
`.claude-plugin/{plugin.json,marketplace.json}` and root `.mcp.json` via
`gh api repos/ProxiBlue/<repo>/contents/...` (per completeness-critical-fetch
rule — full raw content, no WebFetch summarization) plus the official
Claude Code plugins-reference doc (`curl` raw HTML, hand-stripped tags) to
confirm the real schema:

- `.claude-plugin/plugin.json` — metadata only (`name`, `version`,
  `description`, `author`, `license`, `keywords`, `userConfig`). No
  `skills` or `mcpServers` field exists on this manifest — those are
  declared by file/directory *presence*, not a JSON list.
- `.mcp.json` at repo root (or inline in `plugin.json`) — `mcpServers` map,
  standard MCP server config (`command`/`args`/`env`).
- `skills/<name>/SKILL.md` — one directory per skill, YAML frontmatter
  (`name`, `description`). Claude Code auto-discovers these; there is no
  separate skills-list manifest field. Test 2 below therefore validates the
  actual declaration mechanism (directory + frontmatter `name` match)
  rather than a fabricated JSON array field.
- `.claude-plugin/marketplace.json` — self-registers this repo as its own
  installable marketplace (matches pb-graphiti/pb-chatroom/pb-codegraph
  pattern: one-plugin marketplace, `source: "./"`).

**Files created**:
- `.claude-plugin/plugin.json` — plugin metadata + `userConfig` documenting
  `hypernode_api_token_env` (default `HYPERNODE_API_TOKEN`) and
  `hypernode_app_allowlist_env` (default `HYPERNODE_APP_ALLOWLIST`). No
  secret values ever live in this file — only the *names* of the env vars
  the consumer must set in their own shell (matches pb-graphiti's
  `imap_password_env` precedent).
- `.mcp.json` — `pb-hypernode-mcp` stdio server entry:
  `command: "uv"`, `args: ["--directory", "${CLAUDE_PLUGIN_ROOT}", "run", "pb-hypernode-mcp"]`,
  matching task 001's `pyproject.toml` `[project.scripts]` entry
  (`pb-hypernode-mcp = "pb_hypernode_mcp.server:main"`). No fleet precedent
  existed for a `uv`-run Python console-script MCP server (pb-graphiti is
  `http`, pb-chatroom removed its MCP layer, pb-codegraph is
  Node/npm-based) — this shape follows the official plugins-reference doc's
  bundled-server pattern (`${CLAUDE_PLUGIN_ROOT}`-relative command) adapted
  for `uv run <console-script>` instead of a prebuilt binary path.
- `skills/{brancher-spinup,brancher-preview,brancher-cleanup}/SKILL.md` —
  minimal stubs (frontmatter `name`/`description` + a one-line STUB body
  pointing at tasks 011-013) so the directory structure/skill names are
  final now; later tasks fill in real body content without restructuring.
- `NOTICE` — new file alongside the existing LICENSE (Apache-2.0, not
  touched). Documents third-party runtime dependencies NOT bundled in this
  repo: Hypernode Brancher API (consumer's own account/token), system
  `ssh`/`scp`/`rsync` binaries, and the `mcp`/`httpx`/`pydantic*` PyPI
  packages — mirrors the pb-graphiti NOTICE shape (own-copyright header +
  "orchestrates but does not redistribute" third-party list).
- `README.md` — rewritten: install via
  `claude plugin marketplace add` + `claude plugin install`, required env
  vars table (`HYPERNODE_API_TOKEN` required, `HYPERNODE_APP_ALLOWLIST`
  optional), skills summary, and a numbered manual verification procedure
  for the marketplace/seed-mount install path.
- `tests/test_plugin_manifest.py` — 3 automated tests (all TDD RED→GREEN,
  confirmed failing before each corresponding file existed).

**Requirement 4 (marketplace seed-mount install)**: no automated test
written, per the task's explicit instruction not to fabricate one. No
`claude` CLI is available inside this sandbox to actually run
`claude plugin marketplace add` / `claude plugin install`. Documented a
5-step manual verification procedure in `README.md` under "Manual
verification of the marketplace install path" instead (marketplace add →
install → `claude plugin list` check → session-level MCP/skill visibility
check → edit-then-`update` re-read check).

**Verification**: `uv run pytest -v` — 16/16 passed (includes task 002's
already-landed `tests/test_api_client.py`, confirming no interference with
parallel work). `uv run ruff check src tests` clean, `uv run ruff format
--check src tests` clean (11 files), `uv run pyright src tests` — 0
errors/warnings. Did not touch `src/pb_hypernode_mcp/api_client.py`,
`tools/*`, or `sanitization/*` per task scope boundary.
