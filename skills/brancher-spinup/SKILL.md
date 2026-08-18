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

   - If the app has no configured token (`HYPERNODE_API_TOKENS`), or is not
     on a Falcons-eligible plan, or no label was provided, the call fails
     immediately before anything is created. Surface that error message to
     the user verbatim — it already explains which guardrail was tripped.

4. **Report the guardrail context, not just the URL.** On success the tool
   returns:

   - `node_name` — the created node's Brancher name (`<appname>-eph<id>`)
   - `minutes_remaining` — how many Brancher minutes the app had left at
     creation time; tell the user this so they know their remaining budget
   - `access_url` — the browsable URL for the sanitized node
   - `status` — always `"ready"` on success (sanitization already ran)
   - `sanitization_commands_run` — how many sanitization commands were
     executed against the node before it was reported ready

   Report all of these back to the user, not just the URL — the minutes
   remaining and sanitization count are the guardrail evidence that this
   node is safe to hand to a client and won't silently blow through the
   app's Brancher allowance.

5. **Mention `brancher_ssh_info` for direct SSH access.** The URL from step
   4 is enough for browsing, but if the user wants to SSH in directly (to
   run commands, inspect logs, etc.), tell them they can call
   `brancher_ssh_info` with the returned `node_name` to get `host`, `user`,
   and `port`. Don't call it automatically — only mention it as the next
   step, since not every spin-up is followed by an SSH session.

## Errors

`brancher_create` can fail at three points, and the error message differs by
which one:

- **Pre-create guardrail** (missing label, app has no configured token, app
  not Falcons-eligible) — nothing was created; adding the app's token to
  `HYPERNODE_API_TOKENS` or fixing its plan is the fix, or supply a label.
- **Node never becomes SSH-reachable** (`NodeUnreachableTimeoutError`) — the
  node was created but never responded within the reachability timeout.
  Surface this plainly; it usually means retrying later or checking
  Hypernode's own status.
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

1. brancher_create(appname="myapp", labels=["ticket-482"]) ->
   {
     "node_name": "myapp-eph198234",
     "minutes_remaining": 118,
     "access_url": "https://myapp-eph198234.hypernode.io/",
     "status": "ready",
     "sanitization_commands_run": 12
   }

2. Report to the user:
   "Preview ready: https://myapp-eph198234.hypernode.io/
    - Node: myapp-eph198234
    - Brancher minutes remaining on this app: 118
    - Sanitization: 12 commands run (PII anonymized, admin credentials
      reset, payment gateways sandboxed) before this URL was returned.
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
