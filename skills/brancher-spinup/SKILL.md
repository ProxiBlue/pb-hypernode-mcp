---
name: brancher-spinup
description: Spin up a disposable Hypernode Brancher preview environment cloned from production, with mandatory automatic PII/gateway sanitization, and return access details. Use when a client asks to preview a change on a real prod-clone environment before it ships.
---

# Brancher Spinup

Creates a Brancher node, waits for it to become SSH-reachable, sanitizes it
(anonymize PII, reset admin credentials, sandbox payment gateways/API keys),
and only then reports it ready with its access URL. All of this happens in
a **single MCP tool call** — `brancher_create` — because the underlying
create -> wait -> sanitize -> report-ready sequence is non-bypassable by
design: `brancher_create` IS the gated flow, not a raw/unsanitized creation
call. It is structurally impossible to get an access URL back for a node
that has not finished sanitizing, and there is no other tool that creates a
node — `brancher_create` is the sole node-creation entry point this plugin
exposes.

## Flow

1. **Identify which Hypernode/app.** Hypernode API tokens are scoped per
   app, not account-wide — if the user's request doesn't say which app to
   target, call `brancher_apps` first and show the configured list before
   calling any other tool. Never guess an `appname`. If exactly one app is
   configured, it's fine to proceed with it — just tell the user which one
   you're using rather than asking a pointless confirmation question.

2. **Ask for a label if the user hasn't given one.** `brancher_create`
   requires at least one label (e.g. a ticket number like `ticket-123` or a
   short description) — it is not optional, and the call will fail without
   one. Don't invent a label on the user's behalf; if they haven't mentioned
   a ticket/reason, ask.

3. **Call `brancher_create`** with `appname`, `labels`, and optionally
   `clear_services` (defaults to clearing `cron` if omitted). This one call
   covers the entire create -> wait -> sanitize -> ready sequence — do not
   poll or call other tools in between.

   - **This call can take up to ~20 minutes** (Hypernode's own Control Panel
     states node setup can take up to 15 minutes before the node even
     becomes SSH-reachable, before sanitization runs on top of that).
     Because of this, run `brancher_create` via a **background
     Agent/Task call** rather than blocking the current session inline —
     tell the user you're spinning it up in the background, then report
     back with the result (ready, or a clear failure) when the background
     agent completes. Do not poll for progress in the foreground; the
     background agent's single completion notification is the signal.
   - **Run the background agent on the cheapest available model (e.g.
     Haiku), not the session's default model.** This task is a single
     deterministic tool call plus reporting the structured result back
     verbatim — no real reasoning, judgment, or code-writing happens in
     that agent, so there's no reason to spend a larger model's tokens on
     it just because it runs a long time. If a background-agent
     invocation doesn't expose a model override, pick the smallest/cheapest
     agent type or model setting available rather than defaulting silently
     to whatever the session is already running.
   - **If the calling session ends before the background agent completes,
     do not blindly retry `brancher_create` next session.** Check
     `brancher_list(appname)` first — a real node may already exist and
     still be provisioning (or already sanitized-and-ready, if you're very
     unlucky with timing) from the interrupted attempt. There is no way to
     "resume" just the wait+sanitize step on an existing node (by design —
     `brancher_create` is the only entry point so sanitization can never be
     skipped), so if a stale node is found, delete it first
     (`brancher_delete`, confirming) rather than leaving it to accrue cost
     indefinitely, then start a fresh `brancher_create` call.
   - If the app has no configured token (`HYPERNODE_API_TOKENS`), or is not
     on a Falcons-eligible plan, or no label was provided, the call fails
     immediately before anything is created. Surface that error message to
     the user verbatim — it already explains which guardrail was tripped.

4. **Report the guardrail context, not just the URL.** On success the tool
   returns:

   - `node_name` — the created node's Brancher name (`<appname>-eph<id>`)
   - `minutes_remaining` — always `None`. There is no verified Hypernode API
     source for a remaining-minutes figure; do not report this to the user
     as if it were meaningful data, and do not claim to know the app's
     Brancher budget from this field.
   - `access_url` — the browsable site URL for the sanitized node
   - `admin_url` — VERIFIED (2026-08-21) unreliable even after v0.5.1's
     settle-delay fix: a real client-facing spin-up still returned the
     `/admin` fallback here while a manual check moments later got the
     real path instantly, no race even in play. The real, durable fix
     (v0.5.2+) is `HYPERNODE_KNOWN_ADMIN_PATHS` — set the app's admin path
     once (`{"myapp":"/admin-custom"}`) and `brancher_create` skips
     runtime discovery entirely for that app, eliminating the race rather
     than continuing to chase its timing. **If that env var isn't
     configured for this app yet**, do not trust this field as-is: call
     `brancher_exec(node_name, "cd current_root && n98-magerun2
     info:adminuri")` after `brancher_create` returns, parse the real path
     out of its stdout, and build the admin URL you report from THAT —
     then tell the user to add the confirmed path to
     `HYPERNODE_KNOWN_ADMIN_PATHS` so future spin-ups for this app skip
     the check entirely. See the open tracking thread (chatroom) for
     status.
   - `admin_username` / `admin_email` — the sanitized identity of the
     ORIGINAL admin account (`admin` / `admin@example.invalid` by default).
     This account is deliberately LOCKED (invalid password hash) — don't
     present it as a working login. The live production admin
     username/email is never present on this node.
   - `admin_password_note` — always report this verbatim. Explains that the
     account above is intentionally locked and points at
     `preview_admin_username`/`preview_admin_password` instead.
   - `preview_admin_username` / `preview_admin_password` — a genuinely
     usable admin login, freshly created on every node
     (`bin/magento admin:user:create`) with a random password, `None`/`None`
     if the server was configured with `preview_admin_username = None`.
     THIS is the login to report to the user for actually accessing the
     admin panel — not `admin_username` above.
   - `sales_and_customer_data_sanitized` — always `true` on a successful
     result (sanitization is mandatory and non-bypassable — if this field
     is present at all, PII/sales data has already been anonymized).
     State this back to the user explicitly as confirmation, don't just
     imply it.
   - `preview_basic_auth_username` / `preview_basic_auth_password` — HTTP
     Basic Auth gate on the node's own hostname, `None`/`None` if the
     server was configured with `basic_auth_username = None`. When set,
     this is the ONLY thing standing between the sanitized-but-still-real
     storefront/admin and anyone who gets the URL — always report both
     values verbatim alongside the URLs, never omit them as if the login
     were optional. The password is freshly random every spin-up, never a
     fixed/shared one.
   - `status` — always `"ready"` on success (sanitization already ran)
   - `sanitization_commands_run` — how many sanitization commands were
     executed against the node before it was reported ready (includes the
     base-URL/vhost setup commands, not just the PII/gateway ones)
   - `ip_assigned_after_seconds` — how long Hypernode's own provisioning took
     to assign the node a real ip (phase 1 of the reachability wait)
   - `ssh_reachable_after_seconds` — how long SSH then took to answer once
     the ip existed (phase 2)

   Always report back to the user: the site URL (`access_url`) — and its
   Basic Auth login (`preview_basic_auth_username`/`preview_basic_auth_password`)
   if set, since without it the URL alone won't get anyone in — the admin
   URL (`admin_url`) with its WORKING login (`preview_admin_username`/
   `preview_admin_password` — NOT `admin_username`/`admin_email`, which is
   the deliberately-locked original account), and an explicit confirmation
   that sales/customer data was sanitized. Omit `minutes_remaining`; it carries no real
   information. When the two phase timings are notably uneven (e.g. most of
   the wait was IP assignment, or most of it was SSH), mention the split —
   e.g. "IP assigned after 6 min, SSH reachable 40s after that" — since it
   gives the user real signal about where the time went, useful if they need
   to report a slow spin-up back to Hypernode support.

5. **Mention `brancher_ssh_info` for direct SSH access.** The URL from step
   4 is enough for browsing, but if the user wants to SSH in directly (to
   run commands, inspect logs, etc.), tell them they can call
   `brancher_ssh_info` with the returned `node_name` to get `host`, `user`,
   and `port`. Don't call it automatically — only mention it as the next
   step, since not every spin-up is followed by an SSH session.

## Errors

`brancher_create` can fail at four points, and the error message differs by
which one — the wait itself is two explicit, separately-timed phases (an
ip-assignment poll against Hypernode's REST API, then an SSH-reachability
poll), so a timeout during the wait is never a single generic "unreachable"
error; the exception type alone tells you which phase stalled:

- **Pre-create guardrail** (missing label, app has no configured token, app
  not Falcons-eligible) — nothing was created; adding the app's token to
  `HYPERNODE_API_TOKENS` or fixing its plan is the fix, or supply a label.
- **403 mentioning the "financial nature of the command"** — this is not a
  bug in this plugin. It means `allow_api_token_usage` is off for the app;
  an owner/admin must enable "API token usage" in the Hypernode Control
  Panel (Configuration -> Settings) before any Brancher/financial API call,
  including `brancher_create`, will succeed. Tell the user this plainly
  rather than treating it as a transient failure to retry.
- **Node never gets assigned an ip** (`NodeIpNeverAssignedError`) — phase 1:
  the node was created but Hypernode's own provisioning never gave it a real
  ip address within the timeout. This is unambiguously Hypernode's own
  infra stalling, not anything on this plugin's side — SSH was never even
  attempted, since there was no host to attempt it against. Tell the user
  this plainly and suggest checking Hypernode's own status or contacting
  their support; retrying this plugin's config will not fix it.
- **Node gets an ip but SSH never becomes reachable**
  (`NodeUnreachableTimeoutError`) — phase 2: the node has a real ip, but SSH
  itself never answered within the remaining time budget (the overall
  reachability timeout, 20 minutes by default, minus however long phase 1
  already took — phase 2 does not get a fresh timeout of its own). This
  points at SSH-specific causes (sshd still starting, host key/config
  issues) rather than Hypernode's provisioning. Surface this plainly; it
  usually means retrying later or checking SSH connectivity specifically.
- **Sanitization failed partway through** (`SanitizationFailedError`) — the
  node was created and became reachable, but a sanitization command failed.
  **The access URL is deliberately withheld in this case** — do not attempt
  to construct or guess the URL yourself from the node name. A node that
  failed sanitization may still have live production PII/credentials on it
  and must not be handed to the user as "ready". Tell the user spin-up
  failed and that the node was not made available; suggest running
  `brancher-cleanup` to remove the half-sanitized node rather than reusing
  it.

In every failure case, surface the exact error message returned by the tool
— it already names the node and, for sanitization failures, how many
commands succeeded before the failure. Don't paraphrase it into something
vaguer.

## Example

```
User: "Spin up a preview of myapp for ticket-482."

0. Tell the user: "This can take up to ~20 minutes — spinning it up in the
   background so I don't block this session. I'll report back when it's
   ready." Then invoke brancher_create via a background Agent/Task call,
   run on the cheapest available model (e.g. Haiku) since the agent is
   just making one deterministic tool call and relaying the result.

1. brancher_create(appname="myapp", labels=["ticket-482"]) ->
   {
     "node_name": "myapp-eph198234",
     "minutes_remaining": None,
     "access_url": "https://myapp-eph198234.hypernode.io/",
     "admin_url": "https://myapp-eph198234.hypernode.io/admin",
     "admin_username": "admin",
     "admin_email": "admin@example.invalid",
     "admin_password_note": "Password deliberately invalidated during sanitization -- this account (the sanitized original) is intentionally locked out; use preview_admin_username/preview_admin_password below to log in instead.",
     "preview_basic_auth_username": "preview",
     "preview_basic_auth_password": "Kj3n_9dQpXm2vLwZ",
     "preview_admin_username": "preview",
     "preview_admin_password": "rgIbrYnWwFEJ2nt6xzQ0pA-Aa1!",
     "status": "ready",
     "sanitization_commands_run": 21,
     "sales_and_customer_data_sanitized": True,
     "ip_assigned_after_seconds": 360,
     "ssh_reachable_after_seconds": 40
   }

2. Report to the user:
   "Preview ready: https://myapp-eph198234.hypernode.io/
    - Login required: username `preview`, password `Kj3n_9dQpXm2vLwZ`
      (fresh, random every spin-up — not the URL alone).
    - Node: myapp-eph198234
    - Admin: https://myapp-eph198234.hypernode.io/admin — username `preview`,
      password `rgIbrYnWwFEJ2nt6xzQ0pA-Aa1!` (also fresh, random every
      spin-up).
    - Sanitization: 21 commands run (base URL + vhost + Basic Auth wired to
      this node, sales/customer PII anonymized, admin credentials reset +
      a real admin login provisioned, payment gateways sandboxed) before
      this URL was returned.
    - Timing: IP assigned after 6 min, SSH reachable 40s after that.
    - Need to SSH in directly? I can pull connection details via
      brancher_ssh_info."
```

```
User: "Spin up myapp for ticket-501."

1. brancher_create(appname="myapp", labels=["ticket-501"]) raises
   SanitizationFailedError: "Sanitization failed on Brancher node
   'myapp-eph200011' while running '...' (4 prior command(s) succeeded).
   The node is NOT ready and its access URL is being withheld."

2. Report to the user:
   "Spin-up for myapp-eph200011 failed during sanitization (4 of the
    sanitization steps completed before the failure) — no access URL was
    issued, since a partially-sanitized node could still expose production
    data. I'd recommend running brancher-cleanup to remove it rather than
    retrying on the same node."
```

## Implementation notes (for maintainers, not the AI reading this at runtime)

`brancher_create` is a thin MCP tool wrapper (`register()` in
`src/pb_hypernode_mcp/tools/brancher_spinup_flow.py`) around the
already-tested `spinup_sanitized_brancher_node()` orchestration function.
The wrapper itself is unit-tested directly (`tests/tools/test_brancher_spinup_flow.py`,
`tests/test_server.py`) since this markdown file's prose is not a unit-testable
surface — see that task's Implementation Notes for the test/prose split.

Task 022 split the wait into two explicit phases: `_wait_for_ip_assignment()`
polls the Brancher list endpoint (via `list_brancher_nodes()`, reused
as-is — no SSH, cheap, can start immediately) until the node's `ip` field is
non-null, raising `NodeIpNeverAssignedError` on timeout; only then does
`_wait_until_reachable()` (unchanged in shape, but now given only the
remaining time budget) start polling SSH. Both phase durations are threaded
through into the returned dict as `ip_assigned_after_seconds`/
`ssh_reachable_after_seconds`.
