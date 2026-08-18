# Plan: pb-hypernode-mcp — Hypernode Brancher MCP + Skills

## Created
2026-08-18

## Status
completed

## Objective
Build a client-side Claude Code plugin (Python MCP server + skills) that lets a client's own Claude Code spin up disposable Hypernode Brancher preview environments from production, safely drive AI-assisted changes on them over SSH, and view the result — with mandatory automatic sanitization so no live customer data or real payment/API credentials are ever exposed on a public `-eph` URL.

## Related Issues
Relates to uptactics/m2_pvcpipesupplies#409 (origin design ticket, full spec + research). Blocks uptactics/m2_pvcpipesupplies#446 (child: offload Playwright functional tests to Brancher — explicitly out of scope for this plan).

## Discovery Notes
Greenfield repo (github.com/ProxiBlue/pb-hypernode-mcp, public, Apache-2.0), sibling to author's other public Claude Code plugins (pb-graphiti, pb-chatroom, pb-codegraph, pb-hcf). Design was already fully specced in a prior session (ticket #409): MCP wraps the Hypernode REST API directly (`https://api.hypernode.com/v2/app/<app>/brancher/`, no PHP client dep), tool names (`brancher_create/list/delete/ssh_info/exec/put`) and guardrails (confirm-before-delete, mandatory `--label`, minutes-remaining display, app allowlist, `-eph`-only exec guard, Falcons-plan check) were already agreed. This session's research (see #409 comments) confirmed: SSH keys inherit automatically via Brancher's full-filesystem backup clone (no separate provisioning), the full Magento toolchain (`bin/magento`, `n98-magerun2`) is confirmed working on Brancher nodes per Hypernode's own install-hook docs example, and Brancher minutes bill wall-clock uptime regardless of idle (auto-cleanup is mandatory, not optional). No existing Hypernode/Brancher MCP is reusable — checked npm, PyPI, GitHub, Smithery, Glama; the one hit (`poespas/hypernode-mcp-server`) is unmaintained, runs server-side on the node (wrong shape — this plugin is client-side), and has no Brancher lifecycle tools at all.

New this session: a mandatory safety layer with no prior design coverage. Brancher nodes clone production's latest backup wholesale — live customer PII, saved payment tokens, and real (non-sandbox) payment/API credentials come along by default. Since the node gets a public URL and the client's own AI drives changes on it, spinup must automatically neutralize this before the node is usable. Scope decisions (used defaults after two unanswered clarification rounds, each picking the lower-risk/more-thorough option): v1 targets Magento/Mage-OS only (not a generic multi-platform tool); SSH auth uses the client's own local SSH agent/key (matches the "token never leaves client" design intent — no key material touches the MCP process); sanitization covers PII + payment gateways + all live third-party API keys (ShipperHQ, AvaTax, etc.), not just payment.

Language: Python, matching the two closest sibling plugins in shape (pb-graphiti, pb-chatroom — both MCP server + skills), and matching Hypernode's own official Python API client library precedent.

## Scope

### In Scope
- Python MCP server (stdio transport) wrapping the Hypernode REST API directly.
- Lifecycle tools: `brancher_create`, `brancher_list`, `brancher_delete`, `brancher_ssh_info`.
- Change-it tools: `brancher_exec` (SSH command execution, hard-guarded to `-eph` hostnames only), `brancher_put` (scp/rsync local → remote sync).
- Mandatory sanitization + gateway-sandbox-forcing layer for Magento/Mage-OS apps, wired automatically into every `brancher_create` via the install-hook mechanism — not an optional flag.
- Skills: `brancher-spinup` (create + sanitize + return access details), `brancher-preview` (full loop: create → apply changes → build → screenshot via existing browser MCP → delete reminder), `brancher-cleanup` (list/delete stale nodes, minutes-used reporting).
- Guardrails: confirm-before-delete, mandatory `--label`, minutes-remaining display pre-create, app allowlist, Falcons-plan eligibility check.
- Plugin packaging + marketplace registration following the pb-graphiti seed-mount convention.
- Package README per project README standards.

### Out of Scope
- Non-Magento platform support (WooCommerce, Shopware, Laravel) — v1 is Magento/Mage-OS only.
- Offloading Playwright functional test runs to Brancher nodes — tracked separately in child ticket #446, blocked on this plan.
- Hypernode Deploy (`deploy.php`) integration — REST API only for v1.
- A managed/hosted version of this MCP — this is a client-run, client-owned-token plugin only.
- MCP-managed SSH key storage — v1 relies entirely on the client's existing local SSH agent/key.

## Success Criteria
- [ ] A Brancher node can be created, listed, and deleted end-to-end via the MCP tools against a real Hypernode account.
- [ ] `brancher_exec` refuses to run against any hostname not matching `*-eph*`.
- [ ] Every `brancher_create` automatically sanitizes PII and forces payment/API gateways to sandbox before returning the node as ready — this cannot be skipped via a flag.
- [ ] `brancher-cleanup` correctly identifies and can delete nodes past an age threshold, using wall-clock minutes (not idle-detection).
- [ ] All tests passing (pytest).
- [ ] Code follows project standards; README documents install, config (`HYPERNODE_API_TOKEN`), and all tools/skills.

## Task Overview
| Task | Description | Depends On | Status |
|------|-------------|------------|--------|
| 001 | Python project scaffold + MCP server skeleton | - | completed |
| 002 | Hypernode REST API client wrapper | 001 | completed |
| 003 | brancher_create tool + pre-create guardrails | 002 | completed |
| 004 | brancher_list tool | 002 | completed |
| 005 | brancher_delete tool + confirm-before-delete | 002, 004 | completed |
| 006 | brancher_ssh_info tool | 002 | completed |
| 007 | brancher_exec tool + eph-only guard | 006 | completed |
| 008 | brancher_put tool | 006 | completed |
| 009 | Magento sanitization + gateway-sandbox module | 007 | completed |
| 010 | Install-hook orchestration (auto-wires 009 into create) | 003, 009 | completed |
| 011 | brancher-spinup skill | 010 | completed |
| 012 | brancher-preview skill | 011, 008 | completed |
| 013 | brancher-cleanup skill | 004, 005, 016 | completed |
| 014 | Plugin packaging + marketplace registration | 001 | completed |
| 015 | README.md (package standards) | 011, 012, 013, 014 | completed |
| 016 | Wire all MCP tools onto the FastMCP server | 003, 004, 005, 006, 007, 008 | completed |
| 017 | Security remediation (sanitization bypass + rsync injection) | 016 | completed |

## Architecture Notes
- MCP transport: stdio only for v1 (standard local Claude Code plugin pattern).
- `HYPERNODE_API_TOKEN` read from env only, never written to disk by the plugin, matching the pb-graphiti/pb-chatroom secret-handling precedent in this fleet.
- `brancher_exec`/`brancher_put` shell out to the system `ssh`/`scp`/`rsync` binaries using the client's already-configured local SSH agent/key — the MCP process never holds key material.
- The `-eph` hostname guard in task 007 is the single safety-critical chokepoint for the "change-it" layer — must be enforced at the tool-call boundary, not just documented.
- Sanitization (task 009) should be config-driven (a PII table/column list + gateway/API-key stub commands) even though v1 targets Magento only, since the *specific* PII fields and installed integrations (ShipperHQ, AvaTax, Braintree/Stripe) will differ per client app the plugin gets pointed at. Hardcode Magento-shaped defaults, but don't hardcode one client's exact schema.
- `.claude/CLAUDE.md`, `.claude/testing.md` for this repo itself were flagged missing by pre-flight-check (expected — greenfield repo). Not treated as plan tasks; scaffold via a separate `/init`-style pass if/when this repo gets full pb-hcf wiring.

## Amendments (mid-execution)
- **2026-08-18**: Added task 016. Tasks 003/004/006 (built in parallel to avoid `server.py` merge conflicts) each implement their tool as a plain business-logic function without registering it on the FastMCP server instance — confirmed independently by task 004's own Implementation Notes. No original task covered actually wiring `tools/*.py` onto `server.py` so they're callable as MCP tools at all. Task 016 closes this gap once all six tool tasks (003-008) are done. Tasks 011 (spinup) and 013 (cleanup) now also depend on 016, since their skills are only real once the tools they call are actually registered.
- **2026-08-18**: Post-implementation security review (3-specialist quorum, run after task 015) returned 2-of-3 FAIL. Both FAIL votes independently confirmed a critical gap: task 011 built the sanitized create+wait+sanitize flow as a NEW parallel tool (`brancher_spinup`) rather than gating the EXISTING `brancher_create` tool, leaving the raw unsanitized `brancher_create` (and `brancher_ssh_info`) independently callable — a structural bypass of the plan's own non-negotiable Success Criteria. Also found a real rsync argument-injection in `brancher_put` (unescaped `remote_path`/`local_path`, no `--protect-args`). Added task 017 to fix both before this plan is considered complete.

## Risks & Mitigations
- **Sanitization gap leaks real customer PII on a public URL**: task 009's requirements must enumerate concrete PII classes (customer_entity, sales_order*, quote payment info, admin credentials) as explicit test cases, not a vague "sanitize the DB" requirement. Task 010 must make this non-bypassable (runs before the node is reported ready, no opt-out flag).
- **`brancher_exec` used against a non-Brancher (production) host by mistake**: hostname guard in task 007 is the mitigation — reject anything not matching `*-eph*` before opening any SSH connection, tested explicitly against production-shaped hostnames.
- **Brancher minutes accumulate silently (billed wall-clock, not idle-aware)**: task 013's cleanup skill must default to age-based (wall-clock) thresholds, not activity-based ones — confirmed via research this session.
- **SSH key inheritance assumption (from backup clone) is inferred, not lab-verified**: task 007's requirements should include an early real-node smoke test (create → exec trivial command) to confirm this before building further on top of the assumption.
