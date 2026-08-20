"""Shared validation guards for Brancher tool node-name inputs.

Node names follow Hypernode's Brancher naming convention `<appname>-eph<id>`
(e.g. `pps-eph123456`). This module is the single source of truth for that
validation so every tool that accepts a node name (ssh_info, exec, put, ...)
enforces the same hard guard rather than reimplementing the regex.

VERIFIED (2026-08-19): the `-eph<id>` suffix is lowercase-alphanumeric, not
digit-only — both a real account's node (`ppsdev-ephp8b5c2`, suffix
`p8b5c2`) and the official `ByteInternet/hypernode-api-python` docs' own
examples (`yourappname-ephoj82yb`, suffix `oj82yb`) show alphanumeric
suffixes. A digit-only regex rejected the real node's own name when this
plugin tried to delete it through `brancher_delete`.
"""

from __future__ import annotations

import re

# VERIFIED (2026-08-20) via a real interactive session: `ssh app@<node>.hypernode.io`
# connects immediately. Hypernode's SSH login user is the fixed string `app`
# on every Hypernode node (Brancher nodes included) — it is NOT the node's
# own name. Every tool that opens an SSH/rsync connection to a Brancher node
# must use this constant as the login user, never `node_name` itself.
HYPERNODE_SSH_USER = 'app'

_EPH_NODE_NAME_PATTERN = re.compile(r'^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?-eph[a-z0-9]+$')
_APPNAME_FROM_NODE_NAME_PATTERN = re.compile(r'^(?P<appname>.+)-eph[a-z0-9]+$')


class InvalidNodeNameError(ValueError):
    """Raised when a node name does not match the Brancher `<appname>-eph<id>` pattern."""


def is_eph_node_name(name: str) -> bool:
    """Return True if `name` matches the Brancher `<appname>-eph<id>` naming pattern."""
    return bool(_EPH_NODE_NAME_PATTERN.fullmatch(name))


def validate_eph_node_name(name: str) -> None:
    """Raise `InvalidNodeNameError` if `name` does not match the Brancher naming pattern."""
    if not is_eph_node_name(name):
        raise InvalidNodeNameError(
            f'{name!r} is not a valid Brancher node name. '
            "Expected the '<appname>-eph<id>' pattern, e.g. 'pps-eph123456'."
        )


def appname_from_node_name(node_name: str) -> str:
    """Derive the parent `<appname>` from a validated `<appname>-eph<id>` node name.

    Hypernode API tokens are scoped per parent app, not per Brancher node —
    callers that need to resolve the correct token for a node (rather than
    the node's own URL segment) use this to get the key that actually exists
    in `HYPERNODE_API_TOKENS`. Call `validate_eph_node_name(node_name)` first;
    this assumes `node_name` already matches the `-eph<id>` pattern.
    """
    match = _APPNAME_FROM_NODE_NAME_PATTERN.match(node_name)
    assert match is not None  # validated by validate_eph_node_name before this is called

    return match.group('appname')
