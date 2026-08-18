"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _isolated_hypernode_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip Hypernode env vars so tests never pick up the real shell environment.

    pydantic-settings merges a dict-typed field across sources rather than letting an
    explicit constructor kwarg fully override the environment value -- a test that does
    Settings(hypernode_api_tokens={...}) will silently gain whatever real apps are
    configured in HYPERNODE_API_TOKENS on the host/container running the suite unless
    that var is cleared first.
    """
    monkeypatch.delenv('HYPERNODE_API_TOKENS', raising=False)
    yield
