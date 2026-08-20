# pb-hypernode-mcp

Client-side Claude Code plugin for [Hypernode Brancher](https://www.hypernode.com/en/brancher/) — spin up disposable, prod-clone preview environments, drive AI-assisted changes over SSH, view via your existing browser MCP.

## Why

Brancher gives you a mutable, temporary copy of your production Hypernode (≤24h-old data, full toolchain, real infra — not a Docker approximation). The catch: it clones production wholesale, meaning live customer PII and real payment/API credentials come along by default, and the node gets a public URL. This plugin closes that gap — every node it creates is anonymized and sandboxed automatically, before it's ever reported ready, so "let the client's AI poke at a real prod clone" doesn't also mean "expose real customer data on the internet."

## Setup

Three steps: install the plugin, tell it your Hypernode token, restart Claude Code.

### 1. Install the plugin

Type this directly into Claude Code (no terminal needed):

```
/plugin marketplace add ProxiBlue/pb-hypernode-mcp@latest
/plugin install pb-hypernode-mcp@pb-hypernode-mcp
```

Claude Code fetches everything straight from GitHub — no downloading, no separate server to run, nothing to clone by hand.

`@latest` pins you to the newest tested release rather than whatever's mid-development on `main`. To pin to a specific version instead (for reproducibility, e.g. across a team), use its tag directly — check [Releases](https://github.com/ProxiBlue/pb-hypernode-mcp/releases) for the current version number, then:

```
/plugin marketplace add ProxiBlue/pb-hypernode-mcp@vX.Y.Z
```

**If Claude Code reports "already at the latest version" but you know a newer release exists**, it's comparing version numbers, not git commits — re-running `marketplace update` does nothing if the version string didn't change between releases. Remove and re-add the marketplace to force a fresh fetch:

```
/plugin marketplace remove pb-hypernode-mcp
/plugin marketplace add ProxiBlue/pb-hypernode-mcp@latest
/plugin install pb-hypernode-mcp@pb-hypernode-mcp
/reload-plugins
```

(If you'd rather run it from a terminal instead, the same commands work as `claude plugin marketplace add ...` / `claude plugin install ...`.)

### 2. Add your Hypernode API token(s)

Hypernode API tokens are scoped **per Hypernode**, not account-wide — there's no single token that works across every app you manage. This plugin needs one token per Hypernode you want it to touch, set as a JSON object mapping `<appname>` to its token. It never gets stored anywhere by the plugin — you set it as an environment variable, the same way you'd set any password-like value.

Find each app's token in its Hypernode Control Panel, then in your terminal (before opening Claude Code):

```bash
export HYPERNODE_API_TOKENS='{"myapp":"token1","myapp2":"token2"}'
```

Managing a single Hypernode? A one-entry map still works:

```bash
export HYPERNODE_API_TOKENS='{"myapp":"your-token-here"}'
```

The map's keys ARE the allowlist — only apps with an entry here can be operated on. An app with no token configured raises a clear error rather than silently trying (and failing) with the wrong credentials.

Tip: add this line to your shell's startup file (`~/.zshrc` or `~/.bashrc`) so you don't have to re-type it every time.

### 3. Restart Claude Code

Close and reopen Claude Code so it picks up the token and connects to the plugin. You're ready to go.

## Quick start

Just ask, in plain English:

> "Spin up a Brancher preview for myapp so I can show the client the new category page layout."

Claude creates the node, waits for it to come online, sanitizes it (see [Safety guardrails](#safety-guardrails)), and reports back:

```
node_name:     myapp-eph482913
access_url:    https://myapp-eph482913.hypernode.io/
```

**Realistic wait time: up to ~15-20 minutes.** Hypernode's own Control Panel states new Brancher node setup can take up to 15 minutes before the node even becomes SSH-reachable, before sanitization runs on top of that — this is normal, not a stall. The wait is two separately-timed phases under the hood (Hypernode assigning the node a real ip, then SSH itself answering); on success the report includes `ip_assigned_after_seconds`/`ssh_reachable_after_seconds` so Claude can tell you where the time actually went. Claude will typically run this in the background (a background Agent/Task call) rather than blocking the session for the full duration, and report back once the node is ready.

(`minutes_remaining` is always `None` — no verified Hypernode API source for a remaining-minutes figure exists yet; see [Limitations](#limitations-v1).)

From there, ask it to make a change and show you the result, or just say "clean up any leftover preview nodes" when you're done — Brancher bills by the minute whether or not anyone's looking at it.

## What's in the plugin

```
skills/
├── brancher-spinup/      create a sanitized preview node, report access details
├── brancher-preview/     full loop: spin up -> change -> build -> screenshot
└── brancher-cleanup/     list/flag/delete leftover nodes
src/pb_hypernode_mcp/     the MCP server (7 tools) — see MCP tools below
tests/                    automated test suite
```

## Requirements

- A Hypernode account on a **Falcons** plan, with an API token from the Control Panel (Brancher is a Falcons-only feature).
- **`allow_api_token_usage` enabled on the app.** Real accounts default this setting to `false`. Hypernode 403s any Brancher/financial API call — including `brancher_create` — until an owner/admin explicitly turns on "API token usage" for the app in the Control Panel (Configuration -> Settings). A 403 whose message mentions the "financial nature of the command" means this setting is off — it is not a bug in this plugin.
- SSH access to the Hypernode account's `app` user resolvable with **no explicit `-i` flag** — the plugin shells out to plain `ssh app@<node>.hypernode.io`/`rsync`, so whichever key `ssh` picks by default (agent identities, `~/.ssh/id_*`, or an `~/.ssh/config` match) must already be the one registered with your Hypernode account. If your `~/.ssh/config` only has per-app aliases (e.g. `Host hypernode_myapp`) rather than a `Host *.hypernode.io` wildcard, Brancher's generated hostnames (`<appname>-eph<id>.hypernode.io`) won't match any of them and ssh silently falls back to a key Hypernode doesn't recognize — see [Troubleshooting](#troubleshooting).
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) installed on the machine running Claude Code (Claude Code plugins are just code — this is the runtime they need).

## MCP tools

All 7 tools are registered on the `pb-hypernode-mcp` server (`src/pb_hypernode_mcp/server.py`). `brancher_exec` and `brancher_put` shell out to the system `ssh`/`rsync` binaries using your already-configured local SSH agent/key — this plugin never holds or stores key material itself. Every tool that calls the Hypernode REST API resolves its token per-app from `HYPERNODE_API_TOKENS`; an `appname` with no entry in that map has nothing to authenticate with and the call fails with a clear error listing which apps ARE configured.

| Tool | Purpose | Key arguments |
|---|---|---|
| `brancher_create` | The sole node-creation tool: enforces a mandatory label and Falcons-plan eligibility, then wraps create -> wait -> run mandatory sanitization (including pointing the node's own base URL/vhost at itself) -> report ready as one non-bypassable call. There is no separate "raw create" tool — it is structurally impossible to create a Brancher node through this plugin without sanitization running first. Never returns an `access_url` for a node that has not finished sanitizing. The wait is two explicit, separately-timed phases sharing one 1200s (20 min) ceiling: phase 1 polls the Brancher list endpoint (no SSH) until Hypernode assigns a real `ip`, raising `NodeIpNeverAssignedError` on timeout — Hypernode's own provisioning stalled, not an SSH/config issue; phase 2 then polls SSH reachability with whatever's left of the budget, raising `NodeUnreachableTimeoutError` if the ip was assigned but SSH itself never answered. `SanitizationFailedError` (access URL withheld) is raised if a sanitization or url-setup command fails partway through. On success the result includes `ip_assigned_after_seconds`/`ssh_reachable_after_seconds`, `admin_url`, `admin_username`/`admin_email` (sanitized placeholder values), `admin_password_note`, and `sales_and_customer_data_sanitized: true`. Because this call can take up to ~20 minutes, skills invoke it via a background Agent/Task call rather than blocking inline. | `appname` (str), `labels` (list[str], required, at least one), `clear_services` (list[str], optional, defaults to `["cron"]`) |
| `brancher_list` | List active Brancher nodes for `appname`. Returns each node's `name`, `host`, `minutes` (wall-clock uptime since creation, not idle-aware), and `ip` (`None` until Hypernode's provisioning assigns one). Rejects any `appname` with no configured token. | `appname` (str) |
| `brancher_delete` | Delete a Brancher node. Gated behind a `confirm=True` re-call: the first call (default `confirm=False`) looks up and returns the target node's details plus a confirmation prompt without deleting anything; only a second call with `confirm=True` issues the actual DELETE. Validates the node name against the `-eph<id>` pattern first. | `node_name` (str, `<appname>-eph<id>`), `confirm` (bool, default `False`) |
| `brancher_ssh_info` | Return SSH connection details (`host`, `user`, `port`) for a node, without opening a connection itself. Raises `NodeNotReadyError` if the node has no IP assigned yet. | `node_name` (str) |
| `brancher_exec` | Run a shell command on a Brancher node over SSH (shells out to the system `ssh` binary). The single safety-critical chokepoint of the "change-it" layer: refuses any `node_name` that doesn't match the `-eph<id>` pattern, before spawning any subprocess — structurally impossible to point this tool at a production host. Returns `stdout`/`stderr`/`exit_code`; raises `SshConnectionError` on ssh's own exit code 255, `SshCommandTimeoutError` on timeout. | `node_name` (str), `command` (str), `timeout` (float, default 30s) |
| `brancher_put` | Sync a local file/directory to a Brancher node via `rsync -az --protect-args` over SSH. Same `-eph`-only guard and local-SSH-agent connection model as `brancher_exec`. Raises `SyncError` on non-zero rsync exit. | `node_name` (str), `local_path` (str), `remote_path` (str), `port` (int, default 22) |
| `brancher_apps` | List every Hypernode `<appname>` with a configured API token — pure local config introspection, no REST API call. Skills call this first whenever a request doesn't say which Hypernode/app to target, so they never have to guess. | none |

## Skills

- **`brancher-spinup`** — spin up a disposable Brancher preview node cloned from production, with mandatory automatic sanitization, and report its access URL. Use when a client asks to preview a change on a real prod-clone environment before it ships. Wraps the single `brancher_create` tool call — never reproduces the create/wait/sanitize sequence by hand.
- **`brancher-preview`** — the full loop: spin up a node (via the `brancher-spinup` skill), apply a code change (push a local diff with `brancher_put`, or edit in place with `brancher_exec`), run only the Magento build commands the change actually needs (`decide_build_commands()` in `src/pb_hypernode_mcp/preview_logic.py`), view the result through whatever browser MCP tool is already in the session, then explicitly remind the user the node is still billing Brancher minutes. Use when a client wants an end-to-end look at a change on a disposable environment. Never deletes the node itself.
- **`brancher-cleanup`** — list active nodes with `brancher_list`, flag any at or past an age threshold (`minutes >= threshold_minutes`, default 240 minutes / 4 hours, via `flag_stale_nodes()` in `src/pb_hypernode_mcp/cleanup_logic.py`), and delete flagged nodes (single or bulk) only after explicit user confirmation. Use when a client wants to check for or remove leftover Brancher nodes to stop minute accrual. Brancher bills wall-clock minutes from creation regardless of whether anyone is actively using the node.

### Multiple Hypernodes

Every Hypernode needs its own entry in `HYPERNODE_API_TOKENS` — there is no account-wide token. All three skills call `brancher_apps` first whenever a request doesn't say which app to target, show the configured list, and ask before doing anything else; they never guess an appname. If only one app is configured, they proceed with it and just say so, rather than asking a pointless confirmation question.

## Safety guardrails

- **Mandatory sanitization — cannot be disabled.** Every `brancher_create` call runs the full sanitization sequence (`src/pb_hypernode_mcp/sanitization/`) against the node before it is ever reported `"ready"` or returns an `access_url`. There is no flag, config option, or bypass path — `brancher_create` is the ONLY node-creation MCP tool this plugin registers (there is no separate, unsanitized create tool), and `spinup_sanitized_brancher_node()` in `src/pb_hypernode_mcp/tools/brancher_spinup_flow.py` (the function behind it) structurally cannot return an access URL without every sanitization command having exited 0 first. If a sanitization command fails partway through, the tool raises `SanitizationFailedError` and deliberately withholds the access URL — the exception does not even carry it, so a catching caller has no way to accidentally surface it.

  The sequence (config-driven, Magento-shaped default in `sanitization/config.py::DEFAULT_MAGENTO_SANITIZATION_CONFIG`):
  1. **Base URL + vhost setup** — a freshly cloned Brancher node keeps the *originating* app's base URL and has no nginx vhost at all for its own new ephemeral hostname (Hypernode's own documented behaviour — see "Brancher Install Hook" in their docs). `bin/magento config:set web/unsecure/base_url`/`web/secure/base_url` are forced to the node's own `https://<node>.hypernode.io/` at the default scope **and** at each website scope in `SanitizationConfig.base_url_website_scope_codes` (defaults to `('base',)`, Magento's own default website code — VERIFIED live: a website-scoped `env.php` override wins over the default-scope value and, left untouched, kept 301-redirecting the site back to the old domain). The cache is flushed, and (if `vhost_webroot` is set — defaults to Hypernode's standard single-app `/data/web/public` layout) `hypernode-manage-vhosts` creates the vhost. Set `vhost_webroot=None` to skip vhost creation for a multi-app-per-domain layout; set `base_url_website_scope_codes=()` to skip the website-scope pass for an app with no such override.
  2. **PII anonymization** — `UPDATE` statements (via `n98-magerun2 db:query`) against `customer_entity`, `customer_address_entity`, `sales_order`, `sales_order_address` (names/emails/phones/street replaced with anonymized placeholders), and stored card data (`quote_payment`, `sales_order_payment`: `cc_number_enc`, `cc_cid_enc`, `cc_owner`, `additional_data` nulled).
  3. **Admin credential reset** — every `admin_user` row gets its password overwritten with a hash that is deliberately invalid for any real password (locks form-based login until an operator sets a real one via `bin/magento admin:user:create` — see `admin_password_note` in the result), and its username/email replaced with a per-row-unique sanitized value (`admin_user.username` carries a unique index — a bare literal on a bulk update would violate it on any account with more than one admin row). A second, `where`-scoped update (`SanitizationConfig.admin_primary_user_reset`) then overrides exactly one deterministic row back to the literal `admin`/`admin@example.invalid` identity reported in the result as `admin_username`/`admin_email`, so there is always exactly one guaranteed, known-value login.
  4. **Payment gateway sandbox-forcing** — forces e.g. `payment/braintree/environment=sandbox` (PayPal-via-Braintree is covered by the same setting; a real Magento 2.4.9 install has no working `paypal/general/sandbox_flag` at all — legacy PayPal Standard/Express convention, verified absent).
  5. **Third-party API key stubbing** — replaces live keys (e.g. AvaTax) with dummy sandbox values so no preview node can make a real charge or a real third-party API call under production credentials. ShipperHQ is deliberately excluded from this list (explicit client decision) — it stays on its live/production setting on every node, since it has no "developer mode" distinction to force it into.

  Steps 4 and 5 write directly to `core_config_data` via a raw SQL UPSERT rather than `bin/magento config:set` — VERIFIED (2026-08-20) against a real Braintree install that `config:set` validates the path against system.xml-declared admin-UI fields and refuses a genuinely real, actively-used config path with "doesn't exist". Magento's runtime config reader has no knowledge of system.xml and reads raw DB rows directly, so the UPSERT achieves the actual sanitization goal without fighting that unrelated validation layer. A trailing `cache:flush` runs once afterward so the sandboxed values are actually served.

  Each command gets a bounded retry (3 attempts, 5s apart by default) if it hits a connection-level failure — verified live: a DNS record for a freshly created node can flap even after the SSH-reachability probe already succeeded once. A command that ran and returned a non-zero exit code is never retried (a real command failure, not a connectivity blip) — it fails `SanitizationFailedError` immediately.

  After all commands succeed, `brancher_create` makes a best-effort (non-blocking) call to `bin/magento info:adminuri` to report the node's actual `admin_url`, retried the same bounded number of times as sanitization commands on a connection-level failure (VERIFIED live: a single un-retried transient blip here used to silently report `/admin` when the site's real, custom admin path was `/admin-uptactics`) — a failure or unexpected output after retries are exhausted never fails spin-up, it just falls back to `/admin`.

  A real client app's exact table shape and installed integrations should override/extend `SanitizationConfig`, not rely on the shipped default in production — it exists as a safe-by-default starting point, not a promise it matches every schema.
- **Per-app token allowlist** (`HYPERNODE_API_TOKENS`) — the map's keys ARE the allowlist. `brancher_create`, `brancher_list`, `brancher_delete`, and `brancher_ssh_info` refuse any `appname` with no configured token — there is no separate allowlist mechanism to fall out of sync with the token map.
- **Falcons-plan eligibility check** — `brancher_create` rejects apps not on a Brancher-eligible plan before creating anything.
- **`-eph`-only guard** — `brancher_exec` and `brancher_put` validate `node_name` against the `<appname>-eph<id>` pattern (`tools/_guards.py::validate_eph_node_name`, `.fullmatch()` — no partial-match or trailing-character gaps) before opening any SSH connection or subprocess. It is structurally impossible to point either tool at a production hostname.
- **Confirm-before-delete** — `brancher_delete` never deletes on the first call. It requires an explicit `confirm=True` re-call after showing the target node's details; a threshold being configured or a node being flagged as stale is never itself confirmation.
- **Mandatory label** — `brancher_create` rejects calls with no `labels`, so every node is traceable to a reason/ticket.
- **Token handling** — `HYPERNODE_API_TOKENS` is read from the environment only and is never written to disk or plugin config by this plugin. Each Hypernode's token is only ever used to authenticate requests for its own app.
- **`brancher_put` argument hardening** — `remote_path`/`local_path` are shell-quoted and rsync runs with `--protect-args`, so the remote host's shell never re-parses a path argument, closing off metacharacter injection via a crafted path.

This design was checked by a 3-specialist security review before release (static analysis, adversarial testing, defensive audit). It caught a real critical gap in an earlier draft — the sanitized flow had been built as a second tool alongside a still-exposed raw, unsanitized create path — which is why "one creation tool, no exceptions" is called out so insistently above. Found a security issue? Open an issue rather than a PR with the exploit details.

## Limitations (v1)

- **No Basic Auth on the new vhost (confirmed gap, 2026-08-20).** A sanitized node's storefront/admin is reachable by anyone with the URL — the parent app's own vhost had HTTP Basic Auth active (verified: `curl` without credentials returned 401), but a vhost freshly created by `hypernode-manage-vhosts` does NOT inherit it (verified: same check on the new vhost returned 200 with no credentials at all). Confirmed this isn't self-service fixable from user space: `hypernode-manage-vhosts --help` has no basic-auth-related flag, the per-vhost `server.basicauth.conf` template Hypernode ships is inert (commented out) even on the working parent vhost, and the real enabling mechanism lives somewhere in Hypernode's own platform-level provisioning (outside `/etc/nginx/app/<hostname>/`, which is root-owned — the `app` user can't write there directly). No PII/payment exposure risk (sanitization still ran in full before the URL is ever returned) — just no login gate on a URL that anyone with the link could browse. Needs either a Hypernode support answer on the self-service mechanism, or a documented root-required manual step; not solved in v1.
- **Magento/Mage-OS only.** The sanitization layer's default config (`DEFAULT_MAGENTO_SANITIZATION_CONFIG`) and the `brancher-preview` skill's build-command decision logic (`decide_build_commands()`) are both Magento-shaped. This is not a generic multi-platform tool — WooCommerce, Shopware, Laravel, and other Hypernode-hosted platforms are out of scope for v1. A non-Magento app would need a hand-written `SanitizationConfig` at minimum, and the preview skill's build sequence would not apply.
- **No MCP-managed SSH keys.** `brancher_exec`/`brancher_put` shell out to the system `ssh`/`rsync` binaries and rely entirely on your own local SSH agent/key already having access to Brancher nodes (which inherit access automatically via Brancher's full-filesystem clone from production). This plugin never provisions, stores, or transmits key material.
- **stdio transport only.** No remote/HTTP MCP transport in v1 — this is a local Claude Code plugin, run per-developer against their own `HYPERNODE_API_TOKENS`. There is no hosted/managed version of this MCP. Token and SSH access are both entirely client-owned.
- **REST API only.** No Hypernode Deploy (`deploy.php`) integration in v1.
- **Wall-clock, not idle-aware, minute accounting.** `brancher-cleanup`'s staleness check uses `minutes` as reported by the Hypernode API (uptime since creation) — it cannot tell an idle node from an actively used one.
- **The reachability wait is two explicit phases, not one blind SSH-poll loop.** Earlier versions started retrying SSH immediately after create, even while the node had no ip at all yet — every poll was guaranteed to fail until Hypernode's own provisioning finally assigned one, and a timeout only ever surfaced as a single generic "never became reachable" error with no way to tell "Hypernode's infra never gave us a host" apart from "we had a host but SSH never answered". `spinup_sanitized_brancher_node` now splits the wait: phase 1 polls the Brancher list endpoint (a plain REST call, no SSH, reusing `brancher_list`'s `ip` field) until the node has a real ip, raising `NodeIpNeverAssignedError` on timeout; phase 2 then polls SSH with whatever's left of the 1200s (20 min) ceiling, raising `NodeUnreachableTimeoutError` if the ip showed up but SSH itself never answered. The two phases share that one ceiling — phase 2 does not get a fresh timeout of its own on top of phase 1. On success both phase durations (`ip_assigned_after_seconds`, `ssh_reachable_after_seconds`) are returned so a slow spin-up can be reported back to Hypernode support with real numbers instead of "it just timed out".
- **Plan-eligibility field verified; minutes-remaining has no known source.** `brancher_create`'s Falcons-plan eligibility check is confirmed against a real Hypernode account (`GET /v2/app/<appname>/`): the field is `product.code` (e.g. `"FALCON_S_202603DEV"`, matched as a `"FALCON"` substring since Hypernode has multiple Falcon SKUs — not a `plan_type` field, and not an exact-value match). The earlier `minutes_remaining` field name (`brancher_minutes_remaining`) was not just misnamed but nonexistent — there is no verified field or endpoint anywhere on the Hypernode API for an account-wide remaining-minutes figure, so `create_brancher_node` always returns `minutes_remaining: None`.
- **Brancher endpoints, response shapes, and node-name ID charset: now VERIFIED, not guessed (2026-08-19).** Confirmed via two independent sources — a live `curl` against a real Hypernode account's Brancher list endpoint, and the official [`ByteInternet/hypernode-api-python`](https://github.com/ByteInternet/hypernode-api-python) client library's source (`hypernode_api_python/client.py`).
  - **Real, non-deprecated endpoints**: list is `GET /v2/brancher/app/<appname>/`, create is `POST /v2/brancher/app/<appname>/`, destroy is `DELETE /v2/brancher/<name>/` (a *different* top-level path — not nested under `/v2/app/<appname>/` at all). The old `/v2/app/<appname>/brancher/` shape still works but returns an API deprecation warning.
  - **List response**: the node array is under a top-level `branchers` key, not `nodes`. Each entry has `name`, `ip` (null until ready), `created`, `elapsed_time` (wall-clock **seconds** since creation), and `cost` (minutes billed) — no `host` field (`brancher_list` derives it as `f"{name}.hypernode.io"`) and no `minutes` field (`brancher_list` derives it as `elapsed_time // 60`).
  - **Create response**: the node-name field is `name`, not `appname` (confirmed against the official client library's own docstring example, e.g. `{"name": "yourappname-ephoj82yb", ...}`).
  - **Node readiness**: `brancher_ssh_info` reads `ip`, not `ip_address` (confirmed via live curl on `GET /v2/app/<appname>/`).
  - **`-eph<id>` suffix charset**: lowercase-alphanumeric, not digit-only — both a real account's node (`ppsdev-ephp8b5c2`) and the official client library's own examples (`yourappname-ephoj82yb`) show alphanumeric suffixes.
- **Brancher/financial API calls require `allow_api_token_usage: true`.** This is an account-level setting (Hypernode Control Panel -> Configuration -> Settings, owner/admin only), not a code path in this plugin — see [Requirements](#requirements).
- **Playwright test offloading not yet built.** Running the functional test suite against a Brancher node instead of local/CI is tracked separately — see [ProxiBlue/pb-hypernode-mcp#1](../../issues) or the originating design ticket.

## Troubleshooting

- **`NodeUnreachableTimeoutError` even though the node IS actually reachable (verified 2026-08-20).** If a manual `ssh app@<node>.hypernode.io` works fine but `brancher_create` still times out waiting on SSH, suspect an **SSH key mismatch**, not a Hypernode infra problem. `brancher_exec`/`brancher_put` shell out to plain `ssh`/`rsync` with no `-i` flag (see [Requirements](#requirements)) — they rely entirely on whichever key `ssh` picks by its own default resolution. Two common causes:
  - Your `~/.ssh/config` only defines per-app aliases (`Host hypernode_myapp`, `Host hypernode_myappdev`, ...) rather than a wildcard. Those aliases only match when you literally type `ssh hypernode_myapp` — they do **not** match the real generated hostname `myapp-eph<id>.hypernode.io` that Brancher nodes actually use, so `ssh` falls through to your default identity instead, which may not be the key registered with your Hypernode account.
  - Fix: add a wildcard block to `~/.ssh/config` so it matches every Brancher-generated hostname automatically, using whichever key is actually registered with your Hypernode account (Control Panel -> Configuration -> SSH keys):
    ```
    Host *.hypernode.io
        User app
        IdentityFile ~/.ssh/your_hypernode_key
        IdentitiesOnly yes
    ```
  - To confirm this is the actual cause before editing anything: `brancher_list` the stuck node to get its `ip`/hostname, then run `ssh -v app@<hostname>.hypernode.io echo ok` by hand. `Connection refused` or a hang mid-negotiation is genuine Hypernode-side node instability (see the `NodeIpNeverAssignedError`/`NodeUnreachableTimeoutError` distinction in [Limitations](#limitations-v1)); an immediate `Permission denied (publickey,password)` with no `-i` flag confirms it's a local key-selection issue, not the node.
- **A brand new node serves nginx's default page, not your app, even after `brancher_create` reports `status: "ready"`.** This should no longer happen as of v0.3.0 — `brancher_create` now runs Hypernode's own documented base-URL/vhost setup (see the Safety guardrails section) as part of the mandatory sanitization sequence. If you still see this on a current version, check the node's `sanitization_commands_run` count in the result — a low/unexpected count together with a `SanitizationFailedError` means the vhost step itself failed (commonly: `SanitizationConfig.vhost_webroot` doesn't match your app's actual deploy layout — see the field's docstring in `sanitization/config.py`).
- **`/plugin marketplace update` reports success but nothing actually changed.** Claude Code compares the `version` field in `plugin.json`, not the git commit — moving the `latest` tag to a new commit without bumping `version` silently no-ops for anyone already installed. If you maintain a fork, always bump both `pyproject.toml` and `.claude-plugin/plugin.json` before moving tags (see [Cutting a release](#cutting-a-release)).

## Development

```bash
git clone https://github.com/ProxiBlue/pb-hypernode-mcp
cd pb-hypernode-mcp
uv sync --extra dev

uv run pytest -v                     # mocked HTTP/SSH — no real Hypernode account touched
uv run ruff check src tests          # lint
uv run ruff format --check src tests # format check
uv run pyright src tests             # type check
```

No integration tests run automatically against a real Hypernode account. If you're changing `tools/brancher_exec.py` or the reachability-polling logic in `tools/brancher_spinup_flow.py`, do a manual smoke test against a real Falcons-plan node before merging — mocks can't catch a wrong SSH-user assumption or a shape mismatch in the real API response.

To install your own clone for local development instead of the published version, point Claude Code at the folder directly:

```bash
claude plugin marketplace add pb-hypernode-mcp /path/to/your/clone
claude plugin install pb-hypernode-mcp@pb-hypernode-mcp
```

After editing skills or server code, run `claude plugin update pb-hypernode-mcp@pb-hypernode-mcp` to pick up the change without re-adding the marketplace.

If the plugin doesn't show up after installing, check: `claude plugin list` shows `pb-hypernode-mcp` as enabled; a fresh Claude Code session lists the `brancher_*` tools and the three `brancher-*` skills; `HYPERNODE_API_TOKENS` is set in the same shell you launched Claude Code from.

### Cutting a release

Bump `version` in **both** `pyproject.toml` and `.claude-plugin/plugin.json` — Claude Code's `/plugin marketplace update` compares `plugin.json`'s version string, not the git commit. Moving `latest` without bumping this means installed users get told "already at the latest version" even though the underlying code changed. Then:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
git tag -f latest        # move the floating tag to this commit
git push origin latest --force
```

`vX.Y.Z` tags are permanent and never move. `latest` always points at the newest one — that's the only tag ever force-pushed.

## License

Apache-2.0. See `LICENSE` and `NOTICE` for third-party dependency/service attribution (Hypernode Brancher API, system `ssh`/`rsync`, MCP Python SDK).
