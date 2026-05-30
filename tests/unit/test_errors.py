"""Smoke tests for the internal exception hierarchy."""
import pytest

from autopsy.core.errors import (
    AutopsyError,
    StoreError,
    UnknownSchemaVersionError,
    WriterError,
)


def test_all_subclass_autopsy_error():
    for cls in (StoreError, WriterError, UnknownSchemaVersionError):
        assert issubclass(cls, AutopsyError)


def test_unknown_schema_version_message():
    e = UnknownSchemaVersionError(7, "/some/path")
    assert "7" in str(e)
    assert "autopsy migrate" in str(e)


def test_can_be_raised_and_caught():
    with pytest.raises(AutopsyError):
        raise WriterError("queue dead")
