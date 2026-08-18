"""Tests for the shared `-eph` node-name validation guard."""

from __future__ import annotations

import pytest

from pb_hypernode_mcp.tools._guards import InvalidNodeNameError, validate_eph_node_name


def test_it_rejects_a_node_name_with_a_trailing_newline_regex_fullmatch_not_partial_match() -> None:
    with pytest.raises(InvalidNodeNameError):
        validate_eph_node_name('pps-eph123456\n')
