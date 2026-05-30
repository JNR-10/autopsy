"""Internal exception types for the capture layer.

These are never re-raised across the autopsy/host boundary. They exist so
internal call sites can be explicit about what they expect to handle, and
so unit tests can pin down the failure mode.

User-facing failures are surfaced via stdlib `logging` and the manifest's
`status` field, never by raising into the host process.
"""
from __future__ import annotations


class AutopsyError(Exception):
    """Base class for all autopsy-internal exceptions."""


class StoreError(AutopsyError):
    """The on-disk store could not satisfy a read or write."""


class WriterError(AutopsyError):
    """The writer thread or queue is in a non-recoverable state."""


class RedactorError(AutopsyError):
    """A user-supplied redactor raised; the event is dropped fail-closed."""


class UnknownSchemaVersionError(AutopsyError):
    """A manifest carries a newer autopsy_format_version than we understand."""

    def __init__(self, version: int, path: str):
        super().__init__(
            f"autopsy: unknown autopsy_format_version={version} at {path}. "
            f"Run 'autopsy migrate {path}' (not yet implemented in v1)."
        )
        self.version = version
        self.path = path
