# Task 020: Fix Brancher Endpoints, Response Shapes, and Node-Name Regex

**Status**: completed
**Depends on**: 019
**Retry count**: 0

## Description
A real end-to-end spin-up against `ppsdev` got further than before (task 019's plan-eligibility fix worked) but still failed, and in the process created a real, cost-accruing orphaned node (`ppsdev-ephp8b5c2`, manually deleted via the Hypernode dashboard since our own `brancher_delete` tool rejected its name). Root-caused via two independent, verified sources — a live `curl` against the account's own Brancher list endpoint, and the official `ByteInternet/hypernode-api-python` client library source (`hypernode_api_python/client.py`) fetched from GitHub — not guessing this time.

**Confirmed real facts (cite these, do not re-derive):**

1. **Wrong endpoints entirely.** This codebase's `brancher_list`/`brancher_create` hit `GET`/`POST /v2/app/<appname>/brancher/` (confirmed this endpoint DOES still work but returns a deprecation warning: `"This endpoint has been deprecated and will be removed in a future version. Please use the new endpoint instead: /v2/brancher/app/ppsdev/"`). The official client library confirms the real, non-deprecated endpoints:
   - List: `GET /v2/brancher/app/{app_name}/`
   - Create: `POST /v2/brancher/app/{app_name}/`
   - Destroy: `DELETE /v2/brancher/{brancher_name}/` — note this is a **different top-level path** (`/v2/brancher/<name>/`, not nested under `/v2/app/`).
   (Source: `HYPERNODE_API_BRANCHER_APP_ENDPOINT = "/v2/brancher/app/{}/"`, `HYPERNODE_API_BRANCHER_ENDPOINT = "/v2/brancher/{}/"` in the official client's `client.py`.)

2. **List response shape.** Live curl against `GET /v2/app/ppsdev/brancher/` (the deprecated but still-working endpoint, same shape as the new one) returned:
   ```json
   {"monthly_total_time":332,"total_minutes_elapsed":6,"actual_monthly_total_cost":6,"monthly_total_cost":0,"currency":"EUR","price_per_minute":1,"branchers":[{"id":33358,"name":"ppsdev-ephp8b5c2","cost":6,"created":"2026-08-19T12:27:14.791544Z","ip":null,"end_time":null,"elapsed_time":332,"labels":{"test1":null}}]}
   ```
   The list is under a top-level `branchers` key (this codebase currently reads `nodes`, which does not exist). Each entry has `name`, `ip` (null until ready), `created`, `elapsed_time` (wall-clock **seconds** since creation — 332 here corresponds to roughly 5.5 real minutes elapsed, not 332 minutes), and `cost` (minutes billed, given the envelope's `price_per_minute: 1`). There is **no `host` field** — must be derived as `f"{name}.hypernode.io"`. There is **no `minutes` field** — derive as `elapsed_time // 60` (or keep `elapsed_time` as the source of truth and rename the tool's own field — your call on exact field naming in the returned dict, but `cleanup_logic.py`'s `flag_stale_nodes(nodes, threshold_minutes=...)` threshold comparison must keep working against whatever field name is chosen).

3. **Create response shape.** Official client's own docstring example (verified against the official library, not this codebase's guess):
   ```json
   {"name": "yourappname-ephoj82yb", "parent": "yourappname", "type": "brancher", "product": "FALCON_M_202203", "domainname": "yourappname-ephoj82yb.hypernode.io", "..." : "..."}
   ```
   The node-name field is `name`, not `appname` (this codebase's `create_brancher_node` currently does `response.get('appname')`, which is why the real spin-up got `node_name: None` and then failed waiting for `None` to become SSH-reachable — the actual node it half-created was fine, the code just couldn't see its own name).

4. **Brancher IDs are alphanumeric, not numeric-only.** Both the live account's real node (`ppsdev-ephp8b5c2`, suffix `p8b5c2`) and the official docs' own examples (`yourappname-ephoj82yb`, suffix `oj82yb`) show lowercase-alphanumeric suffixes after `-eph`. This codebase's `_guards.py` regex (`-eph[0-9]+$`, digits only) is too strict and rejected our own real node's name when we tried to delete it through the tool — this is the guard that's supposed to make deletion/exec/put safe, and it was actively getting in the way of cleaning up a real orphaned resource.

5. **`brancher_ssh_info`'s field name is also wrong.** It reads `detail.get('ip_address')` to decide node-readiness; the real field (confirmed via live curl on `GET /v2/app/ppsdev/`) is `ip`, not `ip_address`.

6. **Timeout note (do not silently "fix" without evidence):** the failed node's `ip` was still `null` when checked well after the 300s reachability timeout had already elapsed. This might mean 300s is genuinely too short for a first-time create, or might be specific to this one attempt. Do not change `NodeUnreachableTimeoutError`'s default timeout in this task — just note in Implementation Notes that it's worth watching after the endpoint fixes land, since the reachability check itself was also polling the wrong thing (it likely used `exec_command` against a node whose name it didn't even have correctly, per point 3 above) and needs to be re-evaluated with correct node names before concluding anything about the real timeout requirement.

## Context

**`src/pb_hypernode_mcp/api_client.py`** currently only exposes `get`/`post`/`delete` that always build `{base_url}app/{appname}/{path}`. Brancher's real endpoints don't fit that shape (list/create are `brancher/app/{appname}/`, delete is `brancher/{name}/` — neither is `app/{appname}/...`). Add a way to hit an arbitrary path without the `app/<appname>/` prefix assumption — e.g. new `get_path`/`post_path`/`delete_path` methods (or refactor `_build_url`/`_request` to take a full path plus a separate `token_appname` for auth — your call on exact shape, but keep the existing `get`/`post`/`delete` methods and their `/app/<appname>/<path>` behavior intact since `brancher_create`'s plan-eligibility GET and `brancher_ssh_info`'s node-detail GET both correctly use that shape already and must keep working).

**Files to fix:**
- `src/pb_hypernode_mcp/tools/brancher_list.py` — endpoint (`brancher/app/{appname}/` via the new raw-path client method), response key (`branchers` not `nodes`), field mapping (`host` derived from `name`, minutes derived from `elapsed_time`).
- `src/pb_hypernode_mcp/tools/brancher_create.py` — endpoint for the actual create POST (`brancher/app/{appname}/` via the new raw-path client method — the plan-eligibility GET stays on the existing `app/<appname>/` shape, unchanged), node-name field (`name` not `appname`).
- `src/pb_hypernode_mcp/tools/brancher_delete.py` — endpoint (`brancher/{node_name}/` via the new raw-path client method, NOT nested under `app/`).
- `src/pb_hypernode_mcp/tools/brancher_ssh_info.py` — field name (`ip` not `ip_address`).
- `src/pb_hypernode_mcp/tools/_guards.py` — broaden the `-eph<id>` suffix from `[0-9]+` to an alphanumeric class (e.g. `[a-z0-9]+`) in both `_EPH_NODE_NAME_PATTERN` and `_APPNAME_FROM_NODE_NAME_PATTERN`. Keep the guard's actual safety property intact (must still reject production-shaped hostnames like `pps`, `pps.hypernode.io`, `pps-staging`) — only the ID-suffix charset changes, not the overall structural requirement.
- `src/pb_hypernode_mcp/cleanup_logic.py` — check `flag_stale_nodes()`'s threshold comparison still works against whatever field name `brancher_list.py` ends up using for minutes; update if the field was renamed.

**Tests:** every existing test mocking the old `/app/<appname>/brancher/` endpoint, `{'nodes': [...]}` shape, `appname` create-response key, `ip_address` field, or digit-only `-eph` IDs needs updating to the real shapes documented above. Add new test coverage for: alphanumeric `-eph` IDs being accepted, the new raw-path client methods hitting the correct URLs, and the corrected response-field parsing in list/create/ssh_info.

**Docs:** update README's "Unverified API response shapes" bullet — these are now VERIFIED (cite the official `ByteInternet/hypernode-api-python` library and a live account curl as the sources), not just corrected guesses. Update any docstring in the affected files that still says "ASSUMPTION (unverified)" once the real shape is confirmed and coded against.

## Requirements (Test Descriptions)
- [x] `it lists brancher nodes via the non-deprecated brancher/app/appname endpoint`
- [x] `it parses the branchers key from the list response, not nodes`
- [x] `it derives host from the node name since the API does not return one directly`
- [x] `it creates a brancher node via the non-deprecated brancher/app/appname endpoint`
- [x] `it reads the node name from the name field in the create response, not appname`
- [x] `it deletes a brancher node via the brancher/name endpoint, not nested under app`
- [x] `it reads node readiness from the ip field, not ip_address`
- [x] `it accepts an alphanumeric eph id suffix, not just digits`
- [x] `it still rejects a production-shaped hostname despite the broadened id charset`

## Acceptance Criteria
- [x] All requirements have passing tests
- [x] Full suite (`uv run pytest -v`) passes — every stale mock (deprecated endpoint, `nodes` key, `appname` create field, `ip_address` field, digit-only eph IDs) updated across the whole test suite (111 passed)
- [x] `ruff check`/`ruff format --check`/`pyright` clean
- [x] README's unverified-shapes bullet updated to reflect what's now confirmed, citing the official Python client library and a live curl as sources
- [x] `cleanup_logic.py`/`brancher-cleanup` skill still function correctly against whatever field name change was made to `brancher_list`'s minutes value

## Implementation Notes

**`api_client.py`**: added `get_path`/`post_path`/`delete_path` (require `token_appname` explicitly — no `appname`-derived default exists for a raw path) alongside the existing `get`/`post`/`delete`. Refactored the shared low-level dispatch into a new `_send()` helper so both the `/app/<appname>/<path>` methods and the new raw-path methods share one request/error/timeout code path. `get`/`post`/`delete` and their URL shape are unchanged.

**`brancher_list.py`**: now calls `client.get_path(f'brancher/app/{appname}/', token_appname=appname)`, reads the `branchers` key, derives `host` as `f"{name}.hypernode.io"` and `minutes` as `elapsed_time // 60`. Kept the returned dict's field name as `minutes` (not renamed) specifically so `cleanup_logic.py::flag_stale_nodes()` and its threshold comparison needed zero changes.

**`brancher_create.py`**: the plan-eligibility GET (`client.get(appname, '')`) is unchanged, per the task's explicit instruction. The actual create POST now goes through `client.post_path(f'brancher/app/{appname}/', json=body, token_appname=appname)` and reads `response.get('name')` instead of `response.get('appname')`.

**`brancher_delete.py`**: now calls `client.delete_path(f'brancher/{node_name}/', token_appname=appname)` — a different top-level path than list/create, not nested under `/app/`.

**`brancher_ssh_info.py`**: reads `detail.get('ip')` instead of `detail.get('ip_address')`.

**`_guards.py`**: broadened `_EPH_NODE_NAME_PATTERN` and `_APPNAME_FROM_NODE_NAME_PATTERN` from `-eph[0-9]+$` to `-eph[a-z0-9]+$`. Verified the guard's safety property is intact — `pps`, `pps.hypernode.io`, and `pps-staging` are all still rejected (no `-eph<id>` suffix at all, so the broadened charset doesn't touch them).

**`cleanup_logic.py`**: no code change needed — `brancher_list.py` kept the `minutes` field name, so `flag_stale_nodes()`'s `node['minutes'] >= threshold_minutes` comparison keeps working unmodified. Verified via the existing `test_cleanup_logic.py` suite (updated to the new `branchers`/`elapsed_time` request-mock shape) all passing.

**Tests updated**: `tests/test_api_client.py` (3 new tests for `get_path`/`post_path`/`delete_path`), `tests/tools/test_brancher_list.py`, `tests/tools/test_brancher_create.py`, `tests/tools/test_brancher_delete.py`, `tests/tools/test_brancher_ssh_info.py`, `tests/tools/test_guards.py`, `tests/tools/test_brancher_spinup_flow.py`, `tests/test_cleanup_logic.py`, `tests/test_server.py` (its `FakeApiClient` monkeypatches the whole `HypernodeApiClient` class, so it needed `get_path`/`post_path`/`delete_path` added and its fixture data updated to `branchers`/`name`/`ip`). Full suite: 111 passed (99 original + 12 new), `ruff check`/`ruff format --check`/`pyright` all clean.

**README.md**: replaced the "unverified assumption" language for `brancher_list`'s response shape with a new bullet under Limitations documenting the now-VERIFIED endpoints, response shapes, and node-name ID charset, citing both the live curl and the official `ByteInternet/hypernode-api-python` client library as sources.

**Docstrings**: `brancher_list.py`'s module docstring, `brancher_create.py`'s return-value comment, `brancher_ssh_info.py`'s readiness check, and `_guards.py`'s module docstring were all updated from "assumption (unverified)" framing to "VERIFIED (2026-08-19)" framing with the concrete source cited inline.

**Point 6 (timeout) — explicitly NOT changed**, per task instruction. Flagging for follow-up: `NodeUnreachableTimeoutError`'s default 300s reachability timeout was observed to still be exceeded on a real first-time create attempt, but that attempt was running against a node name that `create_brancher_node` couldn't see correctly (task 019/020's `response.get('appname')` bug, now fixed here). The reachability wait needs to be re-evaluated against a real spin-up now that `node_name` resolves correctly before drawing any conclusion about whether 300s itself is too short — out of scope for this task.
