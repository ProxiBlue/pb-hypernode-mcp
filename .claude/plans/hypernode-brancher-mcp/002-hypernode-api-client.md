# Task 002: Hypernode REST API Client Wrapper

**Status**: completed
**Depends on**: 001
**Retry count**: 0

## Description
Build a thin HTTP client wrapping the Hypernode REST API (`https://api.hypernode.com/v2/...`), handling auth header injection (`Authorization: Token <token>`), JSON request/response, and error/timeout handling. All lifecycle tools (003-006) sit on top of this.

## Context
- No PHP/existing client library dependency — wrap REST directly per the original design decision.
- Auth: `Authorization: Token <HYPERNODE_API_TOKEN>` header on every request.
- Base URL: `https://api.hypernode.com/v2/`.
- Needs to support: POST (create), GET (list/detail), DELETE (delete) against `/app/<appname>/brancher/` and `/app/<appname>-eph<id>/` style endpoints.
- Should surface Hypernode API error responses (4xx/5xx) as a typed exception with the response body/status code, not swallow them.

## Requirements (Test Descriptions)
- [x] `it sends the Authorization Token header on every request`
- [x] `it raises a typed HypernodeApiError with status code and body on a 4xx response`
- [x] `it raises a typed HypernodeApiError on a 5xx response`
- [x] `it raises a timeout error when the request exceeds the configured timeout`
- [x] `it parses a successful JSON response into a plain dict`
- [x] `it constructs the correct URL for a given appname and sub-resource path`

## Acceptance Criteria
- All requirements have passing tests (mock HTTP layer — no real API calls in unit tests)
- Code follows code standards
- No decrease in test coverage

## Implementation Notes

Implemented `src/pb_hypernode_mcp/api_client.py`:

- `HypernodeApiClient(settings: Settings, *, base_url=BASE_URL, timeout=DEFAULT_TIMEOUT, transport=None)`
  — takes `Settings` from task 001's `config.py` as a constructor param (never reads env
  directly), keeping it testable via `httpx.MockTransport` injection.
- `HypernodeApiError(Exception)` — carries `status_code: int` and `body: str`; raised for any
  response with `status_code >= 400` (covers both 4xx and 5xx — same generic predicate, so the
  5xx test (req 3) passed immediately once the 4xx test (req 2) was implemented; noted as
  expected, not over-implementation, since `>= 400` is the natural minimal "is this an error"
  check, not something narrowed artificially to 4xx only).
- `HypernodeApiTimeoutError(Exception)` — raised when `httpx.TimeoutException` is caught around
  the request call.
- `get()`/`post()`/`delete()` all route through a shared `_request()` helper (extracted during
  REFACTOR) which builds the URL via `_build_url(appname, path)` →
  `{base_url}app/{appname}/{path}`, injects the `Authorization: Token <token>` header, and
  returns `response.json()` as a plain `dict[str, Any]` on success.
- Requirement 5 (JSON parsing into a dict) and requirement 6 (URL construction) both passed
  immediately on first run — already covered by the `get()` implementation driven out for
  requirement 1; noted per TDD process rather than adding redundant scaffolding.
- Added `post()` and `delete()` methods (with their own tests, not on the original 6-item
  checklist) beyond the strict requirement list — justified by the task's own Context section
  ("Needs to support: POST (create), GET (list/detail), DELETE (delete)") and because tasks
  003-006 (create/list/delete/ssh-info tools) depend on this client exposing all three verbs.
  8 tests total in `tests/test_api_client.py`.
- `ruff check`/`ruff format --check`/`pyright basic` all clean on `api_client.py` and
  `test_api_client.py`. One line (`test_it_raises_a_typed_hypernode_api_error_with_status_code_and_body_on_a_4xx_response`)
  needs `# noqa: E501` since the exact required test name alone exceeds the 100-char line
  limit even after `ruff format`'s auto-wrap.
- Full suite: 13 pre-existing + new tests pass. A 16th test in `tests/test_plugin_manifest.py`
  (README/plugin.json checks) is failing but belongs to unrelated, concurrently-in-progress
  work (not created or touched by this task) — out of scope for 002, left untouched.
