"""Tests for the shared `-eph` node-name validation guard."""

from __future__ import annotations

import pytest

from pb_hypernode_mcp.tools._guards import (
    InvalidNodeNameError,
    appname_from_node_name,
    validate_eph_node_name,
)


def test_it_rejects_a_node_name_with_a_trailing_newline_regex_fullmatch_not_partial_match() -> None:
    with pytest.raises(InvalidNodeNameError):
        validate_eph_node_name('pps-eph123456\n')


def test_it_derives_the_parent_appname_from_a_valid_eph_node_name() -> None:
    assert appname_from_node_name('pps-eph123456') == 'pps'


def test_it_accepts_an_alphanumeric_eph_id_suffix_not_just_digits() -> None:
    """Both the live account's real node (`ppsdev-ephp8b5c2`, suffix `p8b5c2`) and the
    official `ByteInternet/hypernode-api-python` docs' own examples
    (`yourappname-ephoj82yb`, suffix `oj82yb`) show lowercase-alphanumeric `-eph`
    suffixes, not digit-only ones."""
    validate_eph_node_name('ppsdev-ephp8b5c2')
    validate_eph_node_name('yourappname-ephoj82yb')

    assert appname_from_node_name('ppsdev-ephp8b5c2') == 'ppsdev'


def test_it_still_rejects_a_production_shaped_hostname_despite_the_broadened_id_charset() -> None:
    """Broadening the `-eph<id>` charset to alphanumeric must not weaken the guard's
    actual safety property: production-shaped hostnames with no `-eph<id>` suffix at
    all must still be rejected."""
    for hostname in ('pps', 'pps.hypernode.io', 'pps-staging'):
        with pytest.raises(InvalidNodeNameError):
            validate_eph_node_name(hostname)
