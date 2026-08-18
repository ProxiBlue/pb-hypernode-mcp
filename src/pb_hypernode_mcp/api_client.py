"""Thin HTTP client wrapping the Hypernode REST API.

Injects the `Authorization: Token <HYPERNODE_API_TOKEN>` header on every
request. Reads the token from a `Settings` instance (constructor param, not
re-reading env directly) so the client stays testable.
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

    def _headers(self) -> dict[str, str]:
        return {'Authorization': f'Token {self._settings.hypernode_api_token}'}

    def _build_url(self, appname: str, path: str) -> str:
        """Build the full URL for `/app/<appname>/<path>`."""
        return f'{self._base_url}app/{appname}/{path}'

    async def _request(
        self,
        method: str,
        appname: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
            try:
                response = await client.request(
                    method,
                    self._build_url(appname, path),
                    headers=self._headers(),
                    json=json,
                )
            except httpx.TimeoutException as exc:
                raise HypernodeApiTimeoutError(str(exc)) from exc

            if response.status_code >= 400:
                raise HypernodeApiError(response.status_code, response.text)

            return response.json()

    async def get(self, appname: str, path: str) -> dict[str, Any]:
        """Perform a GET request against `/app/<appname>/<path>`."""
        return await self._request('GET', appname, path)

    async def post(
        self,
        appname: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a POST request against `/app/<appname>/<path>` to create a resource."""
        return await self._request('POST', appname, path, json=json)

    async def delete(self, appname: str, path: str) -> dict[str, Any]:
        """Perform a DELETE request against `/app/<appname>/<path>` to remove a resource."""
        return await self._request('DELETE', appname, path)
