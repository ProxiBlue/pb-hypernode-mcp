---
name: brancher-preview
description: Full Brancher preview loop — create a node, apply AI-assisted changes over SSH, build, and view the result via browser MCP, then remind to clean up. Use when a client wants an end-to-end look at a change on a disposable prod-clone environment.
---

# Brancher Preview

The full spin-up -> change -> build -> view loop: create a sanitized node,
apply a code change to it (two supported patterns), run the Magento build
commands the change actually needs, look at the result with a browser, and
end with an explicit reminder that the node is still billing Brancher
minutes. This skill does not delete the node itself — that is
`brancher-cleanup`'s job, or an explicit follow-up `brancher_delete` call.

## Flow

1. **Identify which Hypernode/app, then spin up the node.** Follow the
   `brancher-spinup` skill exactly, starting with its own first step: if the
   user's request doesn't say which app to target, call `brancher_apps`
   first, show the configured list, and ask before calling any other tool
   (never guess an `appname`; if exactly one app is configured, proceed with
   it and just note that). Then continue the `brancher-spinup` flow (ask for
   a label if missing, call `brancher_create`, report `node_name`,
   `access_url`, `admin_url` with its login (`admin_username`/`admin_email`
   + `admin_password_note`), `status`, `sanitization_commands_run`, and an
   explicit `sales_and_customer_data_sanitized` confirmation —
   `minutes_remaining` is always `None`; see the `brancher-spinup` skill for
   why, and don't report it as if it were meaningful data). The wait itself is two
   separately-timed phases (ip-assignment, then SSH-reachability); on
   success report the `ip_assigned_after_seconds`/`ssh_reachable_after_seconds`
   split too when it's notably uneven, and see `brancher-spinup`'s Errors
   section for how to tell the two distinct timeout failure modes apart
   (`NodeIpNeverAssignedError` vs `NodeUnreachableTimeoutError`) if spin-up
   fails here.
   Do not reimplement or shortcut that create -> wait -> sanitize -> ready
   sequence here — reuse it as a step. Nothing in this skill proceeds until
   `brancher_create` reports `status: "ready"`.

   Because `brancher_create` can take up to ~20 minutes, this step inherits
   `brancher-spinup`'s guidance: run it via a background Agent/Task call
   rather than blocking inline, on the cheapest available model (e.g.
   Haiku — the agent is just making one deterministic tool call, not doing
   any real reasoning), tell the user you're doing so, and only continue to
   steps 2-5 of this loop once the background agent reports the node ready.

2. **Apply the change.** Two patterns, pick the one that matches what the
   user asked for:

   - **Push an existing local change** ("test my branch/working copy on a
     preview node"): call `brancher_put(node_name, local_path, remote_path)`
     for each local file/directory that needs to land on the node. This is
     the `put_files` step (`src/pb_hypernode_mcp/preview_logic.py`'s
     `apply_local_change` wraps exactly this call) — rsync's the local path
     up over the same SSH connection model as every other Brancher tool.
   - **Quick experiment authored in-session** ("try changing X and show me"):
     edit the file directly on the node with `brancher_exec(node_name,
     command)`, e.g. writing a file with a heredoc, or an in-place `sed`.
     Only ever target the `-eph` node returned by spin-up — never a
     production host.

   Both patterns can be combined in one preview loop (e.g. push a local
   patch, then also tweak a config value over `brancher_exec`).

3. **Run the Magento build sequence.** After changes are applied, decide
   which build commands are actually needed — do not always run the full
   heavy sequence. The decision logic is a tested pure function,
   `decide_build_commands(changed_paths)` in
   `src/pb_hypernode_mcp/preview_logic.py` (unit-tested in
   `tests/test_preview_logic.py`):

   - **Always**: `bin/magento cache:flush`.
   - **`bin/magento setup:upgrade`** — only if a changed path contains
     `db_schema.xml` or `module.xml` (schema change or module
     enable/disable).
   - **`bin/magento setup:di:compile`** — only if a changed path contains
     `di.xml`.
   - **`bin/magento setup:static-content:deploy -f`** — only if a changed
     path looks like a frontend asset/template (`.phtml`, `.css`, `.js`, a
     `/web/` path, or a `view/frontend`/`view/adminhtml` path).

   Run each decided command in order via `brancher_exec(node_name, command)`.
   This mirrors `run_build_sequence()` in `preview_logic.py`, which composes
   `decide_build_commands()` with a sequence of `exec_command` calls — use it
   as the source of truth for the expected command list and call order, even
   though this skill drives the actual turn-by-turn `brancher_exec` calls.

4. **View the result.** Use whatever browser MCP tool is already available
   in this Claude Code session (e.g. `claude-in-chrome`, `chrome-devtools`,
   or an equivalent) to open/screenshot the node's `access_url` from step 1.
   This skill does not install or wrap a screenshot tool of its own — it
   just points the existing browser MCP at the Brancher URL and shows the
   user what changed. If no browser MCP tool is available in the current
   session, say so plainly and give the user the `access_url` to check
   manually instead of failing silently.

5. **Remind the user the node is still running.** Always end the loop with
   an explicit reminder — never let the conversation move on silently. Use
   `cleanup_reminder(node_name, access_url)` from `preview_logic.py` as the
   reference wording:

   > Node '`node_name`' (`access_url`) is still running and consuming
   > Brancher minutes. Delete it with `brancher_delete` when you're done
   > previewing, or run the `brancher-cleanup` skill later.

   This reminder is required after every preview loop, whether the user
   looked satisfied with the result or not — the node keeps billing minutes
   regardless. Never call `brancher_delete` automatically as part of this
   skill; deletion is always a separate, explicit action.

## Example

```
User: "Spin up a preview of myapp for ticket-482, push my local branch's
       changes to the checkout template, and show me how it looks."

1. brancher_create(appname="myapp", labels=["ticket-482"]) ->
   { node_name: "myapp-eph198234", access_url: "https://myapp-eph198234.hypernode.io/",
     admin_url: "https://myapp-eph198234.hypernode.io/admin", admin_username: "admin",
     admin_email: "admin@example.invalid", minutes_remaining: None, status: "ready",
     sanitization_commands_run: 16, sales_and_customer_data_sanitized: True,
     ip_assigned_after_seconds: 360, ssh_reachable_after_seconds: 40 }

2. brancher_put(node_name="myapp-eph198234",
     local_path="app/design/frontend/Uptactics/pps/templates/checkout/summary.phtml",
     remote_path="/data/web/public/app/design/frontend/Uptactics/pps/templates/checkout/summary.phtml")

3. Changed path is a .phtml under app/design -> decide_build_commands() ->
   ["bin/magento cache:flush", "bin/magento setup:static-content:deploy -f"]
   Run both via brancher_exec.

4. Open https://myapp-eph198234.hypernode.io/checkout/ with the session's
   browser MCP tool and screenshot the checkout summary.

5. Report: "Preview ready at https://myapp-eph198234.hypernode.io/. Node
   'myapp-eph198234' is still running and consuming Brancher minutes —
   delete it with brancher_delete when you're done previewing, or run
   brancher-cleanup later."
```

## Implementation notes (for maintainers, not the AI reading this at runtime)

The two pieces of real decision logic in this loop are extracted into
`src/pb_hypernode_mcp/preview_logic.py` and unit-tested directly in
`tests/test_preview_logic.py`, rather than left as unverified prose:

- `decide_build_commands(changed_paths)` — pure function, the build-command
  selection rules from step 3 above.
- `apply_local_change(node_name, local_path, remote_path, *, put_files)` —
  thin async wrapper around `brancher_put`'s `put_files`, kept as its own
  call site so it's independently testable with a fake `put_files`.
- `run_build_sequence(node_name, changed_paths, *, exec_command)` — composes
  `decide_build_commands()` with a sequence of `exec_command` calls and
  aggregates the per-command results.
- `cleanup_reminder(node_name, access_url)` — pure function producing the
  step-5 reminder text.

The screenshot step (this skill's step 4) has no Python surface in this
plugin and is not unit-tested — it is a direct instruction to Claude to
invoke whichever browser MCP tool is already present in the client's own
session against `access_url`. Verified manually: ran the loop end-to-end
against a real Brancher node with `claude-in-chrome` installed, confirmed
the screenshot step correctly opened `access_url` and captured the changed
page. No automated test exists for this step since it depends on a tool
this plugin does not own, control, or mock — per `.claude/testing.md`'s
guidance to document manual verification instead of forcing a weak/fake
automated test.
