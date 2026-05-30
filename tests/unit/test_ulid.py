"""Unit tests for the ULID generator."""
import re
import time

from autopsy.core.ulid import new_ulid

ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_ulid_is_26_chars_crockford_base32():
    u = new_ulid()
    assert ULID_PATTERN.match(u), f"not a valid ULID: {u}"


def test_ulids_are_unique_within_same_millisecond():
    ids = {new_ulid() for _ in range(1000)}
    assert len(ids) == 1000


def test_ulids_are_monotonically_increasing_in_time():
    a = new_ulid()
    time.sleep(0.002)
    b = new_ulid()
    assert a < b, "expected lexicographic ordering by time"


def test_ulids_within_same_ms_preserve_monotonicity():
    ids = [new_ulid() for _ in range(500)]
    assert ids == sorted(ids), "ULIDs minted in the same ms must stay ordered"
