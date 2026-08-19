"""Thin HTTP client wrapping the Hypernode REST API.

Injects an `Authorization: Token <token>` header on every request, resolved
per-request from `Settings.token_for(appname)` since Hypernode API tokens
are scoped per Hypernode/app, not account-wide — there is no single token
that works for every app. Reads from a `Settings` instance (constructor
param, not re-reading env directly) so the client stays testable.
"""

from __future__ import annotations

from typing import Any

import httpx

from pb_hypernode_mcp.config import Settings

BASE_URL = 'https://api.hypernode.com/v2/'
DEFAULT_TIMEOUT = 30.0


class HypernodeApiError(Exception):
    """Raised when the Hypernode API returns an error (4xx/5xx) response."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body

        super().__init__(f'Hypernode API error {status_code}: {body}')


class HypernodeApiTimeoutError(Exception):
    """Raised when a request to the Hypernode API exceeds the configured timeout."""


class HypernodeApiClient:
    """Async client wrapping the Hypernode REST API."""

    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._base_url = base_url
        self._timeout = timeout
        self._transport = transport

    def _headers(self, token_appname: str) -> dict[str, str]:
        return {'Authorization': f'Token {self._settings.token_for(token_appname)}'}

    def _build_url(self, appname: str, path: str) -> str:
        """Build the full URL for `/app/<appname>/<path>`."""
        return f'{self._base_url}app/{appname}/{path}'

    def _build_raw_url(self, path: str) -> str:
        """Build the full URL for an arbitrary `<path>`, with no `/app/<appname>/` prefix.

        Some Brancher endpoints (e.g. `/v2/brancher/app/<appname>/`,
        `/v2/brancher/<name>/`) don't fit the `/app/<appname>/<path>` shape
        that every other Hypernode API resource uses — see `get_path`/
        `post_path`/`delete_path`.
        """
        return f'{self._base_url}{path}'

    async def _send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any] | None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
            try:
                response = await client.request(method, url, headers=headers, json=json)
            except httpx.TimeoutException as exc:
                raise HypernodeApiTimeoutError(str(exc)) from exc

            if response.status_code >= 400:
                raise HypernodeApiError(response.status_code, response.text)

            # VERIFIED (2026-08-19) against a live DELETE /v2/brancher/<name>/ call: a
            # successful delete returns an empty body (no JSON at all), while calling
            # delete again on an already-cancelled node returns a JSON *array* of
            # strings (not an object). `response.json()` on an empty body raises
            # json.JSONDecodeError ("Expecting value") -- guard against that here
            # rather than letting every raw-path caller reimplement the same check.
            if not response.text:
                return {}

            return response.json()

    async def _request(
        self,
        method: str,
        appname: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        token_appname: str | None = None,
    ) -> dict[str, Any]:
        return await self._send(
            method,
            self._build_url(appname, path),
            self._headers(token_appname if token_appname is not None else appname),
            json,
        )

    async def get(
        self,
        appname: str,
        path: str,
        *,
        token_appname: str | None = None,
    ) -> dict[str, Any]:
        """Perform a GET request against `/app/<appname>/<path>`.

        `token_appname` overrides which app's token authenticates the
        request when it differs from `appname` (e.g. a Brancher node's own
        URL segment vs. its parent app's configured token). Defaults to
        `appname`.
        """
        return await self._request('GET', appname, path, token_appname=token_appname)

    async def post(
        self,
        appname: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        token_appname: str | None = None,
    ) -> dict[str, Any]:
        """Perform a POST request against `/app/<appname>/<path>` to create a resource."""
        return await self._request('POST', appname, path, json=json, token_appname=token_appname)

    async def delete(
        self,
        appname: str,
        path: str,
        *,
        token_appname: str | None = None,
    ) -> dict[str, Any]:
        """Perform a DELETE request against `/app/<appname>/<path>` to remove a resource."""
        return await self._request('DELETE', appname, path, token_appname=token_appname)

    async def get_path(self, path: str, *, token_appname: str) -> dict[str, Any]:
        """Perform a GET request against the raw `<path>`, with no `/app/<appname>/` prefix.

        `token_appname` is required (no `appname`-derived default exists for
        a raw path) and is resolved via `Settings.token_for(token_appname)`,
        same as every other request method.
        """
        return await self._send(
            'GET', self._build_raw_url(path), self._headers(token_appname), None
        )

    async def post_path(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        token_appname: str,
    ) -> dict[str, Any]:
        """Perform a POST request against the raw `<path>`, with no `/app/<appname>/` prefix."""
        return await self._send(
            'POST', self._build_raw_url(path), self._headers(token_appname), json
        )

    async def delete_path(self, path: str, *, token_appname: str) -> dict[str, Any]:
        """Perform a DELETE request against the raw `<path>`, with no `/app/<appname>/` prefix."""
        return await self._send(
            'DELETE', self._build_raw_url(path), self._headers(token_appname), None
        )
