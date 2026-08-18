# pb-hypernode-mcp

Client-side Claude Code plugin for Hypernode Brancher — spin up disposable
prod-clone preview environments, drive AI-assisted changes over SSH, view via
browser MCP.

Bundles a Python MCP server (6 tools) plus 3 skills orchestrating the
spin-up -> preview -> cleanup lifecycle. Every node this plugin creates via
`brancher_create` is automatically PII-anonymized and payment/API-sandboxed
before it is ever reported ready — see [Safety guardrails](#safety-guardrails).
`brancher_create` is the sole node-creation tool: it wraps the full
create -> wait-until-reachable -> sanitize -> report-ready sequence as one
non-bypassable call, so there is no separate "raw create" tool that could
return an unsanitized node.

## Installation

This plugin follows the pb-graphiti/pb-chatroom seed-mount distribution
convention: register the repo as a local marketplace, then install the
plugin from it.

```bash
claude plugin marketplace add pb-hypernode-mcp /path/to/pb-hypernode-mcp
claude plugin install pb-hypernode-mcp@pb-hypernode-mcp
```

To pick up local changes to this repo after editing (skills, MCP manifest,
server code):

```bash
claude plugin update pb-hypernode-mcp@pb-hypernode-mcp
```

The bundled MCP server (`pb-hypernode-mcp`, see `.mcp.json`) starts
automatically once the plugin is enabled, run via `uv run pb-hypernode-mcp`
against this repo's `pyproject.toml` entrypoint
(`pb_hypernode_mcp.server:main`).

## Required configuration

Set these in your shell **before** starting Claude Code — never in plugin
config, never committed:

| Env var | Required | Description |
|---|---|---|
| `HYPERNODE_API_TOKEN` | Yes | Your Hypernode API token. Read from the environment only; never written to disk by this plugin. The server refuses to start without it (`load_settings()` raises `ConfigError`). |
| `HYPERNODE_APP_ALLOWLIST` | No | Comma-separated list of Hypernode `<appname>` values this plugin may operate against, e.g. `myapp,myapp2`. `brancher_create`, `brancher_list`, and `brancher_delete` refuse any app not on this list when set. Leave unset only if you understand every app reachable by this token is fair game. |

```bash
export HYPERNODE_API_TOKEN="your-token-here"
export HYPERNODE_APP_ALLOWLIST="myapp,myapp2"
```

The token/allowlist are read once per server process and cached — restart
the MCP server (restart Claude Code, or `claude plugin update ...`) after
changing either.

## MCP tools

All 6 tools are registered on the `pb-hypernode-mcp` server
(`src/pb_hypernode_mcp/server.py`). `brancher_exec` and `brancher_put` shell
out to the system `ssh`/`rsync` binaries using your already-configured local
SSH agent/key — this plugin never holds or stores key material itself.

| Tool | Purpose | Key arguments |
|---|---|---|
| `brancher_create` | The sole node-creation tool: enforces a mandatory label, the app allowlist, and Falcons-plan eligibility, then wraps create -> wait-until-SSH-reachable -> run mandatory sanitization -> report ready as one non-bypassable call. There is no separate "raw create" tool — it is structurally impossible to create a Brancher node through this plugin without sanitization running first. Never returns an `access_url` for a node that has not finished sanitizing. Raises `NodeUnreachableTimeoutError` if the node never becomes SSH-reachable within 300s, or `SanitizationFailedError` (access URL withheld) if a sanitization command fails partway through. | `appname` (str), `labels` (list[str], required, at least one), `clear_services` (list[str], optional, defaults to `["cron"]`) |
| `brancher_list` | List active Brancher nodes for `appname`. Returns each node's `name`, `host`, and `minutes` (wall-clock uptime since creation, not idle-aware). Rejects any `appname` not on the allowlist. | `appname` (str) |
| `brancher_delete` | Delete a Brancher node. Gated behind a `confirm=True` re-call: the first call (default `confirm=False`) looks up and returns the target node's details plus a confirmation prompt without deleting anything; only a second call with `confirm=True` issues the actual DELETE. Validates the node name against the `-eph<id>` pattern first. | `node_name` (str, `<appname>-eph<id>`), `confirm` (bool, default `False`) |
| `brancher_ssh_info` | Return SSH connection details (`host`, `user`, `port`) for a node, without opening a connection itself. Raises `NodeNotReadyError` if the node has no IP assigned yet. | `node_name` (str) |
| `brancher_exec` | Run a shell command on a Brancher node over SSH (shells out to the system `ssh` binary). The single safety-critical chokepoint of the "change-it" layer: refuses any `node_name` that doesn't match the `-eph<id>` pattern, before spawning any subprocess — structurally impossible to point this tool at a production host. Returns `stdout`/`stderr`/`exit_code`; raises `SshConnectionError` on ssh's own exit code 255, `SshCommandTimeoutError` on timeout. | `node_name` (str), `command` (str), `timeout` (float, default 30s) |
| `brancher_put` | Sync a local file/directory to a Brancher node via `rsync -az` over SSH. Same `-eph`-only guard and local-SSH-agent connection model as `brancher_exec`. Raises `SyncError` on non-zero rsync exit. | `node_name` (str), `local_path` (str), `remote_path` (str), `port` (int, default 22) |

## Skills

- **`brancher-spinup`** — spin up a disposable Brancher preview node cloned
  from production, with mandatory automatic sanitization, and report its
  access URL. Use when a client asks to preview a change on a real
  prod-clone environment before it ships. Wraps the single `brancher_create`
  tool call — never reproduces the create/wait/sanitize sequence by hand.
- **`brancher-preview`** — the full loop: spin up a node (via the
  `brancher-spinup` skill), apply a code change (push a local diff with
  `brancher_put`, or edit in place with `brancher_exec`), run only the
  Magento build commands the change actually needs
  (`decide_build_commands()` in `src/pb_hypernode_mcp/preview_logic.py`),
  view the result through whatever browser MCP tool is already in the
  session, then explicitly remind the user the node is still billing
  Brancher minutes. Use when a client wants an end-to-end look at a change
  on a disposable environment. Never deletes the node itself.
- **`brancher-cleanup`** — list active nodes with `brancher_list`, flag any
  at or past an age threshold (`minutes >= threshold_minutes`, default 240
  minutes / 4 hours, via `flag_stale_nodes()` in
  `src/pb_hypernode_mcp/cleanup_logic.py`), and delete flagged nodes
  (single or bulk) only after explicit user confirmation. Use when a client
  wants to check for or remove leftover Brancher nodes to stop minute
  accrual. Brancher bills wall-clock minutes from creation regardless of
  whether anyone is actively using the node.

## Safety guardrails

- **Mandatory sanitization — cannot be disabled.** Every `brancher_create`
  call runs the full sanitization sequence
  (`src/pb_hypernode_mcp/sanitization/`) against the node before it is ever
  reported `"ready"` or returns an `access_url`. There is no flag, config
  option, or bypass path — `brancher_create` is the ONLY node-creation MCP
  tool this plugin registers (there is no separate, unsanitized create
  tool), and `spinup_sanitized_brancher_node()` in
  `src/pb_hypernode_mcp/tools/brancher_spinup_flow.py` (the function behind
  it) structurally cannot return an access URL without every sanitization
  command having exited 0 first. If a sanitization command fails partway
  through, the tool raises `SanitizationFailedError` and deliberately
  withholds the access URL — the exception does not even carry it, so a
  catching caller has no way to accidentally surface it.
  The sequence (config-driven, Magento-shaped default in
  `sanitization/config.py::DEFAULT_MAGENTO_SANITIZATION_CONFIG`):
  1. **PII anonymization** — `UPDATE` statements (via `n98-magerun2
     db:query`) against `customer_entity`, `customer_address_entity`,
     `sales_order`, `sales_order_address` (names/emails/phones/street
     replaced with anonymized placeholders), and stored card data
     (`quote_payment`, `sales_order_payment`: `cc_number_enc`,
     `cc_cid_enc`, `cc_owner`, `additional_data` nulled).
  2. **Admin credential reset** — `admin_user` username/email reset to
     placeholder values and password overwritten with a hash that is
     deliberately invalid for any real password (locks form-based login
     until an operator sets a real one via `bin/magento admin:user:create`).
  3. **Payment gateway sandbox-forcing** — `bin/magento config:set` forces
     e.g. `payment/braintree/environment=sandbox`,
     `paypal/general/sandbox_flag=1`.
  4. **Third-party API key stubbing** — `bin/magento config:set` replaces
     live keys (e.g. ShipperHQ, AvaTax) with dummy sandbox values so no
     preview node can make a real charge or a real third-party API call
     under production credentials.
  A real client app's exact table shape and installed integrations should
  override/extend `SanitizationConfig`, not rely on the shipped default in
  production — it exists as a safe-by-default starting point, not a promise
  it matches every schema.
- **App allowlist** (`HYPERNODE_APP_ALLOWLIST`) — when set, `brancher_create`,
  `brancher_list`, and `brancher_delete` refuse any `appname` not on the
  list.
- **Falcons-plan eligibility check** — `brancher_create` rejects apps not on
  a Brancher-eligible plan before creating anything.
- **`-eph`-only guard** — `brancher_exec` and `brancher_put` validate
  `node_name` against the `<appname>-eph<id>` pattern
  (`tools/_guards.py::validate_eph_node_name`) before opening any SSH
  connection or subprocess. It is structurally impossible to point either
  tool at a production hostname.
- **Confirm-before-delete** — `brancher_delete` never deletes on the first
  call. It requires an explicit `confirm=True` re-call after showing the
  target node's details; a threshold being configured or a node being
  flagged as stale is never itself confirmation.
- **Mandatory label** — `brancher_create` rejects calls with no `labels`, so
  every node is traceable to a reason/ticket.
- **Token handling** — `HYPERNODE_API_TOKEN` is read from the environment
  only and is never written to disk or plugin config by this plugin.

## Limitations (v1)

- **Magento/Mage-OS only.** The sanitization layer's default config
  (`DEFAULT_MAGENTO_SANITIZATION_CONFIG`) and the `brancher-preview` skill's
  build-command decision logic (`decide_build_commands()`) are both
  Magento-shaped. This is not a generic multi-platform tool — WooCommerce,
  Shopware, Laravel, and other Hypernode-hosted platforms are out of scope
  for v1. A non-Magento app would need a hand-written `SanitizationConfig`
  at minimum, and the preview skill's build sequence would not apply.
- **No MCP-managed SSH keys.** `brancher_exec`/`brancher_put` shell out to
  the system `ssh`/`rsync` binaries and rely entirely on your own local SSH
  agent/key already having access to Brancher nodes (which inherit access
  automatically via Brancher's full-filesystem clone from production). This
  plugin never provisions, stores, or transmits key material.
- **stdio transport only.** No remote/HTTP MCP transport in v1 — this is a
  local Claude Code plugin, run per-developer against their own
  `HYPERNODE_API_TOKEN`.
  There is no hosted/managed version of this MCP.
  Token and SSH access are both entirely client-owned.
- **REST API only.** No Hypernode Deploy (`deploy.php`) integration in v1.
- **Wall-clock, not idle-aware, minute accounting.** `brancher-cleanup`'s
  staleness check uses `minutes` as reported by the Hypernode API
  (uptime since creation) — it cannot tell an idle node from an actively
  used one.
- **Unverified API response shapes.** `brancher_list`'s expected response
  shape (`{"nodes": [{"name", "host", "minutes"}, ...]}`) and
  `create_brancher_node`'s plan/minutes field names (`plan_type`,
  `brancher_minutes_remaining`, used internally by `brancher_create`) are
  documented assumptions, not yet confirmed against the live Hypernode API
  contract — see the module docstrings in
  `src/pb_hypernode_mcp/tools/brancher_list.py` and
  `src/pb_hypernode_mcp/tools/brancher_create.py` if API responses don't
  match at runtime.

## Manual verification of the marketplace install path

Automated installation of a Claude Code plugin through the real `claude`
CLI could not be exercised inside this sandbox (no interactive Claude Code
session available to the TDD worker). Verify manually after cloning:

1. `claude plugin marketplace add pb-hypernode-mcp /path/to/pb-hypernode-mcp`
2. `claude plugin install pb-hypernode-mcp@pb-hypernode-mcp`
3. `claude plugin list` — confirm `pb-hypernode-mcp` appears, enabled.
4. Start a Claude Code session; confirm the `pb-hypernode-mcp` MCP server
   connects (its tools appear in the toolkit) and that
   `brancher-spinup`/`brancher-preview`/`brancher-cleanup` are available
   under `/help` or `@`-mention as `pb-hypernode-mcp:<skill-name>`.
5. Edit a file under `skills/` or `src/pb_hypernode_mcp/`, run
   `claude plugin update pb-hypernode-mcp@pb-hypernode-mcp`, and confirm the
   change is picked up without a fresh marketplace add.

## License

Apache-2.0. See `LICENSE` and `NOTICE` for third-party dependency/service
attribution (Hypernode Brancher API, system `ssh`/`rsync`, MCP Python SDK).
