# Task 015: README.md (Package Standards)

**Status**: completed
**Depends on**: 011, 012, 013, 014
**Retry count**: 0

## Description
Write the project README documenting installation, configuration, all MCP tools, all three skills, the safety guardrails (especially the mandatory sanitization layer), and known limitations (Magento-only v1, no MCP-managed SSH keys).

## Context
- Depends on all functional tasks so it accurately reflects what was actually built, not what was planned.
- Should read similarly in structure/tone to the author's other public pb-* plugin READMEs (pb-graphiti, pb-chatroom) for consistency across the plugin family.

## Requirements (Test Descriptions)
- [x] `it documents installation via the marketplace seed-mount pattern`
- [x] `it documents the HYPERNODE_API_TOKEN configuration requirement`
- [x] `it documents every MCP tool with its purpose and key arguments`
- [x] `it documents all three skills and when to use each`
- [x] `it documents the mandatory sanitization/sandbox-forcing behavior and that it cannot be disabled`
- [x] `it documents the Magento/Mage-OS-only v1 scope limitation`

## Acceptance Criteria
- README renders correctly on GitHub
- Follows project README standards
- No decrease in test coverage (n/a for docs — verify by manual review)

## Implementation Notes

Docs-only task, no test code — verified by cross-referencing every claim
against the actual built source (per this project's testing config, README
correctness is manual review, not new tests).

Rewrote `README.md` in place, expanding task 014's starting draft (which
covered install + config + a one-line skills list only) now that all
functional tasks are built:

- **Install/config sections** — kept task 014's existing marketplace
  seed-mount install steps and `HYPERNODE_API_TOKEN`/`HYPERNODE_APP_ALLOWLIST`
  table (already accurate), folded into the new structure.
- **New "MCP tools" table** — documents all 7 registered tools
  (`brancher_create`, `brancher_spinup`, `brancher_list`, `brancher_delete`,
  `brancher_ssh_info`, `brancher_exec`, `brancher_put`) with purpose, key
  arguments, and the specific exceptions each raises, cross-referenced
  against `src/pb_hypernode_mcp/server.py`'s `create_server()` registration
  list and each tool module's docstring/signature.
- **Expanded "Skills" section** — one paragraph per skill
  (`brancher-spinup`, `brancher-preview`, `brancher-cleanup`) summarizing
  actual flow from each `skills/*/SKILL.md`, not just the one-liner
  description.
- **New "Safety guardrails" section** — documents the mandatory
  sanitization sequence in full (PII anonymization, admin credential reset,
  payment gateway sandbox-forcing, third-party API key stubbing) sourced
  from `sanitization/config.py::DEFAULT_MAGENTO_SANITIZATION_CONFIG` and
  `sanitization/commands.py`, and states plainly that
  `spinup_sanitized_brancher_node()` structurally cannot return an access
  URL without every sanitization command exiting 0 first — no flag/opt-out
  exists anywhere in the codebase (confirmed by reading
  `tools/brancher_spinup_flow.py` end to end). Also covers the app
  allowlist, Falcons-plan check, `-eph`-only exec/put guard,
  confirm-before-delete, and mandatory label guardrails already enforced in
  code.
- **New "Limitations (v1)" section** — Magento/Mage-OS-only scope (sourced
  from `sanitization/config.py`'s docstring and `_plan.md`'s Out of Scope
  list), no MCP-managed SSH keys (client's own local SSH agent/key only),
  stdio-only transport, REST-API-only (no `deploy.php`), wall-clock (not
  idle-aware) minute accounting, and the two documented-but-unverified API
  response shape assumptions already flagged in
  `tools/brancher_list.py`/`brancher_create.py` docstrings.
- Kept task 014's "Manual verification of the marketplace install path"
  section verbatim (still accurate, no functional task touched plugin
  install mechanics) and added a closing License section pointing at
  `LICENSE`/`NOTICE`.

Verification: markdown fence-balance and heading-structure checked via a
small Python script (6 fences = 3 balanced pairs, 9 well-formed `#`/`##`
headings, no malformed fences). Full test suite re-run
(`.venv/bin/pytest -q`) — 81 passed, unchanged from before this docs-only
edit (no source files touched).
