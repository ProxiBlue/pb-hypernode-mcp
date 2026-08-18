"""Shared validation guards for Brancher tool node-name inputs.

Node names follow Hypernode's Brancher naming convention `<appname>-eph<id>`
(e.g. `pps-eph123456`). This module is the single source of truth for that
validation so every tool that accepts a node name (ssh_info, exec, put, ...)
enforces the same hard guard rather than reimplementing the regex.
"""

from __future__ import annotations

import re

_EPH_NODE_NAME_PATTERN = re.compile(r'^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?-eph[0-9]+$')


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
