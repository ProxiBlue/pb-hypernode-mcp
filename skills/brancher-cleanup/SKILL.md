---
name: brancher-cleanup
description: List and delete stale Hypernode Brancher preview nodes, reporting wall-clock minutes used. Use when a client wants to check for or remove leftover Brancher nodes to stop minute accrual.
---

# Brancher Cleanup

Brancher nodes bill wall-clock minutes from creation regardless of whether
anyone is actively using them — an idle node still burns the app's Brancher
minute allowance. This skill finds nodes that have been alive past a
configurable age threshold and removes them, safely.

## Age threshold

Default: **240 minutes (4 hours)** — the sample threshold used in
Hypernode's own Brancher documentation. It is only a starting point:

- Ask the user for a threshold if they haven't given one, but default to 240
  minutes if they have no preference.
- A shorter threshold (e.g. 60 minutes) is appropriate for a team that spins
  up short-lived preview nodes throughout the day and forgets to close them.
- A longer threshold (e.g. 480 minutes / 8 hours) is appropriate if nodes
  routinely stay open across a working day for review.

The actual "is this node past the threshold" decision is NOT prose — it is
the pure function `flag_stale_nodes(nodes, threshold_minutes)` in
`src/pb_hypernode_mcp/cleanup_logic.py` (unit-tested in
`tests/test_cleanup_logic.py`). Conceptually: a node is flagged when its
`minutes` value is `>= threshold_minutes`. When calling the MCP tools below,
apply that same `>=` rule when deciding what to show the user as "flagged".

## Flow

1. **List.** Call `brancher_list` with the app name. Each node returned has
   `name`, `host`, and `minutes` (wall-clock minutes alive, not idle-aware).

2. **Report full list with minutes.** Show the user every active node and
   its `minutes` value, so they can see the cost being avoided by cleanup —
   not just the flagged subset.

3. **Flag.** Apply the age-threshold rule (`minutes >= threshold_minutes`,
   same logic as `flag_stale_nodes`) to the list from step 1.

   - If **no** nodes are flagged, tell the user there is nothing to clean up
     (name every node and its `minutes` so they can see why none qualified)
     and stop here. Do not call `brancher_delete`.
   - If one or more nodes are flagged, list them with their `minutes` and
     move to step 4.

4. **Choose single vs. bulk.**

   - **Single-node**: user wants to review/delete one flagged node at a
     time. Go to step 5 for that one node.
   - **Bulk**: user wants every flagged node gone in one pass. Go to step 6.

5. **Single-node delete (confirm-before-delete).**

   a. Call `brancher_delete` with `node_name` set and `confirm` omitted
      (defaults to `False`). This returns the target node's details
      (`host`, `minutes`) and a message asking for confirmation — it does
      **not** delete anything yet.
   b. Show that detail to the user and ask them to confirm.
   c. Only on explicit user confirmation, call `brancher_delete` again with
      the same `node_name` and `confirm: True`. This issues the actual
      deletion.
   d. Repeat a-c for each additional node the user wants removed one at a
      time.

6. **Bulk delete (confirm-before-delete-all).**

   a. Present the full flagged list (name, host, minutes) as the delete
      plan and ask the user to confirm deleting all of them in one pass.
   b. Only on explicit confirmation, delete each flagged node in turn by
      calling `brancher_delete` with `confirm: True` for each `node_name` in
      the flagged list. (Do not call the unconfirmed preview form per-node
      here — the bulk plan shown in step 6a already served that purpose;
      re-confirming per-node would just repeat the same question.)
   c. Report back which nodes were deleted.

   This mirrors `cleanup_stale_nodes()` in `cleanup_logic.py`: given
   `confirm=False` it returns the flagged set without deleting anything;
   given `confirm=True` it deletes every flagged node and returns the
   deleted names. That function exists as the tested reference
   implementation of this bulk flow — use it as the source of truth for the
   expected call sequence, even though the skill itself drives the actual
   MCP tool calls turn-by-turn.

## Never skip confirmation

`brancher_delete` is destructive and irreversible. Never call it with
`confirm: True` without an explicit, current-turn "yes, delete it" /
"yes, delete them all" from the user — a threshold being configured, or a
node simply being flagged, is not itself confirmation to delete.

## Example

```
User: "Check for stale Brancher nodes on myapp and clean them up."

1. brancher_list(appname="myapp") ->
   [{"name": "myapp-eph1", "host": "myapp-eph1.hypernode.io", "minutes": 12},
    {"name": "myapp-eph2", "host": "myapp-eph2.hypernode.io", "minutes": 300}]

2. Report both nodes and their minutes to the user.

3. Flag (threshold 240): myapp-eph2 (300 >= 240). myapp-eph1 (12 < 240) is not flagged.

4. Ask user: single-node or bulk? User says "just delete it."

5. brancher_delete(node_name="myapp-eph2") -> confirm_required, shows
   host/minutes. Ask user to confirm.

6. User confirms. brancher_delete(node_name="myapp-eph2", confirm=True) ->
   deleted.

7. Report: "Deleted myapp-eph2 (was alive 300 minutes). myapp-eph1 (12
   minutes) is under the 240-minute threshold and was left running."
```
